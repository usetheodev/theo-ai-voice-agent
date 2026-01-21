"""
SIP Event Definitions

Events emitted by SIP Server for inter-module communication
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

from .session import CallSession


class EventType(str, Enum):
    """SIP Event Types"""

    # Call Events
    CALL_INVITE_RECEIVED = "call.invite.received"
    CALL_RINGING = "call.ringing"
    CALL_ESTABLISHED = "call.established"
    CALL_ENDED = "call.ended"
    CALL_FAILED = "call.failed"

    # Authentication Events
    AUTH_REQUIRED = "auth.required"
    AUTH_SUCCESS = "auth.success"
    AUTH_FAILED = "auth.failed"

    # Media Events
    MEDIA_READY = "media.ready"
    MEDIA_TIMEOUT = "media.timeout"

    # DTMF Events
    DTMF_RECEIVED = "dtmf.received"


@dataclass
class SIPEvent:
    """
    Base SIP Event

    Emitted by SIP Server and consumed by other modules
    """
    type: EventType
    session_id: str
    data: Dict[str, Any]
    timestamp: Optional[float] = None

    def __post_init__(self):
        if self.timestamp is None:
            import time
            self.timestamp = time.time()


class CallInviteEvent(SIPEvent):
    """
    CALL_INVITE_RECEIVED event

    Emitted when INVITE is received (before accepting)
    """
    def __init__(self, session_id: str, caller_id: str, caller_uri: str,
                 called_number: str, sdp_offer: str, trunk_id: Optional[str] = None):
        super().__init__(
            type=EventType.CALL_INVITE_RECEIVED,
            session_id=session_id,
            data={
                'caller_id': caller_id,
                'caller_uri': caller_uri,
                'called_number': called_number,
                'sdp_offer': sdp_offer,
                'trunk_id': trunk_id
            }
        )
        self.caller_id = caller_id
        self.caller_uri = caller_uri
        self.called_number = called_number
        self.sdp_offer = sdp_offer
        self.trunk_id = trunk_id


class CallEstablishedEvent(SIPEvent):
    """
    CALL_ESTABLISHED event

    Emitted when call is accepted (200 OK sent)
    """
    def __init__(self, session: CallSession):
        super().__init__(
            type=EventType.CALL_ESTABLISHED,
            session_id=session.session_id,
            data={
                'session': session,
                'remote_ip': session.remote_ip,
                'remote_port': session.remote_port,
                'local_port': session.local_port,
                'codec': session.codec
            }
        )
        self.session = session


class CallEndedEvent(SIPEvent):
    """
    CALL_ENDED event

    Emitted when BYE is received or sent
    """
    def __init__(self, session_id: str, reason: str, duration: float):
        super().__init__(
            type=EventType.CALL_ENDED,
            session_id=session_id,
            data={
                'reason': reason,
                'duration': duration
            }
        )
        self.reason = reason
        self.duration = duration


class CallFailedEvent(SIPEvent):
    """
    CALL_FAILED event

    Emitted when call setup fails
    """
    def __init__(self, session_id: str, error: str, status_code: Optional[int] = None):
        super().__init__(
            type=EventType.CALL_FAILED,
            session_id=session_id,
            data={
                'error': error,
                'status_code': status_code
            }
        )
        self.error = error
        self.status_code = status_code


class DTMFEvent(SIPEvent):
    """
    DTMF_RECEIVED event

    Emitted when DTMF digit is detected
    """
    def __init__(self, session_id: str, digit: str, duration_ms: int = 0):
        super().__init__(
            type=EventType.DTMF_RECEIVED,
            session_id=session_id,
            data={
                'digit': digit,
                'duration_ms': duration_ms
            }
        )
        self.digit = digit
        self.duration_ms = duration_ms
