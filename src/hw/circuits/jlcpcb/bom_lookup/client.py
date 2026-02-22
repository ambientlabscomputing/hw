"""JLCPCB parts search via server-side rendered HTML scraping.

JLCPCB uses Nuxt.js with SSR — component data is embedded in the HTML
inside a compressed ``__NUXT__`` JavaScript function. We fetch the search
results page with httpx, extract the function's parameter/argument
mapping, and resolve each component record's fields to their actual values.

No browser automation (Playwright) is needed since all data is in the
initial HTML response.
"""

from __future__ import annotations

import re

import httpx

from hw import logger
from hw.circuits.jlcpcb.bom_lookup.models import JlcpcbSearchResult

JLCPCB_SEARCH_URL = "https://jlcpcb.com/parts/componentSearch"
TIMEOUT = 15.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Nuxt SSR payload decoder
# ---------------------------------------------------------------------------


def _parse_nuxt_args(args_str: str) -> list[str]:
    """Parse the comma-separated argument list of the __NUXT__ IIFE.

    Handles quoted strings, escaped characters, and nested structures so
    that commas inside strings or braces are not treated as delimiters.
    """
    args: list[str] = []
    cur = ""
    in_str = False
    str_char: str | None = None
    depth = 0
    i = 0
    while i < len(args_str):
        ch = args_str[i]
        if in_str:
            cur += ch
            # Handle escape sequences
            if ch == "\\" and i + 1 < len(args_str):
                cur += args_str[i + 1]
                i += 2
                continue
            if ch == str_char:
                in_str = False
        elif ch in ('"', "'"):
            in_str = True
            str_char = ch
            cur += ch
        elif ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        elif ch in ("(", "[", "{"):
            depth += 1
            cur += ch
        elif ch in (")", "]", "}"):
            depth -= 1
            cur += ch
        else:
            cur += ch
        i += 1
    if cur.strip():
        args.append(cur.strip())
    return args


def _build_param_map(html: str) -> dict[str, str]:
    """Extract the ``__NUXT__`` IIFE and build a parameter → value map.

    The Nuxt SSR payload looks like:

        window.__NUXT__=(function(a,b,c,...){return {…}}(val_a,val_b,val_c,...))

    We extract the parameter names and their corresponding argument values
    and return a dict mapping each short variable name to its literal value.
    """
    nuxt_start = html.find("__NUXT__=(function(")
    if nuxt_start == -1:
        return {}

    # Parameters: between first '(' and first ')'
    params_start = nuxt_start + len("__NUXT__=(function(")
    params_end = html.find(")", params_start)
    params = html[params_start:params_end].split(",")

    # Arguments: between the last '}(' and the final '))'
    last_brace_paren = html.rfind("}(")
    if last_brace_paren == -1:
        return {}
    args_start = last_brace_paren + 2
    args_end = html.rfind("))")
    if args_end == -1 or args_end <= args_start:
        return {}

    args = _parse_nuxt_args(html[args_start:args_end])

    pm: dict[str, str] = {}
    for idx, p in enumerate(params):
        p = p.strip()
        if p and idx < len(args):
            pm[p] = args[idx]
    return pm


def _resolve(value: str | None, pm: dict[str, str]) -> str | None:
    """Resolve a single value which may be a literal or a Nuxt variable ref."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    # Already a string literal
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1]
    # Boolean / special JS values
    if v in ("void 0", "undefined", "null", "!1", "!0"):
        return None
    # Try variable resolution
    if v in pm:
        r = pm[v]
        if len(r) >= 2 and r[0] == '"' and r[-1] == '"':
            return r[1:-1]
        if r in ("void 0", "undefined", "null"):
            return None
        return r
    return v


# ---------------------------------------------------------------------------
# Component record extraction
# ---------------------------------------------------------------------------

_COMPONENT_CODE_RE = re.compile(r'componentCode:"(C\d+)"')


def _extract_field(key: str, ctx: str) -> str | None:
    """Pull the raw value of *key* from a chunk of Nuxt object notation."""
    m = re.search(key + r":([^,}{]+)", ctx)
    return m.group(1) if m else None


def _parse_components(html: str) -> list[JlcpcbSearchResult]:
    """Parse all component records embedded in the Nuxt SSR payload."""
    pm = _build_param_map(html)

    results: list[JlcpcbSearchResult] = []

    for m in _COMPONENT_CODE_RE.finditer(html):
        code = m.group(1)
        # Grab a window of context around each componentCode occurrence
        start = max(0, m.start() - 2000)
        end = min(len(html), m.end() + 500)
        ctx = html[start:end]

        def _get(field: str) -> str | None:
            return _resolve(_extract_field(field, ctx), pm)

        stock_raw = _get("stockCount")
        try:
            stock = int(stock_raw) if stock_raw else 0
        except (ValueError, TypeError):
            stock = 0

        desc = _get("describe") or ""
        spec = _get("componentSpecificationEn")
        brand = _get("componentBrandEn")
        model = _get("componentModelEn")
        name = _get("componentName") or ""

        # Build a description from available fields
        description = desc if desc else name

        results.append(
            JlcpcbSearchResult(
                lcsc_part=code,
                description=description,
                manufacturer=brand,
                mfr_part=model,
                package=spec,
                stock=stock,
                price=None,  # Price requires JS evaluation; not available in SSR
                source="jlcpcb",
            )
        )

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_jlcpcb(query: str) -> list[JlcpcbSearchResult]:
    """Search JLCPCB parts by scraping the SSR search results page.

    Args:
        query: Search term (e.g. ``"100nF"``, ``"ESP32-S3"``)

    Returns:
        Parsed component records from the Nuxt SSR payload.
    """
    logger.debug(f"Searching JLCPCB for: {query}")

    try:
        with httpx.Client(
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            response = client.get(
                JLCPCB_SEARCH_URL,
                params={"searchTxt": query},
            )
            response.raise_for_status()

        results = _parse_components(response.text)
        logger.debug(f"Found {len(results)} results from JLCPCB for '{query}'")
        return results

    except httpx.HTTPStatusError as e:
        logger.warning(
            f"JLCPCB search failed for '{query}': HTTP {e.response.status_code}"
        )
        return []
    except httpx.HTTPError as e:
        logger.warning(f"JLCPCB search failed for '{query}': {e}")
        return []
    except Exception as e:
        logger.warning(f"Unexpected error searching JLCPCB for '{query}': {e}")
        return []


def _sanitize_query(comment: str) -> str:
    """Clean up a BOM comment to produce a better search query.

    KiCad BOM comments often contain notation like ``120R@100MHz`` or
    ``10uF/10V`` that confuse JLCPCB's search.  We replace separators
    with spaces so the search engine can match individual terms.
    """
    q = comment.strip()
    # Replace common separators with spaces
    q = re.sub(r"[@/\\]", " ", q)
    # Collapse multiple spaces
    q = re.sub(r"\s+", " ", q).strip()
    return q


def search_part(comment: str, footprint: str) -> list[JlcpcbSearchResult]:
    """Search for a part on JLCPCB.

    JLCPCB's parts library already includes LCSC (C-number) parts, so a
    single search covers both sources.

    Args:
        comment: Part value/comment (e.g. ``"100nF"``, ``"ESP32-S3"``)
        footprint: Component footprint (e.g. ``"C_0402_1005Metric"``)

    Returns:
        List of search results, deduplicated by C-number.
    """
    logger.info(f"Searching for part: {comment} ({footprint})")

    query = _sanitize_query(comment)
    results = search_jlcpcb(query)

    # Deduplicate by C-number (shouldn't be needed, but just in case)
    seen: dict[str, JlcpcbSearchResult] = {}
    for r in results:
        if r.lcsc_part and r.lcsc_part not in seen:
            seen[r.lcsc_part] = r
    deduped = list(seen.values())

    logger.info(f"Found {len(deduped)} unique parts for '{comment}'")
    return deduped
