"""Configuration management for AI features."""

import os
import tomllib
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field


class McpServerConfig(BaseModel):
    """Configuration for an MCP server."""

    command: str = Field(description="Command to launch the MCP server")
    args: list[str] = Field(
        default_factory=list, description="Arguments for the server command"
    )
    env: dict[str, str] = Field(
        default_factory=dict, description="Environment variables for the server"
    )


class AiConfig(BaseModel):
    """Configuration for AI features."""

    anthropic_api_key: str = Field(description="Anthropic API key for Claude")
    mcp_servers: dict[str, McpServerConfig] = Field(
        default_factory=dict, description="MCP servers to launch"
    )


def get_config_dir() -> Path:
    """Get the configuration directory path."""
    config_dir = Path.home() / ".hw"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_file() -> Path:
    """Get the configuration file path."""
    return get_config_dir() / "config.toml"


def load_config() -> AiConfig:
    """
    Load AI configuration from environment variable or config file.

    Precedence order:
    1. ANTHROPIC_API_KEY environment variable
    2. ~/.hw/config.toml file
    3. Error if neither is present

    Returns:
        AiConfig with loaded configuration

    Raises:
        ValueError: If no API key is found
        FileNotFoundError: If config file is missing and env var is not set
    """
    # Try environment variable first
    api_key = os.getenv("ANTHROPIC_API_KEY")
    mcp_servers: dict[str, McpServerConfig] = {}

    config_file = get_config_file()

    # Try loading from config file
    if config_file.exists():
        try:
            with open(config_file, "rb") as f:
                config_data = tomllib.load(f)

            # Get API key from file if not in env
            if not api_key:
                api_key = config_data.get("ai", {}).get("anthropic_api_key")

            # Load MCP server configurations
            mcp_config = config_data.get("ai", {}).get("mcp_servers", {})
            for server_name, server_data in mcp_config.items():
                mcp_servers[server_name] = McpServerConfig(**server_data)

            logger.debug(f"Loaded config from {config_file}")
        except Exception as e:
            logger.warning(f"Failed to load config file: {e}")

    # Validate that we have an API key
    if not api_key:
        raise ValueError(
            "No Anthropic API key found. Set ANTHROPIC_API_KEY environment variable "
            f"or add it to {config_file} under [ai] section."
        )

    return AiConfig(anthropic_api_key=api_key, mcp_servers=mcp_servers)


def get_default_mcp_servers() -> dict[str, McpServerConfig]:
    """
    Get default MCP server configurations.

    Returns:
        Dictionary of default MCP servers (Playwright browser via npx)
    """
    return {
        "browser": McpServerConfig(
            command="npx",
            args=["@playwright/mcp@latest", "--headless"],
            env={},
        ),
    }


def create_default_config() -> None:
    """Create a default configuration file with example settings."""
    config_file = get_config_file()

    if config_file.exists():
        logger.warning(f"Config file already exists at {config_file}")
        return

    default_content = """# hw CLI AI Configuration

[ai]
# Anthropic API key for Claude (can also be set via ANTHROPIC_API_KEY env var)
anthropic_api_key = "sk-ant-..."

# Playwright browser MCP for JLCPCB parts lookup
# Run 'hw init' to pre-install Playwright Chromium

[ai.mcp_servers.browser]
command = "npx"
args = ["@playwright/mcp@latest", "--headless"]
"""

    config_file.write_text(default_content)
    logger.info(f"Created default config file at {config_file}")
