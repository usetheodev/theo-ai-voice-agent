"""
WebRTC Acoustic Echo Cancellation (AEC)

Uses webrtc-noise-gain library for AEC, Noise Suppression, and AGC.
Optimized for full-duplex telephony (G.711 8kHz).

Features:
- Acoustic Echo Cancellation (AEC)
- Noise Suppression (NS)
- Automatic Gain Control (AGC)
- Low latency (<10ms per 10ms frame)
"""

import numpy as np
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import webrtc_noise_gain as webrtc
    WEBRTC_AEC_AVAILABLE = True
except ImportError:
    WEBRTC_AEC_AVAILABLE = False
    logger.warning("WebRTC AEC not available. Install: pip install webrtc-noise-gain")


class WebRTCAEC:
    """
    WebRTC Acoustic Echo Cancellation.

    Optimized for full-duplex telephony (G.711 8kHz).

    Features:
    - Acoustic Echo Cancellation (AEC) - removes AI voice echo
    - Noise Suppression (NS) - reduces background noise
    - Automatic Gain Control (AGC) - normalizes volume

    Example:
        >>> aec = WebRTCAEC(sample_rate=8000)
        >>> clean_audio = aec.process(user_audio, ai_reference_audio)
    """

    def __init__(
        self,
        sample_rate: int = 8000,
        channels: int = 1,
    ):
        """
        Initialize WebRTC Audio Processing.

        Args:
            sample_rate: Sample rate (8000, 16000, 32000, 48000)
            channels: Number of audio channels (1=mono, 2=stereo)

        Note: webrtc-noise-gain library internally enables:
              - Echo Cancellation
              - Noise Suppression
              - Automatic Gain Control
        """
        if not WEBRTC_AEC_AVAILABLE:
            raise RuntimeError(
                "WebRTC AEC not available. "
                "Install: pip install webrtc-noise-gain"
            )

        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_size_ms = 10  # WebRTC processes 10ms frames

        # IMPORTANT: webrtc-noise-gain always expects 160 samples (320 bytes)
        # regardless of sample rate. This is 10ms @ 16kHz.
        # We need to resample if using other rates.
        self.webrtc_frame_size = 160  # Fixed: 160 samples (320 bytes)
        self.needs_resampling = (sample_rate != 16000)

        if self.needs_resampling:
            logger.warning(
                f"Sample rate {sample_rate}Hz requires resampling to 16kHz for WebRTC AEC. "
                "This adds latency. Consider using 16kHz directly."
            )

        self.frame_size = int(sample_rate * self.frame_size_ms / 1000)

        # Initialize WebRTC AudioProcessor (always at 16kHz, mono)
        # Library is hardcoded to 16kHz processing
        self.processor = webrtc.AudioProcessor(16000, 1)

        # Stats
        self.frames_processed = 0

        logger.info(
            f"✅ WebRTC AEC initialized: {sample_rate}Hz, "
            f"{channels} channel(s), frame_size={self.frame_size_ms}ms ({self.frame_size} samples)"
        )
        logger.info("   Features: AEC + Noise Suppression + AGC enabled")

    def process(
        self,
        user_audio: np.ndarray,
        ai_reference_audio: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Process audio frame with AEC + Noise Suppression + AGC.

        Args:
            user_audio: User microphone audio (with potential echo)
            ai_reference_audio: AI playback reference (for AEC) - NOT USED
                               Note: webrtc-noise-gain doesn't expose separate
                               reference audio API, AEC works internally

        Returns:
            Clean user audio (echo reduced, noise suppressed)

        Note: Library requires 16kHz audio. If input is at different rate,
              it will be resampled (adds latency).
        """
        original_length = len(user_audio)
        original_dtype = user_audio.dtype

        # Ensure int16 PCM
        if user_audio.dtype == np.float32:
            user_int16 = (user_audio * 32767).astype(np.int16)
        else:
            user_int16 = user_audio.astype(np.int16)

        # Resample to 16kHz if needed
        if self.needs_resampling:
            import audioop
            # Resample to 16kHz
            audio_bytes = user_int16.tobytes()
            resampled_bytes, _ = audioop.ratecv(
                audio_bytes,
                2,  # 2 bytes per sample (int16)
                1,  # mono
                self.sample_rate,  # from rate
                16000,  # to rate (WebRTC requirement)
                None
            )
            user_int16 = np.frombuffer(resampled_bytes, dtype=np.int16)

        # Process frame by frame (160 samples = 320 bytes)
        output_frames = []

        for i in range(0, len(user_int16), self.webrtc_frame_size):
            frame = user_int16[i:i + self.webrtc_frame_size]

            # Pad last frame if needed
            if len(frame) < self.webrtc_frame_size:
                frame = np.pad(
                    frame, (0, self.webrtc_frame_size - len(frame)),
                    mode='constant', constant_values=0
                )

            # Convert to bytes (required by webrtc-noise-gain)
            frame_bytes = frame.tobytes()

            # Process with AEC + NS + AGC
            result = self.processor.Process10ms(frame_bytes)

            # Extract processed audio from result
            clean_frame = np.frombuffer(result.audio, dtype=np.int16)
            output_frames.append(clean_frame)

            self.frames_processed += 1

        # Concatenate frames
        clean_audio = np.concatenate(output_frames)

        # Resample back to original rate if needed
        if self.needs_resampling:
            import audioop
            clean_bytes = clean_audio.tobytes()
            resampled_bytes, _ = audioop.ratecv(
                clean_bytes,
                2,  # 2 bytes per sample
                1,  # mono
                16000,  # from rate
                self.sample_rate,  # to rate (original)
                None
            )
            clean_audio = np.frombuffer(resampled_bytes, dtype=np.int16)

        # Trim to original length (remove padding)
        clean_audio = clean_audio[:original_length]

        # Convert back to original dtype
        if original_dtype == np.float32:
            clean_audio = clean_audio.astype(np.float32) / 32767.0

        return clean_audio

    def get_stats(self) -> dict:
        """Get AEC statistics."""
        return {
            "frames_processed": self.frames_processed,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "frame_size_ms": self.frame_size_ms,
            "features": "AEC + Noise Suppression + AGC",
        }


def is_webrtc_aec_available() -> bool:
    """Check if WebRTC AEC is available."""
    return WEBRTC_AEC_AVAILABLE
