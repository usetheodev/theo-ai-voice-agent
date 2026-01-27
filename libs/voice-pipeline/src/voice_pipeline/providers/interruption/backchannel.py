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

# Pure backchannels — ALWAYS backchannel regardless of context
_PURE_BACKCHANNELS_PT = {"uhum", "aham", "hum", "hm", "ahan"}
_PURE_BACKCHANNELS_EN = {"uh huh", "uh-huh", "uhum", "mhm", "hmm", "hm"}

# Context-dependent — backchannel ONLY if agent did NOT ask a question
_CONTEXT_DEPENDENT_PT = {
    "sim", "nao", "não", "ok", "tá", "certo", "entendi", "sei",
    "é", "pois", "isso", "exato", "verdade", "claro",
}
_CONTEXT_DEPENDENT_EN = {
    "yeah", "yep", "yes", "ok", "okay", "right", "sure",
    "exactly", "true", "got it", "i see",
}

# Combined sets for backward compatibility
_BACKCHANNELS_PT = _PURE_BACKCHANNELS_PT | _CONTEXT_DEPENDENT_PT
_BACKCHANNELS_EN = _PURE_BACKCHANNELS_EN | _CONTEXT_DEPENDENT_EN

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
            Default: "en".
        use_transcript: Whether to use partial transcript for
            backchannel detection. Default: True.
        debounce_ms: Minimum time between interruption decisions.
            Default: 300ms.

    Example:
        >>> strategy = BackchannelAwareInterruption(language="en")
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
        language: str = "en",
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
            self._pure_backchannels = _PURE_BACKCHANNELS_PT
            self._context_dependent = _CONTEXT_DEPENDENT_PT
        else:
            self._backchannel_words = _BACKCHANNELS_EN
            self._backchannel_pattern = _BACKCHANNEL_PATTERN_EN
            self._pure_backchannels = _PURE_BACKCHANNELS_EN
            self._context_dependent = _CONTEXT_DEPENDENT_EN

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

        agent_text = context.agent_response_text or ""

        if duration <= self.backchannel_max_ms:
            # Short speech — check transcript if available
            if self.use_transcript and context.partial_transcript:
                # Check if this is a context-dependent response to a question
                if self._is_context_response(context.partial_transcript, agent_text):
                    self._recent_interruption_count += 1
                    logger.debug(
                        f"Context response detected (question answer): "
                        f"'{context.partial_transcript}' → INTERRUPT"
                    )
                    return InterruptionDecision.INTERRUPT_IMMEDIATE

                if self._is_backchannel_text(context.partial_transcript, agent_text):
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
            # Check if this is a context-dependent response to a question
            if self._is_context_response(context.partial_transcript, agent_text):
                self._recent_interruption_count += 1
                logger.debug(
                    f"Context response in uncertain zone: "
                    f"'{context.partial_transcript}' → INTERRUPT"
                )
                return InterruptionDecision.INTERRUPT_IMMEDIATE

            if self._is_backchannel_text(context.partial_transcript, agent_text):
                self._recent_backchannel_count += 1
                logger.debug(
                    f"Backchannel in uncertain zone (transcript): "
                    f"'{context.partial_transcript}'"
                )
                return InterruptionDecision.BACKCHANNEL

        # In uncertain zone without transcript — wait (ignore for now,
        # will be re-evaluated on next VAD frame when duration increases)
        return InterruptionDecision.IGNORE

    def _agent_asked_question(self, agent_text: str) -> bool:
        """Detect if the agent's last sentence ends with '?'.

        Args:
            agent_text: The agent's response text (so far).

        Returns:
            True if the agent asked a question.
        """
        if not agent_text:
            return False
        # Find last sentence-ending character
        trimmed = agent_text.rstrip()
        if not trimmed:
            return False
        return trimmed[-1] == "?"

    def _is_context_response(self, text: str, agent_text: str) -> bool:
        """Check if text is a context-dependent word responding to a question.

        Returns True when the text is a context-dependent backchannel word
        AND the agent asked a question — meaning this is a real answer,
        not a backchannel.

        Args:
            text: Partial transcript text from user.
            agent_text: Agent's response text.

        Returns:
            True if text is a real response to a question.
        """
        cleaned = text.strip().lower()
        if not cleaned:
            return False
        return (
            cleaned in self._context_dependent
            and self._agent_asked_question(agent_text)
        )

    def _is_backchannel_text(self, text: str, agent_text: str = "") -> bool:
        """Check if text matches backchannel patterns.

        Context-aware: words like "sim", "ok" are only backchannels
        when the agent did NOT ask a question. Pure backchannels like
        "uhum", "aham" are always classified as backchannels.

        Args:
            text: Partial transcript text.
            agent_text: Agent's response text (for context detection).

        Returns:
            True if the text looks like a backchannel.
        """
        cleaned = text.strip().lower()

        if not cleaned:
            return False

        # Pure backchannels — always backchannel regardless of context
        if cleaned in self._pure_backchannels:
            return True

        # Context-dependent words — only backchannel if agent didn't ask a question
        if cleaned in self._context_dependent:
            if self._agent_asked_question(agent_text):
                return False  # This is a real answer, not backchannel
            return True

        # Regex pattern match (for variations like "u+h+u+m+")
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
