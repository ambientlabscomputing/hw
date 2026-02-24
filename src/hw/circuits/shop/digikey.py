"""DigiKey cart integration via URL-based add-to-cart scheme.

DigiKey supports adding items to a shopping cart by constructing a URL with
``?part=DIGIKEY_PN|QTY`` query parameters. No authentication is required —
the user just needs to be logged in (or proceed as guest) in their browser.

URL format:
    https://www.digikey.com/ordering/shoppingcart?part=296-1395-5-ND|1&part=296-6501-5-ND|10
"""

from hw.circuits.models.part import Part
from hw.circuits.shop.models import ShoppingPlanItem

_DIGIKEY_CART_BASE = "https://www.digikey.com/ordering/shoppingcart"

DIGIKEY_NAMES = {"digikey", "digi-key", "digi key"}


def is_digikey(part: Part) -> bool:
    """Return True if the part's distributor is DigiKey."""
    if not part.distributor_name:
        return False
    dn = part.distributor_name.lower().replace(".", "").replace("-", " ").strip()
    return any(alias in dn for alias in DIGIKEY_NAMES)


def build_cart_url(items: list[ShoppingPlanItem]) -> str | None:
    """Build a DigiKey add-to-cart URL for the given plan items.

    Only items whose best candidate is fulfilled by DigiKey are included.
    Returns ``None`` if no DigiKey items are present.

    The distributor part number (``source_part_number``) is preferred over the
    manufacturer part number because DigiKey's cart URL requires their own
    catalog number (e.g. ``296-1395-5-ND``, not ``LM358DR``).

    Args:
        items: Plan items to source. Only DigiKey-sourced ones are included.

    Returns:
        A fully-qualified DigiKey shopping cart URL, or ``None``.
    """
    params: list[str] = []
    for item in items:
        best = item.best
        if not best or not is_digikey(best):
            continue
        dk_pn = best.source_part_number or best.part_number
        qty = best.quantity_needed or item.bom_item.quantity
        params.append(f"part={dk_pn}|{qty}")

    if not params:
        return None

    return f"{_DIGIKEY_CART_BASE}?" + "&".join(params)
