"""Command for looking up JLCPCB/LCSC part numbers for BOM components."""

import csv

import click

from hw import logger
from hw.circuits.jlcpcb.bom_lookup.client import search_part
from hw.circuits.jlcpcb.bom_lookup.models import MIN_STOCK, BomLookupRow, LookupReport
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
def bom_lookup(bom_file: str, min_stock: int, dry_run: bool) -> None:
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

    # Build report
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
