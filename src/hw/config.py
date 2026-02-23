"""Configuration management commands."""

import click

from hw import logger
from hw.ai import create_default_config, get_config_file, load_config


@click.group("config")
def config_group() -> None:
    """Manage hw CLI configuration."""


@config_group.command("init")
def init_config() -> None:
    """Initialize configuration file with default settings.

    Creates ~/.hw/config.toml with example AI configuration.
    """
    try:
        create_default_config()
        config_file = get_config_file()
        click.echo(f"✓ Created configuration file: {config_file}")
        click.echo("\nPlease edit the file and add your Anthropic API key.")
        click.echo("You can also set the ANTHROPIC_API_KEY environment variable.")
    except Exception as e:
        click.echo(f"❌ Failed to create config file: {e}")
        logger.error(f"Config init failed: {e}")
        raise click.exceptions.Exit(1)


@config_group.command("show")
def show_config() -> None:
    """Display current configuration.

    Shows the active configuration including API key status and MCP servers.
    """
    config_file = get_config_file()

    if not config_file.exists():
        click.echo(f"⚠️  No config file found at {config_file}")
        click.echo("Run 'hw config init' to create one.")
        return

    try:
        config = load_config()

        click.echo(f"Configuration file: {config_file}\n")

        # Show API key status (masked)
        if config.anthropic_api_key:
            masked_key = (
                config.anthropic_api_key[:10] + "..." + config.anthropic_api_key[-4:]
            )
            click.echo(f"✓ Anthropic API Key: {masked_key}")
        else:
            click.echo("❌ Anthropic API Key: Not configured")

        # Show MCP servers
        if config.mcp_servers:
            click.echo(f"\nMCP Servers ({len(config.mcp_servers)}):")
            for name, server in config.mcp_servers.items():
                click.echo(f"  • {name}: {server.command} {' '.join(server.args)}")
        else:
            click.echo("\n⚠️  No MCP servers configured (will use defaults)")

    except Exception as e:
        click.echo(f"❌ Failed to load config: {e}")
        logger.error(f"Config show failed: {e}")
        raise click.exceptions.Exit(1)
