"""
Audio processing package

Modules:
- buffer: Audio buffer with resampling
- vad: Voice Activity Detection
- resampling: Audio resampling utilities
"""

from .buffer import AudioBuffer
from .vad import VoiceActivityDetector, VADState
from .resampling import resample_audio, resample_to_bytes

__all__ = [
    'AudioBuffer',
    'VoiceActivityDetector',
    'VADState',
    'resample_audio',
    'resample_to_bytes',
]
