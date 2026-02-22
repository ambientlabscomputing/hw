"""Data models for JLCPCB BOM lookup functionality."""

from typing import Literal

from pydantic import BaseModel, Field

# Minimum stock threshold for part availability
MIN_STOCK = 10


class JlcpcbSearchResult(BaseModel):
    """A part search result from JLCPCB or LCSC API."""

    lcsc_part: str = Field(description="LCSC part number (C-number)")
    description: str = Field(description="Part description")
    manufacturer: str | None = Field(default=None, description="Manufacturer name")
    mfr_part: str | None = Field(default=None, description="Manufacturer part number")
    package: str | None = Field(default=None, description="Component package/footprint")
    stock: int = Field(description="Available stock quantity")
    price: float | None = Field(default=None, description="Unit price")
    source: Literal["jlcpcb", "lcsc"] = Field(description="Source API")

    def __hash__(self) -> int:
        """Hash by LCSC part number for deduplication."""
        return hash(self.lcsc_part)

    def __eq__(self, other: object) -> bool:
        """Compare by LCSC part number."""
        if not isinstance(other, JlcpcbSearchResult):
            return False
        return self.lcsc_part == other.lcsc_part


class BomLookupRow(BaseModel):
    """Represents one BOM row being processed for part lookup."""

    comment: str = Field(description="Part value/comment (e.g., '100nF', 'ESP32-S3')")
    designator: str = Field(description="Component designators (e.g., 'C1,C2,C3')")
    footprint: str = Field(
        description="Component footprint (e.g., 'C_0402_1005Metric')"
    )
    candidates: list[JlcpcbSearchResult] = Field(
        default_factory=list, description="Search results from APIs"
    )
    selected: JlcpcbSearchResult | None = Field(
        default=None, description="Selected part after filtering"
    )
    error: str | None = Field(
        default=None, description="Error message if lookup failed"
    )

    @property
    def is_resolved(self) -> bool:
        """Check if part was successfully resolved."""
        return self.selected is not None and self.error is None


class LookupReport(BaseModel):
    """Summary report of the BOM lookup operation."""

    total: int = Field(description="Total number of parts processed")
    resolved: int = Field(description="Number of successfully resolved parts")
    errors: list[BomLookupRow] = Field(
        default_factory=list, description="List of rows with errors"
    )

    @property
    def success_rate(self) -> float:
        """Calculate success rate as a percentage."""
        if self.total == 0:
            return 100.0
        return (self.resolved / self.total) * 100

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0
