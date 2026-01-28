"""Tests for agent callback integration (Sprint 3)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from voice_pipeline.agents.loop import AgentLoop
from voice_pipeline.agents.base import VoiceAgent
from voice_pipeline.callbacks.base import (
    CallbackManager,
    RunContext,
    VoiceCallbackHandler,
)


class TestVoiceCallbackHandlerAgentEvents:
    """Tests for agent events in VoiceCallbackHandler."""

    def test_agent_event_methods_exist(self):
        """Verify all agent event methods exist in base class."""
        handler = VoiceCallbackHandler()

        # Check all agent methods exist
        assert hasattr(handler, "on_agent_start")
        assert hasattr(handler, "on_agent_iteration")
        assert hasattr(handler, "on_agent_thinking")
        assert hasattr(handler, "on_agent_tool_start")
        assert hasattr(handler, "on_agent_tool_end")
        assert hasattr(handler, "on_agent_tool_error")
        assert hasattr(handler, "on_agent_response")
        assert hasattr(handler, "on_agent_end")
        assert hasattr(handler, "on_agent_error")


class TestCallbackManagerAgentEvents:
    """Tests for agent events in CallbackManager."""

    @pytest.mark.asyncio
    async def test_dispatch_agent_start(self):
        """Test dispatching agent_start event."""
        handler = AsyncMock(spec=VoiceCallbackHandler)
        manager = CallbackManager([handler], run_in_background=False)

        ctx = manager.create_context(run_name="test")
        await manager.on_agent_start(ctx, "Hello", ["tool1", "tool2"])

        handler.on_agent_start.assert_called_once_with(
            ctx, "Hello", ["tool1", "tool2"]
        )

    @pytest.mark.asyncio
    async def test_dispatch_agent_iteration(self):
        """Test dispatching agent_iteration event."""
        handler = AsyncMock(spec=VoiceCallbackHandler)
        manager = CallbackManager([handler], run_in_background=False)

        ctx = manager.create_context()
        await manager.on_agent_iteration(ctx, 1, 10)

        handler.on_agent_iteration.assert_called_once_with(ctx, 1, 10)

    @pytest.mark.asyncio
    async def test_dispatch_agent_tool_events(self):
        """Test dispatching tool start/end events."""
        handler = AsyncMock(spec=VoiceCallbackHandler)
        manager = CallbackManager([handler], run_in_background=False)

        ctx = manager.create_context()

        await manager.on_agent_tool_start(ctx, "get_weather", {"city": "NYC"})
        handler.on_agent_tool_start.assert_called_once_with(
            ctx, "get_weather", {"city": "NYC"}
        )

        await manager.on_agent_tool_end(ctx, "get_weather", "Sunny", True, 100.5)
        handler.on_agent_tool_end.assert_called_once_with(
            ctx, "get_weather", "Sunny", True, 100.5
        )

    @pytest.mark.asyncio
    async def test_dispatch_agent_end(self):
        """Test dispatching agent_end event."""
        handler = AsyncMock(spec=VoiceCallbackHandler)
        manager = CallbackManager([handler], run_in_background=False)

        ctx = manager.create_context()
        await manager.on_agent_end(ctx, "Final response", 3, 500.0)

        handler.on_agent_end.assert_called_once_with(
            ctx, "Final response", 3, 500.0
        )

    @pytest.mark.asyncio
    async def test_dispatch_agent_error(self):
        """Test dispatching agent_error event."""
        handler = AsyncMock(spec=VoiceCallbackHandler)
        manager = CallbackManager([handler], run_in_background=False)

        ctx = manager.create_context()
        error = ValueError("Test error")
        await manager.on_agent_error(ctx, error)

        handler.on_agent_error.assert_called_once_with(ctx, error)


class TestAgentLoopCallbackIntegration:
    """Tests for AgentLoop callback integration."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = AsyncMock()
        llm.supports_tools.return_value = False

        async def mock_generate(*args, **kwargs):
            return "Hello, world!"

        llm.generate = mock_generate
        return llm

    @pytest.fixture
    def callback_handler(self):
        """Create a mock callback handler."""
        return AsyncMock(spec=VoiceCallbackHandler)

    @pytest.mark.asyncio
    async def test_loop_emits_agent_start(self, mock_llm, callback_handler):
        """Test that run() emits on_agent_start callback."""
        manager = CallbackManager([callback_handler], run_in_background=False)
        loop = AgentLoop(llm=mock_llm, callbacks=manager)

        await loop.run("Hello")

        callback_handler.on_agent_start.assert_called_once()
        call_args = callback_handler.on_agent_start.call_args
        assert call_args[0][1] == "Hello"  # input
        assert isinstance(call_args[0][2], list)  # tools list

    @pytest.mark.asyncio
    async def test_loop_emits_agent_iteration(self, mock_llm, callback_handler):
        """Test that run() emits on_agent_iteration callback."""
        manager = CallbackManager([callback_handler], run_in_background=False)
        loop = AgentLoop(llm=mock_llm, callbacks=manager)

        await loop.run("Hello")

        callback_handler.on_agent_iteration.assert_called()
        # Should be called with iteration=1
        call_args = callback_handler.on_agent_iteration.call_args
        assert call_args[0][1] == 1  # iteration

    @pytest.mark.asyncio
    async def test_loop_emits_agent_end(self, mock_llm, callback_handler):
        """Test that run() emits on_agent_end callback."""
        manager = CallbackManager([callback_handler], run_in_background=False)
        loop = AgentLoop(llm=mock_llm, callbacks=manager)

        result = await loop.run("Hello")

        callback_handler.on_agent_end.assert_called_once()
        call_args = callback_handler.on_agent_end.call_args
        assert call_args[0][1] == result  # response
        assert isinstance(call_args[0][3], float)  # duration_ms

    @pytest.mark.asyncio
    async def test_loop_emits_tool_callbacks(self, callback_handler):
        """Test that run() emits tool callbacks when tools are used."""
        from voice_pipeline.tools.base import VoiceTool, ToolResult

        class MockTool(VoiceTool):
            name = "mock_tool"
            description = "A mock tool"
            parameters = []

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True, output="Done")

        llm = AsyncMock()
        llm.supports_tools.return_value = True

        call_count = 0

        async def mock_generate_with_tools(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock(
                    content="",
                    has_tool_calls=True,
                    tool_calls=[{
                        "id": "call_1",
                        "function": {"name": "mock_tool", "arguments": "{}"}
                    }]
                )
            return MagicMock(
                content="Done!",
                has_tool_calls=False,
                tool_calls=[]
            )

        llm.generate_with_tools = mock_generate_with_tools

        manager = CallbackManager([callback_handler], run_in_background=False)
        loop = AgentLoop(llm=llm, tools=[MockTool()], callbacks=manager)

        await loop.run("Test")

        # Should have called tool_start
        callback_handler.on_agent_tool_start.assert_called()

        # Should have called tool_end
        callback_handler.on_agent_tool_end.assert_called()


class TestVoiceAgentCallbacks:
    """Tests for VoiceAgent callback support."""

    def test_agent_accepts_callbacks(self):
        """Test that VoiceAgent accepts callbacks parameter."""
        llm = AsyncMock()
        llm.supports_tools.return_value = False

        manager = CallbackManager([])
        agent = VoiceAgent(llm=llm, callbacks=manager)

        assert agent.callbacks is manager
        assert agent._loop.callbacks is manager

    @pytest.mark.asyncio
    async def test_agent_propagates_callbacks(self):
        """Test that VoiceAgent propagates callbacks to loop."""
        llm = AsyncMock()
        llm.supports_tools.return_value = False

        async def mock_generate(*args, **kwargs):
            return "Hi!"

        llm.generate = mock_generate

        handler = AsyncMock(spec=VoiceCallbackHandler)
        manager = CallbackManager([handler], run_in_background=False)

        agent = VoiceAgent(llm=llm, callbacks=manager)
        await agent.ainvoke("Hello")

        # Verify callbacks were called
        handler.on_agent_start.assert_called_once()
        handler.on_agent_end.assert_called_once()


class TestVoiceAgentBuilderCallbacks:
    """Tests for VoiceAgentBuilder callback support."""

    def test_builder_accepts_handlers_list(self):
        """Test that builder accepts list of handlers."""
        from voice_pipeline.agents.base import VoiceAgentBuilder
        from voice_pipeline.callbacks import LoggingHandler

        llm = AsyncMock()
        llm.supports_tools.return_value = False

        builder = VoiceAgentBuilder()
        builder._llm = llm

        # Should accept handlers list
        result = builder.callbacks([LoggingHandler()])
        assert result is builder  # Fluent interface
        assert builder._callbacks is not None

    def test_builder_accepts_callback_manager(self):
        """Test that builder accepts CallbackManager."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        llm = AsyncMock()
        llm.supports_tools.return_value = False

        handler = AsyncMock(spec=VoiceCallbackHandler)
        manager = CallbackManager([handler])

        builder = VoiceAgentBuilder()
        builder._llm = llm
        builder.callbacks(manager=manager)

        assert builder._callbacks is manager

    def test_builder_propagates_callbacks_to_agent(self):
        """Test that build() passes callbacks to VoiceAgent."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        llm = AsyncMock()
        llm.supports_tools.return_value = False

        handler = AsyncMock(spec=VoiceCallbackHandler)
        manager = CallbackManager([handler])

        builder = VoiceAgentBuilder()
        builder._llm = llm
        builder.callbacks(manager=manager)

        agent = builder.build()

        assert agent.callbacks is manager
        assert agent._loop.callbacks is manager


class TestCustomCallbackHandler:
    """Tests for custom callback handler implementation."""

    @pytest.mark.asyncio
    async def test_custom_handler_receives_events(self):
        """Test that a custom handler receives agent events."""
        events_received = []

        class CustomHandler(VoiceCallbackHandler):
            async def on_agent_start(self, ctx, input, tools):
                events_received.append(("start", input, tools))

            async def on_agent_iteration(self, ctx, iteration, max_iterations):
                events_received.append(("iteration", iteration, max_iterations))

            async def on_agent_end(self, ctx, response, iterations, duration_ms):
                events_received.append(("end", response, iterations))

        llm = AsyncMock()
        llm.supports_tools.return_value = False

        async def mock_generate(*args, **kwargs):
            return "Response"

        llm.generate = mock_generate

        manager = CallbackManager([CustomHandler()], run_in_background=False)
        loop = AgentLoop(llm=llm, callbacks=manager)

        await loop.run("Hello")

        # Verify events were received
        assert ("start", "Hello", []) in events_received
        assert any(e[0] == "iteration" for e in events_received)
        assert any(e[0] == "end" and e[1] == "Response" for e in events_received)
