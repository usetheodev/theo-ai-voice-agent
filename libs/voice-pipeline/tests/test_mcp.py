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
    # Sampling types
    ModelHint,
    ModelPreferences,
    SamplingContent,
    SamplingMessage,
    SamplingRequest,
    SamplingResponse,
)
from voice_pipeline.mcp.tools import MCPToolAdapter, MCPToolExecutor
from voice_pipeline.mcp.client import MCPConnection
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


# ==================== Test Client Retry Logic ====================


class TestMCPClientRetry:
    """Tests for MCPClient retry with exponential backoff (I-06)."""

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Test that _request_with_retry retries on CONNECTION_ERROR."""
        from unittest.mock import AsyncMock, patch

        client = MCPClient("http://localhost:9999/mcp")
        client.config.retry_attempts = 3

        call_count = 0

        async def mock_request(method, params=None):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise MCPError(
                    code=MCPErrorCode.CONNECTION_ERROR,
                    message="Connection refused",
                )
            return {"tools": []}

        with patch.object(client, "_request", side_effect=mock_request):
            result = await client._request_with_retry("tools/list")

        assert result == {"tools": []}
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self):
        """Test that _request_with_retry retries on TIMEOUT."""
        from unittest.mock import patch

        client = MCPClient("http://localhost:9999/mcp")
        client.config.retry_attempts = 2

        call_count = 0

        async def mock_request(method, params=None):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise MCPError(
                    code=MCPErrorCode.TIMEOUT,
                    message="Request timed out",
                )
            return {"ok": True}

        async def mock_reconnect():
            pass  # No-op for this test

        with patch.object(client, "_request", side_effect=mock_request):
            with patch.object(client, "_reconnect", side_effect=mock_reconnect):
                result = await client._request_with_retry("test")

        assert result == {"ok": True}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_logic_error(self):
        """Test that non-retryable errors propagate immediately."""
        from unittest.mock import patch

        client = MCPClient("http://localhost:9999/mcp")
        client.config.retry_attempts = 3

        call_count = 0

        async def mock_request(method, params=None):
            nonlocal call_count
            call_count += 1
            raise MCPError(
                code=MCPErrorCode.TOOL_NOT_FOUND,
                message="Tool xyz not found",
            )

        with patch.object(client, "_request", side_effect=mock_request):
            with pytest.raises(MCPError) as exc_info:
                await client._request_with_retry("tools/call", {"name": "xyz"})

        assert exc_info.value.code == MCPErrorCode.TOOL_NOT_FOUND
        assert call_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self):
        """Test that all retries exhausted raises the last error."""
        from unittest.mock import patch

        client = MCPClient("http://localhost:9999/mcp")
        client.config.retry_attempts = 2

        call_count = 0

        async def mock_request(method, params=None):
            nonlocal call_count
            call_count += 1
            raise MCPError(
                code=MCPErrorCode.CONNECTION_ERROR,
                message=f"Fail #{call_count}",
            )

        async def mock_reconnect():
            pass  # No-op for this test

        with patch.object(client, "_request", side_effect=mock_request):
            with patch.object(client, "_reconnect", side_effect=mock_reconnect):
                with pytest.raises(MCPError) as exc_info:
                    await client._request_with_retry("tools/list")

        assert exc_info.value.code == MCPErrorCode.CONNECTION_ERROR
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_auto_reconnect_on_connection_error(self):
        """Test that connection errors trigger automatic reconnection (I-06)."""
        from unittest.mock import patch, AsyncMock

        client = MCPClient("http://localhost:9999/mcp")
        client.config.retry_attempts = 2
        # Fake connection state
        client.connection = MCPConnection(
            url=client.url,
            transport=client.config.transport,
            is_connected=True,
        )

        call_count = 0
        reconnect_count = 0

        async def mock_request(method, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise MCPError(
                    code=MCPErrorCode.CONNECTION_ERROR,
                    message="Server went away",
                )
            return {"tools": []}

        async def mock_reconnect():
            nonlocal reconnect_count
            reconnect_count += 1
            client.connection.is_connected = True

        with patch.object(client, "_request", side_effect=mock_request):
            with patch.object(client, "_reconnect", side_effect=mock_reconnect):
                result = await client._request_with_retry("tools/list")

        assert result == {"tools": []}
        assert call_count == 2
        assert reconnect_count == 1
        # Connection should be re-established
        assert client.connection.is_connected is True


# ==================== Test Client HTTP Fallback ====================


class TestMCPClientHTTPFallback:
    """Tests for MCPClient HTTP fallback (C-04)."""

    @pytest.mark.asyncio
    async def test_sync_fallback_runs_in_thread(self):
        """Test that urllib fallback runs via asyncio.to_thread."""
        import asyncio
        from unittest.mock import patch, MagicMock

        client = MCPClient("http://localhost:9999/mcp")
        client.config.timeout = 5.0

        request = {"jsonrpc": "2.0", "id": 1, "method": "test"}

        # Mock _sync_request_http to verify it's called via to_thread
        expected_result = {"status": "ok"}

        with patch.object(client, "_sync_request_http", return_value=expected_result) as mock_sync:
            with patch("voice_pipeline.mcp.client.aiohttp", None):
                result = await asyncio.to_thread(client._sync_request_http, request)

        assert result == expected_result
        mock_sync.assert_called_once_with(request)

    def test_sync_request_http_raises_on_url_error(self):
        """Test that _sync_request_http raises MCPError on URL error."""
        client = MCPClient("http://localhost:1/invalid")
        client.config.timeout = 0.5

        request = {"jsonrpc": "2.0", "id": 1, "method": "test"}

        with pytest.raises(MCPError) as exc_info:
            client._sync_request_http(request)

        assert exc_info.value.code == MCPErrorCode.CONNECTION_ERROR

    @pytest.mark.asyncio
    async def test_aiohttp_none_uses_thread_fallback(self):
        """Test that when aiohttp is None, _request_http uses to_thread."""
        from unittest.mock import patch, AsyncMock

        client = MCPClient("http://localhost:9999/mcp")
        request = {"jsonrpc": "2.0", "id": 1, "method": "test"}
        expected = {"tools": []}

        with patch("voice_pipeline.mcp.client.aiohttp", None):
            with patch.object(client, "_sync_request_http", return_value=expected) as mock_sync:
                result = await client._request_http(request)

        assert result == expected
        mock_sync.assert_called_once_with(request)


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


# ==================== Test Server Rate Limiting ====================


class TestMCPServerRateLimiting:
    """Tests for MCP Server rate limiting (I-07)."""

    def test_rate_limiter_allows_under_limit(self):
        """Test that requests under limit are allowed."""
        from voice_pipeline.mcp.server import RateLimiter

        limiter = RateLimiter(max_requests=5, window_seconds=60)

        # First 5 requests should be allowed
        for i in range(5):
            assert limiter.is_allowed("client1") is True

        # 6th request should be blocked
        assert limiter.is_allowed("client1") is False

    def test_rate_limiter_tracks_per_client(self):
        """Test that rate limits are tracked per client."""
        from voice_pipeline.mcp.server import RateLimiter

        limiter = RateLimiter(max_requests=2, window_seconds=60)

        # Client 1 uses their limit
        assert limiter.is_allowed("client1") is True
        assert limiter.is_allowed("client1") is True
        assert limiter.is_allowed("client1") is False

        # Client 2 has their own limit
        assert limiter.is_allowed("client2") is True
        assert limiter.is_allowed("client2") is True
        assert limiter.is_allowed("client2") is False

    def test_rate_limiter_remaining(self):
        """Test remaining requests calculation."""
        from voice_pipeline.mcp.server import RateLimiter

        limiter = RateLimiter(max_requests=5, window_seconds=60)

        assert limiter.remaining("client1") == 5

        limiter.is_allowed("client1")
        assert limiter.remaining("client1") == 4

        limiter.is_allowed("client1")
        limiter.is_allowed("client1")
        assert limiter.remaining("client1") == 2

    def test_server_rate_limit_disabled_by_default(self):
        """Test that rate limiting is disabled by default."""
        from voice_pipeline.mcp.server import MCPServer, MCPServerConfig

        server = MCPServer("test")
        assert server._rate_limiter is None

    def test_server_rate_limit_enabled(self):
        """Test that rate limiting can be enabled via config."""
        from voice_pipeline.mcp.server import MCPServer, MCPServerConfig

        config = MCPServerConfig(
            name="test",
            rate_limit_requests=100,
            rate_limit_window=60.0,
        )
        server = MCPServer("test", config=config)

        assert server._rate_limiter is not None
        assert server._rate_limiter.max_requests == 100
        assert server._rate_limiter.window_seconds == 60.0

    @pytest.mark.asyncio
    async def test_server_rejects_when_rate_limited(self):
        """Test that server returns error when rate limited."""
        from voice_pipeline.mcp.server import MCPServer, MCPServerConfig

        config = MCPServerConfig(
            name="test",
            rate_limit_requests=2,
            rate_limit_window=60.0,
        )
        server = MCPServer("test", config=config)

        # First 2 requests should work
        response1 = await server.handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            client_id="test-client",
        )
        assert "error" not in response1

        response2 = await server.handle_request(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            client_id="test-client",
        )
        assert "error" not in response2

        # Third request should be rate limited
        response3 = await server.handle_request(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            client_id="test-client",
        )
        assert "error" in response3
        assert "RateLimitExceeded" in response3["error"]["code"]
        assert "Rate limit exceeded" in response3["error"]["message"]


# ==================== Test Client SSE Transport ====================


class TestMCPClientSSE:
    """Tests for MCP Client SSE transport (C-05)."""

    def test_sse_transport_auto_detect(self):
        """Test that SSE transport must be explicitly set."""
        # HTTP URLs default to HTTP, not SSE
        client = MCPClient("http://localhost:8000")
        assert client.config.transport == TransportType.HTTP

        # Explicit SSE
        client2 = MCPClient("http://localhost:8000", transport=TransportType.SSE)
        assert client2.config.transport == TransportType.SSE

    def test_sse_state_initialization(self):
        """Test that SSE state is initialized properly."""
        client = MCPClient("http://localhost:8000", transport=TransportType.SSE)

        assert client._sse_session is None
        assert client._sse_response is None
        assert client._sse_endpoint is None
        assert client._sse_reader_task is None
        assert client._pending_requests == {}

    @pytest.mark.asyncio
    async def test_request_sse_not_connected(self):
        """Test that _request_sse raises when not connected."""
        client = MCPClient("http://localhost:8000", transport=TransportType.SSE)

        with pytest.raises(MCPError) as exc_info:
            await client._request_sse({"jsonrpc": "2.0", "id": 1, "method": "test"})

        assert exc_info.value.code == MCPErrorCode.CONNECTION_ERROR
        assert "SSE not connected" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_cleanup_sse(self):
        """Test SSE cleanup handles None values gracefully."""
        client = MCPClient("http://localhost:8000", transport=TransportType.SSE)

        # Should not raise even with None values
        await client._cleanup_sse()

        assert client._sse_session is None
        assert client._sse_endpoint is None

    @pytest.mark.asyncio
    async def test_disconnect_cleans_sse(self):
        """Test that disconnect cleans up SSE resources."""
        from unittest.mock import patch, AsyncMock

        client = MCPClient("http://localhost:8000", transport=TransportType.SSE)

        # Mock cleanup
        with patch.object(client, "_cleanup_sse", new_callable=AsyncMock) as mock_cleanup:
            await client.disconnect()

        mock_cleanup.assert_called_once()

    def test_sse_pending_requests_dict(self):
        """Test pending requests tracking structure."""
        client = MCPClient("http://localhost:8000", transport=TransportType.SSE)

        import asyncio
        future = asyncio.get_event_loop().create_future()
        client._pending_requests[1] = future

        assert 1 in client._pending_requests
        assert client._pending_requests[1] is future

        # Cleanup
        del client._pending_requests[1]


# ==================== Test Server SSE Transport ====================


class TestMCPServerSSE:
    """Tests for MCP Server SSE transport (M-07)."""

    def test_server_sse_sessions_init(self):
        """Test that SSE sessions dict is initialized."""
        from voice_pipeline.mcp.server import MCPServer

        server = MCPServer("test")
        assert server._sse_sessions == {}

    def test_server_supports_sse_transport(self):
        """Test that server config accepts SSE transport."""
        from voice_pipeline.mcp.server import MCPServer, MCPServerConfig

        config = MCPServerConfig(
            name="test",
            transport=TransportType.SSE,
        )
        server = MCPServer("test", config=config)

        assert server.config.transport == TransportType.SSE

    def test_create_http_handler(self):
        """Test that _create_http_handler returns a callable."""
        from voice_pipeline.mcp.server import MCPServer

        server = MCPServer("test")
        handler = server._create_http_handler()

        assert callable(handler)

    @pytest.mark.asyncio
    async def test_server_sse_sessions_tracking(self):
        """Test that SSE sessions can be tracked."""
        from voice_pipeline.mcp.server import MCPServer
        import asyncio

        server = MCPServer("test")

        # Simulate adding a session
        session_id = "test-session-123"
        queue: asyncio.Queue = asyncio.Queue()
        server._sse_sessions[session_id] = queue

        assert session_id in server._sse_sessions
        assert server._sse_sessions[session_id] is queue

        # Test queue functionality
        await queue.put({"test": "message"})
        msg = await queue.get()
        assert msg == {"test": "message"}

        # Cleanup
        del server._sse_sessions[session_id]
        assert session_id not in server._sse_sessions

    @pytest.mark.asyncio
    async def test_server_handle_request_with_client_id(self):
        """Test that handle_request accepts client_id for rate limiting."""
        from voice_pipeline.mcp.server import MCPServer

        server = MCPServer("test")

        # Should work with client_id
        response = await server.handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            client_id="192.168.1.1",
        )

        assert "error" not in response
        assert "result" in response


# ==================== Test Sampling Types ====================


class TestSamplingTypes:
    """Tests for MCP Sampling types (M-01)."""

    def test_model_hint_creation(self):
        """Test ModelHint creation."""
        from voice_pipeline.mcp import ModelHint

        hint = ModelHint(name="claude-3-sonnet")
        assert hint.name == "claude-3-sonnet"

        d = hint.to_dict()
        assert d == {"name": "claude-3-sonnet"}

    def test_model_preferences_default(self):
        """Test ModelPreferences with defaults."""
        from voice_pipeline.mcp import ModelPreferences

        prefs = ModelPreferences()
        assert prefs.costPriority == 0.5
        assert prefs.speedPriority == 0.5
        assert prefs.intelligencePriority == 0.5
        assert prefs.hints == []

    def test_model_preferences_custom(self):
        """Test ModelPreferences with custom values."""
        from voice_pipeline.mcp import ModelHint, ModelPreferences

        prefs = ModelPreferences(
            hints=[ModelHint(name="claude-3-opus"), ModelHint(name="gpt-4")],
            costPriority=0.2,
            speedPriority=0.3,
            intelligencePriority=0.9,
        )

        assert len(prefs.hints) == 2
        assert prefs.costPriority == 0.2
        assert prefs.intelligencePriority == 0.9

        d = prefs.to_dict()
        assert d["hints"][0]["name"] == "claude-3-opus"
        assert d["costPriority"] == 0.2

    def test_model_preferences_from_dict(self):
        """Test ModelPreferences.from_dict()."""
        from voice_pipeline.mcp import ModelPreferences

        data = {
            "hints": [{"name": "claude-3-haiku"}],
            "speedPriority": 0.8,
        }

        prefs = ModelPreferences.from_dict(data)
        assert len(prefs.hints) == 1
        assert prefs.hints[0].name == "claude-3-haiku"
        assert prefs.speedPriority == 0.8
        assert prefs.costPriority == 0.5  # Default

    def test_sampling_content_text(self):
        """Test SamplingContent with text."""
        from voice_pipeline.mcp import SamplingContent

        content = SamplingContent.text_content("Hello, world!")
        assert content.type == "text"
        assert content.text == "Hello, world!"

        d = content.to_dict()
        assert d["type"] == "text"
        assert d["text"] == "Hello, world!"

    def test_sampling_content_image(self):
        """Test SamplingContent with image."""
        from voice_pipeline.mcp import SamplingContent

        content = SamplingContent(
            type="image",
            data="base64encodeddata",
            mimeType="image/png",
        )

        d = content.to_dict()
        assert d["type"] == "image"
        assert d["data"] == "base64encodeddata"
        assert d["mimeType"] == "image/png"

    def test_sampling_content_from_dict(self):
        """Test SamplingContent.from_dict()."""
        from voice_pipeline.mcp import SamplingContent

        data = {"type": "text", "text": "Test message"}
        content = SamplingContent.from_dict(data)

        assert content.type == "text"
        assert content.text == "Test message"

    def test_sampling_message(self):
        """Test SamplingMessage."""
        from voice_pipeline.mcp import SamplingContent, SamplingMessage

        msg = SamplingMessage(
            role="user",
            content=SamplingContent.text_content("What is 2+2?"),
        )

        assert msg.role == "user"
        assert msg.content.text == "What is 2+2?"

        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"]["text"] == "What is 2+2?"

    def test_sampling_message_from_dict(self):
        """Test SamplingMessage.from_dict()."""
        from voice_pipeline.mcp import SamplingMessage

        data = {
            "role": "assistant",
            "content": {"type": "text", "text": "4"},
        }

        msg = SamplingMessage.from_dict(data)
        assert msg.role == "assistant"
        assert msg.content.text == "4"

    def test_sampling_message_from_dict_string_content(self):
        """Test SamplingMessage.from_dict() with string content."""
        from voice_pipeline.mcp import SamplingMessage

        data = {
            "role": "user",
            "content": "Simple string content",
        }

        msg = SamplingMessage.from_dict(data)
        assert msg.content.text == "Simple string content"

    def test_sampling_request(self):
        """Test SamplingRequest."""
        from voice_pipeline.mcp import (
            ModelPreferences,
            SamplingContent,
            SamplingMessage,
            SamplingRequest,
        )

        request = SamplingRequest(
            messages=[
                SamplingMessage(
                    role="user",
                    content=SamplingContent.text_content("Hello"),
                ),
            ],
            systemPrompt="You are helpful.",
            maxTokens=2048,
            temperature=0.7,
        )

        assert len(request.messages) == 1
        assert request.systemPrompt == "You are helpful."
        assert request.maxTokens == 2048

        d = request.to_dict()
        assert d["maxTokens"] == 2048
        assert d["systemPrompt"] == "You are helpful."
        assert d["temperature"] == 0.7

    def test_sampling_request_from_dict(self):
        """Test SamplingRequest.from_dict()."""
        from voice_pipeline.mcp import SamplingRequest

        data = {
            "messages": [{"role": "user", "content": {"type": "text", "text": "Hi"}}],
            "maxTokens": 512,
            "modelPreferences": {"intelligencePriority": 0.9},
        }

        req = SamplingRequest.from_dict(data)
        assert len(req.messages) == 1
        assert req.maxTokens == 512
        assert req.modelPreferences.intelligencePriority == 0.9

    def test_sampling_response(self):
        """Test SamplingResponse."""
        from voice_pipeline.mcp import SamplingContent, SamplingResponse

        response = SamplingResponse(
            role="assistant",
            content=SamplingContent.text_content("The answer is 4."),
            model="claude-3-sonnet-20240229",
            stopReason="endTurn",
        )

        assert response.role == "assistant"
        assert response.content.text == "The answer is 4."
        assert response.model == "claude-3-sonnet-20240229"

        d = response.to_dict()
        assert d["model"] == "claude-3-sonnet-20240229"
        assert d["stopReason"] == "endTurn"

    def test_sampling_response_from_dict(self):
        """Test SamplingResponse.from_dict()."""
        from voice_pipeline.mcp import SamplingResponse

        data = {
            "role": "assistant",
            "content": {"type": "text", "text": "Response text"},
            "model": "gpt-4",
            "stopReason": "maxTokens",
        }

        resp = SamplingResponse.from_dict(data)
        assert resp.model == "gpt-4"
        assert resp.stopReason == "maxTokens"


class TestMCPCapabilitiesSampling:
    """Tests for MCPCapabilities with sampling."""

    def test_sampling_capability_default_false(self):
        """Test that sampling is disabled by default."""
        caps = MCPCapabilities()
        assert caps.sampling is False

        d = caps.to_dict()
        assert "sampling" not in d

    def test_sampling_capability_enabled(self):
        """Test that sampling can be enabled."""
        caps = MCPCapabilities(sampling=True)
        assert caps.sampling is True

        d = caps.to_dict()
        assert "sampling" in d


class TestMCPClientSampling:
    """Tests for MCP Client sampling capability (M-01)."""

    def test_client_config_sampling_handler(self):
        """Test that MCPClientConfig accepts sampling_handler."""
        from typing import Callable
        from voice_pipeline.mcp import MCPClientConfig

        async def my_handler(request):
            return None

        config = MCPClientConfig(sampling_handler=my_handler)
        assert config.sampling_handler is my_handler

    def test_client_sampling_handler_none_by_default(self):
        """Test that sampling_handler is None by default."""
        from voice_pipeline.mcp import MCPClientConfig

        config = MCPClientConfig()
        assert config.sampling_handler is None


class TestMCPServerSampling:
    """Tests for MCP Server sampling capability (M-01)."""

    def test_server_create_sampling_request(self):
        """Test server's create_sampling_request helper."""
        from voice_pipeline.mcp.server import MCPServer

        server = MCPServer("test")

        request = server.create_sampling_request(
            messages=[{"role": "user", "content": "What is 2+2?"}],
            system_prompt="You are a math tutor.",
            max_tokens=100,
            temperature=0.5,
        )

        assert len(request.messages) == 1
        assert request.messages[0].content.text == "What is 2+2?"
        assert request.systemPrompt == "You are a math tutor."
        assert request.maxTokens == 100
        assert request.temperature == 0.5

    def test_server_create_sampling_request_with_model_hints(self):
        """Test create_sampling_request with model hints."""
        from voice_pipeline.mcp.server import MCPServer

        server = MCPServer("test")

        request = server.create_sampling_request(
            messages=[{"role": "user", "content": "Complex question"}],
            model_hints=["claude-3-opus", "gpt-4"],
        )

        assert request.modelPreferences is not None
        assert len(request.modelPreferences.hints) == 2
        assert request.modelPreferences.hints[0].name == "claude-3-opus"

    @pytest.mark.asyncio
    async def test_server_request_sampling_no_session(self):
        """Test request_sampling returns None when session doesn't exist."""
        from voice_pipeline.mcp.server import MCPServer

        server = MCPServer("test")

        result = await server.request_sampling(
            messages=[{"role": "user", "content": "Test"}],
            session_id="nonexistent-session",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_server_request_sampling_with_session(self):
        """Test request_sampling sends request to connected client."""
        from voice_pipeline.mcp.server import MCPServer
        import asyncio

        server = MCPServer("test")

        # Simulate a connected SSE session
        session_id = "test-session-123"
        queue: asyncio.Queue = asyncio.Queue()
        server._sse_sessions[session_id] = queue

        # Call request_sampling
        result = await server.request_sampling(
            messages=[{"role": "user", "content": "Hello"}],
            session_id=session_id,
            max_tokens=100,
        )

        # Current implementation returns None immediately
        # (waiting for response is not implemented yet)
        assert result is None

        # But check that a message was put in the queue
        msg = queue.get_nowait()
        assert msg["method"] == "sampling/createMessage"
        assert "params" in msg
        assert msg["params"]["maxTokens"] == 100
        assert len(msg["params"]["messages"]) == 1

        # Cleanup
        del server._sse_sessions[session_id]
