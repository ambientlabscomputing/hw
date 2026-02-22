"""
End-to-end tests for `hw circuits kicad convert pos`.

These tests invoke the actual Click CLI using CliRunner and validate
the full conversion pipeline against the sample files shipped with
the package.
"""

import csv
import io
from pathlib import Path

import pytest
from click.testing import CliRunner

from hw.main import main

SAMPLE_DIR = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "hw"
    / "circuits"
    / "kicad"
    / "convert"
    / "sample_files"
)
KICAD_POS = SAMPLE_DIR / "kicad-generated-pos.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(*args):
    runner = CliRunner()
    return runner.invoke(main, ["circuits", "kicad", "convert", "pos", *args])


def _parse_csv(path: Path) -> tuple[list[str], list[dict]]:
    content = path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    return list(reader.fieldnames or []), rows


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPosHelp:
    def test_help_exits_zero(self):
        result = _run("--help")
        assert result.exit_code == 0

    def test_help_mentions_jlcpcb(self):
        result = _run("--help")
        assert "--jlcpcb" in result.output


class TestPosNoFlag:
    def test_no_flag_errors(self, tmp_path):
        out = tmp_path / "out.csv"
        result = _run(str(KICAD_POS), str(out))
        assert result.exit_code != 0

    def test_no_flag_error_message(self, tmp_path):
        out = tmp_path / "out.csv"
        result = _run(str(KICAD_POS), str(out))
        assert "target format" in result.output.lower()


class TestPosJlcpcb:
    @pytest.fixture()
    def output_path(self, tmp_path) -> Path:
        out = tmp_path / "out-cpl.csv"
        result = _run("--jlcpcb", str(KICAD_POS), str(out))
        assert result.exit_code == 0, (
            f"Command failed (exit {result.exit_code}):\n"
            f"output: {result.output}\n"
            f"exception: {result.exception}"
        )
        return out

    def test_exits_zero(self, tmp_path):
        out = tmp_path / "out-cpl.csv"
        result = _run("--jlcpcb", str(KICAD_POS), str(out))
        assert result.exit_code == 0

    def test_correct_headers(self, output_path):
        headers, _ = _parse_csv(output_path)
        assert headers == ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]

    def test_row_count_matches_kicad_pos(self, output_path):
        """Output should have the same number of rows as the KiCad POS
        file (38 in sample)."""
        _, rows = _parse_csv(output_path)
        assert len(rows) == 38

    def test_designator_maps_from_ref(self, output_path):
        """First KiCad row Ref='C1' → Designator='C1'."""
        _, rows = _parse_csv(output_path)
        assert rows[0]["Designator"] == "C1"

    def test_mid_x_has_mm_suffix(self, output_path):
        """All Mid X values should end with 'mm'."""
        _, rows = _parse_csv(output_path)
        for row in rows:
            assert row["Mid X"].endswith("mm"), f"Mid X missing mm: {row['Mid X']}"

    def test_mid_y_has_mm_suffix(self, output_path):
        """All Mid Y values should end with 'mm'."""
        _, rows = _parse_csv(output_path)
        for row in rows:
            assert row["Mid Y"].endswith("mm"), f"Mid Y missing mm: {row['Mid Y']}"

    def test_layer_mapped_from_side(self, output_path):
        """KiCad 'top' side → JLCPCB 'Top' layer."""
        _, rows = _parse_csv(output_path)
        for row in rows:
            assert row["Layer"] in (
                "Top",
                "Bottom",
            ), f"Unexpected layer: {row['Layer']}"

    def test_all_components_top_in_sample(self, output_path):
        """All components in the sample file are on the top side."""
        _, rows = _parse_csv(output_path)
        for row in rows:
            assert row["Layer"] == "Top"

    def test_coord_values_are_numeric(self, output_path):
        """Mid X and Mid Y should be parseable as floats (after stripping 'mm')."""
        _, rows = _parse_csv(output_path)
        for row in rows:
            float(row["Mid X"].removesuffix("mm"))
            float(row["Mid Y"].removesuffix("mm"))

    def test_rotation_preserved(self, output_path):
        """First row C1 has Rot=-90.000000 in KiCad source."""
        _, rows = _parse_csv(output_path)
        c1 = next(r for r in rows if r["Designator"] == "C1")
        assert float(c1["Rotation"]) == pytest.approx(-90.0)

    def test_output_file_written(self, tmp_path):
        out = tmp_path / "out-cpl.csv"
        result = _run("--jlcpcb", str(KICAD_POS), str(out))
        assert result.exit_code == 0
        assert out.exists()
        assert out.stat().st_size > 0
