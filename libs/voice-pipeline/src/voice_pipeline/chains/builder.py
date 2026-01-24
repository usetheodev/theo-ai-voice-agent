"""
VoiceChainBuilder for fluent API construction of voice pipelines.

Provides a builder pattern for creating VoiceChain instances
with a clean, readable syntax.
"""

from typing import Any, Optional, TypeVar, Union

from voice_pipeline.interfaces import (
    ASRInterface,
    LLMInterface,
    TTSInterface,
    VADInterface,
)
from voice_pipeline.providers import ProviderRegistry, get_registry

T = TypeVar("T", bound="VoiceChainBuilder")


class VoiceChainBuilder:
    """
    Builder for constructing VoiceChain instances.

    Provides a fluent API for configuring voice pipelines:

    Example:
        >>> chain = (
        ...     VoiceChain.builder()
        ...     .with_asr("whisper", model="base")
        ...     .with_llm("ollama", model="llama3")
        ...     .with_tts("piper", voice="pt_BR-faber")
        ...     .with_system_prompt("You are a helpful assistant.")
        ...     .with_language("pt-BR")
        ...     .enable_barge_in(threshold_ms=200)
        ...     .build()
        ... )

    Or with provider instances:
        >>> chain = (
        ...     VoiceChain.builder()
        ...     .with_asr_instance(my_asr)
        ...     .with_llm_instance(my_llm)
        ...     .with_tts_instance(my_tts)
        ...     .build()
        ... )
    """

    def __init__(self, registry: Optional[ProviderRegistry] = None):
        """
        Initialize the builder.

        Args:
            registry: Provider registry to use. Defaults to global registry.
        """
        self._registry = registry or get_registry()

        # Provider instances
        self._asr: Optional[ASRInterface] = None
        self._llm: Optional[LLMInterface] = None
        self._tts: Optional[TTSInterface] = None
        self._vad: Optional[VADInterface] = None

        # Configuration
        self._system_prompt: Optional[str] = None
        self._language: Optional[str] = None
        self._tts_voice: Optional[str] = None
        self._llm_temperature: float = 0.7
        self._llm_max_tokens: Optional[int] = None

        # Barge-in
        self._enable_barge_in: bool = True
        self._barge_in_threshold_ms: int = 200
        self._barge_in_backoff_ms: int = 100

        # Memory
        self._memory = None
        self._max_history: Optional[int] = None

    # ==================== ASR ====================

    def with_asr(self: T, name: str, **config) -> T:
        """
        Configure ASR provider by name.

        Args:
            name: Provider name (e.g., "whisper", "deepgram").
            **config: Provider configuration.

        Returns:
            Self for chaining.
        """
        self._asr = self._registry.get_asr(name, **config)
        return self

    def with_asr_instance(self: T, asr: ASRInterface) -> T:
        """
        Configure ASR with an existing instance.

        Args:
            asr: ASR provider instance.

        Returns:
            Self for chaining.
        """
        self._asr = asr
        return self

    # ==================== LLM ====================

    def with_llm(self: T, name: str, **config) -> T:
        """
        Configure LLM provider by name.

        Args:
            name: Provider name (e.g., "ollama", "openai").
            **config: Provider configuration.

        Returns:
            Self for chaining.
        """
        self._llm = self._registry.get_llm(name, **config)
        return self

    def with_llm_instance(self: T, llm: LLMInterface) -> T:
        """
        Configure LLM with an existing instance.

        Args:
            llm: LLM provider instance.

        Returns:
            Self for chaining.
        """
        self._llm = llm
        return self

    # ==================== TTS ====================

    def with_tts(self: T, name: str, **config) -> T:
        """
        Configure TTS provider by name.

        Args:
            name: Provider name (e.g., "piper", "elevenlabs").
            **config: Provider configuration.

        Returns:
            Self for chaining.
        """
        self._tts = self._registry.get_tts(name, **config)
        return self

    def with_tts_instance(self: T, tts: TTSInterface) -> T:
        """
        Configure TTS with an existing instance.

        Args:
            tts: TTS provider instance.

        Returns:
            Self for chaining.
        """
        self._tts = tts
        return self

    # ==================== VAD ====================

    def with_vad(self: T, name: str, **config) -> T:
        """
        Configure VAD provider by name.

        Args:
            name: Provider name (e.g., "silero", "webrtc").
            **config: Provider configuration.

        Returns:
            Self for chaining.
        """
        self._vad = self._registry.get_vad(name, **config)
        return self

    def with_vad_instance(self: T, vad: VADInterface) -> T:
        """
        Configure VAD with an existing instance.

        Args:
            vad: VAD provider instance.

        Returns:
            Self for chaining.
        """
        self._vad = vad
        return self

    # ==================== Configuration ====================

    def with_system_prompt(self: T, prompt: str) -> T:
        """
        Set the system prompt for the LLM.

        Args:
            prompt: System prompt text.

        Returns:
            Self for chaining.
        """
        self._system_prompt = prompt
        return self

    def with_language(self: T, language: str) -> T:
        """
        Set the language for ASR.

        Args:
            language: Language code (e.g., "pt-BR", "en-US").

        Returns:
            Self for chaining.
        """
        self._language = language
        return self

    def with_voice(self: T, voice: str) -> T:
        """
        Set the TTS voice.

        Args:
            voice: Voice identifier.

        Returns:
            Self for chaining.
        """
        self._tts_voice = voice
        return self

    def with_temperature(self: T, temperature: float) -> T:
        """
        Set the LLM temperature.

        Args:
            temperature: Sampling temperature (0.0 to 2.0).

        Returns:
            Self for chaining.
        """
        self._llm_temperature = temperature
        return self

    def with_max_tokens(self: T, max_tokens: int) -> T:
        """
        Set the maximum tokens for LLM response.

        Args:
            max_tokens: Maximum number of tokens.

        Returns:
            Self for chaining.
        """
        self._llm_max_tokens = max_tokens
        return self

    # ==================== Barge-in ====================

    def enable_barge_in(
        self: T,
        threshold_ms: int = 200,
        backoff_ms: int = 100,
    ) -> T:
        """
        Enable barge-in (user interruption).

        Args:
            threshold_ms: Duration of speech before triggering barge-in.
            backoff_ms: Wait time after barge-in before processing.

        Returns:
            Self for chaining.
        """
        self._enable_barge_in = True
        self._barge_in_threshold_ms = threshold_ms
        self._barge_in_backoff_ms = backoff_ms
        return self

    def disable_barge_in(self: T) -> T:
        """
        Disable barge-in.

        Returns:
            Self for chaining.
        """
        self._enable_barge_in = False
        return self

    # ==================== Memory ====================

    def with_memory(self: T, memory: Any) -> T:
        """
        Configure conversation memory.

        Args:
            memory: Memory instance (e.g., ConversationBufferMemory).

        Returns:
            Self for chaining.
        """
        self._memory = memory
        return self

    def with_max_history(self: T, max_messages: int) -> T:
        """
        Limit conversation history size.

        Args:
            max_messages: Maximum number of messages to keep.

        Returns:
            Self for chaining.
        """
        self._max_history = max_messages
        return self

    # ==================== Build ====================

    def build(self):
        """
        Build the VoiceChain instance.

        Returns:
            Configured VoiceChain.

        Raises:
            ValueError: If required components are missing.
        """
        from voice_pipeline.chains.base import VoiceChain

        if self._asr is None:
            raise ValueError("ASR provider is required. Use with_asr() or with_asr_instance().")

        if self._llm is None:
            raise ValueError("LLM provider is required. Use with_llm() or with_llm_instance().")

        if self._tts is None:
            raise ValueError("TTS provider is required. Use with_tts() or with_tts_instance().")

        return VoiceChain(
            asr=self._asr,
            llm=self._llm,
            tts=self._tts,
            vad=self._vad,
            system_prompt=self._system_prompt,
            language=self._language,
            tts_voice=self._tts_voice,
            llm_temperature=self._llm_temperature,
            llm_max_tokens=self._llm_max_tokens,
        )

    def build_conversation(self):
        """
        Build a ConversationChain instance.

        Returns:
            Configured ConversationChain.
        """
        from voice_pipeline.chains.conversation import ConversationChain

        if self._asr is None:
            raise ValueError("ASR provider is required.")

        if self._llm is None:
            raise ValueError("LLM provider is required.")

        if self._tts is None:
            raise ValueError("TTS provider is required.")

        return ConversationChain(
            asr=self._asr,
            llm=self._llm,
            tts=self._tts,
            vad=self._vad,
            system_prompt=self._system_prompt,
            language=self._language,
            tts_voice=self._tts_voice,
            llm_temperature=self._llm_temperature,
            memory=self._memory,
            max_history=self._max_history,
            enable_barge_in=self._enable_barge_in,
            barge_in_threshold_ms=self._barge_in_threshold_ms,
        )


def voice_chain() -> VoiceChainBuilder:
    """
    Create a new VoiceChainBuilder.

    Convenience function for starting a builder chain.

    Example:
        >>> chain = (
        ...     voice_chain()
        ...     .with_asr("whisper")
        ...     .with_llm("ollama")
        ...     .with_tts("piper")
        ...     .build()
        ... )
    """
    return VoiceChainBuilder()
