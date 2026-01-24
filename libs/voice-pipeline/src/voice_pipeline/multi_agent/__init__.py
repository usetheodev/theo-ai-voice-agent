"""Multi-Agent system for voice pipelines.

This module provides LangGraph-style multi-agent orchestration
optimized for voice applications.

Patterns supported:
- Multi-Agent Collaboration: Shared scratchpad between agents
- Agent Supervisor: Central coordinator routing to specialists
- Hierarchical Teams: Nested agent graphs

Example - Supervisor Pattern:
    >>> from voice_pipeline.multi_agent import (
    ...     VoiceGraph,
    ...     SupervisorAgent,
    ...     create_supervisor,
    ... )
    >>>
    >>> # Define specialist agents
    >>> search_agent = VoiceAgent(llm=llm, tools=[search_tool])
    >>> math_agent = VoiceAgent(llm=llm, tools=[calculator])
    >>>
    >>> # Create supervisor
    >>> supervisor = create_supervisor(
    ...     llm=llm,
    ...     agents={"search": search_agent, "math": math_agent},
    ... )
    >>>
    >>> # Run
    >>> result = await supervisor.ainvoke("What is 25 * 4?")

Example - Graph Pattern:
    >>> from voice_pipeline.multi_agent import VoiceGraph, END
    >>>
    >>> # Build graph
    >>> graph = VoiceGraph(MultiAgentState)
    >>> graph.add_node("router", router_agent)
    >>> graph.add_node("search", search_agent)
    >>> graph.add_node("math", math_agent)
    >>>
    >>> graph.add_edge(START, "router")
    >>> graph.add_conditional_edges("router", routing_logic)
    >>> graph.add_edge("search", END)
    >>> graph.add_edge("math", END)
    >>>
    >>> app = graph.compile()
    >>> result = await app.ainvoke({"user_query": "Hello"})
"""

# Graph
from voice_pipeline.multi_agent.graph import (
    END,
    START,
    CompiledGraph,
    Edge,
    Node,
    VoiceGraph,
)

# State
from voice_pipeline.multi_agent.state import (
    AgentMessage as MultiAgentMessage,
    ChannelState,
    MessageChannel,
    MultiAgentState,
    SharedMemory,
    create_initial_state,
)

# Supervisor
from voice_pipeline.multi_agent.supervisor import (
    RoutingDecision,
    SupervisorAgent,
    SupervisorConfig,
    create_supervisor,
)

# Team
from voice_pipeline.multi_agent.team import (
    AgentRole,
    AgentTeam,
    TeamConfig,
    create_team,
)

# Handoffs
from voice_pipeline.multi_agent.handoff import (
    Handoff,
    HandoffCondition,
    HandoffManager,
    create_handoff,
    keyword_condition,
    intent_condition,
)

# Collaboration
from voice_pipeline.multi_agent.collaboration import (
    CollaborationMode,
    CollaborativeAgents,
    SharedScratchpad,
    create_collaboration,
)

__all__ = [
    # Graph
    "VoiceGraph",
    "CompiledGraph",
    "Node",
    "Edge",
    "START",
    "END",
    # State
    "MultiAgentState",
    "MultiAgentMessage",
    "SharedMemory",
    "MessageChannel",
    "ChannelState",
    "create_initial_state",
    # Supervisor
    "SupervisorAgent",
    "SupervisorConfig",
    "RoutingDecision",
    "create_supervisor",
    # Team
    "AgentTeam",
    "AgentRole",
    "TeamConfig",
    "create_team",
    # Handoffs
    "Handoff",
    "HandoffCondition",
    "HandoffManager",
    "create_handoff",
    "keyword_condition",
    "intent_condition",
    # Collaboration
    "CollaborativeAgents",
    "SharedScratchpad",
    "CollaborationMode",
    "create_collaboration",
]
