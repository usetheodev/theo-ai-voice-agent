"""Handoff pattern for agent-to-agent transfers.

Handoffs allow smooth transitions between agents,
transferring context and control.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union

from voice_pipeline.agents.base import VoiceAgent
from voice_pipeline.multi_agent.state import AgentMessage, MultiAgentState


@dataclass
class HandoffCondition:
    """Condition that triggers a handoff.

    Attributes:
        name: Condition identifier.
        check: Function that returns True if handoff should occur.
        priority: Priority (higher = checked first).
    """

    name: str
    """Condition identifier."""

    check: Callable[[MultiAgentState], bool]
    """Function that checks if handoff should occur."""

    target_agent: str
    """Agent to hand off to."""

    priority: int = 0
    """Priority (higher = checked first)."""

    transfer_context: bool = True
    """Whether to transfer conversation context."""

    message: str = ""
    """Optional message to include in handoff."""


@dataclass
class Handoff:
    """A handoff between agents.

    Represents the transfer of control from one agent to another,
    including context and state.

    Attributes:
        from_agent: Source agent name.
        to_agent: Target agent name.
        reason: Why handoff occurred.
        context: Transferred context.
    """

    from_agent: str
    """Source agent name."""

    to_agent: str
    """Target agent name."""

    reason: str = ""
    """Why handoff occurred."""

    context: dict[str, Any] = field(default_factory=dict)
    """Transferred context."""

    messages: list[AgentMessage] = field(default_factory=list)
    """Conversation history to transfer."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata."""

    def to_message(self) -> AgentMessage:
        """Convert handoff to a message.

        Returns:
            AgentMessage describing the handoff.
        """
        return AgentMessage(
            role="system",
            content=f"Handoff from {self.from_agent} to {self.to_agent}: {self.reason}",
            metadata={
                "handoff": True,
                "from_agent": self.from_agent,
                "to_agent": self.to_agent,
                "context": self.context,
            },
        )


class HandoffManager:
    """Manages handoffs between agents.

    HandoffManager coordinates agent-to-agent transfers,
    evaluating conditions and executing handoffs.

    Example:
        >>> manager = HandoffManager()
        >>>
        >>> # Register agents
        >>> manager.register_agent("general", general_agent)
        >>> manager.register_agent("specialist", specialist_agent)
        >>>
        >>> # Add handoff condition
        >>> manager.add_condition(
        ...     HandoffCondition(
        ...         name="complex_query",
        ...         check=lambda s: "complex" in s.get("user_query", ""),
        ...         target_agent="specialist",
        ...     )
        ... )
        >>>
        >>> # Check and execute handoff
        >>> handoff = await manager.check_handoff(state, "general")
        >>> if handoff:
        ...     result = await manager.execute_handoff(handoff, state)
    """

    def __init__(self):
        """Initialize the handoff manager."""
        self._agents: dict[str, VoiceAgent] = {}
        self._conditions: list[HandoffCondition] = []
        self._handoff_history: list[Handoff] = []

    def register_agent(self, name: str, agent: VoiceAgent) -> None:
        """Register an agent for handoffs.

        Args:
            name: Agent identifier.
            agent: Agent instance.
        """
        self._agents[name] = agent

    def unregister_agent(self, name: str) -> None:
        """Unregister an agent.

        Args:
            name: Agent identifier.
        """
        self._agents.pop(name, None)

    def add_condition(self, condition: HandoffCondition) -> None:
        """Add a handoff condition.

        Args:
            condition: Condition to add.
        """
        self._conditions.append(condition)
        # Sort by priority (highest first)
        self._conditions.sort(key=lambda c: c.priority, reverse=True)

    def remove_condition(self, name: str) -> None:
        """Remove a handoff condition.

        Args:
            name: Condition name.
        """
        self._conditions = [c for c in self._conditions if c.name != name]

    def check_handoff(
        self,
        state: MultiAgentState,
        current_agent: str,
    ) -> Optional[Handoff]:
        """Check if a handoff should occur.

        Evaluates all conditions in priority order.

        Args:
            state: Current state.
            current_agent: Currently active agent.

        Returns:
            Handoff if triggered, None otherwise.
        """
        for condition in self._conditions:
            try:
                if condition.check(state):
                    # Don't handoff to self
                    if condition.target_agent == current_agent:
                        continue

                    # Create handoff
                    handoff = Handoff(
                        from_agent=current_agent,
                        to_agent=condition.target_agent,
                        reason=condition.name,
                        messages=state.get("messages", []) if condition.transfer_context else [],
                        context={
                            "user_query": state.get("user_query", ""),
                            "condition": condition.name,
                        },
                    )
                    return handoff

            except Exception:
                # Condition check failed, continue
                continue

        return None

    async def execute_handoff(
        self,
        handoff: Handoff,
        state: MultiAgentState,
    ) -> MultiAgentState:
        """Execute a handoff.

        Args:
            handoff: Handoff to execute.
            state: Current state.

        Returns:
            Updated state after handoff.
        """
        target_agent = self._agents.get(handoff.to_agent)
        if not target_agent:
            state["error"] = f"Handoff target '{handoff.to_agent}' not found"
            return state

        # Record handoff
        self._handoff_history.append(handoff)

        # Add handoff message
        messages = state.get("messages", [])
        messages.append(handoff.to_message())
        state["messages"] = messages

        # Update state
        state["current_agent"] = handoff.to_agent

        # Execute target agent
        user_query = state.get("user_query", "")
        result = await target_agent.ainvoke(user_query)

        # Update state with result
        state["answer"] = result
        messages.append(
            AgentMessage(
                role="assistant",
                name=handoff.to_agent,
                content=result,
            )
        )

        return state

    def get_handoff_history(self) -> list[Handoff]:
        """Get history of handoffs.

        Returns:
            List of past handoffs.
        """
        return self._handoff_history.copy()

    def clear_history(self) -> None:
        """Clear handoff history."""
        self._handoff_history.clear()

    def list_agents(self) -> list[str]:
        """List registered agents.

        Returns:
            List of agent names.
        """
        return list(self._agents.keys())


def create_handoff(
    from_agent: str,
    to_agent: str,
    reason: str = "",
    context: Optional[dict[str, Any]] = None,
) -> Handoff:
    """Create a handoff object.

    Args:
        from_agent: Source agent.
        to_agent: Target agent.
        reason: Handoff reason.
        context: Optional context.

    Returns:
        Handoff instance.

    Example:
        >>> handoff = create_handoff(
        ...     from_agent="general",
        ...     to_agent="specialist",
        ...     reason="Complex query detected",
        ... )
    """
    return Handoff(
        from_agent=from_agent,
        to_agent=to_agent,
        reason=reason,
        context=context or {},
    )


def keyword_condition(
    keywords: list[str],
    target_agent: str,
    name: Optional[str] = None,
) -> HandoffCondition:
    """Create a keyword-based handoff condition.

    Triggers handoff when any keyword is in the query.

    Args:
        keywords: Keywords to match.
        target_agent: Target agent.
        name: Condition name.

    Returns:
        HandoffCondition.

    Example:
        >>> condition = keyword_condition(
        ...     keywords=["math", "calculate", "equation"],
        ...     target_agent="math_agent",
        ... )
    """

    def check(state: MultiAgentState) -> bool:
        query = state.get("user_query", "").lower()
        return any(kw.lower() in query for kw in keywords)

    return HandoffCondition(
        name=name or f"keywords_{target_agent}",
        check=check,
        target_agent=target_agent,
    )


def intent_condition(
    intent_checker: Callable[[str], bool],
    target_agent: str,
    name: Optional[str] = None,
) -> HandoffCondition:
    """Create an intent-based handoff condition.

    Uses a custom function to check user intent.

    Args:
        intent_checker: Function that checks intent.
        target_agent: Target agent.
        name: Condition name.

    Returns:
        HandoffCondition.

    Example:
        >>> condition = intent_condition(
        ...     intent_checker=lambda q: "book" in q and "meeting" in q,
        ...     target_agent="scheduling_agent",
        ... )
    """

    def check(state: MultiAgentState) -> bool:
        query = state.get("user_query", "")
        return intent_checker(query)

    return HandoffCondition(
        name=name or f"intent_{target_agent}",
        check=check,
        target_agent=target_agent,
    )
