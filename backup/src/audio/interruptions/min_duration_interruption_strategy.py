"""
Min Duration Interruption Strategy - Smart Barge-in Based on Audio Duration

Interrupt agent ONLY if user speaks for at least N seconds.

Algorithm:
    1. Agent speaks: "Let me explain our pricing plans..."
    2. User: [cough] (0.2s) → DON'T INTERRUPT (too short)
    3. Agent continues: "...we have three tiers..."
    4. User: "Actually, stop!" (1.2s) → INTERRUPT (long enough)

Why This Works:
    ✅ Coughs/sneezes: 0.1-0.3s → Ignored
    ✅ "Um", "ah", fillers: 0.2-0.4s → Ignored
    ✅ Background noise: 0.1-0.5s → Ignored
    ✅ Real interruptions: 0.8s+ → Allowed

Trade-offs:
    ✅ Pros:
        - Simple, no ASR needed
        - Fast (no ML inference)
        - No false positives from noise
        - Works across languages

    ❌ Cons:
        - Slow interruptions only (can't say "stop!" quickly)
        - Can't detect intent ("yes" vs "no" both same duration)
        - Fixed threshold (not adaptive)

Recommended Settings:
    - Conservative (fewer false positives): min_duration=1.0s
    - Balanced (good for most cases): min_duration=0.8s
    - Aggressive (faster interruptions): min_duration=0.5s

Pattern based on:
    - Pipecat AI (min_words_interruption_strategy.py)
    - Asterisk-AI-Voice-Agent (Phase 2.1 planning)
    - Common IVR systems (min speech duration)
"""

import logging

from .base_interruption_strategy import BaseInterruptionStrategy

logger = logging.getLogger(__name__)


class MinDurationInterruptionStrategy(BaseInterruptionStrategy):
    """
    Interruption strategy based on minimum audio duration.

    Only allows interruption if user speaks for at least min_duration seconds.

    Algorithm:
        1. Accumulate user audio during agent speech
        2. Calculate total duration (sample_rate + buffer size)
        3. If duration >= min_duration → should_interrupt() = True
        4. If duration < min_duration → should_interrupt() = False

    State Machine:
        ```
        [IDLE] --agent_speaks--> [AGENT_SPEAKING]
                                       |
                                user_speaks (append_audio)
                                       ↓
                                 [ACCUMULATING]
                                       |
                                user_stops (should_interrupt?)
                                       ↓
                        duration >= min_duration?
                        ├─ YES → True (INTERRUPT)
                        └─ NO → False (IGNORE)
        ```

    Example Flow:
        ```
        Time  | Event              | Duration | Action
        ------|--------------------|---------|-----------------
        0.0s  | Agent starts       | 0.0s    | strategy.reset()
        0.5s  | User coughs        | 0.0s    | strategy.append_audio()
        0.7s  | User stops         | 0.2s    | should_interrupt() → False
        1.0s  | Agent continues    | -       | -
        2.0s  | User: "Stop!"      | 0.0s    | strategy.append_audio()
        3.2s  | User stops         | 1.2s    | should_interrupt() → True
        3.2s  | Agent interrupted  | -       | stop_playback()
        ```

    Usage:
        ```python
        # Initialize strategy
        strategy = MinDurationInterruptionStrategy(min_duration=0.8)

        # During agent speech
        while agent_is_speaking:
            if vad_detected_user_speech:
                # Accumulate user audio
                await strategy.append_audio(pcm_data, sample_rate=8000)

            if vad_detected_silence:
                # Check if real interruption
                if await strategy.should_interrupt():
                    await stop_agent_playback()
                    await process_user_input()
                else:
                    logger.info("False alarm (too short)")

                await strategy.reset()  # Clear for next check
        ```
    """

    def __init__(self, *, min_duration: float = 0.8):
        """
        Initialize the minimum duration interruption strategy.

        Args:
            min_duration: Minimum seconds of speech to trigger interruption
                - Default: 0.8s (balanced setting)
                - Conservative: 1.0-1.2s (fewer false positives)
                - Aggressive: 0.5-0.6s (faster interruptions)

        Example:
            # Conservative (fewer false interruptions)
            strategy = MinDurationInterruptionStrategy(min_duration=1.0)

            # Aggressive (faster response)
            strategy = MinDurationInterruptionStrategy(min_duration=0.5)
        """
        super().__init__()
        self._min_duration = min_duration

        # State tracking
        self._total_samples = 0  # Total audio samples accumulated
        self._sample_rate = 0    # Current sample rate

    async def append_audio(self, audio: bytes, sample_rate: int):
        """
        Append audio data and accumulate duration.

        Args:
            audio: Raw PCM audio data (int16 samples)
                - Format: Raw PCM S16LE (signed 16-bit little-endian)
                - Example: 20ms @ 8kHz = 160 samples = 320 bytes

            sample_rate: Sample rate of the audio data in Hz
                - Example: 8000 (G.711 ulaw)
                - Example: 16000 (Whisper)

        Pattern:
            Called for every audio frame during agent speech when user speaks.
            Synchronous audio processing (no blocking I/O).

        Example:
            # In RTP processing
            if agent_is_speaking and user_speaking:
                await strategy.append_audio(pcm_data, sample_rate=8000)
        """
        # Update sample rate (may change mid-call)
        self._sample_rate = sample_rate

        # Calculate samples in this frame
        # int16 = 2 bytes per sample
        num_samples = len(audio) // 2

        # Accumulate total samples
        self._total_samples += num_samples

    async def should_interrupt(self) -> bool:
        """
        Check if the minimum duration has been reached.

        Returns:
            True: User spoke for ≥ min_duration seconds (REAL INTERRUPTION)
            False: User spoke for < min_duration seconds (FALSE ALARM)

        Algorithm:
            duration = total_samples / sample_rate
            interrupt = duration >= min_duration

        Example:
            ```python
            # User spoke for 1.2s with min_duration=0.8s
            should_interrupt() → True (1.2 >= 0.8)

            # User spoke for 0.3s with min_duration=0.8s
            should_interrupt() → False (0.3 < 0.8)
            ```

        Pattern:
            Async for consistency with base class (though synchronous logic).
        """
        if self._sample_rate == 0 or self._total_samples == 0:
            # No audio accumulated yet
            return False

        # Calculate duration from samples
        duration = self._total_samples / self._sample_rate

        # Check threshold
        interrupt = duration >= self._min_duration

        # Log decision
        logger.debug(
            f"should_interrupt={interrupt} "
            f"duration={duration:.2f}s "
            f"min_duration={self._min_duration}s "
            f"samples={self._total_samples} "
            f"sample_rate={self._sample_rate}Hz"
        )

        return interrupt

    async def reset(self):
        """
        Reset the accumulated audio duration.

        Called after processing an interruption check to prepare
        for the next potential interruption.

        Example:
            # After checking interruption
            if await strategy.should_interrupt():
                await handle_interruption()
            await strategy.reset()  # Always reset
        """
        self._total_samples = 0
        # Keep sample_rate (doesn't change often)

    def get_current_duration(self) -> float:
        """
        Get current accumulated audio duration in seconds.

        Returns:
            Duration in seconds (0.0 if no audio accumulated)

        Use Cases:
            - Debugging (check current duration)
            - Metrics (track interruption attempts)
            - UI feedback (show "user speaking X seconds")

        Example:
            duration = strategy.get_current_duration()
            logger.info(f"User spoke for {duration:.2f}s so far")
        """
        if self._sample_rate == 0:
            return 0.0
        return self._total_samples / self._sample_rate

    def __repr__(self) -> str:
        """
        Human-readable representation for debugging.

        Example output:
            MinDurationInterruptionStrategy(min=0.8s, current=0.3s, samples=2400)
        """
        current_duration = self.get_current_duration()
        return (
            f"MinDurationInterruptionStrategy("
            f"min={self._min_duration}s, "
            f"current={current_duration:.2f}s, "
            f"samples={self._total_samples})"
        )


# Export strategy class
__all__ = [
    'MinDurationInterruptionStrategy',
]
