"""Unit tests for the BOM lookup resolver."""

from hw.circuits.jlcpcb.bom_lookup.models import JlcpcbSearchResult
from hw.circuits.jlcpcb.bom_lookup.resolver import (
    _expected_category_keywords,
    _extract_eia_code,
    _package_contains_eia,
    _score_candidate,
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


# ── _expected_category_keywords ───────────────────────────────────────────────────


class TestExpectedCategoryKeywords:
    def test_resistor_footprint(self):
        assert "resistor" in _expected_category_keywords("R_0402_1005Metric")

    def test_capacitor_footprint(self):
        assert "capacitor" in _expected_category_keywords("C_0402_1005Metric")

    def test_fuse_footprint(self):
        kws = _expected_category_keywords("Fuse_1206_3216Metric")
        assert "fuse" in kws or "circuit protection" in kws

    def test_inductor_footprint_empty(self):
        # L_ is handled by the ferrite bead filter, not the category keyword filter
        assert _expected_category_keywords("L_0603_1608Metric") == ()

    def test_ic_footprint_empty(self):
        assert _expected_category_keywords("VQFN-16-1EP_3x3mm") == ()


# ── Category filter in resolve_part ─────────────────────────────────────────


class TestCategoryFilter:
    def _make(self, lcsc, category, package="0402", stock=50_000, price=0.01):
        return JlcpcbSearchResult(
            lcsc_part=lcsc,
            description="Some part",
            package=package,
            stock=stock,
            price=price,
            category=category,
            source="jlcpcb",
        )

    def test_r_footprint_rejects_capacitor(self):
        """Capacitor candidate must not win for R_ pad."""
        candidates = [
            self._make(
                "C_CAP",
                "Capacitors / Multilayer Ceramic Capacitors MLCC",
                stock=1_000_000,
            ),
            self._make("C_RES", "Resistors / Chip Resistor - Surface Mount", stock=100),
        ]
        selected, error = resolve_part("27", "R_0402_1005Metric", candidates)
        assert selected is not None
        assert selected.lcsc_part == "C_RES"

    def test_r_footprint_rejects_ferrite_bead(self):
        """Ferrite bead candidate must not win for R_ pad."""
        candidates = [
            self._make(
                "C_FB", "Filters / Ferrite Beads", package="0603", stock=900_000
            ),
            self._make(
                "C_RES",
                "Resistors / Chip Resistor - Surface Mount",
                package="0603",
                stock=100,
            ),
        ]
        selected, error = resolve_part("1.18k", "R_0603_1608Metric", candidates)
        assert selected is not None
        assert selected.lcsc_part == "C_RES"

    def test_fuse_footprint_rejects_ferrite_bead(self):
        """Ferrite bead must not win for Fuse_ pad."""
        candidates = [
            self._make(
                "C_FB", "Filters / Ferrite Beads", package="1206", stock=800_000
            ),
            self._make(
                "C_F", "Circuit Protection / Fuses", package="1206", stock=1_000
            ),
        ]
        selected, error = resolve_part("1.5A", "Fuse_1206_3216Metric", candidates)
        assert selected is not None
        assert selected.lcsc_part == "C_F"

    def test_category_filter_falls_back_when_no_match(self):
        """If no candidates match category keywords, all in-stock are kept."""
        candidates = [
            self._make("C_ANY", "", stock=1_000),  # empty category
        ]
        # Should not raise; falls back gracefully
        selected, error = resolve_part("27", "R_0402_1005Metric", candidates)
        assert selected is not None


# ── Pin header filter in resolve_part ──────────────────────────────────────


class TestPinHeaderFilter:
    def _make(self, lcsc, description, stock=50_000, price=0.05):
        return JlcpcbSearchResult(
            lcsc_part=lcsc,
            description=description,
            package=None,  # pin headers have no EIA code
            stock=stock,
            price=price,
            source="jlcpcb",
        )

    def test_rejects_wrong_pin_count(self):
        """6-pin header must not be selected for 4-pin PinHeader footprint."""
        candidates = [
            self._make("C_6P", "2.54-1x6P Straight pin header", stock=100_000),
            self._make("C_4P", "2.54-1x4P Straight pin header", stock=1_000),
        ]
        selected, error = resolve_part(
            "Conn_01x04_Pin", "PinHeader_1x04_P2.54mm_Vertical", candidates
        )
        assert selected is not None
        assert selected.lcsc_part == "C_4P"

    def test_orientation_vertical_rejects_right_angle(self):
        """Right-angle header must not be selected for Vertical PinHeader."""
        candidates = [
            self._make("C_RA", "1x5P Right Angle pin header 2.54mm", stock=200_000),
            self._make("C_ST", "1x5P Straight pin header 2.54mm", stock=1_000),
        ]
        selected, error = resolve_part(
            "Conn_01x05_Pin", "PinHeader_1x05_P2.54mm_Vertical", candidates
        )
        assert selected is not None
        assert selected.lcsc_part == "C_ST"

    def test_pin_count_fallback_when_no_desc_match(self):
        """If no description matches pin count, all candidates are kept."""
        candidates = [
            self._make("C_ANY", "Generic 2.54mm header", stock=50_000),
        ]
        selected, error = resolve_part(
            "Conn_01x04_Pin", "PinHeader_1x04_P2.54mm_Vertical", candidates
        )
        assert selected is not None  # Falls back, doesn't crash


# ── Dielectric scoring ──────────────────────────────────────────────────────────


class TestDielectricScoring:
    def _make(self, lcsc, description, stock=100_000, price=0.01):
        return JlcpcbSearchResult(
            lcsc_part=lcsc,
            description=description,
            package="0805",
            stock=stock,
            price=price,
            category="Capacitors / Multilayer Ceramic Capacitors MLCC",
            source="jlcpcb",
        )

    def test_y5v_loses_to_x5r_same_stock(self):
        """Y5V capacitor must score lower than X5R even at equal stock."""
        s_x5r = _score_candidate(
            self._make("C_X5R", "10uF 10V X5R ±20% 0805"), "C_0805_2012Metric"
        )
        s_y5v = _score_candidate(
            self._make("C_Y5V", "10uF 10V Y5V ±80% 0805"), "C_0805_2012Metric"
        )
        assert s_x5r > s_y5v

    def test_x7r_beats_y5v(self):
        s_x7r = _score_candidate(
            self._make("C_X7R", "100nF 50V X7R ±10% 0805"), "C_0805_2012Metric"
        )
        s_y5v = _score_candidate(
            self._make("C_Y5V", "100nF 50V Y5V ±80% 0805"), "C_0805_2012Metric"
        )
        assert s_x7r > s_y5v

    def test_y5v_resolve_loses_to_x5r(self):
        """In a full resolve_part call, Y5V must not be chosen over X5R."""
        candidates = [
            self._make("C_Y5V", "10uF 10V Y5V -20%/+80% 0805", stock=1_000_000),
            self._make("C_X5R", "10uF 10V X5R ±20% 0805", stock=500_000),
        ]
        selected, error = resolve_part("10uF", "C_0805_2012Metric", candidates)
        assert selected is not None
        assert selected.lcsc_part == "C_X5R"

    def test_non_capacitor_unaffected(self):
        """Dielectric penalty must NOT apply to non-C_ footprints."""
        # A resistor description mentioning Y5V (nonsensical, but shouldn't penalise)
        r = JlcpcbSearchResult(
            lcsc_part="C_RES",
            description="27ohm Y5V 0402",
            package="0402",
            stock=100_000,
            price=0.01,
            source="jlcpcb",
        )
        score = _score_candidate(r, "R_0402_1005Metric")
        # Score must be positive (no penalty applied for non-capacitor)
        assert score > 0


# ── Inductor current-rating scoring ───────────────────────────────────────────


class TestInductorCurrentRatingScoring:
    def _make(self, lcsc, description, stock=10_000, price=0.10):
        return JlcpcbSearchResult(
            lcsc_part=lcsc,
            description=description,
            package="1210",
            stock=stock,
            price=price,
            source="jlcpcb",
        )

    def test_higher_current_scores_better(self):
        s_low = _score_candidate(
            self._make("C_LOW", "2.2uH 320mA 1210 Power Inductor"),
            footprint="L_1210_3225Metric",
            comment="2.2uH",
        )
        s_high = _score_candidate(
            self._make("C_HIGH", "2.2uH 1.5A 1210 Power Inductor"),
            footprint="L_1210_3225Metric",
            comment="2.2uH",
        )
        assert s_high > s_low

    def test_ferrite_bead_not_scored_by_current(self):
        """Ferrite beads (comment has @) must not get inductor current bonus."""
        s_bead = _score_candidate(
            self._make("C_BEAD", "600Ohm@100MHz 2A 0603 Ferrite Bead"),
            footprint="L_0603_1608Metric",
            comment="600R@100MHz",
        )
        # Should be a normal stock+price score without any inductor bonus
        s_no_bead = _score_candidate(
            self._make("C_BEAD", "600Ohm@100MHz 2A 0603 Ferrite Bead"),
        )
        assert s_bead == s_no_bead  # no current bonus applied
