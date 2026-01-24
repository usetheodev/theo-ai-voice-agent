"""Tests for MCP integration."""

import pytest
from typing import Any, AsyncIterator, Optional

from voice_pipeline.mcp import (
    MCPCapabilities,
    MCPClient,
    MCPClientConfig,
    MCPEnabledAgent,
    MCPError,
    MCPErrorCode,
    MCPPrompt,
    MCPResource,
    MCPResult,
    MCPServer,
    MCPTool,
    MCPToolCall,
    TransportType,
    VoiceMCP,
    create_mcp_agent,
    mcp_tool_to_voice_tool,
    mcp_tools_to_voice_tools,
    voice_tool_to_mcp,
    voice_tools_to_mcp,
)
from voice_pipeline.mcp.tools import MCPToolAdapter, MCPToolExecutor
from voice_pipeline.agents.base import VoiceAgent
from voice_pipeline.interfaces.llm import LLMChunk, LLMInterface
from voice_pipeline.tools import voice_tool


# ==================== Mock LLM ====================


class MockLLM(LLMInterface):
    """Mock LLM for testing."""

    def __init__(self, response: str = "Mock response"):
        self.response = response

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        yield LLMChunk(text=self.response, is_final=True)


# ==================== Test Types ====================


class TestMCPTool:
    """Tests for MCPTool."""

    def test_basic_creation(self):
        """Test basic tool creation."""
        tool = MCPTool(
            name="search",
            description="Search the web",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        )

        assert tool.name == "search"
        assert tool.description == "Search the web"

    def test_to_mcp_schema(self):
        """Test MCP schema generation."""
        tool = MCPTool(
            name="add",
            description="Add numbers",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
            },
        )

        schema = tool.to_mcp_schema()
        assert schema["name"] == "add"
        assert schema["description"] == "Add numbers"
        assert "inputSchema" in schema

    def test_from_mcp_schema(self):
        """Test creating from MCP schema."""
        schema = {
            "name": "search",
            "description": "Search the web",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        }

        tool = MCPTool.from_mcp_schema(schema)
        assert tool.name == "search"
        assert tool.description == "Search the web"


class TestMCPToolCall:
    """Tests for MCPToolCall."""

    def test_basic_creation(self):
        """Test basic call creation."""
        call = MCPToolCall(
            name="search",
            arguments={"query": "AI news"},
            call_id="call_123",
        )

        assert call.name == "search"
        assert call.arguments["query"] == "AI news"

    def test_to_mcp_request(self):
        """Test MCP request format."""
        call = MCPToolCall(
            name="add",
            arguments={"a": 1, "b": 2},
        )

        request = call.to_mcp_request()
        assert request["name"] == "add"
        assert request["arguments"] == {"a": 1, "b": 2}


class TestMCPResult:
    """Tests for MCPResult."""

    def test_string_result(self):
        """Test string result."""
        result = MCPResult(content="Hello world")
        response = result.to_mcp_response()

        assert response["content"][0]["type"] == "text"
        assert response["content"][0]["text"] == "Hello world"
        assert response["isError"] is False

    def test_error_result(self):
        """Test error result."""
        result = MCPResult(
            content="Something went wrong",
            is_error=True,
        )

        response = result.to_mcp_response()
        assert response["isError"] is True


class TestMCPResource:
    """Tests for MCPResource."""

    def test_basic_creation(self):
        """Test basic resource creation."""
        resource = MCPResource(
            uri="config://settings",
            name="Settings",
            description="Application settings",
            mime_type="application/json",
        )

        assert resource.uri == "config://settings"
        assert resource.mime_type == "application/json"

    def test_to_mcp_schema(self):
        """Test MCP schema generation."""
        resource = MCPResource(
            uri="file://docs/{name}",
            name="Documents",
        )

        schema = resource.to_mcp_schema()
        assert schema["uri"] == "file://docs/{name}"


class TestMCPPrompt:
    """Tests for MCPPrompt."""

    def test_basic_creation(self):
        """Test basic prompt creation."""
        prompt = MCPPrompt(
            name="greeting",
            description="Generate a greeting",
            arguments=[
                {"name": "name", "required": True},
                {"name": "style", "required": False},
            ],
        )

        assert prompt.name == "greeting"
        assert len(prompt.arguments) == 2

    def test_to_mcp_schema(self):
        """Test MCP schema generation."""
        prompt = MCPPrompt(
            name="summarize",
            description="Summarize text",
        )

        schema = prompt.to_mcp_schema()
        assert schema["name"] == "summarize"


class TestMCPCapabilities:
    """Tests for MCPCapabilities."""

    def test_default_capabilities(self):
        """Test default capabilities."""
        caps = MCPCapabilities()
        assert caps.tools is True
        assert caps.resources is False

    def test_to_dict(self):
        """Test dict conversion."""
        caps = MCPCapabilities(
            tools=True,
            resources=True,
            prompts=False,
        )

        d = caps.to_dict()
        assert "tools" in d
        assert "resources" in d
        assert "prompts" not in d


class TestMCPError:
    """Tests for MCPError."""

    def test_error_creation(self):
        """Test error creation."""
        error = MCPError(
            code=MCPErrorCode.TOOL_NOT_FOUND,
            message="Tool not found: xyz",
        )

        assert error.code == MCPErrorCode.TOOL_NOT_FOUND
        assert "xyz" in str(error)

    def test_to_dict(self):
        """Test dict conversion."""
        error = MCPError(
            code=MCPErrorCode.INVALID_PARAMS,
            message="Missing required parameter",
            data={"param": "query"},
        )

        d = error.to_dict()
        assert d["code"] == "InvalidParams"
        assert d["data"]["param"] == "query"


# ==================== Test Server ====================


class TestMCPServer:
    """Tests for MCPServer."""

    def test_tool_decorator(self):
        """Test tool decorator."""
        server = MCPServer("test")

        @server.tool()
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        assert "add" in server._tools
        tool, func = server._tools["add"]
        assert tool.name == "add"
        assert "Add two numbers" in tool.description

    def test_tool_decorator_with_name(self):
        """Test tool decorator with custom name."""
        server = MCPServer("test")

        @server.tool(name="custom_add", description="Custom add function")
        def add(a: int, b: int) -> int:
            return a + b

        assert "custom_add" in server._tools
        tool, _ = server._tools["custom_add"]
        assert tool.description == "Custom add function"

    def test_resource_decorator(self):
        """Test resource decorator."""
        server = MCPServer("test")

        @server.resource("config://settings")
        def get_settings() -> str:
            """Get settings."""
            return '{"theme": "dark"}'

        assert "config://settings" in server._resources
        resource, _ = server._resources["config://settings"]
        assert resource.uri == "config://settings"

    def test_prompt_decorator(self):
        """Test prompt decorator."""
        server = MCPServer("test")

        @server.prompt()
        def greeting(name: str, style: str = "friendly") -> str:
            """Generate a greeting."""
            return f"Write a {style} greeting for {name}"

        assert "greeting" in server._prompts
        prompt, _ = server._prompts["greeting"]
        assert len(prompt.arguments) == 2

    def test_add_voice_tool(self):
        """Test adding VoiceTool."""
        server = MCPServer("test")

        @voice_tool
        def search(query: str) -> str:
            """Search the web."""
            return f"Results for: {query}"

        server.add_voice_tool(search)
        assert "search" in server._tools

    @pytest.mark.asyncio
    async def test_handle_initialize(self):
        """Test initialize request."""
        server = MCPServer("test")

        @server.tool()
        def my_tool() -> str:
            return "result"

        response = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        })

        assert response["result"]["serverInfo"]["name"] == "test"
        assert "tools" in response["result"]["capabilities"]

    @pytest.mark.asyncio
    async def test_handle_list_tools(self):
        """Test tools/list request."""
        server = MCPServer("test")

        @server.tool()
        def add(a: int, b: int) -> int:
            """Add numbers."""
            return a + b

        response = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        })

        tools = response["result"]["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "add"

    @pytest.mark.asyncio
    async def test_handle_call_tool(self):
        """Test tools/call request."""
        server = MCPServer("test")

        @server.tool()
        def add(a: int, b: int) -> int:
            """Add numbers."""
            return a + b

        response = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "add",
                "arguments": {"a": 2, "b": 3},
            },
        })

        content = response["result"]["content"]
        assert "5" in content[0]["text"]

    @pytest.mark.asyncio
    async def test_handle_call_async_tool(self):
        """Test calling async tool."""
        server = MCPServer("test")

        @server.tool()
        async def async_add(a: int, b: int) -> int:
            """Add numbers async."""
            return a + b

        response = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "async_add",
                "arguments": {"a": 2, "b": 3},
            },
        })

        content = response["result"]["content"]
        assert "5" in content[0]["text"]

    @pytest.mark.asyncio
    async def test_handle_tool_not_found(self):
        """Test tool not found error."""
        server = MCPServer("test")

        response = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "nonexistent",
                "arguments": {},
            },
        })

        assert "error" in response
        assert response["error"]["code"] == "ToolNotFound"

    @pytest.mark.asyncio
    async def test_handle_list_resources(self):
        """Test resources/list request."""
        server = MCPServer("test")

        @server.resource("config://settings")
        def get_settings() -> str:
            return "{}"

        response = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/list",
        })

        resources = response["result"]["resources"]
        assert len(resources) == 1

    @pytest.mark.asyncio
    async def test_handle_read_resource(self):
        """Test resources/read request."""
        server = MCPServer("test")

        @server.resource("config://settings")
        def get_settings() -> str:
            return '{"theme": "dark"}'

        response = await server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "config://settings"},
        })

        contents = response["result"]["contents"]
        assert "dark" in contents[0]["text"]


class TestVoiceMCP:
    """Tests for VoiceMCP (alias)."""

    def test_is_mcp_server(self):
        """Test VoiceMCP is MCPServer."""
        mcp = VoiceMCP("test")
        assert isinstance(mcp, MCPServer)


# ==================== Test Tool Adapters ====================


class TestMCPToolAdapter:
    """Tests for MCPToolAdapter."""

    def test_properties(self):
        """Test adapter properties."""
        mcp_tool = MCPTool(
            name="search",
            description="Search the web",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        )

        # Create mock client
        class MockClient:
            async def call_tool(self, name, args):
                return MCPResult(content=f"Results for: {args['query']}")

        adapter = MCPToolAdapter(MockClient(), mcp_tool)

        assert adapter.name == "search"
        assert adapter.description == "Search the web"
        assert len(adapter.parameters) == 1
        assert adapter.parameters[0].name == "query"

    @pytest.mark.asyncio
    async def test_execute(self):
        """Test tool execution."""
        mcp_tool = MCPTool(
            name="add",
            description="Add numbers",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
            },
        )

        class MockClient:
            async def call_tool(self, name, args):
                return MCPResult(content=str(args["a"] + args["b"]))

        adapter = MCPToolAdapter(MockClient(), mcp_tool)
        result = await adapter.execute(a=2, b=3)

        assert result.output == "5"
        assert result.error is None

    def test_to_openai_schema(self):
        """Test OpenAI schema generation."""
        mcp_tool = MCPTool(
            name="test",
            description="Test tool",
            parameters={"type": "object", "properties": {}},
        )

        class MockClient:
            pass

        adapter = MCPToolAdapter(MockClient(), mcp_tool)
        schema = adapter.to_openai_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test"


class TestToolConversions:
    """Tests for tool conversion functions."""

    def test_voice_tool_to_mcp(self):
        """Test converting VoiceTool to MCPTool."""

        @voice_tool
        def search(query: str) -> str:
            """Search the web."""
            return f"Results for: {query}"

        mcp_tool = voice_tool_to_mcp(search)

        assert mcp_tool.name == "search"
        assert "Search the web" in mcp_tool.description
        assert "query" in mcp_tool.parameters.get("properties", {})

    def test_voice_tools_to_mcp(self):
        """Test converting multiple VoiceTools."""

        @voice_tool
        def tool1() -> str:
            """Tool 1."""
            return "1"

        @voice_tool
        def tool2() -> str:
            """Tool 2."""
            return "2"

        mcp_tools = voice_tools_to_mcp([tool1, tool2])

        assert len(mcp_tools) == 2
        assert mcp_tools[0].name == "tool1"
        assert mcp_tools[1].name == "tool2"

    def test_mcp_tool_to_voice_tool(self):
        """Test converting MCPTool to VoiceTool."""
        mcp_tool = MCPTool(
            name="search",
            description="Search",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )

        class MockClient:
            pass

        voice_tool = mcp_tool_to_voice_tool(MockClient(), mcp_tool)

        assert voice_tool.name == "search"
        assert len(voice_tool.parameters) == 1

    def test_mcp_tools_to_voice_tools(self):
        """Test converting multiple MCPTools."""
        mcp_tools = [
            MCPTool(name="t1", description="Tool 1"),
            MCPTool(name="t2", description="Tool 2"),
        ]

        class MockClient:
            pass

        voice_tools = mcp_tools_to_voice_tools(MockClient(), mcp_tools)

        assert len(voice_tools) == 2


class TestMCPToolExecutor:
    """Tests for MCPToolExecutor."""

    def test_list_tools_empty(self):
        """Test empty executor."""
        executor = MCPToolExecutor()
        assert executor.list_tools() == []

    @pytest.mark.asyncio
    async def test_close(self):
        """Test closing executor."""
        executor = MCPToolExecutor()
        await executor.close()
        assert len(executor._clients) == 0


# ==================== Test Agent Integration ====================


class TestMCPEnabledAgent:
    """Tests for MCPEnabledAgent."""

    def test_basic_creation(self):
        """Test basic agent creation."""
        llm = MockLLM()
        agent = MCPEnabledAgent(
            llm=llm,
            mcp_servers=["http://localhost:8000/mcp"],
        )

        assert len(agent._mcp_server_config) == 1
        assert not agent._connected

    def test_creation_with_dict_servers(self):
        """Test creation with dict servers."""
        llm = MockLLM()
        agent = MCPEnabledAgent(
            llm=llm,
            mcp_servers={
                "search": "http://search:8000/mcp",
                "math": "http://math:8001/mcp",
            },
        )

        assert "search" in agent._mcp_server_config
        assert "math" in agent._mcp_server_config

    def test_add_remove_server(self):
        """Test adding and removing servers."""
        llm = MockLLM()
        agent = MCPEnabledAgent(llm=llm)

        agent.add_mcp_server("test", "http://test:8000/mcp")
        assert "test" in agent.list_mcp_servers()

        agent.remove_mcp_server("test")
        assert "test" not in agent.list_mcp_servers()


class TestCreateMCPAgent:
    """Tests for create_mcp_agent factory."""

    def test_create_agent(self):
        """Test creating agent with factory."""
        llm = MockLLM()
        agent = create_mcp_agent(
            llm=llm,
            mcp_servers=["http://localhost:8000/mcp"],
            max_iterations=5,
        )

        assert isinstance(agent, MCPEnabledAgent)
        assert agent.max_iterations == 5


# ==================== Test Client Config ====================


class TestMCPClientConfig:
    """Tests for MCPClientConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = MCPClientConfig()

        assert config.transport == TransportType.HTTP
        assert config.timeout == 30.0
        assert config.retry_attempts == 3

    def test_custom_config(self):
        """Test custom configuration."""
        config = MCPClientConfig(
            transport=TransportType.STDIO,
            timeout=60.0,
            headers={"Authorization": "Bearer token"},
        )

        assert config.transport == TransportType.STDIO
        assert config.timeout == 60.0
        assert "Authorization" in config.headers
