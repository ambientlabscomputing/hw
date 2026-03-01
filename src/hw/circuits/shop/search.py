import asyncio
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from hw.circuits.models.part import Part, PriceBreak
from hw.circuits.shop.config import SearchConfig, load_search_config


class PartSearchQuery(BaseModel):
    query: str = Field(..., description="The search query string.")


class PartSearchPort(ABC):
    @abstractmethod
    async def search(self, query: PartSearchQuery) -> list[Part]:
        """Search for parts matching the query and return a list of results."""
        ...


class OemSecretsAPIAdapter(PartSearchPort):
    """Port adapter that queries the OEM Secrets aggregated distributor API.

    Docs: https://oemsecretsapi.com/documentation/
    """

    BASE_URL = "https://oemsecretsapi.com/partsearch"

    def __init__(self, config: SearchConfig | None = None) -> None:
        self._config = config or load_search_config()

    async def search(self, query: PartSearchQuery) -> list[Part]:
        """Search for parts and return normalized Part results.

        Retries up to 3 times on transient errors with exponential backoff.
        """
        import httpx

        params = {
            "apiKey": self._config.oem_secrets_api_key,
            "searchTerm": query.query,
            "currency": "USD",
        }

        # Retry logic: up to 3 attempts with exponential backoff (1s, 2s, 4s)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(self.BASE_URL, params=params)
                    resp.raise_for_status()
                data = resp.json()
                return [_parse_part(item) for item in data.get("stock", [])]
            except (httpx.HTTPError, asyncio.TimeoutError):
                if attempt == max_retries - 1:
                    # Last attempt failed, raise the exception
                    raise
                # Exponential backoff: 1s, 2s, 4s
                wait_time = 2**attempt
                await asyncio.sleep(wait_time)

        raise RuntimeError("Unreachable: retry loop exhausted without raising")


def _parse_part(item: dict) -> Part:
    """Map a single OEM Secrets stock entry to the normalized Part model."""
    distributor = item.get("distributor") or {}
    if not isinstance(distributor, dict):
        distributor = {}

    # prices may be "" (empty string) for items without pricing data
    prices_raw = item.get("prices")
    prices_usd: list[dict] = (
        prices_raw.get("USD", []) if isinstance(prices_raw, dict) else []
    )
    price_breaks = [
        PriceBreak(qty=int(pb["unit_break"]), unit_price=float(pb["unit_price"]))
        for pb in prices_usd
        if isinstance(pb, dict) and pb.get("unit_break") and pb.get("unit_price")
    ]
    unit_price = price_breaks[0].unit_price if price_breaks else None

    return Part(
        part_number=item.get("part_number", ""),
        source_part_number=item.get("source_part_number"),
        distributor_name=distributor.get("distributor_common_name")
        or distributor.get("distributor_name"),
        quantity_in_stock=item.get("quantity_in_stock"),
        unit_price=unit_price,
        price_breaks=price_breaks,
        buy_now_url=item.get("buy_now_url"),
        datasheet_url=item.get("datasheet_url"),
        lifecycle=item.get("life_cycle"),
        currency="USD",
        value=item.get("part_number", ""),
        footprint="",
    )
