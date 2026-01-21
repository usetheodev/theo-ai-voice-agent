"""
RTP Packet Implementation

Migrated from LiveKit SIP - handles RTP packet parsing and generation
Based on RFC 3550
"""

import struct
from dataclasses import dataclass
from typing import Optional


@dataclass
class RTPHeader:
    """
    RTP Header (RFC 3550)

     0                   1                   2                   3
     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |V=2|P|X|  CC   |M|     PT      |       sequence number         |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |                           timestamp                           |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |           synchronization source (SSRC) identifier            |
    +=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+
    |            contributing source (CSRC) identifiers             |
    |                             ....                              |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    """
    version: int = 2  # RTP version (always 2)
    padding: bool = False
    extension: bool = False
    csrc_count: int = 0
    marker: bool = False
    payload_type: int = 0  # Codec type (0=PCMU, 8=PCMA, 111=Opus, etc.)
    sequence_number: int = 0
    timestamp: int = 0
    ssrc: int = 0  # Synchronization source
    csrc: list = None  # Contributing sources

    def __post_init__(self):
        if self.csrc is None:
            self.csrc = []

    @property
    def header_size(self) -> int:
        """Calculate header size in bytes"""
        return 12 + (len(self.csrc) * 4)


class RTPPacket:
    """RTP Packet parser and generator"""

    # RTP version
    VERSION = 2

    # Header size (fixed part)
    HEADER_SIZE = 12

    # MTU size (maximum transmission unit)
    MTU_SIZE = 1500

    def __init__(self, header: Optional[RTPHeader] = None, payload: bytes = b''):
        self.header = header or RTPHeader()
        self.payload = payload

    @classmethod
    def parse(cls, data: bytes) -> 'RTPPacket':
        """
        Parse RTP packet from bytes

        Args:
            data: Raw RTP packet bytes

        Returns:
            RTPPacket instance

        Raises:
            ValueError: If packet is invalid
        """
        if len(data) < cls.HEADER_SIZE:
            raise ValueError(f"Packet too small: {len(data)} bytes (minimum {cls.HEADER_SIZE})")

        # Parse first byte: V(2) P(1) X(1) CC(4)
        byte0 = data[0]
        version = (byte0 >> 6) & 0x03
        padding = bool((byte0 >> 5) & 0x01)
        extension = bool((byte0 >> 4) & 0x01)
        csrc_count = byte0 & 0x0F

        if version != cls.VERSION:
            raise ValueError(f"Invalid RTP version: {version} (expected {cls.VERSION})")

        # Parse second byte: M(1) PT(7)
        byte1 = data[1]
        marker = bool((byte1 >> 7) & 0x01)
        payload_type = byte1 & 0x7F

        # Parse remaining header fields
        sequence_number = struct.unpack('!H', data[2:4])[0]
        timestamp = struct.unpack('!I', data[4:8])[0]
        ssrc = struct.unpack('!I', data[8:12])[0]

        # Parse CSRC list
        csrc = []
        offset = 12
        for _ in range(csrc_count):
            if offset + 4 > len(data):
                raise ValueError("Invalid CSRC count")
            csrc.append(struct.unpack('!I', data[offset:offset+4])[0])
            offset += 4

        # Create header
        header = RTPHeader(
            version=version,
            padding=padding,
            extension=extension,
            csrc_count=csrc_count,
            marker=marker,
            payload_type=payload_type,
            sequence_number=sequence_number,
            timestamp=timestamp,
            ssrc=ssrc,
            csrc=csrc
        )

        # Extract payload (skip extension if present)
        if extension:
            if offset + 4 > len(data):
                raise ValueError("Invalid extension header")
            ext_length = struct.unpack('!H', data[offset+2:offset+4])[0] * 4
            offset += 4 + ext_length

        # Handle padding
        payload_end = len(data)
        if padding:
            if len(data) > 0:
                padding_length = data[-1]
                payload_end = len(data) - padding_length

        payload = data[offset:payload_end]

        return cls(header=header, payload=payload)

    def marshal(self) -> bytes:
        """
        Marshal RTP packet to bytes

        Returns:
            Raw RTP packet bytes
        """
        # Build first byte: V(2) P(1) X(1) CC(4)
        byte0 = (
            (self.header.version << 6) |
            (int(self.header.padding) << 5) |
            (int(self.header.extension) << 4) |
            (self.header.csrc_count & 0x0F)
        )

        # Build second byte: M(1) PT(7)
        byte1 = (
            (int(self.header.marker) << 7) |
            (self.header.payload_type & 0x7F)
        )

        # Pack fixed header
        data = struct.pack(
            '!BBHII',
            byte0,
            byte1,
            self.header.sequence_number & 0xFFFF,
            self.header.timestamp & 0xFFFFFFFF,
            self.header.ssrc & 0xFFFFFFFF
        )

        # Add CSRC list
        for csrc_id in self.header.csrc:
            data += struct.pack('!I', csrc_id & 0xFFFFFFFF)

        # Add payload
        data += self.payload

        # Add padding if needed
        if self.header.padding:
            # Pad to 4-byte boundary
            padding_needed = (4 - (len(data) % 4)) % 4
            if padding_needed == 0:
                padding_needed = 4
            data += b'\x00' * (padding_needed - 1)
            data += bytes([padding_needed])

        return data

    def __repr__(self):
        return (
            f"RTPPacket(PT={self.header.payload_type}, "
            f"seq={self.header.sequence_number}, "
            f"ts={self.header.timestamp}, "
            f"ssrc={self.header.ssrc:08x}, "
            f"payload={len(self.payload)}b)"
        )
