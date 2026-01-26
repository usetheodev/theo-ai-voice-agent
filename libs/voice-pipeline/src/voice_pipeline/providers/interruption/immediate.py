"""Immediate interruption strategy.

Stops TTS output as soon as user speech is detected with
sufficient duration and confidence. This is the simplest and
lowest-latency strategy, matching the current default behavior.

Best for:
- Applications where responsiveness is paramount
- Systems with good VAD (low false positive rate)
- Turn-based conversation with clear interruptions

Not ideal for:
- Noisy environments (may trigger on noise)
- Conversations with frequent backchannels
- Full-duplex scenarios
"""

import logging

from voice_pipeline.interfaces.interruption import (
    InterruptionContext,
    InterruptionDecision,
    InterruptionStrategy,
)

logger = logging.getLogger(__name__)


class ImmediateInterruption(InterruptionStrategy):
    """Immediately interrupt on user speech detection.

    The simplest strategy: if the user has been speaking for
    at least `min_speech_ms` with sufficient confidence,
    interrupt the agent immediately.

    A debounce mechanism prevents rapid repeated interruptions.

    Args:
        min_speech_ms: Minimum user speech duration before
            triggering interruption. Default: 200ms.
        min_confidence: Minimum VAD confidence to consider
            the speech as real. Default: 0.5.
        debounce_ms: Minimum time between interruptions.
            Prevents rapid fire interruptions. Default: 500ms.

    Example:
        >>> strategy = ImmediateInterruption(min_speech_ms=150)
        >>> decision = await strategy.decide(context)
        >>> # → InterruptionDecision.INTERRUPT_IMMEDIATE
    """

    def __init__(
        self,
        min_speech_ms: float = 200.0,
        min_confidence: float = 0.5,
        debounce_ms: float = 500.0,
    ):
        self.min_speech_ms = min_speech_ms
        self.min_confidence = min_confidence
        self.debounce_ms = debounce_ms

    async def decide(
        self, context: InterruptionContext
    ) -> InterruptionDecision:
        """Decide whether to immediately interrupt."""
        # Must have user speech while agent is speaking
        if not context.user_is_speaking or not context.agent_is_speaking:
            return InterruptionDecision.IGNORE

        # Check confidence
        if context.user_speech_confidence < self.min_confidence:
            return InterruptionDecision.IGNORE

        # Check speech duration
        if context.user_speech_duration_ms < self.min_speech_ms:
            return InterruptionDecision.IGNORE

        # Debounce: prevent rapid interruptions
        if context.time_since_last_interruption_ms > 0:
            if context.time_since_last_interruption_ms < self.debounce_ms:
                return InterruptionDecision.IGNORE

        logger.debug(
            f"Immediate interruption: speech={context.user_speech_duration_ms:.0f}ms, "
            f"confidence={context.user_speech_confidence:.2f}"
        )
        return InterruptionDecision.INTERRUPT_IMMEDIATE
