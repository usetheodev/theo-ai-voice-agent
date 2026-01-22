"""
Metrics API Server

HTTP endpoints for RTP performance metrics and monitoring
"""

import json
from typing import Optional
from aiohttp import web

from ..common.logging import get_logger

logger = get_logger('api.metrics')


class MetricsAPIServer:
    """
    Metrics API Server

    Provides HTTP endpoints for:
    - /metrics - Prometheus-compatible metrics
    - /metrics/rtp - Detailed RTP metrics (JSON)
    - /metrics/rtp/{session_id} - Per-session metrics (JSON)
    - /health - Health check endpoint
    """

    def __init__(self, rtp_server, host: str = '0.0.0.0', port: int = 8001):
        """
        Initialize Metrics API Server

        Args:
            rtp_server: RTPServer instance to collect metrics from
            host: Listen address
            port: Listen port
        """
        self.rtp_server = rtp_server
        self.host = host
        self.port = port
        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None

        logger.info("Metrics API initialized", host=host, port=port)

    async def start(self):
        """Start metrics API server"""
        self.app = web.Application()

        # Register routes
        self.app.router.add_get('/health', self.handle_health)
        self.app.router.add_get('/metrics', self.handle_prometheus_metrics)
        self.app.router.add_get('/metrics/rtp', self.handle_rtp_metrics)
        self.app.router.add_get('/metrics/rtp/{session_id}', self.handle_session_metrics)

        # Start server
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()

        logger.info("✅ Metrics API started",
                   host=self.host,
                   port=self.port,
                   endpoints=['/health', '/metrics', '/metrics/rtp', '/metrics/rtp/{session_id}'])

    async def stop(self):
        """Stop metrics API server"""
        if self.runner:
            await self.runner.cleanup()
            logger.info("Metrics API stopped")

    async def handle_health(self, request: web.Request) -> web.Response:
        """
        Health check endpoint

        Returns:
            200 OK with server status
        """
        health = {
            'status': 'healthy',
            'rtp_server_running': self.rtp_server.running,
            'active_sessions': len(self.rtp_server.sessions)
        }

        return web.json_response(health)

    async def handle_rtp_metrics(self, request: web.Request) -> web.Response:
        """
        Get all RTP sessions metrics (JSON)

        Returns:
            Detailed metrics for all active RTP sessions
        """
        stats = self.rtp_server.get_stats()

        # Extract detailed metrics from each session
        detailed_sessions = {}
        for session_id, session_stats in stats.get('sessions', {}).items():
            if 'metrics' in session_stats:
                detailed_sessions[session_id] = session_stats['metrics']

        response = {
            'server': {
                'running': stats['running'],
                'active_sessions': stats['active_sessions']
            },
            'sessions': detailed_sessions
        }

        return web.json_response(response)

    async def handle_session_metrics(self, request: web.Request) -> web.Response:
        """
        Get specific RTP session metrics (JSON)

        Args:
            request: HTTP request with session_id in path

        Returns:
            Detailed metrics for specified session or 404
        """
        session_id = request.match_info['session_id']

        session = self.rtp_server.get_session(session_id)
        if not session:
            return web.json_response(
                {'error': 'Session not found', 'session_id': session_id},
                status=404
            )

        session_stats = session.get_stats()
        metrics = session_stats.get('metrics', {})

        return web.json_response(metrics)

    async def handle_prometheus_metrics(self, request: web.Request) -> web.Response:
        """
        Get Prometheus-compatible metrics

        Returns:
            Metrics in Prometheus text format
        """
        stats = self.rtp_server.get_stats()

        metrics_lines = []

        # Server metrics
        metrics_lines.append('# HELP rtp_server_running RTP server running status (1=running, 0=stopped)')
        metrics_lines.append('# TYPE rtp_server_running gauge')
        metrics_lines.append(f'rtp_server_running {1 if stats["running"] else 0}')

        metrics_lines.append('# HELP rtp_active_sessions Number of active RTP sessions')
        metrics_lines.append('# TYPE rtp_active_sessions gauge')
        metrics_lines.append(f'rtp_active_sessions {stats["active_sessions"]}')

        # Aggregate metrics from all sessions
        total_packets_rx = 0
        total_packets_tx = 0
        total_packets_lost = 0
        total_bytes_rx = 0
        total_bytes_tx = 0

        mos_scores = []
        jitter_values = []
        rtt_values = []
        total_dtmf_events = 0

        for session_id, session_stats in stats.get('sessions', {}).items():
            metrics_data = session_stats.get('metrics', {})

            # Packet metrics
            audio_quality = metrics_data.get('audio_quality', {})
            packets = audio_quality.get('packets', {})

            total_packets_rx += packets.get('received', 0)
            total_packets_lost += packets.get('lost', 0)

            # Network metrics
            network = metrics_data.get('network', {})
            total_bytes_rx += network.get('bytes_received', 0)
            total_bytes_tx += network.get('bytes_sent', 0)

            # MOS and jitter
            mos = audio_quality.get('mos_score', 0)
            if mos > 0:
                mos_scores.append(mos)

            jitter = audio_quality.get('jitter', {})
            current_jitter = jitter.get('current_ms', 0)
            if current_jitter > 0:
                jitter_values.append(current_jitter)

            # DTMF metrics
            dtmf = metrics_data.get('dtmf', {})
            total_dtmf_events += dtmf.get('dtmf_events_detected', 0)

            # RTCP metrics
            rtcp = metrics_data.get('rtcp', {})
            rtt = rtcp.get('rtt_ms')
            if rtt is not None and rtt > 0:
                rtt_values.append(rtt)

        # Aggregated packet metrics
        metrics_lines.append('# HELP rtp_packets_received_total Total RTP packets received')
        metrics_lines.append('# TYPE rtp_packets_received_total counter')
        metrics_lines.append(f'rtp_packets_received_total {total_packets_rx}')

        metrics_lines.append('# HELP rtp_packets_lost_total Total RTP packets lost')
        metrics_lines.append('# TYPE rtp_packets_lost_total counter')
        metrics_lines.append(f'rtp_packets_lost_total {total_packets_lost}')

        # Calculate loss rate
        if total_packets_rx + total_packets_lost > 0:
            loss_rate = (total_packets_lost / (total_packets_rx + total_packets_lost)) * 100
        else:
            loss_rate = 0.0

        metrics_lines.append('# HELP rtp_packet_loss_rate_percent Packet loss rate percentage')
        metrics_lines.append('# TYPE rtp_packet_loss_rate_percent gauge')
        metrics_lines.append(f'rtp_packet_loss_rate_percent {loss_rate:.2f}')

        # Bandwidth metrics
        metrics_lines.append('# HELP rtp_bytes_received_total Total bytes received')
        metrics_lines.append('# TYPE rtp_bytes_received_total counter')
        metrics_lines.append(f'rtp_bytes_received_total {total_bytes_rx}')

        metrics_lines.append('# HELP rtp_bytes_sent_total Total bytes sent')
        metrics_lines.append('# TYPE rtp_bytes_sent_total counter')
        metrics_lines.append(f'rtp_bytes_sent_total {total_bytes_tx}')

        # MOS score (average)
        if mos_scores:
            avg_mos = sum(mos_scores) / len(mos_scores)
        else:
            avg_mos = 0.0

        metrics_lines.append('# HELP rtp_mos_score Mean Opinion Score (1.0-5.0, higher is better)')
        metrics_lines.append('# TYPE rtp_mos_score gauge')
        metrics_lines.append(f'rtp_mos_score {avg_mos:.2f}')

        # Jitter (average)
        if jitter_values:
            avg_jitter = sum(jitter_values) / len(jitter_values)
        else:
            avg_jitter = 0.0

        metrics_lines.append('# HELP rtp_jitter_ms Average jitter in milliseconds')
        metrics_lines.append('# TYPE rtp_jitter_ms gauge')
        metrics_lines.append(f'rtp_jitter_ms {avg_jitter:.2f}')

        # RTT (average)
        if rtt_values:
            avg_rtt = sum(rtt_values) / len(rtt_values)
        else:
            avg_rtt = 0.0

        metrics_lines.append('# HELP rtcp_rtt_ms Average Round-Trip Time in milliseconds')
        metrics_lines.append('# TYPE rtcp_rtt_ms gauge')
        metrics_lines.append(f'rtcp_rtt_ms {avg_rtt:.2f}')

        # DTMF events (total)
        metrics_lines.append('# HELP dtmf_events_total Total DTMF events detected')
        metrics_lines.append('# TYPE dtmf_events_total counter')
        metrics_lines.append(f'dtmf_events_total {total_dtmf_events}')

        # Join all metrics with newlines
        metrics_text = '\n'.join(metrics_lines) + '\n'

        return web.Response(
            text=metrics_text,
            content_type='text/plain; version=0.0.4'
        )
