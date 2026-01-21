"""
SIP Session Types and Data Structures

Migrated from LiveKit SIP (Go) - pkg/sip/types.go
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
from ipaddress import IPv4Address, IPv6Address
import socket


class Transport(str, Enum):
    """SIP Transport Protocol"""
    UDP = "udp"
    TCP = "tcp"
    TLS = "tls"


class CallStatus(str, Enum):
    """Call Session Status"""
    IDLE = "idle"
    RINGING = "ringing"
    ACTIVE = "active"
    HANGUP = "hangup"


@dataclass
class URI:
    """
    SIP URI representation

    Migrated from types.go:URI
    """
    user: str = ""
    host: str = ""
    port: int = 0
    ip: Optional[str] = None
    transport: Transport = Transport.UDP

    def normalize(self) -> 'URI':
        """Normalize the URI by resolving host/port"""
        if self.port == 0:
            self.port = 5061 if self.transport == Transport.TLS else 5060

        # Try to parse host as host:port
        if ':' in self.host:
            try:
                host, port_str = self.host.rsplit(':', 1)
                self.host = host
                self.port = int(port_str)
            except (ValueError, IndexError):
                pass

        return self

    def get_host(self) -> str:
        """Get the host (prefer IP if available)"""
        return self.ip if self.ip else self.host

    def get_port(self) -> int:
        """Get the port (with default)"""
        if self.port == 0:
            return 5061 if self.transport == Transport.TLS else 5060
        return self.port

    def get_port_or_none(self) -> int:
        """Get port or 0 if default (5060)"""
        port = self.get_port()
        return 0 if port == 5060 else port

    def get_host_port(self) -> str:
        """Get host:port string"""
        return f"{self.get_host()}:{self.get_port()}"

    def get_dest(self) -> str:
        """Get destination address (IP:port preferred)"""
        host = self.ip if self.ip else self.host
        return f"{host}:{self.get_port()}"

    def to_sip_uri(self) -> str:
        """Convert to SIP URI string"""
        uri = f"sip:{self.user}@{self.get_host()}"
        if self.get_port_or_none() != 0:
            uri += f":{self.get_port()}"
        if self.transport != Transport.UDP:
            uri += f";transport={self.transport.value}"
        return uri

    @classmethod
    def from_string(cls, uri_str: str) -> 'URI':
        """Parse SIP URI string"""
        uri = cls()

        # Remove sip: prefix
        if uri_str.startswith('sip:'):
            uri_str = uri_str[4:]
        elif uri_str.startswith('sips:'):
            uri_str = uri_str[5:]
            uri.transport = Transport.TLS

        # Split user@host
        if '@' in uri_str:
            user_part, host_part = uri_str.split('@', 1)
            uri.user = user_part
        else:
            host_part = uri_str

        # Parse transport parameter
        if ';transport=' in host_part:
            host_part, transport = host_part.split(';transport=', 1)
            uri.transport = Transport(transport.lower())

        # Parse host:port
        if ':' in host_part:
            try:
                host, port_str = host_part.rsplit(':', 1)
                uri.host = host
                uri.port = int(port_str)
            except (ValueError, IndexError):
                uri.host = host_part
        else:
            uri.host = host_part

        return uri.normalize()


@dataclass
class CallSession:
    """
    SIP Call Session State

    Shared between SIP Server and RTP Server
    Migrated from types.go (implicit structure)
    """
    # Session identifiers
    session_id: str                    # UUID unique
    call_id: str                       # SIP Call-ID header

    # SIP dialog
    from_uri: URI = field(default_factory=URI)
    to_uri: URI = field(default_factory=URI)
    remote_tag: str = ""
    local_tag: str = ""
    cseq: int = 0

    # Media (RTP)
    remote_ip: str = ""                # Remote RTP IP (from SDP)
    remote_port: int = 0               # Remote RTP port (from SDP)
    local_port: int = 0                # Local RTP port allocated
    codec: str = "PCMU"                # Negotiated codec

    # State
    status: CallStatus = CallStatus.IDLE

    # Metadata
    caller_id: Optional[str] = None    # Caller display name
    trunk_id: Optional[str] = None     # Associated trunk ID
    remote_sdp: str = ""               # Full remote SDP (for debug)
    local_sdp: str = ""                # Full local SDP

    # Timestamps
    created_at: Optional[float] = None
    answered_at: Optional[float] = None
    ended_at: Optional[float] = None

    def get_duration(self) -> float:
        """Get call duration in seconds"""
        if not self.answered_at:
            return 0.0
        end = self.ended_at if self.ended_at else None
        if end:
            return end - self.answered_at
        # Call still active
        import time
        return time.time() - self.answered_at


@dataclass
class AuthInfo:
    """
    Authentication Information for SIP Trunk

    Migrated from server.go:AuthInfo
    """
    username: str
    password: str
    realm: str = "voiceagent"
    trunk_id: Optional[str] = None
    project_id: Optional[str] = None


class AuthResult(Enum):
    """
    Authentication Result

    Migrated from server.go:AuthResult
    """
    NOT_FOUND = "not_found"           # No matching trunk
    DROP = "drop"                     # Drop silently (suspicious IP)
    PASSWORD = "password"             # Requires Digest Auth
    ACCEPT = "accept"                 # Accept (IP whitelisted)
    QUOTA_EXCEEDED = "quota_exceeded" # Rate limit
    NO_TRUNK_FOUND = "no_trunk_found" # No trunk configured


@dataclass
class RoomConfig:
    """
    LiveKit Room Configuration for Call

    Migrated from server.go:RoomConfig
    """
    room_name: str
    participant_identity: str = ""
    participant_name: str = ""
    participant_metadata: str = ""


class DispatchResult(Enum):
    """
    Call Dispatch Decision

    Migrated from server.go:DispatchResult
    """
    ACCEPT = "accept"                 # Accept and route to room
    REQUEST_PIN = "request_pin"       # Request PIN from caller
    NO_RULE_REJECT = "no_rule_reject" # Reject with error
    NO_RULE_DROP = "no_rule_drop"     # Drop silently


@dataclass
class CallDispatch:
    """
    Call Routing Decision

    Migrated from server.go:CallDispatch
    """
    result: DispatchResult
    room: Optional[RoomConfig] = None
    project_id: str = ""
    trunk_id: str = ""
    dispatch_rule_id: str = ""
    pin: str = ""
    no_pin: bool = False


# Constants (migrated from LiveKit SIP)
USER_AGENT = "AI-Voice-Agent/1.0"
INVITE_OK_RETRY_INTERVAL = 0.25      # 250ms (1/2 of T1)
INVITE_OK_RETRY_INTERVAL_MAX = 3.0   # 3 seconds
INVITE_OK_RETRY_ATTEMPTS = 5
AUDIO_BRIDGE_MAX_DELAY = 1.0         # 1 second (battle-tested from LiveKit)
