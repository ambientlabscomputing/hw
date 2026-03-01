"""Mouser Electronics cart integration via the Mouser REST API.

API docs: https://api.mouser.com/api/docs/ui/index

Authentication: API key as a query parameter (``?apiKey=...``).
Obtain a key at https://www.mouser.com/MyMouser/Api-Search/ApiKeyCreation.

The Mouser API creates a persistent server-side cart identified by a
``CartKey`` UUID. There is no browser checkout URL -- users must log in to
mouser.com to view and complete their cart. The cart created via API is
visible in their account once they sign in.
"""

import httpx
from pydantic import BaseModel, Field

from hw.circuits.models.part import Part
from hw.circuits.shop.models import ShoppingPlanItem

_CART_INSERT_URL = "https://api.mouser.com/api/v1/cart/items/insert"

MOUSER_NAMES = {"mouser", "mouser electronics"}


def is_mouser(part: Part) -> bool:
    """Return True if the part's distributor is Mouser."""
    if not part.distributor_name:
        return False
    dn = part.distributor_name.lower().strip()
    return any(alias in dn for alias in MOUSER_NAMES)


class MouserCartResult(BaseModel):
    """Result of adding items to a Mouser cart."""

    cart_key: str = Field(..., description="The Mouser cart key UUID.")
    item_count: int = Field(default=0, description="Total items in the cart.")
    merchandise_total: float | None = Field(
        default=None, description="Total merchandise price."
    )
    errors: list = Field(
        default_factory=list, description="Any API errors encountered."
    )


async def add_items_to_cart(
    items: list[ShoppingPlanItem],
    api_key: str,
    cart_key: str | None = None,
    country_code: str = "US",
    currency_code: str = "USD",
) -> MouserCartResult:
    """Add Mouser-sourced plan items to a Mouser cart via the API.

    Only items whose best candidate is fulfilled by Mouser are included.
    Non-Mouser items are silently skipped.

    Args:
        items: All plan items.
        api_key: Mouser API key.
        cart_key: Existing cart UUID to append to (creates new cart if omitted).
        country_code: ISO country code (default ``US``).
        currency_code: Currency code (default ``USD``).

    Returns:
        A :class:`MouserCartResult` with the cart key, totals, and any errors.

    Raises:
        httpx.HTTPStatusError: On a non-2xx response from Mouser.
    """
    cart_items = []
    for item in items:
        best = item.best
        if not best or not is_mouser(best):
            continue
        qty = best.quantity_needed or item.bom_item.quantity
        cart_items.append(
            {
                "MouserPartNumber": best.source_part_number or best.part_number,
                "Quantity": qty,
                "CustomerPartNumber": ", ".join(item.bom_item.references[:3]),
            }
        )

    if not cart_items:
        return MouserCartResult(
            cart_key=cart_key or "",
            item_count=0,
            merchandise_total=None,
            errors=["No Mouser items found in plan."],
        )

    payload: dict = {"CartItems": cart_items}
    if cart_key:
        payload["CartKey"] = cart_key

    params = {
        "apiKey": api_key,
        "countryCode": country_code,
        "currencyCode": currency_code,
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(_CART_INSERT_URL, params=params, json=payload)
        resp.raise_for_status()

    data = resp.json()
    errors = [e.get("Message", str(e)) for e in data.get("Errors", [])]
    returned_key = data.get("CartKey") or cart_key or ""
    total_raw = data.get("MerchandiseTotal")
    total = float(total_raw) if total_raw is not None else None

    return MouserCartResult(
        cart_key=returned_key,
        item_count=len(cart_items),
        merchandise_total=total,
        errors=errors,
    )
