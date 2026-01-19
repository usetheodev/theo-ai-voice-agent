"""
Audio Codec Module

Provides:
- RTP packet parsing (RFC 3550)
- RTP packet building (RFC 3550)
- G.711 ulaw/alaw encoding/decoding
"""

from .rtp_parser import RTPParser, RTPPacket, RTPHeader, RTPBuilder
from .g711 import G711Codec

__all__ = [
    'RTPParser',
    'RTPPacket',
    'RTPHeader',
    'RTPBuilder',
    'G711Codec',
]
