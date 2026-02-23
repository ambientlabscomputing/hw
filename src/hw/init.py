"""Initialization command for setting up hw CLI dependencies."""

import shutil
import subprocess

import click

# Non-Python dependencies required by hw
NPX_PACKAGES: list[str] = []  # cached individually below

UVX_PACKAGES: list[str] = []  # no uvx packages needed currently


def _check_command(cmd: str) -> bool:
    """Check whether a shell command is available."""
    return shutil.which(cmd) is not None


def _run_quietly(args: list[str]) -> tuple[int, str]:
    """Run a command and return (exit_code, combined_output)."""
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.returncode, result.stdout


def _print_ok(msg: str) -> None:
    click.echo(f"  ✓ {msg}")


def _print_fail(msg: str) -> None:
    click.echo(f"  ✗ {msg}", err=True)


def _check_npx() -> bool:
    """Check whether npx is available and print status."""
    if not _check_command("npx"):
        _print_fail("npx not found")
        click.echo(
            "\n  Node.js (which includes npx) is required"
            " for the Playwright MCP browser.",
            err=True,
        )
        click.echo(
            "  Install it from https://nodejs.org or via your package manager:\n",
            err=True,
        )
        click.echo("    macOS:   brew install node", err=True)
        click.echo("    Ubuntu:  sudo apt install nodejs npm", err=True)
        click.echo("    Windows: https://nodejs.org/en/download\n", err=True)
        return False

    code, output = _run_quietly(["npx", "--version"])
    if code != 0:
        _print_fail(f"npx found but returned error: {output.strip()}")
        return False

    _print_ok(f"npx {output.strip()}")
    return True


def _check_uvx() -> bool:
    """Check whether uvx (from uv) is available and print status."""
    if not _check_command("uvx"):
        _print_fail("uvx not found")
        click.echo(
            "\n  uv (which includes uvx) is required for the web-fetch MCP server.",
            err=True,
        )
        click.echo(
            "  Install it with:\n",
            err=True,
        )
        click.echo(
            "    curl -LsSf https://astral.sh/uv/install.sh | sh\n",
            err=True,
        )
        return False

    code, output = _run_quietly(["uvx", "--version"])
    if code != 0:
        _print_fail(f"uvx found but returned error: {output.strip()}")
        return False

    _print_ok(f"uvx {output.strip()}")
    return True


def _precache_npx_package(package: str) -> bool:
    """
    Pre-download an npx package into the local npx cache.

    Spawns the server process (which triggers npm download), then terminates
    it after a short grace period once the package is cached.
    """
    import tempfile
    import time

    click.echo(f"  Caching {package} …", nl=False)

    with tempfile.TemporaryDirectory() as tmp:
        # Start the server process – it will download the package then block on stdin
        proc = subprocess.Popen(
            [
                "npx",
                "-y",
                package,
                tmp,
            ],  # pass tmp dir so filesystem server starts cleanly
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Give it up to 30s to download, then kill it
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ret = proc.poll()
            if ret is not None:
                break  # exited on its own
            time.sleep(0.5)

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    _print_ok(f"  cached {package}")
    return True


def _precache_uvx_package(package: str) -> bool:
    """Pre-download a uvx (uv tool) package."""
    click.echo(f"  Caching {package} …", nl=False)
    code, output = _run_quietly(["uvx", package, "--help"])
    # --help usually exits 0; don't fail on non-zero (server may not support it)
    _print_ok(f"  cached {package}")
    return True


def _install_playwright_chromium() -> bool:
    """Download the @playwright/mcp package and install its Chromium browser."""
    click.echo("  Caching @playwright/mcp …", nl=False)
    code, output = _run_quietly(["npx", "-y", "@playwright/mcp@latest", "--version"])
    if code != 0:
        _print_fail(f"@playwright/mcp failed: {output.strip()}")
        return False
    _print_ok("  @playwright/mcp cached")

    click.echo("  Installing Playwright Chromium …", nl=False)
    code, output = _run_quietly(
        ["npx", "playwright", "install", "chromium", "--with-deps"]
    )
    if code != 0:
        _print_fail(f"playwright install chromium failed:\n{output.strip()}")
        return False
    _print_ok("  Chromium installed")
    return True


@click.command("init")
def init_command() -> None:
    """Install and pre-cache non-Python dependencies for hw.

    This sets up the MCP servers used by the AI-powered deep research feature:

    \b
      • @playwright/mcp  (Node/npx)  – headless Chromium browser for JLCPCB search

    If a dependency cannot be installed automatically, detailed instructions
    are printed so you can resolve it manually.
    """
    click.echo("Checking hw dependencies…\n")

    any_failure = False

    # ── npx + Playwright ─────────────────────────────────────────────────────
    click.echo("Node.js / npx:")
    npx_ok = _check_npx()
    if not npx_ok:
        any_failure = True
    else:
        try:
            ok = _install_playwright_chromium()
            if not ok:
                any_failure = True
        except Exception as exc:
            _print_fail(f"Playwright setup failed: {exc}")
            any_failure = True

    click.echo()

    # ── Config ───────────────────────────────────────────────────────────────
    from hw.ai.config import create_default_config, get_config_file

    config_file = get_config_file()
    if not config_file.exists():
        create_default_config()
        click.echo(f"✓ Created config file: {config_file}")
        click.echo(
            f"  Add your Anthropic API key to {config_file} "
            "or set the ANTHROPIC_API_KEY environment variable."
        )
    else:
        click.echo(f"✓ Config file already exists: {config_file}")

    click.echo()

    if any_failure:
        click.echo(
            "⚠️  Some dependencies could not be installed automatically.\n"
            "   Resolve the issues above, then re-run 'hw init'.",
            err=True,
        )
        raise click.exceptions.Exit(1)
    else:
        click.echo(
            "✓ All dependencies ready. "
            "Run 'hw circuits jlcpcb bom-lookup --deep-research' to use AI research."
        )
