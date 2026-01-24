"""Agent state management for voice agents.

Provides data structures for managing agent state during
the ReAct (Reasoning + Acting) execution loop.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Optional

from voice_pipeline.tools.executor import ToolCall


class AgentStatus(Enum):
    """Status of the agent execution loop."""

    PENDING = "pending"
    """Agent is waiting to start."""

    THINKING = "thinking"
    """Agent is reasoning about what to do."""

    ACTING = "acting"
    """Agent has decided to call tools."""

    OBSERVING = "observing"
    """Agent is processing tool results."""

    COMPLETED = "completed"
    """Agent has finished with a final response."""

    ERROR = "error"
    """Agent encountered an error."""


@dataclass
class AgentMessage:
    """Message in the agent conversation context.

    Represents a single message in the agent's conversation history,
    with support for tool calls and tool results.

    Attributes:
        role: Message role (user, assistant, tool, system).
        content: Text content of the message.
        tool_calls: List of tool calls (for assistant messages).
        tool_call_id: ID of the tool call this message responds to.
        name: Name of the tool (when role=tool).

    Example:
        >>> # User message
        >>> msg = AgentMessage(role="user", content="What time is it?")
        >>>
        >>> # Assistant with tool call
        >>> msg = AgentMessage(
        ...     role="assistant",
        ...     content="",
        ...     tool_calls=[{"id": "1", "name": "get_time", "arguments": {}}]
        ... )
        >>>
        >>> # Tool result
        >>> msg = AgentMessage(
        ...     role="tool",
        ...     content="14:30",
        ...     tool_call_id="1",
        ...     name="get_time"
        ... )
    """

    role: Literal["user", "assistant", "tool", "system"]
    """Message role."""

    content: str
    """Message content."""

    tool_calls: Optional[list[dict[str, Any]]] = None
    """Tool calls for assistant messages (OpenAI format)."""

    tool_call_id: Optional[str] = None
    """Tool call ID for tool result messages."""

    name: Optional[str] = None
    """Tool name for tool result messages."""

    def to_openai_dict(self) -> dict[str, Any]:
        """Convert to OpenAI message format.

        Returns:
            Dictionary compatible with OpenAI chat API.
        """
        msg: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }

        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls

        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id

        if self.name and self.role == "tool":
            msg["name"] = self.name

        return msg

    def to_anthropic_dict(self) -> dict[str, Any]:
        """Convert to Anthropic message format.

        Returns:
            Dictionary compatible with Anthropic messages API.
        """
        if self.role == "tool":
            # Anthropic uses tool_result content blocks
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": self.tool_call_id,
                        "content": self.content,
                    }
                ],
            }

        if self.tool_calls:
            # Anthropic uses tool_use content blocks
            content_blocks = []
            if self.content:
                content_blocks.append({"type": "text", "text": self.content})
            for tc in self.tool_calls:
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": tc.get("function", {}).get("name", tc.get("name", "")),
                        "input": tc.get("function", {}).get(
                            "arguments", tc.get("arguments", {})
                        ),
                    }
                )
            return {"role": "assistant", "content": content_blocks}

        return {
            "role": self.role if self.role != "system" else "user",
            "content": self.content,
        }

    def to_dict(self, format: str = "openai") -> dict[str, Any]:
        """Convert to message format.

        Args:
            format: Output format ("openai" or "anthropic").

        Returns:
            Dictionary in the specified format.
        """
        if format == "anthropic":
            return self.to_anthropic_dict()
        return self.to_openai_dict()


@dataclass
class AgentState:
    """Complete state of the agent during execution.

    Manages conversation history, pending tool calls, execution status,
    and iteration tracking for the ReAct loop.

    Attributes:
        messages: Conversation history.
        pending_tool_calls: Tool calls waiting to be executed.
        status: Current execution status.
        iteration: Current loop iteration.
        max_iterations: Maximum allowed iterations.
        final_response: Final response when completed.
        error: Error message if failed.
        metadata: Additional state metadata.

    Example:
        >>> state = AgentState(max_iterations=5)
        >>> state.add_user_message("What's the weather?")
        >>> state.add_assistant_message("Let me check...", tool_calls=[...])
        >>> state.pending_tool_calls = [ToolCall(...)]
        >>>
        >>> # Execute tools...
        >>> state.add_tool_result("call_1", "get_weather", "Sunny, 25C")
        >>>
        >>> # Check if should continue
        >>> if state.should_continue():
        ...     # Continue loop
    """

    messages: list[AgentMessage] = field(default_factory=list)
    """Conversation history."""

    pending_tool_calls: list[ToolCall] = field(default_factory=list)
    """Tool calls pending execution."""

    status: AgentStatus = AgentStatus.PENDING
    """Current execution status."""

    iteration: int = 0
    """Current loop iteration."""

    max_iterations: int = 10
    """Maximum allowed iterations."""

    final_response: Optional[str] = None
    """Final response when completed."""

    error: Optional[str] = None
    """Error message if status is ERROR."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional state metadata."""

    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation.

        Args:
            content: User message content.
        """
        self.messages.append(AgentMessage(role="user", content=content))

    def add_system_message(self, content: str) -> None:
        """Add a system message to the conversation.

        Args:
            content: System message content.
        """
        self.messages.append(AgentMessage(role="system", content=content))

    def add_assistant_message(
        self,
        content: str,
        tool_calls: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """Add an assistant message to the conversation.

        Args:
            content: Assistant message content.
            tool_calls: Optional list of tool calls in OpenAI format.
        """
        self.messages.append(
            AgentMessage(role="assistant", content=content, tool_calls=tool_calls)
        )

    def add_tool_result(
        self,
        tool_call_id: str,
        name: str,
        result: str,
    ) -> None:
        """Add a tool result to the conversation.

        Args:
            tool_call_id: ID of the tool call this responds to.
            name: Name of the tool.
            result: Result content from the tool.
        """
        self.messages.append(
            AgentMessage(
                role="tool",
                content=result,
                tool_call_id=tool_call_id,
                name=name,
            )
        )

    def should_continue(self) -> bool:
        """Check if the agent loop should continue.

        Returns:
            True if loop should continue, False otherwise.
        """
        # Don't continue if completed or errored
        if self.status in (AgentStatus.COMPLETED, AgentStatus.ERROR):
            return False

        # Don't continue if max iterations reached
        if self.iteration >= self.max_iterations:
            return False

        return True

    def to_messages(self, format: str = "openai") -> list[dict[str, Any]]:
        """Convert message history to LLM format.

        Args:
            format: Output format ("openai" or "anthropic").

        Returns:
            List of message dictionaries.
        """
        return [msg.to_dict(format) for msg in self.messages]

    def get_last_assistant_message(self) -> Optional[AgentMessage]:
        """Get the last assistant message.

        Returns:
            Last assistant message or None.
        """
        for msg in reversed(self.messages):
            if msg.role == "assistant":
                return msg
        return None

    def get_last_tool_calls(self) -> list[dict[str, Any]]:
        """Get tool calls from the last assistant message.

        Returns:
            List of tool calls or empty list.
        """
        last_msg = self.get_last_assistant_message()
        if last_msg and last_msg.tool_calls:
            return last_msg.tool_calls
        return []

    def clear(self) -> None:
        """Clear the state for a new conversation."""
        self.messages = []
        self.pending_tool_calls = []
        self.status = AgentStatus.PENDING
        self.iteration = 0
        self.final_response = None
        self.error = None
        self.metadata = {}

    def copy(self) -> "AgentState":
        """Create a copy of the state.

        Returns:
            New AgentState with copied data.
        """
        return AgentState(
            messages=self.messages.copy(),
            pending_tool_calls=self.pending_tool_calls.copy(),
            status=self.status,
            iteration=self.iteration,
            max_iterations=self.max_iterations,
            final_response=self.final_response,
            error=self.error,
            metadata=self.metadata.copy(),
        )
