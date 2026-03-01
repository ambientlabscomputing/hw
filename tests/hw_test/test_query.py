"""Unit tests for hw.circuits.query — shared BOM query builder."""

import pytest

from hw.circuits.query import (
    EIA_CODES,
    _build_connector_query,
    _eia_from_footprint,
    _is_ferrite_bead,
    _sanitize_query,
    build_search_query,
    eia_from_footprint,
)

# ---------------------------------------------------------------------------
# _sanitize_query
# ---------------------------------------------------------------------------


class TestSanitizeQuery:
    def test_strips_whitespace(self):
        assert _sanitize_query("  100nF  ") == "100nF"

    def test_replaces_at_sign(self):
        assert _sanitize_query("120R@100MHz") == "120R 100MHz"

    def test_replaces_slash(self):
        assert _sanitize_query("10uF/10V") == "10uF 10V"

    def test_replaces_backslash(self):
        assert _sanitize_query("10uF\\10V") == "10uF 10V"

    def test_collapses_multiple_spaces(self):
        assert _sanitize_query("100  nF") == "100 nF"

    def test_plain_value_unchanged(self):
        assert _sanitize_query("TPS63010") == "TPS63010"

    def test_resistor_k_notation_unchanged(self):
        # "5.1k" should not be altered by sanitize — caller handles "ohm" suffix
        assert _sanitize_query("5.1k") == "5.1k"


# ---------------------------------------------------------------------------
# _is_ferrite_bead
# ---------------------------------------------------------------------------


class TestIsFerriteBead:
    def test_ferrite_bead_l_footprint_with_at(self):
        assert _is_ferrite_bead("120R@100MHz", "L_0603_1608Metric") is True

    def test_not_ferrite_bead_no_at(self):
        assert _is_ferrite_bead("2.2uH", "L_1210_3225Metric") is False

    def test_not_ferrite_bead_c_footprint(self):
        assert _is_ferrite_bead("120R@100MHz", "C_0603_1608Metric") is False

    def test_not_ferrite_bead_r_footprint(self):
        assert _is_ferrite_bead("10k", "R_0603_1608Metric") is False


# ---------------------------------------------------------------------------
# _eia_from_footprint / eia_from_footprint
# ---------------------------------------------------------------------------


class TestEiaFromFootprint:
    @pytest.mark.parametrize(
        "footprint,expected",
        [
            ("C_0402_1005Metric", "0402"),
            ("R_0603_1608Metric", "0603"),
            ("C_0805_2012Metric", "0805"),
            ("C_1206_3216Metric", "1206"),
            ("L_1210_3225Metric", "1210"),
            ("Fuse_1206_3216Metric", "1206"),
            ("L_0603_1608Metric", "0603"),
        ],
    )
    def test_extracts_known_eia_codes(self, footprint, expected):
        assert _eia_from_footprint(footprint) == expected
        assert eia_from_footprint(footprint) == expected  # public alias

    @pytest.mark.parametrize(
        "footprint",
        [
            "ESP32-S3-WROOM-1",
            "PinHeader_1x04_P2.54mm_Vertical",
            "JST_GH_SM08B-GHS-TB_1x08-1MP_P1.25mm_Horizontal",
            "SOT-23-5",
            "QFN-16",
        ],
    )
    def test_returns_none_for_non_eia_footprints(self, footprint):
        assert _eia_from_footprint(footprint) is None


class TestEiaCodes:
    def test_eia_codes_is_frozenset(self):
        assert isinstance(EIA_CODES, frozenset)

    def test_common_codes_present(self):
        for code in ("0201", "0402", "0603", "0805", "1206", "1210"):
            assert code in EIA_CODES


# ---------------------------------------------------------------------------
# _build_connector_query
# ---------------------------------------------------------------------------


class TestBuildConnectorQuery:
    def test_jst_gh_extracts_model(self):
        fp = "JST_GH_SM08B-GHS-TB_1x08-1MP_P1.25mm_Horizontal"
        assert _build_connector_query("Conn_01x08_Pin", fp) == "SM08B-GHS-TB"

    def test_jst_ph_extracts_model(self):
        fp = "JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal"
        assert _build_connector_query("Conn_01x02_Pin", fp) == "S2B-PH-SM4-TB"

    def test_usb_c_extracts_model(self):
        fp = "USB_C_Receptacle_HRO_TYPE-C-31-M-12"
        assert (
            _build_connector_query("USB_C_Receptacle_USB2.0_16P", fp)
            == "TYPE-C-31-M-12"
        )

    def test_pin_header_4pin_vertical(self):
        fp = "PinHeader_1x04_P2.54mm_Vertical"
        result = _build_connector_query("Conn_01x04_Pin", fp)
        assert "2.54mm" in result
        assert "4" in result
        assert "vertical" in result.lower()

    def test_pin_header_5pin_vertical(self):
        fp = "PinHeader_1x05_P2.54mm_Vertical"
        result = _build_connector_query("Conn_01x05_Pin", fp)
        assert "5" in result

    def test_fallback_to_sanitized_comment(self):
        fp = "UnknownConnector_Footprint"
        result = _build_connector_query("MyConn/2.54", fp)
        assert result == "MyConn 2.54"


# ---------------------------------------------------------------------------
# build_search_query — the main entry point
# ---------------------------------------------------------------------------


class TestBuildSearchQuery:
    # ── Ferrite beads ───────────────────────────────────────────────────────

    def test_ferrite_bead_appends_keyword(self):
        q = build_search_query("120R@100MHz", "L_0603_1608Metric")
        assert "ferrite bead" in q
        assert "120R" in q
        assert "100MHz" in q

    def test_ferrite_bead_600r(self):
        q = build_search_query("600R@100MHz", "L_0402_1005Metric")
        assert "ferrite bead" in q

    # ── Fuses ───────────────────────────────────────────────────────────────

    def test_fuse_appends_fuse_and_eia(self):
        q = build_search_query("1.5A", "Fuse_1206_3216Metric")
        assert "fuse" in q.lower()
        assert "1206" in q

    def test_fuse_no_duplicate_eia(self):
        # If the value already has the EIA code, don't double it
        q = build_search_query("1.5A 1206", "Fuse_1206_3216Metric")
        assert q.count("1206") == 1

    # ── Connectors ──────────────────────────────────────────────────────────

    def test_jst_gh_connector(self):
        fp = "JST_GH_SM08B-GHS-TB_1x08-1MP_P1.25mm_Horizontal"
        q = build_search_query("Conn_01x08_Pin", fp)
        assert q == "SM08B-GHS-TB"

    def test_usb_c_connector(self):
        fp = "USB_C_Receptacle_HRO_TYPE-C-31-M-12"
        q = build_search_query("USB_C_Receptacle_USB2.0_16P", fp)
        assert q == "TYPE-C-31-M-12"

    def test_pin_header_4(self):
        fp = "PinHeader_1x04_P2.54mm_Vertical"
        q = build_search_query("Conn_01x04_Pin", fp)
        assert "4" in q and "2.54mm" in q

    def test_pin_header_5(self):
        fp = "PinHeader_1x05_P2.54mm_Vertical"
        q = build_search_query("Conn_01x05_Pin", fp)
        assert "5" in q

    # ── Resistors w/ EIA code ───────────────────────────────────────────────

    def test_resistor_appends_eia_code(self):
        q = build_search_query("100nF", "C_0402_1005Metric")
        assert "0402" in q
        assert "100nF" in q

    def test_resistor_bare_number_appends_ohm(self):
        # "27" with no suffix → "27ohm 0402"
        q = build_search_query("27", "R_0402_1005Metric")
        assert "ohm" in q.lower()
        assert "0402" in q

    def test_resistor_with_unit_no_ohm_suffix(self):
        # "100R" already has a unit — should not append "ohm"
        q = build_search_query("100R", "R_0402_1005Metric")
        assert "ohm" not in q.lower()
        assert "0402" in q

    def test_resistor_5k1(self):
        q = build_search_query("5.1k", "R_0402_1005Metric")
        assert "0402" in q

    def test_resistor_10k_0603(self):
        q = build_search_query("10k", "R_0603_1608Metric")
        assert "0603" in q

    def test_capacitor_47uf_1206(self):
        q = build_search_query("47uF", "C_1206_3216Metric")
        assert "47uF" in q
        assert "1206" in q

    def test_capacitor_22uf_0805(self):
        q = build_search_query("22uF", "C_0805_2012Metric")
        assert "22uF" in q
        assert "0805" in q

    def test_no_duplicate_eia_if_already_in_value(self):
        # If the value already contains the EIA code, do not append it again
        q = build_search_query("100nF 0402", "C_0402_1005Metric")
        assert q.count("0402") == 1

    # ── Inductor (non-ferrite bead) ─────────────────────────────────────────

    def test_inductor_appends_eia(self):
        q = build_search_query("2.2uH", "L_1210_3225Metric")
        assert "2.2uH" in q
        assert "1210" in q

    # ── IC / module — no EIA code ───────────────────────────────────────────

    def test_ic_passthrough(self):
        q = build_search_query("TPS63010", "SOT-23-5")
        assert q == "TPS63010"

    def test_ic_esp32_module(self):
        q = build_search_query("ESP32-S3-WROOM-1", "ESP32-S3-WROOM-1")
        assert "ESP32" in q

    # ── BOM from the failing v0.csv — all 25 items ──────────────────────────

    @pytest.mark.parametrize(
        "value,footprint,expected_contains",
        [
            # Capacitors
            ("100nF", "C_0402_1005Metric", ["0402"]),
            ("22uF", "C_0805_2012Metric", ["0805"]),
            ("1uF", "C_0603_1608Metric", ["0603"]),
            ("4.7uF", "C_0603_1608Metric", ["0603"]),
            ("10uF/10V", "C_0805_2012Metric", ["0805"]),
            ("10uF", "C_0805_2012Metric", ["0805"]),
            ("47uF", "C_1206_3216Metric", ["1206"]),
            # Ferrite bead
            ("120R@100MHz", "L_0603_1608Metric", ["ferrite"]),
            # Connectors
            (
                "Conn_01x08_Pin",
                "JST_GH_SM08B-GHS-TB_1x08-1MP_P1.25mm_Horizontal",
                ["SM08B"],
            ),
            (
                "Conn_01x02_Pin",
                "JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal",
                ["S2B"],
            ),
            ("Conn_01x04_Pin", "PinHeader_1x04_P2.54mm_Vertical", ["2.54mm", "4"]),
            ("Conn_01x05_Pin", "PinHeader_1x05_P2.54mm_Vertical", ["2.54mm", "5"]),
            (
                "USB_C_Receptacle_USB2.0_16P",
                "USB_C_Receptacle_HRO_TYPE-C-31-M-12",
                ["TYPE-C"],
            ),
            # Fuse
            ("1.5A", "Fuse_1206_3216Metric", ["fuse", "1206"]),
            # Inductor
            ("2.2uH", "L_1210_3225Metric", ["2.2uH", "1210"]),
            # Resistors
            ("5.1k", "R_0402_1005Metric", ["5.1k", "0402"]),
            ("27", "R_0402_1005Metric", ["ohm", "0402"]),
            ("10k", "R_0603_1608Metric", ["10k", "0603"]),
            ("1.13k", "R_0603_1608Metric", ["1.13k", "0603"]),
            ("1.18k", "R_0603_1608Metric", ["1.18k", "0603"]),
            ("4.12k", "R_0603_1608Metric", ["4.12k", "0603"]),
        ],
    )
    def test_v0_bom_queries(self, value, footprint, expected_contains):
        q = build_search_query(value, footprint).lower()
        for substring in expected_contains:
            assert substring.lower() in q, (
                f"Expected '{substring}' in query '{q}' "
                f"(value={value!r}, footprint={footprint!r})"
            )
