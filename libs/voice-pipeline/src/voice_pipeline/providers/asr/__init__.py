"""ASR (Automatic Speech Recognition) providers.

Available providers:
- OpenAIASRProvider: OpenAI Whisper (whisper-1)
"""

from voice_pipeline.providers.asr.openai import (
    OpenAIASRProvider,
    OpenAIASRConfig,
)

__all__ = [
    "OpenAIASRProvider",
    "OpenAIASRConfig",
]
