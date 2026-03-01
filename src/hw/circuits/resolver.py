"""Shared part-resolution utilities for the shop workflow.

This module provides package inference and candidate filtering that work with
the vendor-agnostic ``Part`` model used by the multi-distributor shop path.

The JLCPCB path has its own richer resolver (``hw.circuits.jlcpcb.bom_lookup.resolver``)
that operates on ``JlcpcbSearchResult`` objects with structured category and
package fields from JLCPCB's database.  This module handles the harder case
where we only have a manufacturer part number (MPN) and must infer the
package from naming conventions.
"""

from __future__ import annotations

import re

from hw import logger
from hw.circuits.models.part import Part
from hw.circuits.query import eia_from_footprint

# ---------------------------------------------------------------------------
# MPN → package inference
# ---------------------------------------------------------------------------

# Patterns: (compiled regex, inferred EIA code)
# Checked in order; first match wins.
_MPN_PACKAGE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ── Samsung MLCC  (CL + 2-digit "case" code) ───────────────────────────
    # CL03 → 0201, CL05 → 0402, CL10 → 0603, CL21 → 0805, CL31 → 1206,
    # CL32 → 1210, CL43 → 1812
    (re.compile(r"^CL03", re.IGNORECASE), "0201"),
    (re.compile(r"^CL05", re.IGNORECASE), "0402"),
    (re.compile(r"^CL10", re.IGNORECASE), "0603"),
    (re.compile(r"^CL21", re.IGNORECASE), "0805"),
    (re.compile(r"^CL31", re.IGNORECASE), "1206"),
    (re.compile(r"^CL32", re.IGNORECASE), "1210"),
    (re.compile(r"^CL43", re.IGNORECASE), "1812"),
    # ── Murata MLCC  (GRM + 2-digit metric size code) ──────────────────────
    # GRM01 → 0201 (1005 metric skips), GRM03 → 0201, GRM15 → 0402,
    # GRM18 → 0603, GRM21 → 0805, GRM31 → 1206, GRM32 → 1210, GRM43 → 1806
    (re.compile(r"^GRM03", re.IGNORECASE), "0201"),
    (re.compile(r"^GRM15", re.IGNORECASE), "0402"),
    (re.compile(r"^GRM18", re.IGNORECASE), "0603"),
    (re.compile(r"^GRM21", re.IGNORECASE), "0805"),
    (re.compile(r"^GRM31", re.IGNORECASE), "1206"),
    (re.compile(r"^GRM32", re.IGNORECASE), "1210"),
    (re.compile(r"^GRM43", re.IGNORECASE), "1806"),
    # ── Murata GCM (AEC-Q200 MLCC, same metric encoding) ───────────────────
    (re.compile(r"^GCM03", re.IGNORECASE), "0201"),
    (re.compile(r"^GCM15", re.IGNORECASE), "0402"),
    (re.compile(r"^GCM18", re.IGNORECASE), "0603"),
    (re.compile(r"^GCM21", re.IGNORECASE), "0805"),
    (re.compile(r"^GCM31", re.IGNORECASE), "1206"),
    (re.compile(r"^GCM32", re.IGNORECASE), "1210"),
    # ── Taiyo Yuden MLCC  (JMK + 3-digit metric code) ──────────────────────
    # JMK105 → 0402, JMK107 → 0603, JMK212 → 0805, JMK316 → 1206,
    # JMK325 → 1210
    (re.compile(r"^JMK105", re.IGNORECASE), "0402"),
    (re.compile(r"^JMK107", re.IGNORECASE), "0603"),
    (re.compile(r"^JMK212", re.IGNORECASE), "0805"),
    (re.compile(r"^JMK316", re.IGNORECASE), "1206"),
    (re.compile(r"^JMK325", re.IGNORECASE), "1210"),
    # ── TDK MLCC  (C/CGA/CKG + 4-char metric dim prefix) ──────────────────
    # C1005 → 0402, C1608 → 0603, C2012 → 0805, C3216 → 1206, C3225 → 1210
    (re.compile(r"^C(?:GA|KG)?1005", re.IGNORECASE), "0402"),
    (re.compile(r"^C(?:GA|KG)?1608", re.IGNORECASE), "0603"),
    (re.compile(r"^C(?:GA|KG)?2012", re.IGNORECASE), "0805"),
    (re.compile(r"^C(?:GA|KG)?3216", re.IGNORECASE), "1206"),
    (re.compile(r"^C(?:GA|KG)?3225", re.IGNORECASE), "1210"),
    # ── Yageo MLCC / resistors  (CC / RC + 4-char metric) ──────────────────
    (re.compile(r"^(?:CC|RC)0201", re.IGNORECASE), "0201"),
    (re.compile(r"^(?:CC|RC)0402", re.IGNORECASE), "0402"),
    (re.compile(r"^(?:CC|RC)0603", re.IGNORECASE), "0603"),
    (re.compile(r"^(?:CC|RC)0805", re.IGNORECASE), "0805"),
    (re.compile(r"^(?:CC|RC)1206", re.IGNORECASE), "1206"),
    (re.compile(r"^(?:CC|RC)1210", re.IGNORECASE), "1210"),
    # ── Vishay / Dale resistors  (CRCW + EIA code directly) ────────────────
    (re.compile(r"^CRCW0201", re.IGNORECASE), "0201"),
    (re.compile(r"^CRCW0402", re.IGNORECASE), "0402"),
    (re.compile(r"^CRCW0603", re.IGNORECASE), "0603"),
    (re.compile(r"^CRCW0805", re.IGNORECASE), "0805"),
    (re.compile(r"^CRCW1206", re.IGNORECASE), "1206"),
    (re.compile(r"^CRCW1210", re.IGNORECASE), "1210"),
    # ── Panasonic resistors  (ERJ + size code) ─────────────────────────────
    # ERJ-2 → 0402, ERJ-3 → 0603, ERJ-6 → 0805, ERJ-8 → 1206, ERJ-R → 0201
    (re.compile(r"^ERJ.?2", re.IGNORECASE), "0402"),
    (re.compile(r"^ERJ.?3", re.IGNORECASE), "0603"),
    (re.compile(r"^ERJ.?6", re.IGNORECASE), "0805"),
    (re.compile(r"^ERJ.?8", re.IGNORECASE), "1206"),
    (re.compile(r"^ERJ.?R", re.IGNORECASE), "0201"),
    # ── Murata ferrite beads  (BLM + metric size) ──────────────────────────
    # BLM15 → 0402, BLM18 → 0603, BLM21 → 0805, BLM31 → 1206
    (re.compile(r"^BLM15", re.IGNORECASE), "0402"),
    (re.compile(r"^BLM18", re.IGNORECASE), "0603"),
    (re.compile(r"^BLM21", re.IGNORECASE), "0805"),
    (re.compile(r"^BLM31", re.IGNORECASE), "1206"),
    # ── Murata inductors  (LQM + size code) ────────────────────────────────
    # LQM21 → 0805, LQM31 → 1206, LQM32 → 1210, LQM43 → 1812
    (re.compile(r"^LQM21", re.IGNORECASE), "0805"),
    (re.compile(r"^LQM31", re.IGNORECASE), "1206"),
    (re.compile(r"^LQM32", re.IGNORECASE), "1210"),
    (re.compile(r"^LQM43", re.IGNORECASE), "1812"),
]


def infer_package_from_mpn(mpn: str) -> str | None:
    """Infer an EIA package code from a manufacturer part number.

    Uses naming-convention tables for major passive component manufacturers
    (Samsung, Murata, Taiyo Yuden, TDK, Yageo, Vishay, Panasonic).

    Returns the EIA code (e.g. ``"0402"``) or ``None`` if no match is found.
    IC parts, connectors, and modules will return ``None``.

    Args:
        mpn: Manufacturer part number string (case-insensitive).
    """
    if not mpn:
        return None
    for pattern, code in _MPN_PACKAGE_PATTERNS:
        if pattern.match(mpn):
            logger.debug(f"infer_package_from_mpn({mpn!r}) → {code}")
            return code
    return None


# ---------------------------------------------------------------------------
# EIA extraction (re-exported from query.py for convenience)
# ---------------------------------------------------------------------------


def extract_eia_code(footprint: str) -> str | None:
    """Return the EIA package code embedded in a KiCad footprint, or None.

    Delegates to ``hw.circuits.query.eia_from_footprint``.
    """
    return eia_from_footprint(footprint)


def package_matches_eia(package: str | None, eia_code: str) -> bool:
    """Return True if *package* string contains *eia_code* as a standalone token.

    Examples:
        ``package_matches_eia("0402", "0402")``       → ``True``
        ``package_matches_eia("C0402", "0402")``       → ``True``
        ``package_matches_eia("1206", "0402")``        → ``False``
        ``package_matches_eia(None, "0402")``          → ``False``
    """
    if not package:
        return False
    return bool(re.search(r"(?<![0-9])" + re.escape(eia_code) + r"(?![0-9])", package))


# ---------------------------------------------------------------------------
# Component-type category detection from footprint prefix
# ---------------------------------------------------------------------------

# Keywords that **must** appear in a part's description or MPN prefix for the
# given footprint type.  This prevents cross-category substitutions (e.g.
# a ferrite bead for a fuse pad) when category metadata is unavailable.
_FOOTPRINT_CATEGORY_DENY: dict[str, frozenset[str]] = {
    # For fuse pads — reject ferrite beads (BLM*), resistors, inductors
    "Fuse_": frozenset({"BLM", "LQM", "CRCW", "RC", "ERJ"}),
}


def _mpn_is_ferrite_bead(mpn: str) -> bool:
    """Quick heuristic: is this MPN a ferrite bead based on prefix?"""
    return bool(re.match(r"^BLM", mpn, re.IGNORECASE))


def _mpn_is_resistor(mpn: str) -> bool:
    return bool(re.match(r"^(?:CRCW|RC|ERJ|RK|RCS|RT|WR)", mpn, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Candidate filter — main public API for shop workflow
# ---------------------------------------------------------------------------


def filter_candidates(
    candidates: list[Part],
    footprint: str,
    value: str,
) -> list[Part]:
    """Filter a list of ``Part`` candidates to those compatible with the BOM item.

    Applies (in order):

    1. **Component-type rejection** — removes candidates whose MPN belongs to
       a clearly wrong component type for the given footprint (e.g. removes
       ferrite beads from a fuse pad based on MPN prefix).

    2. **EIA package filter** — when the BOM footprint contains a standard EIA
       package code (0402, 0603, …), each candidate's ``package`` field is
       checked.  If ``package`` is missing, ``infer_package_from_mpn`` is
       called as a fallback.  Candidates with a different or indeterminate
       package are excluded.

    If filtering removes *all* candidates, the original unfiltered list is
    returned with a warning so the user sees something rather than nothing.

    Args:
        candidates: Ranked list of ``Part`` objects from the search adapter.
        footprint:  KiCad footprint name from the BOM item.
        value:      BOM value/comment string (used for logging).

    Returns:
        Filtered list (may equal the input if no filter applies or all would
        be filtered out).
    """
    if not candidates:
        return candidates

    # ── Step 1: component-type cross-category rejection ─────────────────────
    for fp_prefix, deny_prefixes in _FOOTPRINT_CATEGORY_DENY.items():
        if footprint.startswith(fp_prefix):
            type_filtered = [
                p
                for p in candidates
                if not any(
                    p.part_number.upper().startswith(bad) for bad in deny_prefixes
                )
            ]
            if type_filtered:
                removed = len(candidates) - len(type_filtered)
                if removed:
                    logger.debug(
                        f"filter_candidates: removed {removed} wrong-type candidates "
                        f"for '{value}' ({footprint})"
                    )
                candidates = type_filtered
            break

    # ── Step 2: ferrite bead guard for fuse pads (belt + suspenders) ────────
    if footprint.startswith("Fuse_"):
        non_bead = [p for p in candidates if not _mpn_is_ferrite_bead(p.part_number)]
        if non_bead:
            candidates = non_bead

    # ── Step 3: EIA package filter ───────────────────────────────────────────
    eia_code = eia_from_footprint(footprint)
    if not eia_code:
        # Non-passive (IC, connector, module) — skip package filter
        logger.debug(
            f"filter_candidates: no EIA code in '{footprint}' — skipping package "
            f"filter for '{value}'"
        )
        return candidates

    # Resolve each candidate's package: prefer the ``package`` field, then fall
    # back to MPN inference.
    def _effective_package(p: Part) -> str | None:
        if p.package:
            return p.package
        return infer_package_from_mpn(p.part_number)

    matched = [
        p for p in candidates if package_matches_eia(_effective_package(p), eia_code)
    ]

    if not matched:
        # Log what packages we actually found to help debugging
        inferred = [(p.part_number, _effective_package(p)) for p in candidates[:5]]
        logger.warning(
            f"filter_candidates: no {eia_code} package match for '{value}' "
            f"({footprint}). Inferred packages: {inferred}. "
            f"Returning all {len(candidates)} unfiltered candidates."
        )
        return candidates  # fall back rather than return nothing

    removed = len(candidates) - len(matched)
    if removed:
        logger.debug(
            f"filter_candidates: {len(matched)}/{len(candidates)} candidates "
            f"match EIA {eia_code} for '{value}' ({footprint}); "
            f"removed {removed} wrong-package candidates"
        )
    return matched
