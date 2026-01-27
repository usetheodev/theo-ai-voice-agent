"""Tests for Voice Tools."""

import pytest

from voice_pipeline.tools import (
    FunctionTool,
    ToolCall,
    ToolExecutor,
    ToolParameter,
    ToolResult,
    VoiceTool,
    create_executor,
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
