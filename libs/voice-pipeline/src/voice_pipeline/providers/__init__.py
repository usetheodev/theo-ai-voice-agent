"""
Provider Registry for Voice Pipeline.

This module provides a central registry for discovering and managing
voice pipeline providers (ASR, LLM, TTS, VAD).

Quick Start:
    >>> from voice_pipeline.providers import get_registry
    >>> registry = get_registry()

    >>> # List available providers
    >>> print(registry.list_providers())
    {'asr': ['whisper'], 'llm': ['ollama'], ...}

    >>> # Get a provider instance
    >>> asr = registry.get_asr("whisper", model="base")

Registration via Decorators:
    >>> from voice_pipeline.providers import register_asr, ASRCapabilities
    >>> @register_asr("my-asr", capabilities=ASRCapabilities(streaming=True))
    ... class MyASR(ASRInterface):
    ...     async def transcribe_stream(self, audio_stream, language=None):
    ...         ...

Manual Registration:
    >>> registry.register_asr(
    ...     name="my-asr",
    ...     provider_class=MyASR,
    ...     capabilities=ASRCapabilities(streaming=True),
    ... )

Auto-discovery:
    >>> # Discover providers from installed packages
    >>> registry.auto_discover()

Simple Usage with Aliases:
    >>> from voice_pipeline.providers import WhisperASR, OllamaLLM, KokoroTTS
    >>> chain = WhisperASR() | OllamaLLM() | KokoroTTS()
"""

# ============================================================================
# Provider Implementations (with friendly aliases)
# ============================================================================

# ASR Providers
from voice_pipeline.providers.asr import (
    WhisperCppASRProvider,
    WhisperCppASRConfig,
    OpenAIASRProvider,
    OpenAIASRConfig,
)

# Friendly aliases for ASR
WhisperASR = WhisperCppASRProvider
WhisperASRConfig = WhisperCppASRConfig
OpenAIASR = OpenAIASRProvider

# LLM Providers
from voice_pipeline.providers.llm import (
    OllamaLLMProvider,
    OllamaLLMConfig,
    OpenAILLMProvider,
    OpenAILLMConfig,
)

# Friendly aliases for LLM
OllamaLLM = OllamaLLMProvider
OpenAILLM = OpenAILLMProvider

# TTS Providers
from voice_pipeline.providers.tts import (
    KokoroTTSProvider,
    KokoroTTSConfig,
    OpenAITTSProvider,
    OpenAITTSConfig,
)

# Friendly aliases for TTS
KokoroTTS = KokoroTTSProvider
OpenAITTS = OpenAITTSProvider

# VAD Providers
from voice_pipeline.providers.vad import (
    SileroVADProvider,
    SileroVADConfig,
    WebRTCVADProvider,
    WebRTCVADConfig,
)

# Friendly aliases for VAD
SileroVAD = SileroVADProvider
WebRTCVAD = WebRTCVADProvider

# Realtime Providers
from voice_pipeline.providers.realtime import (
    OpenAIRealtimeProvider,
    OpenAIRealtimeConfig,
)

# Friendly alias for Realtime
OpenAIRealtime = OpenAIRealtimeProvider

# Embedding Providers
from voice_pipeline.providers.embedding import (
    SentenceTransformerEmbedding,
    SentenceTransformerEmbeddingConfig,
)

# Vector Store Providers
from voice_pipeline.providers.vectorstore import (
    FAISSVectorStore,
    FAISSVectorStoreConfig,
)

# ============================================================================
# Base classes and utilities
# ============================================================================

from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    NonRetryableError,
    ProviderConfig,
    ProviderHealth,
    ProviderMetrics,
    RetryableError,
    config_from_env,
)
from voice_pipeline.providers.decorators import (
    register_asr,
    register_llm,
    register_provider,
    register_tts,
    register_vad,
)
from voice_pipeline.providers.discovery import (
    discover_from_module,
    discover_providers,
    get_provider_metadata,
    list_available_packages,
)
from voice_pipeline.providers.registry import (
    ProviderRegistry,
    get_registry,
    reset_registry,
)
from voice_pipeline.providers.types import (
    ASRCapabilities,
    Capabilities,
    LLMCapabilities,
    ProviderInfo,
    ProviderInstance,
    ProviderType,
    TTSCapabilities,
    VADCapabilities,
)

__all__ = [
    # ========================================================================
    # Provider Classes (full names)
    # ========================================================================
    # ASR
    "WhisperCppASRProvider",
    "WhisperCppASRConfig",
    "OpenAIASRProvider",
    "OpenAIASRConfig",
    # LLM
    "OllamaLLMProvider",
    "OllamaLLMConfig",
    "OpenAILLMProvider",
    "OpenAILLMConfig",
    # TTS
    "KokoroTTSProvider",
    "KokoroTTSConfig",
    "OpenAITTSProvider",
    "OpenAITTSConfig",
    # VAD
    "SileroVADProvider",
    "SileroVADConfig",
    "WebRTCVADProvider",
    "WebRTCVADConfig",
    # Realtime
    "OpenAIRealtimeProvider",
    "OpenAIRealtimeConfig",
    # ========================================================================
    # Friendly Aliases (recommended for simple usage)
    # ========================================================================
    # ASR aliases
    "WhisperASR",
    "WhisperASRConfig",
    "OpenAIASR",
    # LLM aliases
    "OllamaLLM",
    "OpenAILLM",
    # TTS aliases
    "KokoroTTS",
    "OpenAITTS",
    # VAD aliases
    "SileroVAD",
    "WebRTCVAD",
    # Realtime aliases
    "OpenAIRealtime",
    # Embedding
    "SentenceTransformerEmbedding",
    "SentenceTransformerEmbeddingConfig",
    # Vector Store
    "FAISSVectorStore",
    "FAISSVectorStoreConfig",
    # ========================================================================
    # Base classes and utilities
    # ========================================================================
    # Base
    "BaseProvider",
    "ProviderConfig",
    "ProviderHealth",
    "ProviderMetrics",
    "HealthCheckResult",
    "RetryableError",
    "NonRetryableError",
    "config_from_env",
    # Registry
    "ProviderRegistry",
    "get_registry",
    "reset_registry",
    # Types
    "ProviderType",
    "ProviderInfo",
    "ProviderInstance",
    "Capabilities",
    "ASRCapabilities",
    "LLMCapabilities",
    "TTSCapabilities",
    "VADCapabilities",
    # Decorators
    "register_asr",
    "register_llm",
    "register_tts",
    "register_vad",
    "register_provider",
    # Discovery
    "discover_providers",
    "discover_from_module",
    "list_available_packages",
    "get_provider_metadata",
]
