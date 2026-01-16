"""
Audio Codec Module

Provides:
- RTP packet parsing (RFC 3550)
- G.711 ulaw/alaw encoding/decoding
"""

from .rtp_parser import RTPParser, RTPPacket, RTPHeader
from .g711 import G711Codec

__all__ = [
    'RTPParser',
    'RTPPacket',
    'RTPHeader',
    'G711Codec',
]
