"""Unit tests for hw.circuits.resolver — shared package inference and filtering."""

import pytest

from hw.circuits.resolver import (
    extract_eia_code,
    filter_candidates,
    infer_package_from_mpn,
    package_matches_eia,
)
from tests.hw_test.conftest import make_part

# ---------------------------------------------------------------------------
# infer_package_from_mpn
# ---------------------------------------------------------------------------


class TestInferPackageFromMpn:
    # ── Samsung MLCC ────────────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "mpn,expected",
        [
            ("CL03A104KQ3NNNC", "0201"),
            ("CL05A106MP5NUNC", "0402"),  # C1 / C6 from failing BOM
            (
                "CL10A226MP8NUNE",
                "0603",
            ),  # C10/C15/C8/C9 — was incorrectly shown as 0603
            ("CL10E104KC8VPNC", "0603"),  # C11/C13/C16/C2 — was incorrectly matched
            ("CL21A106KAYNNNE", "0805"),
            ("CL31A476KOHNNNE", "1206"),
            ("CL32A107MAVNNNE", "1210"),
        ],
    )
    def test_samsung_mlcc(self, mpn, expected):
        assert infer_package_from_mpn(mpn) == expected

    # ── Murata MLCC (GRM) ───────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "mpn,expected",
        [
            ("GRM033C71C104KE14D", "0201"),  # C3/C14 in failing BOM — wrong val matched
            ("GRM155R71C104KA88D", "0402"),
            ("GRM188R71C104KA93D", "0603"),
            ("GRM21BR60J107ME39L", "0805"),
            ("GRM31CR61A476KE15L", "1206"),
            ("GRM32ER61C476ME20L", "1210"),
        ],
    )
    def test_murata_grm(self, mpn, expected):
        assert infer_package_from_mpn(mpn) == expected

    # ── Murata AEC-Q200 (GCM) ───────────────────────────────────────────────

    @pytest.mark.parametrize(
        "mpn,expected",
        [
            ("GCM188R71H473KA55D", "0603"),  # C12 in failing BOM — was "1206" mismatch
            ("GCM21BR71C475KE36L", "0805"),
            ("GCM31CR61C106KA64L", "1206"),
        ],
    )
    def test_murata_gcm(self, mpn, expected):
        assert infer_package_from_mpn(mpn) == expected

    # ── Taiyo Yuden ─────────────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "mpn,expected",
        [
            ("JMK105BBJ475MVF", "0402"),  # C4/C5 in failing BOM
            ("JMK107BBJ106MALT", "0603"),
            ("JMK212BBJ226MG-T", "0805"),
            ("JMK316ABJ226ML-T", "1206"),
        ],
    )
    def test_taiyo_yuden(self, mpn, expected):
        assert infer_package_from_mpn(mpn) == expected

    # ── TDK ─────────────────────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "mpn,expected",
        [
            ("C1005X5R1C105K050BC", "0402"),
            ("C1608X7R1E105K080AA", "0603"),
            ("C2012X7R1C106K085AA", "0805"),
            ("C3216X7R1C226K160AB", "1206"),
        ],
    )
    def test_tdk(self, mpn, expected):
        assert infer_package_from_mpn(mpn) == expected

    # ── Yageo ───────────────────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "mpn,expected",
        [
            ("RC0402FR-0751KL", "0402"),
            ("RC0603FR-0710KL", "0603"),
            ("RC0805FR-0710KL", "0805"),
            ("RC1206FR-0751KL", "1206"),
        ],
    )
    def test_yageo_resistor(self, mpn, expected):
        assert infer_package_from_mpn(mpn) == expected

    # ── Vishay / Dale (CRCW) ────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "mpn,expected",
        [
            ("CRCW040251K0FKED", "0402"),
            ("CRCW060310K0FKEA", "0603"),
            ("CRCW080510K0FKEA", "0805"),
            ("CRCW120610K0FKEA", "1206"),
        ],
    )
    def test_vishay_crcw(self, mpn, expected):
        assert infer_package_from_mpn(mpn) == expected

    # ── Murata ferrite beads (BLM) ───────────────────────────────────────────

    @pytest.mark.parametrize(
        "mpn,expected",
        [
            ("BLM15AX121SN1D", "0402"),
            ("BLM18KG471SN1D", "0603"),  # F1 in failing BOM — was matched as fuse!
            ("BLM21PG600SN1D", "0805"),
            ("BLM31PG600SN1L", "1206"),
        ],
    )
    def test_murata_blm_ferrite(self, mpn, expected):
        assert infer_package_from_mpn(mpn) == expected

    # ── Murata inductors (LQM) ───────────────────────────────────────────────

    @pytest.mark.parametrize(
        "mpn,expected",
        [
            ("LQM21PN2R2MGHL", "0805"),  # L1 in failing BOM
            ("LQM31PN1R0MGHL", "1206"),
        ],
    )
    def test_murata_lqm_inductor(self, mpn, expected):
        assert infer_package_from_mpn(mpn) == expected

    # ── No match ─────────────────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "mpn",
        [
            "TPS63010",  # IC
            "BQ24074RGTR",  # IC
            "ESP32S3WROOM1N4",  # module
            "TYPE-C-31-M-12",  # connector
            "",  # empty
        ],
    )
    def test_returns_none_for_ics_and_modules(self, mpn):
        assert infer_package_from_mpn(mpn) is None

    def test_case_insensitive(self):
        assert infer_package_from_mpn("cl10e104kc8vpnc") == "0603"
        assert infer_package_from_mpn("CL10E104KC8VPNC") == "0603"


# ---------------------------------------------------------------------------
# extract_eia_code  (delegates to hw.circuits.query.eia_from_footprint)
# ---------------------------------------------------------------------------


class TestExtractEiaCode:
    def test_extracts_from_capacitor_footprint(self):
        assert extract_eia_code("C_0402_1005Metric") == "0402"

    def test_extracts_from_resistor_footprint(self):
        assert extract_eia_code("R_0603_1608Metric") == "0603"

    def test_none_for_ic(self):
        assert extract_eia_code("ESP32-S3-WROOM-1") is None

    def test_none_for_connector(self):
        assert (
            extract_eia_code("JST_GH_SM08B-GHS-TB_1x08-1MP_P1.25mm_Horizontal") is None
        )


# ---------------------------------------------------------------------------
# package_matches_eia
# ---------------------------------------------------------------------------


class TestPackageMatchesEia:
    def test_exact_match(self):
        assert package_matches_eia("0402", "0402") is True

    def test_code_in_longer_string(self):
        assert package_matches_eia("C0402", "0402") is True

    def test_different_code_no_match(self):
        assert package_matches_eia("1206", "0402") is False

    def test_none_package_no_match(self):
        assert package_matches_eia(None, "0402") is False

    def test_empty_string_no_match(self):
        assert package_matches_eia("", "0402") is False

    def test_no_false_positive_on_partial_digits(self):
        # "40201" should NOT match "0402" (leading digit prevents it)
        assert package_matches_eia("40201", "0402") is False


# ---------------------------------------------------------------------------
# filter_candidates
# ---------------------------------------------------------------------------


class TestFilterCandidates:
    # ── Correct package passes through ──────────────────────────────────────

    def test_correct_package_passes(self):
        # 0402 cap matches 0402 footprint
        p = make_part(part_number="CL05A104KA5NQNC")  # CL05 → 0402
        result = filter_candidates([p], "C_0402_1005Metric", "100nF")
        assert p in result

    def test_wrong_package_removed(self):
        # CL10 → 0603 but we need 0402
        p = make_part(part_number="CL10E104KC8VPNC")  # CL10 = 0603
        result = filter_candidates([p], "C_0402_1005Metric", "100nF")
        # Falls back to unfiltered when all candidates removed
        assert p in result  # fallback behaviour
        # But the winner should have been filtered; len stays same due to fallback

    def test_mixed_keeps_only_correct_package(self):
        p_0402 = make_part(part_number="CL05A104KA5NQNC")  # CL05 → 0402
        p_0603 = make_part(part_number="CL10E104KC8VPNC")  # CL10 → 0603
        result = filter_candidates([p_0402, p_0603], "C_0402_1005Metric", "100nF")
        assert p_0402 in result
        assert p_0603 not in result

    # ── Fuse pad rejects ferrite bead ────────────────────────────────────────

    def test_fuse_pad_rejects_blm_ferrite_bead(self):
        ferrite = make_part(part_number="BLM18KG471SN1D")  # is a ferrite bead
        real_fuse = make_part(part_number="0217001.MXP")  # random fuse MPN
        result = filter_candidates([ferrite, real_fuse], "Fuse_1206_3216Metric", "1.5A")
        assert ferrite not in result
        assert real_fuse in result

    def test_fuse_pad_fallback_when_all_beads(self):
        # If ALL candidates are ferrite beads, fall back rather than empty list
        ferrite = make_part(part_number="BLM18KG471SN1D")
        result = filter_candidates([ferrite], "Fuse_1206_3216Metric", "1.5A")
        assert len(result) == 1  # fallback — returns original

    # ── IC / module — no EIA code — passes through unchanged ─────────────────

    def test_ic_no_eia_passes_through(self):
        p = make_part(part_number="TPS63010")
        result = filter_candidates([p], "SOT-23-5", "TPS63010")
        assert p in result

    def test_esp32_module_passes_through(self):
        p = make_part(part_number="ESP32S3WROOM1N4R8")
        result = filter_candidates([p], "ESP32-S3-WROOM-1", "ESP32-S3-WROOM-1")
        assert p in result

    # ── Empty input ──────────────────────────────────────────────────────────

    def test_empty_candidates_returns_empty(self):
        assert filter_candidates([], "C_0402_1005Metric", "100nF") == []

    # ── Part with explicit package field wins over MPN inference ─────────────

    def test_explicit_package_field_used_when_present(self):
        # Part has package="0402" explicitly set — should pass 0402 filter
        p = make_part(part_number="SOMEUNKNOWNMPN123", package="0402")
        result = filter_candidates([p], "C_0402_1005Metric", "100nF")
        assert p in result

    def test_explicit_wrong_package_field_rejected(self):
        p_wrong = make_part(part_number="SOMEUNKNOWNMPN123", package="0603")
        p_right = make_part(part_number="CL05A104KA5NQNC")  # CL05 → 0402
        result = filter_candidates([p_wrong, p_right], "C_0402_1005Metric", "100nF")
        assert p_right in result
        assert p_wrong not in result
