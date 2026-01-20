"""
Audio Filters - Noise reduction and audio enhancement

Available filters:
- RNNoiseFilter: RNN-based noise suppression (48kHz)
"""

from .rnnoise_filter import RNNoiseFilter

__all__ = ['RNNoiseFilter']
