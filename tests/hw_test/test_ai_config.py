"""Tests for AI configuration management."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from hw.ai.config import (
    AiConfig,
    McpServerConfig,
    get_config_dir,
    get_config_file,
    get_default_mcp_servers,
    load_config,
)


def test_mcp_server_config():
    """Test McpServerConfig model."""
    config = McpServerConfig(
        command="uvx",
        args=["mcp-server-fetch"],
        env={"KEY": "value"},
    )

    assert config.command == "uvx"
    assert config.args == ["mcp-server-fetch"]
    assert config.env == {"KEY": "value"}


def test_mcp_server_config_defaults():
    """Test McpServerConfig with default values."""
    config = McpServerConfig(command="test")

    assert config.command == "test"
    assert config.args == []
    assert config.env == {}


def test_ai_config():
    """Test AiConfig model."""
    server_config = McpServerConfig(command="test", args=["arg1"])
    config = AiConfig(
        anthropic_api_key="sk-ant-test123",
        mcp_servers={"test": server_config},
    )

    assert config.anthropic_api_key == "sk-ant-test123"
    assert "test" in config.mcp_servers
    assert config.mcp_servers["test"].command == "test"


def test_ai_config_defaults():
    """Test AiConfig with default values."""
    config = AiConfig(anthropic_api_key="test-key")

    assert config.anthropic_api_key == "test-key"
    assert config.mcp_servers == {}


def test_get_config_dir():
    """Test get_config_dir returns ~/.hw."""
    config_dir = get_config_dir()

    assert config_dir == Path.home() / ".hw"
    assert config_dir.exists()  # Should create if doesn't exist


def test_get_config_file():
    """Test get_config_file returns ~/.hw/config.toml."""
    config_file = get_config_file()

    assert config_file == Path.home() / ".hw" / "config.toml"


def test_get_default_mcp_servers():
    """Test default MCP server configurations."""
    servers = get_default_mcp_servers()

    assert "browser" in servers
    assert "web" not in servers
    assert "filesystem" not in servers

    assert servers["browser"].command == "npx"
    assert "@playwright/mcp@latest" in servers["browser"].args
    assert "--headless" in servers["browser"].args


def test_load_config_from_env(tmp_path):
    """Test loading config from environment variable (no config file)."""
    fake_config = tmp_path / "config.toml"
    # do NOT create the file – env var should be sufficient
    with patch("hw.ai.config.get_config_file", return_value=fake_config):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-env123"}):
            config = load_config()

            assert config.anthropic_api_key == "sk-ant-env123"
            assert config.mcp_servers == {}


def test_load_config_no_api_key():
    """Test loading config without API key raises error."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("hw.ai.config.get_config_file") as mock_config_file:
            # Make it look like file doesn't exist
            mock_config_file.return_value.exists.return_value = False

            with pytest.raises(ValueError, match="No Anthropic API key found"):
                load_config()


def test_load_config_from_file(tmp_path):
    """Test loading config from TOML file."""
    # Create a temporary config file
    config_content = """
[ai]
anthropic_api_key = "sk-ant-file123"

[ai.mcp_servers.web]
command = "uvx"
args = ["mcp-server-fetch"]

[ai.mcp_servers.custom]
command = "python"
args = ["-m", "my_server"]
env = {PATH = "/custom/path"}
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(config_content)

    with patch("hw.ai.config.get_config_file", return_value=config_file):
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()

            assert config.anthropic_api_key == "sk-ant-file123"
            assert len(config.mcp_servers) == 2
            assert "web" in config.mcp_servers
            assert "custom" in config.mcp_servers
            assert config.mcp_servers["custom"].command == "python"
            assert config.mcp_servers["custom"].args == ["-m", "my_server"]


def test_load_config_env_overrides_file(tmp_path):
    """Test that environment variable takes precedence over file."""
    # Create a temporary config file
    config_content = """
[ai]
anthropic_api_key = "sk-ant-file123"
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(config_content)

    with patch("hw.ai.config.get_config_file", return_value=config_file):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-env123"}):
            config = load_config()

            # Environment variable should take precedence
            assert config.anthropic_api_key == "sk-ant-env123"
