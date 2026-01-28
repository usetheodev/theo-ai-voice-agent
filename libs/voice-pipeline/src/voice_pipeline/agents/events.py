"""Stream event types for agent execution.

Provides typed events for streaming output from the agent loop,
allowing callers to distinguish between different types of content.

Example:
    >>> async for event in agent.astream_events("Hello"):
    ...     if event.is_response_token:
    ...         print(event.data, end="")
    ...     elif event.type == StreamEventType.TOOL_START:
    ...         print(f"[Calling {event.metadata['tool_name']}...]")
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class StreamEventType(Enum):
    """Types of events emitted during agent streaming."""

    TOKEN = "token"
    """Token from the LLM response (part of final answer)."""

    FEEDBACK = "feedback"
    """Verbal feedback phrase during tool execution (e.g., "Let me check...")."""

    TOOL_START = "tool_start"
    """Tool execution started."""

    TOOL_END = "tool_end"
    """Tool execution completed."""

    THINKING = "thinking"
    """Agent started thinking phase (LLM call)."""

    ITERATION = "iteration"
    """New loop iteration started."""

    ERROR = "error"
    """Error occurred during execution."""

    DONE = "done"
    """Agent finished with final response."""


@dataclass
class StreamEvent:
    """Event emitted during agent streaming.

    Provides typed information about what's happening in the agent loop,
    allowing callers to handle different event types appropriately.

    Attributes:
        type: The type of event.
        data: The event payload (token text, error message, etc.).
        metadata: Additional event-specific metadata.

    Example:
        >>> event = StreamEvent(
        ...     type=StreamEventType.TOKEN,
        ...     data="Hello",
        ... )
        >>> print(event.is_response_token)  # True
        >>>
        >>> event = StreamEvent(
        ...     type=StreamEventType.TOOL_START,
        ...     data="get_weather",
        ...     metadata={"tool_name": "get_weather", "arguments": {"city": "NYC"}},
        ... )
    """

    type: StreamEventType
    """The type of this event."""

    data: str = ""
    """The event payload (token text, tool name, error message, etc.)."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata for the event."""

    @property
    def is_response_token(self) -> bool:
        """Check if this event is a response token.

        Returns:
            True if this is a TOKEN event (part of final response).
        """
        return self.type == StreamEventType.TOKEN

    @property
    def is_feedback(self) -> bool:
        """Check if this event is a feedback phrase.

        Returns:
            True if this is a FEEDBACK event.
        """
        return self.type == StreamEventType.FEEDBACK

    @property
    def is_tool_event(self) -> bool:
        """Check if this event is related to tool execution.

        Returns:
            True if this is TOOL_START or TOOL_END.
        """
        return self.type in (StreamEventType.TOOL_START, StreamEventType.TOOL_END)

    @property
    def is_error(self) -> bool:
        """Check if this event represents an error.

        Returns:
            True if this is an ERROR event.
        """
        return self.type == StreamEventType.ERROR

    @property
    def is_done(self) -> bool:
        """Check if this event signals completion.

        Returns:
            True if this is a DONE event.
        """
        return self.type == StreamEventType.DONE

    def __repr__(self) -> str:
        """Readable representation."""
        if self.data:
            return f"StreamEvent({self.type.value}: {self.data[:50]!r})"
        return f"StreamEvent({self.type.value})"


@dataclass
class StateDelta:
    """Incremental state changes from a streaming iteration.

    Used to propagate state updates from _think_and_act_stream
    back to the caller without copying the entire state.

    Attributes:
        status: New status if changed.
        iteration_increment: Whether to increment iteration counter.
        final_response: Final response if completed.
        error: Error message if failed.
        pending_tool_calls: New pending tool calls if any.
        add_message: Message to add to history.
    """

    status: Optional["AgentStatus"] = None
    """New status if changed."""

    iteration_increment: bool = False
    """Whether to increment the iteration counter."""

    final_response: Optional[str] = None
    """Final response if agent completed."""

    error: Optional[str] = None
    """Error message if agent failed."""

    pending_tool_calls: Optional[list] = None
    """Pending tool calls to set."""

    add_message: Optional[dict] = None
    """Message to add to conversation history."""

    def apply_to(self, state: "AgentState") -> "AgentState":
        """Apply this delta to a state.

        Args:
            state: The state to update.

        Returns:
            The updated state (same instance, modified in place).
        """
        # Import here to avoid circular import
        from voice_pipeline.agents.state import AgentMessage, AgentStatus

        if self.status is not None:
            state.status = self.status

        if self.iteration_increment:
            state.iteration += 1

        if self.final_response is not None:
            state.final_response = self.final_response

        if self.error is not None:
            state.error = self.error
            state.status = AgentStatus.ERROR

        if self.pending_tool_calls is not None:
            state.pending_tool_calls = self.pending_tool_calls

        if self.add_message is not None:
            msg = self.add_message
            if msg.get("role") == "assistant":
                state.add_assistant_message(
                    content=msg.get("content", ""),
                    tool_calls=msg.get("tool_calls"),
                )
            elif msg.get("role") == "user":
                state.add_user_message(msg.get("content", ""))
            elif msg.get("role") == "tool":
                state.add_tool_result(
                    tool_call_id=msg.get("tool_call_id", ""),
                    name=msg.get("name", ""),
                    result=msg.get("content", ""),
                )

        return state


# Type alias for the streaming result
StreamOutput = tuple[StreamEvent, Optional[StateDelta]]
"""A streaming output: event and optional state delta."""
