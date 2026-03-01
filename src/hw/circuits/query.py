"""Shared BOM query-building utilities.

This module is the single source of truth for transforming raw KiCad BOM
values and footprints into effective search queries.  It is consumed by
both the JLCPCB scraper path (``hw.circuits.jlcpcb.bom_lookup.client``)
and the multi-distributor shop path (``hw.circuits.shop.workflow``).

The core export is ``build_search_query(value, footprint) -> str``.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# EIA/IPC SMD package codes
# ---------------------------------------------------------------------------

# Standard EIA/IPC SMD package codes that appear in KiCad footprint names.
# This is the single source of truth — both the JLCPCB client and the shared
# resolver import from here.
EIA_CODES: frozenset[str] = frozenset(
    {
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
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sanitize_query(comment: str) -> str:
    """Clean up a BOM comment to produce a better search query.

    KiCad BOM comments often contain notation like ``120R@100MHz`` or
    ``10uF/10V`` that confuse full-text search engines.  We replace
    separators with spaces so individual terms can be matched independently.
    """
    q = comment.strip()
    q = re.sub(r"[@/\\]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _is_ferrite_bead(value: str, footprint: str) -> bool:
    """Return True when this BOM row describes a ferrite bead.

    Ferrite beads use inductor footprints (``L_…``) and their value
    follows the ``<impedance>@<frequency>`` pattern (e.g. ``120R@100MHz``).
    """
    return footprint.startswith("L_") and "@" in value


def _eia_from_footprint(footprint: str) -> str | None:
    """Return the EIA package code embedded in a KiCad footprint, or None.

    Examples:
        ``"C_0402_1005Metric"``  → ``"0402"``
        ``"R_0805_2012Metric"``  → ``"0805"``
        ``"ESP32-S3-WROOM-1"``   → ``None``
    """
    for code in re.findall(r"\d{4}", footprint):
        if code in EIA_CODES:
            return code
    return None


def _build_connector_query(value: str, footprint: str) -> str:
    """Build a targeted search query for connector footprints.

    Connector part numbers are model-specific (e.g. ``SM08B-GHS-TB``).
    The KiCad footprint string usually encodes the exact model; we extract
    it so distributor searches return the right connector family instead of
    generic headers.

    Falls back to the sanitised value string if no pattern matches.
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
    return _sanitize_query(value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_CONNECTOR_PREFIXES = ("JST_", "USB_", "PinHeader_", "Conn_", "Molex_")


def build_search_query(value: str, footprint: str) -> str:
    """Choose the best search query for a BOM item.

    Routing rules (applied in priority order):

    * **Ferrite beads** — ``L_`` footprint + ``@`` in value →
      ``"120R 100MHz ferrite bead"``
    * **Connectors** — footprint starts with ``JST_``, ``USB_``,
      ``PinHeader_``, ``Conn_``, ``Molex_`` → model number extracted from
      footprint (e.g. ``"SM08B-GHS-TB"``, ``"TYPE-C-31-M-12"``)
    * **Fuses** — ``Fuse_`` footprint → ``"1.5A fuse 1206"``
    * **Resistors (bare number)** — ``R_`` footprint + value like ``"27"``
      with no unit suffix → ``"27ohm 0402"`` (avoids kΩ/MΩ false positives)
    * **EIA passives** — any footprint containing an EIA code → append the
      code to the sanitised value, e.g. ``"100nF 0402"``
    * **ICs / modules** — return the sanitised value as-is

    Args:
        value:    BOM component value / comment (e.g. ``"100nF"``,
                  ``"120R@100MHz"``, ``"TPS63010"``).
        footprint: KiCad footprint name (e.g. ``"C_0402_1005Metric"``).

    Returns:
        A search query string optimised for distributor full-text search.
    """
    if _is_ferrite_bead(value, footprint):
        # "120R@100MHz" → "120R 100MHz ferrite bead"
        return f"{_sanitize_query(value)} ferrite bead"

    if any(footprint.startswith(p) for p in _CONNECTOR_PREFIXES):
        return _build_connector_query(value, footprint)

    # Fuses: "1.5A" + Fuse_1206 → "1.5A fuse 1206"
    if footprint.startswith("Fuse_"):
        base = _sanitize_query(value)
        eia = _eia_from_footprint(footprint)
        suffix = f" {eia}" if eia and eia not in base else ""
        return f"{base} fuse{suffix}"

    base = _sanitize_query(value)

    # Resistors: bare number (e.g. "27") → append "ohm" to avoid MΩ/kΩ hits
    if footprint.startswith("R_") and re.match(r"^\d+\.?\d*$", base):
        base = f"{base}ohm"

    eia = _eia_from_footprint(footprint)
    if eia and eia not in base:
        return f"{base} {eia}"
    return base


def eia_from_footprint(footprint: str) -> str | None:
    """Public alias for ``_eia_from_footprint``."""
    return _eia_from_footprint(footprint)
