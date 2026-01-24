"""VAD (Voice Activity Detection) providers."""

from .silero import SileroVAD
from .energy import EnergyVAD

__all__ = ["SileroVAD", "EnergyVAD"]
