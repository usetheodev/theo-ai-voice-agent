"""Multi-Agent Collaboration pattern.

Implements the collaboration pattern where agents share
a scratchpad and work together on tasks.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional, Union

from voice_pipeline.agents.base import VoiceAgent
from voice_pipeline.interfaces.llm import LLMInterface
from voice_pipeline.multi_agent.state import (
    AgentMessage,
    MultiAgentState,
    SharedMemory,
    create_initial_state,
)
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable


class CollaborationMode(str, Enum):
    """How agents collaborate."""

    ROUND_ROBIN = "round_robin"
    """Agents take turns in order."""

    DEBATE = "debate"
    """Agents discuss and refine answers."""

    CONSENSUS = "consensus"
    """Agents must agree on final answer."""

    VOTING = "voting"
    """Agents vote on best answer."""

    CHAIN_OF_THOUGHT = "chain_of_thought"
    """Each agent builds on previous work."""


@dataclass
class SharedScratchpad:
    """Shared workspace for collaborating agents.

    All agents can read from and write to the scratchpad,
    enabling transparent collaboration.

    Attributes:
        messages: Shared message history.
        notes: Key-value notes.
        artifacts: Generated artifacts.
    """

    messages: list[AgentMessage] = field(default_factory=list)
    """Shared message history."""

    notes: dict[str, str] = field(default_factory=dict)
    """Key-value notes from agents."""

    artifacts: dict[str, Any] = field(default_factory=dict)
    """Generated artifacts (code, data, etc.)."""

    _memory: SharedMemory = field(default_factory=SharedMemory)
    """Shared memory store."""

    def add_message(
        self,
        role: str,
        content: str,
        agent_name: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Add a message to the scratchpad.

        Args:
            role: Message role.
            content: Message content.
            agent_name: Agent that created message.
            **kwargs: Additional fields.
        """
        msg = AgentMessage(
            role=role,
            content=content,
            name=agent_name,
            **kwargs,
        )
        self.messages.append(msg)

    def add_note(self, key: str, value: str, agent: str = "unknown") -> None:
        """Add a note to the scratchpad.

        Args:
            key: Note key.
            value: Note content.
            agent: Agent adding the note.
        """
        self.notes[key] = value
        self._memory.set(f"note:{key}", value, agent)

    def get_note(self, key: str) -> Optional[str]:
        """Get a note from the scratchpad.

        Args:
            key: Note key.

        Returns:
            Note content or None.
        """
        return self.notes.get(key)

    def add_artifact(self, name: str, artifact: Any, agent: str = "unknown") -> None:
        """Add an artifact to the scratchpad.

        Args:
            name: Artifact name.
            artifact: Artifact content.
            agent: Agent creating artifact.
        """
        self.artifacts[name] = artifact
        self._memory.set(f"artifact:{name}", artifact, agent)

    def get_artifact(self, name: str) -> Optional[Any]:
        """Get an artifact from the scratchpad.

        Args:
            name: Artifact name.

        Returns:
            Artifact or None.
        """
        return self.artifacts.get(name)

    def get_context(self, max_messages: int = 10) -> str:
        """Get formatted context for agents.

        Args:
            max_messages: Max messages to include.

        Returns:
            Formatted context string.
        """
        parts = []

        # Recent messages
        recent = self.messages[-max_messages:] if self.messages else []
        if recent:
            parts.append("Recent discussion:")
            for msg in recent:
                name = msg.get("name", msg.get("role", "unknown"))
                content = msg.get("content", "")
                parts.append(f"  [{name}]: {content}")

        # Notes
        if self.notes:
            parts.append("\nNotes:")
            for key, value in self.notes.items():
                parts.append(f"  - {key}: {value}")

        return "\n".join(parts)

    def clear(self) -> None:
        """Clear the scratchpad."""
        self.messages.clear()
        self.notes.clear()
        self.artifacts.clear()
        self._memory.clear()


class CollaborativeAgents(VoiceRunnable[Union[str, MultiAgentState], str]):
    """Agents that collaborate through a shared scratchpad.

    This implements the "Multi-Agent Collaboration" pattern from
    LangGraph, where agents share a common workspace and can see
    each other's work.

    Example - Round Robin:
        >>> analyst = VoiceAgent(llm=llm, tools=[search_tool])
        >>> critic = VoiceAgent(llm=llm)
        >>>
        >>> collab = CollaborativeAgents(
        ...     agents={"analyst": analyst, "critic": critic},
        ...     mode=CollaborationMode.ROUND_ROBIN,
        ...     max_rounds=3,
        ... )
        >>>
        >>> result = await collab.ainvoke("Analyze AI trends")

    Example - Debate:
        >>> pro = VoiceAgent(llm=llm, system_prompt="Argue in favor")
        >>> con = VoiceAgent(llm=llm, system_prompt="Argue against")
        >>> judge = VoiceAgent(llm=llm, system_prompt="Make final decision")
        >>>
        >>> collab = CollaborativeAgents(
        ...     agents={"pro": pro, "con": con, "judge": judge},
        ...     mode=CollaborationMode.DEBATE,
        ...     max_rounds=2,
        ... )
        >>>
        >>> result = await collab.ainvoke("Should we adopt microservices?")

    Attributes:
        agents: Dict of agent_name -> VoiceAgent.
        scratchpad: Shared workspace.
        mode: Collaboration mode.
        max_rounds: Maximum collaboration rounds.
    """

    name: str = "CollaborativeAgents"

    def __init__(
        self,
        agents: dict[str, VoiceAgent],
        mode: CollaborationMode = CollaborationMode.ROUND_ROBIN,
        max_rounds: int = 3,
        finalizer: Optional[str] = None,
        llm: Optional[LLMInterface] = None,
    ):
        """Initialize collaborative agents.

        Args:
            agents: Dict of agents.
            mode: Collaboration mode.
            max_rounds: Max collaboration rounds.
            finalizer: Agent that produces final answer.
            llm: Optional LLM for synthesis.
        """
        self.agents = agents
        self.mode = mode
        self.max_rounds = max_rounds
        self.finalizer = finalizer
        self.llm = llm
        self.scratchpad = SharedScratchpad()
        self._agent_order = list(agents.keys())

    async def ainvoke(
        self,
        input: Union[str, MultiAgentState],
        config: Optional[RunnableConfig] = None,
    ) -> str:
        """Execute collaborative workflow.

        Args:
            input: User query or state.
            config: Optional configuration.

        Returns:
            Final collaborative result.
        """
        # Reset scratchpad
        self.scratchpad.clear()

        # Normalize input
        if isinstance(input, str):
            state = create_initial_state(user_query=input)
        else:
            state = input

        user_query = state.get("user_query", "")
        self.scratchpad.add_message("user", user_query)

        # Execute based on mode
        if self.mode == CollaborationMode.ROUND_ROBIN:
            result = await self._round_robin(user_query, config)
        elif self.mode == CollaborationMode.DEBATE:
            result = await self._debate(user_query, config)
        elif self.mode == CollaborationMode.CONSENSUS:
            result = await self._consensus(user_query, config)
        elif self.mode == CollaborationMode.VOTING:
            result = await self._voting(user_query, config)
        elif self.mode == CollaborationMode.CHAIN_OF_THOUGHT:
            result = await self._chain_of_thought(user_query, config)
        else:
            result = await self._round_robin(user_query, config)

        state["answer"] = result
        state["is_complete"] = True
        return result

    async def astream(
        self,
        input: Union[str, MultiAgentState],
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[str]:
        """Stream collaborative workflow.

        Args:
            input: User query or state.
            config: Optional configuration.

        Yields:
            Updates from each agent.
        """
        self.scratchpad.clear()

        if isinstance(input, str):
            user_query = input
        else:
            user_query = input.get("user_query", "")

        self.scratchpad.add_message("user", user_query)

        for round_num in range(self.max_rounds):
            yield f"\n--- Round {round_num + 1} ---\n"

            for agent_name in self._agent_order:
                agent = self.agents[agent_name]
                context = self.scratchpad.get_context()
                prompt = f"{context}\n\nTask: {user_query}\nYour contribution:"

                yield f"\n[{agent_name}]: "
                async for token in agent.astream(prompt, config):
                    yield token

    async def _round_robin(
        self,
        query: str,
        config: Optional[RunnableConfig],
    ) -> str:
        """Round-robin collaboration.

        Each agent takes a turn in order.
        """
        for round_num in range(self.max_rounds):
            for agent_name in self._agent_order:
                agent = self.agents[agent_name]

                # Build prompt with context
                context = self.scratchpad.get_context()
                prompt = f"""Previous discussion:
{context}

Original task: {query}

You are {agent_name}. Add your contribution to the discussion.
Be concise and build on what others have said."""

                # Execute agent
                response = await agent.ainvoke(prompt, config)
                self.scratchpad.add_message("assistant", response, agent_name)

        # Get final answer from finalizer or last agent
        return self._get_final_answer()

    async def _debate(
        self,
        query: str,
        config: Optional[RunnableConfig],
    ) -> str:
        """Debate collaboration.

        Agents argue different positions.
        """
        agents_list = list(self.agents.items())

        for round_num in range(self.max_rounds):
            for agent_name, agent in agents_list:
                context = self.scratchpad.get_context()
                prompt = f"""Debate topic: {query}

Discussion so far:
{context}

You are {agent_name}. Present your argument, respond to other positions,
and defend your stance. Be persuasive but concise."""

                response = await agent.ainvoke(prompt, config)
                self.scratchpad.add_message("assistant", response, agent_name)

        # Finalizer or synthesis
        if self.finalizer and self.finalizer in self.agents:
            return await self._finalize(query, config)

        return self._synthesize_debate()

    async def _consensus(
        self,
        query: str,
        config: Optional[RunnableConfig],
    ) -> str:
        """Consensus collaboration.

        Agents work toward agreement.
        """
        for round_num in range(self.max_rounds):
            responses = []

            for agent_name, agent in self.agents.items():
                context = self.scratchpad.get_context()
                prompt = f"""Task: {query}

Discussion so far:
{context}

You are {agent_name}. Provide your answer. Try to find common ground
with other agents. If you agree with a previous answer, say so."""

                response = await agent.ainvoke(prompt, config)
                responses.append((agent_name, response))
                self.scratchpad.add_message("assistant", response, agent_name)

            # Check for consensus
            if self._check_consensus(responses):
                break

        return self._get_final_answer()

    async def _voting(
        self,
        query: str,
        config: Optional[RunnableConfig],
    ) -> str:
        """Voting collaboration.

        Each agent votes on the best answer.
        """
        # First round: each agent proposes
        proposals: dict[str, str] = {}
        for agent_name, agent in self.agents.items():
            response = await agent.ainvoke(query, config)
            proposals[agent_name] = response
            self.scratchpad.add_message("assistant", response, agent_name)

        # Voting round
        votes: dict[str, int] = {name: 0 for name in proposals}
        for agent_name, agent in self.agents.items():
            proposals_text = "\n".join(
                f"{i+1}. [{name}]: {text}"
                for i, (name, text) in enumerate(proposals.items())
            )
            vote_prompt = f"""Task: {query}

Proposals:
{proposals_text}

Vote for the best answer (respond with just the agent name):"""

            vote = await agent.ainvoke(vote_prompt, config)
            for name in proposals:
                if name.lower() in vote.lower():
                    votes[name] += 1
                    break

        # Winner
        winner = max(votes, key=lambda k: votes[k])
        return proposals[winner]

    async def _chain_of_thought(
        self,
        query: str,
        config: Optional[RunnableConfig],
    ) -> str:
        """Chain-of-thought collaboration.

        Each agent builds on the previous agent's work.
        """
        current_result = query

        for agent_name in self._agent_order:
            agent = self.agents[agent_name]
            context = self.scratchpad.get_context()

            prompt = f"""Original task: {query}

Work so far:
{context}

Current state: {current_result}

You are {agent_name}. Continue building on this work.
Add your contribution and improvements."""

            response = await agent.ainvoke(prompt, config)
            self.scratchpad.add_message("assistant", response, agent_name)
            current_result = response

        return current_result

    async def _finalize(
        self,
        query: str,
        config: Optional[RunnableConfig],
    ) -> str:
        """Use finalizer to produce final answer."""
        finalizer = self.agents.get(self.finalizer)
        if not finalizer:
            return self._get_final_answer()

        context = self.scratchpad.get_context()
        prompt = f"""Task: {query}

Full discussion:
{context}

As the final decision-maker, synthesize the discussion and provide
the definitive answer."""

        return await finalizer.ainvoke(prompt, config)

    def _get_final_answer(self) -> str:
        """Get final answer from scratchpad."""
        if self.scratchpad.messages:
            # Return last assistant message
            for msg in reversed(self.scratchpad.messages):
                if msg.get("role") == "assistant":
                    return msg.get("content", "")
        return ""

    def _synthesize_debate(self) -> str:
        """Synthesize debate into final answer."""
        context = self.scratchpad.get_context()
        return f"Debate summary:\n{context}"

    def _check_consensus(self, responses: list[tuple[str, str]]) -> bool:
        """Check if agents have reached consensus.

        Simple heuristic: if agents mention agreement.
        """
        agreement_words = ["agree", "consensus", "same", "correct", "right"]
        for _, response in responses:
            if any(word in response.lower() for word in agreement_words):
                return True
        return False

    def set_agent_order(self, order: list[str]) -> None:
        """Set the order agents participate.

        Args:
            order: List of agent names.
        """
        self._agent_order = [n for n in order if n in self.agents]

    def get_scratchpad(self) -> SharedScratchpad:
        """Get the shared scratchpad.

        Returns:
            SharedScratchpad instance.
        """
        return self.scratchpad


def create_collaboration(
    agents: dict[str, VoiceAgent],
    mode: CollaborationMode = CollaborationMode.ROUND_ROBIN,
    max_rounds: int = 3,
    finalizer: Optional[str] = None,
) -> CollaborativeAgents:
    """Factory function to create CollaborativeAgents.

    Args:
        agents: Dict of agents.
        mode: Collaboration mode.
        max_rounds: Max rounds.
        finalizer: Finalizer agent name.

    Returns:
        Configured CollaborativeAgents.

    Example:
        >>> collab = create_collaboration(
        ...     agents={"analyst": analyst, "critic": critic},
        ...     mode=CollaborationMode.DEBATE,
        ...     max_rounds=2,
        ... )
    """
    return CollaborativeAgents(
        agents=agents,
        mode=mode,
        max_rounds=max_rounds,
        finalizer=finalizer,
    )
