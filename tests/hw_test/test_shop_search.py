"""Unit tests for the OEM Secrets search adapter and _parse_part logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hw.circuits.models.part import Part, PriceBreak
from hw.circuits.shop.search import OemSecretsAPIAdapter, PartSearchQuery, _parse_part

# ---------------------------------------------------------------------------
# Fixtures — raw API response items
# ---------------------------------------------------------------------------

FULL_ITEM = {
    "sku": "123-LM358DR",
    "part_number": "LM358DR",
    "source_part_number": "296-1395-5-ND",
    "manufacturer": "Texas Instruments",
    "description": "Op Amp Dual Low Power 8-SOIC",
    "quantity_in_stock": 15000,
    "life_cycle": "Active",
    "buy_now_url": "https://www.digikey.com/products/en?keywords=LM358DR",
    "datasheet_url": "https://www.ti.com/lit/ds/symlink/lm358.pdf",
    "prices": {
        "USD": [
            {"unit_break": 1, "unit_price": "0.4700"},
            {"unit_break": 10, "unit_price": "0.3500"},
            {"unit_break": 100, "unit_price": "0.2800"},
        ]
    },
    "distributor": {
        "distributor_name": "Digi-Key Electronics",
        "distributor_common_name": "DigiKey",
        "distributor_region": "Americas",
    },
    "compliance": {"rohs": True, "pb_status": "No"},
}

# Items 50+ in real responses return prices as an empty string
NO_PRICE_ITEM = {
    "sku": "UNAVAIL-R10K",
    "part_number": "RK73H2ATTD1002F",
    "source_part_number": "RK73H2ATTD1002F",
    "manufacturer": "KOA Speer",
    "description": "RES 10K OHM 1% 0.25W 0805",
    "quantity_in_stock": 0,
    "life_cycle": "",
    "buy_now_url": "",
    "datasheet_url": "",
    "prices": "",  # <-- the actual bug trigger
    "distributor": {
        "distributor_name": "Some Broker",
        "distributor_common_name": "Some Broker",
        "distributor_region": "Global",
    },
    "compliance": {"rohs": False, "pb_status": "Yes"},
}

NULL_FIELDS_ITEM = {
    "sku": "NULL-ITEM",
    "part_number": "X_PART",
    "source_part_number": None,
    "manufacturer": None,
    "description": "",
    "quantity_in_stock": None,
    "life_cycle": None,
    "buy_now_url": None,
    "datasheet_url": None,
    "prices": None,  # null from API
    "distributor": None,  # null distributor
    "compliance": None,
}

NONE_CURRENCY_ITEM = {
    "sku": "NOCUR-ITEM",
    "part_number": "NOPART",
    "source_part_number": "NP-001",
    "manufacturer": "ACME",
    "description": "Unknown",
    "quantity_in_stock": 5,
    "life_cycle": "Active",
    "buy_now_url": "https://example.com",
    "datasheet_url": "",
    "prices": {
        "None": [{"unit_break": 0, "unit_price": "0.0000"}],
    },
    "distributor": {
        "distributor_name": "Avnet Silica",
        "distributor_common_name": "Avnet Silica",
    },
    "compliance": {},
}


# ---------------------------------------------------------------------------
# _parse_part — happy path
# ---------------------------------------------------------------------------


class TestParsePartHappyPath:
    def test_returns_part_instance(self):
        part = _parse_part(FULL_ITEM)
        assert isinstance(part, Part)

    def test_part_number(self):
        assert _parse_part(FULL_ITEM).part_number == "LM358DR"

    def test_source_part_number(self):
        assert _parse_part(FULL_ITEM).source_part_number == "296-1395-5-ND"

    def test_distributor_name_prefers_common(self):
        assert _parse_part(FULL_ITEM).distributor_name == "DigiKey"

    def test_quantity_in_stock(self):
        assert _parse_part(FULL_ITEM).quantity_in_stock == 15000

    def test_lifecycle(self):
        assert _parse_part(FULL_ITEM).lifecycle == "Active"

    def test_buy_now_url(self):
        assert "digikey" in _parse_part(FULL_ITEM).buy_now_url

    def test_datasheet_url(self):
        assert "ti.com" in _parse_part(FULL_ITEM).datasheet_url

    def test_currency_is_usd(self):
        assert _parse_part(FULL_ITEM).currency == "USD"


# ---------------------------------------------------------------------------
# _parse_part — price breaks
# ---------------------------------------------------------------------------


class TestParsePartPriceBreaks:
    def test_price_breaks_count(self):
        part = _parse_part(FULL_ITEM)
        assert len(part.price_breaks) == 3

    def test_price_breaks_are_pricebreak_objects(self):
        part = _parse_part(FULL_ITEM)
        assert all(isinstance(pb, PriceBreak) for pb in part.price_breaks)

    def test_first_price_break_qty(self):
        part = _parse_part(FULL_ITEM)
        assert part.price_breaks[0].qty == 1

    def test_first_price_break_price(self):
        part = _parse_part(FULL_ITEM)
        assert part.price_breaks[0].unit_price == 0.47

    def test_unit_price_equals_first_break(self):
        part = _parse_part(FULL_ITEM)
        assert part.unit_price == part.price_breaks[0].unit_price

    def test_price_breaks_ascending_qty(self):
        part = _parse_part(FULL_ITEM)
        qtys = [pb.qty for pb in part.price_breaks]
        assert qtys == sorted(qtys)


# ---------------------------------------------------------------------------
# _parse_part — defensive: prices = "" (the original bug)
# ---------------------------------------------------------------------------


class TestParsePartEmptyPrices:
    def test_no_crash_when_prices_is_empty_string(self):
        """Must not raise AttributeError: 'str' object has no attribute 'get'."""
        part = _parse_part(NO_PRICE_ITEM)
        assert isinstance(part, Part)

    def test_price_breaks_empty(self):
        part = _parse_part(NO_PRICE_ITEM)
        assert part.price_breaks == []

    def test_unit_price_is_none(self):
        part = _parse_part(NO_PRICE_ITEM)
        assert part.unit_price is None

    def test_part_number_still_parsed(self):
        part = _parse_part(NO_PRICE_ITEM)
        assert part.part_number == "RK73H2ATTD1002F"


# ---------------------------------------------------------------------------
# _parse_part — defensive: null / missing fields
# ---------------------------------------------------------------------------


class TestParsePartNullFields:
    def test_no_crash_when_prices_is_none(self):
        part = _parse_part(NULL_FIELDS_ITEM)
        assert isinstance(part, Part)

    def test_no_crash_when_distributor_is_none(self):
        part = _parse_part(NULL_FIELDS_ITEM)
        assert part.distributor_name is None

    def test_no_crash_when_quantity_is_none(self):
        part = _parse_part(NULL_FIELDS_ITEM)
        assert part.quantity_in_stock is None

    def test_no_crash_when_source_part_number_is_none(self):
        part = _parse_part(NULL_FIELDS_ITEM)
        assert part.source_part_number is None


# ---------------------------------------------------------------------------
# _parse_part — prices keyed as "None" (another real API quirk)
# ---------------------------------------------------------------------------


class TestParsePartNoneCurrencyKey:
    def test_no_crash_when_no_usd_key(self):
        """prices dict exists but only has 'None' key — no USD prices."""
        part = _parse_part(NONE_CURRENCY_ITEM)
        assert isinstance(part, Part)

    def test_price_breaks_empty_when_no_usd(self):
        part = _parse_part(NONE_CURRENCY_ITEM)
        assert part.price_breaks == []

    def test_unit_price_none_when_no_usd(self):
        part = _parse_part(NONE_CURRENCY_ITEM)
        assert part.unit_price is None

    def test_other_fields_still_parsed(self):
        part = _parse_part(NONE_CURRENCY_ITEM)
        assert part.distributor_name == "Avnet Silica"
        assert part.quantity_in_stock == 5


# ---------------------------------------------------------------------------
# OemSecretsAPIAdapter — HTTP tests with mocking
# ---------------------------------------------------------------------------


class TestOemSecretsAPIAdapterSearch:
    """Tests for OemSecretsAPIAdapter.search() with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_search_returns_parts(self):
        """Successfully searches and returns parts."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "stock": [FULL_ITEM, NO_PRICE_ITEM],
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            adapter = OemSecretsAPIAdapter()
            results = await adapter.search(PartSearchQuery(query="LM358"))

            assert len(results) == 2
            assert results[0].part_number == "LM358DR"
            assert results[1].part_number == "RK73H2ATTD1002F"

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        """Handles empty search results."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"stock": []}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            adapter = OemSecretsAPIAdapter()
            results = await adapter.search(PartSearchQuery(query="NOTFOUND"))

            assert results == []

    @pytest.mark.asyncio
    async def test_search_constructs_correct_url(self):
        """Verifies correct URL parameters are sent."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"stock": []}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            adapter = OemSecretsAPIAdapter()
            await adapter.search(PartSearchQuery(query="TEST-123"))

            # Verify the call was made with correct parameters
            call_args = mock_client.get.call_args
            assert call_args[0][0] == "https://oemsecretsapi.com/partsearch"
            params = call_args[1]["params"]
            assert params["searchTerm"] == "TEST-123"
            assert params["currency"] == "USD"
            assert "apiKey" in params

    @pytest.mark.asyncio
    async def test_search_propagates_http_errors(self):
        """HTTP errors are propagated."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(side_effect=RuntimeError("Connection failed"))
            mock_client_class.return_value = mock_client

            adapter = OemSecretsAPIAdapter()

            with pytest.raises(RuntimeError, match="Connection failed"):
                await adapter.search(PartSearchQuery(query="TEST"))

    @pytest.mark.asyncio
    async def test_search_respects_timeout(self):
        """Adapter has 15s timeout configured."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"stock": []}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            adapter = OemSecretsAPIAdapter()
            await adapter.search(PartSearchQuery(query="TEST"))

            # Verify timeout was set to 15
            call_args = mock_client_class.call_args
            assert call_args[1]["timeout"] == 15
