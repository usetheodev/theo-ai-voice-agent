"""Pipeline configuration."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PipelineConfig:
    """Configuration for the voice pipeline.

    Attributes:
        system_prompt: System prompt for the LLM.
        language: Language code for ASR (e.g., "en", "pt-BR").
        vad_threshold: VAD speech detection threshold (0.0 to 1.0).
        vad_silence_ms: Silence duration to end turn (milliseconds).
        enable_barge_in: Allow user to interrupt assistant.
        barge_in_threshold_ms: Speech duration to trigger barge-in.
        barge_in_backoff_ms: Backoff after barge-in before listening.
        sentence_end_chars: Characters that end a sentence.
        min_tts_chars: Minimum characters before sending to TTS.
        sample_rate: Audio sample rate in Hz.
        tts_voice: Voice identifier for TTS.
        llm_temperature: LLM sampling temperature.
        llm_max_tokens: Maximum tokens for LLM response.
    """

    # Conversation
    system_prompt: str = "You are a helpful voice assistant."
    language: str = "en"

    # VAD settings
    vad_threshold: float = 0.5
    vad_silence_ms: int = 500

    # Barge-in
    enable_barge_in: bool = True
    barge_in_threshold_ms: int = 200
    barge_in_backoff_ms: int = 100

    # TTS streaming
    sentence_end_chars: list[str] = field(
        default_factory=lambda: [".", "!", "?", "\n"]
    )
    min_tts_chars: int = 20

    # Audio
    sample_rate: int = 16000

    # TTS
    tts_voice: Optional[str] = None

    # LLM
    llm_temperature: float = 0.7
    llm_max_tokens: Optional[int] = None

    # Buffer sizes
    buffer_maxsize: int = 50
    """Maximum size for input/output audio buffers (~5s of audio at 16kHz)."""

    tts_queue_maxsize: int = 10
    """Maximum size for TTS sentence queue."""
