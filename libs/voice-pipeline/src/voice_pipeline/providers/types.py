"""
Types and capabilities for Voice Pipeline providers.

This module defines the data structures used to describe providers
and their capabilities in the registry.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ProviderType(Enum):
    """Type of voice provider."""

    ASR = "asr"
    """Automatic Speech Recognition provider."""

    LLM = "llm"
    """Large Language Model provider."""

    TTS = "tts"
    """Text-to-Speech provider."""

    VAD = "vad"
    """Voice Activity Detection provider."""


@dataclass
class ASRCapabilities:
    """Capabilities of an ASR provider."""

    streaming: bool = True
    """Supports streaming transcription."""

    languages: list[str] = field(default_factory=lambda: ["en"])
    """Supported language codes."""

    real_time: bool = True
    """Supports real-time transcription."""

    word_timestamps: bool = False
    """Provides word-level timestamps."""

    speaker_diarization: bool = False
    """Supports speaker identification."""

    punctuation: bool = True
    """Automatically adds punctuation."""

    profanity_filter: bool = False
    """Supports profanity filtering."""


@dataclass
class LLMCapabilities:
    """Capabilities of an LLM provider."""

    streaming: bool = True
    """Supports streaming token generation."""

    function_calling: bool = False
    """Supports function/tool calling."""

    vision: bool = False
    """Supports image inputs."""

    context_window: int = 4096
    """Maximum context window size in tokens."""

    max_output_tokens: Optional[int] = None
    """Maximum output tokens (None = unlimited)."""

    system_prompt: bool = True
    """Supports system prompts."""


@dataclass
class TTSCapabilities:
    """Capabilities of a TTS provider."""

    streaming: bool = True
    """Supports streaming audio output."""

    voices: list[str] = field(default_factory=list)
    """Available voice IDs."""

    languages: list[str] = field(default_factory=lambda: ["en"])
    """Supported language codes."""

    ssml: bool = False
    """Supports SSML input."""

    speed_control: bool = True
    """Supports speech speed adjustment."""

    pitch_control: bool = False
    """Supports pitch adjustment."""

    sample_rates: list[int] = field(default_factory=lambda: [24000])
    """Supported sample rates in Hz."""

    formats: list[str] = field(default_factory=lambda: ["pcm16"])
    """Supported audio formats."""


@dataclass
class VADCapabilities:
    """Capabilities of a VAD provider."""

    frame_size_ms: int = 30
    """Optimal frame size in milliseconds."""

    sample_rates: list[int] = field(default_factory=lambda: [16000])
    """Supported sample rates in Hz."""

    confidence_scores: bool = True
    """Provides confidence scores."""

    speech_timestamps: bool = False
    """Provides speech start/end timestamps."""


# Union type for all capabilities
Capabilities = ASRCapabilities | LLMCapabilities | TTSCapabilities | VADCapabilities


@dataclass
class ProviderInfo:
    """Information about a registered provider."""

    name: str
    """Unique name for the provider (e.g., 'whisper', 'openai')."""

    provider_type: ProviderType
    """Type of provider (ASR, LLM, TTS, VAD)."""

    provider_class: type
    """The provider class to instantiate."""

    capabilities: Capabilities
    """Capabilities of this provider."""

    description: str = ""
    """Human-readable description."""

    version: str = "1.0.0"
    """Provider version."""

    author: str = ""
    """Provider author/maintainer."""

    config_schema: Optional[dict[str, Any]] = None
    """JSON schema for provider configuration."""

    default_config: dict[str, Any] = field(default_factory=dict)
    """Default configuration values."""

    tags: list[str] = field(default_factory=list)
    """Tags for categorization (e.g., ['local', 'fast'])."""

    def __repr__(self) -> str:
        return (
            f"ProviderInfo(name='{self.name}', "
            f"type={self.provider_type.value}, "
            f"class={self.provider_class.__name__})"
        )


@dataclass
class ProviderInstance:
    """A configured instance of a provider."""

    info: ProviderInfo
    """Provider information."""

    instance: Any
    """The actual provider instance."""

    config: dict[str, Any] = field(default_factory=dict)
    """Configuration used to create this instance."""

    def __repr__(self) -> str:
        return f"ProviderInstance({self.info.name}, config={self.config})"
