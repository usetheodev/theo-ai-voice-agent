"""
DTMF Detection via RFC 2833 (RTP Event)

Detects telephone keypad tones (0-9, *, #) transmitted as RTP events
according to RFC 2833 (now RFC 4733).
"""

import struct
from typing import Optional, Callable
from dataclasses import dataclass

from ..common.logging import get_logger
from .packet import RTPHeader

logger = get_logger('rtp.dtmf')


@dataclass
class DTMFEvent:
    """
    DTMF Event (RFC 2833)

    Represents a single DTMF tone event.
    """
    digit: str          # '0'-'9', '*', '#'
    event_code: int     # 0-15 (RFC 2833 event number)
    duration_ms: int    # Duration of the tone in milliseconds
    volume_db: int      # Volume in dB (0 to -63)

    def __repr__(self):
        return f"DTMFEvent(digit='{self.digit}', duration={self.duration_ms}ms, volume={self.volume_db}dB)"


class DTMFDetector:
    """
    DTMF Detection via RFC 2833 (RTP Event)

    Detects telephone keypad tones transmitted as RTP events.

    RFC 2833 Packet Format:

     0                   1                   2                   3
     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |     event     |E|R| volume    |          duration             |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

    - event: Event code (0-15 for DTMF: 0-9, *, #, A-D)
    - E: End bit (1 = last packet for this event)
    - R: Reserved (always 0)
    - volume: Power level (0 to -63 dBm0)
    - duration: Duration in RTP timestamp units (typically 8000 Hz for PCMU)
    """

    # Payload type for telephone-event (typically 101)
    DTMF_PAYLOAD_TYPE = 101

    # RFC 2833 Event Codes to DTMF digits
    EVENT_TO_DIGIT = {
        0: '0',
        1: '1',
        2: '2',
        3: '3',
        4: '4',
        5: '5',
        6: '6',
        7: '7',
        8: '8',
        9: '9',
        10: '*',
        11: '#',
        # 12-15 are A-D (not used in standard telephone keypads)
    }

    # RTP timestamp units to milliseconds (8000 Hz = 8 units per ms)
    TIMESTAMP_TO_MS = 8  # 8000 Hz clock

    def __init__(self, payload_type: int = 101):
        """
        Initialize DTMF Detector

        Args:
            payload_type: RTP payload type for telephone-event (default: 101)
        """
        self.payload_type = payload_type

        # Current event tracking (to detect end of tone)
        self.current_event: Optional[int] = None
        self.current_timestamp: Optional[int] = None

        # Callback for detected DTMF digits
        self.on_dtmf_callback: Optional[Callable[[DTMFEvent], None]] = None

        # Statistics
        self.dtmf_events_detected = 0
        self.invalid_packets = 0

        logger.info("DTMF Detector initialized", payload_type=payload_type)

    def on_dtmf(self, callback: Callable[[DTMFEvent], None]):
        """
        Register callback for DTMF events

        Args:
            callback: Function to call when DTMF digit is detected
                     Signature: callback(dtmf_event: DTMFEvent)
        """
        self.on_dtmf_callback = callback
        logger.debug("DTMF callback registered")

    def process_rtp(self, header: RTPHeader, payload: bytes) -> Optional[DTMFEvent]:
        """
        Process RTP packet, return DTMF event if detected

        Args:
            header: RTP header
            payload: RTP payload

        Returns:
            DTMFEvent if a complete DTMF digit was detected, None otherwise
        """
        # Check if this is a DTMF event packet
        if header.payload_type != self.payload_type:
            return None

        # Parse RFC 2833 packet
        event = self._parse_event_packet(payload)
        if event is None:
            self.invalid_packets += 1
            logger.warn("Invalid DTMF packet", payload_length=len(payload))
            return None

        event_code, end_bit, volume, duration = event

        # Map event code to digit
        digit = self.EVENT_TO_DIGIT.get(event_code)
        if digit is None:
            logger.debug("Unknown DTMF event code", event_code=event_code)
            return None

        # Convert duration from RTP timestamp units to milliseconds
        duration_ms = duration // self.TIMESTAMP_TO_MS

        # Track event state
        is_new_event = (self.current_event != event_code or
                       self.current_timestamp != header.timestamp)

        if is_new_event:
            # New event started
            self.current_event = event_code
            self.current_timestamp = header.timestamp
            logger.debug("DTMF event started",
                        digit=digit,
                        event_code=event_code,
                        timestamp=header.timestamp)

        # Check if event ended
        if end_bit:
            # Event complete - create DTMFEvent
            dtmf_event = DTMFEvent(
                digit=digit,
                event_code=event_code,
                duration_ms=duration_ms,
                volume_db=-volume  # RFC 2833 uses negative dB
            )

            self.dtmf_events_detected += 1

            logger.info("🔢 DTMF detected",
                       digit=digit,
                       duration_ms=duration_ms,
                       volume_db=-volume,
                       total_events=self.dtmf_events_detected)

            # Reset tracking
            self.current_event = None
            self.current_timestamp = None

            # Trigger callback
            if self.on_dtmf_callback:
                try:
                    self.on_dtmf_callback(dtmf_event)
                except Exception as e:
                    logger.error("Error in DTMF callback", error=str(e))

            return dtmf_event

        # Event still in progress
        return None

    def _parse_event_packet(self, payload: bytes) -> Optional[tuple]:
        """
        Parse RFC 2833 event packet

        Packet format (4 bytes):
        - Byte 0: event code (0-255)
        - Byte 1: E|R|volume (1 bit end, 1 bit reserved, 6 bits volume)
        - Bytes 2-3: duration (16 bits, big-endian)

        Args:
            payload: RTP payload

        Returns:
            Tuple of (event_code, end_bit, volume, duration) or None if invalid
        """
        if len(payload) < 4:
            return None

        try:
            # Unpack 4 bytes: event, E/R/volume, duration (big-endian)
            event_code = payload[0]
            flags_volume = payload[1]
            duration = struct.unpack('!H', payload[2:4])[0]  # Big-endian unsigned short

            # Extract end bit (bit 7 of byte 1)
            end_bit = bool(flags_volume & 0x80)

            # Extract volume (bits 0-5 of byte 1)
            volume = flags_volume & 0x3F

            return (event_code, end_bit, volume, duration)

        except Exception as e:
            logger.error("Error parsing DTMF packet", error=str(e))
            return None

    def get_stats(self) -> dict:
        """Get DTMF detector statistics"""
        return {
            'dtmf_events_detected': self.dtmf_events_detected,
            'invalid_packets': self.invalid_packets,
            'current_event_active': self.current_event is not None
        }

    def reset(self):
        """Reset detector state"""
        self.current_event = None
        self.current_timestamp = None
        logger.debug("DTMF detector reset")
