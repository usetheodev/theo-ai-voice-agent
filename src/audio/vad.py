"""
Voice Activity Detection (VAD) - Dual-Mode (WebRTC + Energy)

Detects when user is speaking vs silence using TWO methods:
1. WebRTC VAD (Google ML-based) - primary, more robust
2. RMS Energy VAD - fallback when WebRTC not available

Triggers callbacks when speech starts/ends.

Features:
- Dual-mode detection (WebRTC OR Energy)
- WebRTC VAD: ML-based, robust to noise
- Energy VAD: RMS-based fallback (no external deps)
- Configurable thresholds (start, end)
- Silence timeout (500ms default)
- State tracking (SILENCE, SPEECH, PENDING_END)
"""

import numpy as np
from enum import Enum
from typing import Optional, Callable

from ..common.logging import get_logger

logger = get_logger('audio.vad')

# WebRTC VAD (optional dependency - graceful fallback)
try:
    import webrtcvad
    WEBRTC_VAD_AVAILABLE = True
except ImportError:
    webrtcvad = None
    WEBRTC_VAD_AVAILABLE = False


class VADState(Enum):
    """Voice activity states"""
    SILENCE = "silence"
    SPEECH = "speech"
    PENDING_END = "pending_end"  # Speech detected but waiting for silence confirmation


class VoiceActivityDetector:
    """
    Dual-Mode Voice Activity Detection (WebRTC + Energy)

    Uses WebRTC VAD (ML-based) as primary with energy-based fallback.

    Usage:
        vad = VoiceActivityDetector(
            webrtc_aggressiveness=1,  # 0-3 (1=balanced, recommended)
            on_speech_start=lambda: print("Speech started"),
            on_speech_end=lambda: print("Speech ended")
        )

        # Process each PCM frame
        vad.process_frame(pcm_data)

    Mode Selection:
        - If webrtcvad installed: Dual-mode (WebRTC OR Energy)
        - If webrtcvad missing: Energy-only (graceful fallback)
    """

    def __init__(self,
                 sample_rate: int = 8000,
                 frame_duration_ms: int = 20,
                 energy_threshold_start: float = 500.0,
                 energy_threshold_end: float = 300.0,
                 silence_duration_ms: int = 500,
                 min_speech_duration_ms: int = 300,
                 webrtc_aggressiveness: int = 1,
                 on_speech_start: Optional[Callable] = None,
                 on_speech_end: Optional[Callable] = None):
        """
        Initialize VAD (Dual-Mode: WebRTC + Energy)

        Args:
            sample_rate: Audio sample rate (Hz) - must be 8000/16000/32000 for WebRTC
            frame_duration_ms: Frame duration in milliseconds
            energy_threshold_start: RMS energy to start speech detection
            energy_threshold_end: RMS energy to end speech detection
            silence_duration_ms: Silence duration to confirm end of speech
            min_speech_duration_ms: Minimum speech duration to be considered valid (filters noise)
            webrtc_aggressiveness: WebRTC VAD aggressiveness (0-3, 1=balanced, 3=most aggressive)
            on_speech_start: Callback when speech starts
            on_speech_end: Callback when speech ends
        """
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.energy_threshold_start = energy_threshold_start
        self.energy_threshold_end = energy_threshold_end
        self.silence_duration_ms = silence_duration_ms
        self.min_speech_duration_ms = min_speech_duration_ms
        self.webrtc_aggressiveness = webrtc_aggressiveness

        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end

        # WebRTC VAD initialization (optional dependency)
        self.webrtc_vad = None
        self.webrtc_mode = "energy-only"  # Default to energy-only

        if WEBRTC_VAD_AVAILABLE:
            try:
                # Validate sample rate (WebRTC only supports 8k/16k/32k)
                if sample_rate not in [8000, 16000, 32000]:
                    logger.warning("WebRTC VAD requires 8k/16k/32k Hz, using energy-only mode",
                                 sample_rate=sample_rate)
                    self.webrtc_mode = "energy-only"
                else:
                    self.webrtc_vad = webrtcvad.Vad(webrtc_aggressiveness)
                    self.webrtc_mode = "dual-mode"
                    logger.info("WebRTC VAD initialized",
                              aggressiveness=webrtc_aggressiveness,
                              sample_rate=sample_rate)
            except Exception as e:
                logger.warning("WebRTC VAD init failed, using energy-only mode", error=str(e))
                self.webrtc_vad = None
                self.webrtc_mode = "energy-only"
        else:
            logger.info("WebRTC VAD not available (pip install webrtcvad), using energy-only mode")
            self.webrtc_mode = "energy-only"

        # State tracking
        self.state = VADState.SILENCE
        self.silence_frames = 0
        self.speech_frames = 0

        # Calculate silence threshold in frames
        self.silence_frames_threshold = int(silence_duration_ms / frame_duration_ms)

        # Calculate minimum speech threshold in frames
        self.min_speech_frames_threshold = int(min_speech_duration_ms / frame_duration_ms)

        # Statistics
        self.total_frames = 0
        self.speech_segments = 0
        self.total_speech_frames = 0
        self.webrtc_detections = 0
        self.energy_detections = 0
        self.agreement_count = 0

        logger.info("VAD initialized",
                   mode=self.webrtc_mode,
                   threshold_start=energy_threshold_start,
                   threshold_end=energy_threshold_end,
                   silence_timeout_ms=silence_duration_ms,
                   min_speech_ms=min_speech_duration_ms)

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
            logger.error("Error calculating RMS", error=str(e))
            return 0.0

    def process_frame(self, pcm_data: bytes) -> bool:
        """
        Process audio frame and update VAD state (Dual-Mode: WebRTC OR Energy).

        Decision Logic:
            final_speech = webrtc_result OR energy_result

        This means:
            - If EITHER WebRTC OR Energy detects speech → speech=True
            - Both must agree on silence → speech=False
            - Reduces false negatives (missed speech)

        Args:
            pcm_data: PCM audio data (16-bit signed, 8000 Hz)

        Returns:
            True if currently in speech, False otherwise
        """
        self.total_frames += 1

        # Step 1: Calculate energy (always needed for fallback)
        energy = self.calculate_rms_energy(pcm_data)

        # Step 2: WebRTC VAD detection (if available)
        webrtc_result = False
        if self.webrtc_vad:
            try:
                webrtc_result = self.webrtc_vad.is_speech(pcm_data, self.sample_rate)
                if webrtc_result:
                    self.webrtc_detections += 1
            except Exception as e:
                logger.debug("WebRTC VAD error", error=str(e))
                webrtc_result = False

        # Step 3: Energy VAD detection
        energy_result = energy >= self.energy_threshold_start
        if energy_result:
            self.energy_detections += 1

        # Step 4: Combine results (logical OR - either method triggers speech)
        combined_result = webrtc_result or energy_result

        # Step 5: Track agreement (for confidence scoring)
        if webrtc_result == energy_result:
            self.agreement_count += 1

        # Step 6: State machine (same logic, but using combined_result)
        if self.state == VADState.SILENCE:
            if combined_result:
                # Speech detected (by WebRTC or Energy or both)
                self._transition_to_speech()
                self.speech_frames = 1
                return True
            return False

        elif self.state == VADState.SPEECH:
            # For continuation, use energy_threshold_end (lower threshold)
            energy_continues = energy >= self.energy_threshold_end
            speech_continues = webrtc_result or energy_continues

            if speech_continues:
                # Continue speech
                self.speech_frames += 1
                self.total_speech_frames += 1
                self.silence_frames = 0
                return True
            else:
                # Energy dropped, start silence counter
                self.state = VADState.PENDING_END
                self.silence_frames = 1
                logger.debug("Speech pending end",
                           webrtc=webrtc_result,
                           energy=energy,
                           threshold_end=self.energy_threshold_end)
                return True

        elif self.state == VADState.PENDING_END:
            energy_continues = energy >= self.energy_threshold_end
            speech_continues = webrtc_result or energy_continues

            if speech_continues:
                # False alarm, back to speech
                self.state = VADState.SPEECH
                self.silence_frames = 0
                self.speech_frames += 1
                self.total_speech_frames += 1
                logger.debug("Speech resumed (false end)")
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

        logger.info("Speech started", segment=self.speech_segments)

        if self.on_speech_start:
            try:
                self.on_speech_start()
            except Exception as e:
                logger.error("Error in speech_start callback", error=str(e))

    def _transition_to_silence(self):
        """Transition from SPEECH/PENDING_END to SILENCE"""
        duration_s = (self.speech_frames * self.frame_duration_ms) / 1000.0

        # Validate minimum speech duration (filter out noise)
        if self.speech_frames < self.min_speech_frames_threshold:
            logger.debug("Speech too short, ignoring (likely noise)",
                        duration_s=duration_s,
                        min_duration_s=self.min_speech_duration_ms/1000)
            self.state = VADState.SILENCE
            self.speech_frames = 0
            self.silence_frames = 0
            return

        logger.info("Speech ended",
                   duration_s=duration_s,
                   frames=self.speech_frames)

        self.state = VADState.SILENCE
        self.speech_frames = 0
        self.silence_frames = 0

        if self.on_speech_end:
            try:
                self.on_speech_end()
            except Exception as e:
                logger.error("Error in speech_end callback", error=str(e))

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
            logger.warning("VAD reset while in speech state")

    def get_stats(self) -> dict:
        """
        Get VAD statistics (includes WebRTC metrics).

        Returns:
            Dict with VAD state and performance metrics
        """
        stats = {
            'state': self.state.value,
            'mode': self.webrtc_mode,
            'total_frames': self.total_frames,
            'speech_segments': self.speech_segments,
            'total_speech_frames': self.total_speech_frames,
            'current_speech_frames': self.speech_frames,
            'current_silence_frames': self.silence_frames,
            'is_speech': self.is_speech(),
        }

        # WebRTC-specific metrics
        if self.webrtc_mode == "dual-mode":
            stats.update({
                'webrtc_detections': self.webrtc_detections,
                'energy_detections': self.energy_detections,
                'agreement_count': self.agreement_count,
                'agreement_rate': (
                    self.agreement_count / self.total_frames
                    if self.total_frames > 0 else 0.0
                ),
            })

        return stats
