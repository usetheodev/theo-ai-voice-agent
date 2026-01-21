"""
Audio Buffer Manager

Accumulates PCM audio frames for processing by ASR.
Handles:
- Frame accumulation
- Resampling (8kHz → 16kHz for Whisper)
- Voice Activity Detection integration
- Buffer export to WAV file
"""

import numpy as np
import io
import wave
from typing import Optional

from ..common.logging import get_logger
from .resampling import resample_audio

logger = get_logger('audio.buffer')


class AudioBuffer:
    """
    Buffer for accumulating PCM audio samples

    Usage:
        buffer = AudioBuffer(sample_rate=8000, target_rate=16000)

        # Add frames as they arrive
        buffer.add_frame(pcm_data)

        # When VAD detects end of speech
        audio_data = buffer.get_audio()
        wav_file = buffer.export_wav()
    """

    def __init__(self,
                 sample_rate: int = 8000,
                 target_rate: int = 16000,
                 channels: int = 1,
                 max_duration_seconds: float = 30.0):
        """
        Initialize audio buffer

        Args:
            sample_rate: Input sample rate (from G.711 decoder)
            target_rate: Target sample rate (for Whisper)
            channels: Number of audio channels (1=mono)
            max_duration_seconds: Maximum buffer duration
        """
        self.sample_rate = sample_rate
        self.target_rate = target_rate
        self.channels = channels
        self.max_duration_seconds = max_duration_seconds
        self.max_samples = int(sample_rate * max_duration_seconds)

        # Buffer storage (list of numpy arrays)
        self.frames = []
        self.total_samples = 0

        # Statistics
        self.frames_added = 0
        self.times_cleared = 0

        logger.info("AudioBuffer initialized",
                   sample_rate=sample_rate,
                   target_rate=target_rate,
                   max_duration=f"{max_duration_seconds}s")

    def add_frame(self, pcm_data: bytes) -> bool:
        """
        Add PCM frame to buffer

        Args:
            pcm_data: PCM data (16-bit signed little-endian)

        Returns:
            True if added, False if buffer full
        """
        try:
            # Convert bytes to numpy array
            samples = np.frombuffer(pcm_data, dtype=np.int16)

            # Check if buffer would overflow
            if self.total_samples + len(samples) > self.max_samples:
                logger.warning("Buffer full, rejecting frame",
                             current_samples=self.total_samples,
                             max_samples=self.max_samples)
                return False

            # Add to buffer
            self.frames.append(samples)
            self.total_samples += len(samples)
            self.frames_added += 1

            return True

        except Exception as e:
            logger.error("Error adding frame", error=str(e))
            return False

    def get_duration(self) -> float:
        """Get current buffer duration in seconds"""
        return self.total_samples / self.sample_rate if self.total_samples > 0 else 0.0

    def is_empty(self) -> bool:
        """Check if buffer is empty"""
        return self.total_samples == 0

    def get_audio(self, resample: bool = True) -> Optional[np.ndarray]:
        """
        Get accumulated audio as numpy array

        Args:
            resample: If True, resample to target_rate

        Returns:
            numpy array of audio samples (int16 or float32 if resampled)
        """
        if self.is_empty():
            return None

        try:
            # Concatenate all frames
            audio = np.concatenate(self.frames)

            # Resample if needed
            if resample and self.sample_rate != self.target_rate:
                audio = resample_audio(audio, self.sample_rate, self.target_rate)

            return audio

        except Exception as e:
            logger.error("Error getting audio", error=str(e))
            return None

    def export_wav(self, resample: bool = True) -> Optional[bytes]:
        """
        Export buffer as WAV file (in memory)

        Args:
            resample: If True, resample to target_rate

        Returns:
            WAV file bytes or None
        """
        audio = self.get_audio(resample=resample)
        if audio is None:
            return None

        try:
            # Create in-memory WAV file
            wav_buffer = io.BytesIO()

            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(2)  # 16-bit = 2 bytes
                wav_file.setframerate(self.target_rate if resample else self.sample_rate)
                wav_file.writeframes(audio.tobytes())

            wav_bytes = wav_buffer.getvalue()

            logger.debug("Exported WAV", size_bytes=len(wav_bytes))

            return wav_bytes

        except Exception as e:
            logger.error("WAV export error", error=str(e))
            return None

    def save_wav(self, filename: str, resample: bool = True) -> bool:
        """
        Save buffer as WAV file to disk

        Args:
            filename: Output filename
            resample: If True, resample to target_rate

        Returns:
            True if successful
        """
        wav_bytes = self.export_wav(resample=resample)
        if wav_bytes is None:
            return False

        try:
            with open(filename, 'wb') as f:
                f.write(wav_bytes)

            logger.info("Saved WAV",
                       filename=filename,
                       duration=f"{self.get_duration():.2f}s")
            return True

        except Exception as e:
            logger.error("Error saving WAV", error=str(e))
            return False

    def clear(self):
        """Clear buffer"""
        self.frames = []
        self.total_samples = 0
        self.times_cleared += 1
        logger.debug("Buffer cleared")

    def get_stats(self) -> dict:
        """Get buffer statistics"""
        return {
            'total_samples': self.total_samples,
            'duration_seconds': self.get_duration(),
            'frames_added': self.frames_added,
            'times_cleared': self.times_cleared,
            'sample_rate': self.sample_rate,
            'target_rate': self.target_rate,
            'is_empty': self.is_empty()
        }
