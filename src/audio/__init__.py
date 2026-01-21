"""
Audio Module - Audio Processing Pipeline

Public API for audio processing components
"""

from .codec import G711Codec
from .buffer import AudioBuffer
from .vad import VoiceActivityDetector, VADState
from .resampling import resample_audio, resample_to_bytes, calculate_duration
from .stream import AudioStream, RTPAudioStream
from .pipeline import AudioPipeline, AudioPipelineConfig

__all__ = [
    # Codec
    'G711Codec',

    # Buffer
    'AudioBuffer',

    # VAD
    'VoiceActivityDetector',
    'VADState',

    # Resampling
    'resample_audio',
    'resample_to_bytes',
    'calculate_duration',

    # Stream
    'AudioStream',
    'RTPAudioStream',

    # Pipeline
    'AudioPipeline',
    'AudioPipelineConfig',
]
