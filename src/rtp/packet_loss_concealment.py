"""
Packet Loss Concealment (PLC)

Implements audio concealment for lost RTP packets using a 3-level approach:
- Level 1 (0-3% loss): Repeat last packet
- Level 2 (3-10% loss): Fade to comfort noise
- Level 3 (>10% loss): Comfort noise only

Supports PCMU (G.711 μ-law) codec.
"""

import random
from typing import Optional, Tuple
from dataclasses import dataclass

from ..common.logging import get_logger
from .packet import RTPHeader

logger = get_logger('rtp.plc')


@dataclass
class PLCStats:
    """PLC Statistics"""
    packets_concealed: int = 0
    plc_level_1_count: int = 0  # Repeat last packet
    plc_level_2_count: int = 0  # Fade to comfort noise
    plc_level_3_count: int = 0  # Comfort noise only
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0


class PacketLossConcealment:
    """
    Packet Loss Concealment

    Generates replacement audio for lost RTP packets based on loss rate:
    - Low loss (0-3%): Repeat last good packet
    - Medium loss (3-10%): Fade last packet to comfort noise
    - High loss (>10%): Generate comfort noise only
    """

    # Loss rate thresholds
    THRESHOLD_LEVEL_1 = 0.03  # 3%
    THRESHOLD_LEVEL_2 = 0.10  # 10%

    # PCMU (G.711 μ-law) constants
    PCMU_SILENCE = 0xFF       # μ-law encoding of 0
    PCMU_PACKET_SIZE = 160    # 20ms @ 8kHz

    def __init__(self, codec: str = "PCMU"):
        """
        Initialize PLC

        Args:
            codec: Audio codec (currently only "PCMU" supported)
        """
        if codec != "PCMU":
            raise ValueError(f"Unsupported codec: {codec}. Only PCMU is supported.")

        self.codec = codec

        # Last good packet (for repetition/fading)
        self.last_header: Optional[RTPHeader] = None
        self.last_payload: Optional[bytes] = None

        # PLC state
        self.consecutive_losses = 0
        self.stats = PLCStats()

        logger.debug("PLC initialized", codec=codec)

    def update_last_packet(self, header: RTPHeader, payload: bytes):
        """
        Store last good packet for PLC reference

        Args:
            header: RTP header of good packet
            payload: Audio payload of good packet
        """
        self.last_header = header
        self.last_payload = payload

        # Reset consecutive loss counter on good packet
        if self.consecutive_losses > 0:
            if self.consecutive_losses > self.stats.max_consecutive_losses:
                self.stats.max_consecutive_losses = self.consecutive_losses
            self.consecutive_losses = 0

    def conceal(self, sequence_number: int, loss_rate: float) -> Tuple[RTPHeader, bytes]:
        """
        Generate concealment packet for lost packet

        Args:
            sequence_number: Sequence number of lost packet
            loss_rate: Current packet loss rate (0.0-1.0)

        Returns:
            (header, payload) tuple for concealment packet
        """
        self.consecutive_losses += 1
        self.stats.packets_concealed += 1

        # Select concealment level based on loss rate
        if loss_rate < self.THRESHOLD_LEVEL_1:
            # Level 1: Low loss - repeat last packet
            level = 1
            header, payload = self._repeat_last_packet(sequence_number)
            self.stats.plc_level_1_count += 1

        elif loss_rate < self.THRESHOLD_LEVEL_2:
            # Level 2: Medium loss - fade to comfort noise
            level = 2
            header, payload = self._fade_to_comfort_noise(sequence_number)
            self.stats.plc_level_2_count += 1

        else:
            # Level 3: High loss - comfort noise only
            level = 3
            header, payload = self._generate_comfort_noise(sequence_number)
            self.stats.plc_level_3_count += 1

        logger.debug("PLC concealment",
                    seq=sequence_number,
                    loss_rate=f"{loss_rate*100:.2f}%",
                    level=level,
                    consecutive_losses=self.consecutive_losses)

        return (header, payload)

    def _repeat_last_packet(self, sequence_number: int) -> Tuple[RTPHeader, bytes]:
        """
        Level 1: Repeat last good packet

        Best for low loss rates (0-3%). Simple but effective.

        Args:
            sequence_number: Sequence number for concealment packet

        Returns:
            (header, payload) with last packet's audio
        """
        if self.last_header is None or self.last_payload is None:
            # No previous packet - fall back to silence
            return self._generate_comfort_noise(sequence_number)

        # Create header for concealment packet
        header = RTPHeader(
            version=2,
            padding=False,
            extension=False,
            marker=False,
            payload_type=0,  # PCMU
            sequence_number=sequence_number,
            timestamp=self.last_header.timestamp + 160,  # 20ms @ 8kHz
            ssrc=self.last_header.ssrc
        )

        # Repeat last payload exactly
        payload = self.last_payload

        return (header, payload)

    def _fade_to_comfort_noise(self, sequence_number: int) -> Tuple[RTPHeader, bytes]:
        """
        Level 2: Fade last packet to comfort noise

        For medium loss rates (3-10%). Gradually fades audio to prevent
        jarring transitions.

        Args:
            sequence_number: Sequence number for concealment packet

        Returns:
            (header, payload) with faded audio
        """
        if self.last_header is None or self.last_payload is None:
            # No previous packet - fall back to comfort noise
            return self._generate_comfort_noise(sequence_number)

        # Create header
        header = RTPHeader(
            version=2,
            padding=False,
            extension=False,
            marker=False,
            payload_type=0,  # PCMU
            sequence_number=sequence_number,
            timestamp=self.last_header.timestamp + 160,
            ssrc=self.last_header.ssrc
        )

        # Calculate fade factor based on consecutive losses
        # Fade from 100% (first loss) to 0% (5+ consecutive losses)
        max_fade_packets = 5
        fade_factor = max(0.0, 1.0 - (self.consecutive_losses / max_fade_packets))

        # Blend last packet with comfort noise
        payload = bytearray(self.PCMU_PACKET_SIZE)

        for i in range(min(len(self.last_payload), self.PCMU_PACKET_SIZE)):
            # Get last packet sample
            last_sample = self.last_payload[i]

            # Generate comfort noise sample
            noise_sample = self._pcmu_comfort_noise_sample()

            # Blend: more last_sample initially, more noise_sample later
            # Simple linear interpolation
            blended = int(last_sample * fade_factor + noise_sample * (1.0 - fade_factor))
            payload[i] = blended & 0xFF

        return (header, bytes(payload))

    def _generate_comfort_noise(self, sequence_number: int) -> Tuple[RTPHeader, bytes]:
        """
        Level 3: Generate comfort noise

        For high loss rates (>10%). Generates low-level background noise
        to maintain comfort and avoid dead silence.

        Args:
            sequence_number: Sequence number for concealment packet

        Returns:
            (header, payload) with comfort noise
        """
        # Create header
        header = RTPHeader(
            version=2,
            padding=False,
            extension=False,
            marker=False,
            payload_type=0,  # PCMU
            sequence_number=sequence_number,
            timestamp=0,  # Will be set by caller
            ssrc=0  # Will be set by caller
        )

        # If we have last header, use its timestamp/ssrc
        if self.last_header:
            header.timestamp = self.last_header.timestamp + 160
            header.ssrc = self.last_header.ssrc

        # Generate comfort noise payload
        payload = bytes([self._pcmu_comfort_noise_sample()
                        for _ in range(self.PCMU_PACKET_SIZE)])

        return (header, payload)

    def _pcmu_comfort_noise_sample(self) -> int:
        """
        Generate single PCMU comfort noise sample

        Creates low-level noise around the PCMU silence point (0xFF)
        with small variations to sound natural.

        Returns:
            PCMU encoded noise sample (0x00-0xFF)
        """
        # PCMU silence is 0xFF
        # Add small random variation (±3 to avoid complete silence)
        noise = self.PCMU_SILENCE + random.randint(-3, 3)

        # Clamp to valid PCMU range
        return max(0, min(255, noise))

    def get_stats(self) -> dict:
        """
        Get PLC statistics

        Returns:
            Dictionary with PLC metrics
        """
        total_concealed = self.stats.packets_concealed

        return {
            'packets_concealed': total_concealed,
            'plc_level_1_count': self.stats.plc_level_1_count,
            'plc_level_2_count': self.stats.plc_level_2_count,
            'plc_level_3_count': self.stats.plc_level_3_count,
            'consecutive_losses': self.consecutive_losses,
            'max_consecutive_losses': self.stats.max_consecutive_losses,
            'level_1_percent': (self.stats.plc_level_1_count / max(1, total_concealed)) * 100,
            'level_2_percent': (self.stats.plc_level_2_count / max(1, total_concealed)) * 100,
            'level_3_percent': (self.stats.plc_level_3_count / max(1, total_concealed)) * 100
        }

    def reset(self):
        """Reset PLC state"""
        self.last_header = None
        self.last_payload = None
        self.consecutive_losses = 0
        self.stats = PLCStats()
        logger.debug("PLC reset")
