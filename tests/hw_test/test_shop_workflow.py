"""Unit tests for workflow pure functions (_rank, _matches_vendor_filter)."""

import pytest

from hw.circuits.models.bom import BOM
from hw.circuits.shop.workflow import (
    _matches_vendor_filter,
    _rank,
    _search_item,
    generate_plan,
)
from tests.hw_test.conftest import FakeAdapter, make_bom_item, make_part


class TestRank:
    """Tests for _rank sort key function."""

    def test_in_stock_before_out_of_stock(self):
        """Parts with stock sort before parts without stock."""
        in_stock = make_part(quantity_in_stock=100)
        out_of_stock = make_part(quantity_in_stock=0)

        key_in = _rank(in_stock)
        key_out = _rank(out_of_stock)

        # Rank returns (-in_stock, -qty, price) where in_stock is 1 (has stock) or 0 (no stock)
        # in_stock=100 -> in_stock=1 -> first element = -1
        # in_stock=0 -> in_stock=0 -> first element = -0 = 0
        assert key_in[0] == -1  # Has stock
        assert key_out[0] == 0  # No stock
        assert key_in < key_out  # -1 < 0

    def test_higher_stock_first(self):
        """Among in-stock parts, higher stock sorts first."""
        high = make_part(quantity_in_stock=1000)
        low = make_part(quantity_in_stock=10)

        key_high = _rank(high)
        key_low = _rank(low)

        # Both in stock, so first element is same (-1)
        # Second element: -qty, so -1000 < -10
        assert key_high[1] == -1000
        assert key_low[1] == -10
        assert key_high < key_low

    def test_lower_price_first_when_stock_equal(self):
        """With equal stock, lower price sorts first."""
        cheap = make_part(quantity_in_stock=100, unit_price=0.10)
        expensive = make_part(quantity_in_stock=100, unit_price=1.00)

        key_cheap = _rank(cheap)
        key_expensive = _rank(expensive)

        # Same in_stock and qty, so price is the tiebreaker
        assert key_cheap[2] == 0.10
        assert key_expensive[2] == 1.00
        assert key_cheap < key_expensive

    def test_none_stock_treated_as_zero(self):
        """None quantity_in_stock is treated as 0 (out of stock)."""
        part_with_stock = make_part(quantity_in_stock=100)
        part_none_stock = make_part(quantity_in_stock=None)

        key_stock = _rank(part_with_stock)
        key_none = _rank(part_none_stock)

        # part_with_stock: in_stock=1 (100 > 0) -> first element = -1
        # part_none_stock: in_stock=0 (None coalesces to 0, not > 0) -> first element = 0
        assert key_stock[0] == -1  # Has stock
        assert key_none[0] == 0  # No stock
        assert key_stock < key_none  # -1 < 0

    def test_none_price_treated_as_very_high(self):
        """None unit_price is treated as 9,999,999 (worst case)."""
        with_price = make_part(quantity_in_stock=100, unit_price=1.00)
        no_price = make_part(quantity_in_stock=100, unit_price=None)

        key_price = _rank(with_price)
        key_none = _rank(no_price)

        # no_price should have very high price in sort key
        assert key_price[2] == 1.00
        assert key_none[2] == 9_999_999.0
        assert key_price < key_none

    def test_full_sort_order(self):
        """Full sort order prioritizes: in-stock > quantity > price."""
        parts = [
            make_part(quantity_in_stock=0, unit_price=0.10),  # out-of-stock, cheap
            make_part(
                quantity_in_stock=100, unit_price=10.00
            ),  # in-stock, expensive, small qty
            make_part(
                quantity_in_stock=1000, unit_price=0.10
            ),  # in-stock, cheap, large qty
            make_part(
                quantity_in_stock=100, unit_price=0.10
            ),  # in-stock, cheap, small qty
        ]

        sorted_parts = sorted(parts, key=_rank)

        # Expected order:
        # 1. in-stock, highest qty, cheapest: index 2
        # 2. in-stock, medium qty, cheapest: index 3
        # 3. in-stock, medium qty, expensive: index 1
        # 4. out-of-stock: index 0
        assert sorted_parts[0].quantity_in_stock == 1000
        assert sorted_parts[1].quantity_in_stock == 100
        assert sorted_parts[1].unit_price == 0.10
        assert sorted_parts[2].quantity_in_stock == 100
        assert sorted_parts[2].unit_price == 10.00
        assert sorted_parts[3].quantity_in_stock == 0


class TestMatchesVendorFilter:
    """Tests for _matches_vendor_filter vendor name matching."""

    def test_empty_filter_matches_all(self):
        """Empty filter matches any part."""
        part = make_part(distributor_name="DigiKey")
        assert _matches_vendor_filter(part, []) is True

    def test_exact_vendor_name_match(self):
        """Exact vendor name match returns True."""
        part = make_part(distributor_name="DigiKey")
        assert _matches_vendor_filter(part, ["DigiKey"]) is True

    def test_case_insensitive_match(self):
        """Matching is case-insensitive."""
        part = make_part(distributor_name="DigiKey")
        assert _matches_vendor_filter(part, ["digikey"]) is True
        assert _matches_vendor_filter(part, ["DIGIKEY"]) is True

    def test_substring_match(self):
        """Substring matching works (case-insensitive)."""
        part = make_part(distributor_name="Digi-Key Electronics")
        assert _matches_vendor_filter(part, ["digi"]) is True
        assert _matches_vendor_filter(part, ["key"]) is True
        assert _matches_vendor_filter(part, ["electronics"]) is True

    def test_multiple_filters_any_match(self):
        """Returns True if any filter matches."""
        part = make_part(distributor_name="DigiKey")
        assert _matches_vendor_filter(part, ["Mouser", "DigiKey"]) is True
        assert _matches_vendor_filter(part, ["Mouser", "Avnet"]) is False

    def test_no_match_returns_false(self):
        """Returns False if no vendor matches."""
        part = make_part(distributor_name="DigiKey")
        assert _matches_vendor_filter(part, ["Mouser"]) is False

    def test_none_distributor_returns_false(self):
        """Returns False when distributor_name is None."""
        part = make_part(distributor_name=None)
        assert _matches_vendor_filter(part, ["any"]) is False

    def test_empty_distributor_string_returns_false(self):
        """Returns False when distributor_name is empty string."""
        part = make_part(distributor_name="")
        assert _matches_vendor_filter(part, ["any"]) is False

    def test_empty_filter_with_none_distributor(self):
        """Empty filter matches even with None distributor."""
        part = make_part(distributor_name=None)
        assert _matches_vendor_filter(part, []) is True

    def test_whitespace_handling(self):
        """Strips whitespace from filter strings in matching."""
        part = make_part(distributor_name="DigiKey")
        # " digi " is not in "digikey" as a substring (spaces don't match)
        assert _matches_vendor_filter(part, [" digi "]) is False
        # But "digi" (without spaces) does match
        assert _matches_vendor_filter(part, ["digi"]) is True

    def test_filter_with_multiple_parts(self):
        """Filter multiple parts correctly."""
        digikey_part = make_part(distributor_name="DigiKey")
        mouser_part = make_part(distributor_name="Mouser")

        filters = ["digikey", "mouser"]

        assert _matches_vendor_filter(digikey_part, filters) is True
        assert _matches_vendor_filter(mouser_part, filters) is True

        # Only DigiKey filter
        assert _matches_vendor_filter(digikey_part, ["digikey"]) is True
        assert _matches_vendor_filter(mouser_part, ["digikey"]) is False


class TestSearchItem:
    """Tests for _search_item async function."""

    @pytest.mark.asyncio
    async def test_search_returns_ranked_candidates(self):
        """_search_item returns ranked candidates."""
        adapter = FakeAdapter()
        candidates = [
            make_part(part_number="P1", quantity_in_stock=100, unit_price=0.50),
            make_part(part_number="P2", quantity_in_stock=50, unit_price=0.40),
            make_part(part_number="P3", quantity_in_stock=0, unit_price=0.30),
        ]
        # _search_item tries part_number first ("LM358DR"), which fails, then falls back to value ("LM358")
        adapter.add_error("LM358DR")  # First search fails
        adapter.add_result("LM358", candidates)  # Fallback succeeds

        results, err = await _search_item(
            adapter=adapter,
            bom_item_value="LM358",
            bom_item_footprint="",  # empty → query = value unchanged
            bom_item_part_number="LM358DR",
            max_vendors=3,
            vendors_filter=[],
        )

        # Should return all 3, ranked by _rank (in-stock first)
        assert len(results) == 3
        assert results[0].quantity_in_stock == 100  # Highest stock first
        assert results[1].quantity_in_stock == 50
        assert results[2].quantity_in_stock == 0
        assert err is None

    @pytest.mark.asyncio
    async def test_search_respects_max_vendors(self):
        """_search_item truncates results to max_vendors."""
        adapter = FakeAdapter()
        candidates = [
            make_part(part_number=f"P{i}", quantity_in_stock=1000 - i * 100)
            for i in range(10)
        ]
        adapter.add_result("TEST", candidates)

        results, _err = await _search_item(
            adapter=adapter,
            bom_item_value="TEST",
            bom_item_footprint="",
            bom_item_part_number=None,
            max_vendors=3,
            vendors_filter=[],
        )

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_search_applies_vendor_filter(self):
        """_search_item filters by vendor."""
        adapter = FakeAdapter()
        candidates = [
            make_part(part_number="DK1", distributor_name="DigiKey"),
            make_part(part_number="MOU1", distributor_name="Mouser"),
            make_part(part_number="DK2", distributor_name="DigiKey"),
        ]
        adapter.add_result("PART", candidates)

        results, _err = await _search_item(
            adapter=adapter,
            bom_item_value="PART",
            bom_item_footprint="",
            bom_item_part_number=None,
            max_vendors=10,
            vendors_filter=["digikey"],
        )

        assert len(results) == 2
        assert all("DigiKey" in c.distributor_name for c in results)

    @pytest.mark.asyncio
    async def test_search_fallback_on_error(self):
        """_search_item retries with value if part_number search fails."""
        adapter = FakeAdapter()
        # First search (by part_number) will fail
        adapter.add_error("LM358DR")
        # Second search (by value) will succeed
        adapter.add_result("LM358", [make_part(part_number="LM358")])

        results, err = await _search_item(
            adapter=adapter,
            bom_item_value="LM358",
            bom_item_footprint="",
            bom_item_part_number="LM358DR",
            max_vendors=10,
            vendors_filter=[],
        )

        assert len(results) == 1
        assert results[0].part_number == "LM358"
        assert err is None  # fallback succeeded

    @pytest.mark.asyncio
    async def test_search_fallback_returns_empty_on_both_fail(self):
        """_search_item returns empty list if both searches fail."""
        adapter = FakeAdapter()
        adapter.add_error("LM358DR")
        adapter.add_error("LM358")

        results, err = await _search_item(
            adapter=adapter,
            bom_item_value="LM358",
            bom_item_footprint="",
            bom_item_part_number="LM358DR",
            max_vendors=10,
            vendors_filter=[],
        )

        assert results == []
        assert err is not None  # error reason surfaced

    @pytest.mark.asyncio
    async def test_search_without_part_number_uses_value(self):
        """_search_item uses value when part_number is None."""
        adapter = FakeAdapter()
        adapter.add_result("10k", [make_part(value="10k")])

        results, _err = await _search_item(
            adapter=adapter,
            bom_item_value="10k",
            bom_item_footprint="",  # empty footprint → query = "10k" unchanged
            bom_item_part_number=None,
            max_vendors=10,
            vendors_filter=[],
        )

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_error_captured_not_swallowed(self):
        """If both searches fail, error reason is returned in tuple."""
        adapter = FakeAdapter()
        adapter.add_error("BROKEN")

        results, err = await _search_item(
            adapter=adapter,
            bom_item_value="BROKEN",
            bom_item_footprint="",
            bom_item_part_number=None,
            max_vendors=3,
            vendors_filter=[],
        )
        assert results == []
        assert err is not None and len(err) > 0


class TestGeneratePlan:
    """Tests for generate_plan async function."""

    @pytest.mark.asyncio
    async def test_generate_plan_basic(self):
        """generate_plan returns ShoppingPlan with candidates."""
        bom = BOM(
            items=[
                # Use footprints without EIA codes so build_search_query
                # returns the raw value → FakeAdapter registrations match.
                make_bom_item(references=["R1", "R2"], value="10k", footprint="Custom"),
                make_bom_item(references=["U1"], value="STM32", footprint="BGA"),
            ],
            format="kicad",
            filename="test.csv",
        )

        adapter = FakeAdapter()
        adapter.add_result("10k", [make_part(part_number="RES-10K")])
        adapter.add_result("STM32", [make_part(part_number="STM32F4")])

        plan = await generate_plan(bom=bom, adapter=adapter)

        assert len(plan.items) == 2
        assert plan.items[0].is_sourced is True
        assert plan.items[0].best.part_number == "RES-10K"
        assert plan.items[1].best.part_number == "STM32F4"

    @pytest.mark.asyncio
    async def test_generate_plan_links_bom_fields(self):
        """generate_plan sets references/value/footprint on candidates."""
        bom = BOM(
            items=[
                make_bom_item(references=["R1", "R2"], value="10k", footprint="Custom")
            ],
            format="kicad",
        )

        adapter = FakeAdapter()
        part = make_part(part_number="RES-10K", references=None)  # Not yet set
        adapter.add_result("10k", [part])

        plan = await generate_plan(bom=bom, adapter=adapter)

        # Candidate should have BOM linkage fields set
        candidate = plan.items[0].best
        assert candidate.references == ["R1", "R2"]
        assert candidate.value == "10k"
        assert candidate.footprint == "Custom"

    @pytest.mark.asyncio
    async def test_generate_plan_respects_vendor_filter(self):
        """generate_plan applies vendor filter."""
        bom = BOM(
            items=[make_bom_item(value="TEST", footprint="Custom")], format="kicad"
        )

        adapter = FakeAdapter()
        candidates = [
            make_part(part_number="DK1", distributor_name="DigiKey"),
            make_part(part_number="MOU1", distributor_name="Mouser"),
        ]
        adapter.add_result("TEST", candidates)

        plan = await generate_plan(bom=bom, adapter=adapter, vendors_filter=["digikey"])

        # Should only have DigiKey part
        assert plan.items[0].best.distributor_name == "DigiKey"
        assert len(plan.items[0].candidates) == 1

    @pytest.mark.asyncio
    async def test_generate_plan_progress_callback(self):
        """generate_plan calls progress callback."""
        bom = BOM(
            items=[
                make_bom_item(value="A", footprint="Custom"),
                make_bom_item(value="B", footprint="Custom"),
                make_bom_item(value="C", footprint="Custom"),
            ],
            format="kicad",
        )

        adapter = FakeAdapter()
        adapter.add_result("A", [make_part()])
        adapter.add_result("B", [make_part()])
        adapter.add_result("C", [make_part()])

        progress_calls = []

        def on_progress(done, total):
            progress_calls.append((done, total))

        plan = await generate_plan(bom=bom, adapter=adapter, on_progress=on_progress)

        # Should have 3 calls, one for each item
        assert len(progress_calls) == 3
        assert progress_calls[-1] == (3, 3)  # Last call shows 3 of 3

    @pytest.mark.asyncio
    async def test_generate_plan_handles_unsourced_items(self):
        """generate_plan handles items with no matches."""
        bom = BOM(
            items=[
                make_bom_item(value="FOUND", footprint="Custom"),
                make_bom_item(value="NOTFOUND", footprint="Custom"),
            ],
            format="kicad",
        )

        adapter = FakeAdapter()
        adapter.add_result("FOUND", [make_part()])
        adapter.add_result("NOTFOUND", [])  # No results

        plan = await generate_plan(bom=bom, adapter=adapter)

        assert plan.sourced_count == 1
        assert plan.unsourced_count == 1
