"""VoiceAgent - Main agent class for voice applications.

Provides a unified interface for building voice agents with
LLM, tools, memory, and persona support.
"""

from typing import Any, AsyncIterator, Optional

from voice_pipeline.agents.loop import AgentLoop
from voice_pipeline.agents.state import AgentState, AgentStatus
from voice_pipeline.interfaces.llm import LLMInterface
from voice_pipeline.memory.base import VoiceMemory
from voice_pipeline.prompts.persona import VoicePersona
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable
from voice_pipeline.tools.base import VoiceTool


class VoiceAgent(VoiceRunnable[str, str]):
    """Voice agent with tool calling support.

    Combines LLM, tools, memory, and persona into a unified interface.
    Follows patterns from LangChain AgentExecutor and CrewAI Agent.

    The agent implements VoiceRunnable, allowing composition with
    the | operator for voice pipelines:
        >>> chain = asr | agent | tts
        >>> result = await chain.ainvoke(audio_bytes)

    Attributes:
        llm: LLM interface for generation.
        tools: List of available tools.
        persona: Optional persona for the agent.
        memory: Optional conversation memory.
        max_iterations: Maximum agent loop iterations.
        verbose: Whether to log execution details.

    Example - Basic usage:
        >>> from voice_pipeline.agents import VoiceAgent
        >>> from voice_pipeline.tools import voice_tool
        >>>
        >>> @voice_tool
        ... def get_time() -> str:
        ...     '''Get the current time.'''
        ...     from datetime import datetime
        ...     return datetime.now().strftime("%H:%M")
        >>>
        >>> agent = VoiceAgent(
        ...     llm=my_llm,
        ...     tools=[get_time],
        ... )
        >>>
        >>> response = await agent.ainvoke("What time is it?")
        >>> print(response)  # "The current time is 14:30."

    Example - With persona and memory:
        >>> from voice_pipeline.agents import VoiceAgent
        >>> from voice_pipeline.memory import ConversationBufferMemory
        >>> from voice_pipeline.prompts import VoicePersona
        >>>
        >>> persona = VoicePersona(
        ...     name="Julia",
        ...     personality="friendly and helpful",
        ...     language="pt-BR",
        ... )
        >>>
        >>> agent = VoiceAgent(
        ...     llm=my_llm,
        ...     tools=[schedule_meeting, send_email],
        ...     persona=persona,
        ...     memory=ConversationBufferMemory(max_messages=20),
        ... )
        >>>
        >>> # Agent remembers previous conversations
        >>> response = await agent.ainvoke("Schedule a meeting for tomorrow")

    Example - Pipeline composition:
        >>> asr = MyASR()
        >>> tts = MyTTS()
        >>> agent = VoiceAgent(llm=my_llm, tools=[...])
        >>>
        >>> # Create voice pipeline
        >>> pipeline = asr | agent | tts
        >>>
        >>> # Stream audio output
        >>> async for audio_chunk in pipeline.astream(audio_input):
        ...     play(audio_chunk)
    """

    name: str = "VoiceAgent"

    def __init__(
        self,
        llm: LLMInterface,
        tools: Optional[list[VoiceTool]] = None,
        persona: Optional[VoicePersona] = None,
        memory: Optional[VoiceMemory] = None,
        system_prompt: Optional[str] = None,
        max_iterations: int = 10,
        verbose: bool = False,
    ):
        """Initialize VoiceAgent.

        Args:
            llm: LLM interface for generation.
            tools: List of tools available to the agent.
            persona: Optional persona for system prompt.
            memory: Optional conversation memory.
            system_prompt: Optional explicit system prompt
                          (overrides persona if both provided).
            max_iterations: Maximum loop iterations.
            verbose: Whether to log execution details.
        """
        self.llm = llm
        self.tools = tools or []
        self.persona = persona
        self.memory = memory
        self.max_iterations = max_iterations
        self.verbose = verbose

        # Build system prompt
        self._system_prompt = self._build_system_prompt(system_prompt)

        # Create agent loop
        self._loop = AgentLoop(
            llm=llm,
            tools=self.tools,
            system_prompt=self._system_prompt,
            max_iterations=max_iterations,
        )

    def _build_system_prompt(self, explicit_prompt: Optional[str] = None) -> str:
        """Build the system prompt for the agent.

        Args:
            explicit_prompt: Explicitly provided system prompt.

        Returns:
            System prompt string.
        """
        if explicit_prompt:
            return explicit_prompt

        if self.persona:
            return self.persona.to_system_prompt()

        # Default minimal prompt
        return "You are a helpful voice assistant. Be concise and conversational."

    async def ainvoke(
        self,
        input: str,
        config: Optional[RunnableConfig] = None,
    ) -> str:
        """Execute the agent on input.

        Processes the input through the agent loop, executing
        tools as needed, and returns the final response.

        Args:
            input: User input text.
            config: Optional runnable configuration.

        Returns:
            Agent's final response.
        """
        # Normalize input
        user_input = self._normalize_input(input)

        # Load context from memory
        context_messages = []
        if self.memory:
            context = await self.memory.load_context(user_input)
            context_messages = context.messages

        # Create state with context
        state = AgentState(max_iterations=self.max_iterations)

        # Add context messages
        for msg in context_messages:
            if msg.get("role") == "user":
                state.add_user_message(msg.get("content", ""))
            elif msg.get("role") == "assistant":
                state.add_assistant_message(msg.get("content", ""))

        # Add current user input
        state.add_user_message(user_input)

        # Execute loop
        try:
            response = await self._loop.run(user_input)
        except Exception as e:
            response = f"I encountered an error: {str(e)}"

        # Save to memory
        if self.memory:
            await self.memory.save_context(user_input, response)

        return response

    async def astream(
        self,
        input: str,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[str]:
        """Stream agent response.

        Yields tokens as they're generated during the final response.
        Tool calls are executed silently between yields.

        Args:
            input: User input text.
            config: Optional configuration.

        Yields:
            Response tokens.
        """
        # Normalize input
        user_input = self._normalize_input(input)

        # Load context from memory
        context_messages = []
        if self.memory:
            context = await self.memory.load_context(user_input)
            context_messages = context.messages

        # Build full response for memory
        full_response = []

        async for token in self._loop.run_stream(user_input):
            full_response.append(token)
            yield token

        # Save to memory
        if self.memory:
            response_text = "".join(full_response)
            await self.memory.save_context(user_input, response_text)

    def _normalize_input(self, input: Any) -> str:
        """Normalize various input formats to string.

        Args:
            input: Input in various formats.

        Returns:
            Normalized string input.
        """
        if isinstance(input, str):
            return input
        if isinstance(input, dict):
            # Handle TranscriptionResult-like dicts
            if "text" in input:
                return input["text"]
            if "content" in input:
                return input["content"]
        if hasattr(input, "text"):
            # TranscriptionResult object
            return input.text
        return str(input)

    def add_tool(self, tool: VoiceTool) -> None:
        """Add a tool to the agent.

        Args:
            tool: Tool to add.
        """
        self.tools.append(tool)
        self._loop.add_tool(tool)

    def remove_tool(self, name: str) -> None:
        """Remove a tool from the agent.

        Args:
            name: Name of tool to remove.
        """
        self.tools = [t for t in self.tools if t.name != name]
        self._loop.remove_tool(name)

    def list_tools(self) -> list[str]:
        """List available tool names.

        Returns:
            List of tool names.
        """
        return self._loop.list_tools()

    async def clear_memory(self) -> None:
        """Clear the agent's conversation memory."""
        if self.memory:
            await self.memory.clear()

    @property
    def system_prompt(self) -> str:
        """Get the current system prompt.

        Returns:
            System prompt string.
        """
        return self._system_prompt


class StreamingVoiceAgent(VoiceAgent):
    """VoiceAgent optimized for streaming pipelines.

    This variant prioritizes streaming output and is designed
    for low-latency voice applications.

    Example:
        >>> agent = StreamingVoiceAgent(llm=my_llm, tools=[...])
        >>> async for token in agent.astream("Hello"):
        ...     # Process each token immediately
        ...     print(token, end="", flush=True)
    """

    name: str = "StreamingVoiceAgent"

    async def astream(
        self,
        input: str,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[str]:
        """Stream agent response with optimized buffering.

        Uses smaller buffers for lower latency.

        Args:
            input: User input text.
            config: Optional configuration.

        Yields:
            Response tokens.
        """
        user_input = self._normalize_input(input)
        full_response = []

        async for token in self._loop.run_stream(user_input):
            full_response.append(token)
            yield token

        if self.memory:
            response_text = "".join(full_response)
            await self.memory.save_context(user_input, response_text)


def create_voice_agent(
    llm: LLMInterface,
    tools: Optional[list[VoiceTool]] = None,
    persona: Optional[VoicePersona] = None,
    memory: Optional[VoiceMemory] = None,
    system_prompt: Optional[str] = None,
    max_iterations: int = 10,
) -> VoiceAgent:
    """Factory function to create a VoiceAgent.

    Convenience function for creating agents with common configurations.

    Args:
        llm: LLM interface.
        tools: Optional tools.
        persona: Optional persona.
        memory: Optional memory.
        system_prompt: Optional system prompt.
        max_iterations: Max loop iterations.

    Returns:
        Configured VoiceAgent.

    Example:
        >>> agent = create_voice_agent(
        ...     llm=my_llm,
        ...     tools=[get_time, get_weather],
        ...     persona=ASSISTANT_PERSONA,
        ... )
    """
    return VoiceAgent(
        llm=llm,
        tools=tools,
        persona=persona,
        memory=memory,
        system_prompt=system_prompt,
        max_iterations=max_iterations,
    )
