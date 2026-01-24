"""Pipeline Builder for easy pipeline construction.

Provides a fluent API for building voice pipelines with various providers.
"""

from dataclasses import dataclass, field
from typing import Optional, Type, TypeVar, Any, Callable

from .config import PipelineConfig
from .pipeline import Pipeline
from ..interfaces import ASRInterface, LLMInterface, TTSInterface, VADInterface
from ..interfaces.transport import AudioTransportInterface
from ..interfaces.realtime import RealtimeInterface
from ..callbacks import VoiceCallbackHandler, CallbackManager


T = TypeVar("T")


@dataclass
class ProviderConfig:
    """Configuration for a provider instance."""

    provider_class: Type
    kwargs: dict[str, Any] = field(default_factory=dict)


class PipelineBuilder:
    """Fluent builder for creating voice pipelines.

    Provides a clean API for configuring and building pipelines with
    various providers and settings.

    Example:
        pipeline = (
            PipelineBuilder()
            .with_config(system_prompt="You are a helpful assistant.")
            .with_asr(WhisperASR, model="base")
            .with_llm(OllamaLLM, model="llama3")
            .with_tts(KokoroTTS, voice="af_bella")
            .with_vad(SileroVAD)
            .with_callback(LoggingHandler())
            .build()
        )
    """

    def __init__(self):
        """Initialize builder with defaults."""
        self._config: Optional[PipelineConfig] = None
        self._asr: Optional[ProviderConfig] = None
        self._llm: Optional[ProviderConfig] = None
        self._tts: Optional[ProviderConfig] = None
        self._vad: Optional[ProviderConfig] = None
        self._transport: Optional[ProviderConfig] = None
        self._realtime: Optional[ProviderConfig] = None
        self._callbacks: list[VoiceCallbackHandler] = []
        self._on_error: Optional[Callable[[Exception], None]] = None

        # Pre-built instances (alternative to classes)
        self._asr_instance: Optional[ASRInterface] = None
        self._llm_instance: Optional[LLMInterface] = None
        self._tts_instance: Optional[TTSInterface] = None
        self._vad_instance: Optional[VADInterface] = None
        self._transport_instance: Optional[AudioTransportInterface] = None
        self._realtime_instance: Optional[RealtimeInterface] = None

    def with_config(
        self,
        config: Optional[PipelineConfig] = None,
        **kwargs,
    ) -> "PipelineBuilder":
        """Set pipeline configuration.

        Args:
            config: Pre-built config, or pass kwargs to create one.
            **kwargs: Arguments for PipelineConfig if config not provided.

        Returns:
            Self for chaining.
        """
        if config:
            self._config = config
        else:
            self._config = PipelineConfig(**kwargs)
        return self

    def with_asr(
        self,
        asr: Type[ASRInterface] | ASRInterface,
        **kwargs,
    ) -> "PipelineBuilder":
        """Set ASR provider.

        Args:
            asr: ASR class or instance.
            **kwargs: Arguments for ASR constructor.

        Returns:
            Self for chaining.
        """
        if isinstance(asr, type):
            self._asr = ProviderConfig(provider_class=asr, kwargs=kwargs)
        else:
            self._asr_instance = asr
        return self

    def with_llm(
        self,
        llm: Type[LLMInterface] | LLMInterface,
        **kwargs,
    ) -> "PipelineBuilder":
        """Set LLM provider.

        Args:
            llm: LLM class or instance.
            **kwargs: Arguments for LLM constructor.

        Returns:
            Self for chaining.
        """
        if isinstance(llm, type):
            self._llm = ProviderConfig(provider_class=llm, kwargs=kwargs)
        else:
            self._llm_instance = llm
        return self

    def with_tts(
        self,
        tts: Type[TTSInterface] | TTSInterface,
        **kwargs,
    ) -> "PipelineBuilder":
        """Set TTS provider.

        Args:
            tts: TTS class or instance.
            **kwargs: Arguments for TTS constructor.

        Returns:
            Self for chaining.
        """
        if isinstance(tts, type):
            self._tts = ProviderConfig(provider_class=tts, kwargs=kwargs)
        else:
            self._tts_instance = tts
        return self

    def with_vad(
        self,
        vad: Type[VADInterface] | VADInterface,
        **kwargs,
    ) -> "PipelineBuilder":
        """Set VAD provider.

        Args:
            vad: VAD class or instance.
            **kwargs: Arguments for VAD constructor.

        Returns:
            Self for chaining.
        """
        if isinstance(vad, type):
            self._vad = ProviderConfig(provider_class=vad, kwargs=kwargs)
        else:
            self._vad_instance = vad
        return self

    def with_transport(
        self,
        transport: Type[AudioTransportInterface] | AudioTransportInterface,
        **kwargs,
    ) -> "PipelineBuilder":
        """Set audio transport.

        Args:
            transport: Transport class or instance.
            **kwargs: Arguments for transport constructor.

        Returns:
            Self for chaining.
        """
        if isinstance(transport, type):
            self._transport = ProviderConfig(provider_class=transport, kwargs=kwargs)
        else:
            self._transport_instance = transport
        return self

    def with_realtime(
        self,
        realtime: Type[RealtimeInterface] | RealtimeInterface,
        **kwargs,
    ) -> "PipelineBuilder":
        """Set realtime provider (replaces ASR+LLM+TTS).

        Args:
            realtime: Realtime class or instance.
            **kwargs: Arguments for realtime constructor.

        Returns:
            Self for chaining.
        """
        if isinstance(realtime, type):
            self._realtime = ProviderConfig(provider_class=realtime, kwargs=kwargs)
        else:
            self._realtime_instance = realtime
        return self

    def with_callback(
        self,
        handler: VoiceCallbackHandler,
    ) -> "PipelineBuilder":
        """Add callback handler.

        Args:
            handler: Callback handler to add.

        Returns:
            Self for chaining.
        """
        self._callbacks.append(handler)
        return self

    def with_callbacks(
        self,
        handlers: list[VoiceCallbackHandler],
    ) -> "PipelineBuilder":
        """Add multiple callback handlers.

        Args:
            handlers: List of callback handlers.

        Returns:
            Self for chaining.
        """
        self._callbacks.extend(handlers)
        return self

    def on_error(
        self,
        handler: Callable[[Exception], None],
    ) -> "PipelineBuilder":
        """Set error handler.

        Args:
            handler: Function to call on errors.

        Returns:
            Self for chaining.
        """
        self._on_error = handler
        return self

    def _build_provider(self, config: Optional[ProviderConfig]) -> Optional[Any]:
        """Build a provider from config."""
        if config is None:
            return None
        return config.provider_class(**config.kwargs)

    def build(self) -> Pipeline:
        """Build the pipeline.

        Returns:
            Configured Pipeline instance.

        Raises:
            ValueError: If required providers are missing.
        """
        # Create config if not set
        if self._config is None:
            self._config = PipelineConfig()

        # Build or use provider instances
        asr = self._asr_instance or self._build_provider(self._asr)
        llm = self._llm_instance or self._build_provider(self._llm)
        tts = self._tts_instance or self._build_provider(self._tts)
        vad = self._vad_instance or self._build_provider(self._vad)

        # Validate required providers
        if not asr:
            raise ValueError("ASR provider is required. Use with_asr()")
        if not llm:
            raise ValueError("LLM provider is required. Use with_llm()")
        if not tts:
            raise ValueError("TTS provider is required. Use with_tts()")
        if not vad:
            raise ValueError("VAD provider is required. Use with_vad()")

        # Create pipeline
        pipeline = Pipeline(
            config=self._config,
            asr=asr,
            llm=llm,
            tts=tts,
            vad=vad,
        )

        return pipeline

    def build_chain(self):
        """Build a simple ASR | LLM | TTS chain.

        Returns:
            VoiceSequence chain.

        Raises:
            ValueError: If required providers are missing.
        """
        from ..runnable import VoiceSequence

        # Build or use provider instances
        asr = self._asr_instance or self._build_provider(self._asr)
        llm = self._llm_instance or self._build_provider(self._llm)
        tts = self._tts_instance or self._build_provider(self._tts)

        if not asr:
            raise ValueError("ASR provider is required. Use with_asr()")
        if not llm:
            raise ValueError("LLM provider is required. Use with_llm()")
        if not tts:
            raise ValueError("TTS provider is required. Use with_tts()")

        return VoiceSequence([asr, llm, tts])


class QuickPipeline:
    """Quick pipeline creation with sensible defaults.

    Provides factory methods for common pipeline configurations.
    """

    @staticmethod
    def local(
        system_prompt: str = "You are a helpful voice assistant.",
        asr_model: str = "base",
        llm_model: str = "llama3",
        tts_voice: str = "af_bella",
    ) -> PipelineBuilder:
        """Create a pipeline with local providers.

        Args:
            system_prompt: System prompt for the LLM.
            asr_model: Whisper model size.
            llm_model: Ollama model name.
            tts_voice: Kokoro voice name.

        Returns:
            PipelineBuilder configured for local providers.
        """
        # Import local providers
        from ..providers.asr_whisper import WhisperASR
        from ..providers.llm_ollama import OllamaLLM
        from ..providers.tts_kokoro import KokoroTTS
        from ..providers.vad_silero import SileroVAD

        return (
            PipelineBuilder()
            .with_config(system_prompt=system_prompt)
            .with_asr(WhisperASR, model=asr_model)
            .with_llm(OllamaLLM, model=llm_model)
            .with_tts(KokoroTTS, voice=tts_voice)
            .with_vad(SileroVAD)
        )

    @staticmethod
    def openai(
        api_key: str,
        system_prompt: str = "You are a helpful voice assistant.",
        model: str = "gpt-4o",
        voice: str = "alloy",
    ) -> PipelineBuilder:
        """Create a pipeline with OpenAI providers.

        Args:
            api_key: OpenAI API key.
            system_prompt: System prompt for the LLM.
            model: OpenAI model name.
            voice: TTS voice name.

        Returns:
            PipelineBuilder configured for OpenAI providers.
        """
        from ..providers.tts_openai import OpenAITTS
        from ..providers.vad_silero import SileroVAD

        return (
            PipelineBuilder()
            .with_config(system_prompt=system_prompt)
            .with_tts(OpenAITTS, api_key=api_key, voice=voice)
            .with_vad(SileroVAD)
        )

    @staticmethod
    def realtime_openai(
        api_key: str,
        system_prompt: str = "You are a helpful voice assistant.",
        voice: str = "alloy",
    ) -> PipelineBuilder:
        """Create a pipeline with OpenAI Realtime API.

        Args:
            api_key: OpenAI API key.
            system_prompt: System prompt.
            voice: TTS voice name.

        Returns:
            PipelineBuilder configured for OpenAI Realtime.
        """
        from ..providers.realtime_openai import OpenAIRealtimeProvider

        return (
            PipelineBuilder()
            .with_config(system_prompt=system_prompt)
            .with_realtime(
                OpenAIRealtimeProvider,
                api_key=api_key,
                voice=voice,
            )
        )
