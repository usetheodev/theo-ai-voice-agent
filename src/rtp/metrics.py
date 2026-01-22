"""
RTP Performance Metrics

Collects and exposes detailed RTP performance metrics including:
- Audio quality (jitter, packet loss, MOS score)
- Network performance (latency, throughput)
- Session statistics
- PLC metrics
- Security metrics
"""

import time
from typing import Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime

from ..common.logging import get_logger

logger = get_logger('rtp.metrics')


@dataclass
class AudioQualityMetrics:
    """Audio Quality Metrics"""
    # Jitter metrics
    current_jitter_ms: float = 0.0
    avg_jitter_ms: float = 0.0
    max_jitter_ms: float = 0.0

    # Packet loss metrics
    packets_received: int = 0
    packets_lost: int = 0
    packets_dropped_duplicate: int = 0
    packets_dropped_late: int = 0
    packets_dropped_replay: int = 0
    loss_rate_percent: float = 0.0

    # Buffer metrics
    buffer_depth_ms: int = 0
    buffer_underruns: int = 0
    buffer_overruns: int = 0

    # MOS score (Mean Opinion Score) - estimated from metrics
    # Scale: 1.0 (bad) to 5.0 (excellent)
    estimated_mos: float = 0.0


@dataclass
class NetworkMetrics:
    """Network Performance Metrics"""
    # Throughput
    bytes_received: int = 0
    bytes_sent: int = 0
    bitrate_kbps_rx: float = 0.0
    bitrate_kbps_tx: float = 0.0

    # Round-trip time (if available)
    rtt_ms: Optional[float] = None

    # Sequence metrics
    sequence_jumps_detected: int = 0


@dataclass
class PLCMetrics:
    """Packet Loss Concealment Metrics"""
    packets_concealed: int = 0
    plc_level_1_count: int = 0  # Repeat last packet
    plc_level_2_count: int = 0  # Fade to comfort noise
    plc_level_3_count: int = 0  # Comfort noise only
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0

    # Percentages
    level_1_percent: float = 0.0
    level_2_percent: float = 0.0
    level_3_percent: float = 0.0


@dataclass
class SessionMetrics:
    """RTP Session Metrics"""
    session_id: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_seconds: float = 0.0

    # Codec info
    codec: str = "PCMU"
    sample_rate: int = 8000

    # Audio quality
    audio_quality: AudioQualityMetrics = field(default_factory=AudioQualityMetrics)

    # Network performance
    network: NetworkMetrics = field(default_factory=NetworkMetrics)

    # PLC metrics
    plc: PLCMetrics = field(default_factory=PLCMetrics)


class RTPMetricsCollector:
    """
    RTP Metrics Collector

    Aggregates metrics from jitter buffer, connection, and PLC
    and calculates derived metrics like MOS score.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.metrics = SessionMetrics(session_id=session_id)

        # For calculating averages
        self._jitter_samples = []
        self._last_update_time = time.time()

        logger.debug("RTP metrics collector initialized", session_id=session_id)

    def update_from_jitter_buffer(self, jb_stats: dict):
        """Update metrics from jitter buffer statistics"""
        aq = self.metrics.audio_quality

        # Jitter metrics
        aq.current_jitter_ms = jb_stats.get('current_jitter_ms', 0.0)
        self._jitter_samples.append(aq.current_jitter_ms)
        aq.avg_jitter_ms = sum(self._jitter_samples) / len(self._jitter_samples)
        aq.max_jitter_ms = max(aq.max_jitter_ms, aq.current_jitter_ms)

        # Packet metrics
        aq.packets_received = jb_stats.get('packets_received', 0)
        aq.packets_lost = jb_stats.get('packets_lost', 0)
        aq.packets_dropped_duplicate = jb_stats.get('packets_dropped_duplicate', 0)
        aq.packets_dropped_late = jb_stats.get('packets_dropped_late', 0)
        aq.packets_dropped_replay = jb_stats.get('packets_dropped_replay', 0)

        # Calculate loss rate
        total_expected = aq.packets_received + aq.packets_lost
        if total_expected > 0:
            aq.loss_rate_percent = (aq.packets_lost / total_expected) * 100

        # Buffer metrics
        aq.buffer_depth_ms = jb_stats.get('current_depth_ms', 0)
        aq.buffer_underruns = jb_stats.get('buffer_underruns', 0)
        aq.buffer_overruns = jb_stats.get('buffer_overruns', 0)

        # Network metrics
        self.metrics.network.sequence_jumps_detected = jb_stats.get('sequence_jumps_detected', 0)

        # PLC metrics
        plc_stats = jb_stats.get('plc', {})
        if plc_stats:
            self.metrics.plc.packets_concealed = plc_stats.get('packets_concealed', 0)
            self.metrics.plc.plc_level_1_count = plc_stats.get('plc_level_1_count', 0)
            self.metrics.plc.plc_level_2_count = plc_stats.get('plc_level_2_count', 0)
            self.metrics.plc.plc_level_3_count = plc_stats.get('plc_level_3_count', 0)
            self.metrics.plc.consecutive_losses = plc_stats.get('consecutive_losses', 0)
            self.metrics.plc.max_consecutive_losses = plc_stats.get('max_consecutive_losses', 0)
            self.metrics.plc.level_1_percent = plc_stats.get('level_1_percent', 0.0)
            self.metrics.plc.level_2_percent = plc_stats.get('level_2_percent', 0.0)
            self.metrics.plc.level_3_percent = plc_stats.get('level_3_percent', 0.0)

    def update_from_connection(self, conn_stats: dict):
        """Update metrics from RTP connection statistics"""
        net = self.metrics.network

        # Throughput
        net.bytes_received = conn_stats.get('bytes_received', 0)
        net.bytes_sent = conn_stats.get('bytes_sent', 0)

        # Calculate bitrates (update periodically)
        now = time.time()
        elapsed = now - self._last_update_time

        if elapsed > 0:
            # kbps = (bytes * 8) / (elapsed_seconds * 1000)
            net.bitrate_kbps_rx = (net.bytes_received * 8) / (elapsed * 1000)
            net.bitrate_kbps_tx = (net.bytes_sent * 8) / (elapsed * 1000)

        self._last_update_time = now

    def calculate_mos_score(self) -> float:
        """
        Calculate estimated MOS score (Mean Opinion Score)

        MOS scale: 1.0 (bad) to 5.0 (excellent)

        Simplified E-model calculation based on:
        - Packet loss
        - Jitter
        - Codec (PCMU assumed)

        Reference: ITU-T G.107 (E-model)
        """
        aq = self.metrics.audio_quality

        # Start with ideal score for PCMU
        base_score = 4.0

        # Packet loss penalty
        # Each 1% loss reduces MOS by ~0.5
        loss_penalty = aq.loss_rate_percent * 0.5

        # Jitter penalty
        # Each 10ms of jitter reduces MOS by ~0.1
        jitter_penalty = (aq.current_jitter_ms / 10.0) * 0.1

        # Buffer issues penalty
        buffer_penalty = 0.0
        if aq.buffer_underruns > 0:
            buffer_penalty += 0.2
        if aq.buffer_overruns > 0:
            buffer_penalty += 0.1

        # Calculate final MOS
        mos = base_score - loss_penalty - jitter_penalty - buffer_penalty

        # Clamp to valid range [1.0, 5.0]
        mos = max(1.0, min(5.0, mos))

        self.metrics.audio_quality.estimated_mos = mos
        return mos

    def get_quality_rating(self) -> str:
        """
        Get human-readable quality rating based on MOS score

        Returns:
            Quality rating string
        """
        mos = self.metrics.audio_quality.estimated_mos

        if mos >= 4.3:
            return "Excellent"
        elif mos >= 4.0:
            return "Good"
        elif mos >= 3.6:
            return "Fair"
        elif mos >= 3.1:
            return "Poor"
        else:
            return "Bad"

    def update_session_duration(self):
        """Update session duration"""
        self.metrics.duration_seconds = time.time() - self.metrics.start_time

    def finalize(self):
        """Finalize metrics on session end"""
        self.metrics.end_time = time.time()
        self.update_session_duration()

        # Calculate final MOS
        self.calculate_mos_score()

        logger.info("Session metrics finalized",
                   session_id=self.session_id,
                   duration=f"{self.metrics.duration_seconds:.1f}s",
                   mos=f"{self.metrics.audio_quality.estimated_mos:.2f}",
                   quality=self.get_quality_rating(),
                   loss_rate=f"{self.metrics.audio_quality.loss_rate_percent:.2f}%")

    def get_summary(self) -> dict:
        """
        Get metrics summary for logging/display

        Returns:
            Dictionary with key metrics
        """
        self.update_session_duration()
        mos = self.calculate_mos_score()

        return {
            'session_id': self.session_id,
            'duration_seconds': round(self.metrics.duration_seconds, 1),

            # Audio quality
            'audio_quality': {
                'mos_score': round(mos, 2),
                'quality_rating': self.get_quality_rating(),
                'jitter_ms': round(self.metrics.audio_quality.current_jitter_ms, 2),
                'avg_jitter_ms': round(self.metrics.audio_quality.avg_jitter_ms, 2),
                'max_jitter_ms': round(self.metrics.audio_quality.max_jitter_ms, 2),
                'loss_rate_percent': round(self.metrics.audio_quality.loss_rate_percent, 2),
                'packets_received': self.metrics.audio_quality.packets_received,
                'packets_lost': self.metrics.audio_quality.packets_lost,
            },

            # Network
            'network': {
                'bitrate_kbps_rx': round(self.metrics.network.bitrate_kbps_rx, 2),
                'bitrate_kbps_tx': round(self.metrics.network.bitrate_kbps_tx, 2),
                'bytes_received': self.metrics.network.bytes_received,
                'bytes_sent': self.metrics.network.bytes_sent,
            },

            # PLC
            'plc': {
                'packets_concealed': self.metrics.plc.packets_concealed,
                'max_consecutive_losses': self.metrics.plc.max_consecutive_losses,
                'level_1_percent': round(self.metrics.plc.level_1_percent, 1),
                'level_2_percent': round(self.metrics.plc.level_2_percent, 1),
                'level_3_percent': round(self.metrics.plc.level_3_percent, 1),
            },

            # Security
            'security': {
                'packets_dropped_replay': self.metrics.audio_quality.packets_dropped_replay,
                'sequence_jumps': self.metrics.network.sequence_jumps_detected,
            }
        }

    def get_detailed_metrics(self) -> dict:
        """
        Get detailed metrics for API/Prometheus export

        Returns:
            Complete metrics dictionary
        """
        self.update_session_duration()
        mos = self.calculate_mos_score()

        return {
            'session': {
                'session_id': self.session_id,
                'start_time': self.metrics.start_time,
                'end_time': self.metrics.end_time,
                'duration_seconds': round(self.metrics.duration_seconds, 2),
                'codec': self.metrics.codec,
                'sample_rate': self.metrics.sample_rate,
            },

            'audio_quality': {
                'mos_score': round(mos, 2),
                'quality_rating': self.get_quality_rating(),

                'jitter': {
                    'current_ms': round(self.metrics.audio_quality.current_jitter_ms, 2),
                    'average_ms': round(self.metrics.audio_quality.avg_jitter_ms, 2),
                    'max_ms': round(self.metrics.audio_quality.max_jitter_ms, 2),
                },

                'packets': {
                    'received': self.metrics.audio_quality.packets_received,
                    'lost': self.metrics.audio_quality.packets_lost,
                    'dropped_duplicate': self.metrics.audio_quality.packets_dropped_duplicate,
                    'dropped_late': self.metrics.audio_quality.packets_dropped_late,
                    'dropped_replay': self.metrics.audio_quality.packets_dropped_replay,
                    'loss_rate_percent': round(self.metrics.audio_quality.loss_rate_percent, 2),
                },

                'buffer': {
                    'depth_ms': self.metrics.audio_quality.buffer_depth_ms,
                    'underruns': self.metrics.audio_quality.buffer_underruns,
                    'overruns': self.metrics.audio_quality.buffer_overruns,
                },
            },

            'network': {
                'bytes_received': self.metrics.network.bytes_received,
                'bytes_sent': self.metrics.network.bytes_sent,
                'bitrate_kbps_rx': round(self.metrics.network.bitrate_kbps_rx, 2),
                'bitrate_kbps_tx': round(self.metrics.network.bitrate_kbps_tx, 2),
                'rtt_ms': self.metrics.network.rtt_ms,
                'sequence_jumps_detected': self.metrics.network.sequence_jumps_detected,
            },

            'plc': {
                'packets_concealed': self.metrics.plc.packets_concealed,
                'level_1_count': self.metrics.plc.plc_level_1_count,
                'level_2_count': self.metrics.plc.plc_level_2_count,
                'level_3_count': self.metrics.plc.plc_level_3_count,
                'consecutive_losses': self.metrics.plc.consecutive_losses,
                'max_consecutive_losses': self.metrics.plc.max_consecutive_losses,
                'level_1_percent': round(self.metrics.plc.level_1_percent, 1),
                'level_2_percent': round(self.metrics.plc.level_2_percent, 1),
                'level_3_percent': round(self.metrics.plc.level_3_percent, 1),
            }
        }
