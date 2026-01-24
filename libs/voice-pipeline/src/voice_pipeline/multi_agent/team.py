"""Agent Team pattern for hierarchical multi-agent workflows.

Teams group agents with defined roles and collaboration patterns,
similar to CrewAI's team concept.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional, Union

from voice_pipeline.agents.base import VoiceAgent
from voice_pipeline.interfaces.llm import LLMInterface
from voice_pipeline.multi_agent.state import MultiAgentState, create_initial_state
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable


class ExecutionMode(str, Enum):
    """How agents in a team execute."""

    SEQUENTIAL = "sequential"
    """Agents run one after another."""

    PARALLEL = "parallel"
    """Agents run concurrently."""

    HIERARCHICAL = "hierarchical"
    """Manager delegates to workers."""


@dataclass
class AgentRole:
    """Role definition for an agent in a team.

    Defines the agent's purpose, permissions, and behavior
    within the team context.

    Attributes:
        name: Role identifier.
        description: What this role does.
        agent: The agent instance.
        goal: Specific goal for this role.
        backstory: Character backstory (for persona).
    """

    name: str
    """Role identifier."""

    description: str
    """What this role does."""

    agent: VoiceAgent
    """The agent fulfilling this role."""

    goal: str = ""
    """Specific goal for this role."""

    backstory: str = ""
    """Character backstory for persona."""

    can_delegate: bool = False
    """Whether this agent can delegate to others."""

    tools_allowed: list[str] = field(default_factory=list)
    """List of allowed tool names."""

    max_iterations: int = 5
    """Max iterations for this agent."""

    def to_prompt_context(self) -> str:
        """Generate prompt context from role.

        Returns:
            Context string for LLM prompt.
        """
        parts = [f"Role: {self.name}", f"Description: {self.description}"]
        if self.goal:
            parts.append(f"Goal: {self.goal}")
        if self.backstory:
            parts.append(f"Background: {self.backstory}")
        return "\n".join(parts)


@dataclass
class TeamConfig:
    """Configuration for AgentTeam.

    Attributes:
        execution_mode: How agents execute.
        max_iterations: Global max iterations.
        share_context: Share context between agents.
        verbose: Enable verbose logging.
    """

    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    """How agents execute."""

    max_iterations: int = 20
    """Maximum total iterations."""

    share_context: bool = True
    """Share context between agents."""

    verbose: bool = False
    """Enable verbose output."""

    aggregate_results: bool = True
    """Aggregate all agent results."""

    manager_role: Optional[str] = None
    """Role name of team manager (for hierarchical)."""


class AgentTeam(VoiceRunnable[Union[str, MultiAgentState], str]):
    """A team of agents working together.

    AgentTeam organizes multiple agents with defined roles
    and coordinates their execution to complete tasks.

    Supports three execution modes:
    - SEQUENTIAL: Agents run one after another
    - PARALLEL: Agents run concurrently
    - HIERARCHICAL: Manager delegates to workers

    Example - Sequential Team:
        >>> researcher = AgentRole(
        ...     name="researcher",
        ...     description="Research information",
        ...     agent=research_agent,
        ...     goal="Find accurate information",
        ... )
        >>> writer = AgentRole(
        ...     name="writer",
        ...     description="Write content",
        ...     agent=writer_agent,
        ...     goal="Create clear content",
        ... )
        >>>
        >>> team = AgentTeam(
        ...     roles=[researcher, writer],
        ...     config=TeamConfig(execution_mode=ExecutionMode.SEQUENTIAL),
        ... )
        >>>
        >>> result = await team.ainvoke("Write about AI trends")

    Example - Hierarchical Team:
        >>> manager = AgentRole(
        ...     name="manager",
        ...     description="Coordinate team tasks",
        ...     agent=manager_agent,
        ...     can_delegate=True,
        ... )
        >>> worker1 = AgentRole(name="search", ...)
        >>> worker2 = AgentRole(name="analyze", ...)
        >>>
        >>> team = AgentTeam(
        ...     roles=[manager, worker1, worker2],
        ...     config=TeamConfig(
        ...         execution_mode=ExecutionMode.HIERARCHICAL,
        ...         manager_role="manager",
        ...     ),
        ... )
    """

    name: str = "AgentTeam"

    def __init__(
        self,
        roles: list[AgentRole],
        config: Optional[TeamConfig] = None,
        llm: Optional[LLMInterface] = None,
    ):
        """Initialize the team.

        Args:
            roles: List of agent roles.
            config: Team configuration.
            llm: Optional LLM for coordination.
        """
        self.roles = {role.name: role for role in roles}
        self.config = config or TeamConfig()
        self.llm = llm
        self._execution_order: list[str] = [role.name for role in roles]

    async def ainvoke(
        self,
        input: Union[str, MultiAgentState],
        config: Optional[RunnableConfig] = None,
    ) -> str:
        """Execute the team workflow.

        Args:
            input: User query or state.
            config: Optional configuration.

        Returns:
            Final aggregated result.
        """
        # Normalize input
        if isinstance(input, str):
            state = create_initial_state(user_query=input)
        else:
            state = input

        if self.config.execution_mode == ExecutionMode.SEQUENTIAL:
            return await self._execute_sequential(state, config)
        elif self.config.execution_mode == ExecutionMode.PARALLEL:
            return await self._execute_parallel(state, config)
        else:
            return await self._execute_hierarchical(state, config)

    async def astream(
        self,
        input: Union[str, MultiAgentState],
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[str]:
        """Stream team execution.

        Yields results as each agent completes.

        Args:
            input: User query or state.
            config: Optional configuration.

        Yields:
            Agent results.
        """
        if isinstance(input, str):
            state = create_initial_state(user_query=input)
        else:
            state = input

        if self.config.execution_mode == ExecutionMode.SEQUENTIAL:
            async for result in self._stream_sequential(state, config):
                yield result
        elif self.config.execution_mode == ExecutionMode.PARALLEL:
            async for result in self._stream_parallel(state, config):
                yield result
        else:
            async for result in self._stream_hierarchical(state, config):
                yield result

    async def _execute_sequential(
        self,
        state: MultiAgentState,
        config: Optional[RunnableConfig],
    ) -> str:
        """Execute agents sequentially.

        Each agent receives the output of the previous.

        Args:
            state: Current state.
            config: Configuration.

        Returns:
            Final result.
        """
        results: list[str] = []
        current_input = state.get("user_query", "")

        for role_name in self._execution_order:
            role = self.roles.get(role_name)
            if not role:
                continue

            # Build context for agent
            if self.config.share_context and results:
                context = f"Previous results:\n" + "\n---\n".join(results)
                full_input = f"{context}\n\nCurrent task: {current_input}"
            else:
                full_input = current_input

            # Execute agent
            result = await role.agent.ainvoke(full_input, config)
            results.append(f"[{role_name}]: {result}")

            # Use result as next input
            current_input = result

            state["iteration"] = state.get("iteration", 0) + 1
            if state["iteration"] >= self.config.max_iterations:
                break

        # Aggregate results
        if self.config.aggregate_results:
            state["answer"] = "\n\n".join(results)
        else:
            state["answer"] = results[-1] if results else ""

        return state["answer"]

    async def _execute_parallel(
        self,
        state: MultiAgentState,
        config: Optional[RunnableConfig],
    ) -> str:
        """Execute agents in parallel.

        All agents work on the same input concurrently.

        Args:
            state: Current state.
            config: Configuration.

        Returns:
            Aggregated results.
        """
        import asyncio

        user_query = state.get("user_query", "")
        tasks = []

        for role_name in self._execution_order:
            role = self.roles.get(role_name)
            if role:
                tasks.append(self._execute_agent(role, user_query, config))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Format results
        formatted = []
        for i, result in enumerate(results):
            role_name = self._execution_order[i]
            if isinstance(result, Exception):
                formatted.append(f"[{role_name}]: Error - {result}")
            else:
                formatted.append(f"[{role_name}]: {result}")

        state["answer"] = "\n\n".join(formatted)
        return state["answer"]

    async def _execute_hierarchical(
        self,
        state: MultiAgentState,
        config: Optional[RunnableConfig],
    ) -> str:
        """Execute with manager-worker hierarchy.

        Manager decides which workers to invoke.

        Args:
            state: Current state.
            config: Configuration.

        Returns:
            Manager's final result.
        """
        user_query = state.get("user_query", "")
        manager_name = self.config.manager_role

        if not manager_name or manager_name not in self.roles:
            # Fallback to sequential
            return await self._execute_sequential(state, config)

        manager = self.roles[manager_name]
        workers = {k: v for k, v in self.roles.items() if k != manager_name}

        # Build worker descriptions for manager
        worker_list = "\n".join(
            f"- {name}: {role.description}" for name, role in workers.items()
        )

        manager_prompt = f"""You are the team manager. Coordinate your team to complete this task.

Task: {user_query}

Available team members:
{worker_list}

Decide which team member(s) should handle this task.
Respond with the team member name(s) and instructions."""

        # Get manager's decision
        manager_decision = await manager.agent.ainvoke(manager_prompt, config)

        # Parse and execute worker tasks
        worker_results = []
        for worker_name, worker_role in workers.items():
            if worker_name.lower() in manager_decision.lower():
                result = await worker_role.agent.ainvoke(user_query, config)
                worker_results.append(f"[{worker_name}]: {result}")

        # Manager synthesizes results
        if worker_results:
            synthesis_prompt = f"""Task: {user_query}

Team results:
{chr(10).join(worker_results)}

Synthesize these results into a final answer."""

            final_result = await manager.agent.ainvoke(synthesis_prompt, config)
        else:
            final_result = manager_decision

        state["answer"] = final_result
        return final_result

    async def _stream_sequential(
        self,
        state: MultiAgentState,
        config: Optional[RunnableConfig],
    ) -> AsyncIterator[str]:
        """Stream sequential execution."""
        current_input = state.get("user_query", "")

        for role_name in self._execution_order:
            role = self.roles.get(role_name)
            if not role:
                continue

            yield f"\n[{role_name}]: "
            async for token in role.agent.astream(current_input, config):
                yield token

    async def _stream_parallel(
        self,
        state: MultiAgentState,
        config: Optional[RunnableConfig],
    ) -> AsyncIterator[str]:
        """Stream parallel execution results."""
        # For parallel, we wait and yield results
        result = await self._execute_parallel(state, config)
        yield result

    async def _stream_hierarchical(
        self,
        state: MultiAgentState,
        config: Optional[RunnableConfig],
    ) -> AsyncIterator[str]:
        """Stream hierarchical execution."""
        result = await self._execute_hierarchical(state, config)
        yield result

    async def _execute_agent(
        self,
        role: AgentRole,
        input: str,
        config: Optional[RunnableConfig],
    ) -> str:
        """Execute a single agent.

        Args:
            role: Agent role.
            input: Input string.
            config: Configuration.

        Returns:
            Agent result.
        """
        return await role.agent.ainvoke(input, config)

    def add_role(self, role: AgentRole) -> None:
        """Add a role to the team.

        Args:
            role: Role to add.
        """
        self.roles[role.name] = role
        self._execution_order.append(role.name)

    def remove_role(self, name: str) -> None:
        """Remove a role from the team.

        Args:
            name: Role name to remove.
        """
        self.roles.pop(name, None)
        if name in self._execution_order:
            self._execution_order.remove(name)

    def set_execution_order(self, order: list[str]) -> None:
        """Set the execution order for sequential mode.

        Args:
            order: List of role names in order.
        """
        self._execution_order = [n for n in order if n in self.roles]

    def list_roles(self) -> list[str]:
        """List all role names.

        Returns:
            List of role names.
        """
        return list(self.roles.keys())


def create_team(
    agents: dict[str, VoiceAgent],
    descriptions: Optional[dict[str, str]] = None,
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
    manager: Optional[str] = None,
) -> AgentTeam:
    """Factory function to create an AgentTeam.

    Args:
        agents: Dict of name -> agent.
        descriptions: Optional descriptions.
        execution_mode: Execution mode.
        manager: Manager role name (for hierarchical).

    Returns:
        Configured AgentTeam.

    Example:
        >>> team = create_team(
        ...     agents={
        ...         "researcher": research_agent,
        ...         "writer": writer_agent,
        ...     },
        ...     descriptions={
        ...         "researcher": "Research topics",
        ...         "writer": "Write content",
        ...     },
        ...     execution_mode=ExecutionMode.SEQUENTIAL,
        ... )
    """
    descriptions = descriptions or {}
    roles = [
        AgentRole(
            name=name,
            description=descriptions.get(name, f"Agent: {name}"),
            agent=agent,
        )
        for name, agent in agents.items()
    ]

    config = TeamConfig(
        execution_mode=execution_mode,
        manager_role=manager,
    )

    return AgentTeam(roles=roles, config=config)
