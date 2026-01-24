"""MCP Server implementation.

Allows exposing voice-pipeline tools as MCP servers.
"""

import asyncio
import inspect
import json
import sys
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
    TransportType,
)
from voice_pipeline.tools.base import VoiceTool

F = TypeVar("F", bound=Callable)


@dataclass
class MCPServerConfig:
    """Configuration for MCP server.

    Attributes:
        name: Server name.
        version: Server version.
        transport: Transport type.
        host: HTTP host.
        port: HTTP port.
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

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle an incoming MCP request.

        Args:
            request: JSON-RPC request.

        Returns:
            JSON-RPC response.
        """
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")

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
                response = await self.handle_request(body)
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
