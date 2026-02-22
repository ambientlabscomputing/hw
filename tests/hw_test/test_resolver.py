"""Unit tests for the BOM lookup resolver."""

from hw.circuits.jlcpcb.bom_lookup.models import JlcpcbSearchResult
from hw.circuits.jlcpcb.bom_lookup.resolver import resolve_part


def test_resolve_part_happy_path():
    """Test successful part resolution."""
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
            source="lcsc",
        ),
    ]

    selected, error = resolve_part("100nF", "C_0402_1005Metric", candidates)

    assert selected is not None
    assert error is None
    assert selected.lcsc_part == "C1234"  # Should prefer footprint match


def test_resolve_part_out_of_stock():
    """Test handling of out-of-stock parts."""
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
    """Test handling when no search results are found."""
    candidates = []

    selected, error = resolve_part("UnknownPart", "Unknown", candidates)

    assert selected is None
    assert error is not None
    assert "no search results" in error.lower()


def test_resolve_part_prefers_jlcpcb_source():
    """Test that JLCPCB parts are preferred over LCSC."""
    candidates = [
        JlcpcbSearchResult(
            lcsc_part="C1234",
            description="Component",
            package="0402",
            stock=100,
            price=0.02,
            source="lcsc",
        ),
        JlcpcbSearchResult(
            lcsc_part="C5678",
            description="Component",
            package="0402",
            stock=100,
            price=0.02,
            source="jlcpcb",
        ),
    ]

    selected, error = resolve_part("Component", "C_0402_1005Metric", candidates)

    assert selected is not None
    assert error is None
    assert selected.source == "jlcpcb"


def test_resolve_part_footprint_matching():
    """Test footprint matching logic."""
    candidates = [
        JlcpcbSearchResult(
            lcsc_part="C1234",
            description="Capacitor",
            package="0805",
            stock=100,
            price=0.02,
            source="jlcpcb",
        ),
        JlcpcbSearchResult(
            lcsc_part="C5678",
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
    assert "0402" in selected.package  # Should match 0402 footprint


def test_resolve_part_no_footprint_match_fallback():
    """Test that parts without matching footprint can still be selected."""
    candidates = [
        JlcpcbSearchResult(
            lcsc_part="C1234",
            description="Component",
            package="SomeOtherPackage",
            stock=1000,
            price=0.01,
            source="jlcpcb",
        ),
    ]

    selected, error = resolve_part("Component", "UnknownFootprint", candidates)

    # Should still select since stock is sufficient, even without footprint match
    assert selected is not None
    assert error is None
