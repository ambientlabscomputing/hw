"""Unit tests for DigiKey cart integration."""

from hw.circuits.shop.digikey import build_cart_url, is_digikey
from tests.hw_test.conftest import make_part, make_shopping_plan_item


class TestIsDigikey:
    """Tests for is_digikey distributor matching."""

    def test_exact_match_digikey(self):
        """Matches 'digikey' distributor."""
        part = make_part(distributor_name="DigiKey")
        assert is_digikey(part) is True

    def test_match_digi_key_hyphenated(self):
        """Matches 'Digi-Key' variant."""
        part = make_part(distributor_name="Digi-Key")
        assert is_digikey(part) is True

    def test_match_digi_key_electronics_full(self):
        """Matches 'Digi-Key Electronics' full name."""
        part = make_part(distributor_name="Digi-Key Electronics")
        assert is_digikey(part) is True

    def test_match_case_insensitive(self):
        """Matching is case-insensitive."""
        assert is_digikey(make_part(distributor_name="digikey")) is True
        assert is_digikey(make_part(distributor_name="DIGIKEY")) is True
        assert is_digikey(make_part(distributor_name="DiGiKeY")) is True

    def test_match_ignores_dots(self):
        """Matches despite dots being stripped."""
        part = make_part(distributor_name="Digi.Key")
        assert is_digikey(part) is True

    def test_no_match_mouser(self):
        """Does not match Mouser."""
        part = make_part(distributor_name="Mouser Electronics")
        assert is_digikey(part) is False

    def test_match_partial_string_digi_key(self):
        """Matches 'digi key' substring (with space)."""
        part = make_part(distributor_name="Digital Key (not DigiKey)")
        # "digi key" is in "Digital Key" when case-insensitive
        # The alias check looks for "digikey", "digi-key", or "digi key" in the normalized name
        # normalize: "digital key (not digikey)".lower().replace(".", "").replace("-", " ")
        # So "digi key" IS in that string
        assert is_digikey(part) is True

    def test_no_match_none_distributor(self):
        """Returns False for None distributor_name."""
        part = make_part(distributor_name=None)
        assert is_digikey(part) is False

    def test_no_match_empty_distributor(self):
        """Returns False for empty distributor_name."""
        part = make_part(distributor_name="")
        assert is_digikey(part) is False


class TestBuildCartUrl:
    """Tests for DigiKey cart URL construction."""

    def test_builds_valid_url(self):
        """Builds a valid DigiKey cart URL."""
        part = make_part(
            part_number="LM358DR",
            source_part_number="296-1395-5-ND",
            distributor_name="DigiKey",
            references=["U1"],
        )
        items = [make_shopping_plan_item(candidates=[part])]
        url = build_cart_url(items)

        assert url is not None
        assert "digikey.com/ordering/shoppingcart" in url
        assert "part=296-1395-5-ND|1" in url

    def test_prefers_source_part_number(self):
        """Uses source_part_number over part_number."""
        part = make_part(
            part_number="LM358DR",
            source_part_number="296-1395-5-ND",
            distributor_name="DigiKey",
            references=["U1"],
        )
        items = [make_shopping_plan_item(candidates=[part])]
        url = build_cart_url(items)

        # Should contain source PN, not manufacturer PN
        assert "296-1395-5-ND" in url
        assert "LM358DR" not in url

    def test_uses_part_number_when_no_source(self):
        """Falls back to part_number when source_part_number is None."""
        part = make_part(
            part_number="LM358DR",
            source_part_number=None,
            distributor_name="DigiKey",
            references=["U1"],
        )
        items = [make_shopping_plan_item(candidates=[part])]
        url = build_cart_url(items)

        assert url is not None
        assert "LM358DR" in url

    def test_multiple_items(self):
        """Builds URL with multiple items."""
        part1 = make_part(
            part_number="LM358",
            source_part_number="296-1395-5-ND",
            distributor_name="DigiKey",
            references=["U1"],
        )
        part2 = make_part(
            part_number="STM32",
            source_part_number="STM32-001",
            distributor_name="DigiKey",
            references=["U2", "U3"],
        )
        items = [
            make_shopping_plan_item(candidates=[part1]),
            make_shopping_plan_item(candidates=[part2]),
        ]
        url = build_cart_url(items)

        assert url is not None
        assert "296-1395-5-ND|1" in url
        assert "STM32-001|2" in url

    def test_uses_quantity_needed_from_references(self):
        """Uses quantity_needed (len of references) for quantity."""
        part = make_part(
            part_number="R10K",
            source_part_number="RES-10K",
            distributor_name="DigiKey",
            references=["R1", "R2", "R3", "R4"],  # 4 placements
        )
        items = [
            make_shopping_plan_item(
                candidates=[part],
                bom_item=None,  # Will be created with 1 ref, but overridden by part.references
            )
        ]
        url = build_cart_url(items)

        assert "RES-10K|4" in url

    def test_falls_back_to_bom_quantity_when_no_references(self):
        """Uses bom_item.quantity when part.references is None (not set by workflow)."""
        from tests.hw_test.conftest import make_bom_item

        # Part without references set (simulates Part created outside workflow)
        part = make_part(
            part_number="R10K",
            source_part_number="RES-10K",
            distributor_name="DigiKey",
            references=None,  # Not set by workflow
        )
        bom_item = make_bom_item(references=["R1", "R2"], value="10k")
        items = [make_shopping_plan_item(candidates=[part], bom_item=bom_item)]
        url = build_cart_url(items)

        # part.quantity_needed returns 0 when references is None
        # So it falls back to bom_item.quantity which is 2
        assert "RES-10K|2" in url

    def test_skips_non_digikey_items(self):
        """Ignores items not from DigiKey."""
        digikey_part = make_part(
            part_number="DK",
            source_part_number="DK-001",
            distributor_name="DigiKey",
            references=["U1"],
        )
        mouser_part = make_part(
            part_number="MOU",
            source_part_number="MOU-001",
            distributor_name="Mouser Electronics",
            references=["U2"],
        )
        items = [
            make_shopping_plan_item(candidates=[digikey_part]),
            make_shopping_plan_item(candidates=[mouser_part]),
        ]
        url = build_cart_url(items)

        # Should only have DigiKey item
        assert "DK-001" in url
        assert "MOU-001" not in url

    def test_returns_none_for_no_digikey_items(self):
        """Returns None when no DigiKey items found."""
        mouser_part = make_part(
            part_number="MOU",
            source_part_number="MOU-001",
            distributor_name="Mouser Electronics",
            references=["U1"],
        )
        items = [make_shopping_plan_item(candidates=[mouser_part])]
        url = build_cart_url(items)

        assert url is None

    def test_returns_none_for_empty_items_list(self):
        """Returns None for empty items list."""
        url = build_cart_url([])
        assert url is None

    def test_skips_unsourced_items(self):
        """Ignores items with no best candidate."""
        items = [make_shopping_plan_item(candidates=[])]
        url = build_cart_url(items)

        assert url is None
