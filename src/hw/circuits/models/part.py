from pydantic import BaseModel, Field


class PriceBreak(BaseModel):
    """A quantity-based price break from a distributor."""

    qty: int = Field(..., description="Minimum order quantity to reach this price.")
    unit_price: float = Field(
        ..., description="Unit price at this quantity break (in `currency`)."
    )


class Part(BaseModel):
    """A normalized part result returned from a distributor search.

    This is the canonical, vendor-agnostic representation used throughout
    the shop workflow. It is populated by the OEM Secrets adapter (which
    aggregates multiple distributors) and consumed by the plan and order steps.
    """

    part_number: str = Field(..., description="Manufacturer part number.")
    source_part_number: str | None = Field(
        None,
        description="Distributor's own catalog number (e.g. DigiKey PN '296-1395-5-ND').",  # noqa: E501
    )

    # BOM linkage (optional — set when a Part is matched against a BOMItem)
    references: list[str] | None = Field(
        None,
        description="PCB reference designators this part satisfies (e.g. ['R1', 'R2']).",  # noqa: E501
    )
    value: str = Field(
        "",
        description="Value or description (e.g. '10kΩ', '100nF', 'STM32F4').",
    )
    footprint: str = Field(
        "",
        description="PCB footprint (e.g. 'R_0603', 'SOT-23').",
    )

    # Distributor / sourcing fields (populated from OEM Secrets search)
    distributor_name: str | None = Field(
        None, description="Distributor common name (e.g. 'DigiKey', 'Mouser')."
    )
    quantity_in_stock: int | None = Field(
        None, description="Units currently in stock at the distributor."
    )
    unit_price: float | None = Field(
        None, description="Unit price at qty=1 in `currency`."
    )
    price_breaks: list[PriceBreak] = Field(
        default_factory=list,
        description="All available quantity price breaks.",
    )
    currency: str = Field("USD", description="Currency for all price fields.")
    buy_now_url: str | None = Field(
        None, description="Distributor product page / add-to-cart URL."
    )
    datasheet_url: str | None = Field(None, description="Manufacturer datasheet URL.")
    lifecycle: str | None = Field(
        None, description="Life-cycle status (e.g. 'Active', 'NRND', 'Obsolete')."
    )
    package: str | None = Field(
        None,
        description=(
            "EIA package code or package description inferred from the MPN "
            "(e.g. '0402', '0603').  Populated by infer_package_from_mpn() "
            "when the distributor API does not return structured package data."
        ),
    )

    @property
    def quantity_needed(self) -> int:
        """Number of placements for the matched BOM references."""
        return len(self.references) if self.references else 0
