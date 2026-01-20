"""
Silero VAD - ML-based Voice Activity Detection

ONNX-based VAD using Silero pre-trained model.
90%+ accuracy, supports 8kHz and 16kHz.
"""

from .silero_vad import SileroVAD

__all__ = ['SileroVAD']
