"""Turn-Taking Controller interface.

Pluggable strategies for deciding when a user's turn has ended
and the agent should respond.

The turn-taking problem has multiple dimensions (Full-Duplex-Bench):
1. Pause Handling: Distinguishing thinking pauses from end-of-turn
2. Backchanneling: When to emit feedback ("uhum", "entendo")
3. Smooth Turn Taking: Minimizing response latency
4. User Interruption: Handling barge-in correctly

References:
- FireRedChat (Xiaohongshu): EoT with BERT 170M, 96% accuracy
- Full-Duplex-Bench: 4-dimension evaluation framework
- ChipChat (Apple): KV cache rollback for precise interruptions
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TurnTakingDecision(Enum):
    """Decision from the turn-taking controller.

    Each decision maps to a specific action in the conversation flow.
    """

    CONTINUE_LISTENING = "continue"
    """User is still speaking or pausing to think. Keep collecting audio."""

    END_OF_TURN = "end_of_turn"
    """User has finished speaking. Start processing and responding."""

    BACKCHANNEL = "backchannel"
    """Emit a brief acknowledgment ("uhum", "certo") without taking the turn."""

    BARGE_IN = "barge_in"
    """User is interrupting the agent's response. Stop speaking."""


@dataclass
class TurnTakingContext:
    """Context provided to the turn-taking controller for decision-making.

    Contains all available signals about the current conversation state.
    Controllers can use whichever signals are relevant to their strategy.
    """

    # Audio-level signals
    is_speech: bool = False
    """Whether the current audio chunk contains speech (from VAD)."""

    speech_confidence: float = 0.0
    """VAD confidence that the audio contains speech (0.0-1.0)."""

    silence_duration_ms: float = 0.0
    """Duration of current silence period in milliseconds."""

    speech_duration_ms: float = 0.0
    """Duration of current speech segment in milliseconds."""

    # Text-level signals (from streaming ASR)
    partial_transcript: Optional[str] = None
    """Partial transcription from streaming ASR (if available)."""

    transcript_word_count: int = 0
    """Number of words in the current partial transcript."""

    # Conversation-level signals
    agent_is_speaking: bool = False
    """Whether the agent is currently producing audio output."""

    conversation_turn_count: int = 0
    """Number of completed turns in the conversation so far."""

    last_agent_response_length: int = 0
    """Character length of the agent's last response (context for
    expected user response complexity)."""

    # Metadata
    sample_rate: int = 16000
    """Audio sample rate in Hz."""


class TurnTakingController(ABC):
    """Abstract interface for turn-taking strategies.

    Implementations decide when a user's speaking turn has ended
    based on various signals (silence duration, transcript analysis,
    semantic completeness, etc.).

    The controller is called for each audio chunk during listening.
    It should maintain internal state as needed and reset between turns.

    Example implementation:
        class MyTurnTaking(TurnTakingController):
            async def decide(self, context):
                if context.silence_duration_ms > 500:
                    return TurnTakingDecision.END_OF_TURN
                return TurnTakingDecision.CONTINUE_LISTENING

    Example usage with builder:
        agent = (
            VoiceAgent.builder()
            .asr("faster-whisper")
            .llm("ollama")
            .tts("kokoro")
            .turn_taking("fixed", silence_threshold_ms=600)
            .build()
        )
    """

    @abstractmethod
    async def decide(self, context: TurnTakingContext) -> TurnTakingDecision:
        """Make a turn-taking decision based on the current context.

        Called for each processed audio chunk while the user is
        potentially speaking. Should be fast (< 5ms for non-semantic
        strategies) to avoid adding latency to the pipeline.

        Args:
            context: Current conversation context with all available signals.

        Returns:
            Decision about what to do next.
        """
        ...

    def reset(self) -> None:
        """Reset controller state for a new turn.

        Called after a turn ends (END_OF_TURN or BARGE_IN) to prepare
        for the next user turn. Override if your implementation
        maintains state between chunks.
        """
        pass

    async def connect(self) -> None:
        """Initialize resources (e.g., load models).

        Called once during pipeline setup. Override for strategies
        that require loading ML models or other resources.
        """
        pass

    async def disconnect(self) -> None:
        """Release resources.

        Called during pipeline teardown. Override to clean up
        models, connections, etc.
        """
        pass

    @property
    def name(self) -> str:
        """Human-readable name for this strategy."""
        return self.__class__.__name__

    @property
    def requires_transcript(self) -> bool:
        """Whether this controller needs partial transcripts.

        If True, the pipeline should feed partial ASR results
        into the TurnTakingContext. This enables streaming ASR
        integration for semantic turn-taking.

        Default: False (audio-only strategies).
        """
        return False
