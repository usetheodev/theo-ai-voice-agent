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
        self._rag = None
        self._tools = []
        self._persona = None
        self._memory = None
        self._system_prompt = None
        self._max_iterations = 10
        self._language = "pt"
        self._tts_voice = "pf_dora"
        self._enable_barge_in = True
        self._streaming = False  # Sentence-level streaming for low latency
        self._auto_warmup = True  # Auto warmup TTS to eliminate cold start
        # Sentence streamer config
        self._min_sentence_chars = 20
        self._max_sentence_chars = 200
        self._sentence_timeout_ms = 500
        self._enable_quick_phrases = True
        # History config
        self._max_messages = 20  # Max conversation messages (0 = unlimited)
        # RAG config
        self._rag_k = 5  # Number of documents to retrieve
        # Turn-taking config
        self._turn_taking_controller = None
        # Streaming strategy config
        self._streaming_strategy = None
        # Interruption strategy config
        self._interruption_strategy = None

    def asr(
        self,
        provider: str = "whisper",
        model: str = "base",
        language: str = "pt",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura provider ASR (Speech-to-Text).

        Args:
            provider: Provider ASR a usar:
                - "whisper": whisper.cpp local
                - "faster-whisper": FasterWhisper (4x mais rápido, CPU otimizado)
                - "openai": OpenAI Whisper API
                - "deepgram": Deepgram streaming (real-time)
                - "nemotron": NVIDIA Nemotron (<24ms, GPU required)
            model: Modelo a usar.
            language: Código do idioma.
            **kwargs: Argumentos adicionais para o provider.

        Example:
            >>> # FasterWhisper (recomendado para CPU)
            >>> builder.asr("faster-whisper", model="small", language="pt",
            ...             compute_type="int8", vad_filter=True)
            >>>
            >>> # Local Whisper
            >>> builder.asr("whisper", model="base", language="pt")
            >>>
            >>> # Deepgram streaming (real-time)
            >>> builder.asr("deepgram", api_key="...", language="pt-BR")
            >>>
            >>> # Nemotron (GPU, ultra-low latency)
            >>> builder.asr("nemotron", latency_mode="low", device="cuda")
        """
        self._language = language
        self._asr_provider = provider
        self._asr_kwargs = {"model": model, "language": language, **kwargs}

        if provider == "whisper":
            from voice_pipeline.providers.asr import WhisperCppASRProvider
            self._asr = WhisperCppASRProvider(model=model, language=language, **kwargs)
        elif provider == "openai":
            from voice_pipeline.providers.asr import OpenAIASRProvider
            self._asr = OpenAIASRProvider(model=model, language=language, **kwargs)
        elif provider == "deepgram":
            from voice_pipeline.providers.asr import DeepgramASRProvider
            self._asr = DeepgramASRProvider(language=language, **kwargs)
        elif provider == "faster-whisper":
            from voice_pipeline.providers.asr import FasterWhisperProvider
            self._asr = FasterWhisperProvider(model=model, language=language, **kwargs)
        elif provider == "nemotron":
            from voice_pipeline.providers.asr import NemotronASRProvider
            self._asr = NemotronASRProvider(**kwargs)
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
            provider: Provider TTS a usar:
                - "kokoro": Kokoro local TTS (82M params, qualidade alta)
                - "piper": Piper ultra-fast CPU TTS (5-32M params, mínima latência)
                - "qwen3-tts": Qwen3-TTS (97ms latência, português nativo)
                - "openai": OpenAI TTS API
            voice: Voz a usar (speaker para qwen3-tts).

        Example:
            >>> # Kokoro (padrão, qualidade alta)
            >>> builder.tts("kokoro", voice="pf_dora")
            >>>
            >>> # Piper (ultra-rápido no CPU, ~30ms)
            >>> builder.tts("piper", voice="pt_BR-faber-medium")
            >>>
            >>> # Qwen3-TTS (melhor português, requer mais recursos)
            >>> builder.tts("qwen3-tts", voice="Ryan", language="Portuguese")
            >>>
            >>> # OpenAI (API, requer key)
            >>> builder.tts("openai", voice="nova")
        """
        self._tts_voice = voice
        if provider == "kokoro":
            from voice_pipeline.providers.tts import KokoroTTSProvider
            self._tts = KokoroTTSProvider(voice=voice, **kwargs)
        elif provider == "piper":
            from voice_pipeline.providers.tts import PiperTTSProvider
            self._tts = PiperTTSProvider(voice=voice, **kwargs)
        elif provider in ("qwen3-tts", "qwen3", "qwen"):
            from voice_pipeline.providers.tts import Qwen3TTSProvider
            self._tts = Qwen3TTSProvider(speaker=voice, **kwargs)
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

    def turn_taking(
        self,
        strategy: str = "fixed",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura estratégia de turn-taking.

        Turn-taking determina quando o usuário terminou de falar
        e o agente deve começar a responder.

        Args:
            strategy: Estratégia a usar:
                - "fixed": Silêncio fixo (default, mais simples).
                    kwargs: silence_threshold_ms (default 800)
                - "adaptive": Silêncio adaptativo por contexto.
                    kwargs: base_threshold_ms (default 600),
                            min_threshold_ms (default 400),
                            max_threshold_ms (default 1500)
                - "semantic": Detecção semântica de fim de turno.
                    kwargs: backend ("heuristic"|"transformers"),
                            min_silence_ms (default 300),
                            language (default "pt")
            **kwargs: Argumentos adicionais para a estratégia.

        Returns:
            Self for chaining.

        Example:
            >>> # Silêncio fixo rápido
            >>> builder.turn_taking("fixed", silence_threshold_ms=600)
            >>>
            >>> # Adaptativo (melhor balanço)
            >>> builder.turn_taking("adaptive", base_threshold_ms=500)
            >>>
            >>> # Semântico (máxima precisão)
            >>> builder.turn_taking("semantic", backend="heuristic", language="pt")
        """
        if strategy == "fixed":
            from voice_pipeline.providers.turn_taking import FixedSilenceTurnTaking
            self._turn_taking_controller = FixedSilenceTurnTaking(**kwargs)
        elif strategy == "adaptive":
            from voice_pipeline.providers.turn_taking import AdaptiveSilenceTurnTaking
            self._turn_taking_controller = AdaptiveSilenceTurnTaking(**kwargs)
        elif strategy == "semantic":
            from voice_pipeline.providers.turn_taking import SemanticTurnTaking
            self._turn_taking_controller = SemanticTurnTaking(**kwargs)
        else:
            raise ValueError(
                f"Turn-taking strategy desconhecida: {strategy}. "
                f"Use 'fixed', 'adaptive' ou 'semantic'."
            )
        return self

    def streaming_granularity(
        self,
        granularity: str = "sentence",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura granularidade de streaming LLM → TTS.

        Controla como os tokens do LLM são bufferizados antes de
        serem enviados ao TTS. Granularidades menores reduzem latência
        mas podem afetar a naturalidade da fala.

        Args:
            granularity: Nível de granularidade:
                - "sentence": Sentenças completas (~600-800ms TTFA).
                    Melhor naturalidade. Padrão.
                    kwargs: config (SentenceStreamerConfig)
                - "clause": Cláusulas (~200-400ms TTFA).
                    Bom balanço latência/naturalidade.
                    kwargs: min_chars (default 8),
                            max_chars (default 150),
                            language (default "pt")
                - "word": Palavras individuais (~45ms TTFA).
                    Mínima latência, prosódia menos natural.
                    kwargs: min_word_length (default 1),
                            group_size (default 1)
                - "adaptive": Word-level no primeiro chunk, clause depois.
                    Melhor TTFA com naturalidade (~100-200ms TTFA).
                    kwargs: first_chunk_words (default 3),
                            clause_min_chars (default 10),
                            clause_max_chars (default 150),
                            language (default "pt")
            **kwargs: Argumentos adicionais para a estratégia.

        Returns:
            Self for chaining.

        Example:
            >>> # Cláusula (balanço latência/naturalidade)
            >>> builder.streaming_granularity("clause", min_chars=10)
            >>>
            >>> # Palavra (mínima latência)
            >>> builder.streaming_granularity("word", group_size=2)
            >>>
            >>> # Sentença (padrão, máxima naturalidade)
            >>> builder.streaming_granularity("sentence")
        """
        if granularity == "sentence":
            from voice_pipeline.streaming.sentence_strategy import SentenceStreamingStrategy
            self._streaming_strategy = SentenceStreamingStrategy(**kwargs)
        elif granularity == "clause":
            from voice_pipeline.streaming.clause_strategy import ClauseStreamingStrategy
            self._streaming_strategy = ClauseStreamingStrategy(**kwargs)
        elif granularity == "word":
            from voice_pipeline.streaming.word_strategy import WordStreamingStrategy
            self._streaming_strategy = WordStreamingStrategy(**kwargs)
        elif granularity == "adaptive":
            from voice_pipeline.streaming.adaptive_strategy import AdaptiveStreamingStrategy
            self._streaming_strategy = AdaptiveStreamingStrategy(**kwargs)
        else:
            raise ValueError(
                f"Streaming granularity desconhecida: {granularity}. "
                f"Use 'sentence', 'clause', 'word' ou 'adaptive'."
            )
        return self

    def interruption(
        self,
        strategy: str = "immediate",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura estratégia de interrupção (barge-in).

        Controla como o sistema responde quando o usuário fala
        enquanto o agente está falando.

        Args:
            strategy: Estratégia a usar:
                - "immediate": Para TTS imediatamente (padrão).
                    kwargs: min_speech_ms (default 200),
                            min_confidence (default 0.5),
                            debounce_ms (default 500)
                - "graceful": Termina chunk atual antes de parar.
                    kwargs: min_speech_ms (default 300),
                            finish_threshold (default 0.3),
                            max_wait_ms (default 500)
                - "backchannel": Distingue backchannels de interrupções.
                    kwargs: backchannel_max_ms (default 500),
                            interruption_min_ms (default 800),
                            language (default "pt"),
                            use_transcript (default True)
            **kwargs: Argumentos adicionais para a estratégia.

        Returns:
            Self for chaining.

        Example:
            >>> # Imediato (padrão, menor latência)
            >>> builder.interruption("immediate", min_speech_ms=150)
            >>>
            >>> # Graceful (áudio mais suave)
            >>> builder.interruption("graceful", finish_threshold=0.5)
            >>>
            >>> # Backchannel-aware (melhor para português)
            >>> builder.interruption("backchannel", language="pt")
        """
        if strategy == "immediate":
            from voice_pipeline.providers.interruption import ImmediateInterruption
            self._interruption_strategy = ImmediateInterruption(**kwargs)
        elif strategy == "graceful":
            from voice_pipeline.providers.interruption import GracefulInterruption
            self._interruption_strategy = GracefulInterruption(**kwargs)
        elif strategy == "backchannel":
            from voice_pipeline.providers.interruption import BackchannelAwareInterruption
            self._interruption_strategy = BackchannelAwareInterruption(**kwargs)
        else:
            raise ValueError(
                f"Interruption strategy desconhecida: {strategy}. "
                f"Use 'immediate', 'graceful' ou 'backchannel'."
            )
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

    def warmup(self, enabled: bool = True) -> "VoiceAgentBuilder":
        """Ativa warmup automático do TTS (elimina cold start).

        Quando ativado (padrão), o TTS é pré-aquecido durante connect(),
        eliminando a latência de cold start na primeira síntese.

        Impacto típico:
        - Kokoro: reduz primeira síntese de ~500-800ms para ~100-200ms
        - OpenAI: reduz primeira síntese de ~300-500ms para ~150-250ms

        Args:
            enabled: True para ativar warmup automático (default).

        Returns:
            Self for chaining.

        Example:
            >>> agent = (
            ...     VoiceAgent.builder()
            ...     .asr("whisper")
            ...     .llm("ollama")
            ...     .tts("kokoro")
            ...     .streaming(True)
            ...     .warmup(True)  # Elimina cold start
            ...     .build()
            ... )
        """
        self._auto_warmup = enabled
        return self

    def sentence_config(
        self,
        min_chars: Optional[int] = None,
        max_chars: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        enable_quick_phrases: Optional[bool] = None,
    ) -> "VoiceAgentBuilder":
        """Configura o SentenceStreamer para baixa latência.

        O SentenceStreamer bufferiza tokens do LLM e emite sentenças
        completas para o TTS. Esta configuração controla quando as
        sentenças são emitidas.

        Args:
            min_chars: Mínimo de caracteres antes de emitir (default 20).
                       Sentenças curtas como "Olá!" usam min_chars menor.
            max_chars: Máximo de caracteres antes de forçar emissão (default 200).
            timeout_ms: Emite buffer após este tempo sem pontuação (default 500).
                        Útil para quando o LLM pausa sem terminar a frase.
            enable_quick_phrases: Emite frases comuns ("Olá!", "Sim.")
                                  imediatamente (default True).

        Returns:
            Self for chaining.

        Example:
            >>> # Configuração agressiva para latência mínima
            >>> agent = (
            ...     VoiceAgent.builder()
            ...     .asr("whisper")
            ...     .llm("ollama")
            ...     .tts("kokoro")
            ...     .streaming(True)
            ...     .sentence_config(
            ...         min_chars=10,      # Emite sentenças menores
            ...         timeout_ms=300,    # Timeout mais curto
            ...     )
            ...     .build()
            ... )
        """
        if min_chars is not None:
            self._min_sentence_chars = min_chars
        if max_chars is not None:
            self._max_sentence_chars = max_chars
        if timeout_ms is not None:
            self._sentence_timeout_ms = timeout_ms
        if enable_quick_phrases is not None:
            self._enable_quick_phrases = enable_quick_phrases
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

    def max_messages(self, n: int) -> "VoiceAgentBuilder":
        """Define máximo de mensagens no histórico de conversação.

        Controla quantas mensagens são mantidas no histórico das chains
        (StreamingVoiceChain e ParallelStreamingChain). Mensagens mais
        antigas são descartadas quando o limite é atingido.

        Args:
            n: Máximo de mensagens. 0 para ilimitado (não recomendado).

        Returns:
            Self for chaining.

        Example:
            >>> agent = (
            ...     VoiceAgent.builder()
            ...     .asr("whisper")
            ...     .llm("ollama")
            ...     .tts("kokoro")
            ...     .max_messages(50)  # Histórico maior
            ...     .build()
            ... )
        """
        self._max_messages = n
        return self

    def max_iterations(self, n: int) -> "VoiceAgentBuilder":
        """Define máximo de iterações."""
        self._max_iterations = n
        return self

    def rag(
        self,
        provider: str = "faiss",
        embedding: str = "sentence-transformers",
        documents: Optional[list] = None,
        k: int = 5,
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura RAG (Retrieval-Augmented Generation).

        RAG permite que o agente responda perguntas usando uma base
        de conhecimento de documentos.

        Args:
            provider: Vector store provider ("faiss").
            embedding: Embedding provider ("sentence-transformers").
            documents: Lista de documentos para indexar (opcional).
                       Pode ser lista de strings ou Document objects.
            k: Número de documentos a recuperar por query.
            **kwargs: Argumentos adicionais para os providers.

        Returns:
            Self for chaining.

        Example:
            >>> # RAG com documentos simples
            >>> agent = (
            ...     VoiceAgent.builder()
            ...     .asr("whisper")
            ...     .llm("ollama")
            ...     .tts("kokoro")
            ...     .rag("faiss", documents=[
            ...         "Voice Pipeline é um framework para agentes de voz.",
            ...         "Suporta ASR streaming com Deepgram.",
            ...     ])
            ...     .build()
            ... )
            >>>
            >>> # RAG com Document objects
            >>> from voice_pipeline.interfaces import Document
            >>> agent = (
            ...     VoiceAgent.builder()
            ...     .llm("ollama")
            ...     .rag("faiss", documents=[
            ...         Document(content="...", metadata={"source": "docs/intro.md"}),
            ...     ])
            ...     .build()
            ... )
        """
        from voice_pipeline.interfaces.rag import Document, SimpleRAG

        self._rag_k = k

        # Create embedding provider
        if embedding == "sentence-transformers":
            from voice_pipeline.providers.embedding import SentenceTransformerEmbedding
            embedding_model = kwargs.pop("embedding_model", "all-MiniLM-L6-v2")
            embedding_provider = SentenceTransformerEmbedding(model_name=embedding_model)
        else:
            raise ValueError(f"Embedding provider desconhecido: {embedding}")

        # Get embedding dimension (lazy load model)
        dimension = embedding_provider.dimension

        # Create vector store
        if provider == "faiss":
            from voice_pipeline.providers.vectorstore import FAISSVectorStore
            vector_store = FAISSVectorStore(dimension=dimension, **kwargs)
        else:
            raise ValueError(f"Vector store provider desconhecido: {provider}")

        # Create RAG
        self._rag = SimpleRAG(vector_store, embedding_provider)

        # Store documents for async indexing in build_async
        self._rag_documents = documents

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
                    rag=self._rag,
                    rag_k=self._rag_k,
                    system_prompt=self._system_prompt or "Você é um assistente de voz.",
                    language=self._language,
                    tts_voice=self._tts_voice,
                    auto_warmup=self._auto_warmup,
                    min_sentence_chars=self._min_sentence_chars,
                    max_sentence_chars=self._max_sentence_chars,
                    max_messages=self._max_messages,
                    turn_taking_controller=self._turn_taking_controller,
                    streaming_strategy=self._streaming_strategy,
                    interruption_strategy=self._interruption_strategy,
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

        Para StreamingVoiceChain (streaming=True), também faz warmup do TTS
        para eliminar latência de cold-start.

        Também indexa documentos RAG se configurados.

        Returns:
            VoiceAgent, ConversationChain ou StreamingVoiceChain com providers conectados.
        """
        result = self.build()

        # Se StreamingVoiceChain, usar seu connect() que faz warmup do TTS
        if self._streaming and self._asr is not None and self._tts is not None:
            # StreamingVoiceChain.connect() conecta providers e faz warmup
            await result.connect()
            # VAD é separado (não faz parte do StreamingVoiceChain)
            if self._vad is not None:
                await self._vad.connect()
        else:
            # Conectar providers individualmente
            if self._asr is not None:
                await self._asr.connect()
            if self._llm is not None:
                await self._llm.connect()
            if self._tts is not None:
                await self._tts.connect()
            if self._vad is not None:
                await self._vad.connect()

        # Index RAG documents if provided
        if self._rag is not None and hasattr(self, '_rag_documents') and self._rag_documents:
            from voice_pipeline.interfaces.rag import Document

            # Convert strings to Document objects if needed
            docs = []
            for doc in self._rag_documents:
                if isinstance(doc, str):
                    docs.append(Document(content=doc))
                else:
                    docs.append(doc)

            # Index documents
            await self._rag.add_documents(docs)
            logger.info(f"Indexed {len(docs)} documents for RAG")

        return result
