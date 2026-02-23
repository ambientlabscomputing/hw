"""MCP server management and tool routing."""

from contextlib import AsyncExitStack
from typing import Any

import click
from loguru import logger
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from hw.ai.config import McpServerConfig


class McpManager:
    """Manages multiple MCP server connections and routes tool calls."""

    def __init__(self, server_configs: dict[str, McpServerConfig]):
        """
        Initialize MCP manager with server configurations.

        Args:
            server_configs: Dictionary mapping server names to their configurations
        """
        self.server_configs = server_configs
        self.sessions: dict[str, ClientSession] = {}
        self.tool_to_server: dict[str, str] = {}
        self._exit_stack: AsyncExitStack | None = None

    async def __aenter__(self) -> "McpManager":
        """Start all MCP servers and collect their tools."""
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        for server_name, config in self.server_configs.items():
            try:
                logger.info(f"Starting MCP server: {server_name}")

                # Create server parameters
                server_params = StdioServerParameters(
                    command=config.command,
                    args=config.args,
                    env=config.env if config.env else None,
                )

                # Connect to server
                stdio_transport = await self._exit_stack.enter_async_context(
                    stdio_client(server_params)
                )
                read_stream, write_stream = stdio_transport

                # Create session
                session = await self._exit_stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )

                # Initialize session
                await session.initialize()

                self.sessions[server_name] = session

                # List tools from this server
                tools_response = await session.list_tools()
                logger.info(
                    f"Server {server_name} provides {len(tools_response.tools)} tools"
                )

                # Map tools to their server
                for tool in tools_response.tools:
                    self.tool_to_server[tool.name] = server_name
                    logger.debug(f"Registered tool: {tool.name} from {server_name}")

            except BaseException as e:
                # Re-raise hard signals; swallow everything else (including
                # BaseExceptionGroup / ExceptionGroup from anyio TaskGroups)
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                import traceback

                logger.error(f"Failed to start MCP server {server_name}: {e}")
                logger.debug(f"Full traceback: {traceback.format_exc()}")
                click.echo(
                    f"\n  ⚠️  MCP server '{server_name}' "
                    f"failed to start: {e}"
                    "\n  Run 'hw init' to install and "
                    "pre-cache required dependencies.\n",
                    err=True,
                )
                # Continue with other servers

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up all MCP server connections."""
        if self._exit_stack:
            await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)
        return False

    async def get_tools_for_anthropic(self) -> list[dict[str, Any]]:
        """
        Get all available tools in Anthropic format.

        Returns:
            List of tool definitions formatted for Anthropic API
        """
        anthropic_tools = []

        for server_name, session in self.sessions.items():
            tools_response = await session.list_tools()

            for tool in tools_response.tools:
                # Convert MCP tool definition to Anthropic format
                anthropic_tool = {
                    "name": tool.name,
                    "description": tool.description or "",
                }

                # Convert JSON schema if present
                if tool.inputSchema:
                    anthropic_tool["input_schema"] = tool.inputSchema

                anthropic_tools.append(anthropic_tool)

        return anthropic_tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """
        Route a tool call to the appropriate MCP server.

        Args:
            tool_name: Name of the tool to call
            arguments: Arguments to pass to the tool

        Returns:
            Tool result as a string

        Raises:
            ValueError: If tool is not found in any server
        """
        # Find which server provides this tool
        server_name = self.tool_to_server.get(tool_name)
        if not server_name:
            raise ValueError(f"Tool {tool_name} not found in any MCP server")

        session = self.sessions.get(server_name)
        if not session:
            raise ValueError(f"Server {server_name} is not connected")

        logger.debug(f"Calling tool {tool_name} on server {server_name}")

        try:
            # Call the tool
            result = await session.call_tool(tool_name, arguments)

            # Format result as string
            if result.content:
                # Handle multiple content items
                content_parts = []
                for item in result.content:
                    if hasattr(item, "text"):
                        content_parts.append(item.text)
                    else:
                        content_parts.append(str(item))
                return "\n".join(content_parts)

            return ""

        except Exception as e:
            error_msg = f"Error calling tool {tool_name}: {e}"
            logger.error(error_msg)
            return error_msg
