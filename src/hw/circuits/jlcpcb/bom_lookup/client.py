"""JLCPCB parts search via Playwright browser automation.

JLCPCB renders search results via Nuxt.js SSR.  The initial HTML embeds a
compressed ``window.__NUXT__`` IIFE whose variable references are only
resolved *after* the inline script executes in a real browser.  We use
Playwright to navigate to the search page and call ``page.evaluate()`` to
read the fully-resolved JavaScript object — giving us accurate package
codes, stock counts, and pricing without fragile regex-based decompression.

A single Chromium browser instance is shared across all searches in one
process and closed automatically on exit.
"""

from __future__ import annotations

import atexit
import re
import urllib.parse
from typing import TYPE_CHECKING

from hw import logger
from hw.circuits.jlcpcb.bom_lookup.models import JlcpcbSearchResult

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

JLCPCB_SEARCH_URL = "https://jlcpcb.com/parts/componentSearch"
TIMEOUT = 30_000  # milliseconds (Playwright uses ms)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Playwright browser singleton
# ---------------------------------------------------------------------------

_playwright_ctx = None
_browser: Browser | None = None
_page: Page | None = None


def _get_page() -> Page:
    """Return a shared Playwright page, launching the browser on first call."""
    global _playwright_ctx, _browser, _page
    if _page is not None:
        return _page

    from playwright.sync_api import sync_playwright

    _playwright_ctx = sync_playwright().start()
    _browser = _playwright_ctx.chromium.launch(headless=True)
    _page = _browser.new_page(user_agent=USER_AGENT)
    atexit.register(_close_browser)
    logger.debug("Playwright Chromium browser launched")
    return _page


def _close_browser() -> None:
    """Shut down the shared browser on process exit."""
    global _playwright_ctx, _browser, _page
    try:
        if _browser:
            _browser.close()
        if _playwright_ctx:
            _playwright_ctx.stop()
    except Exception:
        pass
    _playwright_ctx = _browser = _page = None


def close_browser() -> None:
    """Explicitly shut down the shared Playwright browser.

    Call this before entering an ``asyncio.run()`` context (e.g. the AI
    research phase) so that Playwright's background event loop is gone and
    the new ``asyncio.run()`` can start its own loop without conflict.
    """
    _close_browser()


# ---------------------------------------------------------------------------
# JavaScript snippet — extracts component list from window.__NUXT__
# ---------------------------------------------------------------------------

# Playwright's page.evaluate() serialises the return value as JSON, so we get
# back a plain Python list of dicts — no JSON.stringify necessary.
_JS_EXTRACT = """\
() => {
    const nuxt = window.__NUXT__;
    if (!nuxt) return [];

    function findComponents(obj, depth) {
        if (depth > 10) return null;
        if (Array.isArray(obj) && obj.length > 0 &&
                obj[0] && typeof obj[0] === 'object' &&
                'componentCode' in obj[0]) {
            return obj;
        }
        if (obj && typeof obj === 'object') {
            for (const v of Object.values(obj)) {
                const r = findComponents(v, depth + 1);
                if (r) return r;
            }
        }
        return null;
    }

    const components = findComponents(nuxt, 0);
    if (!components) return [];

    return components.map(c => ({
        code:       c.componentCode,
        spec:       c.componentSpecificationEn,
        brand:      c.componentBrandEn,
        model:      c.componentModelEn,
        stock:      c.stockCount,
        describe:   c.describe || c.componentName || '',
        category1:  c.firstSortName  || '',
        category2:  c.secondSortName || '',
        discontinue: !!(c.componentDiscontinue || c.discontinue || false),
        price: (
            Array.isArray(c.componentPrices) && c.componentPrices.length > 0
                ? c.componentPrices[0].productPrice
                : null
        ),
    }));
}
"""


# ---------------------------------------------------------------------------
# Component record extraction
# ---------------------------------------------------------------------------


def _extract_components(raw: list[dict]) -> list[JlcpcbSearchResult]:
    """Convert raw dicts from page.evaluate() into JlcpcbSearchResult objects.

    This function is intentionally pure (no I/O) so it can be unit-tested
    without a real browser.

    Args:
        raw: List of component dicts produced by the JS snippet above.

    Returns:
        Parsed and validated search results.
    """
    results: list[JlcpcbSearchResult] = []
    for item in raw:
        code = item.get("code") or ""
        if not code:
            continue

        stock_val = item.get("stock")
        try:
            stock = int(stock_val) if stock_val is not None else 0
        except (ValueError, TypeError):
            stock = 0

        price_val = item.get("price")
        try:
            price = float(price_val) if price_val is not None else None
        except (ValueError, TypeError):
            price = None

        cat1 = item.get("category1") or ""
        cat2 = item.get("category2") or ""
        category = f"{cat1} / {cat2}".strip(" /") if cat2 else cat1

        results.append(
            JlcpcbSearchResult(
                lcsc_part=code,
                description=item.get("describe") or "",
                manufacturer=item.get("brand") or None,
                mfr_part=item.get("model") or None,
                package=item.get("spec") or None,
                stock=stock,
                price=price,
                category=category,
                discontinued=bool(item.get("discontinue", False)),
                source="jlcpcb",
            )
        )
    return results


# ---------------------------------------------------------------------------
# Public search API
# ---------------------------------------------------------------------------


def search_jlcpcb(query: str) -> list[JlcpcbSearchResult]:
    """Search JLCPCB parts by navigating the search page with Playwright.

    Args:
        query: Search term (e.g. ``"100nF"``, ``"SM08B-GHS-TB"``)

    Returns:
        Parsed component records from the fully-resolved Nuxt state.
    """
    logger.debug(f"Searching JLCPCB for: {query!r}")
    url = f"{JLCPCB_SEARCH_URL}?searchTxt={urllib.parse.quote_plus(query)}"

    try:
        page = _get_page()
        # domcontentloaded is sufficient — __NUXT__ is set by an inline
        # <script> tag and is available as soon as the HTML is parsed.
        page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        raw: list[dict] = page.evaluate(_JS_EXTRACT)  # type: ignore[assignment]
    except Exception as e:
        logger.warning(f"Playwright navigation/evaluation failed for {query!r}: {e}")
        return []

    results = _extract_components(raw)
    logger.debug(f"Found {len(results)} results from JLCPCB for {query!r}")
    return results


# ---------------------------------------------------------------------------
# Query building helpers
# ---------------------------------------------------------------------------


def _sanitize_query(comment: str) -> str:
    """Clean up a BOM comment to produce a better search query.

    KiCad BOM comments often contain notation like ``120R@100MHz`` or
    ``10uF/10V`` that confuse JLCPCB's search.  We replace separators
    with spaces so the search engine can match individual terms.
    """
    q = comment.strip()
    q = re.sub(r"[@/\\]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _is_ferrite_bead(comment: str, footprint: str) -> bool:
    """Return True when this BOM row describes a ferrite bead.

    Ferrite beads use inductor footprints (``L_…``) and their comment
    follows the ``<impedance>@<frequency>`` pattern (e.g. ``120R@100MHz``).
    """
    return footprint.startswith("L_") and "@" in comment


def _build_connector_query(comment: str, footprint: str) -> str:
    """Build a targeted search query for connector footprints.

    JLCPCB connector part numbers are model-specific (e.g. ``SM08B-GHS-TB``).
    The KiCad footprint string usually encodes the exact model; we extract it
    so the search returns the right connector family instead of generic headers.

    Falls back to the sanitised comment if no pattern matches.
    """
    # JST any family: JST_GH_SM08B-GHS-TB_1x08-… → "SM08B-GHS-TB"
    #                  JST_PH_S2B-PH-SM4-TB_1x02-… → "S2B-PH-SM4-TB"
    m = re.match(r"JST_[A-Z]+_([\w-]+?)_\d+x\d+", footprint)
    if m:
        return m.group(1)

    # USB-C: USB_C_Receptacle_HRO_TYPE-C-31-M-12 → "TYPE-C-31-M-12"
    m = re.match(r"USB_C_Receptacle_\w+_([\w-]+)", footprint)
    if m:
        return m.group(1)

    # Generic USB: USB_A_Receptacle_Amphenol_10118194 → "10118194"
    m = re.match(r"USB_[A-Z]+_\w+_\w+_([\w-]+)", footprint)
    if m:
        return m.group(1)

    # Pin header: PinHeader_1x04_P2.54mm_Vertical   → "2.54mm 4 pin header vertical"
    #              PinHeader_1x05_P2.54mm_Horizontal → "2.54mm 5 pin header horizontal"
    m = re.match(
        r"PinHeader_(\d+)x(\d+)_P([\d.]+mm)(?:_(Vertical|Horizontal))?", footprint
    )
    if m:
        rows, cols, pitch, orient = m.groups()
        pins = int(rows) * int(cols)
        orient_word = f" {orient.lower()}" if orient else ""
        return f"{pitch} {pins} pin header{orient_word}"

    # Fallback
    return _sanitize_query(comment)


# Standard EIA package codes — mirrors the set in resolver.py.
_EIA_CODES_CLIENT = {
    "0201",
    "0402",
    "0603",
    "0805",
    "1206",
    "1210",
    "1812",
    "2010",
    "2512",
    "1008",
    "1806",
    "2816",
    "0504",
}


def _eia_from_footprint(footprint: str) -> str | None:
    """Return the EIA package code embedded in a KiCad footprint, or None."""
    for code in re.findall(r"\d{4}", footprint):
        if code in _EIA_CODES_CLIENT:
            return code
    return None


def _build_search_query(comment: str, footprint: str) -> str:
    """Choose the best search query for a BOM row.

    Routing:
    * Ferrite beads → comment value + "ferrite bead" keyword
    * Connectors (footprint starts with known prefixes) → model from footprint
    * EIA passives → sanitised comment + EIA code (e.g. ``"47uF 1206"``),
      which steers JLCPCB away from wrong-family matches such as tantalum
      CASE-D caps for a 1206 pad, or DO-27 diodes for a resistor value of 27.
    * Everything else → sanitised comment
    """
    _CONNECTOR_PREFIXES = ("JST_", "USB_", "PinHeader_", "Conn_", "Molex_")

    if _is_ferrite_bead(comment, footprint):
        # "120R@100MHz" → "120R 100MHz ferrite bead"
        return f"{_sanitize_query(comment)} ferrite bead"

    if any(footprint.startswith(p) for p in _CONNECTOR_PREFIXES):
        return _build_connector_query(comment, footprint)

    # Fuses: "1.5A" + Fuse_1206 → "1.5A fuse 1206" (avoids ferrite bead matches)
    if footprint.startswith("Fuse_"):
        base = _sanitize_query(comment)
        eia = _eia_from_footprint(footprint)
        suffix = f" {eia}" if eia and eia not in base else ""
        return f"{base} fuse{suffix}"

    base = _sanitize_query(comment)

    # Resistors: if the comment is a bare number (e.g. "27") with no unit
    # suffix, JLCPCB's full-text search returns kΩ/MΩ parts that happen to
    # share those digits.  Appending "ohm" locks the search to the right
    # resistance family (27Ω, not 82kΩ).
    if footprint.startswith("R_") and re.match(r"^\d+\.?\d*$", base):
        base = f"{base}ohm"

    eia = _eia_from_footprint(footprint)
    if eia and eia not in base:
        return f"{base} {eia}"
    return base


# ---------------------------------------------------------------------------
# Part-detail page helpers (EOL / discontinued detection)
# ---------------------------------------------------------------------------

# JS snippet for the *detail* page.  Unlike the search page (which returns an
# array of components), the detail page embeds a single component object
# somewhere in window.__NUXT__.  We walk the state tree looking for the first
# object that has both ``componentCode`` and ``stockCount`` (same heuristic as
# the search extractor) and pull out the discontinued flag and any alternative
# part code that JLCPCB recommends.
_JS_DETAIL = """\
() => {
    const nuxt = window.__NUXT__;
    if (!nuxt) return null;

    function findComp(obj, depth) {
        if (depth > 15 || obj === null || obj === undefined) return null;
        if (typeof obj !== 'object') return null;
        if (Array.isArray(obj)) {
            for (const v of obj) {
                const r = findComp(v, depth + 1);
                if (r !== null) return r;
            }
            return null;
        }
        if ('componentCode' in obj && 'stockCount' in obj) {
            const status = (obj.productionStatus || '').toUpperCase();
            const discontinued = !!(
                obj.componentDiscontinue ||
                obj.discontinue ||
                status === 'D' ||
                status === 'DISCONTINUED'
            );
            const alt =
                obj.alternativeComponentCode ||
                obj.alternativeCode ||
                obj.substituteComponentCode ||
                obj.alternativePartCode ||
                null;
            return {
                discontinued,
                alternative: (typeof alt === 'string' && alt) ? alt : null,
            };
        }
        for (const v of Object.values(obj)) {
            const r = findComp(v, depth + 1);
            if (r !== null) return r;
        }
        return null;
    }

    return findComp(nuxt, 0);
}
"""

JLCPCB_DETAIL_URL = "https://jlcpcb.com/partdetail"


def fetch_part_detail(lcsc_part: str) -> tuple[bool, str | None]:
    """Fetch the JLCPCB part-detail page and check for EOL / alternative.

    Args:
        lcsc_part: LCSC C-number (e.g. ``"C47647"``)

    Returns:
        ``(discontinued, alternative_lcsc_part)`` where
        *discontinued* is True when JLCPCB marks the part as no longer
        manufactured, and *alternative_lcsc_part* is the C-number of the
        recommended replacement (or None if not specified).
    """
    url = f"{JLCPCB_DETAIL_URL}/{lcsc_part}"
    try:
        page = _get_page()
        page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        result: dict | None = page.evaluate(_JS_DETAIL)  # type: ignore[assignment]
    except Exception as e:
        logger.warning(f"fetch_part_detail failed for {lcsc_part}: {e}")
        return False, None

    if not result:
        return False, None

    discontinued = bool(result.get("discontinued", False))
    alternative = result.get("alternative") or None
    logger.debug(f"{lcsc_part}: discontinued={discontinued}, alternative={alternative}")
    return discontinued, alternative


def search_part(comment: str, footprint: str) -> list[JlcpcbSearchResult]:
    """Search for a part on JLCPCB using a query tuned for the component type.

    Args:
        comment: Part value/comment (e.g. ``"100nF"``, ``"120R@100MHz"``)
        footprint: Component footprint (e.g. ``"C_0402_1005Metric"``)

    Returns:
        List of search results, deduplicated by C-number.
    """
    logger.info(f"Searching for part: {comment!r} ({footprint})")

    query = _build_search_query(comment, footprint)
    results = search_jlcpcb(query)

    # Deduplicate by C-number
    seen: dict[str, JlcpcbSearchResult] = {}
    for r in results:
        if r.lcsc_part and r.lcsc_part not in seen:
            seen[r.lcsc_part] = r
    deduped = list(seen.values())

    logger.info(f"Found {len(deduped)} unique parts for {comment!r}")
    return deduped
