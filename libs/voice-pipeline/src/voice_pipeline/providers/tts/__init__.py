"""TTS (Text-to-Speech) providers.

Available providers:
- OpenAITTSProvider: OpenAI TTS (alloy, echo, fable, onyx, nova, shimmer)
- KokoroTTSProvider: Kokoro local TTS (af_bella, am_adam, etc.)
"""

from voice_pipeline.providers.tts.openai import (
    OpenAITTSProvider,
    OpenAITTSConfig,
)
from voice_pipeline.providers.tts.kokoro import (
    KokoroTTSProvider,
    KokoroTTSConfig,
)

__all__ = [
    "OpenAITTSProvider",
    "OpenAITTSConfig",
    "KokoroTTSProvider",
    "KokoroTTSConfig",
]
