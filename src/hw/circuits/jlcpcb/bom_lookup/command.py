"""Command for looking up JLCPCB/LCSC part numbers for BOM components."""

import csv

import click

from hw import logger
from hw.circuits.jlcpcb.bom_lookup.client import (
    close_browser,
    fetch_part_detail,
    search_jlcpcb,
    search_part,
)
from hw.circuits.jlcpcb.bom_lookup.models import (
    MIN_STOCK,
    BomLookupRow,
    JlcpcbSearchResult,
    LookupReport,
)
from hw.circuits.jlcpcb.bom_lookup.resolver import resolve_part
from hw.ui.loading_bar import LoadingBar
from hw.ui.table import Table, TableColumn


def _read_jlcpcb_bom(file_path: str) -> list[BomLookupRow]:
    """Read a JLCPCB BOM CSV file.

    Args:
        file_path: Path to the JLCPCB BOM CSV

    Returns:
        List of BomLookupRow objects
    """
    rows: list[BomLookupRow] = []

    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                BomLookupRow(
                    comment=row.get("Comment", "").strip(),
                    designator=row.get("Designator", "").strip(),
                    footprint=row.get("Footprint", "").strip(),
                )
            )

    return rows


def _write_jlcpcb_bom(file_path: str, rows: list[BomLookupRow]) -> None:
    """Write JLCPCB BOM CSV file with updated part numbers.

    Args:
        file_path: Path to write the BOM CSV
        rows: List of BomLookupRow objects
    """
    headers = ["Comment", "Designator", "Footprint", "JLCPCB Part ＃（optional）"]

    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for row in rows:
            part_number = row.selected.lcsc_part if row.selected else ""
            writer.writerow([row.comment, row.designator, row.footprint, part_number])


def _print_report(
    report: LookupReport, rows: list[BomLookupRow], dry_run: bool
) -> None:
    """Print the lookup report to the console.

    Args:
        report: The lookup report
        rows: All BOM rows (needed for the dry-run results table)
        dry_run: Whether this was a dry run
    """
    # Success summary
    if report.has_errors:
        click.echo(
            f"✓ Resolved {report.resolved}/{report.total} parts "
            f"({report.success_rate:.0f}% success rate)"
        )
    else:
        click.echo(
            f"✓ All {report.total} parts resolved successfully{' (dry run)'
            if dry_run else ''}"
        )

    # Dry-run: always show full results table
    if dry_run:
        click.echo()
        columns = [
            TableColumn("Comment", style="cyan"),
            TableColumn("Designator", style="bold"),
            TableColumn("Footprint", style="dim"),
            TableColumn("JLCPCB Part", style="green"),
            TableColumn("Manufacturer Part", style=""),
            TableColumn("Stock", style=""),
        ]

        table = Table(title="BOM Lookup Results", columns=columns)

        for row in rows:
            if row.selected:
                table.add_row(
                    [
                        row.comment,
                        row.designator,
                        row.footprint,
                        row.selected.lcsc_part,
                        row.selected.mfr_part or "",
                        str(row.selected.stock),
                    ]
                )
            else:
                table.add_row(
                    [
                        row.comment,
                        row.designator,
                        row.footprint,
                        "—",
                        row.error or "No match",
                        "—",
                    ],
                    style="red",
                )

        table.render()
        return

    # Non-dry-run: only show error table when there are failures
    if report.has_errors:
        click.echo(f"\n⚠️  {len(report.errors)} parts failed to resolve:\n")

        columns = [
            TableColumn("Comment", style="cyan"),
            TableColumn("Designator", style="bold"),
            TableColumn("Footprint", style="dim"),
            TableColumn("Error", style="red"),
        ]

        table = Table(title="Failed Parts", columns=columns)

        for error_row in report.errors:
            table.add_row(
                [
                    error_row.comment,
                    error_row.designator,
                    error_row.footprint,
                    error_row.error or "Unknown error",
                ]
            )

        table.render()


def _ai_research_failed_parts(rows: list[BomLookupRow]) -> int:
    """
    Use AI to research parts that failed initial lookup.

    Starts MCP servers once and processes all failed parts through the same
    session, then updates rows in place.

    Args:
        rows: List of BOM rows (will be modified in place)

    Returns:
        Number of parts successfully resolved by AI
    """
    from hw.ai import ResearchRequest, load_config, research_all_components
    from hw.ai.models import ResearchResult as _ResearchResult

    # Get failed parts
    failed_rows = [r for r in rows if not r.is_resolved]
    if not failed_rows:
        return 0

    # Load AI configuration
    try:
        config = load_config()
    except Exception as e:
        click.echo(f"\n❌ Failed to load AI configuration: {e}")
        click.echo("Please set ANTHROPIC_API_KEY or configure ~/.hw/config.toml")
        return 0

    click.echo(f"\n🔍 Starting AI research for {len(failed_rows)} failed parts...")
    click.echo("This may take a few minutes as the AI researches each component.\n")

    requests = [
        ResearchRequest(
            comment=row.comment,
            footprint=row.footprint,
            error_message=row.error or "No match found",
        )
        for row in failed_rows
    ]

    resolved_count = 0

    with LoadingBar("AI research", total=len(failed_rows)) as progress:

        def on_complete(request: ResearchRequest, result: _ResearchResult) -> None:
            nonlocal resolved_count
            row = next(r for r in failed_rows if r.comment == request.comment)

            if result.success and result.jlcpcb_part_number:
                row.selected = JlcpcbSearchResult(
                    lcsc_part=result.jlcpcb_part_number,
                    mfr_part=None,
                    package="AI-selected",
                    stock=0,
                    price=None,
                    description=(result.justification or "")[:100],
                    source="ai",  # type: ignore
                )
                row.error = None
                resolved_count += 1
                logger.info(f"AI resolved {row.comment}: {result.jlcpcb_part_number}")
            else:
                row.error = result.error or "AI research could not find suitable part"
                logger.warning(f"AI could not resolve {row.comment}: {row.error}")

            progress.advance()

        try:
            research_all_components(requests, config, on_complete=on_complete)
        except Exception as e:
            logger.error(f"AI research session failed: {e}", exc_info=True)
            click.echo(f"\n❌ AI research session error: {e}", err=True)

    click.echo(f"\n✓ AI resolved {resolved_count}/{len(failed_rows)} additional parts")
    return resolved_count


def _check_eol_parts(rows: list[BomLookupRow]) -> None:
    """Detect discontinued parts and offer user a confirmed replacement.

    For every row whose selected part is flagged as discontinued, this function
    fetches the JLCPCB detail page to find any recommended alternative part
    number and then prompts the user interactively.  If the user confirms, the
    row is updated in-place with the alternative part.

    Requires the Playwright browser session to be open (must be called before
    close_browser()).

    Args:
        rows: List of BOM rows (modified in place).
    """
    for row in rows:
        if row.selected is None or not row.selected.discontinued:
            continue
        if row.selected.source == "ai":
            # AI-resolved parts are synthetic stubs; skip EOL check.
            continue

        old_part = row.selected.lcsc_part
        click.echo(
            f"\n\u26a0\ufe0f  {row.designator} ({row.comment}): "
            f"{old_part} is marked as discontinued on JLCPCB."
        )

        # Fetch the detail page to find the recommended replacement.
        discontinued, alternative = fetch_part_detail(old_part)

        if not alternative:
            click.echo(
                f"   No recommended replacement found on JLCPCB for {old_part}.\n"
                f"   Keeping it in the BOM — please verify manually."
            )
            continue

        click.echo(f"   JLCPCB recommends replacement: {alternative}")
        confirmed = click.confirm(
            f"   Substitute {old_part} \u2192 {alternative} for {row.designator}?",
            default=False,
        )

        if not confirmed:
            click.echo(f"   Keeping original part {old_part}.")
            continue

        # Search for the alternative by its C-number to get full metadata.
        candidates = search_jlcpcb(alternative)
        match = next(
            (c for c in candidates if c.lcsc_part == alternative),
            candidates[0] if candidates else None,
        )

        if match is None:
            click.echo(
                f"   \u274c Could not retrieve details for {alternative}; "
                f"keeping {old_part}."
            )
            continue

        row.selected = match
        row.error = None
        click.echo(
            f"   \u2713 Substituted: {old_part} \u2192 {alternative} "
            f"({match.description[:60]})"
        )


@click.command("bom-lookup")
@click.argument("bom_file", type=click.Path(exists=True))
@click.option(
    "--min-stock",
    type=int,
    default=MIN_STOCK,
    help=f"Minimum stock threshold (default: {MIN_STOCK})",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview results without updating the BOM file",
)
@click.option(
    "--deep-research",
    is_flag=True,
    default=False,
    help="Use AI-powered research for parts that couldn't be found automatically",
)
def bom_lookup(
    bom_file: str, min_stock: int, dry_run: bool, deep_research: bool
) -> None:
    """Look up JLCPCB/LCSC part numbers for BOM components.

    Reads a JLCPCB-format BOM CSV, searches for each part on JLCPCB and LCSC,
    selects the best match based on availability and footprint, and updates
    the BOM with the selected part numbers.

    BOM_FILE: Path to JLCPCB BOM CSV file (output of 'hw circuits kicad convert bom')
    """
    logger.info(f"Starting BOM lookup for: {bom_file}")
    logger.info(f"Min stock threshold: {min_stock}, Dry run: {dry_run}")

    # Read BOM
    click.echo(f"Reading BOM from {bom_file}...")
    rows = _read_jlcpcb_bom(bom_file)
    logger.info(f"Read {len(rows)} parts from BOM")

    if not rows:
        click.echo("No parts found in BOM file.")
        return

    # Process each part with progress bar
    with LoadingBar("Looking up parts", total=len(rows)) as progress:
        for row in rows:
            # Search for the part
            candidates = search_part(row.comment, row.footprint)
            row.candidates = candidates

            # Resolve the best match
            if candidates:
                selected, error = resolve_part(row.comment, row.footprint, candidates)
                row.selected = selected
                row.error = error
            else:
                row.error = "No search results found"

            progress.advance()

    # Check for discontinued / EOL parts and offer user confirmed replacements.
    # Must run while the Playwright browser is still open.
    _check_eol_parts(rows)

    # Build report
    report = LookupReport(
        total=len(rows),
        resolved=sum(1 for r in rows if r.is_resolved),
        errors=[r for r in rows if not r.is_resolved],
    )

    # If deep research is enabled and there are failures, use AI.
    # The Playwright browser must be closed first — its background event loop
    # conflicts with the asyncio.run() call inside research_all_components.
    if deep_research and report.has_errors:
        close_browser()
        _ai_research_failed_parts(rows)

        # Rebuild report with AI results
        report = LookupReport(
            total=len(rows),
            resolved=sum(1 for r in rows if r.is_resolved),
            errors=[r for r in rows if not r.is_resolved],
        )

    # Write updated BOM (unless dry run)
    if not dry_run and report.resolved > 0:
        _write_jlcpcb_bom(bom_file, rows)
        logger.info(f"Updated BOM file: {bom_file}")

    # Print report
    _print_report(report, rows, dry_run)

    # Exit with error code if there were failures
    if report.has_errors:
        raise click.exceptions.Exit(1)
