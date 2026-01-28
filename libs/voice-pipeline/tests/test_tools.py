"""Tests for Voice Tools."""

import pytest

from voice_pipeline.tools import (
    FunctionTool,
    PermissionCheckResult,
    PermissionLevel,
    PermissionPolicy,
    ToolCall,
    ToolExecutor,
    ToolParameter,
    ToolPermission,
    ToolPermissionChecker,
    ToolResult,
    ToolResultChunk,
    VoiceTool,
    create_executor,
    create_moderate_policy,
    create_permissive_policy,
    create_safe_policy,
    tool,
    voice_tool,
)


class TestToolResult:
    """Tests for ToolResult."""

    def test_success_result(self):
        """Test successful result."""
        result = ToolResult(success=True, output="Hello")
        assert result.success is True
        assert result.output == "Hello"
        assert result.error is None
        assert str(result) == "Hello"

    def test_error_result(self):
        """Test error result."""
        result = ToolResult(success=False, output=None, error="Something went wrong")
        assert result.success is False
        assert result.error == "Something went wrong"
        assert "Error:" in str(result)


class TestToolParameter:
    """Tests for ToolParameter."""

    def test_required_parameter(self):
        """Test required parameter."""
        param = ToolParameter(
            name="location",
            type="string",
            description="City name",
            required=True,
        )
        assert param.name == "location"
        assert param.type == "string"
        assert param.required is True

    def test_optional_parameter(self):
        """Test optional parameter."""
        param = ToolParameter(
            name="unit",
            type="string",
            description="Temperature unit",
            required=False,
            default="celsius",
            enum=["celsius", "fahrenheit"],
        )
        assert param.required is False
        assert param.default == "celsius"
        assert param.enum == ["celsius", "fahrenheit"]


class TestVoiceToolDecorator:
    """Tests for @voice_tool decorator."""

    def test_decorator_without_args(self):
        """Test decorator without arguments."""

        @voice_tool
        def get_time() -> str:
            """Get the current time."""
            return "12:00"

        assert isinstance(get_time, FunctionTool)
        assert get_time.name == "get_time"
        assert "time" in get_time.description.lower()

    def test_decorator_with_args(self):
        """Test decorator with arguments."""

        @voice_tool(
            name="custom_name",
            description="Custom description",
        )
        def my_function() -> str:
            return "result"

        assert my_function.name == "custom_name"
        assert my_function.description == "Custom description"

    def test_decorator_infers_parameters(self):
        """Test that decorator infers parameters from signature."""

        @voice_tool
        def greet(name: str, times: int = 1) -> str:
            return f"Hello, {name}!" * times

        assert len(greet.parameters) == 2

        # Check name parameter
        name_param = greet.parameters[0]
        assert name_param.name == "name"
        assert name_param.type == "string"
        assert name_param.required is True

        # Check times parameter
        times_param = greet.parameters[1]
        assert times_param.name == "times"
        assert times_param.type == "integer"
        assert times_param.required is False

    @pytest.mark.asyncio
    async def test_decorated_function_execution(self):
        """Test executing decorated function."""

        @voice_tool
        def add(a: int, b: int) -> int:
            return a + b

        result = await add.execute(a=2, b=3)
        assert result.success is True
        assert result.output == 5

    @pytest.mark.asyncio
    async def test_decorated_async_function(self):
        """Test decorated async function."""

        @voice_tool
        async def async_greet(name: str) -> str:
            return f"Hello, {name}!"

        result = await async_greet.execute(name="World")
        assert result.success is True
        assert result.output == "Hello, World!"


class TestToolAlias:
    """Tests for @tool decorator alias."""

    def test_tool_alias(self):
        """Test @tool decorator alias."""

        @tool(description="Get a greeting")
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        assert isinstance(greet, FunctionTool)
        assert greet.description == "Get a greeting"


class TestFunctionTool:
    """Tests for FunctionTool."""

    def test_from_function(self):
        """Test creating from function."""

        def my_func(x: int) -> int:
            """Double a number."""
            return x * 2

        tool = FunctionTool.from_function(my_func)
        assert tool.name == "my_func"
        assert "Double" in tool.description

    @pytest.mark.asyncio
    async def test_timeout(self):
        """Test function timeout."""
        import asyncio

        @voice_tool(timeout_seconds=0.1)
        async def slow_function() -> str:
            await asyncio.sleep(1)
            return "done"

        result = await slow_function.execute()
        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Test error handling."""

        @voice_tool
        def failing_function() -> str:
            raise ValueError("Something broke")

        result = await failing_function.execute()
        assert result.success is False
        assert "Something broke" in result.error


class TestToolSchemas:
    """Tests for tool schema generation."""

    def test_openai_schema(self):
        """Test OpenAI schema generation."""

        @voice_tool(
            name="get_weather",
            description="Get weather for a location",
        )
        def get_weather(location: str, unit: str = "celsius") -> str:
            return "sunny"

        schema = get_weather.to_openai_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "get_weather"
        assert "properties" in schema["function"]["parameters"]
        assert "location" in schema["function"]["parameters"]["required"]

    def test_anthropic_schema(self):
        """Test Anthropic schema generation."""

        @voice_tool(name="search")
        def search(query: str) -> str:
            return "results"

        schema = search.to_anthropic_schema()

        assert schema["name"] == "search"
        assert "input_schema" in schema
        assert "query" in schema["input_schema"]["properties"]


class TestToolCall:
    """Tests for ToolCall."""

    def test_from_openai(self):
        """Test creating from OpenAI format."""
        openai_call = {
            "id": "call_123",
            "function": {
                "name": "get_weather",
                "arguments": '{"location": "New York"}',
            },
        }

        call = ToolCall.from_openai(openai_call)
        assert call.id == "call_123"
        assert call.name == "get_weather"
        assert call.arguments["location"] == "New York"

    def test_from_openai_with_dict_arguments(self):
        """Test creating from format where arguments is already a dict (Ollama format)."""
        # Ollama and some other providers return arguments as dict, not JSON string
        ollama_call = {
            "id": "call_456",
            "function": {
                "name": "calculate",
                "arguments": {"expression": "2 + 2", "precision": 2},  # Dict, not string
            },
        }

        call = ToolCall.from_openai(ollama_call)
        assert call.id == "call_456"
        assert call.name == "calculate"
        assert call.arguments["expression"] == "2 + 2"
        assert call.arguments["precision"] == 2

    def test_from_openai_with_empty_arguments(self):
        """Test creating from call with no arguments."""
        call_data = {
            "id": "call_789",
            "function": {
                "name": "get_time",
                # No arguments field
            },
        }

        call = ToolCall.from_openai(call_data)
        assert call.id == "call_789"
        assert call.name == "get_time"
        assert call.arguments == {}

    def test_from_openai_flat_format(self):
        """Test creating from flat format (no nested function object)."""
        # Some providers use flat format
        flat_call = {
            "id": "call_flat",
            "name": "search",
            "arguments": '{"query": "test"}',
        }

        call = ToolCall.from_openai(flat_call)
        assert call.id == "call_flat"
        assert call.name == "search"
        assert call.arguments["query"] == "test"

    def test_from_anthropic(self):
        """Test creating from Anthropic format."""
        anthropic_block = {
            "type": "tool_use",
            "id": "toolu_123",
            "name": "get_weather",
            "input": {"location": "New York"},
        }

        call = ToolCall.from_anthropic(anthropic_block)
        assert call.id == "toolu_123"
        assert call.name == "get_weather"
        assert call.arguments["location"] == "New York"


class TestToolExecutor:
    """Tests for ToolExecutor."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """Test basic tool execution."""

        @voice_tool
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        executor = ToolExecutor(tools=[greet])
        result = await executor.execute("greet", {"name": "World"})

        assert result.success is True
        assert result.output == "Hello, World!"

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """Test executing unknown tool."""
        executor = ToolExecutor()
        result = await executor.execute("nonexistent", {})

        assert result.success is False
        assert "not found" in result.error.lower()

    def test_register_unregister(self):
        """Test registering and unregistering tools."""

        @voice_tool
        def my_tool() -> str:
            return "done"

        executor = ToolExecutor()
        executor.register(my_tool)
        assert "my_tool" in executor.list_tools()

        executor.unregister("my_tool")
        assert "my_tool" not in executor.list_tools()

    def test_register_duplicate_raises(self):
        """Test that registering a duplicate tool raises ValueError."""

        @voice_tool
        def dup_tool() -> str:
            return "v1"

        executor = ToolExecutor()
        executor.register(dup_tool)

        with pytest.raises(ValueError, match="already registered"):
            executor.register(dup_tool)

    def test_register_duplicate_with_overwrite(self):
        """Test that overwrite=True allows replacing a tool."""

        @voice_tool
        def dup_tool() -> str:
            return "v1"

        @voice_tool(name="dup_tool")
        def dup_tool_v2() -> str:
            return "v2"

        executor = ToolExecutor()
        executor.register(dup_tool)
        executor.register(dup_tool_v2, overwrite=True)

        assert "dup_tool" in executor.list_tools()
        assert executor.get("dup_tool") is dup_tool_v2

    @pytest.mark.asyncio
    async def test_execute_call(self):
        """Test executing ToolCall."""

        @voice_tool
        def add(a: int, b: int) -> int:
            return a + b

        executor = ToolExecutor(tools=[add])
        call = ToolCall(id="1", name="add", arguments={"a": 1, "b": 2})

        result = await executor.execute_call(call)
        assert result.output == 3

    @pytest.mark.asyncio
    async def test_execute_many_parallel(self):
        """Test parallel execution of multiple calls."""

        @voice_tool
        def double(x: int) -> int:
            return x * 2

        executor = ToolExecutor(tools=[double])
        calls = [
            ToolCall(id="1", name="double", arguments={"x": 1}),
            ToolCall(id="2", name="double", arguments={"x": 2}),
            ToolCall(id="3", name="double", arguments={"x": 3}),
        ]

        results = await executor.execute_many(calls, parallel=True)
        assert [r.output for r in results] == [2, 4, 6]

    def test_to_openai_tools(self):
        """Test generating OpenAI tools list."""

        @voice_tool
        def tool1() -> str:
            return "1"

        @voice_tool
        def tool2() -> str:
            return "2"

        executor = ToolExecutor(tools=[tool1, tool2])
        tools = executor.to_openai_tools()

        assert len(tools) == 2
        assert all(t["type"] == "function" for t in tools)

    def test_to_anthropic_tools(self):
        """Test generating Anthropic tools list."""

        @voice_tool
        def my_tool() -> str:
            return "result"

        executor = ToolExecutor(tools=[my_tool])
        tools = executor.to_anthropic_tools()

        assert len(tools) == 1
        assert "input_schema" in tools[0]

    def test_format_result_for_llm(self):
        """Test formatting result for LLM."""

        @voice_tool
        def my_tool() -> str:
            return "result"

        executor = ToolExecutor(tools=[my_tool])
        call = ToolCall(id="1", name="my_tool", arguments={})
        result = ToolResult(success=True, output="done")

        # OpenAI format
        openai_msg = executor.format_result_for_llm(call, result, format="openai")
        assert openai_msg["role"] == "tool"
        assert openai_msg["tool_call_id"] == "1"

        # Anthropic format
        anthropic_msg = executor.format_result_for_llm(call, result, format="anthropic")
        assert anthropic_msg["type"] == "tool_result"
        assert anthropic_msg["is_error"] is False


class TestExecuteManyErrorHandling:
    """Tests for error handling in execute_many (TASK-2.3)."""

    @pytest.mark.asyncio
    async def test_execute_many_captures_traceback(self):
        """Test that execute_many captures traceback on failure."""

        @voice_tool
        def failing_tool() -> str:
            def inner_function():
                raise ValueError("Something went wrong")
            inner_function()

        executor = ToolExecutor(tools=[failing_tool])
        calls = [ToolCall(id="1", name="failing_tool", arguments={})]

        results = await executor.execute_many(calls, parallel=True)

        assert len(results) == 1
        assert results[0].success is False
        # Error contains the exception message
        assert "Something went wrong" in results[0].error

        # Check traceback is in metadata
        assert results[0].metadata is not None
        assert "traceback" in results[0].metadata
        assert "exception_type" in results[0].metadata
        assert results[0].metadata["exception_type"] == "ValueError"

        # Traceback should contain function names and full info
        tb = results[0].metadata["traceback"]
        assert "inner_function" in tb
        assert "Something went wrong" in tb
        assert "ValueError" in tb

    @pytest.mark.asyncio
    async def test_execute_many_logs_errors(self, caplog):
        """Test that execute_many logs errors with traceback."""
        import logging

        @voice_tool
        def logging_test_tool() -> str:
            raise RuntimeError("Test error for logging")

        executor = ToolExecutor(tools=[logging_test_tool])
        calls = [ToolCall(id="1", name="logging_test_tool", arguments={})]

        with caplog.at_level(logging.ERROR):
            results = await executor.execute_many(calls, parallel=True)

        assert len(results) == 1
        assert results[0].success is False

        # Check that error was logged
        assert any("logging_test_tool" in record.message for record in caplog.records)
        assert any("RuntimeError" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_execute_many_mixed_success_failure(self):
        """Test that successful and failed tools both return correctly."""

        @voice_tool
        def success_tool() -> str:
            return "success"

        @voice_tool
        def failure_tool() -> str:
            raise Exception("Intentional failure")

        executor = ToolExecutor(tools=[success_tool, failure_tool])
        calls = [
            ToolCall(id="1", name="success_tool", arguments={}),
            ToolCall(id="2", name="failure_tool", arguments={}),
            ToolCall(id="3", name="success_tool", arguments={}),
        ]

        results = await executor.execute_many(calls, parallel=True)

        assert len(results) == 3
        assert results[0].success is True
        assert results[0].output == "success"
        assert results[1].success is False
        assert "traceback" in results[1].metadata
        assert results[2].success is True
        assert results[2].output == "success"


class TestExecuteManyCancel:
    """Tests for execute_many with cancel_event (I-02)."""

    @pytest.mark.asyncio
    async def test_cancel_event_cancels_slow_parallel_tools(self):
        """Test that cancel_event cancels slow parallel tools."""
        import asyncio

        @voice_tool
        async def slow_tool() -> str:
            await asyncio.sleep(10)
            return "done"

        @voice_tool
        async def fast_tool() -> str:
            return "fast"

        executor = ToolExecutor(tools=[slow_tool, fast_tool])

        cancel_event = asyncio.Event()

        calls = [
            ToolCall(id="1", name="slow_tool", arguments={}),
            ToolCall(id="2", name="fast_tool", arguments={}),
        ]

        # Set cancel after a short delay
        async def set_cancel():
            await asyncio.sleep(0.1)
            cancel_event.set()

        cancel_task = asyncio.create_task(set_cancel())

        results = await executor.execute_many(
            calls, parallel=True, cancel_event=cancel_event
        )

        await cancel_task

        # fast_tool should succeed, slow_tool should be cancelled
        assert len(results) == 2
        # At least one result should have "Cancelled" error
        cancelled = [r for r in results if not r.success and r.error == "Cancelled"]
        assert len(cancelled) >= 1

    @pytest.mark.asyncio
    async def test_cancel_event_sequential(self):
        """Test that cancel_event stops sequential execution."""
        import asyncio

        call_count = 0

        @voice_tool
        async def counting_tool() -> str:
            nonlocal call_count
            call_count += 1
            return f"call {call_count}"

        executor = ToolExecutor(tools=[counting_tool])

        cancel_event = asyncio.Event()
        cancel_event.set()  # Already cancelled

        calls = [
            ToolCall(id="1", name="counting_tool", arguments={}),
            ToolCall(id="2", name="counting_tool", arguments={}),
        ]

        results = await executor.execute_many(
            calls, parallel=False, cancel_event=cancel_event
        )

        # All calls should be cancelled since event was set before start
        assert all(not r.success for r in results)
        assert all(r.error == "Cancelled" for r in results)
        assert call_count == 0

    @pytest.mark.asyncio
    async def test_gather_return_exceptions(self):
        """Test that parallel execution without cancel handles exceptions gracefully."""

        @voice_tool
        def good_tool() -> str:
            return "ok"

        @voice_tool
        def bad_tool() -> str:
            raise RuntimeError("boom")

        executor = ToolExecutor(tools=[good_tool, bad_tool])

        calls = [
            ToolCall(id="1", name="good_tool", arguments={}),
            ToolCall(id="2", name="bad_tool", arguments={}),
        ]

        results = await executor.execute_many(calls, parallel=True)

        assert len(results) == 2
        assert results[0].success is True
        assert results[0].output == "ok"
        # bad_tool should have error but not crash the entire gather
        assert results[1].success is False


class TestCreateExecutor:
    """Tests for create_executor helper."""

    def test_create_executor(self):
        """Test create_executor helper."""

        @voice_tool
        def tool1() -> str:
            return "1"

        @voice_tool
        def tool2() -> str:
            return "2"

        executor = create_executor(tool1, tool2)
        assert len(executor.list_tools()) == 2


class TestBuiltinTools:
    """Tests for builtin tools."""

    @pytest.mark.asyncio
    async def test_datetime_tools(self):
        """Test datetime builtin tools."""
        from voice_pipeline.tools.builtin import get_current_time, get_current_date

        time_result = await get_current_time.execute()
        assert time_result.success is True
        assert ":" in time_result.output  # HH:MM format

        date_result = await get_current_date.execute()
        assert date_result.success is True
        assert "-" in date_result.output  # YYYY-MM-DD format

    @pytest.mark.asyncio
    async def test_datetime_tools_collection(self):
        """Test DATETIME_TOOLS collection."""
        from voice_pipeline.tools.builtin import DATETIME_TOOLS

        executor = ToolExecutor(tools=DATETIME_TOOLS)

        # Should have multiple datetime tools
        assert len(executor.list_tools()) >= 5


# ==================== Test Tool Result Streaming (M-05) ====================


class TestToolResultChunk:
    """Tests for ToolResultChunk."""

    def test_basic_chunk(self):
        """Test basic chunk creation."""
        from voice_pipeline.tools import ToolResultChunk

        chunk = ToolResultChunk(text="Processing...", is_final=False)
        assert chunk.text == "Processing..."
        assert chunk.is_final is False
        assert chunk.metadata == {}

    def test_final_chunk(self):
        """Test final chunk."""
        from voice_pipeline.tools import ToolResultChunk

        chunk = ToolResultChunk(
            text="Done!",
            is_final=True,
            metadata={"status": "success"},
        )
        assert chunk.is_final is True
        assert chunk.metadata["status"] == "success"


class TestToolStreaming:
    """Tests for tool streaming support (M-05)."""

    @pytest.mark.asyncio
    async def test_voicetool_execute_stream_default(self):
        """Test default execute_stream falls back to execute."""
        from voice_pipeline.tools import ToolResultChunk

        @voice_tool
        def simple_tool() -> str:
            """A simple tool."""
            return "Hello, world!"

        chunks = []
        async for chunk in simple_tool.execute_stream():
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].text == "Hello, world!"
        assert chunks[0].is_final is True

    @pytest.mark.asyncio
    async def test_function_tool_with_async_generator(self):
        """Test FunctionTool with async generator function."""
        from voice_pipeline.tools import ToolResultChunk

        async def streaming_search(query: str):
            """Search that streams results."""
            yield "Searching..."
            yield f"Found results for: {query}"
            yield "Done!"

        tool = FunctionTool.from_function(
            streaming_search,
            name="streaming_search",
            description="Search with streaming",
        )

        assert tool.supports_streaming() is True

        chunks = []
        async for chunk in tool.execute_stream(query="test"):
            chunks.append(chunk)

        # Should have 3 content chunks + 1 final chunk
        assert len(chunks) == 4
        assert chunks[0].text == "Searching..."
        assert chunks[1].text == "Found results for: test"
        assert chunks[2].text == "Done!"
        assert chunks[3].is_final is True

    @pytest.mark.asyncio
    async def test_function_tool_streaming_with_result_chunks(self):
        """Test async generator that yields ToolResultChunk directly."""
        from voice_pipeline.tools import ToolResultChunk

        async def tool_with_chunks():
            """Tool that yields ToolResultChunk."""
            yield ToolResultChunk(text="Step 1 complete")
            yield ToolResultChunk(text="Step 2 complete")
            yield ToolResultChunk(text="All done!", is_final=True)

        tool = FunctionTool.from_function(
            tool_with_chunks,
            name="chunked_tool",
            description="Tool with explicit chunks",
        )

        chunks = []
        async for chunk in tool.execute_stream():
            chunks.append(chunk)

        # 3 explicit chunks + 1 auto final chunk
        assert len(chunks) >= 3
        assert chunks[0].text == "Step 1 complete"
        assert chunks[1].text == "Step 2 complete"
        assert chunks[2].text == "All done!"

    @pytest.mark.asyncio
    async def test_non_streaming_tool_reports_no_support(self):
        """Test that non-streaming tools report no streaming support."""

        @voice_tool
        def regular_tool() -> str:
            """A regular tool."""
            return "result"

        assert regular_tool.supports_streaming() is False

    @pytest.mark.asyncio
    async def test_voicetool_execute_stream_on_error(self):
        """Test execute_stream handles errors gracefully."""
        from voice_pipeline.tools import ToolResultChunk

        @voice_tool
        def failing_tool() -> str:
            """A tool that fails."""
            raise ValueError("Intentional failure")

        chunks = []
        async for chunk in failing_tool.execute_stream():
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].is_final is True
        assert "Error" in chunks[0].text

    @pytest.mark.asyncio
    async def test_streaming_tool_error_handling(self):
        """Test streaming tool handles errors during iteration."""
        from voice_pipeline.tools import ToolResultChunk

        async def failing_generator():
            """Generator that fails mid-stream."""
            yield "Starting..."
            raise RuntimeError("Mid-stream failure")

        tool = FunctionTool.from_function(
            failing_generator,
            name="failing_gen",
            description="Fails during streaming",
        )

        chunks = []
        async for chunk in tool.execute_stream():
            chunks.append(chunk)

        # Should have the first chunk + error chunk
        assert len(chunks) >= 1
        # Last chunk should be error
        assert chunks[-1].is_final is True
        assert "Error" in chunks[-1].text or chunks[-1].metadata.get("error")


# ==================== Test Tool Permissions (M-02) ====================


class TestPermissionLevel:
    """Tests for PermissionLevel enum."""

    def test_level_ordering(self):
        """Test that levels are ordered by danger."""
        assert PermissionLevel.SAFE < PermissionLevel.MODERATE
        assert PermissionLevel.MODERATE < PermissionLevel.SENSITIVE
        assert PermissionLevel.SENSITIVE < PermissionLevel.DANGEROUS

    def test_level_values(self):
        """Test level integer values."""
        assert int(PermissionLevel.SAFE) == 0
        assert int(PermissionLevel.DANGEROUS) == 3


class TestToolPermission:
    """Tests for ToolPermission."""

    def test_basic_permission(self):
        """Test basic permission creation."""
        perm = ToolPermission(
            tool_name="test_tool",
            level=PermissionLevel.MODERATE,
        )

        assert perm.tool_name == "test_tool"
        assert perm.level == PermissionLevel.MODERATE

    def test_validate_args_allowed(self):
        """Test validation with allowed args only."""
        perm = ToolPermission(
            tool_name="test",
            allowed_args={"a", "b"},
        )

        result = perm.validate_args({"a": 1, "b": 2})
        assert result.allowed is True

        result = perm.validate_args({"a": 1, "c": 3})
        assert result.allowed is False
        assert "not allowed" in result.reason

    def test_validate_args_blocked(self):
        """Test validation with blocked args."""
        perm = ToolPermission(
            tool_name="test",
            blocked_args={"password", "secret"},
        )

        result = perm.validate_args({"name": "test"})
        assert result.allowed is True

        result = perm.validate_args({"name": "test", "password": "123"})
        assert result.allowed is False
        assert "Blocked" in result.reason

    def test_validate_args_custom_validator(self):
        """Test custom argument validators."""
        perm = ToolPermission(
            tool_name="test",
            validators={
                "count": lambda x: x > 0 and x < 100,
            },
        )

        result = perm.validate_args({"count": 50})
        assert result.allowed is True

        result = perm.validate_args({"count": 200})
        assert result.allowed is False


class TestPermissionPolicy:
    """Tests for PermissionPolicy."""

    def test_default_policy(self):
        """Test default policy values."""
        policy = PermissionPolicy()

        assert policy.default_level == PermissionLevel.SAFE
        assert policy.max_allowed_level == PermissionLevel.DANGEROUS
        assert len(policy.blocked_tools) == 0

    def test_policy_with_blocklist(self):
        """Test policy with blocked tools."""
        policy = PermissionPolicy(
            blocked_tools={"dangerous_tool", "evil_tool"},
        )

        assert "dangerous_tool" in policy.blocked_tools
        perm = policy.get_tool_permission("dangerous_tool")
        assert perm.tool_name == "dangerous_tool"

    def test_policy_with_specific_permissions(self):
        """Test policy with tool-specific permissions."""
        policy = PermissionPolicy(
            tool_permissions={
                "admin_tool": ToolPermission(
                    tool_name="admin_tool",
                    level=PermissionLevel.DANGEROUS,
                    max_calls_per_session=1,
                ),
            },
        )

        perm = policy.get_tool_permission("admin_tool")
        assert perm.level == PermissionLevel.DANGEROUS
        assert perm.max_calls_per_session == 1

        # Unknown tool gets default
        perm = policy.get_tool_permission("other_tool")
        assert perm.level == PermissionLevel.SAFE


class TestToolPermissionChecker:
    """Tests for ToolPermissionChecker."""

    def test_check_allowed(self):
        """Test checking an allowed tool."""
        policy = PermissionPolicy()
        checker = ToolPermissionChecker(policy)

        result = checker.check("any_tool", {"arg": "value"})
        assert result.allowed is True

    def test_check_blocked_tool(self):
        """Test checking a blocked tool."""
        policy = PermissionPolicy(blocked_tools={"blocked_tool"})
        checker = ToolPermissionChecker(policy)

        result = checker.check("blocked_tool", {})
        assert result.allowed is False
        assert "blocked by policy" in result.reason

    def test_check_allowlist_mode(self):
        """Test allowlist mode (only specific tools allowed)."""
        policy = PermissionPolicy(
            allowed_tools={"tool_a", "tool_b"},
        )
        checker = ToolPermissionChecker(policy)

        result = checker.check("tool_a", {})
        assert result.allowed is True

        result = checker.check("tool_c", {})
        assert result.allowed is False
        assert "not in allowed list" in result.reason

    def test_check_exceeds_max_level(self):
        """Test that tools exceeding max level are blocked."""
        policy = PermissionPolicy(
            max_allowed_level=PermissionLevel.MODERATE,
        )
        checker = ToolPermissionChecker(policy)

        # Pass the tool level directly
        result = checker.check(
            "sensitive_tool", {},
            tool_level=PermissionLevel.SENSITIVE,
        )
        assert result.allowed is False
        assert "exceeds max allowed" in result.reason

    def test_check_requires_confirmation(self):
        """Test that certain levels require confirmation."""
        policy = PermissionPolicy(
            require_confirmation_for={PermissionLevel.SENSITIVE},
        )
        checker = ToolPermissionChecker(policy)

        result = checker.check(
            "sensitive_tool", {},
            tool_level=PermissionLevel.SENSITIVE,
        )
        assert result.allowed is True
        assert result.requires_confirmation is True

    def test_call_rate_limiting(self):
        """Test call rate limiting per session."""
        policy = PermissionPolicy(
            tool_permissions={
                "limited_tool": ToolPermission(
                    tool_name="limited_tool",
                    max_calls_per_session=2,
                ),
            },
        )
        checker = ToolPermissionChecker(policy)

        # First two calls should work
        result = checker.check("limited_tool", {})
        assert result.allowed is True
        checker.record_call("limited_tool")

        result = checker.check("limited_tool", {})
        assert result.allowed is True
        checker.record_call("limited_tool")

        # Third call should be blocked
        result = checker.check("limited_tool", {})
        assert result.allowed is False
        assert "max calls" in result.reason

    def test_reset_session(self):
        """Test resetting session clears call counts."""
        policy = PermissionPolicy(
            tool_permissions={
                "limited_tool": ToolPermission(
                    tool_name="limited_tool",
                    max_calls_per_session=1,
                ),
            },
        )
        checker = ToolPermissionChecker(policy)

        checker.record_call("limited_tool")
        result = checker.check("limited_tool", {})
        assert result.allowed is False

        checker.reset_session()
        result = checker.check("limited_tool", {})
        assert result.allowed is True


class TestPolicyFactories:
    """Tests for policy factory functions."""

    def test_create_safe_policy(self):
        """Test safe policy creation."""
        policy = create_safe_policy()

        assert policy.max_allowed_level == PermissionLevel.SAFE
        assert policy.default_level == PermissionLevel.SAFE

    def test_create_moderate_policy(self):
        """Test moderate policy creation."""
        policy = create_moderate_policy()

        assert policy.max_allowed_level == PermissionLevel.SENSITIVE
        assert PermissionLevel.SENSITIVE in policy.require_confirmation_for

    def test_create_permissive_policy(self):
        """Test permissive policy creation."""
        policy = create_permissive_policy()

        assert policy.max_allowed_level == PermissionLevel.DANGEROUS
        assert PermissionLevel.DANGEROUS in policy.require_confirmation_for


class TestToolExecutorWithPermissions:
    """Tests for ToolExecutor with permission checking."""

    @pytest.mark.asyncio
    async def test_executor_without_permission_checker(self):
        """Test executor works normally without permission checker."""
        @voice_tool
        def simple_tool() -> str:
            """A simple tool."""
            return "result"

        executor = ToolExecutor(tools=[simple_tool])
        result = await executor.execute("simple_tool", {})

        assert result.success is True
        assert result.output == "result"

    @pytest.mark.asyncio
    async def test_executor_with_permission_checker_allowed(self):
        """Test executor allows permitted tools."""
        @voice_tool
        def allowed_tool() -> str:
            """An allowed tool."""
            return "allowed"

        policy = PermissionPolicy()
        checker = ToolPermissionChecker(policy)
        executor = ToolExecutor(
            tools=[allowed_tool],
            permission_checker=checker,
        )

        result = await executor.execute("allowed_tool", {})
        assert result.success is True
        assert result.output == "allowed"

    @pytest.mark.asyncio
    async def test_executor_with_permission_checker_blocked(self):
        """Test executor blocks denied tools."""
        @voice_tool
        def blocked_tool() -> str:
            """A blocked tool."""
            return "should not run"

        policy = PermissionPolicy(blocked_tools={"blocked_tool"})
        checker = ToolPermissionChecker(policy)
        executor = ToolExecutor(
            tools=[blocked_tool],
            permission_checker=checker,
        )

        result = await executor.execute("blocked_tool", {})
        assert result.success is False
        assert "Permission denied" in result.error
        assert result.metadata.get("permission_denied") is True

    @pytest.mark.asyncio
    async def test_executor_skip_permission_check(self):
        """Test that skip_permission_check bypasses checking."""
        @voice_tool
        def blocked_tool() -> str:
            """A blocked tool."""
            return "bypassed"

        policy = PermissionPolicy(blocked_tools={"blocked_tool"})
        checker = ToolPermissionChecker(policy)
        executor = ToolExecutor(
            tools=[blocked_tool],
            permission_checker=checker,
        )

        result = await executor.execute(
            "blocked_tool", {},
            skip_permission_check=True,
        )
        assert result.success is True
        assert result.output == "bypassed"

    @pytest.mark.asyncio
    async def test_tool_with_permission_level(self):
        """Test tool with explicit permission level."""
        tool = FunctionTool.from_function(
            lambda: "danger!",
            name="dangerous_tool",
            description="A dangerous tool",
            permission_level=PermissionLevel.DANGEROUS,
        )

        policy = PermissionPolicy(
            max_allowed_level=PermissionLevel.MODERATE,
        )
        checker = ToolPermissionChecker(policy)
        executor = ToolExecutor(
            tools=[tool],
            permission_checker=checker,
        )

        result = await executor.execute("dangerous_tool", {})
        assert result.success is False
        assert "exceeds max allowed" in result.error
