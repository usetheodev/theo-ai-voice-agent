"""MCP tool wrapper for integrating MCP servers with the voice agent."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from voice_pipeline.tools.base import FunctionTool, ToolResult, VoiceTool

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""

    name: str
    url: str
    transport: str = "http"  # http, stdio, sse
    auto_connect: bool = True


class MCPToolWrapper:
    """Wrapper to integrate MCP tools with the voice agent."""

    def __init__(self):
        """Initialize the MCP tool wrapper."""
        self._clients: dict[str, Any] = {}  # MCPClient instances
        self._tools: dict[str, VoiceTool] = {}  # tool_name -> VoiceTool
        self._tool_servers: dict[str, str] = {}  # tool_name -> server_name

    async def connect_server(self, config: MCPServerConfig) -> bool:
        """Connect to an MCP server.

        Args:
            config: Server configuration.

        Returns:
            True if connected successfully.
        """
        try:
            from voice_pipeline.mcp.client import MCPClient, MCPClientConfig, TransportType

            # Map transport string to enum
            transport_map = {
                "http": TransportType.HTTP,
                "stdio": TransportType.STDIO,
                "sse": TransportType.SSE,
            }
            transport = transport_map.get(config.transport, TransportType.HTTP)

            # Create client config
            client_config = MCPClientConfig(transport=transport)

            # Create and connect client
            client = MCPClient(url=config.url, config=client_config)
            await client.connect()

            self._clients[config.name] = client
            logger.info(f"Connected to MCP server: {config.name}")

            # Discover and register tools
            await self._discover_tools(config.name, client)

            return True

        except ImportError as e:
            logger.error(f"MCP client not available: {e}")
            return False
        except Exception as e:
            logger.error(f"Error connecting to MCP server {config.name}: {e}")
            return False

    async def disconnect_server(self, server_name: str) -> None:
        """Disconnect from an MCP server.

        Args:
            server_name: Name of the server to disconnect.
        """
        if server_name in self._clients:
            try:
                await self._clients[server_name].disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting from {server_name}: {e}")
            finally:
                del self._clients[server_name]

                # Remove tools from this server
                tools_to_remove = [
                    name
                    for name, srv in self._tool_servers.items()
                    if srv == server_name
                ]
                for tool_name in tools_to_remove:
                    del self._tools[tool_name]
                    del self._tool_servers[tool_name]

    async def _discover_tools(self, server_name: str, client: Any) -> None:
        """Discover and register tools from an MCP server.

        Args:
            server_name: Name of the server.
            client: MCPClient instance.
        """
        try:
            tools = await client.list_tools()

            for tool_info in tools:
                # Create a unique tool name
                tool_name = f"{server_name}/{tool_info.name}"

                # Create wrapper function that calls the MCP tool
                # Use closure to capture client and tool_info.name
                def make_tool_func(cli, tname):
                    async def call_mcp_tool(**kwargs) -> ToolResult:
                        try:
                            result = await cli.call_tool(tname, kwargs)
                            return ToolResult(success=True, output=result)
                        except Exception as e:
                            return ToolResult(success=False, output=None, error=str(e))
                    return call_mcp_tool

                tool_func = make_tool_func(client, tool_info.name)

                # Create FunctionTool wrapper
                tool = FunctionTool.from_function(
                    func=tool_func,
                    name=tool_name,
                    description=tool_info.description or f"MCP tool: {tool_info.name}",
                )

                self._tools[tool_name] = tool
                self._tool_servers[tool_name] = server_name
                logger.info(f"Registered MCP tool: {tool_name}")

        except Exception as e:
            logger.error(f"Error discovering tools from {server_name}: {e}")

    def get_tools(self) -> list[VoiceTool]:
        """Get all registered MCP tools.

        Returns:
            List of VoiceTool instances.
        """
        return list(self._tools.values())

    def get_tool(self, name: str) -> Optional[VoiceTool]:
        """Get a specific tool by name.

        Args:
            name: Tool name.

        Returns:
            VoiceTool instance or None.
        """
        return self._tools.get(name)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Call an MCP tool.

        Args:
            name: Tool name.
            arguments: Tool arguments.

        Returns:
            Tool result.
        """
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(success=False, output=None, error=f"Tool not found: {name}")

        try:
            return await tool.execute(**arguments)
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))

    def list_servers(self) -> list[str]:
        """List connected server names.

        Returns:
            List of server names.
        """
        return list(self._clients.keys())

    def list_server_tools(self, server_name: str) -> list[str]:
        """List tools from a specific server.

        Args:
            server_name: Server name.

        Returns:
            List of tool names.
        """
        return [name for name, srv in self._tool_servers.items() if srv == server_name]

    async def close(self) -> None:
        """Close all MCP connections."""
        for server_name in list(self._clients.keys()):
            await self.disconnect_server(server_name)
