"""Provider system for Voice Agents.

Cloud-first architecture: all providers are HTTP/WebSocket clients.
For local execution, run compatible API servers (Ollama, faster-whisper-server, etc.).
"""

from .base import (
    ASRProvider,
    LLMProvider,
    TTSProvider,
    VADProvider,
    TranscriptionResult,
    LLMResponse,
    AudioChunk,
    VADResult,
)
from .manager import ProviderManager, get_provider_manager
from .exceptions import (
    ProviderError,
    ProviderConnectionError,
    ProviderTimeoutError,
    ProviderAuthError,
)

__all__ = [
    # Base classes
    "ASRProvider",
    "LLMProvider",
    "TTSProvider",
    "VADProvider",
    # Data types
    "TranscriptionResult",
    "LLMResponse",
    "AudioChunk",
    "VADResult",
    # Manager
    "ProviderManager",
    "get_provider_manager",
    # Exceptions
    "ProviderError",
    "ProviderConnectionError",
    "ProviderTimeoutError",
    "ProviderAuthError",
]
