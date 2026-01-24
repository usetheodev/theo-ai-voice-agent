"""Voice Pipeline - A modular voice conversation pipeline."""

from .core.pipeline import Pipeline
from .core.config import PipelineConfig
from .core.state_machine import ConversationState, ConversationStateMachine
from .core.events import EventEmitter, PipelineEvent, PipelineEventType

from .interfaces.asr import ASRInterface, TranscriptionResult
from .interfaces.llm import LLMInterface, LLMChunk
from .interfaces.tts import TTSInterface, AudioChunk
from .interfaces.vad import VADInterface, VADEvent, SpeechState

from .streaming.sentence_streamer import SentenceStreamer, SentenceStreamerConfig
from .streaming.buffer import AudioBuffer, TextBuffer, AsyncQueue

__version__ = "0.1.0"

__all__ = [
    # Core
    "Pipeline",
    "PipelineConfig",
    "ConversationState",
    "ConversationStateMachine",
    "EventEmitter",
    "PipelineEvent",
    "PipelineEventType",
    # Interfaces
    "ASRInterface",
    "TranscriptionResult",
    "LLMInterface",
    "LLMChunk",
    "TTSInterface",
    "AudioChunk",
    "VADInterface",
    "VADEvent",
    "SpeechState",
    # Streaming
    "SentenceStreamer",
    "SentenceStreamerConfig",
    "AudioBuffer",
    "TextBuffer",
    "AsyncQueue",
]
