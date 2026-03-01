"""Plan generation workflow: searches each BOM item across distributors."""

import asyncio

from hw import logger
from hw.circuits.models.bom import BOM
from hw.circuits.models.part import Part
from hw.circuits.query import build_search_query
from hw.circuits.resolver import filter_candidates
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
    bom_item_footprint: str,
    bom_item_part_number: str | None,
    max_vendors: int,
    vendors_filter: list[str],
) -> tuple[list[Part], str | None]:
    """Search for a single BOM item and return (ranked candidates, error).

    Search strategy:
    1. If the BOM item has an explicit MPN, try that first (it's already a
       precise identifier — no query transformation needed).
    2. Otherwise (or on MPN search failure), build an optimised query from
       the value + footprint using ``build_search_query``, which appends EIA
       codes, "ohm" suffixes for bare-number resistors, "ferrite bead" for
       impedance-at-frequency values, and extracts connector models from the
       footprint name.
    3. Apply ``filter_candidates`` to remove wrong-package or wrong-type
       results before ranking.

    Returns:
        A tuple of ``(candidates, error_message)``.  ``error_message`` is
        ``None`` on success and a human-readable string on failure.
    """
    error: str | None = None
    results: list[Part] = []

    # ── Attempt 1: explicit MPN (if provided) ────────────────────────────────
    if bom_item_part_number:
        try:
            results = await adapter.search(PartSearchQuery(query=bom_item_part_number))
            logger.debug(
                f"MPN search '{bom_item_part_number}': {len(results)} raw results"
            )
        except Exception as exc:
            logger.warning(
                f"MPN search failed for '{bom_item_part_number}': {exc}; "
                f"falling back to value query"
            )
            error = f"MPN search failed: {exc}"
            results = []

    # ── Attempt 2: built query from value + footprint ─────────────────────────
    if not results:
        query_str = build_search_query(bom_item_value, bom_item_footprint)
        logger.debug(
            f"Value query for '{bom_item_value}' ({bom_item_footprint}): "
            f"'{query_str}'"
        )
        try:
            results = await adapter.search(PartSearchQuery(query=query_str))
            logger.debug(f"Value query '{query_str}': {len(results)} raw results")
            error = None  # success — clear any earlier MPN error
        except Exception as exc:
            logger.warning(f"Value query '{query_str}' failed: {exc}")
            error = str(exc)
            return [], error

    if not results:
        return [], "No results returned by distributor API"

    # ── Filter: remove wrong-package / wrong-type candidates ─────────────────
    results = filter_candidates(results, bom_item_footprint, bom_item_value)

    # ── Vendor filter + rank + slice ──────────────────────────────────────────
    filtered = [p for p in results if _matches_vendor_filter(p, vendors_filter)]
    if not filtered and results:
        # All results were from non-requested vendors — keep them rather than
        # returning nothing, so the user can see what *is* available.
        filtered = results

    ranked = sorted(filtered, key=_rank)
    return ranked[:max_vendors], None


async def generate_plan(
    bom: BOM,
    adapter: OemSecretsAPIAdapter | None = None,
    max_vendors: int = 3,
    vendors_filter: list[str] | None = None,
    on_progress: object = None,
    max_concurrent: int = 5,
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
        max_concurrent: Maximum number of concurrent search requests (default: 5).

    Returns:
        A :class:`ShoppingPlan` with candidates ranked best-first.
    """
    if adapter is None:
        adapter = OemSecretsAPIAdapter()
    _vendors = vendors_filter or []

    # Rate limiting semaphore to prevent overwhelming the API
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _process(idx: int, bom_item) -> ShoppingPlanItem:
        async with semaphore:
            candidates, err = await _search_item(
                adapter=adapter,
                bom_item_value=bom_item.value,
                bom_item_footprint=bom_item.footprint,
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
        return ShoppingPlanItem(bom_item=bom_item, candidates=candidates, error=err)

    tasks = [_process(i, item) for i, item in enumerate(bom.items)]
    plan_items = await asyncio.gather(*tasks)

    return ShoppingPlan(
        bom_file=bom.filename or "",
        max_vendors=max_vendors,
        vendors_filter=_vendors,
        items=list(plan_items),
    )
