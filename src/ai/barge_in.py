"""
Barge-In Handler for Full-Duplex Voice-to-Voice

Manages user interruptions during AI speech (barge-in).

Key Features:
- Immediate cancellation of pending TTS generation
- Stop RTP transmission of queued audio
- Flush ASR pipeline for new input
- Grace period to prevent false interruptions
- Metrics tracking

Architecture:
    User speaks → VAD detects → Barge-in Handler →
    [Cancel TTS] → [Stop RTP] → [Flush ASR] → [Process user input]

Important:
- Cannot cancel audio already sent over network (accept 100-300ms "leakage")
- Must track AI speaking state accurately
- Grace period prevents cutting on natural pauses

Author: AI Voice Agent Team
Date: 2026-01-23
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class BargeInEvent:
    """Barge-in event metadata."""
    timestamp: float
    user_speech_confidence: float
    ai_audio_cancelled_ms: float  # Amount of AI audio cancelled
    grace_period_ms: float
    event_id: int


class BargeInHandler:
    """
    Handles user interruptions (barge-in) during AI speech.

    Responsibilities:
    1. Detect when user starts speaking while AI is speaking
    2. Cancel pending TTS generation (future audio only)
    3. Stop RTP transmission queue
    4. Flush ASR pipeline
    5. Track metrics

    Example:
        >>> handler = BargeInHandler(
        >>>     on_barge_in=handle_interrupt,
        >>>     grace_period_ms=200
        >>> )
        >>> handler.set_ai_speaking(True)  # AI starts
        >>> await handler.handle_user_speech(confidence=0.95)  # User interrupts
        >>> # → on_barge_in callback is called
    """

    def __init__(
        self,
        on_barge_in: Optional[Callable[[BargeInEvent], Awaitable[None]]] = None,
        grace_period_ms: int = 200,
        min_interruption_confidence: float = 0.7,
        enable_metrics: bool = True,
    ):
        """
        Initialize Barge-In Handler.

        Args:
            on_barge_in: Async callback when barge-in is detected
            grace_period_ms: Grace period before triggering (prevents false positives)
            min_interruption_confidence: Minimum VAD confidence to trigger
            enable_metrics: Enable metrics collection
        """
        self.on_barge_in = on_barge_in
        self.grace_period_ms = grace_period_ms
        self.min_interruption_confidence = min_interruption_confidence
        self.enable_metrics = enable_metrics

        # State
        self.ai_is_speaking = False
        self.ai_speech_start_time = 0.0
        self.last_user_speech_time = 0.0
        self.barge_in_in_progress = False
        self.event_counter = 0

        # Metrics
        self.total_barge_ins = 0
        self.false_alarms = 0  # Barge-ins that didn't result in actual interruption
        self.avg_ai_speak_duration_ms = 0.0
        self.barge_in_events = deque(maxlen=100)  # Last 100 events

        # Locks
        self._lock = asyncio.Lock()

        logger.info("🔴 Barge-In Handler initialized (grace_period=%dms, min_confidence=%.2f)",
                   grace_period_ms, min_interruption_confidence)

    def set_ai_speaking(self, is_speaking: bool, audio_duration_ms: float = 0.0):
        """
        Update AI speaking state.

        Call this when:
        - AI starts generating/playing TTS: set_ai_speaking(True)
        - AI finishes/stops TTS: set_ai_speaking(False, duration_ms)

        Args:
            is_speaking: True if AI is currently speaking
            audio_duration_ms: Duration of AI speech (when stopping)
        """
        current_time = time.time()

        if is_speaking and not self.ai_is_speaking:
            # AI started speaking
            self.ai_is_speaking = True
            self.ai_speech_start_time = current_time
            self.barge_in_in_progress = False
            logger.debug("🟢 AI started speaking")

        elif not is_speaking and self.ai_is_speaking:
            # AI stopped speaking
            self.ai_is_speaking = False

            if audio_duration_ms > 0:
                # Update average AI speak duration
                if self.avg_ai_speak_duration_ms == 0:
                    self.avg_ai_speak_duration_ms = audio_duration_ms
                else:
                    # Exponential moving average
                    self.avg_ai_speak_duration_ms = (
                        0.9 * self.avg_ai_speak_duration_ms + 0.1 * audio_duration_ms
                    )

            logger.debug("🔴 AI stopped speaking (duration=%.0fms)", audio_duration_ms)

    async def handle_user_speech(
        self,
        confidence: float,
        energy_db: float = 0.0
    ) -> Optional[BargeInEvent]:
        """
        Handle user speech detection.

        Call this from VAD when speech is detected.

        Args:
            confidence: VAD confidence (0.0 to 1.0)
            energy_db: Audio energy in dB

        Returns:
            BargeInEvent if interruption triggered, None otherwise
        """
        async with self._lock:
            current_time = time.time()

            # Update last speech time
            self.last_user_speech_time = current_time

            # Check if AI is speaking
            if not self.ai_is_speaking:
                return None  # No interruption possible

            # Check if already handling a barge-in
            if self.barge_in_in_progress:
                return None  # Already processing

            # Check confidence threshold
            if confidence < self.min_interruption_confidence:
                logger.debug("⚠️ User speech confidence too low: %.2f < %.2f",
                           confidence, self.min_interruption_confidence)
                return None

            # Check grace period
            ai_speak_duration_ms = (current_time - self.ai_speech_start_time) * 1000

            if ai_speak_duration_ms < self.grace_period_ms:
                logger.debug("⚠️ Grace period not elapsed: %.0fms < %dms",
                           ai_speak_duration_ms, self.grace_period_ms)
                return None

            # BARGE-IN DETECTED!
            self.barge_in_in_progress = True
            self.total_barge_ins += 1
            self.event_counter += 1

            # Calculate how much AI audio to cancel
            # (Note: Cannot cancel audio already sent, only pending)
            ai_audio_cancelled_ms = ai_speak_duration_ms  # Approximation

            # Create event
            event = BargeInEvent(
                timestamp=current_time,
                user_speech_confidence=confidence,
                ai_audio_cancelled_ms=ai_audio_cancelled_ms,
                grace_period_ms=self.grace_period_ms,
                event_id=self.event_counter
            )

            # Store event
            if self.enable_metrics:
                self.barge_in_events.append(event)

            logger.info(
                "🔴 BARGE-IN #%d detected! "
                "(confidence=%.2f, ai_duration=%.0fms, cancelled=%.0fms)",
                self.event_counter,
                confidence,
                ai_speak_duration_ms,
                ai_audio_cancelled_ms
            )

            # Trigger callback
            if self.on_barge_in:
                try:
                    await self.on_barge_in(event)
                except Exception as e:
                    logger.error("❌ Barge-in callback failed: %s", e, exc_info=True)

            return event

    async def cancel_ai_speech(self):
        """
        Cancel AI speech (called by barge-in callback).

        This should:
        1. Cancel pending TTS generation
        2. Clear RTP transmission queue
        3. Flush ASR pipeline

        Note: Implement actual cancellation in the callback.
        This method is a placeholder for documentation.
        """
        logger.info("🛑 Cancelling AI speech...")
        # Implementation delegated to callback
        # (This handler doesn't have direct access to TTS/RTP/ASR pipelines)

    def reset(self):
        """Reset handler state (e.g., after conversation ends)."""
        self.ai_is_speaking = False
        self.ai_speech_start_time = 0.0
        self.last_user_speech_time = 0.0
        self.barge_in_in_progress = False
        logger.debug("Barge-in handler reset")

    def get_stats(self) -> dict:
        """
        Get barge-in statistics.

        Returns:
            Dictionary with metrics
        """
        # Calculate average cancellation time
        avg_cancellation_ms = 0.0
        if self.barge_in_events:
            avg_cancellation_ms = sum(
                e.ai_audio_cancelled_ms for e in self.barge_in_events
            ) / len(self.barge_in_events)

        # Calculate barge-in rate (interruptions per minute of AI speech)
        total_ai_speak_time_s = self.avg_ai_speak_duration_ms * self.total_barge_ins / 1000.0
        barge_in_rate = (
            (self.total_barge_ins / total_ai_speak_time_s * 60.0)
            if total_ai_speak_time_s > 0 else 0.0
        )

        return {
            "total_barge_ins": self.total_barge_ins,
            "false_alarms": self.false_alarms,
            "avg_ai_speak_duration_ms": self.avg_ai_speak_duration_ms,
            "avg_cancellation_ms": avg_cancellation_ms,
            "barge_in_rate_per_minute": barge_in_rate,
            "recent_events_count": len(self.barge_in_events),
            "is_ai_speaking": self.ai_is_speaking,
            "barge_in_in_progress": self.barge_in_in_progress,
        }


# Example usage and testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    async def test_barge_in():
        """Test barge-in handler."""
        logger.info("🧪 Testing Barge-In Handler...")

        # Define callback
        async def on_interrupt(event: BargeInEvent):
            logger.info(
                "📢 Callback triggered! event_id=%d, confidence=%.2f",
                event.event_id,
                event.user_speech_confidence
            )

        # Initialize handler
        handler = BargeInHandler(
            on_barge_in=on_interrupt,
            grace_period_ms=200,
            min_interruption_confidence=0.7
        )

        # Test 1: No AI speaking - should not trigger
        logger.info("\n--- Test 1: User speaks, AI not speaking ---")
        result = await handler.handle_user_speech(confidence=0.95)
        logger.info("Result: %s (expected: None)", result)

        # Test 2: AI speaking, user interrupts after grace period
        logger.info("\n--- Test 2: AI speaking, user interrupts (valid) ---")
        handler.set_ai_speaking(True)
        await asyncio.sleep(0.3)  # Wait > grace period
        result = await handler.handle_user_speech(confidence=0.95)
        logger.info("Result: %s (expected: BargeInEvent)", result)

        # Test 3: Low confidence - should not trigger
        logger.info("\n--- Test 3: Low confidence ---")
        handler.set_ai_speaking(True)
        await asyncio.sleep(0.3)
        result = await handler.handle_user_speech(confidence=0.5)
        logger.info("Result: %s (expected: None)", result)

        # Test 4: Within grace period - should not trigger
        logger.info("\n--- Test 4: Within grace period ---")
        handler.set_ai_speaking(True)
        await asyncio.sleep(0.1)  # Wait < grace period
        result = await handler.handle_user_speech(confidence=0.95)
        logger.info("Result: %s (expected: None)", result)

        # Print stats
        logger.info("\n--- Barge-In Statistics ---")
        stats = handler.get_stats()
        for key, value in stats.items():
            logger.info("%s: %s", key, value)

    # Run test
    asyncio.run(test_barge_in())
