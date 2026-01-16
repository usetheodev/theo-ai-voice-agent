"""
RTP (Real-time Transport Protocol) Parser

Parses RTP packets according to RFC 3550:
https://tools.ietf.org/html/rfc3550

RTP Header Format (12 bytes minimum):

 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|V=2|P|X|  CC   |M|     PT      |       sequence number         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           timestamp                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|           synchronization source (SSRC) identifier            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|            contributing source (CSRC) identifiers             |
|                             ....                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

Where:
- V (version): 2 bits - Always 2 for RTP
- P (padding): 1 bit - If set, padding bytes at end
- X (extension): 1 bit - If set, extension header present
- CC (CSRC count): 4 bits - Number of CSRC identifiers
- M (marker): 1 bit - Interpretation depends on payload type
- PT (payload type): 7 bits - Audio/video codec (0 = PCMU/G.711 ulaw)
- Sequence number: 16 bits - Increments by 1 for each packet
- Timestamp: 32 bits - Sampling instant (increments by 160 for 20ms @ 8kHz)
- SSRC: 32 bits - Synchronization source identifier
"""

import struct
import logging
from dataclasses import dataclass
from typing import Optional


@dataclass
class RTPHeader:
    """Parsed RTP header information"""
    version: int  # 2 bits
    padding: bool  # 1 bit
    extension: bool  # 1 bit
    csrc_count: int  # 4 bits
    marker: bool  # 1 bit
    payload_type: int  # 7 bits
    sequence_number: int  # 16 bits
    timestamp: int  # 32 bits
    ssrc: int  # 32 bits
    csrc_list: list  # Variable length


@dataclass
class RTPPacket:
    """Complete RTP packet"""
    header: RTPHeader
    payload: bytes


class RTPParser:
    """
    Parser for RTP packets

    Usage:
        parser = RTPParser()
        packet = parser.parse(raw_data)
        print(f"Sequence: {packet.header.sequence_number}")
        print(f"Payload: {len(packet.payload)} bytes")
    """

    def __init__(self):
        self.logger = logging.getLogger("ai-voice-agent.rtp.parser")

        # Statistics
        self.packets_parsed = 0
        self.parse_errors = 0

        # Track sequence for loss detection
        self.last_sequence = None
        self.packets_lost = 0

    def parse(self, data: bytes) -> Optional[RTPPacket]:
        """
        Parse RTP packet from raw bytes

        Args:
            data: Raw RTP packet bytes

        Returns:
            RTPPacket object or None if parse failed
        """
        try:
            if len(data) < 12:
                self.logger.error(f"RTP packet too short: {len(data)} bytes (minimum 12)")
                self.parse_errors += 1
                return None

            # Parse fixed header (first 12 bytes)
            # Format: !BBHII
            # B = unsigned char (1 byte)
            # H = unsigned short (2 bytes)
            # I = unsigned int (4 bytes)
            # ! = network byte order (big-endian)

            byte0, byte1, sequence, timestamp, ssrc = struct.unpack('!BBHII', data[:12])

            # Parse byte 0: V(2) P(1) X(1) CC(4)
            version = (byte0 >> 6) & 0x03
            padding = bool((byte0 >> 5) & 0x01)
            extension = bool((byte0 >> 4) & 0x01)
            csrc_count = byte0 & 0x0F

            # Parse byte 1: M(1) PT(7)
            marker = bool((byte1 >> 7) & 0x01)
            payload_type = byte1 & 0x7F

            # Validate version
            if version != 2:
                self.logger.warning(f"Invalid RTP version: {version} (expected 2)")
                self.parse_errors += 1
                return None

            # Parse CSRC identifiers (if any)
            csrc_list = []
            header_size = 12 + (csrc_count * 4)

            if len(data) < header_size:
                self.logger.error(f"Packet too short for CSRC list: {len(data)} < {header_size}")
                self.parse_errors += 1
                return None

            if csrc_count > 0:
                for i in range(csrc_count):
                    offset = 12 + (i * 4)
                    csrc = struct.unpack('!I', data[offset:offset+4])[0]
                    csrc_list.append(csrc)

            # TODO: Handle extension header if X bit is set
            # For now, we ignore it and assume payload starts after CSRC

            # Extract payload
            payload = data[header_size:]

            # Build header object
            header = RTPHeader(
                version=version,
                padding=padding,
                extension=extension,
                csrc_count=csrc_count,
                marker=marker,
                payload_type=payload_type,
                sequence_number=sequence,
                timestamp=timestamp,
                ssrc=ssrc,
                csrc_list=csrc_list
            )

            # Build packet object
            packet = RTPPacket(header=header, payload=payload)

            # Update statistics
            self.packets_parsed += 1

            # Detect packet loss (sequence number jumps)
            if self.last_sequence is not None:
                expected = (self.last_sequence + 1) & 0xFFFF  # Wrap at 16 bits
                if sequence != expected:
                    # Calculate loss (handle wrap-around)
                    if sequence > expected:
                        lost = sequence - expected
                    else:
                        lost = (0xFFFF - expected) + sequence + 1

                    self.packets_lost += lost
                    self.logger.debug(f"Packet loss detected: expected {expected}, got {sequence} (lost {lost})")

            self.last_sequence = sequence

            return packet

        except struct.error as e:
            self.logger.error(f"RTP parsing error: {e}")
            self.parse_errors += 1
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error parsing RTP: {e}", exc_info=True)
            self.parse_errors += 1
            return None

    def get_stats(self) -> dict:
        """Get parser statistics"""
        return {
            'packets_parsed': self.packets_parsed,
            'parse_errors': self.parse_errors,
            'packets_lost': self.packets_lost,
            'loss_rate': self.packets_lost / self.packets_parsed if self.packets_parsed > 0 else 0.0
        }
