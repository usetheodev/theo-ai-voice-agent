"""
RTP Connection - UDP socket for RTP streaming

Migrated from LiveKit SIP - pkg/media/rtpconn/conn.go
"""

import asyncio
import socket
import time
from typing import Optional, Callable, Tuple
from dataclasses import dataclass

from ..common.logging import get_logger
from .packet import RTPPacket, RTPHeader

logger = get_logger('rtp.connection')


@dataclass
class RTPConnectionConfig:
    """RTP Connection Configuration"""
    media_timeout: float = 15.0  # seconds
    media_timeout_initial: float = 30.0  # seconds
    mtu_size: int = 1500
    ip_validation_enabled: bool = True  # Enable IP validation for security


class RTPConnection:
    """
    RTP Connection over UDP

    Handles receiving and sending RTP packets on a UDP socket
    """

    def __init__(self, config: Optional[RTPConnectionConfig] = None):
        self.config = config or RTPConnectionConfig()

        # Socket
        self.sock: Optional[socket.socket] = None
        self.local_addr: Optional[Tuple[str, int]] = None
        self.remote_addr: Optional[Tuple[str, int]] = None

        # State
        self.running = False
        self.packet_count = 0
        self.first_packet_received = False

        # IP Validation (Security)
        self.expected_remote_ip: Optional[str] = None
        self.ip_validation_enabled: bool = self.config.ip_validation_enabled

        # SSRC Tracking (Security - Hijacking Protection)
        self.expected_ssrc: Optional[int] = None
        self.ssrc_locked: bool = False

        # Statistics
        self.packets_accepted = 0
        self.packets_rejected_invalid_ip = 0
        self.packets_rejected_invalid_ssrc = 0
        self.hijacking_attempts = 0

        # Callbacks
        self.on_rtp_callback: Optional[Callable[[RTPHeader, bytes], None]] = None
        self.on_timeout_callback: Optional[Callable[[], None]] = None

        # Asyncio
        self.read_task: Optional[asyncio.Task] = None
        self.timeout_task: Optional[asyncio.Task] = None

        # Timing
        self.last_packet_time: Optional[float] = None

    async def listen(self, port_min: int, port_end: int, listen_addr: str = "0.0.0.0") -> int:
        """
        Listen on a UDP port in the given range

        Args:
            port_min: Minimum port number
            port_end: Maximum port number
            listen_addr: Address to bind to

        Returns:
            Port number that was bound

        Raises:
            OSError: If no port available
        """
        for port in range(port_min, port_end + 1):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.sock.bind((listen_addr, port))
                self.sock.setblocking(False)
                self.local_addr = (listen_addr, port)

                logger.info("RTP socket bound", addr=f"{listen_addr}:{port}")
                return port

            except OSError as e:
                if self.sock:
                    self.sock.close()
                    self.sock = None
                if port == port_end:
                    raise OSError(f"No ports available in range {port_min}-{port_end}") from e
                continue

        raise OSError(f"Failed to bind to any port in range {port_min}-{port_end}")

    async def start(self):
        """Start receiving RTP packets"""
        if not self.sock:
            raise RuntimeError("Socket not initialized. Call listen() first.")

        self.running = True
        self.read_task = asyncio.create_task(self._read_loop())

        if self.on_timeout_callback:
            self.timeout_task = asyncio.create_task(self._timeout_loop())

        logger.info("RTP connection started", local_addr=self.local_addr)

    async def stop(self):
        """Stop receiving RTP packets"""
        self.running = False

        if self.read_task:
            self.read_task.cancel()
            try:
                await self.read_task
            except asyncio.CancelledError:
                pass

        if self.timeout_task:
            self.timeout_task.cancel()
            try:
                await self.timeout_task
            except asyncio.CancelledError:
                pass

        if self.sock:
            self.sock.close()
            self.sock = None

        logger.info("RTP connection stopped")

    def set_remote_addr(self, addr: Tuple[str, int]):
        """Set remote address for sending packets"""
        self.remote_addr = addr
        logger.debug("Remote RTP address set", addr=f"{addr[0]}:{addr[1]}")

    def set_expected_remote_ip(self, ip: str):
        """
        Set expected remote IP from SIP SDP (security)

        Args:
            ip: Expected IP address from SIP negotiation
        """
        self.expected_remote_ip = ip
        logger.info("Expected remote IP set for validation",
                   ip=ip,
                   validation_enabled=self.ip_validation_enabled)

    def _validate_remote_ip(self, addr: Tuple[str, int]) -> bool:
        """
        Validate if packet is from expected source (anti-hijacking)

        Args:
            addr: Source address of incoming packet

        Returns:
            True if packet is from valid source, False otherwise
        """
        # Validation disabled - accept all
        if not self.ip_validation_enabled:
            return True

        # No expected IP set - log warning and accept first packet
        if not self.expected_remote_ip:
            logger.warn("No expected IP set - accepting first packet",
                       remote_ip=addr[0],
                       help="Set expected IP via set_expected_remote_ip()")
            return True

        # Validate IP matches expected
        if addr[0] != self.expected_remote_ip:
            logger.error("🚨 RTP HIJACKING ATTEMPT DETECTED",
                        expected_ip=self.expected_remote_ip,
                        actual_ip=addr[0],
                        action="PACKET_DROPPED",
                        severity="CRITICAL")
            self.hijacking_attempts += 1
            return False

        return True

    def _validate_ssrc(self, header: RTPHeader) -> bool:
        """
        Validate SSRC to prevent hijacking

        The first valid RTP packet locks the SSRC. Subsequent packets
        with a different SSRC are rejected as potential hijacking attempts.

        Args:
            header: RTP packet header

        Returns:
            True if SSRC is valid, False if rejected
        """
        # Lock SSRC on first valid packet
        if not self.ssrc_locked:
            self.expected_ssrc = header.ssrc
            self.ssrc_locked = True
            logger.info("SSRC locked",
                       ssrc=f"0x{header.ssrc:08x}")
            return True

        # Validate subsequent packets
        if header.ssrc != self.expected_ssrc:
            logger.error("🚨 SSRC MISMATCH - Possible hijacking attempt",
                        expected=f"0x{self.expected_ssrc:08x}",
                        actual=f"0x{header.ssrc:08x}",
                        action="PACKET_DROPPED",
                        severity="CRITICAL")
            self.hijacking_attempts += 1
            return False

        return True

    def reset_ssrc_lock(self):
        """
        Reset SSRC lock (e.g., on session restart)

        This allows a new RTP stream to be accepted with a different SSRC.
        Should be called when reusing the connection for a new session.
        """
        self.expected_ssrc = None
        self.ssrc_locked = False
        logger.info("SSRC lock reset")

    def on_rtp(self, callback: Callable[[RTPHeader, bytes], None]):
        """Register callback for incoming RTP packets"""
        self.on_rtp_callback = callback

    def on_timeout(self, callback: Callable[[], None]):
        """Register callback for timeout"""
        self.on_timeout_callback = callback

    async def _read_loop(self):
        """Read loop for incoming RTP packets"""
        loop = asyncio.get_event_loop()
        buf = bytearray(self.config.mtu_size + 1)

        # Event to signal data available
        data_ready = asyncio.Event()

        def on_readable():
            """Callback when socket has data"""
            data_ready.set()

        # Register callback for when socket is readable
        loop.add_reader(self.sock.fileno(), on_readable)

        try:
            while self.running:
                try:
                    # Wait for data to be available
                    await data_ready.wait()
                    data_ready.clear()

                    # Read from socket (non-blocking)
                    try:
                        data, addr = self.sock.recvfrom(len(buf))
                    except BlockingIOError:
                        # No data available yet, wait for next signal
                        continue

                    # Validate IP source (security check)
                    if not self._validate_remote_ip(addr):
                        self.packets_rejected_invalid_ip += 1
                        continue  # Drop packet from invalid source

                    # Update remote address from first packet
                    if not self.first_packet_received:
                        self.set_remote_addr(addr)
                        self.first_packet_received = True

                    # Check for oversized packets
                    if len(data) > self.config.mtu_size:
                        logger.warn("RTP packet exceeds MTU", size=len(data), mtu=self.config.mtu_size)
                        continue

                    # Parse RTP packet
                    try:
                        packet = RTPPacket.parse(data)
                    except ValueError as e:
                        logger.debug("Failed to parse RTP packet", error=str(e))
                        continue

                    # Validate SSRC (security check - hijacking protection)
                    if not self._validate_ssrc(packet.header):
                        self.packets_rejected_invalid_ssrc += 1
                        continue  # Drop packet with invalid SSRC

                    # Update stats
                    self.packet_count += 1
                    self.packets_accepted += 1
                    self.last_packet_time = time.time()

                    # Call handler
                    if self.on_rtp_callback:
                        try:
                            self.on_rtp_callback(packet.header, packet.payload)
                        except Exception as e:
                            logger.error("Error in RTP handler", error=str(e))

                    # Log first packet
                    if self.packet_count == 1:
                        logger.info("First RTP packet received", packet=str(packet))

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    if self.running:
                        logger.error("Error reading RTP packet", error=str(e))
        finally:
            # Remove reader callback
            loop.remove_reader(self.sock.fileno())

    async def _timeout_loop(self):
        """Monitor for RTP timeout"""
        timeout = self.config.media_timeout_initial

        while self.running:
            await asyncio.sleep(1.0)

            if not self.last_packet_time:
                continue

            # Switch to normal timeout after first packet
            if self.packet_count > 0:
                timeout = self.config.media_timeout

            # Check timeout
            elapsed = time.time() - self.last_packet_time
            if elapsed > timeout:
                logger.warn("RTP timeout", elapsed=f"{elapsed:.1f}s", timeout=f"{timeout:.1f}s")

                if self.on_timeout_callback:
                    try:
                        self.on_timeout_callback()
                    except Exception as e:
                        logger.error("Error in timeout callback", error=str(e))
                break

    async def write_rtp(self, header: RTPHeader, payload: bytes) -> int:
        """
        Send RTP packet

        Args:
            header: RTP header
            payload: RTP payload

        Returns:
            Number of bytes sent

        Raises:
            RuntimeError: If remote address not set
        """
        if not self.remote_addr:
            raise RuntimeError("Remote address not set. Call set_remote_addr() first.")

        # Marshal packet
        packet = RTPPacket(header=header, payload=payload)
        data = packet.marshal()

        # Send (use sendto directly, it's non-blocking)
        self.sock.sendto(data, self.remote_addr)

        return len(data)

    def get_stats(self) -> dict:
        """Get connection statistics"""
        return {
            'local_addr': self.local_addr,
            'remote_addr': self.remote_addr,
            'expected_remote_ip': self.expected_remote_ip,
            'expected_ssrc': f"0x{self.expected_ssrc:08x}" if self.expected_ssrc else None,
            'ssrc_locked': self.ssrc_locked,
            'packet_count': self.packet_count,
            'packets_accepted': self.packets_accepted,
            'packets_rejected_invalid_ip': self.packets_rejected_invalid_ip,
            'packets_rejected_invalid_ssrc': self.packets_rejected_invalid_ssrc,
            'hijacking_attempts': self.hijacking_attempts,
            'first_packet_received': self.first_packet_received,
            'last_packet_time': self.last_packet_time,
            'ip_validation_enabled': self.ip_validation_enabled,
            'running': self.running
        }
