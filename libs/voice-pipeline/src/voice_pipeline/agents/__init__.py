"""Voice Agent module for building intelligent voice assistants.

This module provides the core components for creating voice agents
with tool calling support, following patterns from LangChain,
LangGraph, and CrewAI.

Quick Start:
    >>> from voice_pipeline.agents import VoiceAgent
    >>> from voice_pipeline.tools import voice_tool
    >>>
    >>> @voice_tool
    ... def get_weather(location: str) -> str:
    ...     '''Get weather for a location.'''
    ...     return f"Weather in {location}: Sunny, 25C"
    >>>
    >>> agent = VoiceAgent(
    ...     llm=my_llm,
    ...     tools=[get_weather],
    ... )
    >>>
    >>> response = await agent.ainvoke("What's the weather in Tokyo?")
    >>> print(response)  # "The weather in Tokyo is sunny, 25C."

Pipeline Composition:
    >>> from voice_pipeline import ASRInterface, TTSInterface
    >>>
    >>> # Create voice pipeline with agent
    >>> pipeline = asr | agent | tts
    >>>
    >>> # Stream audio response
    >>> async for audio in pipeline.astream(audio_input):
    ...     play(audio)

Components:
    - VoiceAgent: Main agent class
    - AgentState: Execution state management
    - AgentLoop: ReAct execution loop
    - ToolNode: Tool execution as VoiceRunnable
    - AgentRouter: Conditional routing
"""

# State management
from voice_pipeline.agents.state import (
    AgentMessage,
    AgentState,
    AgentStatus,
)

# Tool execution
from voice_pipeline.agents.tool_node import (
    BatchToolNode,
    ToolNode,
)

# Execution loop
from voice_pipeline.agents.loop import (
    AgentLoop,
)

# Routing
from voice_pipeline.agents.router import (
    AgentRouter,
    ConditionalBranch,
    create_tool_router,
    should_continue,
    status_condition,
    tools_condition,
)

# Main agent class
from voice_pipeline.agents.base import (
    StreamingVoiceAgent,
    VoiceAgent,
    VoiceAgentBuilder,
    create_voice_agent,
)

__all__ = [
    # State
    "AgentState",
    "AgentMessage",
    "AgentStatus",
    # Tool execution
    "ToolNode",
    "BatchToolNode",
    # Loop
    "AgentLoop",
    # Routing
    "AgentRouter",
    "ConditionalBranch",
    "tools_condition",
    "should_continue",
    "status_condition",
    "create_tool_router",
    # Agent
    "VoiceAgent",
    "VoiceAgentBuilder",
    "StreamingVoiceAgent",
    "create_voice_agent",
]
