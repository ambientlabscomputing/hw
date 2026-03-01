"""CLI integration tests for hw circuits shop commands."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from hw.circuits.models.bom import BOM, Format
from hw.circuits.shop.command import order, plan, search
from tests.hw_test.conftest import (
    FakeAdapter,
    make_bom_item,
    make_part,
    make_shopping_plan,
    make_shopping_plan_item,
)


class TestSearchCommand:
    """Tests for `hw circuits shop search` command."""

    def test_search_success(self):
        """Successfully searches and displays results."""
        runner = CliRunner()

        with patch(
            "hw.circuits.shop.command.OemSecretsAPIAdapter"
        ) as mock_adapter_class:
            mock_adapter = MagicMock()
            mock_adapter.search = AsyncMock()
            mock_adapter.search.return_value = [
                make_part(part_number="LM358", quantity_in_stock=1000, unit_price=0.47),
                make_part(
                    part_number="LM358",
                    quantity_in_stock=500,
                    unit_price=0.50,
                    distributor_name="Mouser",
                ),
            ]
            mock_adapter_class.return_value = mock_adapter

            result = runner.invoke(search, ["LM358"])

            assert result.exit_code == 0
            assert "LM358" in result.output
            assert "DigiKey" in result.output or "Mouser" in result.output

    def test_search_no_results(self):
        """Handles no search results gracefully."""
        runner = CliRunner()

        with patch(
            "hw.circuits.shop.command.OemSecretsAPIAdapter"
        ) as mock_adapter_class:
            mock_adapter = MagicMock()
            mock_adapter.search = AsyncMock(return_value=[])
            mock_adapter_class.return_value = mock_adapter

            result = runner.invoke(search, ["NOTFOUND"])

            assert result.exit_code == 0
            assert "No results found" in result.output

    def test_search_with_currency_option(self):
        """Accepts --currency option."""
        runner = CliRunner()

        with patch(
            "hw.circuits.shop.command.OemSecretsAPIAdapter"
        ) as mock_adapter_class:
            mock_adapter = MagicMock()
            mock_adapter.search = AsyncMock(return_value=[])
            mock_adapter_class.return_value = mock_adapter

            result = runner.invoke(search, ["TEST", "--currency", "EUR"])

            assert result.exit_code == 0

    def test_search_api_error(self):
        """Handles API errors."""
        runner = CliRunner()

        with patch(
            "hw.circuits.shop.command.OemSecretsAPIAdapter"
        ) as mock_adapter_class:
            mock_adapter = MagicMock()
            mock_adapter.search = MagicMock(side_effect=Exception("API Error"))
            mock_adapter_class.return_value = mock_adapter

            result = runner.invoke(search, ["TEST"])

            assert result.exit_code != 0
            assert "API Error" in result.output or "Search failed" in result.output


class TestPlanCommand:
    """Tests for `hw circuits shop plan` command."""

    def test_plan_success(self, tmp_path):
        """Successfully generates a shopping plan."""
        runner = CliRunner()

        # Create test BOM file
        bom_file = tmp_path / "test.csv"
        bom = BOM(
            items=[
                make_bom_item(references=["R1"], value="10k"),
                make_bom_item(references=["C1"], value="100n"),
            ],
            format=Format.KICAD,
            filename=str(bom_file),
        )
        bom.write_csv()

        output_file = tmp_path / "plan.json"

        with patch(
            "hw.circuits.shop.command.OemSecretsAPIAdapter"
        ) as mock_adapter_class:
            mock_adapter = FakeAdapter()
            mock_adapter.add_result("10k", [make_part(part_number="RES-10K")])
            mock_adapter.add_result("100n", [make_part(part_number="CAP-100N")])
            mock_adapter_class.return_value = mock_adapter

            result = runner.invoke(plan, [str(bom_file), "-o", str(output_file)])

            assert result.exit_code == 0
            assert output_file.exists()

            # Verify output is valid JSON
            plan_data = json.loads(output_file.read_text())
            assert "items" in plan_data
            assert len(plan_data["items"]) == 2

    def test_plan_with_vendor_filter(self, tmp_path):
        """Plan respects vendor filter option."""
        runner = CliRunner()

        bom_file = tmp_path / "test.csv"
        bom = BOM(
            items=[make_bom_item(value="TEST")],
            format=Format.KICAD,
            filename=str(bom_file),
        )
        bom.write_csv()

        output_file = tmp_path / "plan.json"

        with patch(
            "hw.circuits.shop.command.OemSecretsAPIAdapter"
        ) as mock_adapter_class:
            mock_adapter = FakeAdapter()
            mock_adapter.add_result(
                "TEST",
                [
                    make_part(part_number="DK1", distributor_name="DigiKey"),
                    make_part(part_number="MOU1", distributor_name="Mouser"),
                ],
            )
            mock_adapter_class.return_value = mock_adapter

            result = runner.invoke(
                plan,
                [
                    str(bom_file),
                    "-o",
                    str(output_file),
                    "--vendors",
                    "digikey",
                ],
            )

            assert result.exit_code == 0
            plan_data = json.loads(output_file.read_text())
            assert plan_data["vendors_filter"] == ["digikey"]

    def test_plan_with_max_vendors(self, tmp_path):
        """Plan respects max-vendors option."""
        runner = CliRunner()

        bom_file = tmp_path / "test.csv"
        bom = BOM(
            items=[make_bom_item(value="TEST")],
            format=Format.KICAD,
            filename=str(bom_file),
        )
        bom.write_csv()

        output_file = tmp_path / "plan.json"

        with patch(
            "hw.circuits.shop.command.OemSecretsAPIAdapter"
        ) as mock_adapter_class:
            mock_adapter = FakeAdapter()
            mock_adapter.add_result(
                "TEST", [make_part(part_number=f"P{i}") for i in range(10)]
            )
            mock_adapter_class.return_value = mock_adapter

            result = runner.invoke(
                plan,
                [
                    str(bom_file),
                    "-o",
                    str(output_file),
                    "--max-vendors",
                    "2",
                ],
            )

            assert result.exit_code == 0
            plan_data = json.loads(output_file.read_text())
            assert plan_data["max_vendors"] == 2
            # Plan items should have max 2 candidates
            for item in plan_data["items"]:
                assert len(item["candidates"]) <= 2

    def test_plan_bad_bom_file(self):
        """Handles missing BOM file."""
        runner = CliRunner()

        result = runner.invoke(plan, ["/nonexistent/file.csv", "-o", "/tmp/out.json"])

        assert result.exit_code != 0

    def test_plan_no_output_file(self, tmp_path):
        """Requires --output option."""
        runner = CliRunner()

        bom_file = tmp_path / "test.csv"
        bom = BOM(items=[make_bom_item()], format=Format.KICAD, filename=str(bom_file))
        bom.write_csv()

        result = runner.invoke(plan, [str(bom_file)])

        assert result.exit_code != 0


class TestOrderCommand:
    """Tests for `hw circuits shop order` command."""

    def test_order_success(self, tmp_path):
        """Successfully processes order plan."""
        runner = CliRunner()

        # Create a plan file
        plan_data = make_shopping_plan(
            items=[
                make_shopping_plan_item(
                    candidates=[
                        make_part(
                            part_number="DK-001",
                            source_part_number="296-1395-5-ND",
                            distributor_name="DigiKey",
                            references=["U1"],
                        )
                    ]
                )
            ]
        )

        plan_file = tmp_path / "plan.json"
        plan_file.write_text(plan_data.model_dump_json())

        with patch("hw.circuits.shop.command.click.launch") as mock_launch:
            result = runner.invoke(order, [str(plan_file)])

            assert result.exit_code == 0
            assert "DigiKey" in result.output
            # Should have called launch with a URL
            assert mock_launch.called or "Cart URL" in result.output

    def test_order_no_browser_flag(self, tmp_path):
        """--no-browser prints URL instead of launching."""
        runner = CliRunner()

        plan_data = make_shopping_plan(
            items=[
                make_shopping_plan_item(
                    candidates=[
                        make_part(
                            part_number="DK-001",
                            source_part_number="296-1395-5-ND",
                            distributor_name="DigiKey",
                            references=["U1"],
                        )
                    ]
                )
            ]
        )

        plan_file = tmp_path / "plan.json"
        plan_file.write_text(plan_data.model_dump_json())

        with patch("hw.circuits.shop.command.click.launch") as mock_launch:
            result = runner.invoke(order, [str(plan_file), "--no-browser"])

            assert result.exit_code == 0
            assert "Cart URL" in result.output
            assert not mock_launch.called

    def test_order_no_sourced_items(self, tmp_path):
        """Handles plan with no sourced items."""
        runner = CliRunner()

        plan_data = make_shopping_plan(
            items=[make_shopping_plan_item(candidates=[])]  # Unsourced
        )

        plan_file = tmp_path / "plan.json"
        plan_file.write_text(plan_data.model_dump_json())

        result = runner.invoke(order, [str(plan_file)])

        assert result.exit_code == 0
        assert "nothing to order" in result.output.lower()

    def test_order_bad_plan_file(self):
        """Handles invalid plan file."""
        runner = CliRunner()

        result = runner.invoke(order, ["/nonexistent/plan.json"])

        assert result.exit_code != 0
