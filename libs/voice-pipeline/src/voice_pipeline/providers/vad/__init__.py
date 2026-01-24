"""VAD (Voice Activity Detection) providers.

Available providers:
- SileroVADProvider: Silero VAD model (fast, accurate, MIT license)
- WebRTCVADProvider: WebRTC VAD (lightweight, simple)
"""

from voice_pipeline.providers.vad.silero import (
    SileroVADProvider,
    SileroVADConfig,
)
from voice_pipeline.providers.vad.webrtc import (
    WebRTCVADProvider,
    WebRTCVADConfig,
)

__all__ = [
    "SileroVADProvider",
    "SileroVADConfig",
    "WebRTCVADProvider",
    "WebRTCVADConfig",
]
