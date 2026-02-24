"""Data models for the shopping plan workflow."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from hw.circuits.models.bom import BOMItem
from hw.circuits.models.part import Part


class ShoppingPlanItem(BaseModel):
    """One BOM line item paired with ranked vendor sourcing candidates."""

    bom_item: BOMItem
    candidates: list[Part] = Field(
        default_factory=list,
        description="Vendor options ranked best-first (most stock, lowest price).",
    )

    @property
    def best(self) -> Part | None:
        """The top-ranked candidate, or None if no match was found."""
        return self.candidates[0] if self.candidates else None

    @property
    def is_sourced(self) -> bool:
        return self.best is not None


class ShoppingPlan(BaseModel):
    """A complete shopping plan generated from a BOM file."""

    bom_file: str = Field(description="Path to the source BOM file.")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 timestamp when the plan was generated.",
    )
    vendors_filter: list[str] = Field(
        default_factory=list,
        description="Vendor names the plan was constrained to (empty = all).",
    )
    max_vendors: int = Field(
        3, description="Max candidate vendor options retained per BOM item."
    )
    items: list[ShoppingPlanItem] = Field(
        ..., description="Plan entries, one per BOM line item."
    )

    # -----------------------------------------------------------------------
    # Convenience helpers
    # -----------------------------------------------------------------------

    @property
    def sourced_count(self) -> int:
        return sum(1 for i in self.items if i.is_sourced)

    @property
    def unsourced_count(self) -> int:
        return len(self.items) - self.sourced_count

    def items_for_distributor(self, name: str) -> list[ShoppingPlanItem]:
        """Return items whose best candidate is from the named distributor.

        Matching is case-insensitive and checks if ``name`` appears anywhere
        in the distributor_name string.
        """
        name_lower = name.lower()
        return [
            item
            for item in self.items
            if item.best
            and item.best.distributor_name
            and name_lower in item.best.distributor_name.lower()
        ]
