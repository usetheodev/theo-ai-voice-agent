"""ASR (Automatic Speech Recognition) providers.

Available providers:
- OpenAIASRProvider: OpenAI Whisper (whisper-1)
- WhisperCppASRProvider: Local whisper.cpp (tiny, base, small, medium, large, turbo)
- DeepgramASRProvider: Real-time streaming ASR via WebSocket (nova-2)
"""

from voice_pipeline.providers.asr.openai import (
    OpenAIASRProvider,
    OpenAIASRConfig,
)
from voice_pipeline.providers.asr.whispercpp import (
    WhisperCppASRProvider,
    WhisperCppASRConfig,
)
from voice_pipeline.providers.asr.deepgram import (
    DeepgramASRProvider,
    DeepgramASRConfig,
    DeepgramASR,  # Alias
)

__all__ = [
    # OpenAI Whisper
    "OpenAIASRProvider",
    "OpenAIASRConfig",
    # whisper.cpp (local)
    "WhisperCppASRProvider",
    "WhisperCppASRConfig",
    # Deepgram (streaming)
    "DeepgramASRProvider",
    "DeepgramASRConfig",
    "DeepgramASR",
]
