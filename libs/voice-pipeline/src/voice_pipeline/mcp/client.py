"""MCP Client implementation.

Allows connecting to MCP servers and calling their tools.
"""

import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, Union

from voice_pipeline.mcp.types import (
    MCPCapabilities,
    MCPError,
    MCPErrorCode,
    MCPPrompt,
    MCPResource,
    MCPResult,
    MCPTool,
    MCPToolCall,
    TransportType,
)


@dataclass
class MCPClientConfig:
    """Configuration for MCP client.

    Attributes:
        transport: Transport type to use.
        timeout: Request timeout in seconds.
        retry_attempts: Number of retry attempts.
        headers: Additional HTTP headers.
    """

    transport: TransportType = TransportType.HTTP
    """Transport type."""

    timeout: float = 30.0
    """Request timeout in seconds."""

    retry_attempts: int = 3
    """Number of retry attempts."""

    headers: dict[str, str] = field(default_factory=dict)
    """Additional HTTP headers."""

    client_info: dict[str, str] = field(
        default_factory=lambda: {
            "name": "voice-pipeline",
            "version": "0.1.0",
        }
    )
    """Client info for handshake."""


@dataclass
class MCPConnection:
    """Active connection to an MCP server.

    Tracks connection state and capabilities.

    Attributes:
        url: Server URL or command.
        transport: Transport type.
        capabilities: Server capabilities.
        is_connected: Connection status.
    """

    url: str
    """Server URL or command."""

    transport: TransportType
    """Transport type."""

    capabilities: MCPCapabilities = field(default_factory=MCPCapabilities)
    """Server capabilities."""

    is_connected: bool = False
    """Connection status."""

    server_info: dict[str, Any] = field(default_factory=dict)
    """Server information."""


class MCPClient:
    """Client for connecting to MCP servers.

    MCPClient enables voice-pipeline agents to use tools from
    any MCP-compliant server. Supports HTTP, stdio, and SSE transports.

    Example - HTTP transport:
        >>> async with MCPClient("http://localhost:8000/mcp") as client:
        ...     tools = await client.list_tools()
        ...     result = await client.call_tool("search", {"query": "AI"})

    Example - Stdio transport (subprocess):
        >>> async with MCPClient(
        ...     "python my_server.py",
        ...     transport=TransportType.STDIO,
        ... ) as client:
        ...     tools = await client.list_tools()

    Example - With VoiceAgent:
        >>> async with MCPClient(url) as client:
        ...     tools = await client.list_tools()
        ...     voice_tools = mcp_tools_to_voice_tools(client, tools)
        ...     agent = VoiceAgent(llm=llm, tools=voice_tools)

    Attributes:
        url: Server URL or command.
        config: Client configuration.
        connection: Active connection (when connected).
    """

    def __init__(
        self,
        url: str,
        transport: Optional[TransportType] = None,
        config: Optional[MCPClientConfig] = None,
    ):
        """Initialize MCP client.

        Args:
            url: Server URL or stdio command.
            transport: Transport type (auto-detected if None).
            config: Client configuration.
        """
        self.url = url
        self.config = config or MCPClientConfig()

        # Auto-detect transport
        if transport:
            self.config.transport = transport
        elif url.startswith(("http://", "https://")):
            self.config.transport = TransportType.HTTP
        else:
            self.config.transport = TransportType.STDIO

        self.connection: Optional[MCPConnection] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0

    async def __aenter__(self) -> "MCPClient":
        """Connect on context entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Disconnect on context exit."""
        await self.disconnect()

    async def connect(self) -> MCPConnection:
        """Connect to the MCP server.

        Performs handshake and capability negotiation.

        Returns:
            MCPConnection with server info.

        Raises:
            MCPError: If connection fails.
        """
        self.connection = MCPConnection(
            url=self.url,
            transport=self.config.transport,
        )

        try:
            if self.config.transport == TransportType.STDIO:
                await self._connect_stdio()
            else:
                await self._connect_http()

            # Initialize session
            response = await self._request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": MCPCapabilities().to_dict(),
                    "clientInfo": self.config.client_info,
                },
            )

            self.connection.capabilities = MCPCapabilities(
                tools="tools" in response.get("capabilities", {}),
                resources="resources" in response.get("capabilities", {}),
                prompts="prompts" in response.get("capabilities", {}),
            )
            self.connection.server_info = response.get("serverInfo", {})
            self.connection.is_connected = True

            # Send initialized notification
            await self._notify("notifications/initialized", {})

            return self.connection

        except Exception as e:
            raise MCPError(
                code=MCPErrorCode.CONNECTION_ERROR,
                message=f"Failed to connect: {e}",
            )

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._process:
            self._process.terminate()
            await self._process.wait()
            self._process = None

        if self.connection:
            self.connection.is_connected = False

    async def _connect_stdio(self) -> None:
        """Connect via stdio transport."""
        # Parse command
        parts = self.url.split()
        self._process = await asyncio.create_subprocess_exec(
            *parts,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _connect_http(self) -> None:
        """Connect via HTTP transport."""
        # HTTP is stateless, just verify server is reachable
        # Actual requests happen per-call
        pass

    async def _request(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Send a request to the server.

        Args:
            method: RPC method name.
            params: Method parameters.

        Returns:
            Response result.

        Raises:
            MCPError: If request fails.
        """
        self._request_id += 1

        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params:
            request["params"] = params

        if self.config.transport == TransportType.STDIO:
            return await self._request_stdio(request)
        else:
            return await self._request_http(request)

    async def _notify(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
    ) -> None:
        """Send a notification (no response expected).

        Args:
            method: Notification method.
            params: Parameters.
        """
        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params:
            notification["params"] = params

        if self.config.transport == TransportType.STDIO and self._process:
            data = json.dumps(notification) + "\n"
            self._process.stdin.write(data.encode())
            await self._process.stdin.drain()

    async def _request_stdio(self, request: dict) -> dict[str, Any]:
        """Send request via stdio."""
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise MCPError(
                code=MCPErrorCode.CONNECTION_ERROR,
                message="Not connected via stdio",
            )

        data = json.dumps(request) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

        line = await asyncio.wait_for(
            self._process.stdout.readline(),
            timeout=self.config.timeout,
        )

        response = json.loads(line.decode())
        if "error" in response:
            raise MCPError(
                code=MCPErrorCode.INTERNAL_ERROR,
                message=response["error"].get("message", "Unknown error"),
            )

        return response.get("result", {})

    async def _request_http(self, request: dict) -> dict[str, Any]:
        """Send request via HTTP."""
        try:
            import aiohttp
        except ImportError:
            # Fallback to urllib for basic HTTP
            import urllib.request
            import urllib.error

            data = json.dumps(request).encode()
            req = urllib.request.Request(
                self.url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    **self.config.headers,
                },
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                    response = json.loads(resp.read().decode())
            except urllib.error.URLError as e:
                raise MCPError(
                    code=MCPErrorCode.CONNECTION_ERROR,
                    message=str(e),
                )

            if "error" in response:
                raise MCPError(
                    code=MCPErrorCode.INTERNAL_ERROR,
                    message=response["error"].get("message", "Unknown error"),
                )

            return response.get("result", {})

        # Use aiohttp if available
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.url,
                json=request,
                headers={
                    "Content-Type": "application/json",
                    **self.config.headers,
                },
                timeout=aiohttp.ClientTimeout(total=self.config.timeout),
            ) as resp:
                response = await resp.json()

        if "error" in response:
            raise MCPError(
                code=MCPErrorCode.INTERNAL_ERROR,
                message=response["error"].get("message", "Unknown error"),
            )

        return response.get("result", {})

    # ==================== Tool Operations ====================

    async def list_tools(self) -> list[MCPTool]:
        """List available tools from the server.

        Returns:
            List of available MCPTool objects.

        Example:
            >>> tools = await client.list_tools()
            >>> for tool in tools:
            ...     print(f"{tool.name}: {tool.description}")
        """
        response = await self._request("tools/list")
        tools_data = response.get("tools", [])

        return [MCPTool.from_mcp_schema(t) for t in tools_data]

    async def call_tool(
        self,
        name: str,
        arguments: Optional[dict[str, Any]] = None,
    ) -> MCPResult:
        """Call a tool on the server.

        Args:
            name: Tool name.
            arguments: Tool arguments.

        Returns:
            MCPResult with tool output.

        Example:
            >>> result = await client.call_tool(
            ...     "search",
            ...     {"query": "AI news"},
            ... )
            >>> print(result.content)
        """
        call = MCPToolCall(name=name, arguments=arguments or {})

        response = await self._request("tools/call", call.to_mcp_request())

        # Parse response content
        content = response.get("content", [])
        if content and isinstance(content, list):
            # Extract text content
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            result_content = "\n".join(texts) if texts else str(content)
        else:
            result_content = str(response)

        return MCPResult(
            content=result_content,
            is_error=response.get("isError", False),
        )

    # ==================== Resource Operations ====================

    async def list_resources(self) -> list[MCPResource]:
        """List available resources.

        Returns:
            List of MCPResource objects.
        """
        response = await self._request("resources/list")
        resources_data = response.get("resources", [])

        return [
            MCPResource(
                uri=r.get("uri", ""),
                name=r.get("name", ""),
                description=r.get("description", ""),
                mime_type=r.get("mimeType", "text/plain"),
            )
            for r in resources_data
        ]

    async def read_resource(self, uri: str) -> str:
        """Read a resource.

        Args:
            uri: Resource URI.

        Returns:
            Resource content.
        """
        response = await self._request("resources/read", {"uri": uri})
        contents = response.get("contents", [])

        if contents:
            return contents[0].get("text", "")
        return ""

    # ==================== Prompt Operations ====================

    async def list_prompts(self) -> list[MCPPrompt]:
        """List available prompts.

        Returns:
            List of MCPPrompt objects.
        """
        response = await self._request("prompts/list")
        prompts_data = response.get("prompts", [])

        return [
            MCPPrompt(
                name=p.get("name", ""),
                description=p.get("description", ""),
                arguments=p.get("arguments", []),
            )
            for p in prompts_data
        ]

    async def get_prompt(
        self,
        name: str,
        arguments: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Get a prompt with arguments.

        Args:
            name: Prompt name.
            arguments: Prompt arguments.

        Returns:
            Prompt messages.
        """
        response = await self._request(
            "prompts/get",
            {
                "name": name,
                "arguments": arguments or {},
            },
        )
        return response

    # ==================== Utility Methods ====================

    def is_connected(self) -> bool:
        """Check if client is connected.

        Returns:
            True if connected.
        """
        return self.connection is not None and self.connection.is_connected

    def get_capabilities(self) -> MCPCapabilities:
        """Get server capabilities.

        Returns:
            Server capabilities.
        """
        if self.connection:
            return self.connection.capabilities
        return MCPCapabilities()

    def get_server_info(self) -> dict[str, Any]:
        """Get server information.

        Returns:
            Server info dict.
        """
        if self.connection:
            return self.connection.server_info
        return {}
