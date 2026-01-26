"""Backchannel-aware interruption strategy.

Distinguishes between real interruptions and backchannel feedback
(e.g., "uhum", "ok", "sim", "yeah", "right"). Backchannels are
short acknowledgments that signal the user is listening but does
NOT want to take the conversational floor.

Detection approach (multi-signal):
1. Duration: Backchannels are typically < 500ms
2. Transcript (if available): Match against known backchannel patterns
3. Confidence: Higher confidence = more likely real speech

References:
- FireRedChat: BERT-based backchannel vs. interruption classification
- Full-Duplex-Bench: Metrics for backchannel detection accuracy
- Linguistics: Backchannels in conversational analysis (Yngve, 1970)
"""

import logging
import re
from typing import Optional

from voice_pipeline.interfaces.interruption import (
    InterruptionContext,
    InterruptionDecision,
    InterruptionStrategy,
)

logger = logging.getLogger(__name__)

# Common backchannel expressions by language
_BACKCHANNELS_PT = {
    # Short acknowledgments
    "uhum", "aham", "hum", "hm", "sim", "ok", "tá",
    "certo", "entendi", "sei", "é", "pois",
    # Agreement
    "isso", "exato", "verdade", "claro",
}

_BACKCHANNELS_EN = {
    # Short acknowledgments
    "uh huh", "uh-huh", "uhum", "mhm", "hmm", "hm",
    "yeah", "yep", "yes", "ok", "okay", "right",
    # Agreement
    "sure", "exactly", "true", "got it", "i see",
}

# Regex patterns for backchannel detection
_BACKCHANNEL_PATTERN_PT = re.compile(
    r"^(?:u+h+u+m+|a+h+a+m+|h+[u|m]+|sim|ok|tá|certo|entendi|sei|"
    r"é+|pois|isso|exato|verdade|claro)\s*[.!?]*\s*$",
    re.IGNORECASE,
)

_BACKCHANNEL_PATTERN_EN = re.compile(
    r"^(?:u+h+ *h+u+h+|m+h+m+|h+m+|yeah|yep|yes|ok|okay|right|"
    r"sure|exactly|true|got it|i see)\s*[.!?]*\s*$",
    re.IGNORECASE,
)


class BackchannelAwareInterruption(InterruptionStrategy):
    """Backchannel-aware interruption strategy.

    Uses multiple signals to distinguish backchannels from real
    interruptions:

    1. **Duration-based**: Speech < backchannel_max_ms is likely
       a backchannel. Speech > interruption_min_ms is likely
       a real interruption. Between these is the "uncertain zone"
       where transcript analysis is used.

    2. **Transcript-based** (optional): If partial transcript is
       available, matches against known backchannel patterns.

    3. **Frequency tracking**: If the user repeatedly "interrupts"
       with short utterances, they're likely backchanneling.

    Args:
        backchannel_max_ms: Maximum duration for a backchannel.
            Speech shorter than this is classified as backchannel
            (unless transcript says otherwise). Default: 500ms.
        interruption_min_ms: Minimum duration for a real interruption.
            Speech longer than this is always treated as interruption.
            Default: 800ms.
        min_confidence: Minimum VAD confidence. Default: 0.5.
        language: Language for backchannel pattern matching.
            Default: "pt".
        use_transcript: Whether to use partial transcript for
            backchannel detection. Default: True.
        debounce_ms: Minimum time between interruption decisions.
            Default: 300ms.

    Example:
        >>> strategy = BackchannelAwareInterruption(language="pt")
        >>> # User says "uhum" while agent speaks
        >>> context = InterruptionContext(
        ...     user_is_speaking=True,
        ...     agent_is_speaking=True,
        ...     user_speech_duration_ms=300,
        ...     partial_transcript="uhum",
        ... )
        >>> decision = await strategy.decide(context)
        >>> # → InterruptionDecision.BACKCHANNEL
    """

    def __init__(
        self,
        backchannel_max_ms: float = 500.0,
        interruption_min_ms: float = 800.0,
        min_confidence: float = 0.5,
        language: str = "pt",
        use_transcript: bool = True,
        debounce_ms: float = 300.0,
    ):
        self.backchannel_max_ms = backchannel_max_ms
        self.interruption_min_ms = interruption_min_ms
        self.min_confidence = min_confidence
        self.language = language
        self.use_transcript = use_transcript
        self.debounce_ms = debounce_ms

        # Select backchannel pattern by language
        if language.startswith("pt"):
            self._backchannel_words = _BACKCHANNELS_PT
            self._backchannel_pattern = _BACKCHANNEL_PATTERN_PT
        else:
            self._backchannel_words = _BACKCHANNELS_EN
            self._backchannel_pattern = _BACKCHANNEL_PATTERN_EN

        # Track backchannel frequency
        self._recent_backchannel_count = 0
        self._recent_interruption_count = 0

    async def decide(
        self, context: InterruptionContext
    ) -> InterruptionDecision:
        """Decide between backchannel, interruption, or ignore."""
        # Must have user speech while agent is speaking
        if not context.user_is_speaking or not context.agent_is_speaking:
            return InterruptionDecision.IGNORE

        # Check confidence
        if context.user_speech_confidence < self.min_confidence:
            return InterruptionDecision.IGNORE

        # Debounce
        if context.time_since_last_interruption_ms > 0:
            if context.time_since_last_interruption_ms < self.debounce_ms:
                return InterruptionDecision.IGNORE

        # Phase 1: Duration-based classification
        duration = context.user_speech_duration_ms

        if duration >= self.interruption_min_ms:
            # Long speech = definitely an interruption
            self._recent_interruption_count += 1
            logger.debug(
                f"Real interruption detected: duration={duration:.0f}ms "
                f"(>= {self.interruption_min_ms}ms)"
            )
            return InterruptionDecision.INTERRUPT_IMMEDIATE

        if duration <= self.backchannel_max_ms:
            # Short speech — check transcript if available
            if self.use_transcript and context.partial_transcript:
                if self._is_backchannel_text(context.partial_transcript):
                    self._recent_backchannel_count += 1
                    logger.debug(
                        f"Backchannel detected (transcript): "
                        f"'{context.partial_transcript}'"
                    )
                    return InterruptionDecision.BACKCHANNEL

            # No transcript or no match — treat as backchannel by duration
            self._recent_backchannel_count += 1
            logger.debug(
                f"Backchannel detected (duration): {duration:.0f}ms "
                f"(<= {self.backchannel_max_ms}ms)"
            )
            return InterruptionDecision.BACKCHANNEL

        # Phase 2: Uncertain zone (between backchannel_max and interruption_min)
        # Use transcript if available
        if self.use_transcript and context.partial_transcript:
            if self._is_backchannel_text(context.partial_transcript):
                self._recent_backchannel_count += 1
                logger.debug(
                    f"Backchannel in uncertain zone (transcript): "
                    f"'{context.partial_transcript}'"
                )
                return InterruptionDecision.BACKCHANNEL

        # In uncertain zone without transcript — wait (ignore for now,
        # will be re-evaluated on next VAD frame when duration increases)
        return InterruptionDecision.IGNORE

    def _is_backchannel_text(self, text: str) -> bool:
        """Check if text matches backchannel patterns.

        Args:
            text: Partial transcript text.

        Returns:
            True if the text looks like a backchannel.
        """
        cleaned = text.strip().lower()

        if not cleaned:
            return False

        # Direct word match
        if cleaned in self._backchannel_words:
            return True

        # Regex pattern match
        if self._backchannel_pattern.match(cleaned):
            return True

        return False

    def reset(self) -> None:
        """Reset backchannel tracking."""
        self._recent_backchannel_count = 0
        self._recent_interruption_count = 0

    def on_interruption_executed(self, decision: InterruptionDecision) -> None:
        """Track executed interruptions."""
        if decision == InterruptionDecision.BACKCHANNEL:
            self._recent_backchannel_count += 1
        elif decision in (
            InterruptionDecision.INTERRUPT_IMMEDIATE,
            InterruptionDecision.INTERRUPT_GRACEFUL,
        ):
            self._recent_interruption_count += 1

    @property
    def backchannel_count(self) -> int:
        """Number of backchannels detected since last reset."""
        return self._recent_backchannel_count

    @property
    def interruption_count(self) -> int:
        """Number of real interruptions detected since last reset."""
        return self._recent_interruption_count
