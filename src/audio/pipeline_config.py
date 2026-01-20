"""
Audio Pipeline Configuration

Centralized configuration for all audio processing components:
- Noise filters (RNNoise)
- VAD (Silero, WebRTC, Energy-based)
- Resamplers (SOXR)

Usage:
    from audio.pipeline_config import AudioPipelineConfig

    config = AudioPipelineConfig.from_env()

    # Enable/disable components
    config.rnnoise_enabled = True
    config.silero_vad_enabled = True
    config.soxr_enabled = True

    # Configure thresholds
    config.silero_confidence = 0.7
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AudioPipelineConfig:
    """
    Configuration for audio processing pipeline.

    Phase 1 Components (Quality Improvements):
    - rnnoise_filter: Noise reduction (RNN-based)
    - silero_vad: ML-based VAD (ONNX)
    - soxr_resampler: High-quality resampling
    """

    # === RNNoise Filter Config ===
    rnnoise_enabled: bool = True
    rnnoise_quality: str = "QQ"  # SOXR quality for resampling ("QQ" = Quick, lowest latency)

    # === Silero VAD Config ===
    silero_vad_enabled: bool = True
    silero_confidence: float = 0.5  # Voice confidence threshold (0.0-1.0)
    silero_start_frames: int = 3  # Frames to confirm speech start
    silero_stop_frames: int = 10  # Frames to confirm speech end
    silero_min_speech_frames: int = 5  # Minimum frames for valid speech
    silero_model_path: Optional[str] = None  # Auto-download if None

    # === SOXR Resampler Config ===
    soxr_enabled: bool = True
    soxr_quality: str = "VHQ"  # "VHQ", "HQ", "MQ", "LQ", "QQ"

    # === Legacy VAD (Fallback) ===
    # WebRTC VAD (energy-based disabled in production)
    webrtc_vad_enabled: bool = True
    webrtc_aggressiveness: int = 1  # 0-3 (1=balanced, 3=most aggressive)

    energy_vad_enabled: bool = False  # Disabled by default (WebRTC + Silero preferred)
    energy_threshold_start: float = 999999.0  # Effectively disabled
    energy_threshold_end: float = 999999.0  # Effectively disabled

    # === Timing Config ===
    vad_silence_duration_ms: int = 300  # Fast response (ML VAD decides)
    vad_min_speech_duration_ms: int = 150  # Accept short utterances

    # === Audio Buffer Config ===
    input_sample_rate: int = 8000  # G.711 ulaw @ 8kHz
    target_sample_rate: int = 16000  # ASR (Whisper) expects 16kHz
    max_buffer_duration: float = 30.0  # Max audio buffer (seconds)

    @classmethod
    def from_env(cls) -> "AudioPipelineConfig":
        """
        Load configuration from environment variables.

        Environment Variables:
            RNNOISE_ENABLED: Enable RNNoise filter (default: true)
            SILERO_VAD_ENABLED: Enable Silero VAD (default: true)
            SILERO_CONFIDENCE: Silero confidence threshold (default: 0.5)
            SOXR_ENABLED: Enable SOXR resampler (default: true)
            SOXR_QUALITY: SOXR quality (default: VHQ)

        Returns:
            AudioPipelineConfig instance
        """
        return cls(
            # RNNoise
            rnnoise_enabled=os.getenv("RNNOISE_ENABLED", "true").lower() == "true",
            rnnoise_quality=os.getenv("RNNOISE_QUALITY", "QQ"),

            # Silero VAD
            silero_vad_enabled=os.getenv("SILERO_VAD_ENABLED", "true").lower() == "true",
            silero_confidence=float(os.getenv("SILERO_CONFIDENCE", "0.5")),
            silero_start_frames=int(os.getenv("SILERO_START_FRAMES", "3")),
            silero_stop_frames=int(os.getenv("SILERO_STOP_FRAMES", "10")),
            silero_min_speech_frames=int(os.getenv("SILERO_MIN_SPEECH_FRAMES", "5")),
            silero_model_path=os.getenv("SILERO_MODEL_PATH"),

            # SOXR
            soxr_enabled=os.getenv("SOXR_ENABLED", "true").lower() == "true",
            soxr_quality=os.getenv("SOXR_QUALITY", "VHQ"),

            # Legacy VAD
            webrtc_vad_enabled=os.getenv("WEBRTC_VAD_ENABLED", "true").lower() == "true",
            webrtc_aggressiveness=int(os.getenv("WEBRTC_AGGRESSIVENESS", "1")),
            energy_vad_enabled=os.getenv("ENERGY_VAD_ENABLED", "false").lower() == "true",

            # Timing
            vad_silence_duration_ms=int(os.getenv("VAD_SILENCE_DURATION_MS", "300")),
            vad_min_speech_duration_ms=int(os.getenv("VAD_MIN_SPEECH_DURATION_MS", "150")),

            # Audio
            input_sample_rate=int(os.getenv("INPUT_SAMPLE_RATE", "8000")),
            target_sample_rate=int(os.getenv("TARGET_SAMPLE_RATE", "16000")),
            max_buffer_duration=float(os.getenv("MAX_BUFFER_DURATION", "30.0")),
        )

    def to_dict(self) -> dict:
        """Convert config to dictionary"""
        return {
            'rnnoise': {
                'enabled': self.rnnoise_enabled,
                'quality': self.rnnoise_quality,
            },
            'silero_vad': {
                'enabled': self.silero_vad_enabled,
                'confidence': self.silero_confidence,
                'start_frames': self.silero_start_frames,
                'stop_frames': self.silero_stop_frames,
                'min_speech_frames': self.silero_min_speech_frames,
            },
            'soxr': {
                'enabled': self.soxr_enabled,
                'quality': self.soxr_quality,
            },
            'legacy_vad': {
                'webrtc_enabled': self.webrtc_vad_enabled,
                'energy_enabled': self.energy_vad_enabled,
            },
            'audio': {
                'input_sample_rate': self.input_sample_rate,
                'target_sample_rate': self.target_sample_rate,
            },
        }
