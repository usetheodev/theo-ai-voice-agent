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
"""

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
