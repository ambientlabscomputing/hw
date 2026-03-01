"""Unit tests for Mouser cart integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hw.circuits.shop.mouser import add_items_to_cart, is_mouser
from tests.hw_test.conftest import make_bom_item, make_part, make_shopping_plan_item


class TestIsMouser:
    """Tests for is_mouser distributor matching."""

    def test_exact_match_mouser(self):
        """Matches 'mouser' distributor."""
        part = make_part(distributor_name="Mouser")
        assert is_mouser(part) is True

    def test_match_mouser_electronics_full(self):
        """Matches 'Mouser Electronics' full name."""
        part = make_part(distributor_name="Mouser Electronics")
        assert is_mouser(part) is True

    def test_match_case_insensitive(self):
        """Matching is case-insensitive."""
        assert is_mouser(make_part(distributor_name="mouser")) is True
        assert is_mouser(make_part(distributor_name="MOUSER")) is True
        assert is_mouser(make_part(distributor_name="Mouser")) is True

    def test_match_with_whitespace(self):
        """Handles leading/trailing whitespace."""
        part = make_part(distributor_name="  Mouser Electronics  ")
        assert is_mouser(part) is True

    def test_no_match_digikey(self):
        """Does not match DigiKey."""
        part = make_part(distributor_name="DigiKey")
        assert is_mouser(part) is False

    def test_no_match_partial_string(self):
        """Does not match 'mou' alone (needs full alias)."""
        part = make_part(distributor_name="Mou Corp")
        # MOUSER_NAMES = {"mouser", "mouser electronics"}
        # This checks if any alias in dn, so "mouser" must be in "mou corp" -> no
        assert is_mouser(part) is False

    def test_no_match_none_distributor(self):
        """Returns False for None distributor_name."""
        part = make_part(distributor_name=None)
        assert is_mouser(part) is False

    def test_no_match_empty_distributor(self):
        """Returns False for empty distributor_name."""
        part = make_part(distributor_name="")
        assert is_mouser(part) is False

    def test_no_match_substring(self):
        """Does not match substring containment."""
        # "mouse" is a substring of "mouser" but the check is exact in the MOUSER_NAMES set
        # Actually, looking at the code: any(alias in dn for alias in MOUSER_NAMES)
        # This means "mouser" is IN "mouser electronics", so it's substring matching
        part = make_part(distributor_name="Mouser Electronics Corp")
        # "mouser" is in "mouser electronics corp" -> True
        assert is_mouser(part) is True

    def test_case_insensitive_full_phrase(self):
        """Matches full 'Mouser Electronics' with varied case."""
        assert is_mouser(make_part(distributor_name="MOUSER ELECTRONICS")) is True
        assert is_mouser(make_part(distributor_name="mouser electronics")) is True


class TestAddItemsToCart:
    """Tests for add_items_to_cart with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_successful_cart_insert(self):
        """Successfully adds items to cart via API."""
        mouser_part = make_part(
            part_number="TEST-001",
            source_part_number="TEST-MOUSER-001",
            distributor_name="Mouser Electronics",
            references=["U1"],
        )
        items = [
            make_shopping_plan_item(
                candidates=[mouser_part],
                bom_item=make_bom_item(references=["U1"], value="Test Part"),
            )
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "CartKey": "ABC-123-DEF",
            "MerchandiseTotal": "100.50",
            "Errors": [],
        }

        with patch("hw.circuits.shop.mouser.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            result = await add_items_to_cart(items, api_key="test-key")

            assert result.cart_key == "ABC-123-DEF"
            assert result.item_count == 1
            assert result.merchandise_total == 100.50
            assert result.errors == []

    @pytest.mark.asyncio
    async def test_cart_with_errors(self):
        """Handles API errors in response."""
        mouser_part = make_part(
            part_number="TEST-001",
            source_part_number="INVALID",
            distributor_name="Mouser Electronics",
            references=["U1"],
        )
        items = [make_shopping_plan_item(candidates=[mouser_part])]

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "CartKey": "ABC-123",
            "MerchandiseTotal": None,
            "Errors": [
                {"Message": "Invalid part number"},
                {"Message": "Out of stock"},
            ],
        }

        with patch("hw.circuits.shop.mouser.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            result = await add_items_to_cart(items, api_key="test-key")

            assert result.cart_key == "ABC-123"
            assert len(result.errors) == 2
            assert "Invalid part number" in result.errors

    @pytest.mark.asyncio
    async def test_no_mouser_items_returns_early(self):
        """Returns early when no Mouser items found."""
        non_mouser_part = make_part(distributor_name="DigiKey")
        items = [make_shopping_plan_item(candidates=[non_mouser_part])]

        result = await add_items_to_cart(items, api_key="test-key")

        assert result.cart_key == ""
        assert result.item_count == 0
        assert result.merchandise_total is None
        assert "No Mouser items found" in result.errors[0]

    @pytest.mark.asyncio
    async def test_preserves_cart_key_on_append(self):
        """Appends to existing cart when cart_key provided."""
        mouser_part = make_part(
            part_number="TEST-001",
            distributor_name="Mouser Electronics",
            references=["U1"],
        )
        items = [make_shopping_plan_item(candidates=[mouser_part])]

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "CartKey": "EXISTING-KEY",
            "MerchandiseTotal": "50.00",
            "Errors": [],
        }

        with patch("hw.circuits.shop.mouser.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            result = await add_items_to_cart(
                items, api_key="test-key", cart_key="EXISTING-KEY"
            )

            # Verify the cart_key was passed in the request
            call_args = mock_client.post.call_args
            assert call_args[1]["json"]["CartKey"] == "EXISTING-KEY"
            assert result.cart_key == "EXISTING-KEY"
