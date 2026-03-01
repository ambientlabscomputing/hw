"""Part resolution logic for selecting the best component from search results."""

import math
import re

from hw import logger
from hw.circuits.jlcpcb.bom_lookup.models import MIN_STOCK, JlcpcbSearchResult
from hw.circuits.query import eia_from_footprint
from hw.circuits.resolver import package_matches_eia as _package_contains_eia

# _extract_eia_code is an alias for eia_from_footprint kept for callers below.
_extract_eia_code = eia_from_footprint


def _expected_category_keywords(footprint: str) -> tuple[str, ...]:
    """Return JLCPCB category keywords that a candidate must match for this footprint.

    When the KiCad footprint prefix unambiguously identifies the component
    category, we require at least one keyword to appear in the candidate's
    JLCPCB category string.  This prevents capacitors from being selected for
    resistor pads, ferrite beads from being selected for fuse pads, etc.

    Returns an empty tuple for footprint prefixes that are ambiguous or where
    category filtering is not applicable (ICs, modules, connectors).
    """
    if footprint.startswith("R_"):
        return ("resistor",)
    if footprint.startswith("C_"):
        return ("capacitor",)
    if footprint.startswith("Fuse_"):
        # JLCPCB categories: "Circuit Protection/Fuses", "PPTC Resettable Fuses"
        return ("fuse", "pptc", "circuit protection")
    # L_ is handled by the dedicated ferrite bead filter
    return ()


def _score_candidate(
    candidate: JlcpcbSearchResult,
    footprint: str = "",
    comment: str = "",
) -> float:
    """Score a candidate by stock, price, dielectric quality, and current rating.

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

    # ── Capacitor dielectric quality ────────────────────────────────────────
    # Stable dielectrics (C0G/NP0/X7R/X5R) get a bonus; poor dielectrics
    # (Y5V/Z5U/Y5U) get a large penalty so they never beat a stable part.
    if footprint.startswith("C_"):
        desc = (candidate.description or "").upper()
        if re.search(r"\bC0G\b|\bNP0\b|\bX7R\b|\bX5R\b", desc):
            score += 20.0
        elif re.search(r"\bY5V\b|\bZ5U\b|\bY5U\b", desc):
            score -= 50.0

    # ── Power inductor current rating ───────────────────────────────────────
    # For inductors (L_ footprint, no @-notation in comment), prefer higher
    # current ratings.  Each additional 100 mA adds ~1 point (capped at +30).
    if footprint.startswith("L_") and "@" not in comment:
        desc = (candidate.description or "").upper()
        current_ma = 0.0
        m_a = re.search(r"(\d+\.?\d*)\s*A(?![A-Z0-9])", desc)
        m_ma = re.search(r"(\d+\.?\d*)\s*MA(?![A-Z0-9])", desc)
        if m_a:
            current_ma = float(m_a.group(1)) * 1000
        elif m_ma:
            current_ma = float(m_ma.group(1))
        score += min(30.0, current_ma / 100.0)

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

    # ── Step 1.2: component-type category filter ────────────────────────────
    # Reject candidates whose JLCPCB category is inconsistent with the KiCad
    # footprint prefix (e.g. reject capacitors for R_ pads, ferrite beads for
    # Fuse_ pads).  This prevents high-stock out-of-category parts from winning.
    category_keywords = _expected_category_keywords(footprint)
    if category_keywords:
        type_matched = [
            c
            for c in in_stock
            if any(kw in (c.category or "").lower() for kw in category_keywords)
        ]
        if type_matched:
            logger.debug(
                f"Category filter {category_keywords}: "
                f"{len(type_matched)}/{len(in_stock)} match expected component type"
            )
            in_stock = type_matched
        else:
            logger.warning(
                f"No candidates match expected category {category_keywords} for "
                f"'{comment}' ({footprint}) — category data may be unavailable; "
                f"proceeding with all in-stock"
            )

    # ── Step 1.5: ferrite bead category filter ──────────────────────────────
    # Ferrite beads share EIA package codes (0402, 0603 …) with resistors and
    # inductors, so a plain package filter is not enough.  When the footprint
    # is an inductor pad (L_…) and the comment uses impedance@frequency
    # notation we know this must be a ferrite bead; discard any candidates
    # that do not belong to a ferrite / inductor category.
    if footprint.startswith("L_") and "@" in comment:
        _FERRITE_KEYWORDS = ("ferrite", "bead", "inductor", "coil", "choke", "emi")
        ferrite_candidates = [
            c
            for c in in_stock
            if any(kw in (c.category or "").lower() for kw in _FERRITE_KEYWORDS)
        ]
        if ferrite_candidates:
            logger.debug(
                f"Ferrite bead filter: {len(ferrite_candidates)}/{len(in_stock)} "
                f"match inductor/ferrite category"
            )
            in_stock = ferrite_candidates
        else:
            logger.warning(
                f"No ferrite/inductor category candidates found for '{comment}' "
                f"— category data may be unavailable; proceeding with all in-stock"
            )

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

    # ── Step 2.5: pin-header pin count and orientation filter ───────────────
    # PinHeader footprints encode the exact pin count and orientation.  These
    # are not captured by the EIA package code (all single-row 2.54mm headers
    # share the same pitch), so we inspect candidate descriptions directly.
    ph_m = re.match(
        r"PinHeader_(\d+)x(\d+)_P[\d.]+mm(?:_(Vertical|Horizontal))?", footprint
    )
    if ph_m:
        ph_rows, ph_cols, ph_orient = ph_m.groups()
        expected_pins = int(ph_rows) * int(ph_cols)

        # ── Pin count sub-filter ────────────────────────────────────────────
        def _desc_has_pin_count(desc: str, n: int) -> bool:
            dl = desc.lower()
            patterns = [
                rf"1[x*×]{n}p\b",  # 1x4P, 1*4P, 1×4P  (JLCPCB style)
                rf"1[x*×]{n}(?!\d)",  # 1x4, 1*4 (no P suffix)
                rf"\b{n}x1\b",  # 4x1 (transposed)
                rf"\b{n}-pin\b",  # 4-pin
                rf"\b{n}pin\b",  # 4pin
                rf"\b{n}\*1\b",  # 4*1
            ]
            return any(re.search(p, dl) for p in patterns)

        pin_matched = [
            c
            for c in candidates_to_rank
            if _desc_has_pin_count(c.description, expected_pins)
        ]
        if pin_matched:
            logger.debug(
                f"Pin header pin count filter ({expected_pins}): "
                f"{len(pin_matched)}/{len(candidates_to_rank)} match"
            )
            candidates_to_rank = pin_matched
        else:
            logger.warning(
                f"No {expected_pins}-pin header description found for '{comment}' "
                f"({footprint}) — skipping pin count filter"
            )

        # ── Orientation sub-filter ──────────────────────────────────────────
        if ph_orient:
            _RA_PATTERN = re.compile(r"right.?angle|horizontal|angled", re.IGNORECASE)
            if ph_orient == "Vertical":
                # Straight/vertical: exclude anything advertising right-angle
                orient_matched = [
                    c
                    for c in candidates_to_rank
                    if not _RA_PATTERN.search(c.description)
                ]
            else:  # Horizontal / right-angle
                orient_matched = [
                    c for c in candidates_to_rank if _RA_PATTERN.search(c.description)
                ]
            if orient_matched:
                logger.debug(
                    f"Pin header orientation filter ({ph_orient}): "
                    f"{len(orient_matched)}/{len(candidates_to_rank)} match"
                )
                candidates_to_rank = orient_matched
            else:
                logger.warning(
                    f"No {ph_orient} orientation candidates found for '{comment}' "
                    f"({footprint}) — skipping orientation filter"
                )

    # ── Step 3: rank and select ─────────────────────────────────────────────
    selected = max(
        candidates_to_rank, key=lambda c: _score_candidate(c, footprint, comment)
    )

    logger.info(
        f"Selected {selected.lcsc_part} for '{comment}' "
        f"(stock: {selected.stock}, package: {selected.package},\
 source: {selected.source})"
    )

    return selected, None
