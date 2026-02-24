import csv
from enum import Enum

from pydantic import BaseModel, Field

from hw.circuits.kicad.convert.models import KICAD_BOM_DELIMITER


class Format(str, Enum):
    """Supported BOM formats for parsing and writing."""

    JLCPCB = "jlcpcb"
    KICAD = "kicad"


class Vendor(str, Enum):
    """Supported vendors for part research."""

    DIGIKEY = "digikey"
    MOUSER = "mouser"


class BOMItem(BaseModel):
    """Represents a single line item in a Bill of Materials (BOM).

    Each item corresponds to one unique component type; a component that
    appears multiple times on the board is captured as a list of reference
    designators rather than repeated rows.
    """

    # required fields
    references: list[str] = Field(
        ...,
        description="All reference designators for this component (e.g. ['R1', 'R2']).",
    )
    value: str = Field(
        ...,
        description="Value or description of the component (e.g. '10kΩ', '100nF', 'STM32F4').",  # noqa: E501
    )
    footprint: str = Field(
        ...,
        description="PCB footprint of the component (e.g. 'R_0603', 'SOT-23').",
    )

    # optional fields (depends on functionality)
    vendor: Vendor | None = Field(
        None,
        description="Preferred vendor for sourcing this component (e.g. 'digikey').",
    )
    part_number: str | None = Field(
        None,
        description="Specific part number for this component, if known (e.g. 'C12345').",  # noqa: E501
    )

    @property
    def quantity(self) -> int:
        """Number of placements derived from the reference list."""
        return len(self.references)


class BOM(BaseModel):
    """Represents a Bill of Materials (BOM) for a circuit design."""

    items: list[BOMItem] = Field(..., description="A list of BOM items.")
    format: Format = Field(
        Format.KICAD, description="The format of the BOM (e.g. 'jlcpcb', 'kicad')."
    )
    filename: str | None = Field(
        None, description="Original filename of the BOM, if loaded from a file."
    )

    def write_csv(
        self, filename: str | None = None, format: Format | None = None
    ) -> None:
        """Writes the BOM to a CSV file with headers: References, Value, Footprint."""
        if filename is None:
            if self.filename is None:
                raise ValueError("No filename specified for writing BOM.")
            filename = self.filename
        if format is None:
            format = self.format
        with open(filename, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if format == Format.JLCPCB:
                writer.writerow(["Comment", "Designator", "Footprint", "JLCPCB Part #"])
                for item in self.items:
                    writer.writerow(
                        [
                            item.value,
                            ", ".join(item.references),
                            item.footprint,
                            item.part_number or "",
                        ]
                    )
            elif format == Format.KICAD:
                writer.writerow(
                    [
                        "Id",
                        "Designator",
                        "Footprint",
                        "Quantity",
                        "Designation",
                        "Supplier and ref",
                    ]
                )
                for idx, item in enumerate(self.items, start=1):
                    writer.writerow(
                        [
                            idx,
                            ", ".join(item.references),
                            item.footprint,
                            item.quantity,
                            item.value,
                            item.part_number or "",
                        ]
                    )
            else:
                raise ValueError(f"Unsupported BOM format: {format}")

    @classmethod
    def from_jlcpcb_csv(cls, filename: str) -> "BOM":
        """Parses BOM items from a JLCPCB CSV export.

        Expected headers (comma-delimited):
            Comment, Designator, Footprint, JLCPCB Part #（optional）

        ``Comment``    → value
        ``Designator`` → references (comma-separated list)
        ``Footprint``  → footprint
        """
        items: list[BOMItem] = []
        with open(filename, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                refs_raw = row.get("Designator", "")
                references = [r.strip() for r in refs_raw.split(",") if r.strip()]
                items.append(
                    BOMItem(
                        references=references,
                        value=row.get("Comment", "").strip(),
                        footprint=row.get("Footprint", "").strip(),
                        part_number=row.get("JLCPCB Part #", "").strip() or None,
                    )
                )
        return cls(items=items, format=Format.JLCPCB, filename=filename)

    @classmethod
    def from_kicad_csv(cls, filename: str) -> "BOM":
        """Parses BOM items from a KiCad-generated BOM CSV export.

        Expected headers (semicolon-delimited):
            Id, Designator, Footprint, Quantity, Designation, Supplier and ref

        ``Designation`` → value
        ``Designator``  → references (comma-separated list)
        ``Footprint``   → footprint
        """
        items: list[BOMItem] = []
        with open(filename, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter=KICAD_BOM_DELIMITER):
                refs_raw = row.get("Designator", "")
                references = [r.strip() for r in refs_raw.split(",") if r.strip()]
                items.append(
                    BOMItem(
                        references=references,
                        value=row.get("Designation", "").strip(),
                        footprint=row.get("Footprint", "").strip(),
                        part_number=row.get("Supplier and ref", "").strip() or None,
                    )
                )
        return cls(items=items, format=Format.KICAD, filename=filename)
