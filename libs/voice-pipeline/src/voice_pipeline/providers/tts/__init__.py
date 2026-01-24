"""TTS (Text-to-Speech) providers.

Available providers:
- OpenAITTSProvider: OpenAI TTS (alloy, echo, fable, onyx, nova, shimmer)
"""

from voice_pipeline.providers.tts.openai import (
    OpenAITTSProvider,
    OpenAITTSConfig,
)

__all__ = [
    "OpenAITTSProvider",
    "OpenAITTSConfig",
]
