"""Part resolution logic for selecting the best component from search results."""

import math
import re

from hw import logger
from hw.circuits.jlcpcb.bom_lookup.models import MIN_STOCK, JlcpcbSearchResult

# Standard EIA/IPC SMD package codes that appear in KiCad footprint names.
# When a BOM footprint contains one of these, it is mandatory that the selected
# part's package also contains the same code.  We cannot substitute a different
# package size — the pads literally won't line up.
_EIA_CODES = {
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


def _extract_eia_code(footprint: str) -> str | None:
    """Return the EIA package code embedded in a KiCad footprint string, or None.

    Examples:
        "C_0402_1005Metric"  -> "0402"
        "R_0805_2012Metric"  -> "0805"
        "ESP32-S3-WROOM-1"   -> None
        "PinHeader_1x04_..."  -> None
    """
    for code in re.findall(r"\d{4}", footprint):
        if code in _EIA_CODES:
            return code
    return None


def _package_contains_eia(package: str | None, eia_code: str) -> bool:
    """Return True if *package* contains *eia_code* as a standalone token."""
    if not package:
        return False
    return bool(re.search(r"(?<![0-9])" + re.escape(eia_code) + r"(?![0-9])", package))


def _score_candidate(candidate: JlcpcbSearchResult) -> float:
    """Score a candidate by stock and price.

    Footprint filtering happens before scoring, so we do not award footprint
    points here — that would mask mismatches.
    """
    score = 0.0

    # Log-scale stock score so a 35M-stock part doesn't crush everything else
    if candidate.stock > 0:
        score += min(100.0, math.log10(candidate.stock) * 20)

    # Lower price is better
    if candidate.price is not None and candidate.price > 0:
        score += min(30.0, 30.0 / (1.0 + candidate.price))

    return score


def resolve_part(
    comment: str,
    footprint: str,
    candidates: list[JlcpcbSearchResult],
) -> tuple[JlcpcbSearchResult | None, str | None]:
    """Select the best part from search results.

    Algorithm:
    1. Reject parts with insufficient stock.
    2. If the BOM footprint contains a standard EIA package code, **require** that
       the candidate's package field also contains that code.  Parts with a null
       or mismatched package are excluded entirely — we never substitute a different
       physical size.
    3. If no EIA code is present (ICs, connectors, modules …) fall back to all
       in-stock candidates and warn the user to verify the selection.
    4. Rank remaining candidates by stock / price and return the top result.

    Returns:
        ``(selected, None)`` on success, ``(None, error_message)`` on failure.
    """
    logger.info(
        f"Resolving part: {comment} ({footprint}) from {len(candidates)} candidates"
    )

    if not candidates:
        return None, "No search results found"

    # ── Step 1: stock filter ────────────────────────────────────────────────
    in_stock = [c for c in candidates if c.stock >= MIN_STOCK]
    if not in_stock:
        max_stock = max(c.stock for c in candidates)
        return (
            None,
            f"All candidates out of stock (max available: \
{max_stock}, need: {MIN_STOCK})",
        )

    logger.debug(f"{len(in_stock)}/{len(candidates)} candidates have sufficient stock")

    # ── Step 2: footprint filter ────────────────────────────────────────────
    eia_code = _extract_eia_code(footprint)

    if eia_code:
        matched = [c for c in in_stock if _package_contains_eia(c.package, eia_code)]

        if not matched:
            with_package = [c for c in in_stock if c.package]
            if with_package:
                found_packages = ", ".join(
                    sorted({c.package for c in with_package if c.package})[:5]
                )
                return (
                    None,
                    f"No {eia_code} package match found. "
                    f"Available packages: {found_packages}",
                )
            return (
                None,
                f"No {eia_code} package match found "
                f"({len(in_stock)} in-stock candidates had no package info)",
            )

        logger.debug(
            f"{len(matched)}/{len(in_stock)} candidates match package '{eia_code}'"
        )
        candidates_to_rank = matched

    else:
        # No EIA code — IC, connector, module, etc. Skip package filter but warn.
        logger.warning(
            f"No EIA package code in footprint '{footprint}' — "
            f"skipping package filter for '{comment}'. Verify selection manually."
        )
        candidates_to_rank = in_stock

    # ── Step 3: rank and select ─────────────────────────────────────────────
    selected = max(candidates_to_rank, key=_score_candidate)

    logger.info(
        f"Selected {selected.lcsc_part} for '{comment}' "
        f"(stock: {selected.stock}, package: {selected.package},\
 source: {selected.source})"
    )

    return selected, None
