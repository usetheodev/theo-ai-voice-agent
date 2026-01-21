"""
SDP (Session Description Protocol) Parser and Generator

Migrated from LiveKit SIP - handles SDP negotiation for RTP media
"""

import re
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass, field


@dataclass
class SDPCodec:
    """SDP Media Codec"""
    payload_type: int
    name: str
    clock_rate: int
    channels: int = 1
    fmtp: Optional[str] = None


@dataclass
class SDPMedia:
    """SDP Media Description (m= line)"""
    media_type: str  # "audio" or "video"
    port: int
    protocol: str = "RTP/AVP"
    codecs: List[SDPCodec] = field(default_factory=list)
    direction: str = "sendrecv"  # sendrecv, sendonly, recvonly, inactive


@dataclass
class SDP:
    """
    Session Description Protocol

    Represents a complete SDP offer/answer
    """
    # Session information
    version: int = 0
    origin: str = ""
    session_name: str = "AI Voice Agent"
    connection_address: str = "0.0.0.0"

    # Timing
    time_start: int = 0
    time_stop: int = 0

    # Media streams
    media: List[SDPMedia] = field(default_factory=list)

    # Raw SDP for reference
    raw: str = ""


class SDPParser:
    """
    SDP Parser

    Parses SDP from SIP INVITE/200 OK
    """

    # Common codecs
    CODEC_MAP = {
        0: ("PCMU", 8000, 1),
        8: ("PCMA", 8000, 1),
        9: ("G722", 8000, 1),
        18: ("G729", 8000, 1),
        101: ("telephone-event", 8000, 1),  # DTMF
        111: ("opus", 48000, 2),
    }

    @classmethod
    def parse(cls, sdp_text: str) -> SDP:
        """Parse SDP text"""
        sdp = SDP(raw=sdp_text)
        lines = sdp_text.strip().split('\n')

        current_media = None

        for line in lines:
            line = line.strip()
            if not line or '=' not in line:
                continue

            field, value = line.split('=', 1)

            if field == 'v':
                sdp.version = int(value)

            elif field == 'o':
                sdp.origin = value

            elif field == 's':
                sdp.session_name = value

            elif field == 'c':
                # c=IN IP4 192.168.1.1
                parts = value.split()
                if len(parts) >= 3:
                    sdp.connection_address = parts[2]

            elif field == 't':
                # t=0 0
                parts = value.split()
                if len(parts) >= 2:
                    sdp.time_start = int(parts[0])
                    sdp.time_stop = int(parts[1])

            elif field == 'm':
                # m=audio 10000 RTP/AVP 0 8 101
                current_media = cls._parse_media_line(value)
                sdp.media.append(current_media)

            elif field == 'a' and current_media:
                # a=rtpmap:111 opus/48000/2
                # a=fmtp:111 ...
                # a=sendrecv
                cls._parse_attribute(value, current_media)

        return sdp

    @classmethod
    def _parse_media_line(cls, value: str) -> SDPMedia:
        """Parse m= line"""
        # m=audio 10000 RTP/AVP 0 8 101
        parts = value.split()

        if len(parts) < 4:
            raise ValueError(f"Invalid m= line: {value}")

        media_type = parts[0]
        port = int(parts[1])
        protocol = parts[2]
        payload_types = [int(pt) for pt in parts[3:]]

        media = SDPMedia(
            media_type=media_type,
            port=port,
            protocol=protocol
        )

        # Add codecs from payload types
        for pt in payload_types:
            codec_info = cls.CODEC_MAP.get(pt)
            if codec_info:
                name, clock_rate, channels = codec_info
                media.codecs.append(SDPCodec(
                    payload_type=pt,
                    name=name,
                    clock_rate=clock_rate,
                    channels=channels
                ))
            else:
                # Unknown codec, add placeholder
                media.codecs.append(SDPCodec(
                    payload_type=pt,
                    name=f"unknown-{pt}",
                    clock_rate=8000,
                    channels=1
                ))

        return media

    @classmethod
    def _parse_attribute(cls, value: str, media: SDPMedia):
        """Parse a= line"""
        if value.startswith('rtpmap:'):
            # a=rtpmap:111 opus/48000/2
            cls._parse_rtpmap(value, media)

        elif value.startswith('fmtp:'):
            # a=fmtp:111 minptime=10;useinbandfec=1
            cls._parse_fmtp(value, media)

        elif value in ('sendrecv', 'sendonly', 'recvonly', 'inactive'):
            media.direction = value

    @classmethod
    def _parse_rtpmap(cls, value: str, media: SDPMedia):
        """Parse rtpmap attribute"""
        # rtpmap:111 opus/48000/2
        match = re.match(r'rtpmap:(\d+)\s+([^/]+)/(\d+)(?:/(\d+))?', value)
        if not match:
            return

        pt = int(match.group(1))
        name = match.group(2)
        clock_rate = int(match.group(3))
        channels = int(match.group(4)) if match.group(4) else 1

        # Update codec in media
        for codec in media.codecs:
            if codec.payload_type == pt:
                codec.name = name
                codec.clock_rate = clock_rate
                codec.channels = channels
                break

    @classmethod
    def _parse_fmtp(cls, value: str, media: SDPMedia):
        """Parse fmtp attribute"""
        # fmtp:111 minptime=10;useinbandfec=1
        match = re.match(r'fmtp:(\d+)\s+(.+)', value)
        if not match:
            return

        pt = int(match.group(1))
        fmtp = match.group(2)

        # Update codec in media
        for codec in media.codecs:
            if codec.payload_type == pt:
                codec.fmtp = fmtp
                break


class SDPGenerator:
    """
    SDP Generator

    Generates SDP for 200 OK response
    """

    @classmethod
    def generate(cls, local_ip: str, local_port: int,
                 codecs: List[str], session_id: Optional[str] = None) -> str:
        """
        Generate SDP offer/answer

        Args:
            local_ip: Local IP address
            local_port: Local RTP port
            codecs: List of codec names (e.g., ["PCMU", "PCMA", "opus"])
            session_id: Session ID (default: timestamp)

        Returns:
            SDP string
        """
        import time

        if session_id is None:
            session_id = str(int(time.time()))

        # Build codec list
        codec_list = []
        payload_types = []

        for codec_name in codecs:
            codec_name_upper = codec_name.upper()
            for pt, (name, clock_rate, channels) in SDPParser.CODEC_MAP.items():
                if name.upper() == codec_name_upper:
                    codec_list.append((pt, name, clock_rate, channels))
                    payload_types.append(str(pt))
                    break

        if not codec_list:
            # Default to PCMU
            codec_list = [(0, "PCMU", 8000, 1)]
            payload_types = ["0"]

        # Generate SDP
        sdp_lines = [
            "v=0",
            f"o=- {session_id} {session_id} IN IP4 {local_ip}",
            "s=AI Voice Agent",
            f"c=IN IP4 {local_ip}",
            "t=0 0",
            f"m=audio {local_port} RTP/AVP {' '.join(payload_types)}",
        ]

        # Add rtpmap for each codec
        for pt, name, clock_rate, channels in codec_list:
            if channels > 1:
                sdp_lines.append(f"a=rtpmap:{pt} {name}/{clock_rate}/{channels}")
            else:
                sdp_lines.append(f"a=rtpmap:{pt} {name}/{clock_rate}")

        # Add direction
        sdp_lines.append("a=sendrecv")

        return '\r\n'.join(sdp_lines) + '\r\n'


def negotiate_codec(offer_sdp: str, supported_codecs: List[str]) -> Optional[str]:
    """
    Negotiate codec from SDP offer

    Returns the first matching codec name, or None if no match
    """
    sdp = SDPParser.parse(offer_sdp)

    # Find audio media
    audio_media = None
    for media in sdp.media:
        if media.media_type == 'audio':
            audio_media = media
            break

    if not audio_media:
        return None

    # Find first matching codec
    for codec in audio_media.codecs:
        if codec.name.upper() in [c.upper() for c in supported_codecs]:
            return codec.name

    return None


def extract_remote_address(offer_sdp: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Extract remote RTP address from SDP

    Returns: (ip, port) or (None, None) if not found
    """
    sdp = SDPParser.parse(offer_sdp)

    # Find audio media
    for media in sdp.media:
        if media.media_type == 'audio' and media.port > 0:
            return sdp.connection_address, media.port

    return None, None
