"""Multi-agent state management.

Provides shared state structures for multi-agent communication,
following LangGraph's state patterns.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, TypedDict


class AgentMessage(TypedDict, total=False):
    """Message in multi-agent communication.

    Follows OpenAI message format with extensions for
    multi-agent coordination.
    """

    role: str
    """Role: 'user', 'assistant', 'tool', 'system', or agent name."""

    content: str
    """Message content."""

    name: Optional[str]
    """Agent name (for agent-to-agent messages)."""

    tool_calls: Optional[list[dict[str, Any]]]
    """Tool calls made by the agent."""

    tool_call_id: Optional[str]
    """ID of tool call this message responds to."""

    timestamp: Optional[str]
    """ISO timestamp of message."""

    metadata: Optional[dict[str, Any]]
    """Additional metadata."""


class MultiAgentState(TypedDict, total=False):
    """Shared state for multi-agent workflows.

    This is the primary state type passed between agents
    in a VoiceGraph. All agents read from and write to
    this shared state.

    Example:
        >>> state = MultiAgentState(
        ...     user_query="What's the weather?",
        ...     messages=[],
        ...     current_agent="router",
        ... )
        >>> result = await graph.ainvoke(state)
        >>> print(result["answer"])
    """

    # Input/Output
    user_query: str
    """Original user query."""

    answer: str
    """Final answer to return."""

    # Messages
    messages: list[AgentMessage]
    """Conversation history (shared scratchpad)."""

    # Routing
    current_agent: str
    """Currently active agent name."""

    next_agent: str
    """Next agent to route to."""

    # Iteration control
    iteration: int
    """Current iteration count."""

    max_iterations: int
    """Maximum allowed iterations."""

    # Status
    is_complete: bool
    """Whether workflow is complete."""

    error: Optional[str]
    """Error message if any."""

    # Audio (voice-specific)
    audio_input: Optional[bytes]
    """Raw audio input bytes."""

    audio_output: Optional[bytes]
    """Generated audio output bytes."""

    transcription: Optional[str]
    """ASR transcription of audio input."""

    # Metadata
    metadata: dict[str, Any]
    """Arbitrary metadata."""

    # Tool results
    tool_results: list[dict[str, Any]]
    """Results from tool executions."""

    # Agent-specific scratchpads
    agent_scratchpads: dict[str, list[AgentMessage]]
    """Per-agent private scratchpads."""


def create_initial_state(
    user_query: str = "",
    audio_input: Optional[bytes] = None,
    max_iterations: int = 10,
    **kwargs: Any,
) -> MultiAgentState:
    """Create initial multi-agent state.

    Args:
        user_query: User's text query.
        audio_input: Optional audio bytes.
        max_iterations: Max workflow iterations.
        **kwargs: Additional state fields.

    Returns:
        Initialized MultiAgentState.
    """
    state: MultiAgentState = {
        "user_query": user_query,
        "answer": "",
        "messages": [],
        "current_agent": "",
        "next_agent": "",
        "iteration": 0,
        "max_iterations": max_iterations,
        "is_complete": False,
        "error": None,
        "audio_input": audio_input,
        "audio_output": None,
        "transcription": None,
        "metadata": {},
        "tool_results": [],
        "agent_scratchpads": {},
    }
    state.update(kwargs)
    return state


@dataclass
class SharedMemory:
    """Shared memory store for multi-agent collaboration.

    Provides a key-value store that all agents can access.
    Useful for sharing intermediate results, context, or
    coordination data.

    Example:
        >>> memory = SharedMemory()
        >>> memory.set("search_results", ["result1", "result2"])
        >>> results = memory.get("search_results")
    """

    _store: dict[str, Any] = field(default_factory=dict)
    _history: list[tuple[str, str, Any]] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        """Get value by key.

        Args:
            key: Storage key.
            default: Default if key not found.

        Returns:
            Stored value or default.
        """
        return self._store.get(key, default)

    def set(self, key: str, value: Any, agent: str = "unknown") -> None:
        """Set value by key.

        Args:
            key: Storage key.
            value: Value to store.
            agent: Agent making the update.
        """
        self._store[key] = value
        self._history.append((agent, key, value))

    def delete(self, key: str) -> None:
        """Delete value by key.

        Args:
            key: Key to delete.
        """
        self._store.pop(key, None)

    def keys(self) -> list[str]:
        """Get all keys.

        Returns:
            List of keys.
        """
        return list(self._store.keys())

    def clear(self) -> None:
        """Clear all stored values."""
        self._store.clear()
        self._history.clear()

    def get_history(self) -> list[tuple[str, str, Any]]:
        """Get modification history.

        Returns:
            List of (agent, key, value) tuples.
        """
        return self._history.copy()


class ChannelType(str, Enum):
    """Types of message channels."""

    BROADCAST = "broadcast"
    """All agents receive messages."""

    DIRECT = "direct"
    """Point-to-point messaging."""

    TOPIC = "topic"
    """Topic-based subscription."""


@dataclass
class MessageChannel:
    """Channel for agent-to-agent communication.

    Provides pub/sub messaging between agents.

    Example:
        >>> channel = MessageChannel(name="coordination")
        >>> channel.publish("router", {"next": "search_agent"})
        >>> messages = channel.get_messages("search_agent")
    """

    name: str
    """Channel name."""

    channel_type: ChannelType = ChannelType.BROADCAST
    """Channel type."""

    _messages: list[tuple[str, AgentMessage]] = field(default_factory=list)
    """(sender, message) tuples."""

    _subscribers: set[str] = field(default_factory=set)
    """Subscribed agent names."""

    def subscribe(self, agent_name: str) -> None:
        """Subscribe an agent to this channel.

        Args:
            agent_name: Agent to subscribe.
        """
        self._subscribers.add(agent_name)

    def unsubscribe(self, agent_name: str) -> None:
        """Unsubscribe an agent from this channel.

        Args:
            agent_name: Agent to unsubscribe.
        """
        self._subscribers.discard(agent_name)

    def publish(
        self,
        sender: str,
        content: str,
        target: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Publish a message to the channel.

        Args:
            sender: Sending agent name.
            content: Message content.
            target: Target agent (for DIRECT type).
            **kwargs: Additional message fields.
        """
        message: AgentMessage = {
            "role": sender,
            "content": content,
            "name": sender,
            "timestamp": datetime.now().isoformat(),
            "metadata": {"target": target, **kwargs},
        }
        self._messages.append((sender, message))

    def get_messages(
        self,
        agent_name: str,
        since_index: int = 0,
    ) -> list[AgentMessage]:
        """Get messages for an agent.

        Args:
            agent_name: Agent requesting messages.
            since_index: Only get messages after this index.

        Returns:
            List of messages.
        """
        if self.channel_type == ChannelType.BROADCAST:
            return [msg for _, msg in self._messages[since_index:]]

        if self.channel_type == ChannelType.DIRECT:
            return [
                msg
                for _, msg in self._messages[since_index:]
                if msg.get("metadata", {}).get("target") == agent_name
            ]

        # TOPIC - agent must be subscribed
        if agent_name not in self._subscribers:
            return []
        return [msg for _, msg in self._messages[since_index:]]

    def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()


@dataclass
class ChannelState:
    """State container with multiple channels.

    Manages multiple communication channels for
    complex multi-agent workflows.

    Example:
        >>> channels = ChannelState()
        >>> channels.create_channel("coordination")
        >>> channels.publish("coordination", "router", "Starting search")
    """

    _channels: dict[str, MessageChannel] = field(default_factory=dict)

    def create_channel(
        self,
        name: str,
        channel_type: ChannelType = ChannelType.BROADCAST,
    ) -> MessageChannel:
        """Create a new channel.

        Args:
            name: Channel name.
            channel_type: Type of channel.

        Returns:
            Created channel.
        """
        channel = MessageChannel(name=name, channel_type=channel_type)
        self._channels[name] = channel
        return channel

    def get_channel(self, name: str) -> Optional[MessageChannel]:
        """Get channel by name.

        Args:
            name: Channel name.

        Returns:
            Channel or None.
        """
        return self._channels.get(name)

    def publish(
        self,
        channel_name: str,
        sender: str,
        content: str,
        **kwargs: Any,
    ) -> None:
        """Publish to a channel.

        Args:
            channel_name: Target channel.
            sender: Sending agent.
            content: Message content.
            **kwargs: Additional fields.
        """
        channel = self._channels.get(channel_name)
        if channel:
            channel.publish(sender, content, **kwargs)

    def list_channels(self) -> list[str]:
        """List all channel names.

        Returns:
            List of channel names.
        """
        return list(self._channels.keys())
