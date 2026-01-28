"""MCP Server implementation.

Allows exposing voice-pipeline tools as MCP servers.
"""

import asyncio
import inspect
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar, Union

from voice_pipeline.mcp.types import (
    MCPCapabilities,
    MCPError,
    MCPErrorCode,
    MCPPrompt,
    MCPResource,
    MCPResult,
    MCPTool,
    SamplingContent,
    SamplingMessage,
    SamplingRequest,
    SamplingResponse,
    ModelPreferences,
    ModelHint,
    TransportType,
)
from voice_pipeline.tools.base import VoiceTool

F = TypeVar("F", bound=Callable)


class RateLimiter:
    """Sliding window rate limiter for MCP requests.

    Tracks request timestamps per client and enforces rate limits
    using a sliding window algorithm.

    Attributes:
        max_requests: Maximum requests allowed in the window.
        window_seconds: Size of the sliding window in seconds.

    Example:
        >>> limiter = RateLimiter(max_requests=100, window_seconds=60)
        >>> if limiter.is_allowed("client-123"):
        ...     # Process request
        ...     pass
        ... else:
        ...     # Reject with 429
        ...     pass
    """

    def __init__(self, max_requests: int = 100, window_seconds: float = 60.0):
        """Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed per window.
            window_seconds: Window size in seconds.
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_id: str = "default") -> bool:
        """Check if a request is allowed and record it.

        Args:
            client_id: Client identifier (IP, session ID, etc.).

        Returns:
            True if request is allowed, False if rate limited.
        """
        now = time.monotonic()
        window_start = now - self.window_seconds

        # Get and clean old timestamps for this client
        timestamps = self._requests[client_id]
        # Remove timestamps outside the window
        self._requests[client_id] = [ts for ts in timestamps if ts > window_start]

        # Check if under limit
        if len(self._requests[client_id]) >= self.max_requests:
            return False

        # Record this request
        self._requests[client_id].append(now)
        return True

    def remaining(self, client_id: str = "default") -> int:
        """Get remaining requests for a client.

        Args:
            client_id: Client identifier.

        Returns:
            Number of remaining requests in current window.
        """
        now = time.monotonic()
        window_start = now - self.window_seconds

        timestamps = self._requests.get(client_id, [])
        current_count = sum(1 for ts in timestamps if ts > window_start)

        return max(0, self.max_requests - current_count)

    def reset_time(self, client_id: str = "default") -> float:
        """Get seconds until the oldest request expires.

        Args:
            client_id: Client identifier.

        Returns:
            Seconds until rate limit resets (0 if not limited).
        """
        now = time.monotonic()
        window_start = now - self.window_seconds

        timestamps = self._requests.get(client_id, [])
        valid_timestamps = [ts for ts in timestamps if ts > window_start]

        if len(valid_timestamps) < self.max_requests:
            return 0.0

        # Time until oldest request in window expires
        oldest = min(valid_timestamps)
        return max(0.0, oldest - window_start)


@dataclass
class MCPServerConfig:
    """Configuration for MCP server.

    Attributes:
        name: Server name.
        version: Server version.
        transport: Transport type.
        host: HTTP host.
        port: HTTP port.
        rate_limit_requests: Max requests per window (0 to disable).
        rate_limit_window: Window size in seconds.
    """

    name: str = "voice-pipeline-mcp"
    """Server name."""

    version: str = "0.1.0"
    """Server version."""

    transport: TransportType = TransportType.HTTP
    """Transport type."""

    host: str = "localhost"
    """HTTP host."""

    port: int = 8000
    """HTTP port."""

    capabilities: MCPCapabilities = field(default_factory=MCPCapabilities)
    """Server capabilities."""

    rate_limit_requests: int = 0
    """Maximum requests per window. Set to 0 to disable rate limiting."""

    rate_limit_window: float = 60.0
    """Rate limit window size in seconds."""


class MCPServer:
    """MCP server that exposes tools.

    MCPServer allows you to expose voice-pipeline tools
    as an MCP-compliant server that can be used by any
    MCP client.

    Example:
        >>> server = MCPServer("my-service")
        >>>
        >>> @server.tool()
        ... def search(query: str) -> str:
        ...     '''Search the web.'''
        ...     return f"Results for: {query}"
        >>>
        >>> await server.run(transport="http", port=8000)

    Example - Adding VoiceTools:
        >>> from voice_pipeline.tools import voice_tool
        >>>
        >>> @voice_tool
        ... def get_weather(city: str) -> str:
        ...     '''Get weather.'''
        ...     return f"Sunny in {city}"
        >>>
        >>> server = MCPServer("weather")
        >>> server.add_voice_tool(get_weather)
        >>> await server.run()
    """

    def __init__(
        self,
        name: str = "voice-pipeline-mcp",
        config: Optional[MCPServerConfig] = None,
    ):
        """Initialize MCP server.

        Args:
            name: Server name.
            config: Server configuration.
        """
        self.config = config or MCPServerConfig(name=name)
        self.config.name = name

        self._tools: dict[str, tuple[MCPTool, Callable]] = {}
        self._resources: dict[str, tuple[MCPResource, Callable]] = {}
        self._prompts: dict[str, tuple[MCPPrompt, Callable]] = {}

        # Initialize rate limiter (disabled by default with rate_limit_requests=0)
        self._rate_limiter: Optional[RateLimiter] = None
        if self.config.rate_limit_requests > 0:
            self._rate_limiter = RateLimiter(
                max_requests=self.config.rate_limit_requests,
                window_seconds=self.config.rate_limit_window,
            )

        # SSE state: maps session_id -> asyncio.Queue for sending responses
        self._sse_sessions: dict[str, asyncio.Queue] = {}

    def tool(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Callable[[F], F]:
        """Decorator to register a tool.

        Args:
            name: Tool name (defaults to function name).
            description: Tool description (defaults to docstring).

        Returns:
            Decorator function.

        Example:
            >>> @server.tool()
            ... def add(a: int, b: int) -> int:
            ...     '''Add two numbers.'''
            ...     return a + b
        """

        def decorator(func: F) -> F:
            tool_name = name or func.__name__
            tool_desc = description or func.__doc__ or ""

            # Build parameter schema from type hints
            sig = inspect.signature(func)
            hints = func.__annotations__

            properties = {}
            required = []

            for param_name, param in sig.parameters.items():
                if param_name in ("self", "ctx", "context"):
                    continue

                param_type = hints.get(param_name, str)
                json_type = self._python_type_to_json(param_type)

                properties[param_name] = {"type": json_type}
                if param.default is inspect.Parameter.empty:
                    required.append(param_name)

            mcp_tool = MCPTool(
                name=tool_name,
                description=tool_desc.strip(),
                parameters={
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            )

            self._tools[tool_name] = (mcp_tool, func)
            return func

        return decorator

    def resource(
        self,
        uri: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        mime_type: str = "text/plain",
    ) -> Callable[[F], F]:
        """Decorator to register a resource.

        Args:
            uri: Resource URI template.
            name: Resource name.
            description: Resource description.
            mime_type: Content MIME type.

        Returns:
            Decorator function.

        Example:
            >>> @server.resource("config://settings")
            ... def get_settings() -> str:
            ...     return '{"theme": "dark"}'
        """

        def decorator(func: F) -> F:
            resource_name = name or func.__name__
            resource_desc = description or func.__doc__ or ""

            mcp_resource = MCPResource(
                uri=uri,
                name=resource_name,
                description=resource_desc.strip(),
                mime_type=mime_type,
            )

            self._resources[uri] = (mcp_resource, func)
            return func

        return decorator

    def prompt(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Callable[[F], F]:
        """Decorator to register a prompt.

        Args:
            name: Prompt name.
            description: Prompt description.

        Returns:
            Decorator function.

        Example:
            >>> @server.prompt()
            ... def greeting(name: str, style: str = "friendly") -> str:
            ...     '''Generate a greeting.'''
            ...     return f"Write a {style} greeting for {name}"
        """

        def decorator(func: F) -> F:
            prompt_name = name or func.__name__
            prompt_desc = description or func.__doc__ or ""

            # Build arguments from signature
            sig = inspect.signature(func)
            arguments = []

            for param_name, param in sig.parameters.items():
                if param_name in ("self", "ctx"):
                    continue

                arg = {
                    "name": param_name,
                    "required": param.default is inspect.Parameter.empty,
                }
                arguments.append(arg)

            mcp_prompt = MCPPrompt(
                name=prompt_name,
                description=prompt_desc.strip(),
                arguments=arguments,
            )

            self._prompts[prompt_name] = (mcp_prompt, func)
            return func

        return decorator

    def add_voice_tool(self, tool: VoiceTool) -> None:
        """Add a VoiceTool to the server.

        Args:
            tool: VoiceTool to add.
        """
        mcp_tool = MCPTool(
            name=tool.name,
            description=tool.description,
            parameters=tool.to_openai_schema().get("function", {}).get("parameters", {}),
        )

        async def wrapper(**kwargs):
            result = await tool.execute(**kwargs)
            return result.output

        self._tools[tool.name] = (mcp_tool, wrapper)

    def _python_type_to_json(self, python_type: type) -> str:
        """Convert Python type to JSON Schema type.

        Args:
            python_type: Python type.

        Returns:
            JSON Schema type string.
        """
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }
        return type_map.get(python_type, "string")

    # ==================== Request Handling ====================

    async def handle_request(
        self,
        request: dict[str, Any],
        client_id: str = "default",
    ) -> dict[str, Any]:
        """Handle an incoming MCP request.

        Args:
            request: JSON-RPC request.
            client_id: Client identifier for rate limiting (e.g., IP address).

        Returns:
            JSON-RPC response.
        """
        request_id = request.get("id")

        # Check rate limit (if enabled)
        if self._rate_limiter is not None:
            if not self._rate_limiter.is_allowed(client_id):
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": MCPErrorCode.RATE_LIMIT_EXCEEDED.value,
                        "message": (
                            f"Rate limit exceeded. "
                            f"Max {self._rate_limiter.max_requests} requests "
                            f"per {self._rate_limiter.window_seconds}s. "
                            f"Retry after {self._rate_limiter.reset_time(client_id):.1f}s."
                        ),
                    },
                }

        method = request.get("method", "")
        params = request.get("params", {})

        try:
            if method == "initialize":
                result = await self._handle_initialize(params)
            elif method == "tools/list":
                result = await self._handle_list_tools()
            elif method == "tools/call":
                result = await self._handle_call_tool(params)
            elif method == "resources/list":
                result = await self._handle_list_resources()
            elif method == "resources/read":
                result = await self._handle_read_resource(params)
            elif method == "prompts/list":
                result = await self._handle_list_prompts()
            elif method == "prompts/get":
                result = await self._handle_get_prompt(params)
            elif method.startswith("notifications/"):
                # Notifications don't need a response
                return {}
            else:
                raise MCPError(
                    code=MCPErrorCode.METHOD_NOT_FOUND,
                    message=f"Unknown method: {method}",
                )

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }

        except MCPError as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": e.to_dict(),
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": MCPErrorCode.INTERNAL_ERROR.value,
                    "message": str(e),
                },
            }

    async def _handle_initialize(self, params: dict) -> dict:
        """Handle initialize request."""
        self.config.capabilities = MCPCapabilities(
            tools=bool(self._tools),
            resources=bool(self._resources),
            prompts=bool(self._prompts),
        )

        return {
            "protocolVersion": "2024-11-05",
            "capabilities": self.config.capabilities.to_dict(),
            "serverInfo": {
                "name": self.config.name,
                "version": self.config.version,
            },
        }

    async def _handle_list_tools(self) -> dict:
        """Handle tools/list request."""
        tools = [tool.to_mcp_schema() for tool, _ in self._tools.values()]
        return {"tools": tools}

    async def _handle_call_tool(self, params: dict) -> dict:
        """Handle tools/call request."""
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        if name not in self._tools:
            raise MCPError(
                code=MCPErrorCode.TOOL_NOT_FOUND,
                message=f"Tool not found: {name}",
            )

        _, func = self._tools[name]

        # Execute tool
        if asyncio.iscoroutinefunction(func):
            result = await func(**arguments)
        else:
            result = func(**arguments)

        # Format result
        mcp_result = MCPResult(content=str(result))
        return mcp_result.to_mcp_response()

    async def _handle_list_resources(self) -> dict:
        """Handle resources/list request."""
        resources = [res.to_mcp_schema() for res, _ in self._resources.values()]
        return {"resources": resources}

    async def _handle_read_resource(self, params: dict) -> dict:
        """Handle resources/read request."""
        uri = params.get("uri", "")

        if uri not in self._resources:
            raise MCPError(
                code=MCPErrorCode.RESOURCE_NOT_FOUND,
                message=f"Resource not found: {uri}",
            )

        resource, func = self._resources[uri]

        # Execute resource handler
        if asyncio.iscoroutinefunction(func):
            content = await func()
        else:
            content = func()

        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": resource.mime_type,
                    "text": str(content),
                }
            ]
        }

    async def _handle_list_prompts(self) -> dict:
        """Handle prompts/list request."""
        prompts = [prompt.to_mcp_schema() for prompt, _ in self._prompts.values()]
        return {"prompts": prompts}

    async def _handle_get_prompt(self, params: dict) -> dict:
        """Handle prompts/get request."""
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        if name not in self._prompts:
            raise MCPError(
                code=MCPErrorCode.METHOD_NOT_FOUND,
                message=f"Prompt not found: {name}",
            )

        _, func = self._prompts[name]

        # Execute prompt handler
        if asyncio.iscoroutinefunction(func):
            content = await func(**arguments)
        else:
            content = func(**arguments)

        return {
            "messages": [
                {"role": "user", "content": {"type": "text", "text": str(content)}}
            ]
        }

    # ==================== Sampling ====================

    async def request_sampling(
        self,
        messages: list[dict[str, Any]],
        session_id: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: Optional[float] = None,
        model_hints: Optional[list[str]] = None,
        intelligence_priority: float = 0.5,
        speed_priority: float = 0.5,
        cost_priority: float = 0.5,
    ) -> Optional[SamplingResponse]:
        """Request LLM sampling from a connected client.

        This allows the server to request the client to generate text
        using the client's LLM. Only works with SSE transport where
        bidirectional communication is possible.

        Args:
            messages: Conversation messages. Each should have 'role' and 'content'.
            session_id: SSE session ID to send request to.
            system_prompt: Optional system prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            model_hints: Optional model name hints (e.g., ["claude-3-sonnet", "gpt-4"]).
            intelligence_priority: Priority for model capability (0-1).
            speed_priority: Priority for speed (0-1).
            cost_priority: Priority for low cost (0-1).

        Returns:
            SamplingResponse if successful, None if session not found or
            client doesn't support sampling.

        Example:
            >>> response = await server.request_sampling(
            ...     messages=[{"role": "user", "content": "Summarize this text: ..."}],
            ...     session_id="abc-123",
            ...     max_tokens=500,
            ... )
            >>> if response:
            ...     print(response.content.text)
        """
        if session_id not in self._sse_sessions:
            return None

        # Build model preferences
        model_prefs = None
        if model_hints or intelligence_priority != 0.5 or speed_priority != 0.5 or cost_priority != 0.5:
            hints = [ModelHint(name=h) for h in (model_hints or [])]
            model_prefs = ModelPreferences(
                hints=hints,
                intelligencePriority=intelligence_priority,
                speedPriority=speed_priority,
                costPriority=cost_priority,
            )

        # Convert messages to SamplingMessage format
        sampling_messages = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                sampling_content = SamplingContent.text_content(content)
            elif isinstance(content, dict):
                sampling_content = SamplingContent.from_dict(content)
            else:
                sampling_content = SamplingContent.text_content(str(content))

            sampling_messages.append(SamplingMessage(
                role=msg.get("role", "user"),
                content=sampling_content,
            ))

        # Build request
        request = SamplingRequest(
            messages=sampling_messages,
            modelPreferences=model_prefs,
            systemPrompt=system_prompt,
            maxTokens=max_tokens,
            temperature=temperature,
        )

        # Send sampling request to client via SSE
        queue = self._sse_sessions[session_id]

        # Generate unique request ID
        import uuid
        request_id = str(uuid.uuid4())

        sampling_request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "sampling/createMessage",
            "params": request.to_dict(),
        }

        await queue.put(sampling_request)

        # Note: In a full implementation, we'd need to wait for the
        # response from the client. For now, we just send the request
        # and return None. A proper implementation would need:
        # 1. A way to receive responses from the client
        # 2. A pending requests map to match responses to requests
        # This is left as future work since it requires significant
        # changes to the SSE transport model.

        return None

    def create_sampling_request(
        self,
        messages: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: Optional[float] = None,
        model_hints: Optional[list[str]] = None,
    ) -> SamplingRequest:
        """Create a SamplingRequest object.

        Helper method to create properly formatted sampling requests.

        Args:
            messages: Conversation messages.
            system_prompt: Optional system prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            model_hints: Optional model name hints.

        Returns:
            SamplingRequest ready to be sent.
        """
        sampling_messages = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                sampling_content = SamplingContent.text_content(content)
            else:
                sampling_content = SamplingContent.from_dict(content)
            sampling_messages.append(SamplingMessage(
                role=msg.get("role", "user"),
                content=sampling_content,
            ))

        model_prefs = None
        if model_hints:
            model_prefs = ModelPreferences(
                hints=[ModelHint(name=h) for h in model_hints],
            )

        return SamplingRequest(
            messages=sampling_messages,
            modelPreferences=model_prefs,
            systemPrompt=system_prompt,
            maxTokens=max_tokens,
            temperature=temperature,
        )

    # ==================== Server Running ====================

    async def run(
        self,
        transport: Optional[TransportType] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        """Run the MCP server.

        Args:
            transport: Transport type.
            host: HTTP host.
            port: HTTP port.
        """
        transport = transport or self.config.transport
        host = host or self.config.host
        port = port or self.config.port

        if transport == TransportType.STDIO:
            await self._run_stdio()
        elif transport == TransportType.SSE:
            await self._run_sse(host, port)
        else:
            await self._run_http(host, port)

    async def _run_stdio(self) -> None:
        """Run server with stdio transport."""
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, sys.stdin.readline
                )
                if not line:
                    break

                request = json.loads(line)
                response = await self.handle_request(request)

                if response:
                    print(json.dumps(response), flush=True)

            except json.JSONDecodeError:
                continue
            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": MCPErrorCode.INTERNAL_ERROR.value,
                        "message": str(e),
                    },
                }
                print(json.dumps(error_response), flush=True)

    async def _run_http(self, host: str, port: int) -> None:
        """Run server with HTTP transport."""
        try:
            from aiohttp import web
        except ImportError:
            raise ImportError(
                "aiohttp is required for HTTP transport. "
                "Install with: pip install aiohttp"
            )

        async def handle_post(request: web.Request) -> web.Response:
            try:
                body = await request.json()
                # Use client IP for rate limiting
                client_ip = request.remote or "unknown"
                response = await self.handle_request(body, client_id=client_ip)
                return web.json_response(response)
            except Exception as e:
                return web.json_response(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32603, "message": str(e)},
                    },
                    status=500,
                )

        app = web.Application()
        app.router.add_post("/mcp", handle_post)
        app.router.add_post("/", handle_post)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()

        print(f"MCP Server '{self.config.name}' running on http://{host}:{port}/mcp")

        # Keep running
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await runner.cleanup()

    async def _run_sse(self, host: str, port: int) -> None:
        """Run server with SSE (Server-Sent Events) transport.

        Implements the MCP SSE transport:
        - GET /sse: Establish SSE connection, receive 'endpoint' event
        - POST /messages/{session_id}: Send JSON-RPC requests
        - Responses sent via SSE 'message' events
        """
        try:
            from aiohttp import web
        except ImportError:
            raise ImportError(
                "aiohttp is required for SSE transport. "
                "Install with: pip install aiohttp"
            )

        import uuid

        async def handle_sse(request: web.Request) -> web.StreamResponse:
            """Handle SSE connection request."""
            # Create unique session ID
            session_id = str(uuid.uuid4())

            # Create queue for this session's responses
            queue: asyncio.Queue = asyncio.Queue()
            self._sse_sessions[session_id] = queue

            # Prepare SSE response
            response = web.StreamResponse(
                status=200,
                reason="OK",
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",  # Disable nginx buffering
                },
            )
            await response.prepare(request)

            # Send endpoint event
            endpoint_url = f"/messages/{session_id}"
            await response.write(
                f"event: endpoint\ndata: {endpoint_url}\n\n".encode()
            )

            client_ip = request.remote or "unknown"

            try:
                # Keep connection alive and send responses
                while True:
                    try:
                        # Wait for response with timeout to allow heartbeat
                        msg = await asyncio.wait_for(queue.get(), timeout=30)
                        # Send message event
                        json_data = json.dumps(msg)
                        await response.write(
                            f"event: message\ndata: {json_data}\n\n".encode()
                        )
                    except asyncio.TimeoutError:
                        # Send heartbeat comment to keep connection alive
                        await response.write(b": heartbeat\n\n")
            except asyncio.CancelledError:
                pass
            except ConnectionResetError:
                pass
            finally:
                # Cleanup session
                self._sse_sessions.pop(session_id, None)

            return response

        async def handle_messages(request: web.Request) -> web.Response:
            """Handle JSON-RPC request via POST."""
            session_id = request.match_info.get("session_id", "")

            if session_id not in self._sse_sessions:
                return web.json_response(
                    {"error": "Session not found"},
                    status=404,
                )

            queue = self._sse_sessions[session_id]

            try:
                body = await request.json()
                client_ip = request.remote or "unknown"

                # Handle request
                response = await self.handle_request(body, client_id=client_ip)

                # Send response via SSE queue
                if response:
                    await queue.put(response)

                # Return 202 Accepted (response will come via SSE)
                return web.Response(status=202)

            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": str(e)},
                }
                await queue.put(error_response)
                return web.Response(status=202)

        app = web.Application()
        app.router.add_get("/sse", handle_sse)
        app.router.add_post("/messages/{session_id}", handle_messages)
        # Also support HTTP for backwards compatibility
        app.router.add_post("/mcp", self._create_http_handler())
        app.router.add_post("/", self._create_http_handler())

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()

        print(f"MCP Server '{self.config.name}' running on http://{host}:{port}/sse (SSE)")
        print(f"  HTTP fallback: http://{host}:{port}/mcp")

        # Keep running
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            # Close all SSE sessions
            for queue in self._sse_sessions.values():
                await queue.put(None)  # Signal to close
            self._sse_sessions.clear()
            await runner.cleanup()

    def _create_http_handler(self):
        """Create HTTP POST handler for use in SSE mode."""
        from aiohttp import web

        async def handle_post(request: web.Request) -> web.Response:
            try:
                body = await request.json()
                client_ip = request.remote or "unknown"
                response = await self.handle_request(body, client_id=client_ip)
                return web.json_response(response)
            except Exception as e:
                return web.json_response(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32603, "message": str(e)},
                    },
                    status=500,
                )

        return handle_post


# Alias for FastMCP-style usage
class VoiceMCP(MCPServer):
    """FastMCP-style MCP server for voice-pipeline.

    Provides a familiar decorator-based API matching the
    official MCP Python SDK's FastMCP.

    Example:
        >>> mcp = VoiceMCP("my-service")
        >>>
        >>> @mcp.tool()
        ... def search(query: str) -> str:
        ...     '''Search the web.'''
        ...     return f"Results for: {query}"
        >>>
        >>> @mcp.resource("config://settings")
        ... def get_settings() -> str:
        ...     return '{"theme": "dark"}'
        >>>
        >>> mcp.run()
    """

    pass
