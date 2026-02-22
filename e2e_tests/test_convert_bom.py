"""
End-to-end tests for `hw circuits kicad convert bom`.

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
KICAD_BOM = SAMPLE_DIR / "kicad-generated-bom.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(*args):
    runner = CliRunner()
    return runner.invoke(main, ["circuits", "kicad", "convert", "bom", *args])


def _parse_csv(text: str) -> tuple[list[str], list[dict]]:
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return list(reader.fieldnames or []), rows


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBomHelp:
    def test_help_exits_zero(self):
        result = _run("--help")
        assert result.exit_code == 0

    def test_help_mentions_jlcpcb(self):
        result = _run("--help")
        assert "--jlcpcb" in result.output


class TestBomNoFlag:
    def test_no_flag_errors(self, tmp_path):
        out = tmp_path / "out.csv"
        result = _run(str(KICAD_BOM), str(out))
        assert result.exit_code != 0

    def test_no_flag_error_message(self, tmp_path):
        out = tmp_path / "out.csv"
        result = _run(str(KICAD_BOM), str(out))
        assert "target format" in result.output.lower()


class TestBomJlcpcb:
    @pytest.fixture()
    def result_and_csv(self, tmp_path):
        out = tmp_path / "out-bom.csv"
        result = _run("--jlcpcb", str(KICAD_BOM), str(out))
        assert result.exit_code == 0, (
            f"Command failed (exit {result.exit_code}):\n"
            f"output: {result.output}\n"
            f"exception: {result.exception}"
        )
        content = out.read_text(encoding="utf-8")
        headers = content.splitlines()[0].split(",")
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        return result, headers, rows

    def test_exits_zero(self, result_and_csv):
        result, _, _ = result_and_csv
        assert result.exit_code == 0

    def test_correct_headers(self, result_and_csv):
        _, headers, _ = result_and_csv
        assert headers[0] == "Comment"
        assert headers[1] == "Designator"
        assert headers[2] == "Footprint"
        # 4th header is the JLCPCB part number column (contains unicode chars)
        assert "JLCPCB" in headers[3] or "optional" in headers[3].lower()

    def test_row_count_matches_kicad_bom(self, result_and_csv):
        """Output should have one row per KiCad BOM line (25 in sample)."""
        _, _, rows = result_and_csv
        assert len(rows) == 25

    def test_comment_maps_from_designation(self, result_and_csv):
        """First KiCad row Designation is '100nF' → Comment should be '100nF'."""
        _, _, rows = result_and_csv
        assert rows[0]["Comment"] == "100nF"

    def test_designator_preserved(self, result_and_csv):
        """Designators (possibly grouped) are preserved as-is."""
        _, _, rows = result_and_csv
        # First row in sample: C11,C13,C16,C2,C7
        assert rows[0]["Designator"] == "C11,C13,C16,C2,C7"

    def test_footprint_preserved(self, result_and_csv):
        _, _, rows = result_and_csv
        assert rows[0]["Footprint"] == "C_0402_1005Metric"

    def test_jlcpcb_part_empty(self, result_and_csv):
        """JLCPCB Part # column should be blank – user fills it later."""
        _, _, rows = result_and_csv
        part_key = [k for k in rows[0] if "JLCPCB" in k or "optional" in k.lower()][0]
        for row in rows:
            assert row[part_key] == ""

    def test_output_file_written(self, tmp_path):
        out = tmp_path / "out-bom.csv"
        result = _run("--jlcpcb", str(KICAD_BOM), str(out))
        assert result.exit_code == 0
        assert out.exists()
        assert out.stat().st_size > 0
