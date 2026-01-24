"""Tests for Voice Agents."""

import pytest
from typing import Any, AsyncIterator, Optional

from voice_pipeline.agents import (
    AgentLoop,
    AgentMessage,
    AgentRouter,
    AgentState,
    AgentStatus,
    ConditionalBranch,
    StreamingVoiceAgent,
    ToolNode,
    VoiceAgent,
    create_tool_router,
    create_voice_agent,
    should_continue,
    status_condition,
    tools_condition,
)
from voice_pipeline.interfaces.llm import LLMChunk, LLMInterface, LLMResponse
from voice_pipeline.memory import ConversationBufferMemory
from voice_pipeline.prompts import VoicePersona
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable
from voice_pipeline.tools import ToolCall, ToolExecutor, ToolResult, voice_tool


# ==================== Mock LLM for Testing ====================


class MockLLM(LLMInterface):
    """Mock LLM that returns predefined responses."""

    def __init__(
        self,
        response: str = "Hello!",
        tool_calls: Optional[list[dict]] = None,
        supports_tools_flag: bool = True,
    ):
        self.response = response
        self.tool_calls = tool_calls or []
        self._supports_tools = supports_tools_flag
        self.call_count = 0
        self.last_messages = None

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        self.call_count += 1
        self.last_messages = messages
        for word in self.response.split():
            yield LLMChunk(text=word + " ")
        yield LLMChunk(text="", is_final=True, finish_reason="stop")

    async def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        self.call_count += 1
        self.last_messages = messages

        if self.tool_calls:
            # Return tool calls on first call, then clear them
            calls = self.tool_calls
            self.tool_calls = []
            return LLMResponse(
                content="",
                tool_calls=calls,
                finish_reason="tool_calls",
            )

        return LLMResponse(
            content=self.response,
            tool_calls=[],
            finish_reason="stop",
        )

    def supports_tools(self) -> bool:
        return self._supports_tools


class MockLLMWithMultipleCalls(LLMInterface):
    """Mock LLM that returns different responses on subsequent calls."""

    def __init__(self, responses: list[tuple[str, list[dict]]]):
        """
        Args:
            responses: List of (content, tool_calls) tuples for each call.
        """
        self.responses = responses
        self.call_count = 0

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        if self.call_count < len(self.responses):
            content, _ = self.responses[self.call_count]
            for char in content:
                yield LLMChunk(text=char)
        self.call_count += 1

    async def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **kwargs,
    ) -> LLMResponse:
        if self.call_count < len(self.responses):
            content, tool_calls = self.responses[self.call_count]
            self.call_count += 1
            return LLMResponse(content=content, tool_calls=tool_calls)
        return LLMResponse(content="Done", tool_calls=[])

    def supports_tools(self) -> bool:
        return True


# ==================== Test AgentState ====================


class TestAgentMessage:
    """Tests for AgentMessage."""

    def test_user_message(self):
        """Test user message creation."""
        msg = AgentMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.tool_calls is None

    def test_assistant_message_with_tool_calls(self):
        """Test assistant message with tool calls."""
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_time", "arguments": "{}"},
            }
        ]
        msg = AgentMessage(role="assistant", content="", tool_calls=tool_calls)
        assert msg.role == "assistant"
        assert len(msg.tool_calls) == 1

    def test_tool_result_message(self):
        """Test tool result message."""
        msg = AgentMessage(
            role="tool",
            content="14:30",
            tool_call_id="call_1",
            name="get_time",
        )
        assert msg.role == "tool"
        assert msg.tool_call_id == "call_1"
        assert msg.name == "get_time"

    def test_to_openai_dict(self):
        """Test OpenAI format conversion."""
        msg = AgentMessage(role="user", content="Hello")
        d = msg.to_openai_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hello"

    def test_to_openai_dict_with_tools(self):
        """Test OpenAI format with tool calls."""
        tool_calls = [{"id": "1", "function": {"name": "test", "arguments": "{}"}}]
        msg = AgentMessage(role="assistant", content="", tool_calls=tool_calls)
        d = msg.to_openai_dict()
        assert "tool_calls" in d
        assert d["tool_calls"] == tool_calls

    def test_to_anthropic_dict_tool_result(self):
        """Test Anthropic format for tool result."""
        msg = AgentMessage(
            role="tool",
            content="result",
            tool_call_id="123",
        )
        d = msg.to_anthropic_dict()
        assert d["role"] == "user"
        assert d["content"][0]["type"] == "tool_result"


class TestAgentState:
    """Tests for AgentState."""

    def test_initial_state(self):
        """Test initial state."""
        state = AgentState()
        assert len(state.messages) == 0
        assert state.status == AgentStatus.PENDING
        assert state.iteration == 0
        assert state.final_response is None

    def test_add_user_message(self):
        """Test adding user message."""
        state = AgentState()
        state.add_user_message("Hello")
        assert len(state.messages) == 1
        assert state.messages[0].role == "user"
        assert state.messages[0].content == "Hello"

    def test_add_assistant_message(self):
        """Test adding assistant message."""
        state = AgentState()
        state.add_assistant_message("Hi there!")
        assert state.messages[0].role == "assistant"

    def test_add_assistant_message_with_tools(self):
        """Test adding assistant message with tool calls."""
        state = AgentState()
        tool_calls = [{"id": "1", "function": {"name": "test"}}]
        state.add_assistant_message("", tool_calls=tool_calls)
        assert state.messages[0].tool_calls == tool_calls

    def test_add_tool_result(self):
        """Test adding tool result."""
        state = AgentState()
        state.add_tool_result("call_1", "get_time", "14:30")
        assert state.messages[0].role == "tool"
        assert state.messages[0].tool_call_id == "call_1"
        assert state.messages[0].name == "get_time"
        assert state.messages[0].content == "14:30"

    def test_should_continue_pending(self):
        """Test should_continue when pending."""
        state = AgentState(max_iterations=10)
        assert state.should_continue() is True

    def test_should_continue_completed(self):
        """Test should_continue when completed."""
        state = AgentState()
        state.status = AgentStatus.COMPLETED
        assert state.should_continue() is False

    def test_should_continue_max_iterations(self):
        """Test should_continue at max iterations."""
        state = AgentState(max_iterations=5)
        state.iteration = 5
        assert state.should_continue() is False

    def test_should_continue_error(self):
        """Test should_continue on error."""
        state = AgentState()
        state.status = AgentStatus.ERROR
        assert state.should_continue() is False

    def test_to_messages(self):
        """Test converting to message list."""
        state = AgentState()
        state.add_user_message("Hello")
        state.add_assistant_message("Hi!")

        messages = state.to_messages()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_clear(self):
        """Test clearing state."""
        state = AgentState()
        state.add_user_message("Hello")
        state.status = AgentStatus.COMPLETED
        state.iteration = 5

        state.clear()
        assert len(state.messages) == 0
        assert state.status == AgentStatus.PENDING
        assert state.iteration == 0

    def test_copy(self):
        """Test copying state."""
        state = AgentState()
        state.add_user_message("Hello")
        state.iteration = 3

        copy = state.copy()
        assert len(copy.messages) == 1
        assert copy.iteration == 3

        # Ensure it's a real copy
        copy.add_user_message("World")
        assert len(state.messages) == 1
        assert len(copy.messages) == 2


# ==================== Test ToolNode ====================


class TestToolNode:
    """Tests for ToolNode."""

    @pytest.mark.asyncio
    async def test_execute_single_tool(self):
        """Test executing single tool."""

        @voice_tool
        def get_time() -> str:
            return "14:30"

        executor = ToolExecutor(tools=[get_time])
        tool_node = ToolNode(executor)

        state = AgentState()
        state.pending_tool_calls = [
            ToolCall(id="1", name="get_time", arguments={})
        ]

        new_state = await tool_node.ainvoke(state)

        assert len(new_state.pending_tool_calls) == 0
        assert len(new_state.messages) == 1
        assert new_state.messages[0].role == "tool"
        assert "14:30" in new_state.messages[0].content

    @pytest.mark.asyncio
    async def test_execute_multiple_tools(self):
        """Test executing multiple tools."""

        @voice_tool
        def add(a: int, b: int) -> int:
            return a + b

        @voice_tool
        def multiply(a: int, b: int) -> int:
            return a * b

        executor = ToolExecutor(tools=[add, multiply])
        tool_node = ToolNode(executor, parallel=True)

        state = AgentState()
        state.pending_tool_calls = [
            ToolCall(id="1", name="add", arguments={"a": 2, "b": 3}),
            ToolCall(id="2", name="multiply", arguments={"a": 4, "b": 5}),
        ]

        new_state = await tool_node.ainvoke(state)

        assert len(new_state.messages) == 2
        assert new_state.status == AgentStatus.OBSERVING

    @pytest.mark.asyncio
    async def test_empty_tool_calls(self):
        """Test with no pending tool calls."""
        executor = ToolExecutor()
        tool_node = ToolNode(executor)

        state = AgentState()
        new_state = await tool_node.ainvoke(state)

        assert new_state is state
        assert len(new_state.messages) == 0

    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Test tool error handling."""

        @voice_tool
        def failing_tool() -> str:
            raise ValueError("Something broke")

        executor = ToolExecutor(tools=[failing_tool])
        tool_node = ToolNode(executor, handle_errors=True)

        state = AgentState()
        state.pending_tool_calls = [
            ToolCall(id="1", name="failing_tool", arguments={})
        ]

        new_state = await tool_node.ainvoke(state)

        assert len(new_state.messages) == 1
        assert "Error" in new_state.messages[0].content


# ==================== Test Router ====================


class TestRouterFunctions:
    """Tests for routing condition functions."""

    def test_tools_condition_with_tools(self):
        """Test tools_condition with pending tools."""
        state = AgentState()
        state.pending_tool_calls = [ToolCall(id="1", name="test", arguments={})]

        assert tools_condition(state) == "tools"

    def test_tools_condition_without_tools(self):
        """Test tools_condition without pending tools."""
        state = AgentState()
        assert tools_condition(state) == "end"

    def test_should_continue_function(self):
        """Test should_continue function."""
        state = AgentState(max_iterations=5)
        assert should_continue(state) == "continue"

        state.status = AgentStatus.COMPLETED
        assert should_continue(state) == "end"

    def test_status_condition(self):
        """Test status_condition function."""
        state = AgentState()
        state.status = AgentStatus.ACTING
        assert status_condition(state) == "acting"


class TestAgentRouter:
    """Tests for AgentRouter."""

    @pytest.mark.asyncio
    async def test_basic_routing(self):
        """Test basic route selection."""

        class DoubleIterationNode(VoiceRunnable[AgentState, AgentState]):
            async def ainvoke(
                self, state: AgentState, config: Optional[RunnableConfig] = None
            ) -> AgentState:
                state.iteration *= 2
                return state

        router = AgentRouter()
        router.add_route(
            "double",
            lambda s: s.iteration > 0,
            DoubleIterationNode(),
        )

        state = AgentState()
        state.iteration = 5

        new_state = await router.ainvoke(state)
        assert new_state.iteration == 10

    @pytest.mark.asyncio
    async def test_no_matching_route(self):
        """Test when no route matches."""
        router = AgentRouter()
        router.add_route(
            "never",
            lambda s: False,
            VoiceRunnable[AgentState, AgentState],
        )

        state = AgentState()
        new_state = await router.ainvoke(state)

        # Should return unchanged
        assert new_state is state

    def test_get_route(self):
        """Test get_route method."""
        router = AgentRouter()
        router.add_route("first", lambda s: True, None)
        router.add_route("second", lambda s: True, None)

        state = AgentState()
        assert router.get_route(state) == "first"


class TestConditionalBranch:
    """Tests for ConditionalBranch."""

    @pytest.mark.asyncio
    async def test_true_branch(self):
        """Test true branch execution."""

        class IncrementNode(VoiceRunnable[AgentState, AgentState]):
            async def ainvoke(
                self, state: AgentState, config: Optional[RunnableConfig] = None
            ) -> AgentState:
                state.iteration += 1
                return state

        class DecrementNode(VoiceRunnable[AgentState, AgentState]):
            async def ainvoke(
                self, state: AgentState, config: Optional[RunnableConfig] = None
            ) -> AgentState:
                state.iteration -= 1
                return state

        branch = ConditionalBranch(
            condition=lambda s: s.iteration > 0,
            if_true=IncrementNode(),
            if_false=DecrementNode(),
        )

        state = AgentState()
        state.iteration = 5

        new_state = await branch.ainvoke(state)
        assert new_state.iteration == 6

    @pytest.mark.asyncio
    async def test_false_branch(self):
        """Test false branch execution."""

        class IncrementNode(VoiceRunnable[AgentState, AgentState]):
            async def ainvoke(
                self, state: AgentState, config: Optional[RunnableConfig] = None
            ) -> AgentState:
                state.iteration += 1
                return state

        class DecrementNode(VoiceRunnable[AgentState, AgentState]):
            async def ainvoke(
                self, state: AgentState, config: Optional[RunnableConfig] = None
            ) -> AgentState:
                state.iteration -= 1
                return state

        branch = ConditionalBranch(
            condition=lambda s: s.iteration > 0,
            if_true=IncrementNode(),
            if_false=DecrementNode(),
        )

        state = AgentState()
        state.iteration = 0

        new_state = await branch.ainvoke(state)
        assert new_state.iteration == -1


# ==================== Test AgentLoop ====================


class TestAgentLoop:
    """Tests for AgentLoop."""

    @pytest.mark.asyncio
    async def test_simple_response(self):
        """Test simple response without tools."""
        llm = MockLLM(response="Hello, I'm here to help!")

        loop = AgentLoop(llm=llm, tools=[])
        result = await loop.run("Hello")

        assert "Hello" in result
        assert llm.call_count >= 1

    @pytest.mark.asyncio
    async def test_with_tool_call(self):
        """Test response with tool call."""

        @voice_tool
        def get_time() -> str:
            return "14:30"

        # LLM will return tool call first, then final response
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_time", "arguments": "{}"},
            }
        ]
        llm = MockLLM(response="The time is 14:30", tool_calls=tool_calls)

        loop = AgentLoop(llm=llm, tools=[get_time])
        result = await loop.run("What time is it?")

        assert "14:30" in result
        assert llm.call_count >= 2  # Initial + after tool result

    @pytest.mark.asyncio
    async def test_max_iterations(self):
        """Test max iterations limit."""

        @voice_tool
        def endless_tool() -> str:
            return "call me again"

        # LLM always returns tool calls
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "endless_tool", "arguments": "{}"},
            }
        ]

        class EndlessLLM(MockLLM):
            async def generate_with_tools(self, *args, **kwargs) -> LLMResponse:
                self.call_count += 1
                return LLMResponse(content="", tool_calls=tool_calls)

        llm = EndlessLLM()
        loop = AgentLoop(llm=llm, tools=[endless_tool], max_iterations=3)

        result = await loop.run("Start the loop")

        assert "unable to complete" in result.lower() or llm.call_count <= 4

    @pytest.mark.asyncio
    async def test_run_with_state(self):
        """Test run_with_state returns full state."""
        llm = MockLLM(response="Hello!")

        loop = AgentLoop(llm=llm, tools=[])
        state = await loop.run_with_state("Hi")

        assert len(state.messages) >= 2  # User + assistant
        assert state.messages[0].role == "user"
        assert state.status == AgentStatus.COMPLETED

    def test_add_remove_tool(self):
        """Test adding and removing tools."""
        llm = MockLLM()
        loop = AgentLoop(llm=llm, tools=[])

        @voice_tool
        def my_tool() -> str:
            return "result"

        loop.add_tool(my_tool)
        assert "my_tool" in loop.list_tools()

        loop.remove_tool("my_tool")
        assert "my_tool" not in loop.list_tools()


# ==================== Test VoiceAgent ====================


class TestVoiceAgent:
    """Tests for VoiceAgent."""

    @pytest.mark.asyncio
    async def test_basic_invoke(self):
        """Test basic agent invocation."""
        llm = MockLLM(response="Hello! How can I help?")
        agent = VoiceAgent(llm=llm)

        response = await agent.ainvoke("Hello")

        assert "Hello" in response
        assert llm.call_count >= 1

    @pytest.mark.asyncio
    async def test_with_tools(self):
        """Test agent with tools."""

        @voice_tool
        def get_weather(location: str) -> str:
            return f"Sunny in {location}"

        tool_calls = [
            {
                "id": "1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"location": "Tokyo"}'},
            }
        ]
        llm = MockLLM(response="It's sunny in Tokyo!", tool_calls=tool_calls)

        agent = VoiceAgent(llm=llm, tools=[get_weather])
        response = await agent.ainvoke("What's the weather in Tokyo?")

        assert "sunny" in response.lower() or "Tokyo" in response

    @pytest.mark.asyncio
    async def test_with_persona(self):
        """Test agent with persona."""
        llm = MockLLM(response="Hello! I'm Julia.")

        persona = VoicePersona(
            name="Julia",
            personality="friendly and helpful",
            language="en-US",
        )

        agent = VoiceAgent(llm=llm, persona=persona)

        assert "Julia" in agent.system_prompt
        assert "friendly" in agent.system_prompt

    @pytest.mark.asyncio
    async def test_with_memory(self):
        """Test agent with memory."""
        llm = MockLLM(response="I remember you!")
        memory = ConversationBufferMemory(max_messages=10)

        agent = VoiceAgent(llm=llm, memory=memory)

        # First interaction
        await agent.ainvoke("Hello")

        # Check memory was saved
        messages = memory.get_messages()
        assert len(messages) == 2  # User + assistant

    @pytest.mark.asyncio
    async def test_clear_memory(self):
        """Test clearing agent memory."""
        llm = MockLLM(response="Hello!")
        memory = ConversationBufferMemory(max_messages=10)

        agent = VoiceAgent(llm=llm, memory=memory)

        await agent.ainvoke("Hello")
        assert len(memory.get_messages()) > 0

        await agent.clear_memory()
        assert len(memory.get_messages()) == 0

    @pytest.mark.asyncio
    async def test_tool_management(self):
        """Test adding and removing tools from agent."""
        llm = MockLLM()
        agent = VoiceAgent(llm=llm)

        @voice_tool
        def my_tool() -> str:
            return "result"

        agent.add_tool(my_tool)
        assert "my_tool" in agent.list_tools()

        agent.remove_tool("my_tool")
        assert "my_tool" not in agent.list_tools()

    @pytest.mark.asyncio
    async def test_normalize_dict_input(self):
        """Test normalizing dict input."""
        llm = MockLLM(response="Got it!")
        agent = VoiceAgent(llm=llm)

        # TranscriptionResult-like dict
        response = await agent.ainvoke({"text": "Hello from dict"})
        assert response is not None

    @pytest.mark.asyncio
    async def test_custom_system_prompt(self):
        """Test custom system prompt overrides persona."""
        llm = MockLLM()
        persona = VoicePersona(name="Julia")

        agent = VoiceAgent(
            llm=llm,
            persona=persona,
            system_prompt="You are a pirate.",
        )

        assert "pirate" in agent.system_prompt
        assert "Julia" not in agent.system_prompt


class TestStreamingVoiceAgent:
    """Tests for StreamingVoiceAgent."""

    @pytest.mark.asyncio
    async def test_streaming_output(self):
        """Test streaming response."""
        llm = MockLLM(response="Hello World")
        agent = StreamingVoiceAgent(llm=llm)

        tokens = []
        async for token in agent.astream("Hi"):
            tokens.append(token)

        assert len(tokens) > 0


class TestCreateVoiceAgent:
    """Tests for create_voice_agent factory."""

    def test_basic_creation(self):
        """Test basic agent creation."""
        llm = MockLLM()
        agent = create_voice_agent(llm=llm)

        assert isinstance(agent, VoiceAgent)

    def test_with_all_options(self):
        """Test creation with all options."""

        @voice_tool
        def my_tool() -> str:
            return "result"

        llm = MockLLM()
        persona = VoicePersona(name="Test")
        memory = ConversationBufferMemory()

        agent = create_voice_agent(
            llm=llm,
            tools=[my_tool],
            persona=persona,
            memory=memory,
            max_iterations=5,
        )

        assert len(agent.tools) == 1
        assert agent.persona is persona
        assert agent.memory is memory
        assert agent.max_iterations == 5


# ==================== Test Pipeline Composition ====================


class TestAgentComposition:
    """Tests for agent composition with pipelines."""

    @pytest.mark.asyncio
    async def test_agent_is_runnable(self):
        """Test that VoiceAgent is a valid VoiceRunnable."""
        llm = MockLLM(response="Hello!")
        agent = VoiceAgent(llm=llm)

        assert isinstance(agent, VoiceRunnable)

        # Can call ainvoke
        result = await agent.ainvoke("Hi")
        assert result is not None

    @pytest.mark.asyncio
    async def test_agent_pipe_composition(self):
        """Test composing agent with other runnables."""

        class MockInput(VoiceRunnable[str, str]):
            async def ainvoke(
                self, input: str, config: Optional[RunnableConfig] = None
            ) -> str:
                return f"Processed: {input}"

        class MockOutput(VoiceRunnable[str, str]):
            async def ainvoke(
                self, input: str, config: Optional[RunnableConfig] = None
            ) -> str:
                return f"Output: {input}"

        llm = MockLLM(response="Response")
        agent = VoiceAgent(llm=llm)

        # Compose pipeline
        pipeline = MockInput() | agent | MockOutput()

        result = await pipeline.ainvoke("Test")

        assert "Output" in result

    @pytest.mark.asyncio
    async def test_agent_streaming_composition(self):
        """Test streaming through composed pipeline."""

        class PassThrough(VoiceRunnable[str, str]):
            async def ainvoke(
                self, input: str, config: Optional[RunnableConfig] = None
            ) -> str:
                return input

        llm = MockLLM(response="Streaming test")
        agent = VoiceAgent(llm=llm)

        pipeline = PassThrough() | agent

        tokens = []
        async for token in pipeline.astream("Hello"):
            tokens.append(token)

        # Should get some output
        assert len(tokens) > 0


# ==================== Test LLMResponse ====================


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_basic_response(self):
        """Test basic response creation."""
        response = LLMResponse(content="Hello")
        assert response.content == "Hello"
        assert response.tool_calls == []
        assert not response.has_tool_calls

    def test_response_with_tools(self):
        """Test response with tool calls."""
        tool_calls = [{"id": "1", "name": "test"}]
        response = LLMResponse(content="", tool_calls=tool_calls)

        assert response.has_tool_calls
        assert len(response.tool_calls) == 1

    def test_response_properties(self):
        """Test response properties."""
        response = LLMResponse(
            content="Done",
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )

        assert response.finish_reason == "stop"
        assert response.usage["prompt_tokens"] == 10
