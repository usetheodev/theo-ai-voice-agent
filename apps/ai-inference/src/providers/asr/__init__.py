"""ASR (Speech-to-Text) providers."""

from .openai_whisper import OpenAIWhisperASR
from .deepgram import DeepgramASR

__all__ = ["OpenAIWhisperASR", "DeepgramASR"]
