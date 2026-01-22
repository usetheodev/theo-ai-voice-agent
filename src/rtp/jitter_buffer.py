"""
Adaptive Jitter Buffer for RTP

Implements RFC 3550 jitter calculation and adaptive buffer depth
to handle network jitter and packet reordering.
"""

import asyncio
import time
from typing import Optional, Tuple, Dict
from dataclasses import dataclass
from collections import OrderedDict

from ..common.logging import get_logger
from .packet import RTPHeader
from .packet_loss_concealment import PacketLossConcealment

logger = get_logger('rtp.jitter_buffer')


@dataclass
class JitterBufferConfig:
    """Jitter Buffer Configuration"""
    initial_depth_ms: int = 60      # Initial buffer depth
    min_depth_ms: int = 20           # Minimum depth (low latency)
    max_depth_ms: int = 300          # Maximum depth (high jitter)
    packet_duration_ms: int = 20     # Duration per packet (20ms @ 8kHz)
    adaptation_rate: float = 0.1     # How fast to adapt (0.0-1.0)


@dataclass
class JitterBufferStats:
    """Jitter Buffer Statistics"""
    packets_received: int = 0
    packets_dropped_duplicate: int = 0
    packets_dropped_late: int = 0
    packets_output: int = 0
    packets_lost: int = 0
    current_depth_ms: int = 0
    current_jitter_ms: float = 0.0
    buffer_underruns: int = 0
    buffer_overruns: int = 0


class AdaptiveJitterBuffer:
    """
    Adaptive Jitter Buffer

    Features:
    - Reorders out-of-sequence packets
    - Detects packet loss
    - Adapts buffer depth based on observed jitter
    - RFC 3550 compliant jitter calculation
    """

    def __init__(self, config: Optional[JitterBufferConfig] = None):
        self.config = config or JitterBufferConfig()

        # Buffer storage (sequence_number -> (header, payload, arrival_time))
        self.buffer: OrderedDict[int, Tuple[RTPHeader, bytes, float]] = OrderedDict()

        # State
        self.stats = JitterBufferStats()
        self.stats.current_depth_ms = self.config.initial_depth_ms

        # Sequence tracking
        self.last_seq_received: Optional[int] = None
        self.last_seq_output: Optional[int] = None
        self.highest_seq_received: Optional[int] = None

        # Jitter calculation (RFC 3550)
        self.jitter: float = 0.0  # Estimated jitter in timestamp units
        self.last_timestamp: Optional[int] = None
        self.last_arrival_time: Optional[float] = None

        # Playout timing
        self.playout_timestamp: Optional[int] = None

        # Packet Loss Concealment
        self.plc = PacketLossConcealment(codec="PCMU")

        # Asyncio
        self.ready_event = asyncio.Event()

    def push(self, header: RTPHeader, payload: bytes) -> bool:
        """
        Add packet to jitter buffer

        Args:
            header: RTP header
            payload: RTP payload

        Returns:
            True if packet accepted, False if rejected (duplicate/late)
        """
        seq = header.sequence_number
        arrival_time = time.time()

        self.stats.packets_received += 1

        # Check for duplicate
        if seq in self.buffer:
            self.stats.packets_dropped_duplicate += 1
            logger.debug("Duplicate packet dropped", seq=seq)
            return False

        # Check if packet is too late (already output)
        if self.last_seq_output is not None:
            seq_diff = self._seq_diff(seq, self.last_seq_output)
            if seq_diff <= 0:
                self.stats.packets_dropped_late += 1
                logger.debug("Late packet dropped", seq=seq, last_output=self.last_seq_output)
                return False

        # Store packet
        self.buffer[seq] = (header, payload, arrival_time)

        # Update highest sequence
        if self.highest_seq_received is None or self._seq_diff(seq, self.highest_seq_received) > 0:
            self.highest_seq_received = seq

        # Update jitter calculation (RFC 3550)
        self._update_jitter(header.timestamp, arrival_time)

        # Adapt buffer depth based on jitter
        self._adapt_buffer_depth()

        # Update last received
        self.last_seq_received = seq

        # Signal that data is available
        self.ready_event.set()

        logger.debug("Packet buffered",
                    seq=seq,
                    buffer_size=len(self.buffer),
                    jitter_ms=f"{self.stats.current_jitter_ms:.1f}")

        return True

    async def pop(self) -> Optional[Tuple[RTPHeader, bytes]]:
        """
        Get next packet in sequence

        Waits for buffer to fill to depth before starting playout.
        Returns None if packet is lost.

        Returns:
            (header, payload) or None if packet lost
        """
        # Wait for initial fill
        if self.playout_timestamp is None:
            await self._wait_for_initial_fill()

        # Calculate next expected sequence number
        if self.last_seq_output is None:
            # First packet - use lowest seq in buffer
            if not self.buffer:
                await self.ready_event.wait()
                self.ready_event.clear()
                if not self.buffer:
                    return None

            next_seq = min(self.buffer.keys())
        else:
            next_seq = (self.last_seq_output + 1) % 65536

        # Try to get packet
        if next_seq in self.buffer:
            # Good packet - pop from buffer
            header, payload, _ = self.buffer.pop(next_seq)
            self.last_seq_output = next_seq
            self.stats.packets_output += 1

            # Update PLC with good packet for reference
            self.plc.update_last_packet(header, payload)

            logger.debug("Packet output",
                        seq=next_seq,
                        buffer_size=len(self.buffer))

            return (header, payload)
        else:
            # Packet lost - use PLC to conceal
            self.stats.packets_lost += 1
            self.last_seq_output = next_seq

            # Calculate loss rate for PLC level selection
            total_packets = self.stats.packets_received
            loss_rate = self.stats.packets_lost / max(1, total_packets)

            # Generate concealment packet
            header, payload = self.plc.conceal(next_seq, loss_rate)

            logger.warn("Packet loss - PLC active",
                       seq=next_seq,
                       loss_rate=f"{loss_rate*100:.2f}%",
                       buffer_size=len(self.buffer))

            return (header, payload)

    async def _wait_for_initial_fill(self):
        """Wait for buffer to fill to initial depth"""
        target_packets = self.stats.current_depth_ms // self.config.packet_duration_ms

        while len(self.buffer) < target_packets:
            await self.ready_event.wait()
            self.ready_event.clear()

        logger.info("Jitter buffer filled",
                   packets=len(self.buffer),
                   target=target_packets,
                   depth_ms=self.stats.current_depth_ms)

        # Start playout
        self.playout_timestamp = time.time()

    def _update_jitter(self, rtp_timestamp: int, arrival_time: float):
        """
        Update jitter estimate using RFC 3550 algorithm

        J(i) = J(i-1) + (|D(i-1,i)| - J(i-1))/16
        where D(i-1,i) = (arrival(i) - arrival(i-1)) - (ts(i) - ts(i-1))
        """
        if self.last_timestamp is None or self.last_arrival_time is None:
            self.last_timestamp = rtp_timestamp
            self.last_arrival_time = arrival_time
            return

        # Calculate interarrival jitter (RFC 3550 Section 6.4.1)
        # D(i-1,i) = (arrival(i) - arrival(i-1)) - (ts(i) - ts(i-1))/sample_rate
        arrival_diff = arrival_time - self.last_arrival_time
        timestamp_diff = (rtp_timestamp - self.last_timestamp) / 8000.0  # 8kHz sample rate

        D = abs(arrival_diff - timestamp_diff)

        # J(i) = J(i-1) + (|D(i-1,i)| - J(i-1))/16
        self.jitter += (D - self.jitter) / 16.0

        # Update stats (convert to milliseconds)
        self.stats.current_jitter_ms = self.jitter * 1000.0

        # Update last values
        self.last_timestamp = rtp_timestamp
        self.last_arrival_time = arrival_time

    def _adapt_buffer_depth(self):
        """Adapt buffer depth based on observed jitter"""
        # Target depth = jitter * 4 (4 standard deviations)
        target_depth_ms = int(self.stats.current_jitter_ms * 4)

        # Clamp to min/max
        target_depth_ms = max(self.config.min_depth_ms, target_depth_ms)
        target_depth_ms = min(self.config.max_depth_ms, target_depth_ms)

        # Smooth adaptation
        current = self.stats.current_depth_ms
        adaptation = self.config.adaptation_rate
        new_depth = int(current + (target_depth_ms - current) * adaptation)

        if new_depth != current:
            logger.debug("Adapting buffer depth",
                        old_depth_ms=current,
                        new_depth_ms=new_depth,
                        jitter_ms=f"{self.stats.current_jitter_ms:.1f}")
            self.stats.current_depth_ms = new_depth

    def _seq_diff(self, seq1: int, seq2: int) -> int:
        """
        Calculate signed difference between sequence numbers

        Handles wraparound at 65536.

        Returns:
            Positive if seq1 > seq2, negative if seq1 < seq2
        """
        diff = seq1 - seq2
        if diff > 32768:
            diff -= 65536
        elif diff < -32768:
            diff += 65536
        return diff

    def get_stats(self) -> dict:
        """Get buffer statistics"""
        plc_stats = self.plc.get_stats()

        return {
            'packets_received': self.stats.packets_received,
            'packets_output': self.stats.packets_output,
            'packets_lost': self.stats.packets_lost,
            'packets_dropped_duplicate': self.stats.packets_dropped_duplicate,
            'packets_dropped_late': self.stats.packets_dropped_late,
            'buffer_size': len(self.buffer),
            'current_depth_ms': self.stats.current_depth_ms,
            'current_jitter_ms': round(self.stats.current_jitter_ms, 2),
            'buffer_underruns': self.stats.buffer_underruns,
            'buffer_overruns': self.stats.buffer_overruns,
            'plc': plc_stats
        }

    def reset(self):
        """Reset buffer state"""
        self.buffer.clear()
        self.last_seq_received = None
        self.last_seq_output = None
        self.highest_seq_received = None
        self.jitter = 0.0
        self.last_timestamp = None
        self.last_arrival_time = None
        self.playout_timestamp = None
        self.stats = JitterBufferStats()
        self.stats.current_depth_ms = self.config.initial_depth_ms
        self.plc.reset()
        logger.info("Jitter buffer reset")
