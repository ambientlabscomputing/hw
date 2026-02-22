"""E2E tests for the bom-lookup command."""

import csv
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from hw.circuits.jlcpcb.bom_lookup.command import bom_lookup
from hw.circuits.jlcpcb.bom_lookup.models import JlcpcbSearchResult


def create_test_bom(file_path: Path) -> None:
    """Create a test JLCPCB BOM CSV file."""
    headers = ["Comment", "Designator", "Footprint", "JLCPCB Part ＃（optional）"]
    rows = [
        ["100nF", "C1,C2,C3", "C_0402_1005Metric", ""],
        ["10uF", "C4", "C_0805_2012Metric", ""],
        ["ESP32-S3-WROOM-1", "U1", "ESP32-S3-WROOM-1", ""],
    ]

    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def mock_search_part(comment: str, footprint: str) -> list[JlcpcbSearchResult]:
    """Mock search_part function that returns predictable results."""
    results = {
        "100nF": [
            JlcpcbSearchResult(
                lcsc_part="C1234",
                description="100nF Capacitor",
                package="0402",
                stock=1000,
                price=0.01,
                source="jlcpcb",
            ),
        ],
        "10uF": [
            JlcpcbSearchResult(
                lcsc_part="C5678",
                description="10uF Capacitor",
                package="0805",
                stock=500,
                price=0.05,
                source="jlcpcb",
            ),
        ],
        "ESP32-S3-WROOM-1": [
            JlcpcbSearchResult(
                lcsc_part="C2913203",
                description="ESP32-S3-WROOM-1",
                package="SMD",
                stock=100,
                price=2.50,
                source="jlcpcb",
            ),
        ],
    }

    return results.get(comment, [])


def test_bom_lookup_success(tmp_path: Path) -> None:
    """Test successful BOM lookup."""
    # Create test BOM file
    bom_file = tmp_path / "test_bom.csv"
    create_test_bom(bom_file)

    runner = CliRunner()

    with patch(
        "hw.circuits.jlcpcb.bom_lookup.command.search_part",
        side_effect=mock_search_part,
    ):
        result = runner.invoke(bom_lookup, [str(bom_file)])

    # Check exit code
    assert result.exit_code == 0

    # Check output
    assert "All 3 parts resolved successfully" in result.output

    # Check BOM file was updated
    with open(bom_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 3
    assert rows[0]["JLCPCB Part ＃（optional）"] == "C1234"
    assert rows[1]["JLCPCB Part ＃（optional）"] == "C5678"
    assert rows[2]["JLCPCB Part ＃（optional）"] == "C2913203"


def test_bom_lookup_dry_run(tmp_path: Path) -> None:
    """Test BOM lookup with --dry-run flag."""
    # Create test BOM file
    bom_file = tmp_path / "test_bom.csv"
    create_test_bom(bom_file)

    runner = CliRunner()

    with patch(
        "hw.circuits.jlcpcb.bom_lookup.command.search_part",
        side_effect=mock_search_part,
    ):
        result = runner.invoke(bom_lookup, [str(bom_file), "--dry-run"])

    # Check exit code
    assert result.exit_code == 0

    # Check output indicates dry run
    assert "(dry run)" in result.output

    # Check BOM file was NOT updated
    with open(bom_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Part numbers should still be empty
    assert rows[0]["JLCPCB Part ＃（optional）"] == ""
    assert rows[1]["JLCPCB Part ＃（optional）"] == ""
    assert rows[2]["JLCPCB Part ＃（optional）"] == ""


def test_bom_lookup_with_errors(tmp_path: Path) -> None:
    """Test BOM lookup when some parts fail to resolve."""
    bom_file = tmp_path / "test_bom.csv"
    create_test_bom(bom_file)

    def mock_search_with_failures(
        comment: str, footprint: str
    ) -> list[JlcpcbSearchResult]:
        """Mock that returns results for some parts but not others."""
        if comment == "100nF":
            return mock_search_part(comment, footprint)
        else:
            return []  # No results for other parts

    runner = CliRunner()

    with patch(
        "hw.circuits.jlcpcb.bom_lookup.command.search_part",
        side_effect=mock_search_with_failures,
    ):
        result = runner.invoke(bom_lookup, [str(bom_file)])

    # Check exit code indicates failure
    assert result.exit_code == 1

    # Check output shows partial success
    assert "Resolved 1/3 parts" in result.output
    assert "2 parts failed to resolve" in result.output
    assert "Failed Parts" in result.output

    # Check BOM file was updated with successful resolutions
    with open(bom_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert rows[0]["JLCPCB Part ＃（optional）"] == "C1234"  # Resolved
    assert rows[1]["JLCPCB Part ＃（optional）"] == ""  # Failed
    assert rows[2]["JLCPCB Part ＃（optional）"] == ""  # Failed


def test_bom_lookup_empty_file(tmp_path: Path) -> None:
    """Test BOM lookup with an empty file."""
    bom_file = tmp_path / "empty_bom.csv"

    # Create empty BOM
    headers = ["Comment", "Designator", "Footprint", "JLCPCB Part ＃（optional）"]
    with open(bom_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

    runner = CliRunner()
    result = runner.invoke(bom_lookup, [str(bom_file)])

    # Should handle empty file gracefully
    assert "No parts found" in result.output
