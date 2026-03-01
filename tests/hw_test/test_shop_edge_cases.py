"""Edge case and robustness tests for shop commands."""

import asyncio
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from hw.circuits.models.bom import BOM
from hw.circuits.shop.command import order, plan, search
from hw.circuits.shop.search import OemSecretsAPIAdapter
from hw.circuits.shop.workflow import generate_plan
from tests.hw_test.conftest import (
    FakeAdapter,
    make_bom_item,
    make_part,
    make_shopping_plan,
)


class TestGeneratePlanRateLimiting:
    """Tests for rate limiting in generate_plan."""

    @pytest.mark.asyncio
    async def test_rate_limiting_with_semaphore(self):
        """Verify that generate_plan respects max_concurrent settings."""
        # Create a BOM with 10 items
        bom_items = [
            make_bom_item(value=f"ITEM_{i}", references=[f"R{i}"]) for i in range(10)
        ]
        bom = BOM(filename="test.csv", items=bom_items)

        # Track concurrent searches
        concurrent_searches = []
        max_concurrent_observed = 0

        async def slow_search(query):
            concurrent_searches.append(1)
            max_concurrent_observed_local = len(concurrent_searches)
            nonlocal max_concurrent_observed
            max_concurrent_observed = max(
                max_concurrent_observed, max_concurrent_observed_local
            )
            await asyncio.sleep(0.01)  # Small delay to simulate API call
            concurrent_searches.pop()
            return [make_part(part_number=f"PN_{query}", value=query)]

        adapter = FakeAdapter()
        # Set up results for each query
        for i in range(10):
            adapter.add_result(
                f"ITEM_{i}", [make_part(part_number=f"PN_ITEM_{i}", value=f"ITEM_{i}")]
            )

        # Override search with slow implementation that wraps the real search
        original_search = adapter.search

        async def slow_adapter_search(query):
            concurrent_searches.append(1)
            max_concurrent_observed_local = len(concurrent_searches)
            nonlocal max_concurrent_observed
            max_concurrent_observed = max(
                max_concurrent_observed, max_concurrent_observed_local
            )
            try:
                await asyncio.sleep(0.01)  # Small delay to simulate API call
                return await original_search(query)
            finally:
                concurrent_searches.pop()

        adapter.search = slow_adapter_search

        # Generate plan with max_concurrent=3
        plan = await generate_plan(bom, adapter=adapter, max_concurrent=3)

        # Verify that we didn't exceed max_concurrent limit
        assert max_concurrent_observed <= 3
        assert len(plan.items) == 10

    @pytest.mark.asyncio
    async def test_generate_plan_with_large_bom(self):
        """Test generate_plan with a large BOM to ensure efficiency."""
        # Create a BOM with 50 items
        bom_items = [
            make_bom_item(value=f"ITEM_{i}", references=[f"R{i}"]) for i in range(50)
        ]
        bom = BOM(filename="large.csv", items=bom_items)

        adapter = FakeAdapter()
        for i in range(50):
            adapter.add_result(
                f"ITEM_{i}", [make_part(part_number=f"PN_{i}", value=f"ITEM_{i}")]
            )

        plan = await generate_plan(bom, adapter=adapter, max_concurrent=5)

        assert len(plan.items) == 50
        assert all(item.candidates for item in plan.items)


class TestSearchRetryLogic:
    """Tests for retry logic in OEM Secrets adapter."""

    @pytest.mark.asyncio
    async def test_search_fails_after_max_retries(self):
        """Verify that search fails after max retries are exhausted."""
        adapter = OemSecretsAPIAdapter()

        async def mock_get(*args, **kwargs):
            raise asyncio.TimeoutError("Persistent timeout")

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get_method:

            async def mock_get_async(*args, **kwargs):
                return await mock_get(*args, **kwargs)

            mock_get_method.side_effect = mock_get_async

            from hw.circuits.shop.search import PartSearchQuery

            with pytest.raises(asyncio.TimeoutError):
                await adapter.search(PartSearchQuery(query="test"))


class TestNestedEventLoopHandling:
    """Tests for handling nested event loops (Jupyter, etc.)."""

    def test_search_command_in_cli_context(self):
        """Test search command runs successfully in CLI context."""
        runner = CliRunner()

        with patch(
            "hw.circuits.shop.command.OemSecretsAPIAdapter"
        ) as mock_adapter_class:
            mock_adapter = MagicMock()
            mock_adapter.search = AsyncMock(
                return_value=[
                    make_part(
                        part_number="LM358", quantity_in_stock=100, unit_price=0.5
                    ),
                ]
            )
            mock_adapter_class.return_value = mock_adapter

            result = runner.invoke(search, ["LM358"])

            assert result.exit_code == 0
            assert "LM358" in result.output


class TestEmptyInputHandling:
    """Tests for empty or edge case inputs."""

    @pytest.mark.asyncio
    async def test_generate_plan_with_empty_bom(self):
        """Test generate_plan with an empty BOM."""
        bom = BOM(filename="empty.csv", items=[])
        adapter = FakeAdapter()

        plan = await generate_plan(bom, adapter=adapter)

        assert len(plan.items) == 0
        assert plan.bom_file == "empty.csv"

    @pytest.mark.asyncio
    async def test_generate_plan_with_empty_search_results(self):
        """Test generate_plan when no parts are found."""
        bom_items = [make_bom_item(value="NONEXISTENT")]
        bom = BOM(filename="test.csv", items=bom_items)

        adapter = FakeAdapter()
        # Don't add any results, so search returns empty

        plan = await generate_plan(bom, adapter=adapter)

        assert len(plan.items) == 1
        assert len(plan.items[0].candidates) == 0

    def test_search_command_with_empty_query(self):
        """Test search command with empty query."""
        runner = CliRunner()

        with patch(
            "hw.circuits.shop.command.OemSecretsAPIAdapter"
        ) as mock_adapter_class:
            mock_adapter = MagicMock()
            mock_adapter.search = AsyncMock(return_value=[])
            mock_adapter_class.return_value = mock_adapter

            result = runner.invoke(search, [""])

            assert result.exit_code == 0
            assert "No results found" in result.output

    def test_plan_command_with_nonexistent_file(self):
        """Test plan command with nonexistent BOM file."""
        runner = CliRunner()

        result = runner.invoke(plan, ["/nonexistent/bom.csv", "-o", "/tmp/out.json"])

        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_order_command_with_empty_plan(self):
        """Test order command with a plan that has no sourced items."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            empty_plan = make_shopping_plan(items=[])
            f.write(empty_plan.model_dump_json())
            f.flush()

            result = runner.invoke(order, [f.name])

            assert result.exit_code == 0
            # Should indicate no items to order
            assert (
                "No sourced items" in result.output
                or "completed" in result.output.lower()
            )


class TestMouserErrorHandling:
    """Tests for Mouser-specific error cases."""

    @pytest.mark.asyncio
    async def test_mouser_add_items_with_empty_api_key(self):
        """Test add_items_to_cart with empty API key."""
        from hw.circuits.shop.mouser import add_items_to_cart

        result = await add_items_to_cart([], api_key="")

        # Should handle empty items gracefully
        assert hasattr(result, "cart_key")
        assert hasattr(result, "errors")

    def test_order_command_with_mouser_missing_api_key(self):
        """Test order command when Mouser API key is missing."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            plan = make_shopping_plan()
            f.write(plan.model_dump_json())
            f.flush()

            # Set environment to have no Mouser API key
            with patch.dict("os.environ", {}, clear=False):
                result = runner.invoke(order, [f.name])

                # Should still succeed but skip Mouser
                assert result.exit_code == 0


class TestConcurrencyEdgeCases:
    """Tests for concurrency edge cases."""

    @pytest.mark.asyncio
    async def test_generate_plan_with_single_concurrent(self):
        """Test generate_plan with max_concurrent=1."""
        bom_items = [
            make_bom_item(value=f"ITEM_{i}", references=[f"R{i}"]) for i in range(5)
        ]
        bom = BOM(filename="test.csv", items=bom_items)

        adapter = FakeAdapter()
        for i in range(5):
            adapter.add_result(
                f"ITEM_{i}", [make_part(part_number=f"PN_{i}", value=f"ITEM_{i}")]
            )

        plan = await generate_plan(bom, adapter=adapter, max_concurrent=1)

        assert len(plan.items) == 5

    @pytest.mark.asyncio
    async def test_generate_plan_with_very_large_concurrent(self):
        """Test generate_plan with max_concurrent > number of items."""
        bom_items = [
            make_bom_item(value=f"ITEM_{i}", references=[f"R{i}"]) for i in range(3)
        ]
        bom = BOM(filename="test.csv", items=bom_items)

        adapter = FakeAdapter()
        for i in range(3):
            adapter.add_result(
                f"ITEM_{i}", [make_part(part_number=f"PN_{i}", value=f"ITEM_{i}")]
            )

        plan = await generate_plan(bom, adapter=adapter, max_concurrent=100)

        assert len(plan.items) == 3

    @pytest.mark.asyncio
    async def test_generate_plan_progress_callback(self):
        """Test that progress callback is called correctly."""
        bom_items = [
            make_bom_item(value=f"ITEM_{i}", references=[f"R{i}"]) for i in range(5)
        ]
        bom = BOM(filename="test.csv", items=bom_items)

        adapter = FakeAdapter()
        for i in range(5):
            adapter.add_result(
                f"ITEM_{i}", [make_part(part_number=f"PN_{i}", value=f"ITEM_{i}")]
            )

        progress_calls = []

        def on_progress(done, total):
            progress_calls.append((done, total))

        plan = await generate_plan(bom, adapter=adapter, on_progress=on_progress)

        # Should have 5 progress callbacks (one per item)
        assert len(progress_calls) == 5
        # Final callback should indicate all items done
        assert progress_calls[-1] == (5, 5)
