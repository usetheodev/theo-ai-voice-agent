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

        # Track sequence for loss detection (per SSRC)
        self.last_sequence = None
        self.last_ssrc = None
        self.packets_lost = 0
        self.packets_received_current_stream = 0  # Count packets in current stream

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

            # Detect SSRC change (new stream or source change)
            if self.last_ssrc is not None and self.last_ssrc != ssrc:
                self.logger.debug(f"SSRC changed: {self.last_ssrc} → {ssrc}, resetting loss tracking")
                self.last_sequence = None
                self.packets_received_current_stream = 0

            # Detect packet loss (sequence number jumps)
            # Only track loss after we have a baseline (ignore first packet)
            if self.last_sequence is not None and self.last_ssrc == ssrc:
                expected = (self.last_sequence + 1) & 0xFFFF  # Wrap at 16 bits

                # Allow small reordering (±5 packets) - not considered loss
                seq_diff = (sequence - expected) & 0xFFFF

                if seq_diff > 0 and seq_diff < 0x7FFF:  # Forward jump (lost packets)
                    # Only count as loss if jump is > 5 packets (avoid false positives from reordering)
                    if seq_diff <= 100:  # Reasonable gap (not a reset)
                        self.packets_lost += seq_diff
                        self.logger.debug(f"Packet loss detected: expected {expected}, got {sequence} (lost {seq_diff})")
                elif seq_diff > 0x7FFF:  # Backward (out of order) or wrap-around
                    # This is likely out-of-order delivery, don't count as loss
                    self.logger.debug(f"Out-of-order packet: expected {expected}, got {sequence}")

            self.last_sequence = sequence
            self.last_ssrc = ssrc
            self.packets_received_current_stream += 1

            return packet

        except struct.error as e:
            self.logger.error(f"RTP parsing error: {e}")
            self.parse_errors += 1
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error parsing RTP: {e}", exc_info=True)
            self.parse_errors += 1
            return None

    def reset_stats(self):
        """Reset statistics (call this when starting a new call)"""
        self.packets_parsed = 0
        self.parse_errors = 0
        self.last_sequence = None
        self.last_ssrc = None
        self.packets_lost = 0
        self.packets_received_current_stream = 0
        self.logger.debug("RTP parser statistics reset")

    def get_stats(self) -> dict:
        """Get parser statistics"""
        # Calculate loss rate based on current stream
        # Use packets_received_current_stream for more accurate calculation
        denominator = max(self.packets_received_current_stream, 1)

        # Loss rate = lost packets / (received + lost)
        # This gives actual percentage of packets that were lost
        if self.packets_received_current_stream > 0:
            total_expected = self.packets_received_current_stream + self.packets_lost
            loss_rate = self.packets_lost / total_expected if total_expected > 0 else 0.0
            # Clamp to [0.0, 1.0]
            loss_rate = min(1.0, max(0.0, loss_rate))
        else:
            loss_rate = 0.0

        return {
            'packets_parsed': self.packets_parsed,
            'parse_errors': self.parse_errors,
            'packets_lost': self.packets_lost,
            'packets_received': self.packets_received_current_stream,
            'loss_rate': loss_rate
        }


class RTPBuilder:
    """
    Builder for creating RTP packets according to RFC 3550

    Usage:
        builder = RTPBuilder(ssrc=12345)

        # Build packet
        rtp_packet = builder.build_packet(
            payload=g711_data,
            payload_type=0  # G.711 ulaw
        )

        # Send via socket
        sock.sendto(rtp_packet, dest_addr)
    """

    def __init__(self, ssrc: int = None, initial_sequence: int = 0, initial_timestamp: int = 0):
        """
        Initialize RTP packet builder

        Args:
            ssrc: Synchronization source identifier (random 32-bit)
            initial_sequence: Initial sequence number
            initial_timestamp: Initial timestamp
        """
        self.logger = logging.getLogger("ai-voice-agent.rtp.builder")

        # Generate random SSRC if not provided
        if ssrc is None:
            import random
            self.ssrc = random.randint(0, 0xFFFFFFFF)
        else:
            self.ssrc = ssrc

        # Sequence number (16-bit, wraps around)
        self.sequence_number = initial_sequence & 0xFFFF

        # Timestamp (32-bit, wraps around)
        self.timestamp = initial_timestamp & 0xFFFFFFFF

        # Statistics
        self.packets_built = 0

        self.logger.info(f"RTP Builder initialized: SSRC={self.ssrc}, seq={self.sequence_number}, ts={self.timestamp}")

    def build_packet(self,
                     payload: bytes,
                     payload_type: int = 0,
                     marker: bool = False,
                     timestamp_increment: int = 160) -> bytes:
        """
        Build RTP packet with automatic sequence/timestamp management

        Args:
            payload: RTP payload (encoded audio data)
            payload_type: RTP payload type (0 = PCMU/G.711 ulaw, 8 = PCMA/G.711 alaw)
            marker: Marker bit (set to True for first packet after silence)
            timestamp_increment: Timestamp increment (160 for 20ms @ 8kHz)

        Returns:
            Complete RTP packet bytes
        """
        packet = self.build_packet_raw(
            payload=payload,
            sequence_number=self.sequence_number,
            timestamp=self.timestamp,
            ssrc=self.ssrc,
            payload_type=payload_type,
            marker=marker
        )

        # Auto-increment sequence and timestamp
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF
        self.timestamp = (self.timestamp + timestamp_increment) & 0xFFFFFFFF
        self.packets_built += 1

        return packet

    @staticmethod
    def build_packet_raw(payload: bytes,
                         sequence_number: int,
                         timestamp: int,
                         ssrc: int,
                         payload_type: int = 0,
                         marker: bool = False,
                         version: int = 2,
                         padding: bool = False,
                         extension: bool = False,
                         csrc_count: int = 0) -> bytes:
        """
        Build RTP packet from raw parameters (static method for one-off packets)

        Args:
            payload: RTP payload bytes
            sequence_number: Sequence number (16-bit)
            timestamp: Timestamp (32-bit)
            ssrc: SSRC identifier (32-bit)
            payload_type: Payload type (0-127)
            marker: Marker bit
            version: RTP version (always 2)
            padding: Padding flag
            extension: Extension flag
            csrc_count: CSRC count (0-15)

        Returns:
            Complete RTP packet bytes (12-byte header + payload)
        """
        # Build byte 0: V(2) P(1) X(1) CC(4)
        byte0 = ((version & 0x03) << 6) | \
                ((1 if padding else 0) << 5) | \
                ((1 if extension else 0) << 4) | \
                (csrc_count & 0x0F)

        # Build byte 1: M(1) PT(7)
        byte1 = ((1 if marker else 0) << 7) | (payload_type & 0x7F)

        # Pack header (12 bytes minimum)
        # Format: !BBHII
        # B = unsigned char (1 byte)
        # H = unsigned short (2 bytes)
        # I = unsigned int (4 bytes)
        # ! = network byte order (big-endian)
        header = struct.pack('!BBHII',
                            byte0,
                            byte1,
                            sequence_number & 0xFFFF,
                            timestamp & 0xFFFFFFFF,
                            ssrc & 0xFFFFFFFF)

        # TODO: Add CSRC list support if needed (csrc_count > 0)

        # Combine header + payload
        return header + payload

    def reset_sequence(self, value: int = 0):
        """Reset sequence number"""
        self.sequence_number = value & 0xFFFF

    def reset_timestamp(self, value: int = 0):
        """Reset timestamp"""
        self.timestamp = value & 0xFFFFFFFF

    def get_stats(self) -> dict:
        """Get builder statistics"""
        return {
            'ssrc': self.ssrc,
            'sequence_number': self.sequence_number,
            'timestamp': self.timestamp,
            'packets_built': self.packets_built
        }
