"""MCP (Model Context Protocol) integration for voice-pipeline.

This module provides MCP support, allowing voice agents to:
- Connect to MCP servers and use their tools
- Expose voice-pipeline tools as MCP servers
- Integrate MCP resources and prompts

MCP is an open standard by Anthropic for connecting AI models
to external tools and data sources.

Example - Using MCP tools in VoiceAgent:
    >>> from voice_pipeline.mcp import MCPClient, mcp_tools_to_voice_tools
    >>>
    >>> # Connect to MCP server
    >>> async with MCPClient("http://localhost:8000/mcp") as client:
    ...     # Get tools from server
    ...     mcp_tools = await client.list_tools()
    ...     voice_tools = mcp_tools_to_voice_tools(client, mcp_tools)
    ...
    ...     # Use in agent
    ...     agent = VoiceAgent(llm=llm, tools=voice_tools)
    ...     result = await agent.ainvoke("Search for AI news")

Example - Exposing tools as MCP server:
    >>> from voice_pipeline.mcp import MCPServer, voice_tool_to_mcp
    >>>
    >>> @voice_tool
    ... def get_weather(city: str) -> str:
    ...     '''Get weather for a city.'''
    ...     return f"Sunny in {city}"
    >>>
    >>> server = MCPServer("weather-service")
    >>> server.add_voice_tool(get_weather)
    >>> await server.run(transport="http", port=8000)

Example - FastMCP-style decorator:
    >>> from voice_pipeline.mcp import VoiceMCP
    >>>
    >>> mcp = VoiceMCP("my-voice-service")
    >>>
    >>> @mcp.tool()
    ... def search(query: str) -> str:
    ...     '''Search the web.'''
    ...     return f"Results for: {query}"
    >>>
    >>> @mcp.resource("config://settings")
    ... def get_settings() -> str:
    ...     return '{"voice": "en-US"}'
    >>>
    >>> mcp.run(transport="http")

Sources:
- https://github.com/modelcontextprotocol/python-sdk
- https://modelcontextprotocol.io/specification/2025-11-25
- https://pypi.org/project/mcp/
"""

# Types
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
    # Sampling types
    ModelHint,
    ModelPreferences,
    SamplingContent,
    SamplingMessage,
    SamplingRequest,
    SamplingResponse,
)

# Client
from voice_pipeline.mcp.client import (
    MCPClient,
    MCPClientConfig,
    MCPConnection,
)

# Server
from voice_pipeline.mcp.server import (
    MCPServer,
    MCPServerConfig,
    VoiceMCP,
)

# Tool adapters
from voice_pipeline.mcp.tools import (
    MCPToolAdapter,
    MCPToolExecutor,
    mcp_tool_to_voice_tool,
    mcp_tools_to_voice_tools,
    voice_tool_to_mcp,
    voice_tools_to_mcp,
)

# Agent integration
from voice_pipeline.mcp.agent import (
    MCPEnabledAgent,
    create_mcp_agent,
    load_mcp_tools,
)

__all__ = [
    # Types
    "MCPTool",
    "MCPResource",
    "MCPPrompt",
    "MCPToolCall",
    "MCPResult",
    "MCPError",
    "MCPErrorCode",
    "MCPCapabilities",
    "TransportType",
    # Sampling types
    "ModelHint",
    "ModelPreferences",
    "SamplingContent",
    "SamplingMessage",
    "SamplingRequest",
    "SamplingResponse",
    # Client
    "MCPClient",
    "MCPClientConfig",
    "MCPConnection",
    # Server
    "MCPServer",
    "MCPServerConfig",
    "VoiceMCP",
    # Tool adapters
    "MCPToolAdapter",
    "MCPToolExecutor",
    "mcp_tool_to_voice_tool",
    "mcp_tools_to_voice_tools",
    "voice_tool_to_mcp",
    "voice_tools_to_mcp",
    # Agent integration
    "MCPEnabledAgent",
    "create_mcp_agent",
    "load_mcp_tools",
]
