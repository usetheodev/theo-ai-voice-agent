"""
SIP Server Implementation

Migrated from LiveKit SIP (Go) - pkg/sip/server.go

This is a minimal SIP User Agent that:
1. Listens for INVITE requests
2. Responds with 200 OK
3. Handles ACK and BYE
4. Emits events to EventBus
"""

import asyncio
import socket
import uuid
import time
from typing import Optional, Dict
from dataclasses import dataclass, field

from ..common.logging import get_logger
from ..orchestrator.events import EventBus

from .session import (
    CallSession, CallStatus, URI, Transport, AuthInfo,
    USER_AGENT, INVITE_OK_RETRY_INTERVAL, INVITE_OK_RETRY_ATTEMPTS
)
from .rate_limiter import RateLimiter, RateLimitConfig as RLConfig
from .protocol import (
    SIPMethod, SIPStatus, generate_tag, generate_call_id, generate_branch,
    parse_via_header, build_via_header, parse_contact_header, build_contact_header,
    status_name
)
from .events import (
    EventType, CallInviteEvent, CallEstablishedEvent, CallEndedEvent, CallFailedEvent
)
from .sdp import SDPParser, SDPGenerator, negotiate_codec, extract_remote_address
from .auth import DigestAuthenticator, DigestAlgorithm


logger = get_logger('sip.server')


@dataclass
class SIPServerConfig:
    """SIP Server Configuration (internal use)"""
    host: str = "0.0.0.0"
    port: int = 5060
    realm: str = "voiceagent"
    external_ip: Optional[str] = None

    # Codecs supported (in priority order)
    codecs: list = field(default_factory=lambda: ["PCMU", "PCMA", "opus"])

    # RTP port range
    rtp_port_start: int = 10000
    rtp_port_end: int = 20000

    # Authentication
    auth_enabled: bool = True
    trunks: list = field(default_factory=list)  # List of {username, password, trunk_id}

    # IP Access Control
    ip_whitelist: list = field(default_factory=list)
    ip_blacklist: list = field(default_factory=list)

    # Rate Limiting
    rate_limit: 'RLConfig' = field(default_factory=lambda: RLConfig())


class SIPServer:
    """
    SIP Server (User Agent)

    Minimal SIP implementation for accepting calls from any SIP source.
    Migrated from LiveKit SIP server.go
    """

    def __init__(self, config: SIPServerConfig, event_bus: EventBus, rtp_server=None):
        self.config = config
        self.event_bus = event_bus
        self.rtp_server = rtp_server  # Optional RTP server for audio

        # Active sessions
        self.sessions: Dict[str, CallSession] = {}

        # UDP socket
        self.sock: Optional[socket.socket] = None
        self.transport: Optional[asyncio.DatagramTransport] = None

        # Server state
        self.running = False
        self.local_ip = config.external_ip or self._get_local_ip()

        # RTP port allocation
        self.next_rtp_port = config.rtp_port_start

        # Digest Authentication
        self.authenticator: Optional[DigestAuthenticator] = None
        if config.auth_enabled and config.trunks:
            # Build users dict from trunks
            users = {trunk['username']: trunk['password'] for trunk in config.trunks}
            self.authenticator = DigestAuthenticator(
                realm=config.realm,
                users=users,
                nonce_timeout=300,  # 5 minutes
                preferred_algorithm=DigestAlgorithm.MD5
            )
            logger.info("🔐 Authentication ENABLED",
                       realm=config.realm,
                       algorithm=self.authenticator.preferred_algorithm.value,
                       trunks=len(users),
                       nonce_timeout=f"{self.authenticator.nonce_timeout}s")
        else:
            logger.warn("⚠️ Authentication DISABLED - accepting all calls!",
                       help="Set auth_enabled=true and configure trunks in config")

        # Rate Limiting
        self.rate_limiter: Optional[RateLimiter] = None
        if config.rate_limit and config.rate_limit.enabled:
            rl_config = RLConfig(
                requests_per_minute=config.rate_limit.requests_per_minute,
                burst_size=config.rate_limit.burst_size,
                ban_threshold=config.rate_limit.ban_threshold,
                ban_duration_seconds=config.rate_limit.ban_duration_seconds,
                violation_window_seconds=config.rate_limit.violation_window_seconds,
                cleanup_interval_seconds=config.rate_limit.cleanup_interval_seconds
            )
            self.rate_limiter = RateLimiter(rl_config)

            # Initialize whitelist/blacklist from config
            if config.ip_whitelist:
                for ip in config.ip_whitelist:
                    self.rate_limiter.add_to_whitelist(ip)
            if config.ip_blacklist:
                for ip in config.ip_blacklist:
                    self.rate_limiter.add_to_blacklist(ip)
        else:
            logger.warn("⚠️ Rate Limiting DISABLED - no DDoS protection!",
                       help="Set rate_limit.enabled=true in config")

        logger.info("SIP Server initialized",
                   host=config.host,
                   port=config.port,
                   local_ip=self.local_ip)

    def _get_local_ip(self) -> str:
        """Get local IP address"""
        try:
            # Create a socket to determine local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "127.0.0.1"

    def _allocate_rtp_port(self) -> int:
        """Allocate next available RTP port"""
        port = self.next_rtp_port
        self.next_rtp_port += 2  # RTP + RTCP

        if self.next_rtp_port > self.config.rtp_port_end:
            self.next_rtp_port = self.config.rtp_port_start

        return port

    async def start(self):
        """Start SIP server"""
        logger.info("Starting SIP Server...", host=self.config.host, port=self.config.port)

        # Create UDP socket
        loop = asyncio.get_event_loop()

        self.transport, protocol = await loop.create_datagram_endpoint(
            lambda: SIPProtocol(self),
            local_addr=(self.config.host, self.config.port)
        )

        self.running = True

        # Start cleanup task for rate limiter
        if self.rate_limiter:
            asyncio.create_task(self._rate_limiter_cleanup_task())

        logger.info("✅ SIP Server started",
                   host=self.config.host,
                   port=self.config.port,
                   local_ip=self.local_ip)

    async def stop(self):
        """Stop SIP server"""
        logger.info("Stopping SIP Server...")

        self.running = False

        if self.transport:
            self.transport.close()

        # End all active sessions
        for session_id in list(self.sessions.keys()):
            await self._end_session(session_id, "server_shutdown")

        logger.info("✅ SIP Server stopped")

    async def handle_message(self, data: bytes, addr: tuple):
        """
        Handle incoming SIP message

        Args:
            data: Raw SIP message
            addr: (host, port) tuple
        """
        try:
            message = data.decode('utf-8')

            # Parse first line to determine message type
            lines = message.split('\r\n')
            if not lines:
                return

            first_line = lines[0]

            if first_line.startswith('SIP/2.0'):
                # Response
                await self._handle_response(message, addr)
            else:
                # Request
                await self._handle_request(message, addr)

        except Exception as e:
            logger.error("Error handling SIP message", error=str(e), addr=addr)

    async def _handle_request(self, message: str, addr: tuple):
        """Handle SIP request"""
        lines = message.split('\r\n')
        first_line = lines[0]

        # Parse request line: "INVITE sip:agent@host SIP/2.0"
        parts = first_line.split()
        if len(parts) < 3:
            logger.warn("Invalid request line", line=first_line)
            return

        method = parts[0]
        request_uri = parts[1]

        logger.debug("SIP request received", method=method, from_addr=addr)

        # Route to handler
        if method == SIPMethod.INVITE:
            await self._handle_invite(message, addr)
        elif method == SIPMethod.ACK:
            await self._handle_ack(message, addr)
        elif method == SIPMethod.BYE:
            await self._handle_bye(message, addr)
        elif method == SIPMethod.CANCEL:
            await self._handle_cancel(message, addr)
        elif method == SIPMethod.OPTIONS:
            await self._handle_options(message, addr)
        else:
            logger.warn("Unsupported SIP method", method=method)
            # Send 501 Not Implemented
            await self._send_response(message, addr, SIPStatus.NOT_IMPLEMENTED)

    async def _handle_response(self, message: str, addr: tuple):
        """Handle SIP response"""
        lines = message.split('\r\n')
        first_line = lines[0]

        # Parse status line: "SIP/2.0 200 OK"
        parts = first_line.split(None, 2)
        if len(parts) < 2:
            return

        status_code = int(parts[1])
        logger.debug("SIP response received", status=status_code, from_addr=addr)

    async def _handle_invite(self, message: str, addr: tuple):
        """
        Handle INVITE request

        This is the main call setup logic with digest authentication
        """
        headers = self._parse_headers(message)
        body = self._extract_body(message)

        call_id = headers.get('call-id', '')
        from_header = headers.get('from', '')
        to_header = headers.get('to', '')
        via_header = headers.get('via', '')
        cseq = headers.get('cseq', '')
        contact = headers.get('contact', '')
        authorization = headers.get('authorization', '')

        if not call_id:
            logger.warn("INVITE missing Call-ID")
            return

        logger.info("📞 INVITE received", call_id=call_id, from_addr=addr)

        # ===== RATE LIMITING CHECK =====
        client_ip = addr[0]
        if self.rate_limiter:
            is_allowed, reason = self.rate_limiter.is_allowed(client_ip, "INVITE")
            if not is_allowed:
                logger.warn("🚫 Rate limit exceeded - rejecting INVITE",
                           call_id=call_id,
                           client_ip=client_ip,
                           reason=reason)
                await self._send_response(
                    message, addr,
                    SIPStatus.SERVICE_UNAVAILABLE,
                    "Service Unavailable - Rate Limit Exceeded"
                )
                return

        # ===== AUTHENTICATION CHECK =====
        if self.authenticator:
            # Extract caller for logging (before full parsing)
            from_user = from_header.split(':')[1].split('@')[0] if ':' in from_header and '@' in from_header else 'unknown'

            if not authorization:
                # No Authorization header - send 401 challenge
                logger.info("🔐 No auth credentials - sending 401 challenge",
                          call_id=call_id,
                          from_user=from_user,
                          algorithm=self.authenticator.preferred_algorithm.value)
                await self._send_auth_challenge(message, addr)
                return

            # Parse Authorization header
            credentials = DigestAuthenticator.parse_authorization_header(authorization)
            if not credentials:
                logger.warn("🔒 Invalid Authorization header format",
                          call_id=call_id,
                          from_user=from_user,
                          auth_header_prefix=authorization[:50] + "..." if len(authorization) > 50 else authorization)
                await self._send_response(message, addr, SIPStatus.BAD_REQUEST, "Invalid Authorization")
                return

            # Validate credentials
            is_valid, error_msg = self.authenticator.validate_response(
                credentials=credentials,
                method=SIPMethod.INVITE
            )

            if not is_valid:
                logger.warn("🔒 Authentication validation failed",
                          call_id=call_id,
                          username=credentials.username,
                          algorithm=credentials.algorithm.value,
                          realm=credentials.realm,
                          error=error_msg)
                # Check if we should try MD5 fallback
                if credentials.algorithm == DigestAlgorithm.SHA256:
                    # Client used SHA-256 but failed - send MD5 challenge
                    logger.info("🔄 SHA-256 failed, trying MD5 fallback", call_id=call_id)
                    await self._send_auth_challenge(message, addr, algorithm=DigestAlgorithm.MD5)
                    return
                else:
                    # MD5 also failed or already was MD5 - reject with 403
                    logger.error("❌ Authentication failed - rejecting call",
                               call_id=call_id,
                               username=credentials.username,
                               error=error_msg)
                    await self._send_response(message, addr, SIPStatus.FORBIDDEN, "Authentication Failed")
                    return

            logger.info("✅ Authentication successful",
                       call_id=call_id,
                       username=credentials.username,
                       algorithm=credentials.algorithm.value,
                       realm=credentials.realm)

        # Create session
        session_id = str(uuid.uuid4())

        # Parse From/To URIs
        from_uri = self._parse_name_addr(from_header)
        to_uri = self._parse_name_addr(to_header)

        # Extract caller info
        caller_id = self._extract_display_name(from_header) or from_uri.user

        # Parse SDP
        if not body:
            logger.warn("INVITE missing SDP")
            await self._send_response(message, addr, SIPStatus.BAD_REQUEST, "Missing SDP")
            return

        # Extract remote RTP address
        remote_ip, remote_port = extract_remote_address(body)
        if not remote_ip or not remote_port:
            logger.error("Failed to extract RTP address from SDP")
            await self._send_response(message, addr, SIPStatus.BAD_REQUEST, "Invalid SDP")
            return

        # Negotiate codec
        codec = negotiate_codec(body, self.config.codecs)
        if not codec:
            logger.error("No compatible codec found")
            await self._send_response(message, addr, SIPStatus.NOT_ACCEPTABLE_HERE, "No compatible codec")
            return

        logger.info("Codec negotiated", codec=codec)

        # Allocate local RTP port
        local_rtp_port = self._allocate_rtp_port()

        # Create session
        session = CallSession(
            session_id=session_id,
            call_id=call_id,
            from_uri=from_uri,
            to_uri=to_uri,
            remote_ip=remote_ip,
            remote_port=remote_port,
            local_port=local_rtp_port,
            codec=codec,
            status=CallStatus.RINGING,
            caller_id=caller_id,
            remote_sdp=body,
            created_at=time.time()
        )

        self.sessions[session_id] = session

        # Create RTP session if RTP server available
        if self.rtp_server:
            try:
                rtp_session = await self.rtp_server.create_session(
                    session_id=session_id,
                    remote_ip=remote_ip,
                    remote_port=remote_port
                )
                # Update local port with actual RTP port
                session.local_port = rtp_session.connection.local_addr[1]
                logger.info("RTP session created", session_id=session_id, port=session.local_port)
            except Exception as e:
                logger.error("Failed to create RTP session", error=str(e))
                await self._send_response(message, addr, SIPStatus.SERVER_ERROR, "RTP setup failed")
                del self.sessions[session_id]
                return

        # Emit INVITE event
        invite_event = CallInviteEvent(
            session_id=session_id,
            caller_id=caller_id,
            caller_uri=from_uri.to_sip_uri(),
            called_number=to_uri.user,
            sdp_offer=body
        )
        await self.event_bus.publish(invite_event)

        # Send 200 OK
        await self._send_invite_ok(message, addr, session)

        logger.info("✅ Call established",
                   session_id=session_id,
                   codec=codec,
                   rtp=f"{remote_ip}:{remote_port} -> {self.local_ip}:{local_rtp_port}")

    async def _send_invite_ok(self, invite_message: str, addr: tuple, session: CallSession):
        """Send 200 OK for INVITE"""
        headers = self._parse_headers(invite_message)

        # Generate local SDP
        local_sdp = SDPGenerator.generate(
            local_ip=self.local_ip,
            local_port=session.local_port,
            codecs=[session.codec]
        )

        session.local_sdp = local_sdp

        # Build 200 OK response
        response = self._build_response(
            invite_message,
            SIPStatus.OK,
            "OK",
            body=local_sdp,
            extra_headers={
                'Content-Type': 'application/sdp',
                'Contact': f'<sip:{self.local_ip}:{self.config.port}>'
            }
        )

        # Send response
        await self._send_raw(response, addr)

        # Update session status
        session.status = CallStatus.ACTIVE
        session.answered_at = time.time()

        # Emit ESTABLISHED event
        established_event = CallEstablishedEvent(session=session)
        await self.event_bus.publish(established_event)

    async def _send_auth_challenge(
        self,
        invite_message: str,
        addr: tuple,
        algorithm: Optional[DigestAlgorithm] = None
    ):
        """
        Send 401 Unauthorized with WWW-Authenticate challenge

        Args:
            invite_message: Original INVITE message
            addr: Client address
            algorithm: Digest algorithm (None = use preferred)
        """
        if not self.authenticator:
            return

        # Generate challenge
        challenge = self.authenticator.generate_challenge(algorithm=algorithm)

        # Build WWW-Authenticate header
        www_auth = self.authenticator.build_www_authenticate_header(challenge)

        # Send 401 Unauthorized
        await self._send_response(
            invite_message,
            addr,
            SIPStatus.UNAUTHORIZED,
            "Unauthorized",
            extra_headers={'WWW-Authenticate': www_auth}
        )

        logger.info("🔐 401 Unauthorized challenge sent",
                   algorithm=challenge.algorithm.value,
                   realm=challenge.realm,
                   qop=challenge.qop,
                   nonce_timeout=f"{self.authenticator.nonce_timeout}s")

    async def _handle_ack(self, message: str, addr: tuple):
        """Handle ACK request"""
        headers = self._parse_headers(message)
        call_id = headers.get('call-id', '')

        logger.debug("ACK received", call_id=call_id)

        # ACK confirms 200 OK was received - nothing more to do

    async def _handle_bye(self, message: str, addr: tuple):
        """Handle BYE request"""
        headers = self._parse_headers(message)
        call_id = headers.get('call-id', '')

        logger.info("BYE received", call_id=call_id)

        # Find session by call_id
        session = None
        for s in self.sessions.values():
            if s.call_id == call_id:
                session = s
                break

        if not session:
            logger.warn("BYE for unknown call", call_id=call_id)
            # Still send 200 OK
            await self._send_response(message, addr, SIPStatus.OK)
            return

        # Send 200 OK
        await self._send_response(message, addr, SIPStatus.OK)

        # End session
        await self._end_session(session.session_id, "remote_hangup")

    async def _handle_cancel(self, message: str, addr: tuple):
        """Handle CANCEL request"""
        headers = self._parse_headers(message)
        call_id = headers.get('call-id', '')

        logger.info("CANCEL received", call_id=call_id)

        # Send 200 OK for CANCEL
        await self._send_response(message, addr, SIPStatus.OK)

        # Find and end session
        for session in list(self.sessions.values()):
            if session.call_id == call_id:
                await self._end_session(session.session_id, "cancelled")
                break

    async def _handle_options(self, message: str, addr: tuple):
        """Handle OPTIONS request"""
        logger.debug("OPTIONS received")

        # Send 200 OK with capabilities
        await self._send_response(
            message, addr, SIPStatus.OK, "OK",
            extra_headers={
                'Allow': 'INVITE, ACK, BYE, CANCEL, OPTIONS',
                'Accept': 'application/sdp'
            }
        )

    async def _end_session(self, session_id: str, reason: str):
        """End a call session"""
        session = self.sessions.get(session_id)
        if not session:
            return

        session.status = CallStatus.HANGUP
        session.ended_at = time.time()

        duration = session.get_duration()

        logger.info("Call ended",
                   session_id=session_id,
                   reason=reason,
                   duration=f"{duration:.1f}s")

        # End RTP session
        if self.rtp_server:
            await self.rtp_server.end_session(session_id)

        # Emit ENDED event
        ended_event = CallEndedEvent(
            session_id=session_id,
            reason=reason,
            duration=duration
        )
        await self.event_bus.publish(ended_event)

        # Remove session
        del self.sessions[session_id]

    def _parse_headers(self, message: str) -> Dict[str, str]:
        """Parse SIP headers"""
        headers = {}
        lines = message.split('\r\n')

        for line in lines[1:]:  # Skip first line (request/status)
            if not line or line == '\r\n':
                break

            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.lower().strip()] = value.strip()

        return headers

    def _extract_body(self, message: str) -> str:
        """Extract message body (SDP)"""
        parts = message.split('\r\n\r\n', 1)
        if len(parts) > 1:
            return parts[1]
        return ""

    def _parse_name_addr(self, header: str) -> URI:
        """Parse Name-Addr format: "Display Name" <sip:user@host>"""
        if '<' in header and '>' in header:
            uri_str = header[header.index('<')+1:header.index('>')]
        else:
            uri_str = header.split(';')[0].strip()

        return URI.from_string(uri_str)

    def _extract_display_name(self, header: str) -> Optional[str]:
        """Extract display name from From/To header"""
        if '<' in header:
            display = header[:header.index('<')].strip(' "')
            return display if display else None
        return None

    def _build_response(self, request: str, status_code: int, reason: str,
                       body: str = "", extra_headers: Optional[Dict[str, str]] = None) -> str:
        """Build SIP response"""
        headers = self._parse_headers(request)

        # Status line
        response_lines = [f"SIP/2.0 {status_code} {reason}"]

        # Copy required headers
        for header in ['via', 'from', 'to', 'call-id', 'cseq']:
            if header in headers:
                response_lines.append(f"{header.capitalize()}: {headers[header]}")

        # Add extra headers
        if extra_headers:
            for key, value in extra_headers.items():
                response_lines.append(f"{key}: {value}")

        # Content-Length
        response_lines.append(f"Content-Length: {len(body)}")

        # Blank line + body
        response = '\r\n'.join(response_lines) + '\r\n\r\n' + body

        return response

    async def _send_response(self, request: str, addr: tuple, status_code: int,
                            reason: str = "", extra_headers: Optional[Dict[str, str]] = None):
        """Send SIP response"""
        if not reason:
            reason = status_name(status_code)

        response = self._build_response(request, status_code, reason, extra_headers=extra_headers)
        await self._send_raw(response, addr)

    async def _send_raw(self, message: str, addr: tuple):
        """Send raw SIP message"""
        if self.transport:
            self.transport.sendto(message.encode('utf-8'), addr)
            logger.debug("SIP message sent", to_addr=addr, size=len(message))

    async def _rate_limiter_cleanup_task(self):
        """Periodic cleanup task for rate limiter"""
        if not self.rate_limiter or not self.config.rate_limit:
            return

        interval = self.config.rate_limit.cleanup_interval_seconds

        logger.info("🧹 Rate limiter cleanup task started",
                   interval=f"{interval}s")

        while self.running:
            await asyncio.sleep(interval)

            if not self.running:
                break

            # Run cleanup
            self.rate_limiter.cleanup()

            # Log statistics
            stats = self.rate_limiter.get_stats()
            logger.debug("Rate limiter stats",
                        active_buckets=stats['active_buckets'],
                        banned_ips=stats['banned_ips'],
                        whitelisted=stats['whitelisted_ips'],
                        blacklisted=stats['blacklisted_ips'])

        logger.info("🧹 Rate limiter cleanup task stopped")


class SIPProtocol(asyncio.DatagramProtocol):
    """
    Asyncio UDP Protocol for SIP
    """

    def __init__(self, server: SIPServer):
        self.server = server

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple):
        """Handle incoming datagram"""
        asyncio.create_task(self.server.handle_message(data, addr))

    def error_received(self, exc):
        logger.error("Protocol error", error=str(exc))
