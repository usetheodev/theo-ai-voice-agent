"""Adaptive silence threshold turn-taking strategy.

Adjusts the silence threshold dynamically based on conversation context:
- Short utterances (1-3 words) → shorter threshold (user likely done)
- Long utterances → longer threshold (user may be thinking)
- Questions from agent → longer threshold (user needs time to think)
- Early in conversation → longer threshold (user warming up)

This provides a good balance between responsiveness and accuracy
without requiring any ML models.

Inspired by observations from Full-Duplex-Bench that fixed thresholds
perform poorly on pause handling.
"""

import logging
from typing import Optional

from voice_pipeline.interfaces.turn_taking import (
    TurnTakingContext,
    TurnTakingController,
    TurnTakingDecision,
)

logger = logging.getLogger(__name__)


class AdaptiveSilenceTurnTaking(TurnTakingController):
    """Turn-taking with adaptive silence threshold.

    The threshold adjusts based on multiple context signals:

    1. Speech duration: Longer speech → longer threshold (thinking pauses)
    2. Transcript length: Short transcripts → shorter threshold
    3. Agent response complexity: Complex agent response → longer threshold
       (user needs more time to formulate response)

    The effective threshold is:
        threshold = base_threshold_ms * multiplier

    Where multiplier is computed from context signals, clamped to
    [min_threshold_ms, max_threshold_ms].

    Args:
        base_threshold_ms: Base silence threshold. Default: 600ms.
        min_threshold_ms: Minimum threshold (fast responses). Default: 400ms.
        max_threshold_ms: Maximum threshold (patient waiting). Default: 1500ms.
        barge_in_confidence: Minimum VAD confidence for barge-in. Default: 0.6.
        min_speech_ms: Minimum speech duration to consider. Default: 200ms.

    Example:
        >>> controller = AdaptiveSilenceTurnTaking(
        ...     base_threshold_ms=500,
        ...     min_threshold_ms=300,
        ...     max_threshold_ms=1200,
        ... )
    """

    def __init__(
        self,
        base_threshold_ms: int = 600,
        min_threshold_ms: int = 400,
        max_threshold_ms: int = 1500,
        barge_in_confidence: float = 0.6,
        min_speech_ms: float = 200.0,
    ):
        self.base_threshold_ms = base_threshold_ms
        self.min_threshold_ms = min_threshold_ms
        self.max_threshold_ms = max_threshold_ms
        self.barge_in_confidence = barge_in_confidence
        self.min_speech_ms = min_speech_ms

        self._had_speech = False
        self._current_threshold_ms: Optional[float] = None

    def _compute_threshold(self, context: TurnTakingContext) -> float:
        """Compute adaptive threshold based on context.

        Returns:
            Threshold in milliseconds, clamped to [min, max].
        """
        multiplier = 1.0

        # Factor 1: Transcript length
        # Short utterances (1-3 words) are likely complete → reduce threshold
        # Long utterances may have pauses → increase threshold
        if context.transcript_word_count > 0:
            if context.transcript_word_count <= 3:
                multiplier *= 0.7  # Short utterance (1-3 words): likely complete
            elif context.transcript_word_count <= 8:
                multiplier *= 0.9  # Medium utterance: slightly reduce wait
            elif context.transcript_word_count > 15:
                multiplier *= 1.3  # Long speech: may pause to think

        # Factor 2: Speech duration
        # Very short speech segments are likely complete
        if context.speech_duration_ms > 0:
            if context.speech_duration_ms < 1000:
                multiplier *= 0.8  # Quick utterance
            elif context.speech_duration_ms > 5000:
                multiplier *= 1.2  # Extended speech, may pause

        # Factor 3: Agent response complexity
        # If agent asked something complex, give user more time
        if context.last_agent_response_length > 200:
            multiplier *= 1.2  # Agent said a lot, user thinking
        elif context.last_agent_response_length > 0 and context.last_agent_response_length < 50:
            multiplier *= 0.9  # Agent said little, quick exchange

        # Factor 4: Conversation warmup
        # First few turns → be more patient
        if context.conversation_turn_count <= 2:
            multiplier *= 1.1

        # Compute and clamp
        threshold = self.base_threshold_ms * multiplier
        threshold = max(self.min_threshold_ms, min(self.max_threshold_ms, threshold))

        return threshold

    async def decide(self, context: TurnTakingContext) -> TurnTakingDecision:
        """Decide based on adaptive silence threshold.

        Computes context-dependent threshold, then applies same
        logic as FixedSilenceTurnTaking with the dynamic threshold.
        """
        # Barge-in detection
        if context.agent_is_speaking and context.is_speech:
            if context.speech_confidence >= self.barge_in_confidence:
                logger.debug(
                    f"Barge-in detected (confidence={context.speech_confidence:.2f})"
                )
                return TurnTakingDecision.BARGE_IN

        # Track speech activity
        if context.is_speech:
            self._had_speech = True
            self._current_threshold_ms = None  # Recompute on silence
            return TurnTakingDecision.CONTINUE_LISTENING

        # Check for end-of-turn
        if self._had_speech:
            if context.speech_duration_ms < self.min_speech_ms:
                return TurnTakingDecision.CONTINUE_LISTENING

            # Compute threshold once when silence starts
            if self._current_threshold_ms is None:
                self._current_threshold_ms = self._compute_threshold(context)
                logger.debug(
                    f"Adaptive threshold: {self._current_threshold_ms:.0f}ms "
                    f"(words={context.transcript_word_count}, "
                    f"speech={context.speech_duration_ms:.0f}ms)"
                )

            if context.silence_duration_ms >= self._current_threshold_ms:
                logger.debug(
                    f"End-of-turn: {context.silence_duration_ms:.0f}ms silence "
                    f"(adaptive threshold={self._current_threshold_ms:.0f}ms)"
                )
                return TurnTakingDecision.END_OF_TURN

        return TurnTakingDecision.CONTINUE_LISTENING

    def reset(self) -> None:
        """Reset for new turn."""
        self._had_speech = False
        self._current_threshold_ms = None

    @property
    def name(self) -> str:
        return f"AdaptiveSilence(base={self.base_threshold_ms}ms)"
