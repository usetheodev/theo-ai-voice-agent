"""VoiceAgent - Main agent class for voice applications.

Provides a unified interface for building voice agents with
LLM, tools, memory, and persona support.

Quick Start:
    >>> from voice_pipeline import VoiceAgent
    >>> agent = VoiceAgent.local()
    >>> await agent.connect()
    >>> response = await agent.chat("Olá!")

    >>> # Ou com builder
    >>> agent = (
    ...     VoiceAgent.builder()
    ...     .llm("ollama", model="qwen2.5:0.5b")
    ...     .system_prompt("Você é um assistente...")
    ...     .build()
    ... )
"""

import logging
from typing import Any, AsyncIterator, Optional, TYPE_CHECKING

from voice_pipeline.agents.loop import AgentLoop
from voice_pipeline.agents.state import AgentState, AgentStatus
from voice_pipeline.interfaces.llm import LLMInterface
from voice_pipeline.memory.base import VoiceMemory
from voice_pipeline.prompts.persona import VoicePersona
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable
from voice_pipeline.tools.base import VoiceTool

if TYPE_CHECKING:
    from voice_pipeline.interfaces import ASRInterface, TTSInterface, VADInterface

logger = logging.getLogger(__name__)


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

    # =========================================================================
    # Factory Methods (Presets)
    # =========================================================================

    @classmethod
    def local(
        cls,
        system_prompt: Optional[str] = None,
        tools: Optional[list[VoiceTool]] = None,
        llm_model: str = "qwen2.5:0.5b",
        **kwargs,
    ) -> "VoiceAgent":
        """Cria agente com LLM local (Ollama).

        Args:
            system_prompt: Prompt do sistema.
            tools: Lista de ferramentas.
            llm_model: Modelo Ollama.

        Returns:
            VoiceAgent configurado com Ollama.

        Example:
            >>> agent = VoiceAgent.local()
            >>> await agent.llm.connect()
            >>> response = await agent.ainvoke("Olá!")
        """
        from voice_pipeline.providers.llm import OllamaLLMProvider

        llm = OllamaLLMProvider(model=llm_model)

        return cls(
            llm=llm,
            tools=tools,
            system_prompt=system_prompt,
            **kwargs,
        )

    @classmethod
    def openai(
        cls,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        tools: Optional[list[VoiceTool]] = None,
        llm_model: str = "gpt-4o-mini",
        **kwargs,
    ) -> "VoiceAgent":
        """Cria agente com LLM OpenAI.

        Args:
            api_key: OpenAI API key.
            system_prompt: Prompt do sistema.
            tools: Lista de ferramentas.
            llm_model: Modelo OpenAI.

        Returns:
            VoiceAgent configurado com OpenAI.
        """
        from voice_pipeline.providers.llm import OpenAILLMProvider

        llm = OpenAILLMProvider(api_key=api_key, model=llm_model)

        return cls(
            llm=llm,
            tools=tools,
            system_prompt=system_prompt,
            **kwargs,
        )

    @classmethod
    def builder(cls) -> "VoiceAgentBuilder":
        """Retorna builder para configuração fluente.

        Example:
            >>> agent = (
            ...     VoiceAgent.builder()
            ...     .llm("ollama", model="qwen2.5:0.5b")
            ...     .tools([get_weather, search])
            ...     .system_prompt("Você é um assistente...")
            ...     .build()
            ... )
        """
        return VoiceAgentBuilder()

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


class VoiceAgentBuilder:
    """Builder fluente para VoiceAgent.

    Example - Agente de texto:
        >>> agent = (
        ...     VoiceAgent.builder()
        ...     .llm("ollama", model="qwen2.5:0.5b")
        ...     .tools([get_weather])
        ...     .system_prompt("Você é um assistente...")
        ...     .memory(max_messages=20)
        ...     .build()
        ... )

    Example - Pipeline de voz completo:
        >>> agent = (
        ...     VoiceAgent.builder()
        ...     .asr("whisper", model="base", language="pt")
        ...     .llm("ollama", model="qwen2.5:0.5b")
        ...     .tts("kokoro", voice="pf_dora")
        ...     .vad("silero")
        ...     .system_prompt("Você é um assistente...")
        ...     .memory(max_messages=20)
        ...     .build()
        ... )
    """

    def __init__(self):
        self._llm = None
        self._asr = None
        self._tts = None
        self._vad = None
        self._tools = []
        self._persona = None
        self._memory = None
        self._system_prompt = None
        self._max_iterations = 10
        self._language = "pt"
        self._tts_voice = "pf_dora"
        self._enable_barge_in = True
        self._streaming = False  # Sentence-level streaming for low latency

    def asr(
        self,
        provider: str = "whisper",
        model: str = "base",
        language: str = "pt",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura provider ASR (Speech-to-Text).

        Args:
            provider: "whisper" ou "openai".
            model: Modelo a usar.
            language: Código do idioma.
        """
        self._language = language
        if provider == "whisper":
            from voice_pipeline.providers.asr import WhisperCppASRProvider
            self._asr = WhisperCppASRProvider(model=model, language=language, **kwargs)
        elif provider == "openai":
            from voice_pipeline.providers.asr import OpenAIASRProvider
            self._asr = OpenAIASRProvider(model=model, language=language, **kwargs)
        else:
            raise ValueError(f"ASR provider desconhecido: {provider}")
        return self

    def llm(
        self,
        provider: str = "ollama",
        model: Optional[str] = None,
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura provider LLM.

        Args:
            provider: "ollama" ou "openai".
            model: Modelo a usar.
        """
        if provider == "ollama":
            from voice_pipeline.providers.llm import OllamaLLMProvider
            self._llm = OllamaLLMProvider(model=model or "qwen2.5:0.5b", **kwargs)
        elif provider == "openai":
            from voice_pipeline.providers.llm import OpenAILLMProvider
            self._llm = OpenAILLMProvider(model=model or "gpt-4o-mini", **kwargs)
        else:
            raise ValueError(f"LLM provider desconhecido: {provider}")
        return self

    def tts(
        self,
        provider: str = "kokoro",
        voice: str = "pf_dora",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura provider TTS (Text-to-Speech).

        Args:
            provider: "kokoro" ou "openai".
            voice: Voz a usar.
        """
        self._tts_voice = voice
        if provider == "kokoro":
            from voice_pipeline.providers.tts import KokoroTTSProvider
            self._tts = KokoroTTSProvider(voice=voice, **kwargs)
        elif provider == "openai":
            from voice_pipeline.providers.tts import OpenAITTSProvider
            self._tts = OpenAITTSProvider(voice=voice, **kwargs)
        else:
            raise ValueError(f"TTS provider desconhecido: {provider}")
        return self

    def vad(
        self,
        provider: str = "silero",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura provider VAD (Voice Activity Detection).

        Args:
            provider: "silero" ou "webrtc".
        """
        if provider == "silero":
            from voice_pipeline.providers.vad import SileroVADProvider
            self._vad = SileroVADProvider(**kwargs)
        elif provider == "webrtc":
            from voice_pipeline.providers.vad import WebRTCVADProvider
            self._vad = WebRTCVADProvider(**kwargs)
        else:
            raise ValueError(f"VAD provider desconhecido: {provider}")
        return self

    def language(self, lang: str) -> "VoiceAgentBuilder":
        """Define idioma padrão."""
        self._language = lang
        return self

    def barge_in(self, enabled: bool = True) -> "VoiceAgentBuilder":
        """Habilita/desabilita interrupção de fala."""
        self._enable_barge_in = enabled
        return self

    def streaming(self, enabled: bool = True) -> "VoiceAgentBuilder":
        """Ativa streaming sentence-level (baixa latência).

        Quando ativado:
        - LLM e TTS executam em paralelo
        - Áudio começa a ser gerado assim que uma sentença completa
        - TTFA reduzido de ~2-3s para ~0.6-0.8s

        Args:
            enabled: True para ativar streaming (default).

        Returns:
            Self for chaining.

        Example:
            >>> agent = (
            ...     VoiceAgent.builder()
            ...     .asr("whisper")
            ...     .llm("ollama")
            ...     .tts("kokoro")
            ...     .streaming(True)  # Baixa latência
            ...     .build()
            ... )
        """
        self._streaming = enabled
        return self

    def tools(self, tools: list[VoiceTool]) -> "VoiceAgentBuilder":
        """Configura ferramentas."""
        self._tools = tools
        return self

    def tool(self, tool: VoiceTool) -> "VoiceAgentBuilder":
        """Adiciona uma ferramenta."""
        self._tools.append(tool)
        return self

    def persona(self, persona: VoicePersona) -> "VoiceAgentBuilder":
        """Configura persona."""
        self._persona = persona
        return self

    def system_prompt(self, prompt: str) -> "VoiceAgentBuilder":
        """Define prompt do sistema."""
        self._system_prompt = prompt
        return self

    def memory(self, max_messages: int = 20) -> "VoiceAgentBuilder":
        """Configura memória."""
        from voice_pipeline.memory import ConversationBufferMemory
        self._memory = ConversationBufferMemory(max_messages=max_messages)
        return self

    def max_iterations(self, n: int) -> "VoiceAgentBuilder":
        """Define máximo de iterações."""
        self._max_iterations = n
        return self

    def build(self):
        """Constrói o VoiceAgent, ConversationChain ou StreamingVoiceChain.

        Lógica de seleção:
        - Se ASR + TTS + streaming=True → StreamingVoiceChain (baixa latência)
        - Se ASR + TTS + streaming=False → ConversationChain (batch)
        - Se apenas LLM → VoiceAgent (texto → texto)

        Returns:
            VoiceAgent, ConversationChain ou StreamingVoiceChain.
        """
        if self._llm is None:
            raise ValueError("LLM é obrigatório. Use .llm() para configurar.")

        # Se tem ASR e TTS, criar pipeline de voz
        if self._asr is not None and self._tts is not None:
            if self._streaming:
                # Streaming sentence-level (baixa latência)
                from voice_pipeline.chains import StreamingVoiceChain

                return StreamingVoiceChain(
                    asr=self._asr,
                    llm=self._llm,
                    tts=self._tts,
                    system_prompt=self._system_prompt or "Você é um assistente de voz.",
                    language=self._language,
                    tts_voice=self._tts_voice,
                )
            else:
                # Batch (padrão)
                from voice_pipeline.chains import ConversationChain

                return ConversationChain(
                    asr=self._asr,
                    llm=self._llm,
                    tts=self._tts,
                    vad=self._vad,
                    system_prompt=self._system_prompt or "Você é um assistente de voz.",
                    language=self._language,
                    tts_voice=self._tts_voice,
                    memory=self._memory,
                    enable_barge_in=self._enable_barge_in,
                )

        # Caso contrário, criar VoiceAgent (texto → texto)
        return VoiceAgent(
            llm=self._llm,
            tools=self._tools,
            persona=self._persona,
            memory=self._memory,
            system_prompt=self._system_prompt,
            max_iterations=self._max_iterations,
        )

    async def build_async(self):
        """Constrói e conecta todos os providers.

        Returns:
            VoiceAgent ou ConversationChain com providers conectados.
        """
        result = self.build()

        # Conectar providers
        if self._asr is not None:
            await self._asr.connect()
        if self._llm is not None:
            await self._llm.connect()
        if self._tts is not None:
            await self._tts.connect()
        if self._vad is not None:
            await self._vad.connect()

        return result
