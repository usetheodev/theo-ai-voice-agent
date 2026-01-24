"""ASR (Automatic Speech Recognition) providers.

Available providers:
- OpenAIASRProvider: OpenAI Whisper (whisper-1)
- WhisperCppASRProvider: Local whisper.cpp (tiny, base, small, medium, large, turbo)
"""

from voice_pipeline.providers.asr.openai import (
    OpenAIASRProvider,
    OpenAIASRConfig,
)
from voice_pipeline.providers.asr.whispercpp import (
    WhisperCppASRProvider,
    WhisperCppASRConfig,
)

__all__ = [
    "OpenAIASRProvider",
    "OpenAIASRConfig",
    "WhisperCppASRProvider",
    "WhisperCppASRConfig",
]
