"""Supervisor Agent pattern for multi-agent orchestration.

The supervisor pattern uses a central coordinator that routes
tasks to specialized agents based on the query.
"""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Optional, Union

from voice_pipeline.agents.base import VoiceAgent
from voice_pipeline.interfaces.llm import LLMInterface, LLMResponse
from voice_pipeline.multi_agent.state import MultiAgentState, create_initial_state
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable


@dataclass
class RoutingDecision:
    """Result of supervisor routing decision.

    Attributes:
        agent_name: Selected agent name.
        confidence: Confidence score (0-1).
        reasoning: Explanation of decision.
    """

    agent_name: str
    """Name of agent to route to."""

    confidence: float = 1.0
    """Confidence in decision (0-1)."""

    reasoning: str = ""
    """Explanation of routing decision."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional routing metadata."""


@dataclass
class SupervisorConfig:
    """Configuration for SupervisorAgent.

    Attributes:
        max_iterations: Max routing iterations.
        allow_recursion: Allow routing back to same agent.
        use_llm_routing: Use LLM for routing decisions.
    """

    max_iterations: int = 10
    """Maximum routing iterations."""

    allow_recursion: bool = False
    """Allow routing back to the same agent."""

    use_llm_routing: bool = True
    """Use LLM to make routing decisions."""

    fallback_agent: Optional[str] = None
    """Default agent if routing fails."""

    include_agent_docs: bool = True
    """Include agent docstrings in routing prompt."""

    routing_temperature: float = 0.0
    """LLM temperature for routing (0 = deterministic)."""


class SupervisorAgent(VoiceRunnable[Union[str, MultiAgentState], str]):
    """Supervisor that coordinates multiple specialist agents.

    The supervisor acts as a router, analyzing user queries and
    delegating to the most appropriate specialist agent.

    This follows the "Agent Supervisor" pattern from LangGraph:
    - A central supervisor makes routing decisions
    - Specialist agents handle specific tasks
    - Results are aggregated by the supervisor

    Example:
        >>> # Define specialist agents
        >>> search_agent = VoiceAgent(llm=llm, tools=[search_tool])
        >>> math_agent = VoiceAgent(llm=llm, tools=[calculator])
        >>>
        >>> # Create supervisor
        >>> supervisor = SupervisorAgent(
        ...     llm=llm,
        ...     agents={
        ...         "search": search_agent,
        ...         "math": math_agent,
        ...     },
        ...     agent_descriptions={
        ...         "search": "Web search and information retrieval",
        ...         "math": "Mathematical calculations",
        ...     },
        ... )
        >>>
        >>> result = await supervisor.ainvoke("What is 25 * 4?")
        >>> # Routes to math_agent automatically

    Attributes:
        llm: LLM for routing decisions.
        agents: Dict of agent_name -> VoiceAgent.
        agent_descriptions: Dict of agent_name -> description.
        config: Supervisor configuration.
    """

    name: str = "SupervisorAgent"

    def __init__(
        self,
        llm: LLMInterface,
        agents: dict[str, VoiceAgent],
        agent_descriptions: Optional[dict[str, str]] = None,
        config: Optional[SupervisorConfig] = None,
        custom_router: Optional[Callable[[str, dict[str, str]], str]] = None,
    ):
        """Initialize the supervisor.

        Args:
            llm: LLM for routing decisions.
            agents: Dict mapping agent names to agents.
            agent_descriptions: Optional descriptions for routing.
            config: Supervisor configuration.
            custom_router: Optional custom routing function.
        """
        self.llm = llm
        self.agents = agents
        self.config = config or SupervisorConfig()
        self.custom_router = custom_router

        # Build descriptions from docstrings if not provided
        self.agent_descriptions = agent_descriptions or {}
        if self.config.include_agent_docs:
            for name, agent in agents.items():
                if name not in self.agent_descriptions:
                    # Use agent's system prompt or default description
                    if hasattr(agent, "system_prompt") and agent.system_prompt:
                        self.agent_descriptions[name] = agent.system_prompt[:200]
                    else:
                        self.agent_descriptions[name] = f"Agent: {name}"

    async def ainvoke(
        self,
        input: Union[str, MultiAgentState],
        config: Optional[RunnableConfig] = None,
    ) -> str:
        """Execute the supervisor workflow.

        Args:
            input: User query or state.
            config: Optional configuration.

        Returns:
            Final response string.
        """
        # Normalize input
        if isinstance(input, str):
            state = create_initial_state(user_query=input)
        else:
            state = input

        user_query = state.get("user_query", "")

        # Route to appropriate agent
        decision = await self._route(user_query)
        state["current_agent"] = decision.agent_name

        # Get the selected agent
        agent = self.agents.get(decision.agent_name)
        if not agent:
            if self.config.fallback_agent:
                agent = self.agents.get(self.config.fallback_agent)
            if not agent:
                return f"No agent available for: {user_query}"

        # Execute the agent
        result = await agent.ainvoke(user_query, config)

        # Store result
        state["answer"] = result
        state["is_complete"] = True

        return result

    async def astream(
        self,
        input: Union[str, MultiAgentState],
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[str]:
        """Stream supervisor workflow.

        Args:
            input: User query or state.
            config: Optional configuration.

        Yields:
            Response tokens.
        """
        # Normalize input
        if isinstance(input, str):
            user_query = input
        else:
            user_query = input.get("user_query", "")

        # Route
        decision = await self._route(user_query)
        agent = self.agents.get(decision.agent_name)

        if not agent:
            if self.config.fallback_agent:
                agent = self.agents.get(self.config.fallback_agent)
            if not agent:
                yield f"No agent available for: {user_query}"
                return

        # Stream from agent
        async for token in agent.astream(user_query, config):
            yield token

    async def _route(self, query: str) -> RoutingDecision:
        """Route query to appropriate agent.

        Args:
            query: User query.

        Returns:
            Routing decision.
        """
        # Custom router
        if self.custom_router:
            agent_name = self.custom_router(query, self.agent_descriptions)
            return RoutingDecision(agent_name=agent_name)

        # LLM-based routing
        if self.config.use_llm_routing:
            return await self._llm_route(query)

        # Fallback: first agent
        first_agent = next(iter(self.agents.keys()))
        return RoutingDecision(agent_name=first_agent)

    async def _llm_route(self, query: str) -> RoutingDecision:
        """Use LLM to make routing decision.

        Args:
            query: User query.

        Returns:
            Routing decision.
        """
        # Build routing prompt
        agent_list = "\n".join(
            f"- {name}: {desc}" for name, desc in self.agent_descriptions.items()
        )

        prompt = f"""You are a router agent. Your task is to choose the best agent for the job.

User query: {query}

Available agents:
{agent_list}

Which agent should handle this query? Respond with ONLY the agent name, nothing else."""

        # Call LLM
        response = await self.llm.generate(
            messages=[{"role": "user", "content": prompt}],
            temperature=self.config.routing_temperature,
        )

        # Parse response
        agent_name = response.strip().lower()

        # Find matching agent
        for name in self.agents.keys():
            if name.lower() in agent_name or agent_name in name.lower():
                return RoutingDecision(
                    agent_name=name,
                    reasoning=f"LLM selected '{name}' for query",
                )

        # Fallback
        if self.config.fallback_agent:
            return RoutingDecision(
                agent_name=self.config.fallback_agent,
                reasoning="Fallback: no clear match",
            )

        # First agent
        first_agent = next(iter(self.agents.keys()))
        return RoutingDecision(
            agent_name=first_agent,
            reasoning="Default: first available agent",
        )

    def add_agent(
        self,
        name: str,
        agent: VoiceAgent,
        description: Optional[str] = None,
    ) -> None:
        """Add an agent to the supervisor.

        Args:
            name: Agent name.
            agent: Agent instance.
            description: Optional description.
        """
        self.agents[name] = agent
        if description:
            self.agent_descriptions[name] = description

    def remove_agent(self, name: str) -> None:
        """Remove an agent from the supervisor.

        Args:
            name: Agent name to remove.
        """
        self.agents.pop(name, None)
        self.agent_descriptions.pop(name, None)

    def list_agents(self) -> list[str]:
        """List available agent names.

        Returns:
            List of agent names.
        """
        return list(self.agents.keys())

    def get_agent(self, name: str) -> Optional[VoiceAgent]:
        """Get agent by name.

        Args:
            name: Agent name.

        Returns:
            Agent or None.
        """
        return self.agents.get(name)


def create_supervisor(
    llm: LLMInterface,
    agents: dict[str, VoiceAgent],
    agent_descriptions: Optional[dict[str, str]] = None,
    max_iterations: int = 10,
    fallback_agent: Optional[str] = None,
    use_llm_routing: bool = True,
) -> SupervisorAgent:
    """Factory function to create a SupervisorAgent.

    Args:
        llm: LLM for routing.
        agents: Dict of agents.
        agent_descriptions: Agent descriptions.
        max_iterations: Max iterations.
        fallback_agent: Default fallback.
        use_llm_routing: Use LLM for routing.

    Returns:
        Configured SupervisorAgent.

    Example:
        >>> supervisor = create_supervisor(
        ...     llm=my_llm,
        ...     agents={"search": search_agent, "math": math_agent},
        ...     agent_descriptions={
        ...         "search": "Search the web",
        ...         "math": "Solve math problems",
        ...     },
        ... )
    """
    config = SupervisorConfig(
        max_iterations=max_iterations,
        fallback_agent=fallback_agent,
        use_llm_routing=use_llm_routing,
    )

    return SupervisorAgent(
        llm=llm,
        agents=agents,
        agent_descriptions=agent_descriptions,
        config=config,
    )
