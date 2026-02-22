"""Unit tests for the BOM lookup resolver."""

from hw.circuits.jlcpcb.bom_lookup.models import JlcpcbSearchResult
from hw.circuits.jlcpcb.bom_lookup.resolver import (
    _extract_eia_code,
    _package_contains_eia,
    resolve_part,
)

# ── _extract_eia_code ───────────────────────────────────────────────────────


def test_extract_eia_code_passive():
    assert _extract_eia_code("C_0402_1005Metric") == "0402"
    assert _extract_eia_code("R_0805_2012Metric") == "0805"
    assert _extract_eia_code("L_1206_3216Metric") == "1206"


def test_extract_eia_code_no_match():
    assert _extract_eia_code("ESP32-S3-WROOM-1") is None
    assert _extract_eia_code("PinHeader_1x04_P2.54mm_Vertical") is None
    assert _extract_eia_code("VQFN-16-1EP_3x3mm") is None


# ── _package_contains_eia ───────────────────────────────────────────────────


def test_package_contains_eia_match():
    assert _package_contains_eia("0402", "0402") is True
    assert _package_contains_eia("0402 Resistor", "0402") is True


def test_package_contains_eia_no_match():
    assert _package_contains_eia("0805", "0402") is False
    assert _package_contains_eia(None, "0402") is False
    assert _package_contains_eia("", "0402") is False


# ── resolve_part ────────────────────────────────────────────────────────────


def test_resolve_part_happy_path():
    """Correct footprint present in candidates → selects it."""
    candidates = [
        JlcpcbSearchResult(
            lcsc_part="C1234",
            description="100nF Capacitor",
            package="0402",
            stock=1000,
            price=0.01,
            source="jlcpcb",
        ),
        JlcpcbSearchResult(
            lcsc_part="C5678",
            description="100nF Capacitor",
            package="0805",
            stock=500,
            price=0.02,
            source="jlcpcb",
        ),
    ]

    selected, error = resolve_part("100nF", "C_0402_1005Metric", candidates)

    assert selected is not None
    assert error is None
    assert selected.lcsc_part == "C1234"  # Only 0402 passes the package filter


def test_resolve_part_wrong_footprint_returns_none():
    """If only wrong-package candidates exist, resolver must return None."""
    candidates = [
        JlcpcbSearchResult(
            lcsc_part="C9999",
            description="100nF Capacitor",
            package="0805",  # Wrong — BOM needs 0402
            stock=9999,
            price=0.01,
            source="jlcpcb",
        ),
    ]

    selected, error = resolve_part("100nF", "C_0402_1005Metric", candidates)

    assert selected is None
    assert error is not None
    assert "0402" in error


def test_resolve_part_no_package_info_returns_none():
    """Candidates with null package must not be selected for passives."""
    candidates = [
        JlcpcbSearchResult(
            lcsc_part="C9999",
            description="100nF Capacitor",
            package=None,  # No package info
            stock=9999,
            price=0.01,
            source="jlcpcb",
        ),
    ]

    selected, error = resolve_part("100nF", "C_0402_1005Metric", candidates)

    assert selected is None
    assert error is not None


def test_resolve_part_out_of_stock():
    """All candidates below MIN_STOCK → error."""
    candidates = [
        JlcpcbSearchResult(
            lcsc_part="C1234",
            description="Rare Component",
            package="0402",
            stock=5,  # Below minimum
            price=0.50,
            source="jlcpcb",
        ),
    ]

    selected, error = resolve_part("RareChip", "C_0402_1005Metric", candidates)

    assert selected is None
    assert error is not None
    assert "out of stock" in error.lower()


def test_resolve_part_no_results():
    """Empty candidate list → error."""
    selected, error = resolve_part("UnknownPart", "Unknown", [])

    assert selected is None
    assert "no search results" in error.lower()


def test_resolve_part_prefers_higher_stock():
    """Among valid footprint matches, pick the one with most stock."""
    candidates = [
        JlcpcbSearchResult(
            lcsc_part="C_LOW",
            description="Capacitor",
            package="0402",
            stock=100,
            price=0.02,
            source="jlcpcb",
        ),
        JlcpcbSearchResult(
            lcsc_part="C_HIGH",
            description="Capacitor",
            package="0402",
            stock=50000,
            price=0.02,
            source="jlcpcb",
        ),
    ]

    selected, error = resolve_part("100nF", "C_0402_1005Metric", candidates)

    assert selected is not None
    assert error is None
    assert selected.lcsc_part == "C_HIGH"


def test_resolve_part_footprint_matching():
    """Package filter removes wrong-size candidate."""
    candidates = [
        JlcpcbSearchResult(
            lcsc_part="C_WRONG",
            description="Capacitor",
            package="0805",
            stock=10000,
            price=0.01,
            source="jlcpcb",
        ),
        JlcpcbSearchResult(
            lcsc_part="C_RIGHT",
            description="Capacitor",
            package="0402",
            stock=100,
            price=0.02,
            source="jlcpcb",
        ),
    ]

    selected, error = resolve_part("100nF", "C_0402_1005Metric", candidates)

    assert selected is not None
    assert error is None
    assert selected.lcsc_part == "C_RIGHT"
    assert "0402" in selected.package


def test_resolve_part_non_passive_skips_package_filter():
    """No EIA code in footprint → skip package filter, still select."""
    candidates = [
        JlcpcbSearchResult(
            lcsc_part="C1234",
            description="Some IC",
            package="QFN-16",
            stock=1000,
            price=0.01,
            source="jlcpcb",
        ),
    ]

    selected, error = resolve_part("SomeIC", "VQFN-16-1EP_3x3mm", candidates)

    assert selected is not None
    assert error is None
