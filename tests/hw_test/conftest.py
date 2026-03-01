"""Shared fixtures and factories for shop-related tests."""

from hw.circuits.models.bom import BOMItem
from hw.circuits.models.part import Part
from hw.circuits.shop.models import ShoppingPlan, ShoppingPlanItem
from hw.circuits.shop.search import PartSearchPort, PartSearchQuery

# ---------------------------------------------------------------------------
# Factories / Builders
# ---------------------------------------------------------------------------


def make_part(
    part_number: str = "LM358",
    source_part_number: str | None = "296-1395-5-ND",
    distributor_name: str | None = "DigiKey",
    quantity_in_stock: int | None = 1000,
    unit_price: float | None = 0.47,
    references: list[str] | None = None,
    **kwargs,
) -> Part:
    """Factory for Part with sensible defaults."""
    return Part(
        part_number=part_number,
        source_part_number=source_part_number,
        distributor_name=distributor_name,
        quantity_in_stock=quantity_in_stock,
        unit_price=unit_price,
        references=references,
        value=kwargs.get("value", part_number),
        footprint=kwargs.get("footprint", ""),
        price_breaks=kwargs.get("price_breaks", []),
        currency=kwargs.get("currency", "USD"),
        buy_now_url=kwargs.get("buy_now_url"),
        datasheet_url=kwargs.get("datasheet_url"),
        lifecycle=kwargs.get("lifecycle"),
        package=kwargs.get("package"),
    )


def make_bom_item(
    references: list[str] | None = None,
    value: str = "10kΩ",
    footprint: str = "",
    part_number: str | None = None,
    **kwargs,
) -> BOMItem:
    """Factory for BOMItem with sensible defaults."""
    return BOMItem(
        references=references or ["R1"],
        value=value,
        footprint=footprint,
        part_number=part_number,
        vendor=kwargs.get("vendor"),
    )


def make_shopping_plan_item(
    bom_item: BOMItem | None = None,
    candidates: list[Part] | None = None,
    **kwargs,
) -> ShoppingPlanItem:
    """Factory for ShoppingPlanItem with sensible defaults."""
    if bom_item is None:
        bom_item = make_bom_item()
    return ShoppingPlanItem(
        bom_item=bom_item,
        candidates=candidates or [],
        error=kwargs.get("error"),
    )


def make_shopping_plan(
    items: list[ShoppingPlanItem] | None = None,
    bom_file: str = "test.csv",
    vendors_filter: list[str] | None = None,
    max_vendors: int = 3,
    **kwargs,
) -> ShoppingPlan:
    """Factory for ShoppingPlan with sensible defaults."""
    if items is None:
        items = [make_shopping_plan_item()]
    return ShoppingPlan(
        items=items,
        bom_file=bom_file,
        vendors_filter=vendors_filter or [],
        max_vendors=max_vendors,
    )


# ---------------------------------------------------------------------------
# Fake Search Adapter
# ---------------------------------------------------------------------------


class FakeAdapter(PartSearchPort):
    """Mock PartSearchPort that returns canned results.

    Usage:
        adapter = FakeAdapter()
        adapter.add_result("LM358", [make_part(part_number="LM358")])
        parts = await adapter.search(PartSearchQuery(query="LM358"))
    """

    def __init__(self):
        self._results: dict[str, list[Part]] = {}
        self._raise_on: set[str] = set()

    def add_result(self, query: str, parts: list[Part]) -> None:
        """Register a result for a specific query."""
        self._results[query] = parts

    def add_error(self, query: str) -> None:
        """Make a query raise an exception."""
        self._raise_on.add(query)

    async def search(self, query: PartSearchQuery) -> list[Part]:
        """Return results or raise if configured to do so."""
        if query.query in self._raise_on:
            raise RuntimeError(f"Fake adapter configured to fail on: {query.query}")
        return self._results.get(query.query, [])
