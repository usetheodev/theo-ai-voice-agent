"""VAD (Voice Activity Detection) providers.

Available providers:
- SileroVADProvider: Silero VAD model (fast, accurate, MIT license)
- WebRTCVADProvider: WebRTC VAD (lightweight, simple)
- NoiseAwareVAD: Wrapper that calibrates threshold from ambient noise
"""

from voice_pipeline.providers.vad.silero import (
    SileroVADProvider,
    SileroVADConfig,
)
from voice_pipeline.providers.vad.webrtc import (
    WebRTCVADProvider,
    WebRTCVADConfig,
)
from voice_pipeline.providers.vad.noise_aware import (
    NoiseAwareVAD,
    NoiseFloorConfig,
)

__all__ = [
    "SileroVADProvider",
    "SileroVADConfig",
    "WebRTCVADProvider",
    "WebRTCVADConfig",
    "NoiseAwareVAD",
    "NoiseFloorConfig",
]
