"""Interruption strategy providers.

Available strategies:
- ImmediateInterruption: Stop TTS instantly on user speech.
- GracefulInterruption: Finish current chunk then stop.
- BackchannelAwareInterruption: Distinguish backchannels from real interruptions.
"""

from .immediate import ImmediateInterruption
from .graceful import GracefulInterruption
from .backchannel import BackchannelAwareInterruption

__all__ = [
    "ImmediateInterruption",
    "GracefulInterruption",
    "BackchannelAwareInterruption",
]
