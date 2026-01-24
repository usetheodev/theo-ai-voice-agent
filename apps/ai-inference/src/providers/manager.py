"""Provider Manager - Registry and Factory for providers."""

import logging
from typing import Optional, Type

from .base import ASRProvider, LLMProvider, TTSProvider, VADProvider
from .exceptions import ProviderNotFoundError, ProviderConfigError

logger = logging.getLogger(__name__)


class ProviderManager:
    """Central registry and factory for all providers.

    Singleton that manages provider registration and instantiation.
    """

    _instance: Optional["ProviderManager"] = None

    def __init__(self):
        # Registered provider classes
        self._asr_providers: dict[str, Type[ASRProvider]] = {}
        self._llm_providers: dict[str, Type[LLMProvider]] = {}
        self._tts_providers: dict[str, Type[TTSProvider]] = {}
        self._vad_providers: dict[str, Type[VADProvider]] = {}

        # Cached instances (for reuse)
        self._asr_instances: dict[str, ASRProvider] = {}
        self._llm_instances: dict[str, LLMProvider] = {}
        self._tts_instances: dict[str, TTSProvider] = {}
        self._vad_instances: dict[str, VADProvider] = {}

    # =========================================================================
    # REGISTRATION
    # =========================================================================

    def register_asr(self, name: str, provider_class: Type[ASRProvider]) -> None:
        """Register an ASR provider class."""
        self._asr_providers[name] = provider_class
        logger.debug(f"Registered ASR provider: {name}")

    def register_llm(self, name: str, provider_class: Type[LLMProvider]) -> None:
        """Register an LLM provider class."""
        self._llm_providers[name] = provider_class
        logger.debug(f"Registered LLM provider: {name}")

    def register_tts(self, name: str, provider_class: Type[TTSProvider]) -> None:
        """Register a TTS provider class."""
        self._tts_providers[name] = provider_class
        logger.debug(f"Registered TTS provider: {name}")

    def register_vad(self, name: str, provider_class: Type[VADProvider]) -> None:
        """Register a VAD provider class."""
        self._vad_providers[name] = provider_class
        logger.debug(f"Registered VAD provider: {name}")

    # =========================================================================
    # FACTORY METHODS
    # =========================================================================

    def get_asr(
        self,
        name: str,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        cache: bool = True,
        **kwargs,
    ) -> ASRProvider:
        """Get or create an ASR provider instance.

        Args:
            name: Provider name (e.g., 'deepgram', 'whisper').
            api_base: API base URL.
            api_key: API key.
            cache: Whether to cache and reuse the instance.

        Returns:
            ASR provider instance.
        """
        cache_key = f"{name}:{api_base}"

        if cache and cache_key in self._asr_instances:
            return self._asr_instances[cache_key]

        if name not in self._asr_providers:
            available = list(self._asr_providers.keys())
            raise ProviderNotFoundError(
                f"ASR provider '{name}' not found. Available: {available}",
                provider=name,
            )

        provider_class = self._asr_providers[name]
        instance = provider_class(api_base=api_base or "", api_key=api_key, **kwargs)

        if cache:
            self._asr_instances[cache_key] = instance

        logger.info(f"Created ASR provider: {name}")
        return instance

    def get_llm(
        self,
        name: str,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        cache: bool = True,
        **kwargs,
    ) -> LLMProvider:
        """Get or create an LLM provider instance.

        Args:
            name: Provider name (e.g., 'openai', 'ollama').
            api_base: API base URL.
            api_key: API key.
            model: Model name to use.
            cache: Whether to cache and reuse the instance.

        Returns:
            LLM provider instance.
        """
        cache_key = f"{name}:{api_base}:{model}"

        if cache and cache_key in self._llm_instances:
            return self._llm_instances[cache_key]

        if name not in self._llm_providers:
            available = list(self._llm_providers.keys())
            raise ProviderNotFoundError(
                f"LLM provider '{name}' not found. Available: {available}",
                provider=name,
            )

        provider_class = self._llm_providers[name]
        instance = provider_class(
            api_base=api_base or "",
            api_key=api_key,
            model=model,
            **kwargs,
        )

        if cache:
            self._llm_instances[cache_key] = instance

        logger.info(f"Created LLM provider: {name} (model={model})")
        return instance

    def get_tts(
        self,
        name: str,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        voice: Optional[str] = None,
        cache: bool = True,
        **kwargs,
    ) -> TTSProvider:
        """Get or create a TTS provider instance.

        Args:
            name: Provider name (e.g., 'elevenlabs', 'piper').
            api_base: API base URL.
            api_key: API key.
            voice: Default voice to use.
            cache: Whether to cache and reuse the instance.

        Returns:
            TTS provider instance.
        """
        cache_key = f"{name}:{api_base}"

        if cache and cache_key in self._tts_instances:
            return self._tts_instances[cache_key]

        if name not in self._tts_providers:
            available = list(self._tts_providers.keys())
            raise ProviderNotFoundError(
                f"TTS provider '{name}' not found. Available: {available}",
                provider=name,
            )

        provider_class = self._tts_providers[name]
        instance = provider_class(
            api_base=api_base or "",
            api_key=api_key,
            default_voice=voice,
            **kwargs,
        )

        if cache:
            self._tts_instances[cache_key] = instance

        logger.info(f"Created TTS provider: {name}")
        return instance

    def get_vad(
        self,
        name: str,
        cache: bool = True,
        **kwargs,
    ) -> VADProvider:
        """Get or create a VAD provider instance.

        Args:
            name: Provider name (e.g., 'silero', 'webrtc').
            cache: Whether to cache and reuse the instance.

        Returns:
            VAD provider instance.
        """
        if cache and name in self._vad_instances:
            return self._vad_instances[name]

        if name not in self._vad_providers:
            available = list(self._vad_providers.keys())
            raise ProviderNotFoundError(
                f"VAD provider '{name}' not found. Available: {available}",
                provider=name,
            )

        provider_class = self._vad_providers[name]
        instance = provider_class(**kwargs)

        if cache:
            self._vad_instances[name] = instance

        logger.info(f"Created VAD provider: {name}")
        return instance

    # =========================================================================
    # LISTING
    # =========================================================================

    def list_asr_providers(self) -> list[str]:
        """List registered ASR provider names."""
        return list(self._asr_providers.keys())

    def list_llm_providers(self) -> list[str]:
        """List registered LLM provider names."""
        return list(self._llm_providers.keys())

    def list_tts_providers(self) -> list[str]:
        """List registered TTS provider names."""
        return list(self._tts_providers.keys())

    def list_vad_providers(self) -> list[str]:
        """List registered VAD provider names."""
        return list(self._vad_providers.keys())

    # =========================================================================
    # CLEANUP
    # =========================================================================

    def clear_cache(self) -> None:
        """Clear all cached provider instances."""
        self._asr_instances.clear()
        self._llm_instances.clear()
        self._tts_instances.clear()
        self._vad_instances.clear()
        logger.info("Cleared provider cache")


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_manager: Optional[ProviderManager] = None


def get_provider_manager() -> ProviderManager:
    """Get the singleton ProviderManager instance."""
    global _manager
    if _manager is None:
        _manager = ProviderManager()
        _register_default_providers(_manager)
    return _manager


def _register_default_providers(manager: ProviderManager) -> None:
    """Register default provider implementations.

    Lazy imports to avoid circular dependencies.
    """
    try:
        from .asr import OpenAIWhisperASR, DeepgramASR
        manager.register_asr("openai-whisper", OpenAIWhisperASR)
        manager.register_asr("deepgram", DeepgramASR)
    except ImportError as e:
        logger.warning(f"Failed to register ASR providers: {e}")

    try:
        from .llm import OpenAILLM, OllamaLLM, GroqLLM
        manager.register_llm("openai", OpenAILLM)
        manager.register_llm("ollama", OllamaLLM)
        manager.register_llm("groq", GroqLLM)
    except ImportError as e:
        logger.warning(f"Failed to register LLM providers: {e}")

    try:
        from .tts import OpenAITTS, ElevenLabsTTS
        manager.register_tts("openai-tts", OpenAITTS)
        manager.register_tts("elevenlabs", ElevenLabsTTS)
    except ImportError as e:
        logger.warning(f"Failed to register TTS providers: {e}")

    try:
        from .vad import SileroVAD, EnergyVAD
        manager.register_vad("silero", SileroVAD)
        manager.register_vad("energy", EnergyVAD)
    except ImportError as e:
        logger.warning(f"Failed to register VAD providers: {e}")

    logger.info(
        f"Registered providers: "
        f"ASR={manager.list_asr_providers()}, "
        f"LLM={manager.list_llm_providers()}, "
        f"TTS={manager.list_tts_providers()}, "
        f"VAD={manager.list_vad_providers()}"
    )
