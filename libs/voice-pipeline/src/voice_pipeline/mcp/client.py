"""MCP Client implementation.

Allows connecting to MCP servers and calling their tools.
"""

import asyncio
import json
import logging
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, Union

try:
    import aiohttp
except ImportError:
    aiohttp = None

from voice_pipeline.mcp.types import (
    MCPCapabilities,
    MCPError,
    MCPErrorCode,
    MCPPrompt,
    MCPResource,
    MCPResult,
    MCPTool,
    MCPToolCall,
    SamplingRequest,
    SamplingResponse,
    TransportType,
)

# Type for sampling handler callback
SamplingHandler = Any  # Callable[[SamplingRequest], Awaitable[SamplingResponse]]

logger = logging.getLogger(__name__)


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

    sampling_handler: Optional[SamplingHandler] = None
    """Handler for sampling/createMessage requests from server.

    If provided, the client will declare sampling capability and
    process sampling requests. The handler should be an async function:

        async def my_handler(request: SamplingRequest) -> SamplingResponse:
            # Use your LLM to generate response
            ...
    """


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

        # SSE transport state
        self._sse_session: Optional[Any] = None  # aiohttp.ClientSession
        self._sse_response: Optional[Any] = None  # aiohttp.ClientResponse
        self._sse_endpoint: Optional[str] = None  # POST endpoint for requests
        self._sse_reader_task: Optional[asyncio.Task] = None
        self._pending_requests: dict[int, asyncio.Future] = {}

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
            elif self.config.transport == TransportType.SSE:
                await self._connect_sse()
            else:
                await self._connect_http()

            # Build client capabilities
            client_caps = MCPCapabilities(
                sampling=self.config.sampling_handler is not None,
            )

            # Initialize session
            response = await self._request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": client_caps.to_dict(),
                    "clientInfo": self.config.client_info,
                },
            )

            self.connection.capabilities = MCPCapabilities(
                tools="tools" in response.get("capabilities", {}),
                resources="resources" in response.get("capabilities", {}),
                prompts="prompts" in response.get("capabilities", {}),
                sampling="sampling" in response.get("capabilities", {}),
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

        # Clean up SSE resources
        await self._cleanup_sse()

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

    async def _connect_sse(self) -> None:
        """Connect via SSE (Server-Sent Events) transport.

        Establishes SSE connection to server and starts background
        reader task to receive responses.

        The MCP SSE transport works as follows:
        1. Client opens SSE connection to server's /sse endpoint
        2. Server sends 'endpoint' event with URL for POST requests
        3. Client sends JSON-RPC requests via POST to that endpoint
        4. Server sends responses via SSE 'message' events
        """
        if aiohttp is None:
            raise ImportError(
                "aiohttp is required for SSE transport. "
                "Install with: pip install aiohttp"
            )

        # Create session
        self._sse_session = aiohttp.ClientSession()

        # Determine SSE endpoint URL
        sse_url = self.url
        if not sse_url.endswith("/sse"):
            sse_url = sse_url.rstrip("/") + "/sse"

        try:
            # Open SSE connection
            self._sse_response = await self._sse_session.get(
                sse_url,
                headers={
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-cache",
                    **self.config.headers,
                },
                timeout=aiohttp.ClientTimeout(
                    total=None,  # No total timeout for SSE
                    connect=self.config.timeout,
                ),
            )

            if self._sse_response.status != 200:
                raise MCPError(
                    code=MCPErrorCode.CONNECTION_ERROR,
                    message=f"SSE connection failed: HTTP {self._sse_response.status}",
                )

            # Wait for endpoint event
            self._sse_endpoint = await self._wait_for_endpoint()

            # Start background reader task
            self._sse_reader_task = asyncio.create_task(self._sse_reader_loop())

            logger.info("SSE connection established. Endpoint: %s", self._sse_endpoint)

        except Exception as e:
            await self._cleanup_sse()
            raise MCPError(
                code=MCPErrorCode.CONNECTION_ERROR,
                message=f"SSE connection failed: {e}",
            )

    async def _wait_for_endpoint(self) -> str:
        """Wait for and parse the endpoint event from SSE stream.

        Returns:
            The endpoint URL for sending requests.

        Raises:
            MCPError: If endpoint event not received or invalid.
        """
        if self._sse_response is None:
            raise MCPError(
                code=MCPErrorCode.CONNECTION_ERROR,
                message="SSE response not initialized",
            )

        event_type = None
        event_data = ""

        async for line_bytes in self._sse_response.content:
            line = line_bytes.decode("utf-8").rstrip("\r\n")

            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                event_data = line[5:].strip()
            elif line == "":
                # End of event
                if event_type == "endpoint":
                    # Parse endpoint URL
                    endpoint = event_data
                    # If relative URL, make absolute
                    if endpoint.startswith("/"):
                        from urllib.parse import urljoin
                        endpoint = urljoin(self.url, endpoint)
                    return endpoint
                # Reset for next event
                event_type = None
                event_data = ""

        raise MCPError(
            code=MCPErrorCode.CONNECTION_ERROR,
            message="SSE stream closed before endpoint event received",
        )

    async def _sse_reader_loop(self) -> None:
        """Background task that reads SSE events and dispatches responses."""
        if self._sse_response is None:
            return

        event_type = None
        event_data = ""

        try:
            async for line_bytes in self._sse_response.content:
                line = line_bytes.decode("utf-8").rstrip("\r\n")

                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    event_data = line[5:].strip()
                elif line == "":
                    # End of event - process it
                    if event_type == "message" and event_data:
                        try:
                            response = json.loads(event_data)
                            request_id = response.get("id")
                            if request_id in self._pending_requests:
                                future = self._pending_requests.pop(request_id)
                                if not future.done():
                                    future.set_result(response)
                        except json.JSONDecodeError:
                            logger.warning("Invalid JSON in SSE message: %s", event_data)

                    # Reset for next event
                    event_type = None
                    event_data = ""

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("SSE reader error: %s", e)
            # Cancel all pending requests
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(MCPError(
                        code=MCPErrorCode.CONNECTION_ERROR,
                        message=f"SSE connection lost: {e}",
                    ))
            self._pending_requests.clear()

    async def _cleanup_sse(self) -> None:
        """Clean up SSE connection resources."""
        if self._sse_reader_task:
            self._sse_reader_task.cancel()
            try:
                await self._sse_reader_task
            except asyncio.CancelledError:
                pass
            self._sse_reader_task = None

        if self._sse_response:
            self._sse_response.close()
            self._sse_response = None

        if self._sse_session:
            await self._sse_session.close()
            self._sse_session = None

        self._sse_endpoint = None
        self._pending_requests.clear()

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
        elif self.config.transport == TransportType.SSE:
            return await self._request_sse(request)
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
        elif self.config.transport == TransportType.SSE and self._sse_session and self._sse_endpoint:
            # Send notification via POST (no response expected)
            try:
                async with self._sse_session.post(
                    self._sse_endpoint,
                    json=notification,
                    headers={
                        "Content-Type": "application/json",
                        **self.config.headers,
                    },
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout),
                ):
                    pass
            except Exception as e:
                logger.warning("Failed to send SSE notification: %s", e)

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

    async def _request_sse(self, request: dict) -> dict[str, Any]:
        """Send request via SSE transport.

        Sends POST request to the endpoint URL and waits for response
        via SSE event stream.

        Args:
            request: JSON-RPC request dict.

        Returns:
            Response result.

        Raises:
            MCPError: If request fails or times out.
        """
        if self._sse_session is None or self._sse_endpoint is None:
            raise MCPError(
                code=MCPErrorCode.CONNECTION_ERROR,
                message="SSE not connected",
            )

        request_id = request.get("id")

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            # Send POST request to endpoint
            async with self._sse_session.post(
                self._sse_endpoint,
                json=request,
                headers={
                    "Content-Type": "application/json",
                    **self.config.headers,
                },
                timeout=aiohttp.ClientTimeout(total=self.config.timeout),
            ) as resp:
                if resp.status != 200 and resp.status != 202:
                    raise MCPError(
                        code=MCPErrorCode.CONNECTION_ERROR,
                        message=f"SSE request failed: HTTP {resp.status}",
                    )

            # Wait for response via SSE
            response = await asyncio.wait_for(
                future,
                timeout=self.config.timeout,
            )

            if "error" in response:
                raise MCPError(
                    code=MCPErrorCode.INTERNAL_ERROR,
                    message=response["error"].get("message", "Unknown error"),
                )

            return response.get("result", {})

        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise MCPError(
                code=MCPErrorCode.TIMEOUT,
                message="SSE request timed out",
            )
        except Exception as e:
            self._pending_requests.pop(request_id, None)
            if isinstance(e, MCPError):
                raise
            raise MCPError(
                code=MCPErrorCode.CONNECTION_ERROR,
                message=f"SSE request failed: {e}",
            )

    def _sync_request_http(self, request: dict) -> dict[str, Any]:
        """Send request via HTTP using urllib (sync, thread-safe fallback).

        Args:
            request: JSON-RPC request dict.

        Returns:
            Response result.

        Raises:
            MCPError: If request fails.
        """
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

    async def _request_http(self, request: dict) -> dict[str, Any]:
        """Send request via HTTP.

        Uses aiohttp if available (fully async); otherwise falls back
        to urllib in a worker thread via ``asyncio.to_thread`` so the
        event loop is never blocked.
        """
        if aiohttp is None:
            # Fallback: run blocking urllib in a thread
            return await asyncio.to_thread(self._sync_request_http, request)

        # Async path with aiohttp
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

    # ==================== Retry Logic ====================

    _RETRYABLE_CODES = frozenset({
        MCPErrorCode.CONNECTION_ERROR,
        MCPErrorCode.TIMEOUT,
    })

    async def _reconnect(self) -> None:
        """Attempt to reconnect to the MCP server.

        Disconnects (if needed) and reconnects with a fresh session.
        Used internally when connection errors are detected.

        Raises:
            MCPError: If reconnection fails.
        """
        logger.info("MCP client attempting reconnection to %s", self.url)
        try:
            await self.disconnect()
        except Exception:
            pass  # Ignore disconnect errors

        await self.connect()
        logger.info("MCP client reconnected successfully")

    async def _request_with_retry(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Send a request with exponential-backoff retry and auto-reconnect.

        On CONNECTION_ERROR or TIMEOUT, attempts to reconnect before
        retrying. Logic errors propagate immediately.

        Uses ``config.retry_attempts`` (default 3).

        Args:
            method: RPC method name.
            params: Method parameters.

        Returns:
            Response result.

        Raises:
            MCPError: After all retries exhausted, or on non-retryable error.
        """
        max_attempts = max(self.config.retry_attempts, 1)
        last_error: Optional[MCPError] = None

        for attempt in range(max_attempts):
            try:
                return await self._request(method, params)
            except MCPError as e:
                last_error = e
                if e.code not in self._RETRYABLE_CODES:
                    raise

                # Mark connection as stale on connection errors
                if self.connection:
                    self.connection.is_connected = False

                if attempt < max_attempts - 1:
                    delay = (2 ** attempt) * 0.1  # 0.1s, 0.2s, 0.4s …
                    logger.warning(
                        "MCP request '%s' failed (attempt %d/%d): %s — reconnecting in %.1fs",
                        method, attempt + 1, max_attempts, e.message, delay,
                    )
                    await asyncio.sleep(delay)

                    # Attempt reconnection before next retry
                    try:
                        await self._reconnect()
                    except MCPError as reconnect_error:
                        logger.warning(
                            "MCP reconnection failed: %s — will retry",
                            reconnect_error.message,
                        )

        # All attempts exhausted
        raise last_error  # type: ignore[misc]

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
        response = await self._request_with_retry("tools/list")
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

        response = await self._request_with_retry("tools/call", call.to_mcp_request())

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
        response = await self._request_with_retry("resources/list")
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
        response = await self._request_with_retry("resources/read", {"uri": uri})
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
        response = await self._request_with_retry("prompts/list")
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
        response = await self._request_with_retry(
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
