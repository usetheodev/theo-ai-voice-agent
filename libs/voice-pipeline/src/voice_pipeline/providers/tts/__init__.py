"""TTS (Text-to-Speech) providers.

Available providers:
- OpenAITTSProvider: OpenAI TTS (alloy, echo, fable, onyx, nova, shimmer)
- KokoroTTSProvider: Kokoro local TTS (af_bella, am_adam, etc.)
- Qwen3TTSProvider: Qwen3-TTS with ultra-low latency and native Portuguese
- PiperTTSProvider: Piper ultra-fast CPU TTS (pt_BR, en_US, etc.)
"""

from voice_pipeline.providers.tts.openai import (
    OpenAITTSProvider,
    OpenAITTSConfig,
)
from voice_pipeline.providers.tts.kokoro import (
    KokoroTTSProvider,
    KokoroTTSConfig,
)
from voice_pipeline.providers.tts.qwen3 import (
    Qwen3TTSProvider,
    Qwen3TTSConfig,
)
from voice_pipeline.providers.tts.piper import (
    PiperTTSProvider,
    PiperTTSConfig,
)

__all__ = [
    "OpenAITTSProvider",
    "OpenAITTSConfig",
    "KokoroTTSProvider",
    "KokoroTTSConfig",
    "Qwen3TTSProvider",
    "Qwen3TTSConfig",
    "PiperTTSProvider",
    "PiperTTSConfig",
]
