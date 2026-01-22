"""
RTP Server - Manages RTP connections for multiple calls

Migrated from LiveKit SIP
"""

import asyncio
from typing import Dict, Optional
from dataclasses import dataclass

from ..common.logging import get_logger
from ..orchestrator.events import EventBus
from .connection import RTPConnection, RTPConnectionConfig
from .packet import RTPHeader
from .jitter_buffer import AdaptiveJitterBuffer, JitterBufferConfig
from .metrics import RTPMetricsCollector
from .dtmf import DTMFDetector, DTMFEvent
from .rtcp import RTCPReceiverReport, ReceptionReport, RTCPSenderReport, parse_rtcp_packet, RTCP_SR

logger = get_logger('rtp.server')


@dataclass
class RTPServerConfig:
    """RTP Server Configuration"""
    port_start: int = 10000
    port_end: int = 20000
    listen_addr: str = "0.0.0.0"
    media_timeout: float = 15.0
    media_timeout_initial: float = 30.0
    ip_validation_enabled: bool = True  # Enable IP validation for security

    # Jitter Buffer
    jitter_buffer_initial_ms: int = 60
    jitter_buffer_min_ms: int = 20
    jitter_buffer_max_ms: int = 300
    jitter_buffer_adaptation_rate: float = 0.1


class RTPSession:
    """RTP Session for a call"""

    def __init__(self, session_id: str, connection: RTPConnection,
                 jitter_buffer_config: Optional[JitterBufferConfig] = None):
        self.session_id = session_id
        self.connection = connection
        self.created_at = asyncio.get_event_loop().time()

        # Jitter Buffer
        if jitter_buffer_config is None:
            jitter_buffer_config = JitterBufferConfig()
        self.jitter_buffer = AdaptiveJitterBuffer(config=jitter_buffer_config)

        # Audio buffers (for future AI pipeline integration)
        self.audio_in_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.audio_out_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

        # DTMF Detection
        self.dtmf_detector = DTMFDetector(payload_type=101)
        self.dtmf_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        # Register DTMF callback to put events in queue
        def on_dtmf(event: DTMFEvent):
            try:
                self.dtmf_queue.put_nowait(event)
                logger.info("DTMF queued for AI processing",
                           session_id=self.session_id,
                           digit=event.digit)
            except asyncio.QueueFull:
                logger.warn("DTMF queue full - dropping event",
                           session_id=self.session_id,
                           digit=event.digit)

        self.dtmf_detector.on_dtmf(on_dtmf)

        # Stats
        self.packets_received = 0
        self.packets_sent = 0
        self.bytes_received = 0
        self.bytes_sent = 0

        # Metrics Collector
        self.metrics_collector = RTPMetricsCollector(session_id=session_id)

        # RTCP Tracking
        self.remote_ssrc: Optional[int] = None  # SSRC of remote sender
        self.local_ssrc: int = 0x12345678  # Our SSRC (same as in _send_test_audio)
        self.last_sr_ntp_timestamp: int = 0  # Middle 32 bits of NTP from last SR
        self.last_sr_received_time: float = 0  # When we received last SR (system time)
        self.rtt_ms: float = 0.0  # Round-Trip Time in milliseconds

        # RTCP Socket (will be created when session starts)
        self.rtcp_sock: Optional[asyncio.DatagramProtocol] = None
        self.rtcp_transport: Optional[asyncio.DatagramTransport] = None
        self.rtcp_local_port: Optional[int] = None
        self.rtcp_remote_addr: Optional[tuple] = None

        # Playout task
        self.playout_task: Optional[asyncio.Task] = None
        self.playout_running = False

        # RTCP task
        self.rtcp_task: Optional[asyncio.Task] = None
        self.rtcp_running = False

    def on_rtp_received(self, header: RTPHeader, payload: bytes):
        """Handle incoming RTP packet"""
        self.packets_received += 1
        self.bytes_received += len(payload)

        # Track remote SSRC (for RTCP)
        if self.remote_ssrc is None:
            self.remote_ssrc = header.ssrc
            logger.debug("Remote SSRC captured", session_id=self.session_id, ssrc=hex(header.ssrc))

        # Check for DTMF events (RFC 2833)
        dtmf_event = self.dtmf_detector.process_rtp(header, payload)
        if dtmf_event:
            # DTMF detected - callback already queued it
            # Don't push DTMF packets to jitter buffer (they're not audio)
            return

        # Push audio packets to jitter buffer
        accepted = self.jitter_buffer.push(header, payload)
        if not accepted:
            logger.debug("Packet rejected by jitter buffer",
                        seq=header.sequence_number,
                        session_id=self.session_id)
            return

        # Start playout loop on first packet
        if not self.playout_running:
            self.playout_running = True
            self.playout_task = asyncio.create_task(self._playout_loop())
            logger.info("Playout loop started", session_id=self.session_id)

        # TEST: Echo back silence to validate TX path
        # This sends RTP packets back to test transmission
        if self.packets_received % 50 == 1:  # Log every 50th packet
            asyncio.create_task(self._send_test_audio())

    async def _playout_loop(self):
        """
        Playout loop - pops packets from jitter buffer in sequence

        Handles:
        - Waiting for jitter buffer to fill
        - Packet loss (None returned from jitter buffer)
        - Timing (20ms per packet for PCMU)
        """
        packet_interval = 0.020  # 20ms for PCMU
        packets_output = 0

        logger.info("Playout loop starting", session_id=self.session_id)

        try:
            while self.playout_running:
                # Get next packet from jitter buffer (in sequence)
                # Jitter buffer now handles PLC internally - always returns a packet
                result = await self.jitter_buffer.pop()

                if result is None:
                    # Should not happen - jitter buffer now handles PLC
                    logger.error("Unexpected None from jitter buffer",
                               session_id=self.session_id)
                    continue

                header, payload = result
                packets_output += 1

                # Put in audio queue for AI pipeline
                try:
                    self.audio_in_queue.put_nowait((header, payload))
                except asyncio.QueueFull:
                    logger.warn("Audio input queue full - dropping packet",
                              session_id=self.session_id)

                # Update metrics and log periodically
                if packets_output % 50 == 0:
                    # Collect metrics from jitter buffer and connection
                    jb_stats = self.jitter_buffer.get_stats()
                    conn_stats = self.connection.get_stats()
                    dtmf_stats = self.dtmf_detector.get_stats()
                    rtcp_stats = {
                        'rtcp_running': self.rtcp_running,
                        'rtcp_local_port': self.rtcp_local_port,
                        'rtcp_remote_addr': self.rtcp_remote_addr
                    }

                    self.metrics_collector.update_from_jitter_buffer(jb_stats)
                    self.metrics_collector.update_from_connection(conn_stats)
                    self.metrics_collector.update_from_dtmf(dtmf_stats)
                    self.metrics_collector.update_from_rtcp(rtcp_stats, self.rtt_ms)

                    # Get metrics summary with MOS score
                    metrics_summary = self.metrics_collector.get_summary()

                    plc_stats = jb_stats.get('plc', {})
                    logger.info("Playout progress",
                               session_id=self.session_id,
                               packets_output=packets_output,
                               jitter_ms=jb_stats['current_jitter_ms'],
                               buffer_depth_ms=jb_stats['current_depth_ms'],
                               packets_lost=jb_stats['packets_lost'],
                               plc_concealed=plc_stats.get('packets_concealed', 0),
                               mos_score=metrics_summary['audio_quality']['mos_score'],
                               quality=metrics_summary['audio_quality']['quality_rating'])

                # Sleep for packet interval (20ms timing)
                await asyncio.sleep(packet_interval)

        except asyncio.CancelledError:
            logger.info("Playout loop cancelled", session_id=self.session_id)
        except Exception as e:
            logger.error("Error in playout loop", session_id=self.session_id, error=str(e))
        finally:
            logger.info("Playout loop stopped",
                       session_id=self.session_id,
                       packets_output=packets_output)

    async def _send_test_audio(self):
        """Send test audio packet (silence) to validate TX path"""
        import time

        # Generate silence payload for PCMU (160 bytes = 20ms @ 8kHz)
        # PCMU silence value is 0xFF (μ-law encoding of 0)
        silence_payload = bytes([0xFF] * 160)

        # Create RTP header
        # Use a separate SSRC for our outbound stream
        header = RTPHeader(
            version=2,
            padding=False,
            extension=False,
            marker=False,
            payload_type=0,  # PCMU
            sequence_number=self.packets_sent & 0xFFFF,  # Wrap at 16 bits
            timestamp=int(time.time() * 8000) & 0xFFFFFFFF,  # 8kHz clock
            ssrc=0x12345678  # Our SSRC
        )

        await self.send_rtp(header, silence_payload)
        logger.info("Test RTP packet sent",
                   session_id=self.session_id,
                   seq=header.sequence_number,
                   packets_sent=self.packets_sent)

    async def send_rtp(self, header: RTPHeader, payload: bytes):
        """Send RTP packet"""
        try:
            await self.connection.write_rtp(header, payload)
            self.packets_sent += 1
            self.bytes_sent += len(payload)
        except Exception as e:
            logger.error("Failed to send RTP", session_id=self.session_id, error=str(e))

    def generate_receiver_report(self) -> Optional[RTCPReceiverReport]:
        """
        Generate RTCP Receiver Report with reception quality statistics

        Returns:
            RTCPReceiverReport instance or None if no remote SSRC yet
        """
        if self.remote_ssrc is None:
            # No RTP packets received yet
            return None

        # Create RR packet with our SSRC
        rr = RTCPReceiverReport(ssrc=self.local_ssrc)

        # Get stats from jitter buffer and connection
        jb_stats = self.jitter_buffer.get_stats()

        # Calculate fraction lost (0-255, representing 0-100%)
        # Fraction lost since last RR
        total_expected = jb_stats.packets_received + jb_stats.packets_lost
        if total_expected > 0:
            loss_fraction = jb_stats.packets_lost / total_expected
            fraction_lost = min(255, int(loss_fraction * 256))
        else:
            fraction_lost = 0

        # Extended highest sequence number received
        # (RFC 3550: 16-bit cycle count + 16-bit highest seq)
        extended_highest_seq = jb_stats.highest_seq_received

        # Interarrival jitter (in RTP timestamp units)
        # For PCMU @ 8kHz: jitter_ms * 8 = jitter in timestamp units
        jitter_timestamp_units = int(jb_stats.current_jitter_ms * 8)

        # LSR (Last SR timestamp) - middle 32 bits of NTP timestamp from last SR
        lsr = self.last_sr_ntp_timestamp

        # DLSR (Delay since Last SR) - in units of 1/65536 seconds
        if self.last_sr_received_time > 0:
            import time
            delay_seconds = time.time() - self.last_sr_received_time
            dlsr = int(delay_seconds * 65536) & 0xFFFFFFFF
        else:
            dlsr = 0

        # Create reception report for remote sender
        report = ReceptionReport(
            ssrc=self.remote_ssrc,
            fraction_lost=fraction_lost,
            cumulative_lost=jb_stats.packets_lost,
            extended_highest_seq=extended_highest_seq,
            jitter=jitter_timestamp_units,
            last_sr_timestamp=lsr,
            delay_since_last_sr=dlsr
        )

        rr.add_report(report)

        logger.debug("Generated RTCP RR",
                    session_id=self.session_id,
                    fraction_lost=fraction_lost,
                    cumulative_lost=jb_stats.packets_lost,
                    jitter_ms=jb_stats.current_jitter_ms)

        return rr

    async def start_rtcp(self, local_rtp_port: int, remote_ip: str, remote_rtp_port: int):
        """
        Start RTCP socket and send loop

        Args:
            local_rtp_port: Local RTP port (RTCP will use RTP+1)
            remote_ip: Remote IP address
            remote_rtp_port: Remote RTP port (RTCP will use RTP+1)
        """
        # RTCP uses RTP port + 1 (RFC 3550)
        self.rtcp_local_port = local_rtp_port + 1
        remote_rtcp_port = remote_rtp_port + 1
        self.rtcp_remote_addr = (remote_ip, remote_rtcp_port)

        # Create RTCP socket
        loop = asyncio.get_event_loop()

        class RTCPProtocol(asyncio.DatagramProtocol):
            def __init__(self, session):
                self.session = session

            def datagram_received(self, data, addr):
                # Handle incoming RTCP packets (SR, RR, etc.)
                asyncio.create_task(self.session._on_rtcp_received(data, addr))

        try:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: RTCPProtocol(self),
                local_addr=('0.0.0.0', self.rtcp_local_port)
            )

            self.rtcp_transport = transport
            self.rtcp_sock = protocol

            logger.info("RTCP socket created",
                       session_id=self.session_id,
                       local_port=self.rtcp_local_port,
                       remote=f"{remote_ip}:{remote_rtcp_port}")

            # Start RTCP send loop
            self.rtcp_running = True
            self.rtcp_task = asyncio.create_task(self._rtcp_send_loop())

        except Exception as e:
            logger.error("Failed to create RTCP socket",
                        session_id=self.session_id,
                        error=str(e))

    async def _rtcp_send_loop(self):
        """
        RTCP send loop - sends Receiver Reports every 5 seconds (RFC 3550)
        """
        logger.info("RTCP send loop started", session_id=self.session_id)

        try:
            while self.rtcp_running:
                # Wait 5 seconds between reports (RFC 3550 recommends 5s)
                await asyncio.sleep(5.0)

                # Generate and send RR
                rr = self.generate_receiver_report()
                if rr and self.rtcp_transport:
                    rr_bytes = rr.serialize()
                    self.rtcp_transport.sendto(rr_bytes, self.rtcp_remote_addr)

                    logger.debug("RTCP RR sent",
                               session_id=self.session_id,
                               size=len(rr_bytes),
                               remote=self.rtcp_remote_addr)

        except asyncio.CancelledError:
            logger.info("RTCP send loop cancelled", session_id=self.session_id)
        except Exception as e:
            logger.error("Error in RTCP send loop",
                        session_id=self.session_id,
                        error=str(e))
        finally:
            logger.info("RTCP send loop stopped", session_id=self.session_id)

    async def _on_rtcp_received(self, data: bytes, addr: tuple):
        """
        Handle incoming RTCP packet

        Args:
            data: RTCP packet bytes
            addr: Source address (ip, port)
        """
        import time

        # Parse RTCP packet
        result = parse_rtcp_packet(data)
        if not result:
            logger.warn("Failed to parse RTCP packet",
                       session_id=self.session_id,
                       size=len(data))
            return

        packet_type, packet = result

        if packet_type == RTCP_SR:
            # Sender Report received
            sr: RTCPSenderReport = packet

            # Extract middle 32 bits of NTP timestamp from SR
            # This is used for RTT calculation
            ntp_timestamp = (sr.sender_info.ntp_timestamp_msw << 16) | (sr.sender_info.ntp_timestamp_lsw >> 16)
            ntp_middle_32 = ntp_timestamp & 0xFFFFFFFF

            # Store for later use in RR generation
            self.last_sr_ntp_timestamp = ntp_middle_32
            self.last_sr_received_time = time.time()

            # Check if SR contains RR about us (for RTT calculation)
            for report in sr.reception_reports:
                if report.ssrc == self.local_ssrc:
                    # This is a reception report about our transmitted RTP
                    # Calculate RTT using LSR and DLSR fields

                    # LSR: Last SR timestamp (middle 32 bits of NTP) that we sent
                    # DLSR: Delay since last SR (in units of 1/65536 seconds)
                    lsr = report.last_sr_timestamp
                    dlsr = report.delay_since_last_sr

                    if lsr != 0:  # Valid LSR
                        # Current time in NTP format (middle 32 bits)
                        current_time = time.time()
                        NTP_EPOCH_OFFSET = 2208988800
                        ntp_now = current_time + NTP_EPOCH_OFFSET
                        ntp_now_middle_32 = int((ntp_now * 65536)) & 0xFFFFFFFF

                        # RTT = (current_time - LSR) - DLSR
                        # All in units of 1/65536 seconds
                        rtt_ntp_units = ntp_now_middle_32 - lsr - dlsr

                        # Convert to seconds
                        rtt_seconds = rtt_ntp_units / 65536.0

                        # Convert to milliseconds
                        self.rtt_ms = rtt_seconds * 1000.0

                        logger.info("📊 RTT measured",
                                   session_id=self.session_id,
                                   rtt_ms=f"{self.rtt_ms:.2f}",
                                   fraction_lost=report.fraction_lost,
                                   cumulative_lost=report.cumulative_lost,
                                   jitter=report.jitter)

            logger.debug("RTCP SR received",
                        session_id=self.session_id,
                        sender_packets=sr.sender_info.sender_packet_count,
                        sender_bytes=sr.sender_info.sender_octet_count,
                        reports=len(sr.reception_reports))

        else:
            logger.debug("RTCP packet received",
                        session_id=self.session_id,
                        packet_type=packet_type,
                        size=len(data))

    async def stop_rtcp(self):
        """Stop RTCP socket and send loop"""
        self.rtcp_running = False

        # Stop send loop
        if self.rtcp_task:
            self.rtcp_task.cancel()
            try:
                await self.rtcp_task
            except asyncio.CancelledError:
                pass

        # Close socket
        if self.rtcp_transport:
            self.rtcp_transport.close()

        logger.info("RTCP stopped", session_id=self.session_id)

    def get_stats(self) -> dict:
        """Get session statistics with performance metrics"""
        # Update metrics from latest stats
        jb_stats = self.jitter_buffer.get_stats()
        conn_stats = self.connection.get_stats()
        dtmf_stats = self.dtmf_detector.get_stats()
        rtcp_stats = {
            'rtcp_running': self.rtcp_running,
            'rtcp_local_port': self.rtcp_local_port,
            'rtcp_remote_addr': self.rtcp_remote_addr
        }

        self.metrics_collector.update_from_jitter_buffer(jb_stats)
        self.metrics_collector.update_from_connection(conn_stats)
        self.metrics_collector.update_from_dtmf(dtmf_stats)
        self.metrics_collector.update_from_rtcp(rtcp_stats, self.rtt_ms)

        # Get comprehensive metrics
        metrics = self.metrics_collector.get_detailed_metrics()

        return {
            'session_id': self.session_id,
            'packets_received': self.packets_received,
            'packets_sent': self.packets_sent,
            'bytes_received': self.bytes_received,
            'bytes_sent': self.bytes_sent,
            'audio_in_queue_size': self.audio_in_queue.qsize(),
            'audio_out_queue_size': self.audio_out_queue.qsize(),
            'dtmf_queue_size': self.dtmf_queue.qsize(),
            'dtmf': self.dtmf_detector.get_stats(),
            'rtcp': {
                'rtt_ms': round(self.rtt_ms, 2),
                'rtcp_running': self.rtcp_running,
                'rtcp_local_port': self.rtcp_local_port,
                'rtcp_remote_addr': self.rtcp_remote_addr
            },
            'jitter_buffer': jb_stats,
            'connection': conn_stats,
            'metrics': metrics  # Comprehensive performance metrics with MOS score
        }


class RTPServer:
    """
    RTP Server

    Manages RTP connections for multiple simultaneous calls
    """

    def __init__(self, config: RTPServerConfig, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus

        # Active sessions
        self.sessions: Dict[str, RTPSession] = {}

        # Server state
        self.running = False

        logger.info("RTP Server initialized",
                   port_range=f"{config.port_start}-{config.port_end}",
                   listen_addr=config.listen_addr)

    async def start(self):
        """Start RTP server"""
        self.running = True
        logger.info("✅ RTP Server started")

    async def stop(self):
        """Stop RTP server"""
        logger.info("Stopping RTP Server...")

        self.running = False

        # Stop all sessions
        for session_id in list(self.sessions.keys()):
            await self.end_session(session_id)

        logger.info("✅ RTP Server stopped")

    async def create_session(self, session_id: str, remote_ip: str, remote_port: int) -> RTPSession:
        """
        Create RTP session for a call

        Args:
            session_id: Unique session identifier (from SIP)
            remote_ip: Remote RTP IP address
            remote_port: Remote RTP port

        Returns:
            RTPSession instance
        """
        if session_id in self.sessions:
            logger.warn("RTP session already exists", session_id=session_id)
            return self.sessions[session_id]

        # Create RTP connection
        conn_config = RTPConnectionConfig(
            media_timeout=self.config.media_timeout,
            media_timeout_initial=self.config.media_timeout_initial,
            ip_validation_enabled=self.config.ip_validation_enabled
        )
        connection = RTPConnection(config=conn_config)

        # Listen on available port
        local_port = await connection.listen(
            port_min=self.config.port_start,
            port_end=self.config.port_end,
            listen_addr=self.config.listen_addr
        )

        # Set remote address
        connection.set_remote_addr((remote_ip, remote_port))

        # Create jitter buffer config from server config
        jb_config = JitterBufferConfig(
            initial_depth_ms=self.config.jitter_buffer_initial_ms,
            min_depth_ms=self.config.jitter_buffer_min_ms,
            max_depth_ms=self.config.jitter_buffer_max_ms,
            packet_duration_ms=20,  # 20ms @ 8kHz PCMU
            adaptation_rate=self.config.jitter_buffer_adaptation_rate
        )

        # Create session
        session = RTPSession(
            session_id=session_id,
            connection=connection,
            jitter_buffer_config=jb_config
        )

        # Register RTP handler
        connection.on_rtp(session.on_rtp_received)

        # Register timeout handler
        def on_timeout():
            logger.warn("RTP timeout", session_id=session_id)
            asyncio.create_task(self.end_session(session_id))

        connection.on_timeout(on_timeout)

        # Start connection
        await connection.start()

        # Start RTCP
        await session.start_rtcp(local_port, remote_ip, remote_port)

        # Store session
        self.sessions[session_id] = session

        logger.info("RTP session created",
                   session_id=session_id,
                   local_port=local_port,
                   remote=f"{remote_ip}:{remote_port}",
                   active_sessions=len(self.sessions))

        return session

    async def end_session(self, session_id: str):
        """End RTP session"""
        session = self.sessions.get(session_id)
        if not session:
            return

        logger.info("Ending RTP session",
                   session_id=session_id,
                   packets_rx=session.packets_received,
                   packets_tx=session.packets_sent)

        # Stop playout loop
        if session.playout_task:
            session.playout_running = False
            session.playout_task.cancel()
            try:
                await session.playout_task
            except asyncio.CancelledError:
                pass

        # Stop RTCP
        await session.stop_rtcp()

        # Finalize metrics
        session.metrics_collector.finalize()

        # Stop connection
        await session.connection.stop()

        # Remove session
        del self.sessions[session_id]

        logger.info("RTP session removed",
                   session_id=session_id,
                   active_sessions=len(self.sessions))

    def get_session(self, session_id: str) -> Optional[RTPSession]:
        """Get RTP session by ID"""
        return self.sessions.get(session_id)

    def get_stats(self) -> dict:
        """Get server statistics"""
        return {
            'running': self.running,
            'active_sessions': len(self.sessions),
            'sessions': {
                sid: session.get_stats()
                for sid, session in self.sessions.items()
            }
        }
