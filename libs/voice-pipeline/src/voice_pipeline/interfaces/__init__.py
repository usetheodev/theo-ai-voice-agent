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
from .realtime import (
    RealtimeEvent,
    RealtimeEventType,
    RealtimeInput,
    RealtimeInterface,
    RealtimeSessionConfig,
)
from .transport import (
    AudioConfig,
    AudioFrame,
    AudioTransportInterface,
    TransportConfig,
    TransportInput,
    TransportState,
)
from .rag import (
    Document,
    RetrievalResult,
    EmbeddingInterface,
    VectorStoreInterface,
    RAGInterface,
    SimpleRAG,
)
from .turn_taking import (
    TurnTakingContext,
    TurnTakingController,
    TurnTakingDecision,
)
from .interruption import (
    InterruptionContext,
    InterruptionDecision,
    InterruptionStrategy,
)

from typing import Protocol, runtime_checkable


@runtime_checkable
class Warmable(Protocol):
    """Protocol for providers that support warmup.

    Providers implementing this protocol can pre-load models
    or run initial inference to eliminate cold-start latency.

    Example:
        >>> if isinstance(provider, Warmable):
        ...     warmup_ms = await provider.warmup()
        ...     print(f"Warmed up in {warmup_ms:.1f}ms")
    """

    async def warmup(self) -> float:
        """Warm up the provider.

        Returns:
            Warmup time in milliseconds.
        """
        ...


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
    # Realtime
    "RealtimeInterface",
    "RealtimeInput",
    "RealtimeEvent",
    "RealtimeEventType",
    "RealtimeSessionConfig",
    # Transport
    "AudioTransportInterface",
    "TransportInput",
    "TransportConfig",
    "TransportState",
    "AudioConfig",
    "AudioFrame",
    # RAG
    "Document",
    "RetrievalResult",
    "EmbeddingInterface",
    "VectorStoreInterface",
    "RAGInterface",
    "SimpleRAG",
    # Turn-Taking
    "TurnTakingController",
    "TurnTakingContext",
    "TurnTakingDecision",
    # Interruption
    "InterruptionStrategy",
    "InterruptionContext",
    "InterruptionDecision",
    # Warmable
    "Warmable",
]
