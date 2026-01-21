"""
SIP Module - Session Initiation Protocol Implementation

Migrated from LiveKit SIP (Go)

Public API for SIP Server functionality
"""

from .server import SIPServer, SIPConfig, SIPProtocol
from .session import (
    CallSession,
    CallStatus,
    URI,
    Transport,
    AuthInfo,
    AuthResult,
    RoomConfig,
    DispatchResult,
    CallDispatch,
    USER_AGENT
)
from .protocol import (
    SIPMethod,
    SIPStatus,
    STATUS_NAMES,
    status_name,
    generate_tag,
    generate_call_id,
    generate_branch,
    compute_digest_response,
    parse_www_authenticate,
    build_authorization_header
)
from .events import (
    EventType,
    SIPEvent,
    CallInviteEvent,
    CallEstablishedEvent,
    CallEndedEvent,
    CallFailedEvent,
    DTMFEvent
)
from .sdp import (
    SDP,
    SDPMedia,
    SDPCodec,
    SDPParser,
    SDPGenerator,
    negotiate_codec,
    extract_remote_address
)

__all__ = [
    # Server
    'SIPServer',
    'SIPConfig',
    'SIPProtocol',

    # Session
    'CallSession',
    'CallStatus',
    'URI',
    'Transport',
    'AuthInfo',
    'AuthResult',
    'RoomConfig',
    'DispatchResult',
    'CallDispatch',
    'USER_AGENT',

    # Protocol
    'SIPMethod',
    'SIPStatus',
    'STATUS_NAMES',
    'status_name',
    'generate_tag',
    'generate_call_id',
    'generate_branch',
    'compute_digest_response',
    'parse_www_authenticate',
    'build_authorization_header',

    # Events
    'EventType',
    'SIPEvent',
    'CallInviteEvent',
    'CallEstablishedEvent',
    'CallEndedEvent',
    'CallFailedEvent',
    'DTMFEvent',

    # SDP
    'SDP',
    'SDPMedia',
    'SDPCodec',
    'SDPParser',
    'SDPGenerator',
    'negotiate_codec',
    'extract_remote_address',
]
