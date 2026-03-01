"""CLI commands for the `hw circuits shop` subgroup."""

import asyncio

import click

from hw import logger
from hw.circuits.models.bom import BOM, Format
from hw.circuits.query import eia_from_footprint
from hw.circuits.resolver import infer_package_from_mpn
from hw.circuits.shop.models import ShoppingPlan, ShoppingPlanItem
from hw.circuits.shop.search import OemSecretsAPIAdapter, PartSearchQuery
from hw.circuits.shop.workflow import generate_plan
from hw.ui.loading_bar import LoadingBar
from hw.ui.table import Table, TableColumn

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_async(coro):
    """Run an async coroutine, handling the case where an event loop is already running.

    This is useful for environments like Jupyter notebooks where an event loop
    may already be active. It attempts to use asyncio.run() first, and falls back
    to nest_asyncio if needed.
    """
    try:
        # Try to check if there's a running loop
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, safe to use asyncio.run()
        return asyncio.run(coro)

    # If we get here, a loop is already running
    # Try to use nest_asyncio to allow nested event loop
    try:
        import nest_asyncio

        nest_asyncio.apply()
        return asyncio.run(coro)
    except ImportError:
        # If nest_asyncio is not available, create a task and run it
        # This works in some interactive environments
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()


def _fmt_price(price: float | None, currency: str = "USD") -> str:
    if price is None:
        return "—"
    symbol = "$" if currency == "USD" else currency + " "
    return f"{symbol}{price:.4f}"


def _fmt_stock(qty: int | None) -> str:
    if qty is None:
        return "—"
    return f"{qty:,}"


def _truncate(s: str | None, n: int = 50) -> str:
    if not s:
        return "—"
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------


@click.group()
def shop() -> None:
    """Research parts, generate shopping plans, and automate vendor carts."""


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@shop.command()
@click.argument("query")
@click.option(
    "--currency",
    default="USD",
    show_default=True,
    help="Currency for price display.",
)
def search(query: str, currency: str) -> None:
    """Search for parts across all distributors via OEM Secrets.

    QUERY is a manufacturer part number or keyword (e.g. LM358, STM32F4).
    """
    try:
        adapter = OemSecretsAPIAdapter()
    except ValueError as e:
        raise click.ClickException(str(e))

    logger.info(f"Searching OEM Secrets for: {query}")
    click.echo(f"Searching for '{query}'…")

    try:
        parts = _run_async(adapter.search(PartSearchQuery(query=query)))
    except Exception as e:
        raise click.ClickException(f"Search failed: {e}")

    if not parts:
        click.echo("No results found.")
        return

    columns = [
        TableColumn("MPN", style="bold cyan", no_wrap=True),
        TableColumn("Distributor", style="yellow"),
        TableColumn("Stock", justify="right"),
        TableColumn("Unit Price", justify="right", style="green"),
        TableColumn("Lifecycle"),
        TableColumn("URL"),
    ]
    table = Table(f"Results for '{query}' ({len(parts)} listings)", columns)
    for p in parts:
        table.add_row(
            [
                p.part_number,
                p.distributor_name or "—",
                _fmt_stock(p.quantity_in_stock),
                _fmt_price(p.unit_price, p.currency),
                p.lifecycle or "—",
                _truncate(p.buy_now_url, 60),
            ]
        )
    table.render()


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def _parse_vendors(ctx, param, value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


@shop.command()
@click.argument("bom_file", type=click.Path(exists=True))
@click.option(
    "-o",
    "--output",
    "output_file",
    required=True,
    type=click.Path(),
    help="Output filename for the shopping plan JSON.",
)
@click.option(
    "--format",
    "bom_format",
    type=click.Choice([f.value for f in Format], case_sensitive=False),
    default=Format.KICAD.value,
    show_default=True,
    help="BOM file format.",
)
@click.option(
    "--max-vendors",
    default=3,
    show_default=True,
    help="Maximum vendor options to keep per BOM line item.",
)
@click.option(
    "--vendors",
    callback=_parse_vendors,
    is_eager=False,
    default=None,
    help=(
        "Comma-separated distributor names to restrict results to "
        "(e.g. 'digikey,mouser'). Omit for all distributors."
    ),
)
def plan(
    bom_file: str,
    output_file: str,
    bom_format: str,
    max_vendors: int,
    vendors: list[str],
) -> None:
    """Generate a shopping plan from a BOM file.

    BOM_FILE is a KiCad or JLCPCB BOM CSV. The plan is saved as JSON to
    --output so it can later be passed to `hw circuits shop order`.
    """
    fmt = Format(bom_format)
    logger.info(f"Loading BOM ({fmt.value}): {bom_file}")

    try:
        bom = (
            BOM.from_kicad_csv(bom_file)
            if fmt == Format.KICAD
            else BOM.from_jlcpcb_csv(bom_file)
        )
    except Exception as e:
        raise click.ClickException(f"Failed to parse BOM: {e}")

    click.echo(f"Loaded {len(bom.items)} BOM items. Searching across distributors…")

    try:
        adapter = OemSecretsAPIAdapter()
    except ValueError as e:
        raise click.ClickException(str(e))

    bar = LoadingBar("Searching parts", total=len(bom.items))
    bar.start()

    def on_progress(done: int, total: int) -> None:
        bar.advance()

    try:
        shopping_plan = _run_async(
            generate_plan(
                bom=bom,
                adapter=adapter,
                max_vendors=max_vendors,
                vendors_filter=vendors or None,
                on_progress=on_progress,
            )
        )
    except Exception as e:
        bar.finish()
        raise click.ClickException(f"Plan generation failed: {e}")

    bar.finish()

    # Write plan JSON
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(shopping_plan.model_dump_json(indent=2))
    logger.info(f"Plan saved to {output_file}")

    # Summary table
    # "Pkg" column: shows required EIA vs inferred match EIA so mismatches
    # are visible at a glance.  Format: "req→found" or "✓ req" or "IC/mod"
    def _pkg_cell(item: ShoppingPlanItem) -> str:
        req_eia = eia_from_footprint(item.bom_item.footprint)
        if not item.is_sourced:
            return "—"
        best = item.best
        if best is None:
            return "—"
        # infer matched part's EIA from its package field (set during parse)
        # or fall back to MPN inference
        matched_eia = best.package or infer_package_from_mpn(best.part_number)
        if not req_eia:
            return "IC/mod"  # module / IC — no EIA code expected
        if not matched_eia:
            return f"? ({req_eia})"  # required but unknown for this MPN
        if matched_eia == req_eia:
            return f"✓ {req_eia}"
        return f"✗ {req_eia}≠{matched_eia}"  # mismatch — wrong package

    columns = [
        TableColumn("References", style="cyan", no_wrap=True),
        TableColumn("Value"),
        TableColumn("Best match", style="bold"),
        TableColumn("Pkg", justify="center"),
        TableColumn("Distributor", style="yellow"),
        TableColumn("Qty", justify="right"),
        TableColumn("Unit price", justify="right", style="green"),
        TableColumn("Stock", justify="right"),
    ]
    sourced_title = (
        f"Shopping Plan — "
        f"{shopping_plan.sourced_count}/{len(shopping_plan.items)} sourced"
    )
    table = Table(sourced_title, columns)

    for item in shopping_plan.items:
        best = item.best
        refs = ", ".join(item.bom_item.references[:4])
        if len(item.bom_item.references) > 4:
            refs += f" +{len(item.bom_item.references) - 4}"
        if best:
            match_cell = best.part_number
        elif item.error:
            match_cell = _truncate(f"FAIL: {item.error}", 32)
        else:
            match_cell = "NOT FOUND"
        row = [
            refs,
            _truncate(item.bom_item.value, 30),
            match_cell,
            _pkg_cell(item),
            best.distributor_name if best else "—",
            str(item.bom_item.quantity),
            _fmt_price(best.unit_price if best else None),
            _fmt_stock(best.quantity_in_stock if best else None),
        ]
        # Colour-code: green=match+pkg ok, yellow=pkg mismatch, red=not found
        pkg = _pkg_cell(item)
        if not item.is_sourced:
            style = "red"
        elif pkg.startswith("✗"):
            style = "yellow"
        else:
            style = None
        table.add_row(row, style=style)

    table.render()

    click.echo(f"\nPlan saved to: {output_file}")
    if shopping_plan.unsourced_count:
        click.echo(
            f"⚠  {shopping_plan.unsourced_count} item(s) could not be matched — "
            "check values or try different vendor filters."
        )


# ---------------------------------------------------------------------------
# order
# ---------------------------------------------------------------------------


def _print_buy_links(items: list[ShoppingPlanItem], label: str) -> None:
    columns = [
        TableColumn("References", style="cyan", no_wrap=True),
        TableColumn("MPN", style="bold"),
        TableColumn("Distributor", style="yellow"),
        TableColumn("Qty", justify="right"),
        TableColumn("Unit price", justify="right", style="green"),
        TableColumn("Stock", justify="right"),
        TableColumn("Buy URL"),
    ]
    table = Table(label, columns)
    for item in items:
        best = item.best
        if not best:
            continue
        refs = ", ".join(item.bom_item.references[:3])
        if len(item.bom_item.references) > 3:
            refs += f" +{len(item.bom_item.references) - 3}"
        table.add_row(
            [
                refs,
                best.part_number,
                best.distributor_name or "—",
                str(best.quantity_needed or item.bom_item.quantity),
                _fmt_price(best.unit_price, best.currency),
                _fmt_stock(best.quantity_in_stock),
                _truncate(best.buy_now_url, 70),
            ]
        )
    table.render()


@shop.command()
@click.argument("plan_file", type=click.Path(exists=True))
@click.option(
    "--no-browser",
    is_flag=True,
    default=False,
    help="Print DigiKey URL to stdout instead of opening in the browser.",
)
def order(plan_file: str, no_browser: bool) -> None:
    """Fill vendor carts from a shopping plan JSON.

    PLAN_FILE is the JSON output from `hw circuits shop plan`.

    For DigiKey items a pre-filled cart URL is constructed and opened in
    your browser. For Mouser items the cart is populated via the Mouser API
    (requires mouser_api_key in config) and a summary is displayed. Items
    from other distributors are listed with direct buy links.
    """
    from hw.circuits.shop import digikey as dk_mod
    from hw.circuits.shop import mouser as mouser_mod
    from hw.circuits.shop.config import load_search_config

    try:
        raw = open(plan_file, encoding="utf-8").read()
        shopping_plan = ShoppingPlan.model_validate_json(raw)
    except Exception as e:
        raise click.ClickException(f"Failed to load plan: {e}")

    sourced = [i for i in shopping_plan.items if i.is_sourced]
    if not sourced:
        click.echo("No sourced items in plan — nothing to order.")
        return

    # ---- DigiKey -----------------------------------------------------------
    dk_items = [i for i in sourced if i.best and dk_mod.is_digikey(i.best)]
    dk_url = dk_mod.build_cart_url(dk_items)

    if dk_url:
        click.echo(f"\n[DigiKey] {len(dk_items)} item(s) ready.")
        if no_browser:
            click.echo(f"  Cart URL: {dk_url}")
        else:
            click.echo("  Opening DigiKey cart in your browser…")
            click.launch(dk_url)
    else:
        click.echo("\n[DigiKey] No DigiKey items in plan.")

    # ---- Mouser ------------------------------------------------------------
    mouser_items = [i for i in sourced if i.best and mouser_mod.is_mouser(i.best)]

    if mouser_items:
        try:
            cfg = load_search_config()
        except ValueError:
            cfg = None

        if cfg and cfg.mouser_api_key:
            click.echo(
                f"\n[Mouser] Adding {len(mouser_items)} item(s) to cart via API…"
            )
            try:
                result = _run_async(
                    mouser_mod.add_items_to_cart(
                        mouser_items, api_key=cfg.mouser_api_key
                    )
                )
                click.echo(f"  Cart key : {result.cart_key}")
                click.echo(f"  Items    : {result.item_count}")
                if result.merchandise_total is not None:
                    click.echo(f"  Total    : ${result.merchandise_total:.2f}")
                for err in result.errors:
                    click.echo(f"  ⚠  {err}", err=True)
                click.echo("  → Log in to mouser.com to review and complete checkout.")
            except Exception as e:
                click.echo(f"  ⚠  Mouser cart API failed: {e}", err=True)
                _print_buy_links(mouser_items, "Mouser")
        else:
            click.echo(
                "\n[Mouser] No mouser_api_key configured — showing buy links instead."
            )
            _print_buy_links(mouser_items, "Mouser")
    else:
        click.echo("\n[Mouser] No Mouser items in plan.")

    # ---- Everything else ---------------------------------------------------
    other_items = [
        i
        for i in sourced
        if i.best and not dk_mod.is_digikey(i.best) and not mouser_mod.is_mouser(i.best)
    ]
    if other_items:
        click.echo(f"\n[Other distributors] {len(other_items)} item(s):")
        _print_buy_links(other_items, "Other")

    # ---- Unsourced ---------------------------------------------------------
    unsourced = [i for i in shopping_plan.items if not i.is_sourced]
    if unsourced:
        click.echo(f"\n⚠  {len(unsourced)} item(s) not sourced:")
        for i in unsourced:
            refs = ", ".join(i.bom_item.references)
            click.echo(f"   - {refs}  ({i.bom_item.value})")
