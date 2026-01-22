"""
RTCP (RTP Control Protocol) - RFC 3550

Implements RTCP packet types:
- SR (Sender Report): Sent by active senders with transmission stats
- RR (Receiver Report): Sent by receivers with reception quality stats

Used for:
- Quality monitoring (packet loss, jitter)
- Round-Trip Time (RTT) measurement
- Network feedback
"""

import struct
import time
from dataclasses import dataclass
from typing import Optional, List, Tuple

from ..common.logging import get_logger

logger = get_logger('rtp.rtcp')


# RTCP Packet Types (RFC 3550)
RTCP_SR = 200  # Sender Report
RTCP_RR = 201  # Receiver Report
RTCP_SDES = 202  # Source Description
RTCP_BYE = 203  # Goodbye
RTCP_APP = 204  # Application-defined


@dataclass
class RTCPHeader:
    """
    RTCP Common Header (RFC 3550 Section 6.1)

     0                   1                   2                   3
     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |V=2|P|    RC   |   PT=SR/RR    |             length            |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |                         SSRC of sender                        |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    """
    version: int = 2  # Always 2
    padding: bool = False
    report_count: int = 0  # Number of reception report blocks (RC)
    packet_type: int = 0  # SR=200, RR=201
    length: int = 0  # Packet length in 32-bit words minus one
    ssrc: int = 0  # SSRC of sender/receiver


@dataclass
class SenderInfo:
    """
    Sender Info Block (SR only - RFC 3550 Section 6.4.1)

    Contains transmission statistics from the sender.
    """
    ntp_timestamp_msw: int = 0  # NTP timestamp - most significant word
    ntp_timestamp_lsw: int = 0  # NTP timestamp - least significant word
    rtp_timestamp: int = 0  # RTP timestamp (same units as RTP packets)
    sender_packet_count: int = 0  # Total packets sent
    sender_octet_count: int = 0  # Total bytes sent

    @property
    def ntp_timestamp(self) -> float:
        """Convert NTP timestamp to seconds since 1900"""
        return self.ntp_timestamp_msw + (self.ntp_timestamp_lsw / (2**32))

    @staticmethod
    def from_system_time() -> 'SenderInfo':
        """Create SenderInfo with current system time as NTP timestamp"""
        # NTP epoch: 1900-01-01 00:00:00
        # Unix epoch: 1970-01-01 00:00:00
        # Difference: 2208988800 seconds
        NTP_EPOCH_OFFSET = 2208988800

        current_time = time.time()
        ntp_time = current_time + NTP_EPOCH_OFFSET

        # Split into integer and fractional parts
        ntp_seconds = int(ntp_time)
        ntp_fraction = ntp_time - ntp_seconds

        # Convert to NTP format (32.32 fixed point)
        ntp_msw = ntp_seconds & 0xFFFFFFFF
        ntp_lsw = int(ntp_fraction * (2**32)) & 0xFFFFFFFF

        return SenderInfo(
            ntp_timestamp_msw=ntp_msw,
            ntp_timestamp_lsw=ntp_lsw,
            rtp_timestamp=0,  # Will be set later
            sender_packet_count=0,
            sender_octet_count=0
        )


@dataclass
class ReceptionReport:
    """
    Reception Report Block (RFC 3550 Section 6.4.1)

    Reception quality statistics for one RTP source (SSRC).
    Included in both SR and RR packets.

     0                   1                   2                   3
     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |                 SSRC_1 (SSRC of first source)                 |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    | fraction lost |       cumulative number of packets lost       |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |           extended highest sequence number received           |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |                      interarrival jitter                      |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |                         last SR (LSR)                         |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |                   delay since last SR (DLSR)                  |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    """
    ssrc: int = 0  # SSRC of source being reported on
    fraction_lost: int = 0  # Fraction lost since last RR (0-255, 0=0%, 255=100%)
    cumulative_lost: int = 0  # Total packets lost since start (24-bit, signed)
    extended_highest_seq: int = 0  # Extended highest sequence number received
    jitter: int = 0  # Interarrival jitter (in RTP timestamp units)
    last_sr_timestamp: int = 0  # Middle 32 bits of NTP timestamp from last SR (LSR)
    delay_since_last_sr: int = 0  # Delay since last SR in 1/65536 seconds (DLSR)


class RTCPPacket:
    """Base class for RTCP packets"""

    @staticmethod
    def calculate_length_field(packet_bytes: int) -> int:
        """
        Calculate RTCP length field value

        RFC 3550: Length field is the packet length in 32-bit words minus one,
        excluding the common header.

        Args:
            packet_bytes: Total packet size in bytes (including header)

        Returns:
            Length field value (16-bit)
        """
        # Length in 32-bit words
        words = packet_bytes // 4
        # Minus one (RFC 3550 requirement)
        return (words - 1) & 0xFFFF


class RTCPSenderReport:
    """
    RTCP Sender Report (SR) - RFC 3550 Section 6.4.1

    Sent by active senders to report transmission and reception statistics.
    """

    def __init__(self, ssrc: int):
        """
        Initialize Sender Report

        Args:
            ssrc: SSRC of the sender
        """
        self.header = RTCPHeader(
            version=2,
            padding=False,
            report_count=0,  # Will be set when reports are added
            packet_type=RTCP_SR,
            length=0,  # Will be calculated during serialization
            ssrc=ssrc
        )
        self.sender_info = SenderInfo.from_system_time()
        self.reception_reports: List[ReceptionReport] = []

    def add_report(self, report: ReceptionReport):
        """Add a reception report block"""
        if len(self.reception_reports) < 31:  # Max 31 reports (5-bit RC field)
            self.reception_reports.append(report)
            self.header.report_count = len(self.reception_reports)
        else:
            logger.warn("Cannot add more than 31 reception reports to SR")

    def serialize(self) -> bytes:
        """
        Serialize SR packet to bytes

        Returns:
            Binary RTCP SR packet
        """
        # Update length field
        # SR packet size: header(8) + sender_info(20) + reports(24 * count)
        packet_size = 8 + 20 + (24 * len(self.reception_reports))
        self.header.length = RTCPPacket.calculate_length_field(packet_size)

        # Pack header (8 bytes)
        byte0 = (self.header.version << 6) | (int(self.header.padding) << 5) | (self.header.report_count & 0x1F)
        header_bytes = struct.pack('!BBH I',
                                   byte0,
                                   self.header.packet_type,
                                   self.header.length,
                                   self.header.ssrc)

        # Pack sender info (20 bytes)
        sender_bytes = struct.pack('!II III',
                                   self.sender_info.ntp_timestamp_msw,
                                   self.sender_info.ntp_timestamp_lsw,
                                   self.sender_info.rtp_timestamp,
                                   self.sender_info.sender_packet_count,
                                   self.sender_info.sender_octet_count)

        # Pack reception reports (24 bytes each)
        reports_bytes = b''
        for report in self.reception_reports:
            # Pack cumulative_lost as 24-bit signed integer
            cumulative_lost_24bit = report.cumulative_lost & 0xFFFFFF

            report_bytes = struct.pack('!I BBH I II I',
                                       report.ssrc,
                                       report.fraction_lost,
                                       (cumulative_lost_24bit >> 16) & 0xFF,
                                       cumulative_lost_24bit & 0xFFFF,
                                       report.extended_highest_seq,
                                       report.jitter,
                                       report.last_sr_timestamp,
                                       report.delay_since_last_sr)
            reports_bytes += report_bytes

        return header_bytes + sender_bytes + reports_bytes

    @staticmethod
    def parse(data: bytes) -> Optional['RTCPSenderReport']:
        """
        Parse SR packet from bytes

        Args:
            data: Binary RTCP packet

        Returns:
            RTCPSenderReport instance or None if invalid
        """
        if len(data) < 28:  # Minimum: header(8) + sender_info(20)
            logger.warn("RTCP SR packet too short", length=len(data))
            return None

        try:
            # Parse header
            byte0, pt, length, ssrc = struct.unpack('!BBH I', data[0:8])

            version = (byte0 >> 6) & 0x3
            padding = bool((byte0 >> 5) & 0x1)
            report_count = byte0 & 0x1F

            if version != 2:
                logger.warn("Invalid RTCP version", version=version)
                return None

            if pt != RTCP_SR:
                logger.warn("Not an SR packet", packet_type=pt)
                return None

            # Parse sender info
            ntp_msw, ntp_lsw, rtp_ts, pkt_count, octet_count = struct.unpack('!II III', data[8:28])

            sender_info = SenderInfo(
                ntp_timestamp_msw=ntp_msw,
                ntp_timestamp_lsw=ntp_lsw,
                rtp_timestamp=rtp_ts,
                sender_packet_count=pkt_count,
                sender_octet_count=octet_count
            )

            # Create SR
            sr = RTCPSenderReport(ssrc=ssrc)
            sr.sender_info = sender_info
            sr.header.padding = padding
            sr.header.length = length

            # Parse reception reports
            offset = 28
            for i in range(report_count):
                if offset + 24 > len(data):
                    logger.warn("Truncated reception report", index=i)
                    break

                rr_data = data[offset:offset+24]
                rr_ssrc, frac_lost, lost_msb, lost_lsw, ext_seq, jitter, lsr, dlsr = struct.unpack('!I BBH I II I', rr_data)

                # Reconstruct 24-bit cumulative lost
                cumulative_lost = (lost_msb << 16) | lost_lsw
                # Sign extend if negative
                if cumulative_lost & 0x800000:
                    cumulative_lost |= 0xFF000000

                report = ReceptionReport(
                    ssrc=rr_ssrc,
                    fraction_lost=frac_lost,
                    cumulative_lost=cumulative_lost,
                    extended_highest_seq=ext_seq,
                    jitter=jitter,
                    last_sr_timestamp=lsr,
                    delay_since_last_sr=dlsr
                )
                sr.add_report(report)

                offset += 24

            return sr

        except Exception as e:
            logger.error("Error parsing SR packet", error=str(e))
            return None


class RTCPReceiverReport:
    """
    RTCP Receiver Report (RR) - RFC 3550 Section 6.4.2

    Sent by receivers that are not also senders (no transmission stats).
    """

    def __init__(self, ssrc: int):
        """
        Initialize Receiver Report

        Args:
            ssrc: SSRC of the receiver
        """
        self.header = RTCPHeader(
            version=2,
            padding=False,
            report_count=0,
            packet_type=RTCP_RR,
            length=0,
            ssrc=ssrc
        )
        self.reception_reports: List[ReceptionReport] = []

    def add_report(self, report: ReceptionReport):
        """Add a reception report block"""
        if len(self.reception_reports) < 31:
            self.reception_reports.append(report)
            self.header.report_count = len(self.reception_reports)
        else:
            logger.warn("Cannot add more than 31 reception reports to RR")

    def serialize(self) -> bytes:
        """
        Serialize RR packet to bytes

        Returns:
            Binary RTCP RR packet
        """
        # RR packet size: header(8) + reports(24 * count)
        packet_size = 8 + (24 * len(self.reception_reports))
        self.header.length = RTCPPacket.calculate_length_field(packet_size)

        # Pack header (8 bytes)
        byte0 = (self.header.version << 6) | (int(self.header.padding) << 5) | (self.header.report_count & 0x1F)
        header_bytes = struct.pack('!BBH I',
                                   byte0,
                                   self.header.packet_type,
                                   self.header.length,
                                   self.header.ssrc)

        # Pack reception reports (24 bytes each)
        reports_bytes = b''
        for report in self.reception_reports:
            cumulative_lost_24bit = report.cumulative_lost & 0xFFFFFF

            report_bytes = struct.pack('!I BBH I II I',
                                       report.ssrc,
                                       report.fraction_lost,
                                       (cumulative_lost_24bit >> 16) & 0xFF,
                                       cumulative_lost_24bit & 0xFFFF,
                                       report.extended_highest_seq,
                                       report.jitter,
                                       report.last_sr_timestamp,
                                       report.delay_since_last_sr)
            reports_bytes += report_bytes

        return header_bytes + reports_bytes

    @staticmethod
    def parse(data: bytes) -> Optional['RTCPReceiverReport']:
        """
        Parse RR packet from bytes

        Args:
            data: Binary RTCP packet

        Returns:
            RTCPReceiverReport instance or None if invalid
        """
        if len(data) < 8:  # Minimum: header only
            logger.warn("RTCP RR packet too short", length=len(data))
            return None

        try:
            # Parse header
            byte0, pt, length, ssrc = struct.unpack('!BBH I', data[0:8])

            version = (byte0 >> 6) & 0x3
            padding = bool((byte0 >> 5) & 0x1)
            report_count = byte0 & 0x1F

            if version != 2:
                logger.warn("Invalid RTCP version", version=version)
                return None

            if pt != RTCP_RR:
                logger.warn("Not an RR packet", packet_type=pt)
                return None

            # Create RR
            rr = RTCPReceiverReport(ssrc=ssrc)
            rr.header.padding = padding
            rr.header.length = length

            # Parse reception reports
            offset = 8
            for i in range(report_count):
                if offset + 24 > len(data):
                    logger.warn("Truncated reception report", index=i)
                    break

                rr_data = data[offset:offset+24]
                rr_ssrc, frac_lost, lost_msb, lost_lsw, ext_seq, jitter, lsr, dlsr = struct.unpack('!I BBH I II I', rr_data)

                cumulative_lost = (lost_msb << 16) | lost_lsw
                if cumulative_lost & 0x800000:
                    cumulative_lost |= 0xFF000000

                report = ReceptionReport(
                    ssrc=rr_ssrc,
                    fraction_lost=frac_lost,
                    cumulative_lost=cumulative_lost,
                    extended_highest_seq=ext_seq,
                    jitter=jitter,
                    last_sr_timestamp=lsr,
                    delay_since_last_sr=dlsr
                )
                rr.add_report(report)

                offset += 24

            return rr

        except Exception as e:
            logger.error("Error parsing RR packet", error=str(e))
            return None


def parse_rtcp_packet(data: bytes) -> Optional[Tuple[int, object]]:
    """
    Parse RTCP packet and return packet type and parsed object

    Args:
        data: Binary RTCP packet

    Returns:
        Tuple of (packet_type, parsed_packet) or None if invalid
    """
    if len(data) < 8:
        return None

    try:
        byte0, pt = struct.unpack('!BB', data[0:2])
        version = (byte0 >> 6) & 0x3

        if version != 2:
            return None

        if pt == RTCP_SR:
            sr = RTCPSenderReport.parse(data)
            return (RTCP_SR, sr) if sr else None
        elif pt == RTCP_RR:
            rr = RTCPReceiverReport.parse(data)
            return (RTCP_RR, rr) if rr else None
        else:
            logger.debug("Unsupported RTCP packet type", packet_type=pt)
            return None

    except Exception as e:
        logger.error("Error parsing RTCP packet", error=str(e))
        return None
