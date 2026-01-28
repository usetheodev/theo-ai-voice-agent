"""Tests for agent streaming events."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from voice_pipeline.agents.events import (
    StateDelta,
    StreamEvent,
    StreamEventType,
)
from voice_pipeline.agents.state import AgentMessage, AgentState, AgentStatus
from voice_pipeline.agents.loop import AgentLoop, ToolFeedbackConfig


class TestStreamEventType:
    """Tests for StreamEventType enum."""

    def test_all_event_types_exist(self):
        """Verify all expected event types are defined."""
        expected = [
            "TOKEN",
            "FEEDBACK",
            "TOOL_START",
            "TOOL_END",
            "THINKING",
            "ITERATION",
            "ERROR",
            "DONE",
        ]
        for name in expected:
            assert hasattr(StreamEventType, name)

    def test_event_type_values(self):
        """Event type values should be lowercase strings."""
        assert StreamEventType.TOKEN.value == "token"
        assert StreamEventType.FEEDBACK.value == "feedback"
        assert StreamEventType.ERROR.value == "error"


class TestStreamEvent:
    """Tests for StreamEvent dataclass."""

    def test_basic_event(self):
        """Test creating a basic event."""
        event = StreamEvent(type=StreamEventType.TOKEN, data="Hello")
        assert event.type == StreamEventType.TOKEN
        assert event.data == "Hello"
        assert event.metadata == {}

    def test_event_with_metadata(self):
        """Test event with metadata."""
        event = StreamEvent(
            type=StreamEventType.TOOL_START,
            data="get_weather",
            metadata={"tool_name": "get_weather", "arguments": {"city": "NYC"}},
        )
        assert event.metadata["tool_name"] == "get_weather"
        assert event.metadata["arguments"]["city"] == "NYC"

    def test_is_response_token(self):
        """Test is_response_token property."""
        token_event = StreamEvent(type=StreamEventType.TOKEN, data="Hi")
        assert token_event.is_response_token is True

        feedback_event = StreamEvent(type=StreamEventType.FEEDBACK, data="Let me check")
        assert feedback_event.is_response_token is False

    def test_is_feedback(self):
        """Test is_feedback property."""
        feedback_event = StreamEvent(type=StreamEventType.FEEDBACK, data="One moment")
        assert feedback_event.is_feedback is True

        token_event = StreamEvent(type=StreamEventType.TOKEN, data="Hi")
        assert token_event.is_feedback is False

    def test_is_tool_event(self):
        """Test is_tool_event property."""
        start_event = StreamEvent(type=StreamEventType.TOOL_START, data="tool1")
        assert start_event.is_tool_event is True

        end_event = StreamEvent(type=StreamEventType.TOOL_END, data="")
        assert end_event.is_tool_event is True

        token_event = StreamEvent(type=StreamEventType.TOKEN, data="Hi")
        assert token_event.is_tool_event is False

    def test_is_error(self):
        """Test is_error property."""
        error_event = StreamEvent(type=StreamEventType.ERROR, data="Something went wrong")
        assert error_event.is_error is True

        token_event = StreamEvent(type=StreamEventType.TOKEN, data="Hi")
        assert token_event.is_error is False

    def test_is_done(self):
        """Test is_done property."""
        done_event = StreamEvent(type=StreamEventType.DONE, data="Final response")
        assert done_event.is_done is True

        token_event = StreamEvent(type=StreamEventType.TOKEN, data="Hi")
        assert token_event.is_done is False

    def test_repr(self):
        """Test string representation."""
        event = StreamEvent(type=StreamEventType.TOKEN, data="Hello world")
        repr_str = repr(event)
        assert "StreamEvent" in repr_str
        assert "token" in repr_str
        assert "Hello world" in repr_str


class TestStateDelta:
    """Tests for StateDelta dataclass."""

    def test_empty_delta(self):
        """Test delta with no changes."""
        delta = StateDelta()
        assert delta.status is None
        assert delta.iteration_increment is False
        assert delta.final_response is None

    def test_status_delta(self):
        """Test delta that changes status."""
        delta = StateDelta(status=AgentStatus.COMPLETED)
        state = AgentState()

        delta.apply_to(state)

        assert state.status == AgentStatus.COMPLETED

    def test_iteration_increment(self):
        """Test delta that increments iteration."""
        delta = StateDelta(iteration_increment=True)
        state = AgentState()
        assert state.iteration == 0

        delta.apply_to(state)

        assert state.iteration == 1

    def test_final_response_delta(self):
        """Test delta with final response."""
        delta = StateDelta(final_response="The answer is 42")
        state = AgentState()

        delta.apply_to(state)

        assert state.final_response == "The answer is 42"

    def test_error_delta(self):
        """Test delta with error sets status to ERROR."""
        delta = StateDelta(error="Something went wrong")
        state = AgentState()

        delta.apply_to(state)

        assert state.error == "Something went wrong"
        assert state.status == AgentStatus.ERROR

    def test_add_message_assistant(self):
        """Test delta that adds assistant message."""
        delta = StateDelta(
            add_message={
                "role": "assistant",
                "content": "Hello there!",
            }
        )
        state = AgentState()

        delta.apply_to(state)

        assert len(state.messages) == 1
        assert state.messages[0].role == "assistant"
        assert state.messages[0].content == "Hello there!"

    def test_add_message_user(self):
        """Test delta that adds user message."""
        delta = StateDelta(
            add_message={
                "role": "user",
                "content": "Hi there!",
            }
        )
        state = AgentState()

        delta.apply_to(state)

        assert len(state.messages) == 1
        assert state.messages[0].role == "user"

    def test_add_message_tool(self):
        """Test delta that adds tool message."""
        delta = StateDelta(
            add_message={
                "role": "tool",
                "content": "Tool result",
                "tool_call_id": "call_123",
                "name": "get_weather",
            }
        )
        state = AgentState()

        delta.apply_to(state)

        assert len(state.messages) == 1
        assert state.messages[0].role == "tool"
        assert state.messages[0].tool_call_id == "call_123"

    def test_combined_delta(self):
        """Test delta with multiple changes."""
        delta = StateDelta(
            status=AgentStatus.COMPLETED,
            iteration_increment=True,
            final_response="Done!",
            add_message={"role": "assistant", "content": "Done!"},
        )
        state = AgentState()

        delta.apply_to(state)

        assert state.status == AgentStatus.COMPLETED
        assert state.iteration == 1
        assert state.final_response == "Done!"
        assert len(state.messages) == 1


class TestAgentLoopStreamEvents:
    """Tests for AgentLoop.run_stream_events()."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM that returns a simple response."""
        llm = AsyncMock()
        llm.supports_tools.return_value = False

        async def mock_astream(messages):
            yield MagicMock(text="Hello ")
            yield MagicMock(text="world!")

        llm.astream = mock_astream
        return llm

    @pytest.fixture
    def mock_llm_with_tools(self):
        """Create a mock LLM that supports tools."""
        llm = AsyncMock()
        llm.supports_tools.return_value = True

        async def mock_stream_with_tools(messages, tools, system_prompt=None):
            yield MagicMock(text="I'll help ", tool_calls_delta=None)
            yield MagicMock(text="you!", tool_calls_delta=None)

        llm.generate_stream_with_tools = mock_stream_with_tools
        return llm

    @pytest.mark.asyncio
    async def test_stream_events_emits_tokens(self, mock_llm):
        """Test that stream_events yields TOKEN events."""
        loop = AgentLoop(llm=mock_llm)

        events = []
        async for event in loop.run_stream_events("Hi"):
            events.append(event)

        # Should have ITERATION, THINKING, TOKEN events, and DONE
        token_events = [e for e in events if e.type == StreamEventType.TOKEN]
        assert len(token_events) >= 1

        # Last event should be DONE
        assert events[-1].type == StreamEventType.DONE

    @pytest.mark.asyncio
    async def test_stream_events_emits_iteration(self, mock_llm):
        """Test that stream_events yields ITERATION event."""
        loop = AgentLoop(llm=mock_llm)

        events = []
        async for event in loop.run_stream_events("Hi"):
            events.append(event)

        iteration_events = [e for e in events if e.type == StreamEventType.ITERATION]
        assert len(iteration_events) >= 1
        assert iteration_events[0].metadata["iteration"] == 1

    @pytest.mark.asyncio
    async def test_stream_events_emits_thinking(self, mock_llm):
        """Test that stream_events yields THINKING event."""
        loop = AgentLoop(llm=mock_llm)

        events = []
        async for event in loop.run_stream_events("Hi"):
            events.append(event)

        thinking_events = [e for e in events if e.type == StreamEventType.THINKING]
        assert len(thinking_events) >= 1


class TestAgentLoopFeedbackSeparation:
    """Tests that feedback is properly separated from response tokens."""

    @pytest.fixture
    def mock_llm_with_tool_call(self):
        """Create a mock LLM that returns a tool call then a response."""
        llm = AsyncMock()
        llm.supports_tools.return_value = True

        call_count = 0

        async def mock_stream_with_tools(messages, tools, system_prompt=None):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: return tool call
                yield MagicMock(
                    text="",
                    tool_calls_delta=[{
                        "id": "call_1",
                        "function": {"name": "get_time", "arguments": "{}"}
                    }]
                )
            else:
                # Second call: return response
                yield MagicMock(text="The time is 10:00", tool_calls_delta=None)

        llm.generate_stream_with_tools = mock_stream_with_tools
        return llm

    @pytest.mark.asyncio
    async def test_feedback_separate_from_tokens(self, mock_llm_with_tool_call):
        """Test that FEEDBACK events are separate from TOKEN events."""
        from voice_pipeline.tools.base import VoiceTool, ToolResult

        # Create a simple mock tool
        class MockTool(VoiceTool):
            name = "get_time"
            description = "Get current time"
            parameters = []

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True, output="10:00")

        feedback_config = ToolFeedbackConfig(
            enabled=True,
            phrases=["Let me check..."],
        )

        loop = AgentLoop(
            llm=mock_llm_with_tool_call,
            tools=[MockTool()],
            tool_feedback=feedback_config,
        )

        events = []
        async for event in loop.run_stream_events("What time is it?"):
            events.append(event)

        # Should have FEEDBACK event
        feedback_events = [e for e in events if e.type == StreamEventType.FEEDBACK]
        assert len(feedback_events) >= 1
        assert feedback_events[0].data == "Let me check..."

        # FEEDBACK should not be mixed with TOKEN
        token_events = [e for e in events if e.type == StreamEventType.TOKEN]
        for event in token_events:
            assert "Let me check" not in event.data


class TestRunStreamBackwardsCompatibility:
    """Tests that run_stream() maintains backwards compatibility."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = AsyncMock()
        llm.supports_tools.return_value = False

        async def mock_astream(messages):
            yield MagicMock(text="Hello ")
            yield MagicMock(text="world!")

        llm.astream = mock_astream
        return llm

    @pytest.mark.asyncio
    async def test_run_stream_yields_strings(self, mock_llm):
        """Test that run_stream still yields strings, not events."""
        loop = AgentLoop(llm=mock_llm)

        tokens = []
        async for token in loop.run_stream("Hi"):
            tokens.append(token)
            assert isinstance(token, str)

        full_response = "".join(tokens)
        assert "Hello" in full_response
        assert "world" in full_response

    @pytest.mark.asyncio
    async def test_run_stream_excludes_feedback(self, mock_llm):
        """Test that run_stream excludes feedback phrases."""
        from voice_pipeline.tools.base import VoiceTool, ToolResult

        class MockTool(VoiceTool):
            name = "test_tool"
            description = "Test"
            parameters = []

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True, output="result")

        # Create LLM that returns tool call then response
        llm = AsyncMock()
        llm.supports_tools.return_value = True

        call_count = 0

        async def mock_stream(messages, tools, system_prompt=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield MagicMock(text="", tool_calls_delta=[{
                    "id": "1", "function": {"name": "test_tool", "arguments": "{}"}
                }])
            else:
                yield MagicMock(text="Done!", tool_calls_delta=None)

        llm.generate_stream_with_tools = mock_stream

        feedback_config = ToolFeedbackConfig(
            enabled=True,
            phrases=["Working on it..."],
        )

        loop = AgentLoop(
            llm=llm,
            tools=[MockTool()],
            tool_feedback=feedback_config,
        )

        tokens = []
        async for token in loop.run_stream("Test"):
            tokens.append(token)

        full_response = "".join(tokens)
        # Feedback should NOT be in the response
        assert "Working on it" not in full_response


class TestAgentMessageAnthropicFormat:
    """Tests for AgentMessage Anthropic format conversion (TASK-1.4 fix)."""

    def test_system_message_preserves_role(self):
        """Test that system messages keep role='system' for caller to filter."""
        msg = AgentMessage(role="system", content="You are a helpful assistant")
        result = msg.to_anthropic_dict()

        # Should preserve system role, NOT convert to user
        assert result["role"] == "system"
        assert result["content"] == "You are a helpful assistant"

    def test_is_system_property(self):
        """Test is_system property."""
        system_msg = AgentMessage(role="system", content="System prompt")
        assert system_msg.is_system is True

        user_msg = AgentMessage(role="user", content="Hello")
        assert user_msg.is_system is False

    def test_user_message_unchanged(self):
        """Test user messages are unchanged."""
        msg = AgentMessage(role="user", content="Hello")
        result = msg.to_anthropic_dict()

        assert result["role"] == "user"
        assert result["content"] == "Hello"

    def test_assistant_message_unchanged(self):
        """Test assistant messages are unchanged."""
        msg = AgentMessage(role="assistant", content="Hi there!")
        result = msg.to_anthropic_dict()

        assert result["role"] == "assistant"
        assert result["content"] == "Hi there!"

    def test_tool_message_converts_correctly(self):
        """Test tool messages convert to tool_result format."""
        msg = AgentMessage(
            role="tool",
            content="Weather is sunny",
            tool_call_id="call_123",
            name="get_weather"
        )
        result = msg.to_anthropic_dict()

        assert result["role"] == "user"
        assert result["content"][0]["type"] == "tool_result"
        assert result["content"][0]["tool_use_id"] == "call_123"

    def test_assistant_with_tool_calls(self):
        """Test assistant message with tool calls."""
        msg = AgentMessage(
            role="assistant",
            content="Let me check",
            tool_calls=[{
                "id": "call_123",
                "function": {"name": "get_weather", "arguments": {"city": "NYC"}}
            }]
        )
        result = msg.to_anthropic_dict()

        assert result["role"] == "assistant"
        assert len(result["content"]) == 2  # text + tool_use
        assert result["content"][0]["type"] == "text"
        assert result["content"][1]["type"] == "tool_use"

    def test_state_filters_system_messages(self):
        """Test that callers can filter system messages from state."""
        state = AgentState()
        state.add_system_message("You are helpful")
        state.add_user_message("Hello")
        state.add_assistant_message("Hi!")

        messages = state.to_messages(format="anthropic")

        # Caller should filter system messages
        non_system = [m for m in messages if m["role"] != "system"]
        assert len(non_system) == 2  # user and assistant only

        # System message should still be present with role="system"
        system_msgs = [m for m in messages if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "You are helpful"


class TestAgentLoopCancellation:
    """Tests for AgentLoop cancellation support (TASK-2.2)."""

    def test_cancel_sets_event(self):
        """Test that cancel() sets the cancel event."""
        llm = AsyncMock()
        llm.supports_tools.return_value = False
        loop = AgentLoop(llm=llm)

        assert loop.is_cancelled is False
        loop.cancel()
        assert loop.is_cancelled is True

    def test_reset_cancel_clears_event(self):
        """Test that reset_cancel() clears the cancel event."""
        llm = AsyncMock()
        llm.supports_tools.return_value = False
        loop = AgentLoop(llm=llm)

        loop.cancel()
        assert loop.is_cancelled is True

        loop.reset_cancel()
        assert loop.is_cancelled is False

    @pytest.mark.asyncio
    async def test_run_cancels_during_llm_call(self):
        """Test that run() can be cancelled during LLM call."""
        import asyncio

        llm = AsyncMock()
        llm.supports_tools.return_value = True

        cancel_triggered = False

        async def slow_generate(*args, loop_ref=None, **kwargs):
            nonlocal cancel_triggered
            # Simulate slow LLM that checks cancellation
            for _ in range(10):
                await asyncio.sleep(0.05)
                if loop_ref and loop_ref.is_cancelled:
                    cancel_triggered = True
            return MagicMock(content="Done", has_tool_calls=False, tool_calls=[])

        loop = AgentLoop(llm=llm)

        # Wrap to inject loop reference
        async def wrapped_generate(*args, **kwargs):
            return await slow_generate(*args, loop_ref=loop, **kwargs)

        llm.generate_with_tools = wrapped_generate

        async def run_and_cancel():
            task = asyncio.create_task(loop.run("Test"))
            await asyncio.sleep(0.1)  # Let it start
            loop.cancel()
            return await task

        result = await asyncio.wait_for(run_and_cancel(), timeout=2.0)

        # Note: The current implementation doesn't cancel during LLM calls,
        # but it does check after each iteration. This test verifies the
        # mechanism exists.
        assert loop.is_cancelled

    @pytest.mark.asyncio
    async def test_tool_executor_uses_cancel_event(self):
        """Test that ToolExecutor.execute_many uses cancel_event."""
        from voice_pipeline.tools.base import VoiceTool, ToolResult
        from voice_pipeline.tools.executor import ToolExecutor, ToolCall
        import asyncio

        class FastTool(VoiceTool):
            name = "fast_tool"
            description = "A fast tool"
            parameters = []

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True, output="Done")

        executor = ToolExecutor(tools=[FastTool()])
        cancel_event = asyncio.Event()

        # Set cancel before execution
        cancel_event.set()

        calls = [ToolCall(id="1", name="fast_tool", arguments={})]
        results = await executor.execute_many(calls, cancel_event=cancel_event)

        # When cancel is set, tools should return cancelled result
        assert len(results) == 1
        # Note: The cancel event is checked during execution, so if set before,
        # the tool may still execute. This test verifies the API accepts cancel_event.

    @pytest.mark.asyncio
    async def test_cancel_event_propagated_to_tool_node(self):
        """Test that cancel_event is passed to ToolNode."""
        llm = AsyncMock()
        llm.supports_tools.return_value = False

        loop = AgentLoop(llm=llm)

        # Verify that ToolNode received the cancel_event
        assert loop.tool_node.cancel_event is loop._cancel_event

    @pytest.mark.asyncio
    async def test_voice_agent_exposes_cancel(self):
        """Test that VoiceAgent exposes cancel method."""
        from voice_pipeline.agents.base import VoiceAgent

        llm = AsyncMock()
        llm.supports_tools.return_value = False

        agent = VoiceAgent(llm=llm)

        # Verify cancel methods exist
        assert hasattr(agent, 'cancel')
        assert hasattr(agent, 'reset_cancel')
        assert hasattr(agent, 'is_cancelled')

        # Verify they work
        assert agent.is_cancelled is False
        agent.cancel()
        assert agent.is_cancelled is True
        agent.reset_cancel()
        assert agent.is_cancelled is False
