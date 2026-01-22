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


class RTPSession:
    """RTP Session for a call"""

    def __init__(self, session_id: str, connection: RTPConnection):
        self.session_id = session_id
        self.connection = connection
        self.created_at = asyncio.get_event_loop().time()

        # Audio buffers (for future AI pipeline integration)
        self.audio_in_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.audio_out_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

        # Stats
        self.packets_received = 0
        self.packets_sent = 0
        self.bytes_received = 0
        self.bytes_sent = 0

    def on_rtp_received(self, header: RTPHeader, payload: bytes):
        """Handle incoming RTP packet"""
        self.packets_received += 1
        self.bytes_received += len(payload)

        # Put audio in queue for processing
        try:
            self.audio_in_queue.put_nowait((header, payload))
        except asyncio.QueueFull:
            logger.warn("Audio input queue full", session_id=self.session_id)

        # TEST: Echo back silence to validate TX path
        # This sends RTP packets back to test transmission
        if self.packets_received % 50 == 1:  # Log every 50th packet
            asyncio.create_task(self._send_test_audio())

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

    def get_stats(self) -> dict:
        """Get session statistics"""
        return {
            'session_id': self.session_id,
            'packets_received': self.packets_received,
            'packets_sent': self.packets_sent,
            'bytes_received': self.bytes_received,
            'bytes_sent': self.bytes_sent,
            'audio_in_queue_size': self.audio_in_queue.qsize(),
            'audio_out_queue_size': self.audio_out_queue.qsize(),
            'connection': self.connection.get_stats()
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

        # Create session
        session = RTPSession(session_id=session_id, connection=connection)

        # Register RTP handler
        connection.on_rtp(session.on_rtp_received)

        # Register timeout handler
        def on_timeout():
            logger.warn("RTP timeout", session_id=session_id)
            asyncio.create_task(self.end_session(session_id))

        connection.on_timeout(on_timeout)

        # Start connection
        await connection.start()

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
