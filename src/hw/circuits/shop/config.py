"""Configuration management for the shop/search features."""

import os
import tomllib
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field


class SearchConfig(BaseModel):
    """Configuration for part-search features."""

    oem_secrets_api_key: str = Field(description="OEM Secrets API key for part search")
    mouser_api_key: str | None = Field(
        None,
        description="Mouser Electronics API key (optional; needed for cart automation)",
    )


def _get_config_file() -> Path:
    return Path.home() / ".hw" / "config.toml"


def load_search_config() -> SearchConfig:
    """Load search configuration.

    Precedence order:
    1. ``OEM_SECRETS_API_KEY`` environment variable
    2. ``~/.hw/config.toml`` → ``[search].oem_secrets_api_key``

    Raises:
        ValueError: If no API key is found by either mechanism.
    """
    api_key = os.getenv("OEM_SECRETS_API_KEY")
    mouser_api_key = os.getenv("MOUSER_API_KEY")

    config_file = _get_config_file()
    if config_file.exists():
        try:
            with open(config_file, "rb") as f:
                config_data = tomllib.load(f)
            search_section = config_data.get("search", {})
            if not api_key:
                api_key = search_section.get("oem_secrets_api_key")
            if not mouser_api_key:
                mouser_api_key = search_section.get("mouser_api_key")
            logger.debug(f"Loaded search config from {config_file}")
        except Exception as e:
            logger.warning(f"Failed to load config file: {e}")

    if not api_key:
        raise ValueError(
            "No OEM Secrets API key found. Set the OEM_SECRETS_API_KEY environment "
            f"variable or add it to {config_file} under the [search] section:\n\n"
            "    [search]\n"
            '    oem_secrets_api_key = "your-key-here"\n'
        )

    return SearchConfig(oem_secrets_api_key=api_key, mouser_api_key=mouser_api_key)
