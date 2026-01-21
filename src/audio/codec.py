"""
G.711 Codec (A-law and μ-law)

ITU-T G.711 is a narrow-band audio codec originally designed for telephony.
It provides toll-quality audio at 64 kbit/s.

Two main companding algorithms:
- **μ-law (mu-law/ulaw)**: Used in North America and Japan
- **A-law (alaw)**: Used in Europe and rest of world

Characteristics:
- Sample rate: 8000 Hz
- Sample size: 8 bits (companded) → 16 bits (linear PCM)
- Bitrate: 64 kbit/s
- Typical frame: 160 samples = 20ms @ 8kHz

Python's audioop module provides built-in encoding/decoding.
"""

import audioop
from typing import Optional
import numpy as np

from ..common.logging import get_logger

logger = get_logger('audio.codec')


class G711Codec:
    """
    G.711 Audio Codec (μ-law and A-law)

    Usage:
        codec = G711Codec(law='ulaw')

        # Decode RTP payload to PCM
        pcm_data = codec.decode(rtp_payload)

        # Encode PCM to G.711 for sending
        g711_data = codec.encode(pcm_data)
    """

    def __init__(self, law: str = 'ulaw'):
        """
        Initialize G.711 codec

        Args:
            law: 'ulaw' (μ-law) or 'alaw' (A-law)
        """
        if law not in ['ulaw', 'alaw']:
            raise ValueError(f"Invalid law: {law}. Must be 'ulaw' or 'alaw'")

        self.law = law

        # Statistics
        self.frames_decoded = 0
        self.frames_encoded = 0
        self.bytes_decoded = 0
        self.bytes_encoded = 0

        logger.info("G.711 codec initialized", law=law.upper())

    def decode(self, data: bytes) -> Optional[bytes]:
        """
        Decode G.711 to linear PCM (16-bit signed)

        Args:
            data: G.711 encoded bytes (8-bit samples)

        Returns:
            PCM data (16-bit signed little-endian) or None on error
        """
        try:
            if not data:
                return None

            # Decode using audioop
            # Width=2 means output will be 16-bit (2 bytes per sample)
            if self.law == 'ulaw':
                pcm_data = audioop.ulaw2lin(data, 2)  # μ-law to linear
            else:  # alaw
                pcm_data = audioop.alaw2lin(data, 2)  # A-law to linear

            # Update statistics
            self.frames_decoded += 1
            self.bytes_decoded += len(data)

            return pcm_data

        except Exception as e:
            logger.error("Decode error", error=str(e))
            return None

    def encode(self, pcm_data: bytes) -> Optional[bytes]:
        """
        Encode linear PCM (16-bit signed) to G.711

        Args:
            pcm_data: PCM data (16-bit signed little-endian)

        Returns:
            G.711 encoded bytes (8-bit samples) or None on error
        """
        try:
            if not pcm_data:
                return None

            # Encode using audioop
            # Width=2 means input is 16-bit (2 bytes per sample)
            if self.law == 'ulaw':
                g711_data = audioop.lin2ulaw(pcm_data, 2)  # Linear to μ-law
            else:  # alaw
                g711_data = audioop.lin2alaw(pcm_data, 2)  # Linear to A-law

            # Update statistics
            self.frames_encoded += 1
            self.bytes_encoded += len(g711_data)

            return g711_data

        except Exception as e:
            logger.error("Encode error", error=str(e))
            return None

    def decode_to_numpy(self, data: bytes, dtype=np.int16) -> Optional[np.ndarray]:
        """
        Decode G.711 to numpy array (useful for DSP/analysis)

        Args:
            data: G.711 encoded bytes
            dtype: numpy dtype (default: np.int16)

        Returns:
            numpy array of audio samples or None on error
        """
        pcm_data = self.decode(data)
        if pcm_data is None:
            return None

        try:
            # Convert bytes to numpy array
            # PCM is 16-bit little-endian signed
            samples = np.frombuffer(pcm_data, dtype=np.int16)

            if dtype != np.int16:
                # Convert to requested dtype (e.g., float32)
                samples = samples.astype(dtype)

                # Normalize to [-1.0, 1.0] if float
                if dtype in [np.float32, np.float64]:
                    samples = samples / 32768.0

            return samples

        except Exception as e:
            logger.error("Numpy conversion error", error=str(e))
            return None

    def encode_from_numpy(self, samples: np.ndarray) -> Optional[bytes]:
        """
        Encode numpy array to G.711

        Args:
            samples: numpy array of audio samples

        Returns:
            G.711 encoded bytes or None on error
        """
        try:
            # Convert to int16 if needed
            if samples.dtype in [np.float32, np.float64]:
                # Denormalize from [-1.0, 1.0] to int16 range
                samples = (samples * 32768.0).astype(np.int16)
            elif samples.dtype != np.int16:
                samples = samples.astype(np.int16)

            # Convert numpy array to bytes
            pcm_data = samples.tobytes()

            # Encode to G.711
            return self.encode(pcm_data)

        except Exception as e:
            logger.error("Numpy encode error", error=str(e))
            return None

    def get_stats(self) -> dict:
        """Get codec statistics"""
        return {
            'law': self.law,
            'frames_decoded': self.frames_decoded,
            'frames_encoded': self.frames_encoded,
            'bytes_decoded': self.bytes_decoded,
            'bytes_encoded': self.bytes_encoded,
            'compression_ratio': self.bytes_encoded / self.bytes_decoded if self.bytes_decoded > 0 else 0.0
        }
