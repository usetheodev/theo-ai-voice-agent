"""
Voice Activity Detection (VAD)

Detects when user is speaking vs silence using RMS energy analysis.
Triggers callbacks when speech starts/ends.

Features:
- RMS energy-based detection
- Configurable thresholds (start, end)
- Silence timeout (500ms default)
- State tracking (SILENCE, SPEECH, PENDING_END)
"""

import logging
import numpy as np
from enum import Enum
from typing import Optional, Callable
import time


class VADState(Enum):
    """Voice activity states"""
    SILENCE = "silence"
    SPEECH = "speech"
    PENDING_END = "pending_end"  # Speech detected but waiting for silence confirmation


class VoiceActivityDetector:
    """
    Energy-based Voice Activity Detection

    Usage:
        vad = VoiceActivityDetector(
            on_speech_start=lambda: print("Speech started"),
            on_speech_end=lambda: print("Speech ended")
        )

        # Process each PCM frame
        vad.process_frame(pcm_data)
    """

    def __init__(self,
                 sample_rate: int = 8000,
                 frame_duration_ms: int = 20,
                 energy_threshold_start: float = 500.0,
                 energy_threshold_end: float = 300.0,
                 silence_duration_ms: int = 500,
                 on_speech_start: Optional[Callable] = None,
                 on_speech_end: Optional[Callable] = None):
        """
        Initialize VAD

        Args:
            sample_rate: Audio sample rate (Hz)
            frame_duration_ms: Frame duration in milliseconds
            energy_threshold_start: RMS energy to start speech detection
            energy_threshold_end: RMS energy to end speech detection
            silence_duration_ms: Silence duration to confirm end of speech
            on_speech_start: Callback when speech starts
            on_speech_end: Callback when speech ends
        """
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.energy_threshold_start = energy_threshold_start
        self.energy_threshold_end = energy_threshold_end
        self.silence_duration_ms = silence_duration_ms

        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end

        self.logger = logging.getLogger("ai-voice-agent.audio.vad")

        # State tracking
        self.state = VADState.SILENCE
        self.silence_frames = 0
        self.speech_frames = 0

        # Calculate silence threshold in frames
        self.silence_frames_threshold = int(
            (silence_duration_ms / frame_duration_ms)
        )

        # Statistics
        self.total_frames = 0
        self.speech_segments = 0
        self.total_speech_frames = 0

        self.logger.info(
            f"VAD initialized: "
            f"threshold_start={energy_threshold_start:.1f}, "
            f"threshold_end={energy_threshold_end:.1f}, "
            f"silence_timeout={silence_duration_ms}ms ({self.silence_frames_threshold} frames)"
        )

    def calculate_rms_energy(self, pcm_data: bytes) -> float:
        """
        Calculate RMS (Root Mean Square) energy of audio frame

        Args:
            pcm_data: PCM audio data (16-bit signed)

        Returns:
            RMS energy value
        """
        try:
            # Convert to numpy array
            samples = np.frombuffer(pcm_data, dtype=np.int16)

            # Calculate RMS: sqrt(mean(x^2))
            rms = np.sqrt(np.mean(samples.astype(np.float32) ** 2))

            return float(rms)

        except Exception as e:
            self.logger.error(f"Error calculating RMS: {e}", exc_info=True)
            return 0.0

    def process_frame(self, pcm_data: bytes) -> bool:
        """
        Process audio frame and update VAD state

        Args:
            pcm_data: PCM audio data (16-bit signed)

        Returns:
            True if currently in speech, False otherwise
        """
        self.total_frames += 1

        # Calculate energy
        energy = self.calculate_rms_energy(pcm_data)

        # State machine
        if self.state == VADState.SILENCE:
            if energy >= self.energy_threshold_start:
                # Speech detected
                self._transition_to_speech()
                self.speech_frames = 1
                return True
            return False

        elif self.state == VADState.SPEECH:
            if energy >= self.energy_threshold_end:
                # Continue speech
                self.speech_frames += 1
                self.total_speech_frames += 1
                self.silence_frames = 0
                return True
            else:
                # Energy dropped, start silence counter
                self.state = VADState.PENDING_END
                self.silence_frames = 1
                self.logger.debug(
                    f"Speech pending end (energy={energy:.1f} < {self.energy_threshold_end:.1f})"
                )
                return True

        elif self.state == VADState.PENDING_END:
            if energy >= self.energy_threshold_end:
                # False alarm, back to speech
                self.state = VADState.SPEECH
                self.silence_frames = 0
                self.speech_frames += 1
                self.total_speech_frames += 1
                self.logger.debug("Speech resumed (false end)")
                return True
            else:
                # Continue silence counter
                self.silence_frames += 1

                if self.silence_frames >= self.silence_frames_threshold:
                    # Confirmed end of speech
                    self._transition_to_silence()
                    return False

                # Still waiting for confirmation
                return True

        return False

    def _transition_to_speech(self):
        """Transition from SILENCE to SPEECH"""
        self.state = VADState.SPEECH
        self.speech_segments += 1

        self.logger.info(
            f"🎙️  Speech started (segment #{self.speech_segments})"
        )

        if self.on_speech_start:
            try:
                self.on_speech_start()
            except Exception as e:
                self.logger.error(f"Error in speech_start callback: {e}", exc_info=True)

    def _transition_to_silence(self):
        """Transition from SPEECH/PENDING_END to SILENCE"""
        duration_s = (self.speech_frames * self.frame_duration_ms) / 1000.0

        self.logger.info(
            f"🤫 Speech ended (duration: {duration_s:.2f}s, {self.speech_frames} frames)"
        )

        self.state = VADState.SILENCE
        self.speech_frames = 0
        self.silence_frames = 0

        if self.on_speech_end:
            try:
                self.on_speech_end()
            except Exception as e:
                self.logger.error(f"Error in speech_end callback: {e}", exc_info=True)

    def is_speech(self) -> bool:
        """Check if currently in speech state"""
        return self.state in (VADState.SPEECH, VADState.PENDING_END)

    def reset(self):
        """Reset VAD state"""
        was_speech = self.is_speech()

        self.state = VADState.SILENCE
        self.silence_frames = 0
        self.speech_frames = 0

        if was_speech:
            self.logger.warning("VAD reset while in speech state")

    def get_stats(self) -> dict:
        """Get VAD statistics"""
        return {
            'state': self.state.value,
            'total_frames': self.total_frames,
            'speech_segments': self.speech_segments,
            'total_speech_frames': self.total_speech_frames,
            'current_speech_frames': self.speech_frames,
            'current_silence_frames': self.silence_frames,
            'is_speech': self.is_speech()
        }


def test_vad():
    """Test VAD with synthetic audio"""
    import numpy as np

    def on_start():
        print(">>> SPEECH STARTED")

    def on_end():
        print(">>> SPEECH ENDED")

    # Create VAD
    vad = VoiceActivityDetector(
        sample_rate=8000,
        energy_threshold_start=500.0,
        energy_threshold_end=300.0,
        silence_duration_ms=500,
        on_speech_start=on_start,
        on_speech_end=on_end
    )

    # Generate test audio
    sample_rate = 8000
    frame_size = 160  # 20ms @ 8kHz

    # 1. Silence (500ms = 25 frames)
    print("\n1. Silence (500ms)")
    for i in range(25):
        silence = np.zeros(frame_size, dtype=np.int16)
        vad.process_frame(silence.tobytes())

    # 2. Speech (1000ms = 50 frames)
    print("\n2. Speech (1000ms)")
    for i in range(50):
        # Generate 440 Hz tone
        t = np.linspace(0, 0.02, frame_size)
        speech = (np.sin(2 * np.pi * 440 * t) * 5000).astype(np.int16)
        vad.process_frame(speech.tobytes())

    # 3. Silence (600ms = 30 frames) - should trigger end
    print("\n3. Silence (600ms)")
    for i in range(30):
        silence = np.zeros(frame_size, dtype=np.int16)
        vad.process_frame(silence.tobytes())

    # 4. Speech again (500ms = 25 frames)
    print("\n4. Speech again (500ms)")
    for i in range(25):
        t = np.linspace(0, 0.02, frame_size)
        speech = (np.sin(2 * np.pi * 440 * t) * 5000).astype(np.int16)
        vad.process_frame(speech.tobytes())

    # 5. Final silence
    print("\n5. Final silence (600ms)")
    for i in range(30):
        silence = np.zeros(frame_size, dtype=np.int16)
        vad.process_frame(silence.tobytes())

    print(f"\nVAD Stats: {vad.get_stats()}")


if __name__ == '__main__':
    test_vad()
