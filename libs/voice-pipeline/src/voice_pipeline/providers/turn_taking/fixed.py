"""Fixed silence threshold turn-taking strategy.

The simplest turn-taking approach: waits for a fixed duration
of silence after speech before declaring end-of-turn.

This reproduces the behavior of the original framework (800ms threshold)
and serves as the default strategy for backwards compatibility.

Pros:
- Zero overhead, no models needed
- Predictable behavior
- Works on any hardware

Cons:
- Cannot distinguish thinking pauses from end-of-turn
- Fixed latency regardless of context
- High false positive rate for pause handling
"""

import logging
from typing import Optional

from voice_pipeline.interfaces.turn_taking import (
    TurnTakingContext,
    TurnTakingController,
    TurnTakingDecision,
)

logger = logging.getLogger(__name__)


class FixedSilenceTurnTaking(TurnTakingController):
    """Turn-taking based on fixed silence duration.

    Declares end-of-turn after detecting silence for at least
    `silence_threshold_ms` milliseconds following speech.

    Also handles barge-in: if the agent is speaking and user
    speech is detected with sufficient confidence, returns BARGE_IN.

    Args:
        silence_threshold_ms: Silence duration to trigger end-of-turn.
            Lower values = faster response, higher false positives.
            Higher values = fewer false positives, more latency.
            Default: 800ms (original framework behavior).
        barge_in_confidence: Minimum VAD confidence to trigger barge-in
            when agent is speaking. Default: 0.6.
        min_speech_ms: Minimum speech duration before considering
            end-of-turn. Prevents very short noises from triggering.
            Default: 200ms.

    Example:
        >>> controller = FixedSilenceTurnTaking(silence_threshold_ms=600)
        >>> decision = await controller.decide(context)
    """

    def __init__(
        self,
        silence_threshold_ms: int = 800,
        barge_in_confidence: float = 0.6,
        min_speech_ms: float = 200.0,
    ):
        self.silence_threshold_ms = silence_threshold_ms
        self.barge_in_confidence = barge_in_confidence
        self.min_speech_ms = min_speech_ms
        self._had_speech = False

    async def decide(self, context: TurnTakingContext) -> TurnTakingDecision:
        """Decide based on fixed silence threshold.

        Logic:
        1. If agent is speaking and user speaks → BARGE_IN
        2. If speech detected → mark speech started, CONTINUE
        3. If silence after speech >= threshold → END_OF_TURN
        4. Otherwise → CONTINUE_LISTENING
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
            return TurnTakingDecision.CONTINUE_LISTENING

        # Check for end-of-turn (silence after speech)
        if self._had_speech:
            if context.speech_duration_ms < self.min_speech_ms:
                return TurnTakingDecision.CONTINUE_LISTENING

            if context.silence_duration_ms >= self.silence_threshold_ms:
                logger.debug(
                    f"End-of-turn: {context.silence_duration_ms:.0f}ms silence "
                    f"(threshold={self.silence_threshold_ms}ms)"
                )
                return TurnTakingDecision.END_OF_TURN

        return TurnTakingDecision.CONTINUE_LISTENING

    def reset(self) -> None:
        """Reset for new turn."""
        self._had_speech = False

    @property
    def name(self) -> str:
        return f"FixedSilence({self.silence_threshold_ms}ms)"
