"""
EchoGuard — Adaptive Post-Playback Cooldown

Replaces the fixed 500ms post-playback cooldown with an adaptive one
based on echo detection history.

Heuristic: if barge-in happens <200ms after playback ends AND speech
duration is <150ms, it's likely echo from the speaker, not the user.

The cooldown adapts:
- Many false positives (echo) → increase cooldown
- Few false positives → decrease cooldown
- Bounded: min 100ms, max 1000ms
"""

import logging
import time
import threading
from collections import deque
from typing import Optional

logger = logging.getLogger("media-server.echo-guard")

# Defaults
ECHO_GUARD_ENABLED = True
ECHO_GUARD_MIN_COOLDOWN_MS = 100
ECHO_GUARD_MAX_COOLDOWN_MS = 1000
ECHO_GUARD_INITIAL_COOLDOWN_MS = 500

# Heuristic thresholds
ECHO_TIME_THRESHOLD_MS = 200    # Speech start within this time after playback = suspect
ECHO_DURATION_THRESHOLD_MS = 150  # Speech shorter than this = likely echo


class EchoGuard:
    """
    Adaptive cooldown manager for post-playback echo suppression.

    Instead of a fixed cooldown, adapts based on observed false positive
    patterns. Thread-safe for use from PJSIP callback threads.
    """

    def __init__(
        self,
        enabled: bool = ECHO_GUARD_ENABLED,
        min_cooldown_ms: int = ECHO_GUARD_MIN_COOLDOWN_MS,
        max_cooldown_ms: int = ECHO_GUARD_MAX_COOLDOWN_MS,
        initial_cooldown_ms: int = ECHO_GUARD_INITIAL_COOLDOWN_MS,
        history_size: int = 10,
    ):
        self._enabled = enabled
        self._min_cooldown_ms = min_cooldown_ms
        self._max_cooldown_ms = max_cooldown_ms
        self._cooldown_ms = initial_cooldown_ms
        self._lock = threading.Lock()

        # Timestamp of last playback end
        self._playback_end_time: float = 0.0

        # History of echo detections (True = likely echo, False = real speech)
        self._echo_history: deque = deque(maxlen=history_size)

        # Counters for metrics
        self.echo_detected_count: int = 0
        self.real_speech_count: int = 0

    def mark_playback_end(self):
        """Mark the end of a playback (TTS response finished)."""
        with self._lock:
            self._playback_end_time = time.monotonic()

    def evaluate_speech_event(
        self, duration_ms: float, energy: float = 0
    ) -> bool:
        """Evaluate whether a speech event is echo or real speech.

        Args:
            duration_ms: Duration of the detected speech in ms
            energy: RMS energy of the speech (unused for now)

        Returns:
            True if the speech is likely echo (should be ignored),
            False if it's likely real user speech.
        """
        if not self._enabled:
            return False

        with self._lock:
            if self._playback_end_time == 0:
                return False

            elapsed_ms = (time.monotonic() - self._playback_end_time) * 1000

            # Heuristic: speech started shortly after playback AND is very short
            is_echo = (
                elapsed_ms < ECHO_TIME_THRESHOLD_MS
                and duration_ms < ECHO_DURATION_THRESHOLD_MS
            )

            self._echo_history.append(is_echo)

            if is_echo:
                self.echo_detected_count += 1
                logger.debug(
                    f"EchoGuard: likely echo "
                    f"(elapsed={elapsed_ms:.0f}ms, duration={duration_ms:.0f}ms)"
                )
            else:
                self.real_speech_count += 1

            # Adapt cooldown based on recent history
            self._adapt_cooldown()

            return is_echo

    def _adapt_cooldown(self):
        """Adapt cooldown based on echo detection history."""
        if len(self._echo_history) < 3:
            return

        echo_ratio = sum(self._echo_history) / len(self._echo_history)

        # Many echoes → increase cooldown
        if echo_ratio > 0.5:
            self._cooldown_ms = min(
                self._cooldown_ms + 50,
                self._max_cooldown_ms,
            )
        # Few echoes → decrease cooldown
        elif echo_ratio < 0.2:
            self._cooldown_ms = max(
                self._cooldown_ms - 25,
                self._min_cooldown_ms,
            )

        logger.debug(
            f"EchoGuard: cooldown={self._cooldown_ms}ms "
            f"(echo_ratio={echo_ratio:.1%})"
        )

    def get_cooldown_seconds(self) -> float:
        """Get current adaptive cooldown in seconds."""
        if not self._enabled:
            return 0.5  # Fallback to fixed 500ms

        with self._lock:
            return self._cooldown_ms / 1000.0

    @property
    def cooldown_ms(self) -> int:
        """Current cooldown in milliseconds."""
        return self._cooldown_ms
