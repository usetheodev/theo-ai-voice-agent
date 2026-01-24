"""MCP Tool adapters.

Provides bidirectional conversion between MCP tools and VoiceTools.
"""

from typing import Any, Optional, TYPE_CHECKING

from voice_pipeline.mcp.types import MCPResult, MCPTool
from voice_pipeline.tools.base import FunctionTool, ToolParameter, ToolResult, VoiceTool

if TYPE_CHECKING:
    from voice_pipeline.mcp.client import MCPClient


class MCPToolAdapter(VoiceTool):
    """Adapter that wraps an MCP tool as a VoiceTool.

    Allows MCP tools to be used seamlessly with VoiceAgent.

    Example:
        >>> async with MCPClient(url) as client:
        ...     mcp_tools = await client.list_tools()
        ...     for mcp_tool in mcp_tools:
        ...         voice_tool = MCPToolAdapter(client, mcp_tool)
        ...         agent.add_tool(voice_tool)
    """

    def __init__(
        self,
        client: "MCPClient",
        mcp_tool: MCPTool,
    ):
        """Initialize MCP tool adapter.

        Args:
            client: MCP client connection.
            mcp_tool: MCP tool definition.
        """
        self._client = client
        self._mcp_tool = mcp_tool

    @property
    def name(self) -> str:
        """Tool name."""
        return self._mcp_tool.name

    @property
    def description(self) -> str:
        """Tool description."""
        return self._mcp_tool.description

    @property
    def parameters(self) -> list[ToolParameter]:
        """Tool parameters."""
        params = []
        schema = self._mcp_tool.parameters

        properties = schema.get("properties", {})
        required = schema.get("required", [])

        for name, prop in properties.items():
            params.append(
                ToolParameter(
                    name=name,
                    type=prop.get("type", "string"),
                    description=prop.get("description", ""),
                    required=name in required,
                    default=prop.get("default"),
                )
            )

        return params

    @property
    def return_direct(self) -> bool:
        """Whether to return output directly."""
        return False

    def _json_type_to_python(self, json_type: str) -> type:
        """Convert JSON Schema type to Python type."""
        type_map = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        return type_map.get(json_type, str)

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the MCP tool.

        Args:
            **kwargs: Tool arguments.

        Returns:
            ToolResult with output.
        """
        try:
            result = await self._client.call_tool(self.name, kwargs)

            if result.is_error:
                return ToolResult(
                    success=False,
                    output=str(result.content),
                    error=str(result.content),
                )

            return ToolResult(
                success=True,
                output=str(result.content),
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._mcp_tool.parameters,
            },
        }

    def to_anthropic_schema(self) -> dict[str, Any]:
        """Convert to Anthropic tool schema."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self._mcp_tool.parameters,
        }


def mcp_tool_to_voice_tool(
    client: "MCPClient",
    mcp_tool: MCPTool,
) -> VoiceTool:
    """Convert an MCP tool to a VoiceTool.

    Args:
        client: MCP client connection.
        mcp_tool: MCP tool to convert.

    Returns:
        VoiceTool adapter.

    Example:
        >>> async with MCPClient(url) as client:
        ...     mcp_tools = await client.list_tools()
        ...     voice_tool = mcp_tool_to_voice_tool(client, mcp_tools[0])
    """
    return MCPToolAdapter(client, mcp_tool)


def mcp_tools_to_voice_tools(
    client: "MCPClient",
    mcp_tools: list[MCPTool],
) -> list[VoiceTool]:
    """Convert multiple MCP tools to VoiceTools.

    Args:
        client: MCP client connection.
        mcp_tools: List of MCP tools.

    Returns:
        List of VoiceTool adapters.

    Example:
        >>> async with MCPClient(url) as client:
        ...     mcp_tools = await client.list_tools()
        ...     voice_tools = mcp_tools_to_voice_tools(client, mcp_tools)
        ...     agent = VoiceAgent(llm=llm, tools=voice_tools)
    """
    return [MCPToolAdapter(client, tool) for tool in mcp_tools]


def voice_tool_to_mcp(tool: VoiceTool) -> MCPTool:
    """Convert a VoiceTool to MCP tool definition.

    Args:
        tool: VoiceTool to convert.

    Returns:
        MCPTool definition.

    Example:
        >>> @voice_tool
        ... def search(query: str) -> str:
        ...     '''Search the web.'''
        ...     return "results"
        >>>
        >>> mcp_tool = voice_tool_to_mcp(search)
    """
    # Build parameter schema
    properties = {}
    required = []

    for param in tool.parameters:
        properties[param.name] = {
            "type": param.type,
            "description": param.description,
        }
        if param.default is not None:
            properties[param.name]["default"] = param.default

        if param.required:
            required.append(param.name)

    return MCPTool(
        name=tool.name,
        description=tool.description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": required,
        },
    )


def voice_tools_to_mcp(tools: list[VoiceTool]) -> list[MCPTool]:
    """Convert multiple VoiceTools to MCP tool definitions.

    Args:
        tools: List of VoiceTools.

    Returns:
        List of MCPTool definitions.
    """
    return [voice_tool_to_mcp(tool) for tool in tools]


def _python_type_to_json(python_type: type) -> str:
    """Convert Python type to JSON Schema type."""
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    # Handle string type names
    if isinstance(python_type, str):
        return python_type

    return type_map.get(python_type, "string")


class MCPToolExecutor:
    """Executor for MCP tools.

    Manages connections to multiple MCP servers and provides
    a unified interface for tool execution.

    Example:
        >>> executor = MCPToolExecutor()
        >>> await executor.add_server("search", "http://localhost:8000/mcp")
        >>> await executor.add_server("math", "http://localhost:8001/mcp")
        >>>
        >>> result = await executor.call("search:web_search", {"query": "AI"})
    """

    def __init__(self):
        """Initialize executor."""
        self._clients: dict[str, "MCPClient"] = {}
        self._tools: dict[str, tuple[str, MCPTool]] = {}

    async def add_server(
        self,
        name: str,
        url: str,
    ) -> list[MCPTool]:
        """Add an MCP server.

        Args:
            name: Server name (used as prefix).
            url: Server URL.

        Returns:
            List of tools from the server.
        """
        from voice_pipeline.mcp.client import MCPClient

        client = MCPClient(url)
        await client.connect()
        self._clients[name] = client

        # Load tools
        tools = await client.list_tools()
        for tool in tools:
            tool_id = f"{name}:{tool.name}"
            self._tools[tool_id] = (name, tool)

        return tools

    async def remove_server(self, name: str) -> None:
        """Remove an MCP server.

        Args:
            name: Server name.
        """
        if name in self._clients:
            await self._clients[name].disconnect()
            del self._clients[name]

        # Remove tools
        self._tools = {
            k: v for k, v in self._tools.items() if not k.startswith(f"{name}:")
        }

    async def call(
        self,
        tool_id: str,
        arguments: Optional[dict[str, Any]] = None,
    ) -> MCPResult:
        """Call a tool.

        Args:
            tool_id: Tool ID (format: "server:tool_name").
            arguments: Tool arguments.

        Returns:
            MCPResult with output.
        """
        if tool_id not in self._tools:
            return MCPResult(
                content=f"Tool not found: {tool_id}",
                is_error=True,
            )

        server_name, tool = self._tools[tool_id]
        client = self._clients.get(server_name)

        if not client:
            return MCPResult(
                content=f"Server not connected: {server_name}",
                is_error=True,
            )

        return await client.call_tool(tool.name, arguments or {})

    def list_tools(self) -> list[str]:
        """List all available tool IDs.

        Returns:
            List of tool IDs.
        """
        return list(self._tools.keys())

    def get_all_voice_tools(self) -> list[VoiceTool]:
        """Get all tools as VoiceTools.

        Returns:
            List of VoiceTool adapters.
        """
        tools = []
        for server_name, mcp_tool in self._tools.values():
            client = self._clients[server_name]
            tools.append(MCPToolAdapter(client, mcp_tool))
        return tools

    async def close(self) -> None:
        """Close all connections."""
        for client in self._clients.values():
            await client.disconnect()
        self._clients.clear()
        self._tools.clear()
