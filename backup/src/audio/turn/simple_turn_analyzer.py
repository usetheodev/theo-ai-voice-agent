"""
Simple Turn Analyzer - Rule-Based End-of-Turn Detection

Simple rule-based turn detection using pause duration analysis.

Algorithm:
    1. User speaks: "Hello, how are you?"
    2. VAD detects silence for 1.0s → END-OF-TURN
    3. Agent processes user's utterance

Parameters:
    - pause_duration: How long silence before declaring end-of-turn (default: 1.0s)
    - min_duration: Minimum speech duration to consider valid turn (default: 0.3s)

Trade-offs:
    ✅ Pros:
        - Simple, fast (no ML overhead)
        - Predictable behavior
        - No model downloads
        - Low CPU usage

    ❌ Cons:
        - Fixed pause duration (not adaptive)
        - Can't handle fast speakers (short natural pauses)
        - Can't handle slow speakers (long thinking pauses)
        - No prosody analysis (can't detect questions vs statements)

Pattern based on:
    - Pipecat AI (turn detection strategy)
    - Asterisk-AI-Voice-Agent (Phase 2.1 planning)
    - Common telephony IVR timeout logic
"""

import time
from dataclasses import dataclass
from typing import Optional, Tuple

from .base_turn_analyzer import (
    BaseTurnAnalyzer,
    BaseTurnParams,
    EndOfTurnState,
)


@dataclass
class SimpleTurnParams(BaseTurnParams):
    """
    Parameters for SimpleTurnAnalyzer.

    Attributes:
        pause_duration: Seconds of silence to declare end-of-turn (default: 1.0s)
            - Too short (0.3s): Agent interrupts mid-sentence → BAD UX
            - Too long (2.0s): User waits unnecessarily → BAD UX
            - Sweet spot: 0.8-1.2s for natural conversations

        min_duration: Minimum speech duration to consider valid turn (default: 0.3s)
            - Prevents false triggers from coughs, background noise
            - Example: 0.1s of speech → Ignore (too short)
            - Example: 0.5s of speech → Valid turn

    Recommended Settings:
        - Telephony (polite): pause=1.2s, min=0.3s
        - Telephony (responsive): pause=0.8s, min=0.2s
        - Video call: pause=1.0s, min=0.3s
        - Gaming/fast-paced: pause=0.6s, min=0.2s
    """
    pause_duration: float = 1.0   # Seconds of silence for end-of-turn
    min_duration: float = 0.3     # Minimum speech duration to consider


class SimpleTurnAnalyzer(BaseTurnAnalyzer):
    """
    Simple rule-based turn analyzer using pause duration.

    Algorithm:
        1. Accumulate audio frames with VAD labels (speech/silence)
        2. Track speech_duration and silence_duration
        3. When silence_duration >= pause_duration → COMPLETE
        4. When speech detected → Reset silence counter

    State Machine:
        ```
        [INITIAL] --speech--> [SPEAKING] --silence(>1s)--> [COMPLETE]
            ↑                     |
            └---------------------┘
                 (clear() resets)
        ```

    Example Flow:
        ```
        Time  | Audio    | VAD    | State      | Action
        ------|----------|--------|------------|------------------
        0.0s  | silence  | False  | INITIAL    | Wait for speech
        0.2s  | "Hello"  | True   | SPEAKING   | speech_duration += 0.02s
        0.4s  | "how"    | True   | SPEAKING   | speech_duration += 0.02s
        0.6s  | silence  | False  | SPEAKING   | silence_duration += 0.02s
        1.6s  | silence  | False  | COMPLETE   | Turn complete! (1.0s silence)
        ```

    Usage:
        ```python
        # Initialize
        analyzer = SimpleTurnAnalyzer(
            sample_rate=8000,
            pause_duration=1.0,
            min_duration=0.3
        )

        # Process audio frames (20ms each @ 8kHz)
        for pcm_data, is_speech in audio_stream:
            state = analyzer.append_audio(pcm_data, is_speech)

            if state == EndOfTurnState.COMPLETE:
                # User finished speaking
                transcription = await asr.transcribe(analyzer.buffer)
                response = await llm.generate(transcription)
                analyzer.clear()  # Reset for next turn
        ```
    """

    def __init__(
        self,
        *,
        sample_rate: Optional[int] = None,
        pause_duration: float = 1.0,
        min_duration: float = 0.3,
    ):
        """
        Initialize SimpleTurnAnalyzer.

        Args:
            sample_rate: Audio sample rate in Hz (e.g., 8000 for G.711 ulaw)
            pause_duration: Seconds of silence to declare end-of-turn
            min_duration: Minimum speech duration to consider valid turn

        Example:
            analyzer = SimpleTurnAnalyzer(sample_rate=8000, pause_duration=1.0)
        """
        super().__init__(sample_rate=sample_rate)

        # Configuration
        self._params = SimpleTurnParams(
            pause_duration=pause_duration,
            min_duration=min_duration,
        )

        # State tracking
        self._speech_triggered = False     # True once speech detected
        self._speech_start_time: Optional[float] = None  # When speech started
        self._silence_start_time: Optional[float] = None  # When silence started
        self._last_audio_time: float = time.time()

        # Audio buffer (for passing to ASR)
        self._audio_buffer: list[bytes] = []

    @property
    def params(self) -> SimpleTurnParams:
        """Get current turn analyzer parameters."""
        return self._params

    @property
    def speech_triggered(self) -> bool:
        """Check if speech has been detected."""
        return self._speech_triggered

    def append_audio(self, buffer: bytes, is_speech: bool) -> EndOfTurnState:
        """
        Append audio frame and update turn detection state.

        Args:
            buffer: Raw PCM audio data (int16 samples)
                - Format: Raw PCM S16LE (signed 16-bit little-endian)
                - Example: 20ms @ 8kHz = 160 samples = 320 bytes

            is_speech: VAD result for this frame
                - True: Speech detected (user speaking)
                - False: Silence detected (pause or no input)

        Returns:
            EndOfTurnState:
                - COMPLETE: User finished speaking (pause_duration reached)
                - INCOMPLETE: User still speaking or pause too short

        Pattern:
            Synchronous for performance (called 50x/second @ 20ms frames)
        """
        current_time = time.time()
        self._last_audio_time = current_time

        # Accumulate audio buffer
        self._audio_buffer.append(buffer)

        if is_speech:
            # Speech detected
            if not self._speech_triggered:
                # First speech detection
                self._speech_triggered = True
                self._speech_start_time = current_time

            # Reset silence counter (user still speaking)
            self._silence_start_time = None

            return EndOfTurnState.INCOMPLETE

        else:
            # Silence detected
            if not self._speech_triggered:
                # No speech yet, ignore silence
                return EndOfTurnState.INCOMPLETE

            # Start tracking silence
            if self._silence_start_time is None:
                self._silence_start_time = current_time

            # Calculate silence duration
            silence_duration = current_time - self._silence_start_time

            # Check if pause threshold reached
            if silence_duration >= self._params.pause_duration:
                # Calculate total speech duration
                if self._speech_start_time is not None:
                    speech_duration = self._silence_start_time - self._speech_start_time
                else:
                    speech_duration = 0.0

                # Validate minimum speech duration
                if speech_duration >= self._params.min_duration:
                    # Valid turn complete
                    return EndOfTurnState.COMPLETE
                else:
                    # Too short, ignore (likely noise/cough)
                    self.clear()  # Reset for next turn
                    return EndOfTurnState.INCOMPLETE

            return EndOfTurnState.INCOMPLETE

    async def analyze_end_of_turn(self) -> Tuple[EndOfTurnState, Optional[dict]]:
        """
        Analyze if end-of-turn occurred (called on VAD silence).

        For SimpleTurnAnalyzer, this is straightforward:
        - Check current silence duration
        - Return COMPLETE if pause_duration reached

        Returns:
            Tuple of:
                - EndOfTurnState: COMPLETE or INCOMPLETE
                - Optional[dict]: Debug metrics (pause duration, speech duration)

        Example:
            state, metrics = await analyzer.analyze_end_of_turn()
            if state == EndOfTurnState.COMPLETE:
                logger.info(f"Turn complete: {metrics}")
        """
        if not self._speech_triggered:
            # No speech detected yet
            return EndOfTurnState.INCOMPLETE, None

        if self._silence_start_time is None:
            # Still speaking (no silence yet)
            return EndOfTurnState.INCOMPLETE, None

        current_time = time.time()
        silence_duration = current_time - self._silence_start_time

        if silence_duration >= self._params.pause_duration:
            # Calculate speech duration
            if self._speech_start_time is not None and self._silence_start_time is not None:
                speech_duration = self._silence_start_time - self._speech_start_time
            else:
                speech_duration = 0.0

            # Check minimum duration
            if speech_duration >= self._params.min_duration:
                # Valid turn complete
                metrics = {
                    "speech_duration": speech_duration,
                    "silence_duration": silence_duration,
                    "pause_threshold": self._params.pause_duration,
                    "frames_buffered": len(self._audio_buffer),
                }
                return EndOfTurnState.COMPLETE, metrics
            else:
                # Too short, ignore
                self.clear()
                return EndOfTurnState.INCOMPLETE, {
                    "reason": "speech_too_short",
                    "speech_duration": speech_duration,
                    "min_duration": self._params.min_duration,
                }

        # Pause not long enough yet
        return EndOfTurnState.INCOMPLETE, {
            "silence_duration": silence_duration,
            "pause_threshold": self._params.pause_duration,
        }

    def clear(self):
        """
        Reset turn analyzer to initial state.

        Called after processing a complete turn (user utterance) to
        prepare for the next turn.

        Example:
            # After processing user input
            transcription = await asr.transcribe(analyzer.get_buffer())
            response = await llm.generate(transcription)
            analyzer.clear()  # Ready for next turn
        """
        self._speech_triggered = False
        self._speech_start_time = None
        self._silence_start_time = None
        self._audio_buffer.clear()

    def get_buffer(self) -> bytes:
        """
        Get accumulated audio buffer for ASR processing.

        Returns:
            Concatenated PCM audio data (all frames since last clear())

        Example:
            if turn_state == EndOfTurnState.COMPLETE:
                audio = analyzer.get_buffer()
                transcription = await asr.transcribe(audio)
        """
        return b''.join(self._audio_buffer)

    def get_buffer_duration(self) -> float:
        """
        Calculate duration of buffered audio in seconds.

        Returns:
            Duration in seconds based on sample_rate and buffer size

        Example:
            duration = analyzer.get_buffer_duration()
            logger.info(f"Buffered {duration:.2f}s of audio")
        """
        if self._sample_rate == 0:
            return 0.0

        total_bytes = sum(len(chunk) for chunk in self._audio_buffer)
        total_samples = total_bytes // 2  # int16 = 2 bytes per sample
        return total_samples / self._sample_rate

    def __repr__(self) -> str:
        """
        Human-readable representation for debugging.

        Example output:
            SimpleTurnAnalyzer(pause=1.0s, min=0.3s, speaking=True,
                              speech=0.5s, silence=0.2s, buffered=25 frames)
        """
        speech_duration = 0.0
        silence_duration = 0.0

        if self._speech_start_time is not None and self._silence_start_time is not None:
            speech_duration = self._silence_start_time - self._speech_start_time
        if self._silence_start_time is not None:
            silence_duration = time.time() - self._silence_start_time

        return (
            f"SimpleTurnAnalyzer("
            f"pause={self._params.pause_duration}s, "
            f"min={self._params.min_duration}s, "
            f"speaking={self._speech_triggered}, "
            f"speech={speech_duration:.2f}s, "
            f"silence={silence_duration:.2f}s, "
            f"buffered={len(self._audio_buffer)} frames)"
        )


# Export all classes
__all__ = [
    'SimpleTurnParams',
    'SimpleTurnAnalyzer',
]
