import csv

import click
from loguru import logger

from hw.circuits.kicad.convert.models import (
    JLCPCB_BOM_HEADERS,
    JLCPCB_CPL_HEADERS,
    KICAD_BOM_DELIMITER,
    KICAD_POS_DELIMITER,
    SIDE_MAP,
    JlcpcbBomRow,
    JlcpcbCplRow,
    KicadBomRow,
    KicadPosRow,
)

# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------


def _read_kicad_bom(input_file: str) -> list[KicadBomRow]:
    rows: list[KicadBomRow] = []
    with open(input_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=KICAD_BOM_DELIMITER)
        for row in reader:
            rows.append(
                KicadBomRow(
                    id=row.get("Id", "").strip(),
                    designator=row.get("Designator", "").strip(),
                    footprint=row.get("Footprint", "").strip(),
                    quantity=row.get("Quantity", "").strip(),
                    designation=row.get("Designation", "").strip(),
                    supplier_and_ref=row.get("Supplier and ref", "").strip(),
                )
            )
    return rows


def _read_kicad_pos(input_file: str) -> list[KicadPosRow]:
    rows: list[KicadPosRow] = []
    with open(input_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=KICAD_POS_DELIMITER)
        for row in reader:
            rows.append(
                KicadPosRow(
                    ref=row.get("Ref", "").strip(),
                    val=row.get("Val", "").strip(),
                    package=row.get("Package", "").strip(),
                    pos_x=row.get("PosX", "").strip(),
                    pos_y=row.get("PosY", "").strip(),
                    rot=row.get("Rot", "").strip(),
                    side=row.get("Side", "").strip(),
                )
            )
    return rows


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------


def _to_jlcpcb_bom(rows: list[KicadBomRow]) -> list[JlcpcbBomRow]:
    return [
        JlcpcbBomRow(
            comment=row.designation,
            designator=row.designator,
            footprint=row.footprint,
        )
        for row in rows
    ]


def _to_jlcpcb_cpl(rows: list[KicadPosRow]) -> list[JlcpcbCplRow]:
    out: list[JlcpcbCplRow] = []
    for row in rows:
        try:
            mid_x = f"{float(row.pos_x):.4f}mm"
            mid_y = f"{float(row.pos_y):.4f}mm"
        except ValueError:
            logger.warning(
                f"Could not parse coordinates for {row.ref}: ({row.pos_x}, {row.pos_y})"
            )
            mid_x = row.pos_x
            mid_y = row.pos_y
        layer = SIDE_MAP.get(row.side.lower(), row.side)
        out.append(
            JlcpcbCplRow(
                designator=row.ref,
                mid_x=mid_x,
                mid_y=mid_y,
                layer=layer,
                rotation=row.rot,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _write_csv(output_file: str, headers: list[str], rows: list[list[str]]) -> None:
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@click.group()
def convert() -> None:
    """Convert KiCad artifacts to vendor-ready formats."""


@convert.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.argument("output_file", type=click.Path())
@click.option(
    "--jlcpcb", is_flag=True, default=False, help="Convert to JLCPCB BOM format."
)
def bom(input_file: str, output_file: str, jlcpcb: bool) -> None:
    """Convert a KiCad-generated BOM CSV to a vendor format."""
    if not jlcpcb:
        raise click.UsageError("Specify a target format (e.g. --jlcpcb).")

    logger.info(f"Reading KiCad BOM from {input_file}")
    kicad_rows = _read_kicad_bom(input_file)

    logger.info(f"Converting {len(kicad_rows)} rows to JLCPCB BOM format")
    jlcpcb_rows = _to_jlcpcb_bom(kicad_rows)

    _write_csv(output_file, JLCPCB_BOM_HEADERS, [r.to_row() for r in jlcpcb_rows])
    click.echo(f"Wrote {len(jlcpcb_rows)} rows to {output_file}")


@convert.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.argument("output_file", type=click.Path())
@click.option(
    "--jlcpcb", is_flag=True, default=False, help="Convert to JLCPCB CPL format."
)
def pos(input_file: str, output_file: str, jlcpcb: bool) -> None:
    """Convert a KiCad-generated POS CSV to a vendor CPL format."""
    if not jlcpcb:
        raise click.UsageError("Specify a target format (e.g. --jlcpcb).")

    logger.info(f"Reading KiCad POS from {input_file}")
    kicad_rows = _read_kicad_pos(input_file)

    logger.info(f"Converting {len(kicad_rows)} rows to JLCPCB CPL format")
    jlcpcb_rows = _to_jlcpcb_cpl(kicad_rows)

    _write_csv(output_file, JLCPCB_CPL_HEADERS, [r.to_row() for r in jlcpcb_rows])
    click.echo(f"Wrote {len(jlcpcb_rows)} rows to {output_file}")
