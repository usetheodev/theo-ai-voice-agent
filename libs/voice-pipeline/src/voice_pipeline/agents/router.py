"""Routing utilities for agent execution flow.

Provides conditional routing similar to LangGraph's routing functions,
allowing agents to dynamically choose execution paths.
"""

from typing import Any, Callable, Literal, Optional, TypeVar

from voice_pipeline.agents.state import AgentState, AgentStatus
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable

T = TypeVar("T")


def tools_condition(state: AgentState) -> Literal["tools", "end"]:
    """Routing condition: execute tools or end.

    Similar to LangGraph's tools_condition. Checks if there are
    pending tool calls in the state.

    Args:
        state: Current agent state.

    Returns:
        "tools" if there are pending tool calls.
        "end" if no tools to execute.

    Example:
        >>> state = AgentState()
        >>> state.pending_tool_calls = [ToolCall(...)]
        >>> tools_condition(state)
        'tools'
        >>>
        >>> state.pending_tool_calls = []
        >>> tools_condition(state)
        'end'
    """
    if state.pending_tool_calls:
        return "tools"
    return "end"


def should_continue(state: AgentState) -> Literal["continue", "end"]:
    """Check if the agent loop should continue.

    Args:
        state: Current agent state.

    Returns:
        "continue" if loop should continue.
        "end" if loop should stop.

    Example:
        >>> state = AgentState(max_iterations=5)
        >>> state.iteration = 3
        >>> should_continue(state)
        'continue'
        >>>
        >>> state.status = AgentStatus.COMPLETED
        >>> should_continue(state)
        'end'
    """
    if state.should_continue():
        return "continue"
    return "end"


def status_condition(state: AgentState) -> str:
    """Route based on agent status.

    Args:
        state: Current agent state.

    Returns:
        Status value as string for routing.

    Example:
        >>> state = AgentState()
        >>> state.status = AgentStatus.ACTING
        >>> status_condition(state)
        'acting'
    """
    return state.status.value


class AgentRouter(VoiceRunnable[AgentState, AgentState]):
    """Conditional router for agent execution flow.

    Routes execution to different VoiceRunnables based on
    conditions evaluated against the agent state.

    Attributes:
        routes: List of (name, condition, target) tuples.
        default: Default target if no condition matches.

    Example:
        >>> from voice_pipeline.agents import ToolNode
        >>>
        >>> tool_node = ToolNode(executor)
        >>> end_node = VoiceLambda(lambda s: s)  # Pass through
        >>>
        >>> router = AgentRouter()
        >>> router.add_route(
        ...     "tools",
        ...     lambda s: bool(s.pending_tool_calls),
        ...     tool_node,
        ... )
        >>> router.add_route(
        ...     "end",
        ...     lambda s: s.status == AgentStatus.COMPLETED,
        ...     end_node,
        ... )
        >>>
        >>> new_state = await router.ainvoke(state)
    """

    name: str = "AgentRouter"

    def __init__(
        self,
        routes: Optional[list[tuple[str, Callable[[AgentState], bool], VoiceRunnable]]] = None,
        default: Optional[VoiceRunnable[AgentState, AgentState]] = None,
    ):
        """Initialize router.

        Args:
            routes: Initial routes as (name, condition, target) tuples.
            default: Default target if no condition matches.
        """
        self.routes: list[tuple[str, Callable[[AgentState], bool], VoiceRunnable]] = (
            routes or []
        )
        self.default = default

    def add_route(
        self,
        name: str,
        condition: Callable[[AgentState], bool],
        target: VoiceRunnable[AgentState, AgentState],
    ) -> "AgentRouter":
        """Add a route to the router.

        Args:
            name: Route name for debugging.
            condition: Function that returns True if this route should be taken.
            target: VoiceRunnable to execute when condition is True.

        Returns:
            Self for method chaining.
        """
        self.routes.append((name, condition, target))
        return self

    def add_conditional_edge(
        self,
        condition: Callable[[AgentState], str],
        edges: dict[str, VoiceRunnable[AgentState, AgentState]],
    ) -> "AgentRouter":
        """Add conditional edges similar to LangGraph.

        The condition function returns a string key that maps to
        a specific target runnable.

        Args:
            condition: Function that returns an edge key.
            edges: Dictionary mapping keys to target runnables.

        Returns:
            Self for method chaining.

        Example:
            >>> router.add_conditional_edge(
            ...     tools_condition,
            ...     {
            ...         "tools": tool_node,
            ...         "end": end_node,
            ...     }
            ... )
        """
        for key, target in edges.items():
            self.add_route(
                name=key,
                condition=lambda s, k=key, c=condition: c(s) == k,
                target=target,
            )
        return self

    async def ainvoke(
        self,
        state: AgentState,
        config: Optional[RunnableConfig] = None,
    ) -> AgentState:
        """Route to appropriate target and execute.

        Evaluates conditions in order and executes the first
        matching route's target.

        Args:
            state: Current agent state.
            config: Optional runnable configuration.

        Returns:
            Updated state from executed target.
        """
        for name, condition, target in self.routes:
            if condition(state):
                return await target.ainvoke(state, config)

        # No condition matched
        if self.default:
            return await self.default.ainvoke(state, config)

        # Return state unchanged
        return state

    def get_route(self, state: AgentState) -> Optional[str]:
        """Get the name of the route that would be taken.

        Useful for debugging or logging.

        Args:
            state: Current agent state.

        Returns:
            Route name or None if no match.
        """
        for name, condition, _ in self.routes:
            if condition(state):
                return name
        return None


class ConditionalBranch(VoiceRunnable[AgentState, AgentState]):
    """Binary conditional branch.

    Executes one of two targets based on a condition.

    Example:
        >>> branch = ConditionalBranch(
        ...     condition=lambda s: s.pending_tool_calls,
        ...     if_true=tool_node,
        ...     if_false=end_node,
        ... )
        >>> new_state = await branch.ainvoke(state)
    """

    name: str = "ConditionalBranch"

    def __init__(
        self,
        condition: Callable[[AgentState], bool],
        if_true: VoiceRunnable[AgentState, AgentState],
        if_false: VoiceRunnable[AgentState, AgentState],
    ):
        """Initialize branch.

        Args:
            condition: Function that returns True or False.
            if_true: Target when condition is True.
            if_false: Target when condition is False.
        """
        self.condition = condition
        self.if_true = if_true
        self.if_false = if_false

    async def ainvoke(
        self,
        state: AgentState,
        config: Optional[RunnableConfig] = None,
    ) -> AgentState:
        """Execute branch based on condition.

        Args:
            state: Current agent state.
            config: Optional configuration.

        Returns:
            Updated state from executed target.
        """
        if self.condition(state):
            return await self.if_true.ainvoke(state, config)
        return await self.if_false.ainvoke(state, config)


def create_tool_router(
    tool_node: VoiceRunnable[AgentState, AgentState],
) -> AgentRouter:
    """Create a router for tool execution flow.

    Convenience function to create a common routing pattern:
    - If pending_tool_calls: execute tool_node
    - Otherwise: pass through

    Args:
        tool_node: ToolNode or similar for executing tools.

    Returns:
        Configured AgentRouter.

    Example:
        >>> from voice_pipeline.agents import ToolNode
        >>>
        >>> tool_node = ToolNode(executor)
        >>> router = create_tool_router(tool_node)
        >>>
        >>> # Will execute tools if pending, otherwise pass through
        >>> new_state = await router.ainvoke(state)
    """

    class PassThrough(VoiceRunnable[AgentState, AgentState]):
        async def ainvoke(
            self, state: AgentState, config: Optional[RunnableConfig] = None
        ) -> AgentState:
            return state

    return AgentRouter(
        routes=[
            ("tools", lambda s: bool(s.pending_tool_calls), tool_node),
        ],
        default=PassThrough(),
    )
