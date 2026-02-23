"""Unit tests for the JLCPCB Playwright-based search client."""

from hw.circuits.jlcpcb.bom_lookup.client import (
    _build_connector_query,
    _build_search_query,
    _eia_from_footprint,
    _extract_components,
    _is_ferrite_bead,
    _sanitize_query,
)

# ---------------------------------------------------------------------------
# _sanitize_query
# ---------------------------------------------------------------------------


class TestSanitizeQuery:
    def test_at_sign(self):
        assert _sanitize_query("120R@100MHz") == "120R 100MHz"

    def test_slash(self):
        assert _sanitize_query("10uF/10V") == "10uF 10V"

    def test_backslash(self):
        assert _sanitize_query("a\\b") == "a b"

    def test_plain(self):
        assert _sanitize_query("100nF") == "100nF"

    def test_multiple_spaces(self):
        assert _sanitize_query("  a @  b  ") == "a b"


# ---------------------------------------------------------------------------
# _is_ferrite_bead
# ---------------------------------------------------------------------------


class TestIsFerrtieBead:
    def test_ferrite_bead_true(self):
        assert _is_ferrite_bead("120R@100MHz", "L_0603_1608Metric") is True

    def test_resistor_false(self):
        # Same footprint prefix letter but not an L_ footprint
        assert _is_ferrite_bead("120R", "R_0603_1608Metric") is False

    def test_inductor_no_at_false(self):
        # Inductor footprint but no @ in comment
        assert _is_ferrite_bead("10uH", "L_0603_1608Metric") is False

    def test_other_at_false(self):
        # @ in comment but not an inductor footprint
        assert _is_ferrite_bead("120R@100MHz", "R_0603_1608Metric") is False


# ---------------------------------------------------------------------------
# _build_connector_query
# ---------------------------------------------------------------------------


class TestBuildConnectorQuery:
    def test_jst_gh_8pin(self):
        result = _build_connector_query(
            "Conn_01x08_Pin",
            "JST_GH_SM08B-GHS-TB_1x08-1MP_P1.25mm_Horizontal",
        )
        assert result == "SM08B-GHS-TB"

    def test_jst_ph_2pin(self):
        result = _build_connector_query(
            "Conn_01x02_Pin",
            "JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal",
        )
        assert result == "S2B-PH-SM4-TB"

    def test_usb_c(self):
        result = _build_connector_query(
            "USB_C_Receptacle",
            "USB_C_Receptacle_HRO_TYPE-C-31-M-12",
        )
        assert result == "TYPE-C-31-M-12"

    def test_pin_header(self):
        result = _build_connector_query(
            "Conn_01x04_Pin",
            "PinHeader_1x04_P2.54mm_Vertical",
        )
        assert "2.54mm" in result
        assert "4" in result

    def test_fallback_to_comment(self):
        result = _build_connector_query("MyPart", "SomeUnknownFootprint")
        assert result == "MyPart"


# ---------------------------------------------------------------------------
# _eia_from_footprint
# ---------------------------------------------------------------------------


class TestEiaFromFootprint:
    def test_capacitor_0402(self):
        assert _eia_from_footprint("C_0402_1005Metric") == "0402"

    def test_resistor_0805(self):
        assert _eia_from_footprint("R_0805_2012Metric") == "0805"

    def test_inductor_1210(self):
        assert _eia_from_footprint("L_1210_3225Metric") == "1210"

    def test_ic_no_match(self):
        assert _eia_from_footprint("ESP32-S3-WROOM-1") is None

    def test_connector_no_match(self):
        assert (
            _eia_from_footprint("JST_GH_SM08B-GHS-TB_1x08-1MP_P1.25mm_Horizontal")
            is None
        )


# ---------------------------------------------------------------------------
# _build_search_query
# ---------------------------------------------------------------------------


class TestBuildSearchQuery:
    def test_ferrite_bead_appends_keyword(self):
        q = _build_search_query("120R@100MHz", "L_0603_1608Metric")
        assert "ferrite bead" in q
        assert "120R" in q

    def test_jst_connector_uses_model(self):
        q = _build_search_query(
            "Conn_01x08_Pin",
            "JST_GH_SM08B-GHS-TB_1x08-1MP_P1.25mm_Horizontal",
        )
        assert "SM08B" in q

    def test_passive_eia_appended(self):
        # EIA code is added so JLCPCB narrows to the right package family
        q = _build_search_query("100nF", "C_0402_1005Metric")
        assert q == "100nF 0402"

    def test_resistor_bare_number_gets_ohm_suffix(self):
        # Bare number "27" + R_ footprint → append "ohm" so JLCPCB filters to
        # the right resistance family (27Ω, not 82kΩ).
        q = _build_search_query("27", "R_0402_1005Metric")
        assert q == "27ohm 0402"

    def test_resistor_with_unit_suffix_unchanged(self):
        # "100R" already has a unit suffix — do NOT append "ohm" again.
        q = _build_search_query("100R", "R_0402_1005Metric")
        assert q == "100R 0402"
        assert "ohm" not in q

    def test_large_capacitor_eia(self):
        # 47uF on 1206 pad → "47uF 1206" (avoids tantalum CASE-D matches)
        q = _build_search_query("47uF", "C_1206_3216Metric")
        assert q == "47uF 1206"

    def test_inductor_eia(self):
        q = _build_search_query("2.2uH", "L_1210_3225Metric")
        assert q == "2.2uH 1210"

    def test_eia_not_duplicated_if_already_in_comment(self):
        # If comment somehow already has the EIA code, don't duplicate it
        q = _build_search_query("100nF 0402", "C_0402_1005Metric")
        assert q == "100nF 0402"
        assert q.count("0402") == 1

    def test_ic_no_eia_added(self):
        # IC with no EIA footprint → just comment, no spurious suffix
        q = _build_search_query("TPS63010", "SOT-23-5")
        assert q == "TPS63010"

    def test_ferrite_sanitises_separators(self):
        q = _build_search_query("600R@100MHz", "L_0402_1005Metric")
        assert "@" not in q
        assert "ferrite bead" in q

    def test_fuse_query_includes_fuse_keyword(self):
        q = _build_search_query("1.5A", "Fuse_1206_3216Metric")
        assert "fuse" in q.lower()
        assert "1206" in q

    def test_fuse_query_does_not_include_ferrite(self):
        q = _build_search_query("1.5A", "Fuse_1206_3216Metric")
        assert "ferrite" not in q.lower()


class TestBuildConnectorQueryOrientation:
    def test_pin_header_vertical_in_query(self):
        q = _build_connector_query(
            "Conn_01x04_Pin",
            "PinHeader_1x04_P2.54mm_Vertical",
        )
        assert "vertical" in q.lower()
        assert "4" in q

    def test_pin_header_horizontal_in_query(self):
        q = _build_connector_query(
            "Conn_01x05_Pin",
            "PinHeader_1x05_P2.54mm_Horizontal",
        )
        assert "horizontal" in q.lower()
        assert "5" in q

    def test_pin_header_no_orientation_suffix_omitted(self):
        # footprint without Vertical/Horizontal suffix
        q = _build_connector_query(
            "Conn_01x04_Pin",
            "PinHeader_1x04_P2.54mm",
        )
        assert "2.54mm" in q
        assert "4" in q


# ---------------------------------------------------------------------------
# _extract_components
# ---------------------------------------------------------------------------


class TestExtractComponents:
    """Tests for the pure data-mapping layer (no browser required)."""

    def _make_raw(self, **overrides):
        base = {
            "code": "C1525",
            "spec": "0402",
            "brand": "Samsung Electro-Mechanics",
            "model": "CL05B104KO5NNNC",
            "stock": 35_787_350,
            "describe": "100nF 16V X7R ±10% 0402 MLCC",
            "category1": "Capacitors",
            "category2": "Multilayer Ceramic Capacitors MLCC",
            "price": 0.0012,
        }
        base.update(overrides)
        return base

    def test_basic_mapping(self):
        results = _extract_components([self._make_raw()])
        assert len(results) == 1
        r = results[0]
        assert r.lcsc_part == "C1525"
        assert r.package == "0402"
        assert r.stock == 35_787_350
        assert r.manufacturer == "Samsung Electro-Mechanics"
        assert r.mfr_part == "CL05B104KO5NNNC"
        assert r.price == 0.0012
        assert r.source == "jlcpcb"

    def test_category_concatenated(self):
        r = _extract_components([self._make_raw()])[0]
        assert "Capacitors" in r.category
        assert "Multilayer" in r.category

    def test_category1_only(self):
        r = _extract_components([self._make_raw(category2="")])[0]
        assert r.category == "Capacitors"

    def test_missing_code_skipped(self):
        results = _extract_components([self._make_raw(code="")])
        assert results == []

    def test_none_price_allowed(self):
        r = _extract_components([self._make_raw(price=None)])[0]
        assert r.price is None

    def test_invalid_stock_defaults_to_zero(self):
        r = _extract_components([self._make_raw(stock="bad")])[0]
        assert r.stock == 0

    def test_empty_list(self):
        assert _extract_components([]) == []

    def test_multiple_records(self):
        raw = [
            self._make_raw(code="C1525"),
            self._make_raw(code="C9999", spec="0805"),
        ]
        results = _extract_components(raw)
        assert len(results) == 2
        assert results[1].package == "0805"

    def test_discontinued_false_by_default(self):
        r = _extract_components([self._make_raw()])[0]
        assert r.discontinued is False

    def test_discontinued_true_when_flagged(self):
        r = _extract_components([self._make_raw(discontinue=True)])[0]
        assert r.discontinued is True

    def test_discontinued_false_when_zero(self):
        # JS falsy values should map to False
        r = _extract_components([self._make_raw(discontinue=False)])[0]
        assert r.discontinued is False
