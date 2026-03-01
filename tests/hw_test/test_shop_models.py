"""Unit tests for ShoppingPlan and ShoppingPlanItem models."""

from hw.circuits.shop.models import ShoppingPlan
from tests.hw_test.conftest import (
    make_bom_item,
    make_part,
    make_shopping_plan,
    make_shopping_plan_item,
)


class TestShoppingPlanItem:
    """Tests for ShoppingPlanItem properties."""

    def test_best_returns_first_candidate(self):
        """best property returns the first ranked candidate."""
        candidates = [
            make_part(part_number="A", unit_price=0.50),
            make_part(part_number="B", unit_price=0.75),
        ]
        item = make_shopping_plan_item(candidates=candidates)
        assert item.best == candidates[0]
        assert item.best.part_number == "A"

    def test_best_returns_none_when_no_candidates(self):
        """best property returns None if no candidates."""
        item = make_shopping_plan_item(candidates=[])
        assert item.best is None

    def test_is_sourced_true_when_best_exists(self):
        """is_sourced is True when there is a best candidate."""
        candidates = [make_part()]
        item = make_shopping_plan_item(candidates=candidates)
        assert item.is_sourced is True

    def test_is_sourced_false_when_no_candidates(self):
        """is_sourced is False when no candidates."""
        item = make_shopping_plan_item(candidates=[])
        assert item.is_sourced is False

    def test_preserves_bom_item(self):
        """Stores and returns BOMItem correctly."""
        bom_item = make_bom_item(references=["U1", "U2"], value="STM32F4")
        item = make_shopping_plan_item(bom_item=bom_item)
        assert item.bom_item == bom_item
        assert len(item.bom_item.references) == 2


class TestShoppingPlan:
    """Tests for ShoppingPlan properties and methods."""

    def test_sourced_count_all_sourced(self):
        """sourced_count counts items with candidates."""
        items = [
            make_shopping_plan_item(candidates=[make_part()]),
            make_shopping_plan_item(candidates=[make_part()]),
            make_shopping_plan_item(candidates=[]),  # unsourced
        ]
        plan = make_shopping_plan(items=items)
        assert plan.sourced_count == 2

    def test_sourced_count_none_sourced(self):
        """sourced_count is 0 when no sources found."""
        items = [
            make_shopping_plan_item(candidates=[]),
            make_shopping_plan_item(candidates=[]),
        ]
        plan = make_shopping_plan(items=items)
        assert plan.sourced_count == 0

    def test_unsourced_count(self):
        """unsourced_count is correct."""
        items = [
            make_shopping_plan_item(candidates=[make_part()]),
            make_shopping_plan_item(candidates=[]),
            make_shopping_plan_item(candidates=[]),
        ]
        plan = make_shopping_plan(items=items)
        assert plan.unsourced_count == 2

    def test_sourced_and_unsourced_sum_to_total(self):
        """sourced_count + unsourced_count == len(items)."""
        items = [
            make_shopping_plan_item(candidates=[make_part()]),
            make_shopping_plan_item(candidates=[]),
            make_shopping_plan_item(candidates=[make_part()]),
        ]
        plan = make_shopping_plan(items=items)
        assert plan.sourced_count + plan.unsourced_count == len(plan.items)

    def test_items_for_distributor_exact_match(self):
        """items_for_distributor returns items with matching distributor."""
        digikey_part = make_part(distributor_name="DigiKey")
        mouser_part = make_part(
            part_number="DIF", distributor_name="Mouser Electronics"
        )
        items = [
            make_shopping_plan_item(candidates=[digikey_part]),
            make_shopping_plan_item(candidates=[mouser_part]),
        ]
        plan = make_shopping_plan(items=items)

        digikey_items = plan.items_for_distributor("digikey")
        assert len(digikey_items) == 1
        assert digikey_items[0].best.distributor_name == "DigiKey"

    def test_items_for_distributor_case_insensitive(self):
        """items_for_distributor is case-insensitive."""
        part = make_part(distributor_name="DigiKey")
        items = [make_shopping_plan_item(candidates=[part])]
        plan = make_shopping_plan(items=items)

        assert len(plan.items_for_distributor("DIGIKEY")) == 1
        assert len(plan.items_for_distributor("digikey")) == 1
        assert len(plan.items_for_distributor("DiGiKeY")) == 1

    def test_items_for_distributor_partial_match(self):
        """items_for_distributor does substring matching."""
        part = make_part(distributor_name="Digi-Key Electronics")
        items = [make_shopping_plan_item(candidates=[part])]
        plan = make_shopping_plan(items=items)

        # "digi" should match "Digi-Key Electronics"
        assert len(plan.items_for_distributor("digi")) == 1
        assert len(plan.items_for_distributor("key")) == 1
        assert len(plan.items_for_distributor("electronics")) == 1

    def test_items_for_distributor_returns_empty_for_no_match(self):
        """items_for_distributor returns empty list for no matches."""
        part = make_part(distributor_name="DigiKey")
        items = [make_shopping_plan_item(candidates=[part])]
        plan = make_shopping_plan(items=items)

        assert plan.items_for_distributor("Mouser") == []

    def test_items_for_distributor_skips_unsourced(self):
        """items_for_distributor only returns sourced items."""
        items = [
            make_shopping_plan_item(candidates=[]),  # unsourced
        ]
        plan = make_shopping_plan(items=items)
        assert plan.items_for_distributor("anything") == []

    def test_items_for_distributor_skips_none_distributor(self):
        """items_for_distributor skips items with None distributor_name."""
        part = make_part(distributor_name=None)
        items = [make_shopping_plan_item(candidates=[part])]
        plan = make_shopping_plan(items=items)

        # Should not crash and should return empty
        assert plan.items_for_distributor("any") == []

    def test_json_roundtrip(self):
        """ShoppingPlan can be serialized and deserialized."""
        original = make_shopping_plan(
            items=[
                make_shopping_plan_item(
                    bom_item=make_bom_item(references=["R1", "R2"], value="10k"),
                    candidates=[make_part(part_number="RES10K")],
                )
            ],
            bom_file="resistors.csv",
            max_vendors=5,
        )

        # Serialize and deserialize
        json_str = original.model_dump_json()
        restored = ShoppingPlan.model_validate_json(json_str)

        # Verify key fields match
        assert restored.bom_file == original.bom_file
        assert restored.max_vendors == original.max_vendors
        assert len(restored.items) == len(original.items)
        assert restored.items[0].bom_item.value == "10k"
        assert restored.items[0].best.part_number == "RES10K"

    def test_has_generated_at_timestamp(self):
        """ShoppingPlan has generated_at timestamp."""
        plan = make_shopping_plan()
        assert plan.generated_at is not None
        assert isinstance(plan.generated_at, str)
        # Should be ISO-8601 format
        assert "T" in plan.generated_at  # includes time portion
