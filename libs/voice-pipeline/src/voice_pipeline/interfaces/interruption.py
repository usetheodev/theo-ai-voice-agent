"""Interruption strategy interface for pluggable barge-in handling.

Defines how the system responds when the user speaks while the
agent is still speaking (barge-in / interruption event).

Different strategies trade off responsiveness vs. speech quality:

- Immediate: Stop TTS instantly (lowest latency, abrupt cutoff)
- Graceful: Finish current chunk/sentence then stop (smoother)
- BackchannelAware: Distinguish "uhum/ok" from real interruptions

References:
- Full-Duplex-Bench: Evaluation of full-duplex voice agents
- FireRedChat: Backchannel vs. interruption classification
- ChipChat (Apple): SpeakStream with overlap handling
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class InterruptionDecision(Enum):
    """Decision on how to handle a detected interruption.

    Returned by InterruptionStrategy.decide() to control the
    pipeline's response to user speech during agent output.
    """

    IGNORE = "ignore"
    """Ignore the speech — do not interrupt.
    Used for very short sounds, noise, or when interruption is disabled."""

    INTERRUPT_IMMEDIATE = "interrupt_immediate"
    """Stop TTS output immediately.
    Fastest response, but may cut audio mid-word/sentence."""

    INTERRUPT_GRACEFUL = "interrupt_graceful"
    """Finish the current TTS chunk, then stop.
    Slightly higher latency, but smoother audio transition."""

    BACKCHANNEL = "backchannel"
    """User is giving backchannel feedback (e.g., "uhum", "ok").
    Agent should continue speaking without interruption.
    Optionally acknowledge the backchannel."""


@dataclass
class InterruptionContext:
    """Context signals for making interruption decisions.

    Provides the InterruptionStrategy with all available information
    about the current state of the conversation when an interruption
    is detected.
    """

    # Speech detection signals
    user_is_speaking: bool = False
    """Whether the VAD currently detects user speech."""

    user_speech_duration_ms: float = 0.0
    """How long the user has been speaking (current utterance)."""

    user_speech_confidence: float = 0.0
    """VAD confidence that user speech is present (0.0-1.0)."""

    # Agent output state
    agent_is_speaking: bool = False
    """Whether the agent is currently outputting audio."""

    agent_speech_duration_ms: float = 0.0
    """How long the agent has been speaking in the current turn."""

    agent_chunks_remaining: int = 0
    """Number of TTS chunks still queued for output."""

    current_chunk_progress: float = 0.0
    """Progress through the current TTS chunk (0.0-1.0).
    0.0 = just started, 1.0 = about to finish."""

    # Transcript signals (if available from streaming ASR)
    partial_transcript: Optional[str] = None
    """Partial transcript of the user's interrupting speech."""

    # Conversation context
    agent_response_text: str = ""
    """Text of the agent's current response (generated so far)."""

    conversation_turn_count: int = 0
    """Number of completed conversation turns."""

    # Timing
    time_since_agent_start_ms: float = 0.0
    """Milliseconds since the agent started speaking."""

    time_since_last_interruption_ms: float = 0.0
    """Milliseconds since the last interruption event.
    Useful for debouncing rapid interruptions."""


class InterruptionStrategy(ABC):
    """Abstract interface for interruption handling strategies.

    Implementations decide how the pipeline should respond when
    the user speaks while the agent is outputting audio.

    The interface has one main method:
    - decide(context): Analyze signals and return an InterruptionDecision

    And optional lifecycle methods:
    - reset(): Reset internal state for a new conversation
    - on_interruption_executed(): Called after an interruption is actually performed

    Example implementation:
        class MyStrategy(InterruptionStrategy):
            async def decide(self, context: InterruptionContext) -> InterruptionDecision:
                if context.user_speech_duration_ms < 200:
                    return InterruptionDecision.IGNORE
                return InterruptionDecision.INTERRUPT_IMMEDIATE

    Example usage with builder:
        agent = (
            VoiceAgent.builder()
            .asr("faster-whisper")
            .llm("ollama")
            .tts("kokoro")
            .streaming(True)
            .interruption("backchannel")
            .build()
        )
    """

    @abstractmethod
    async def decide(
        self, context: InterruptionContext
    ) -> InterruptionDecision:
        """Decide how to handle a potential interruption.

        Called when the VAD detects user speech while the agent
        is speaking. Should analyze the context and return an
        appropriate decision.

        This method may be called frequently (every VAD frame),
        so implementations should be efficient.

        Args:
            context: All available signals about the current state.

        Returns:
            InterruptionDecision indicating how to handle the event.
        """
        ...

    def reset(self) -> None:
        """Reset internal state for a new conversation.

        Called at the start of a new conversation or after
        a long pause. Override if your implementation maintains
        state across decisions.
        """
        pass

    def on_interruption_executed(self, decision: InterruptionDecision) -> None:
        """Callback after an interruption is actually performed.

        Called by the pipeline after it acts on a non-IGNORE decision.
        Useful for updating internal state (e.g., counting interruptions,
        adjusting thresholds).

        Args:
            decision: The decision that was executed.
        """
        pass

    @property
    def name(self) -> str:
        """Human-readable name for this strategy."""
        return self.__class__.__name__
