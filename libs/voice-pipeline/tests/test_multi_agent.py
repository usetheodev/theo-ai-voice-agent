"""Tests for Multi-Agent system."""

import pytest
from typing import Any, AsyncIterator, Optional

from voice_pipeline.multi_agent import (
    END,
    START,
    AgentRole,
    AgentTeam,
    CollaborationMode,
    CollaborativeAgents,
    CompiledGraph,
    Handoff,
    HandoffCondition,
    HandoffManager,
    MultiAgentState,
    SharedMemory,
    SharedScratchpad,
    SupervisorAgent,
    SupervisorConfig,
    TeamConfig,
    VoiceGraph,
    create_collaboration,
    create_handoff,
    create_initial_state,
    create_supervisor,
    create_team,
    keyword_condition,
)
from voice_pipeline.multi_agent.state import (
    ChannelState,
    ChannelType,
    MessageChannel,
)
from voice_pipeline.multi_agent.team import ExecutionMode
from voice_pipeline.agents.base import VoiceAgent
from voice_pipeline.interfaces.llm import LLMChunk, LLMInterface, LLMResponse
from voice_pipeline.runnable import RunnableConfig


# ==================== Mock LLM ====================


class MockLLM(LLMInterface):
    """Mock LLM for testing."""

    def __init__(self, response: str = "Mock response"):
        self.response = response
        self.call_count = 0

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        self.call_count += 1
        yield LLMChunk(text=self.response, is_final=True)

    async def generate(
        self,
        messages: list[dict[str, str]],
        **kwargs,
    ) -> str:
        self.call_count += 1
        return self.response


# ==================== Test State ====================


class TestMultiAgentState:
    """Tests for MultiAgentState."""

    def test_create_initial_state(self):
        """Test creating initial state."""
        state = create_initial_state(
            user_query="Hello",
            max_iterations=5,
        )

        assert state["user_query"] == "Hello"
        assert state["max_iterations"] == 5
        assert state["iteration"] == 0
        assert state["is_complete"] is False
        assert state["messages"] == []

    def test_create_initial_state_with_audio(self):
        """Test creating state with audio."""
        audio = b"audio bytes"
        state = create_initial_state(
            user_query="",
            audio_input=audio,
        )

        assert state["audio_input"] == audio


class TestSharedMemory:
    """Tests for SharedMemory."""

    def test_get_set(self):
        """Test get and set."""
        memory = SharedMemory()
        memory.set("key1", "value1", agent="agent1")

        assert memory.get("key1") == "value1"
        assert memory.get("missing") is None
        assert memory.get("missing", "default") == "default"

    def test_delete(self):
        """Test delete."""
        memory = SharedMemory()
        memory.set("key1", "value1")
        memory.delete("key1")

        assert memory.get("key1") is None

    def test_keys(self):
        """Test keys listing."""
        memory = SharedMemory()
        memory.set("a", 1)
        memory.set("b", 2)

        assert set(memory.keys()) == {"a", "b"}

    def test_history(self):
        """Test modification history."""
        memory = SharedMemory()
        memory.set("key1", "v1", agent="agent1")
        memory.set("key2", "v2", agent="agent2")

        history = memory.get_history()
        assert len(history) == 2
        assert history[0] == ("agent1", "key1", "v1")

    def test_clear(self):
        """Test clear."""
        memory = SharedMemory()
        memory.set("key1", "value1")
        memory.clear()

        assert memory.keys() == []


class TestMessageChannel:
    """Tests for MessageChannel."""

    def test_broadcast(self):
        """Test broadcast channel."""
        channel = MessageChannel(name="test", channel_type=ChannelType.BROADCAST)
        channel.publish("agent1", "Hello everyone")

        msgs = channel.get_messages("agent2")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Hello everyone"

    def test_direct(self):
        """Test direct messaging."""
        channel = MessageChannel(name="test", channel_type=ChannelType.DIRECT)
        channel.publish("agent1", "Hello agent2", target="agent2")
        channel.publish("agent1", "Hello agent3", target="agent3")

        msgs2 = channel.get_messages("agent2")
        msgs3 = channel.get_messages("agent3")

        assert len(msgs2) == 1
        assert len(msgs3) == 1

    def test_topic_subscription(self):
        """Test topic subscription."""
        channel = MessageChannel(name="test", channel_type=ChannelType.TOPIC)
        channel.subscribe("subscriber1")
        channel.publish("publisher", "Message")

        msgs1 = channel.get_messages("subscriber1")
        msgs2 = channel.get_messages("non_subscriber")

        assert len(msgs1) == 1
        assert len(msgs2) == 0


class TestChannelState:
    """Tests for ChannelState."""

    def test_create_channel(self):
        """Test creating channels."""
        channels = ChannelState()
        ch = channels.create_channel("coordination")

        assert ch.name == "coordination"
        assert channels.get_channel("coordination") is ch

    def test_publish(self):
        """Test publishing to channel."""
        channels = ChannelState()
        channels.create_channel("test")
        channels.publish("test", "sender", "Hello")

        ch = channels.get_channel("test")
        msgs = ch.get_messages("anyone")
        assert len(msgs) == 1


# ==================== Test VoiceGraph ====================


class TestVoiceGraph:
    """Tests for VoiceGraph."""

    def test_add_node(self):
        """Test adding nodes."""
        graph = VoiceGraph()

        def my_node(state):
            return {"answer": "done"}

        graph.add_node("my_node", my_node)
        structure = graph.get_graph_structure()

        assert "my_node" in structure["nodes"]

    def test_add_node_duplicate(self):
        """Test adding duplicate node raises error."""
        graph = VoiceGraph()
        graph.add_node("node1", lambda s: s)

        with pytest.raises(ValueError):
            graph.add_node("node1", lambda s: s)

    def test_add_edge(self):
        """Test adding edges."""
        graph = VoiceGraph()
        graph.add_node("node1", lambda s: s)
        graph.add_node("node2", lambda s: s)
        graph.add_edge(START, "node1")
        graph.add_edge("node1", "node2")
        graph.add_edge("node2", END)

        structure = graph.get_graph_structure()
        assert len(structure["edges"]) == 3
        assert structure["entry_point"] == "node1"

    def test_add_edge_invalid_node(self):
        """Test adding edge with invalid node."""
        graph = VoiceGraph()

        with pytest.raises(ValueError):
            graph.add_edge(START, "nonexistent")

    def test_add_conditional_edges(self):
        """Test adding conditional edges."""
        graph = VoiceGraph()
        graph.add_node("router", lambda s: s)
        graph.add_node("path_a", lambda s: s)
        graph.add_node("path_b", lambda s: s)

        graph.add_conditional_edges(
            "router",
            lambda s: s.get("next", "path_a"),
            {"path_a": "path_a", "path_b": "path_b"},
        )

        structure = graph.get_graph_structure()
        conditional_edges = [e for e in structure["edges"] if e["conditional"]]
        assert len(conditional_edges) == 1

    def test_compile(self):
        """Test compiling graph."""
        graph = VoiceGraph()
        graph.add_node("node1", lambda s: {"answer": "done"})
        graph.add_edge(START, "node1")
        graph.add_edge("node1", END)

        compiled = graph.compile()
        assert isinstance(compiled, CompiledGraph)

    def test_compile_no_entry_point(self):
        """Test compile fails without entry point."""
        graph = VoiceGraph()
        graph.add_node("node1", lambda s: s)

        with pytest.raises(ValueError):
            graph.compile()

    @pytest.mark.asyncio
    async def test_compiled_graph_invoke(self):
        """Test executing compiled graph."""

        def node1(state):
            return {"answer": "from node1"}

        graph = VoiceGraph()
        graph.add_node("node1", node1)
        graph.add_edge(START, "node1")
        graph.add_edge("node1", END)

        app = graph.compile()
        result = await app.ainvoke({"user_query": "test"})

        assert result["answer"] == "from node1"

    @pytest.mark.asyncio
    async def test_compiled_graph_conditional(self):
        """Test conditional routing."""

        def router(state):
            if "math" in state.get("user_query", ""):
                return {"next_agent": "math"}
            return {"next_agent": "search"}

        def math_node(state):
            return {"answer": "math result"}

        def search_node(state):
            return {"answer": "search result"}

        graph = VoiceGraph()
        graph.add_node("router", router)
        graph.add_node("math", math_node)
        graph.add_node("search", search_node)

        graph.add_edge(START, "router")
        graph.add_conditional_edges(
            "router",
            lambda s: s.get("next_agent", "search"),
        )
        graph.add_edge("math", END)
        graph.add_edge("search", END)

        app = graph.compile()

        # Test math path
        result = await app.ainvoke({"user_query": "what is 2+2 math"})
        assert result["answer"] == "math result"

        # Test search path
        result = await app.ainvoke({"user_query": "who is Einstein"})
        assert result["answer"] == "search result"

    @pytest.mark.asyncio
    async def test_compiled_graph_stream(self):
        """Test streaming graph execution."""

        def node1(state):
            return {"step": "node1"}

        def node2(state):
            return {"answer": "done", "is_complete": True}

        graph = VoiceGraph()
        graph.add_node("node1", node1)
        graph.add_node("node2", node2)
        graph.add_edge(START, "node1")
        graph.add_edge("node1", "node2")
        graph.add_edge("node2", END)

        app = graph.compile()

        events = []
        async for node_name, state in app.astream({"user_query": "test"}):
            events.append((node_name, state.get("answer")))

        assert len(events) >= 2
        assert events[-1][0] == END


# ==================== Test SupervisorAgent ====================


class TestSupervisorAgent:
    """Tests for SupervisorAgent."""

    @pytest.mark.asyncio
    async def test_basic_routing(self):
        """Test basic routing to agents."""
        llm = MockLLM(response="math")

        math_llm = MockLLM(response="The answer is 4")
        search_llm = MockLLM(response="Search results")

        math_agent = VoiceAgent(llm=math_llm)
        search_agent = VoiceAgent(llm=search_llm)

        supervisor = SupervisorAgent(
            llm=llm,
            agents={"math": math_agent, "search": search_agent},
            agent_descriptions={
                "math": "Mathematical calculations",
                "search": "Web search",
            },
        )

        result = await supervisor.ainvoke("What is 2+2?")
        assert "4" in result or "math" in result.lower()

    @pytest.mark.asyncio
    async def test_custom_router(self):
        """Test custom routing function."""
        llm = MockLLM()

        agent1 = VoiceAgent(llm=MockLLM(response="Agent 1"))
        agent2 = VoiceAgent(llm=MockLLM(response="Agent 2"))

        def custom_router(query: str, descriptions: dict) -> str:
            if "one" in query.lower():
                return "agent1"
            return "agent2"

        supervisor = SupervisorAgent(
            llm=llm,
            agents={"agent1": agent1, "agent2": agent2},
            custom_router=custom_router,
        )

        result = await supervisor.ainvoke("Route to one")
        assert "Agent 1" in result

    @pytest.mark.asyncio
    async def test_fallback_agent(self):
        """Test fallback agent."""
        llm = MockLLM(response="unknown_agent")
        fallback = VoiceAgent(llm=MockLLM(response="Fallback response"))

        supervisor = SupervisorAgent(
            llm=llm,
            agents={"fallback": fallback},
            config=SupervisorConfig(fallback_agent="fallback"),
        )

        result = await supervisor.ainvoke("Any query")
        assert "Fallback" in result

    def test_add_remove_agent(self):
        """Test adding and removing agents."""
        llm = MockLLM()
        supervisor = SupervisorAgent(llm=llm, agents={})

        agent = VoiceAgent(llm=MockLLM())
        supervisor.add_agent("new_agent", agent, "Description")

        assert "new_agent" in supervisor.list_agents()
        assert supervisor.get_agent("new_agent") is agent

        supervisor.remove_agent("new_agent")
        assert "new_agent" not in supervisor.list_agents()


class TestCreateSupervisor:
    """Tests for create_supervisor factory."""

    def test_create_supervisor(self):
        """Test creating supervisor with factory."""
        llm = MockLLM()
        agents = {
            "agent1": VoiceAgent(llm=MockLLM()),
            "agent2": VoiceAgent(llm=MockLLM()),
        }

        supervisor = create_supervisor(
            llm=llm,
            agents=agents,
            max_iterations=5,
            fallback_agent="agent1",
        )

        assert isinstance(supervisor, SupervisorAgent)
        assert supervisor.config.max_iterations == 5
        assert supervisor.config.fallback_agent == "agent1"


# ==================== Test AgentTeam ====================


class TestAgentTeam:
    """Tests for AgentTeam."""

    @pytest.mark.asyncio
    async def test_sequential_execution(self):
        """Test sequential team execution."""
        agent1 = VoiceAgent(llm=MockLLM(response="Step 1 done"))
        agent2 = VoiceAgent(llm=MockLLM(response="Step 2 done"))

        roles = [
            AgentRole(name="step1", description="First step", agent=agent1),
            AgentRole(name="step2", description="Second step", agent=agent2),
        ]

        team = AgentTeam(
            roles=roles,
            config=TeamConfig(execution_mode=ExecutionMode.SEQUENTIAL),
        )

        result = await team.ainvoke("Do the task")
        assert "Step 1" in result
        assert "Step 2" in result

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        """Test parallel team execution."""
        agent1 = VoiceAgent(llm=MockLLM(response="Result A"))
        agent2 = VoiceAgent(llm=MockLLM(response="Result B"))

        roles = [
            AgentRole(name="a", description="Agent A", agent=agent1),
            AgentRole(name="b", description="Agent B", agent=agent2),
        ]

        team = AgentTeam(
            roles=roles,
            config=TeamConfig(execution_mode=ExecutionMode.PARALLEL),
        )

        result = await team.ainvoke("Do both tasks")
        assert "Result A" in result
        assert "Result B" in result

    def test_add_remove_role(self):
        """Test adding and removing roles."""
        team = AgentTeam(roles=[])
        role = AgentRole(
            name="new_role",
            description="New",
            agent=VoiceAgent(llm=MockLLM()),
        )

        team.add_role(role)
        assert "new_role" in team.list_roles()

        team.remove_role("new_role")
        assert "new_role" not in team.list_roles()

    def test_set_execution_order(self):
        """Test setting execution order."""
        agent = VoiceAgent(llm=MockLLM())
        roles = [
            AgentRole(name="a", description="A", agent=agent),
            AgentRole(name="b", description="B", agent=agent),
            AgentRole(name="c", description="C", agent=agent),
        ]

        team = AgentTeam(roles=roles)
        team.set_execution_order(["c", "a", "b"])

        assert team._execution_order == ["c", "a", "b"]


class TestAgentRole:
    """Tests for AgentRole."""

    def test_to_prompt_context(self):
        """Test prompt context generation."""
        role = AgentRole(
            name="researcher",
            description="Research information",
            agent=VoiceAgent(llm=MockLLM()),
            goal="Find accurate data",
            backstory="Expert researcher",
        )

        context = role.to_prompt_context()
        assert "researcher" in context
        assert "Research information" in context
        assert "Find accurate data" in context


class TestCreateTeam:
    """Tests for create_team factory."""

    def test_create_team(self):
        """Test creating team with factory."""
        agents = {
            "agent1": VoiceAgent(llm=MockLLM()),
            "agent2": VoiceAgent(llm=MockLLM()),
        }

        team = create_team(
            agents=agents,
            descriptions={"agent1": "First", "agent2": "Second"},
            execution_mode=ExecutionMode.SEQUENTIAL,
        )

        assert isinstance(team, AgentTeam)
        assert "agent1" in team.roles


# ==================== Test Handoffs ====================


class TestHandoff:
    """Tests for Handoff."""

    def test_create_handoff(self):
        """Test creating handoff."""
        handoff = create_handoff(
            from_agent="general",
            to_agent="specialist",
            reason="Complex query",
        )

        assert handoff.from_agent == "general"
        assert handoff.to_agent == "specialist"
        assert handoff.reason == "Complex query"

    def test_to_message(self):
        """Test converting handoff to message."""
        handoff = Handoff(
            from_agent="a",
            to_agent="b",
            reason="test",
        )

        msg = handoff.to_message()
        assert msg["role"] == "system"
        assert "Handoff" in msg["content"]


class TestHandoffCondition:
    """Tests for HandoffCondition."""

    def test_keyword_condition(self):
        """Test keyword-based condition."""
        condition = keyword_condition(
            keywords=["math", "calculate"],
            target_agent="math_agent",
        )

        state1: MultiAgentState = {"user_query": "Calculate 2+2"}
        state2: MultiAgentState = {"user_query": "Who is Einstein?"}

        assert condition.check(state1) is True
        assert condition.check(state2) is False


class TestHandoffManager:
    """Tests for HandoffManager."""

    def test_register_agent(self):
        """Test registering agents."""
        manager = HandoffManager()
        agent = VoiceAgent(llm=MockLLM())

        manager.register_agent("test", agent)
        assert "test" in manager.list_agents()

        manager.unregister_agent("test")
        assert "test" not in manager.list_agents()

    def test_check_handoff(self):
        """Test checking handoff conditions."""
        manager = HandoffManager()
        manager.register_agent("general", VoiceAgent(llm=MockLLM()))
        manager.register_agent("math", VoiceAgent(llm=MockLLM()))

        condition = keyword_condition(["math"], "math")
        manager.add_condition(condition)

        state: MultiAgentState = {"user_query": "Do some math"}
        handoff = manager.check_handoff(state, "general")

        assert handoff is not None
        assert handoff.to_agent == "math"

    def test_no_self_handoff(self):
        """Test that agents don't handoff to themselves."""
        manager = HandoffManager()
        manager.register_agent("math", VoiceAgent(llm=MockLLM()))

        condition = keyword_condition(["math"], "math")
        manager.add_condition(condition)

        state: MultiAgentState = {"user_query": "Do some math"}
        handoff = manager.check_handoff(state, "math")

        assert handoff is None

    @pytest.mark.asyncio
    async def test_execute_handoff(self):
        """Test executing handoff."""
        manager = HandoffManager()
        target = VoiceAgent(llm=MockLLM(response="Specialist response"))
        manager.register_agent("specialist", target)

        handoff = Handoff(
            from_agent="general",
            to_agent="specialist",
            reason="test",
        )

        state = create_initial_state(user_query="Help me")
        new_state = await manager.execute_handoff(handoff, state)

        assert new_state["answer"] == "Specialist response"
        assert new_state["current_agent"] == "specialist"


# ==================== Test Collaboration ====================


class TestSharedScratchpad:
    """Tests for SharedScratchpad."""

    def test_add_message(self):
        """Test adding messages."""
        pad = SharedScratchpad()
        pad.add_message("user", "Hello", agent_name="user")
        pad.add_message("assistant", "Hi!", agent_name="agent1")

        assert len(pad.messages) == 2
        assert pad.messages[0]["content"] == "Hello"

    def test_notes(self):
        """Test notes."""
        pad = SharedScratchpad()
        pad.add_note("key1", "value1", agent="agent1")

        assert pad.get_note("key1") == "value1"
        assert pad.get_note("missing") is None

    def test_artifacts(self):
        """Test artifacts."""
        pad = SharedScratchpad()
        pad.add_artifact("code", "print('hello')", agent="coder")

        assert pad.get_artifact("code") == "print('hello')"

    def test_get_context(self):
        """Test getting formatted context."""
        pad = SharedScratchpad()
        pad.add_message("assistant", "Result 1", agent_name="agent1")
        pad.add_note("finding", "Important fact")

        context = pad.get_context()
        assert "Result 1" in context
        assert "Important fact" in context

    def test_clear(self):
        """Test clearing scratchpad."""
        pad = SharedScratchpad()
        pad.add_message("user", "Hello")
        pad.add_note("key", "value")
        pad.clear()

        assert len(pad.messages) == 0
        assert len(pad.notes) == 0


class TestCollaborativeAgents:
    """Tests for CollaborativeAgents."""

    @pytest.mark.asyncio
    async def test_round_robin(self):
        """Test round-robin collaboration."""
        agent1 = VoiceAgent(llm=MockLLM(response="Contribution 1"))
        agent2 = VoiceAgent(llm=MockLLM(response="Contribution 2"))

        collab = CollaborativeAgents(
            agents={"agent1": agent1, "agent2": agent2},
            mode=CollaborationMode.ROUND_ROBIN,
            max_rounds=1,
        )

        result = await collab.ainvoke("Discuss this topic")
        # Both agents should have contributed
        assert len(collab.scratchpad.messages) >= 2

    @pytest.mark.asyncio
    async def test_chain_of_thought(self):
        """Test chain-of-thought collaboration."""
        agent1 = VoiceAgent(llm=MockLLM(response="Step 1"))
        agent2 = VoiceAgent(llm=MockLLM(response="Step 2"))
        agent3 = VoiceAgent(llm=MockLLM(response="Final answer"))

        collab = CollaborativeAgents(
            agents={"a": agent1, "b": agent2, "c": agent3},
            mode=CollaborationMode.CHAIN_OF_THOUGHT,
        )

        result = await collab.ainvoke("Solve this")
        assert result == "Final answer"

    @pytest.mark.asyncio
    async def test_voting(self):
        """Test voting collaboration."""
        # All agents propose, then vote
        agent1 = VoiceAgent(llm=MockLLM(response="Proposal A"))
        agent2 = VoiceAgent(llm=MockLLM(response="agent1"))  # Votes for agent1

        collab = CollaborativeAgents(
            agents={"agent1": agent1, "agent2": agent2},
            mode=CollaborationMode.VOTING,
        )

        result = await collab.ainvoke("What should we do?")
        # Result should be one of the proposals
        assert result is not None

    def test_set_agent_order(self):
        """Test setting agent order."""
        agent1 = VoiceAgent(llm=MockLLM())
        agent2 = VoiceAgent(llm=MockLLM())

        collab = CollaborativeAgents(
            agents={"a": agent1, "b": agent2},
        )

        collab.set_agent_order(["b", "a"])
        assert collab._agent_order == ["b", "a"]


class TestCreateCollaboration:
    """Tests for create_collaboration factory."""

    def test_create_collaboration(self):
        """Test creating collaboration with factory."""
        agents = {
            "analyst": VoiceAgent(llm=MockLLM()),
            "critic": VoiceAgent(llm=MockLLM()),
        }

        collab = create_collaboration(
            agents=agents,
            mode=CollaborationMode.DEBATE,
            max_rounds=2,
        )

        assert isinstance(collab, CollaborativeAgents)
        assert collab.mode == CollaborationMode.DEBATE
        assert collab.max_rounds == 2
