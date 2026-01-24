"""Provider interfaces for the voice pipeline.

All interfaces inherit from VoiceRunnable, enabling composition with
the | operator:

    >>> chain = asr | llm | tts
    >>> result = await chain.ainvoke(audio_bytes)

    >>> # Streaming
    >>> async for chunk in chain.astream(audio_bytes):
    ...     play(chunk)
"""

from .asr import ASRInput, ASRInterface, TranscriptionResult
from .llm import LLMChunk, LLMInput, LLMInterface, LLMResponse
from .tts import AudioChunk, TTSInput, TTSInterface
from .vad import SpeechState, VADEvent, VADInput, VADInterface

__all__ = [
    # ASR
    "ASRInterface",
    "ASRInput",
    "TranscriptionResult",
    # LLM
    "LLMInterface",
    "LLMInput",
    "LLMChunk",
    "LLMResponse",
    # TTS
    "TTSInterface",
    "TTSInput",
    "AudioChunk",
    # VAD
    "VADInterface",
    "VADInput",
    "VADEvent",
    "SpeechState",
]
