"""VoiceGraph - LangGraph-style state graph for voice agents.

Provides a graph-based workflow builder for multi-agent systems,
following the LangGraph StateGraph pattern.
"""

from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Literal,
    Optional,
    TypeVar,
    Union,
)

from voice_pipeline.multi_agent.state import MultiAgentState
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable

# Type for state
StateType = TypeVar("StateType", bound=dict)

# Special node markers
START = "__start__"
END = "__end__"


@dataclass
class Node:
    """A node in the voice graph.

    Represents a processing step that takes state and returns
    updated state.

    Attributes:
        name: Node identifier.
        func: Processing function.
        is_async: Whether function is async.
    """

    name: str
    """Node identifier."""

    func: Union[Callable, VoiceRunnable]
    """Processing function or runnable."""

    is_async: bool = True
    """Whether function is async."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata."""

    async def execute(
        self,
        state: StateType,
        config: Optional[RunnableConfig] = None,
    ) -> StateType:
        """Execute the node.

        Args:
            state: Current state.
            config: Optional configuration.

        Returns:
            Updated state.
        """
        if isinstance(self.func, VoiceRunnable):
            result = await self.func.ainvoke(state, config)
        elif self.is_async:
            result = await self.func(state)
        else:
            result = self.func(state)

        # If result is a dict, merge with state
        if isinstance(result, dict):
            return {**state, **result}
        return result


@dataclass
class Edge:
    """An edge connecting nodes in the graph.

    Attributes:
        source: Source node name.
        target: Target node name.
        condition: Optional condition function.
    """

    source: str
    """Source node name."""

    target: str
    """Target node name (or special markers)."""

    condition: Optional[Callable[[StateType], str]] = None
    """Optional condition function for conditional edges."""


class VoiceGraph:
    """LangGraph-style state graph for voice agent workflows.

    VoiceGraph allows you to define multi-agent workflows as a
    directed graph where nodes are agents/functions and edges
    define the flow between them.

    Example:
        >>> from voice_pipeline.multi_agent import VoiceGraph, START, END
        >>>
        >>> # Define nodes
        >>> def router(state):
        ...     if "math" in state["user_query"].lower():
        ...         return {"next_agent": "math"}
        ...     return {"next_agent": "search"}
        >>>
        >>> # Build graph
        >>> graph = VoiceGraph(MultiAgentState)
        >>> graph.add_node("router", router)
        >>> graph.add_node("search", search_agent)
        >>> graph.add_node("math", math_agent)
        >>>
        >>> # Define edges
        >>> graph.add_edge(START, "router")
        >>> graph.add_conditional_edges(
        ...     "router",
        ...     lambda s: s["next_agent"],
        ...     {"search": "search", "math": "math"},
        ... )
        >>> graph.add_edge("search", END)
        >>> graph.add_edge("math", END)
        >>>
        >>> # Compile and run
        >>> app = graph.compile()
        >>> result = await app.ainvoke({"user_query": "What is 2+2?"})
    """

    def __init__(
        self,
        state_schema: type = MultiAgentState,
        name: str = "VoiceGraph",
    ):
        """Initialize the graph.

        Args:
            state_schema: Type definition for state.
            name: Graph name for debugging.
        """
        self.state_schema = state_schema
        self.name = name
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []
        self._entry_point: Optional[str] = None
        self._compiled = False

    def add_node(
        self,
        name: str,
        func: Union[Callable, VoiceRunnable],
        metadata: Optional[dict[str, Any]] = None,
    ) -> "VoiceGraph":
        """Add a node to the graph.

        Args:
            name: Node identifier.
            func: Processing function or VoiceRunnable.
            metadata: Optional metadata.

        Returns:
            Self for chaining.

        Raises:
            ValueError: If node already exists.
        """
        if name in self._nodes:
            raise ValueError(f"Node '{name}' already exists")

        if name in (START, END):
            raise ValueError(f"Cannot use reserved name '{name}'")

        # Check if function is async
        import asyncio

        is_async = asyncio.iscoroutinefunction(func) or isinstance(
            func, VoiceRunnable
        )

        self._nodes[name] = Node(
            name=name,
            func=func,
            is_async=is_async,
            metadata=metadata or {},
        )
        return self

    def add_edge(
        self,
        source: str,
        target: str,
    ) -> "VoiceGraph":
        """Add a simple edge between nodes.

        Args:
            source: Source node (or START).
            target: Target node (or END).

        Returns:
            Self for chaining.

        Raises:
            ValueError: If source/target don't exist.
        """
        self._validate_edge(source, target)
        self._edges.append(Edge(source=source, target=target))

        if source == START:
            self._entry_point = target

        return self

    def add_conditional_edges(
        self,
        source: str,
        condition: Callable[[StateType], str],
        path_map: Optional[dict[str, str]] = None,
    ) -> "VoiceGraph":
        """Add conditional edges from a node.

        The condition function receives the state and returns
        the name of the next node to route to.

        Args:
            source: Source node.
            condition: Function that returns next node name.
            path_map: Optional mapping of condition results to node names.

        Returns:
            Self for chaining.

        Example:
            >>> graph.add_conditional_edges(
            ...     "router",
            ...     lambda s: s["next_agent"],
            ...     {"search": "search_agent", "math": "math_agent"},
            ... )
        """
        if source not in self._nodes and source != START:
            raise ValueError(f"Source node '{source}' does not exist")

        def wrapped_condition(state: StateType) -> str:
            result = condition(state)
            if path_map:
                return path_map.get(result, result)
            return result

        self._edges.append(
            Edge(source=source, target="__conditional__", condition=wrapped_condition)
        )
        return self

    def set_entry_point(self, node_name: str) -> "VoiceGraph":
        """Set the entry point node.

        Args:
            node_name: Node to start from.

        Returns:
            Self for chaining.
        """
        if node_name not in self._nodes:
            raise ValueError(f"Node '{node_name}' does not exist")
        self._entry_point = node_name
        return self

    def _validate_edge(self, source: str, target: str) -> None:
        """Validate edge endpoints.

        Args:
            source: Source node.
            target: Target node.

        Raises:
            ValueError: If nodes don't exist.
        """
        if source != START and source not in self._nodes:
            raise ValueError(f"Source node '{source}' does not exist")

        if target != END and target not in self._nodes:
            raise ValueError(f"Target node '{target}' does not exist")

    def compile(self) -> "CompiledGraph":
        """Compile the graph into an executable.

        Returns:
            CompiledGraph ready for execution.

        Raises:
            ValueError: If graph is invalid.
        """
        if not self._entry_point:
            raise ValueError("No entry point defined. Use add_edge(START, ...) or set_entry_point()")

        self._compiled = True
        return CompiledGraph(
            nodes=self._nodes.copy(),
            edges=self._edges.copy(),
            entry_point=self._entry_point,
            state_schema=self.state_schema,
            name=self.name,
        )

    def get_graph_structure(self) -> dict[str, Any]:
        """Get graph structure for visualization.

        Returns:
            Dict with nodes and edges.
        """
        return {
            "nodes": list(self._nodes.keys()),
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "conditional": e.condition is not None,
                }
                for e in self._edges
            ],
            "entry_point": self._entry_point,
        }


class CompiledGraph(VoiceRunnable[StateType, StateType]):
    """Compiled graph ready for execution.

    This is returned by VoiceGraph.compile() and can be
    executed with ainvoke() or streamed with astream().
    """

    name: str = "CompiledGraph"

    def __init__(
        self,
        nodes: dict[str, Node],
        edges: list[Edge],
        entry_point: str,
        state_schema: type,
        name: str = "CompiledGraph",
    ):
        """Initialize compiled graph.

        Args:
            nodes: Node dictionary.
            edges: Edge list.
            entry_point: Starting node.
            state_schema: State type.
            name: Graph name.
        """
        self._nodes = nodes
        self._edges = edges
        self._entry_point = entry_point
        self._state_schema = state_schema
        self.name = name

        # Build adjacency map for fast lookup
        self._adjacency: dict[str, list[Edge]] = {}
        for edge in edges:
            if edge.source not in self._adjacency:
                self._adjacency[edge.source] = []
            self._adjacency[edge.source].append(edge)

    async def ainvoke(
        self,
        input: StateType,
        config: Optional[RunnableConfig] = None,
    ) -> StateType:
        """Execute the graph.

        Args:
            input: Initial state.
            config: Optional configuration.

        Returns:
            Final state after execution.
        """
        state = dict(input)
        current_node = self._entry_point

        # Set defaults
        state.setdefault("iteration", 0)
        state.setdefault("max_iterations", 100)
        state.setdefault("is_complete", False)

        while current_node and current_node != END:
            # Check iteration limit
            if state["iteration"] >= state["max_iterations"]:
                state["error"] = "Max iterations reached"
                break

            state["iteration"] += 1
            state["current_agent"] = current_node

            # Execute node
            node = self._nodes.get(current_node)
            if node:
                state = await node.execute(state, config)

            # Check if complete
            if state.get("is_complete"):
                break

            # Get next node
            current_node = self._get_next_node(current_node, state)

        return state

    async def astream(
        self,
        input: StateType,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[tuple[str, StateType]]:
        """Stream graph execution.

        Yields (node_name, state) tuples after each node.

        Args:
            input: Initial state.
            config: Optional configuration.

        Yields:
            Tuples of (node_name, current_state).
        """
        state = dict(input)
        current_node = self._entry_point

        state.setdefault("iteration", 0)
        state.setdefault("max_iterations", 100)
        state.setdefault("is_complete", False)

        while current_node and current_node != END:
            if state["iteration"] >= state["max_iterations"]:
                state["error"] = "Max iterations reached"
                yield ("__error__", state)
                break

            state["iteration"] += 1
            state["current_agent"] = current_node

            node = self._nodes.get(current_node)
            if node:
                state = await node.execute(state, config)
                yield (current_node, state)

            if state.get("is_complete"):
                break

            current_node = self._get_next_node(current_node, state)

        yield (END, state)

    def _get_next_node(self, current: str, state: StateType) -> Optional[str]:
        """Determine next node based on edges.

        Args:
            current: Current node name.
            state: Current state.

        Returns:
            Next node name or None.
        """
        edges = self._adjacency.get(current, [])

        for edge in edges:
            if edge.condition:
                # Conditional edge
                next_node = edge.condition(state)
                if next_node == END:
                    return END
                if next_node in self._nodes:
                    return next_node
            else:
                # Simple edge
                return edge.target

        return None

    def get_state_schema(self) -> type:
        """Get state schema type.

        Returns:
            State schema class.
        """
        return self._state_schema

    def __repr__(self) -> str:
        nodes = list(self._nodes.keys())
        return f"CompiledGraph(name={self.name}, nodes={nodes})"
