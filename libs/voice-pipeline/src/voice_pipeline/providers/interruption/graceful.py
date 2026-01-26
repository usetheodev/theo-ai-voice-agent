"""Graceful interruption strategy.

Instead of cutting TTS audio abruptly, allows the current chunk
to finish playing before stopping. This produces smoother audio
transitions at the cost of slightly higher latency.

The strategy considers how far the current TTS chunk has progressed:
- If near the end (>= finish_threshold), let it finish
- If near the start, interrupt immediately anyway

Best for:
- Applications where audio quality matters
- TTS engines that produce artifacts on abrupt stop
- Natural-sounding conversations

TTFA impact: +50-200ms compared to immediate interruption.
"""

import logging

from voice_pipeline.interfaces.interruption import (
    InterruptionContext,
    InterruptionDecision,
    InterruptionStrategy,
)

logger = logging.getLogger(__name__)


class GracefulInterruption(InterruptionStrategy):
    """Gracefully interrupt by finishing the current TTS chunk.

    Uses a two-phase approach:
    1. If user speech is short, wait (may be backchannel/noise)
    2. If sustained, decide between graceful and immediate based
       on current chunk progress

    Args:
        min_speech_ms: Minimum user speech to trigger any interruption.
            Default: 300ms (slightly higher than immediate for stability).
        min_confidence: Minimum VAD confidence. Default: 0.5.
        finish_threshold: Chunk progress threshold (0.0-1.0) above which
            to finish the current chunk gracefully. Below this, interrupt
            immediately. Default: 0.3 (finish if >30% done).
        max_wait_ms: Maximum time to wait for chunk to finish after
            deciding to interrupt gracefully. If chunk takes longer,
            force immediate interruption. Default: 500ms.
        debounce_ms: Minimum time between interruptions. Default: 500ms.

    Example:
        >>> strategy = GracefulInterruption(finish_threshold=0.5)
        >>> # If chunk is 60% done → finish it
        >>> # If chunk is 20% done → interrupt immediately
    """

    def __init__(
        self,
        min_speech_ms: float = 300.0,
        min_confidence: float = 0.5,
        finish_threshold: float = 0.3,
        max_wait_ms: float = 500.0,
        debounce_ms: float = 500.0,
    ):
        self.min_speech_ms = min_speech_ms
        self.min_confidence = min_confidence
        self.finish_threshold = finish_threshold
        self.max_wait_ms = max_wait_ms
        self.debounce_ms = debounce_ms

    async def decide(
        self, context: InterruptionContext
    ) -> InterruptionDecision:
        """Decide between graceful and immediate interruption."""
        # Must have user speech while agent is speaking
        if not context.user_is_speaking or not context.agent_is_speaking:
            return InterruptionDecision.IGNORE

        # Check confidence
        if context.user_speech_confidence < self.min_confidence:
            return InterruptionDecision.IGNORE

        # Check speech duration
        if context.user_speech_duration_ms < self.min_speech_ms:
            return InterruptionDecision.IGNORE

        # Debounce
        if context.time_since_last_interruption_ms > 0:
            if context.time_since_last_interruption_ms < self.debounce_ms:
                return InterruptionDecision.IGNORE

        # Decide graceful vs immediate based on chunk progress
        if context.current_chunk_progress >= self.finish_threshold:
            # Chunk is far enough along, let it finish
            logger.debug(
                f"Graceful interruption: chunk at {context.current_chunk_progress:.0%}, "
                f"letting it finish"
            )
            return InterruptionDecision.INTERRUPT_GRACEFUL
        else:
            # Chunk just started, interrupt immediately
            logger.debug(
                f"Immediate interruption (chunk at {context.current_chunk_progress:.0%}, "
                f"below threshold {self.finish_threshold:.0%})"
            )
            return InterruptionDecision.INTERRUPT_IMMEDIATE
