"""Plan generation workflow: searches each BOM item across distributors."""

import asyncio

from hw.circuits.models.bom import BOM
from hw.circuits.models.part import Part
from hw.circuits.shop.models import ShoppingPlan, ShoppingPlanItem
from hw.circuits.shop.search import OemSecretsAPIAdapter, PartSearchQuery


def _rank(part: Part) -> tuple:
    """Sort key: in-stock parts first, then most stock, then lowest price."""
    in_stock = 1 if (part.quantity_in_stock or 0) > 0 else 0
    price = part.unit_price if part.unit_price is not None else 9_999_999.0
    return (-in_stock, -(part.quantity_in_stock or 0), price)


def _matches_vendor_filter(part: Part, vendors_filter: list[str]) -> bool:
    if not vendors_filter:
        return True
    if not part.distributor_name:
        return False
    dn = part.distributor_name.lower()
    return any(v.lower() in dn for v in vendors_filter)


async def _search_item(
    adapter: OemSecretsAPIAdapter,
    bom_item_value: str,
    bom_item_part_number: str | None,
    max_vendors: int,
    vendors_filter: list[str],
) -> list[Part]:
    """Search for a single BOM item and return ranked candidates."""
    query_str = bom_item_part_number or bom_item_value
    try:
        results = await adapter.search(PartSearchQuery(query=query_str))
    except Exception:
        # Fallback to value if part_number search returned nothing
        if bom_item_part_number:
            try:
                results = await adapter.search(PartSearchQuery(query=bom_item_value))
            except Exception:
                return []
        else:
            return []

    filtered = [p for p in results if _matches_vendor_filter(p, vendors_filter)]
    ranked = sorted(filtered, key=_rank)
    return ranked[:max_vendors]


async def generate_plan(
    bom: BOM,
    adapter: OemSecretsAPIAdapter | None = None,
    max_vendors: int = 3,
    vendors_filter: list[str] | None = None,
    on_progress: object = None,
) -> ShoppingPlan:
    """Generate a shopping plan from a BOM by searching all items in parallel.

    Args:
        bom: Parsed BOM to source.
        adapter: OEM Secrets adapter (created automatically if omitted).
        max_vendors: Maximum candidate options to keep per BOM line item.
        vendors_filter: Restrict candidates to these distributor names (partial
            case-insensitive match). Empty/None means all distributors.
        on_progress: Optional callable invoked after each item completes;
            receives ``(index: int, total: int)`` for progress reporting.

    Returns:
        A :class:`ShoppingPlan` with candidates ranked best-first.
    """
    if adapter is None:
        adapter = OemSecretsAPIAdapter()
    _vendors = vendors_filter or []

    async def _process(idx: int, bom_item) -> ShoppingPlanItem:
        candidates = await _search_item(
            adapter=adapter,
            bom_item_value=bom_item.value,
            bom_item_part_number=bom_item.part_number,
            max_vendors=max_vendors,
            vendors_filter=_vendors,
        )
        # Tag each candidate with the BOM linkage fields
        for candidate in candidates:
            candidate.references = bom_item.references
            candidate.value = bom_item.value
            candidate.footprint = bom_item.footprint
        if callable(on_progress):
            on_progress(idx + 1, len(bom.items))
        return ShoppingPlanItem(bom_item=bom_item, candidates=candidates)

    tasks = [_process(i, item) for i, item in enumerate(bom.items)]
    plan_items = await asyncio.gather(*tasks)

    return ShoppingPlan(
        bom_file=bom.filename or "",
        max_vendors=max_vendors,
        vendors_filter=_vendors,
        items=list(plan_items),
    )
