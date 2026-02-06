"""
Enumerações do Audio Session Protocol (ASP)
"""

from enum import Enum


class AudioEncoding(str, Enum):
    """Codificação de áudio suportada."""
    PCM_S16LE = "pcm_s16le"
    MULAW = "mulaw"
    ALAW = "alaw"


class SessionStatus(str, Enum):
    """Status da negociação de sessão."""
    ACCEPTED = "accepted"
    ACCEPTED_WITH_CHANGES = "accepted_with_changes"
    REJECTED = "rejected"


class ErrorCategory(str, Enum):
    """Categoria de erro do protocolo."""
    PROTOCOL = "protocol"
    AUDIO = "audio"
    VAD = "vad"
    SESSION = "session"


class SessionState(str, Enum):
    """Estado da sessão ASP."""
    IDLE = "idle"
    CONNECTED = "connected"
    CAPS_RECEIVED = "caps_received"
    NEGOTIATING = "negotiating"
    ACTIVE = "active"
    UPDATING = "updating"
    ENDING = "ending"
    CLOSED = "closed"


class CallActionType(str, Enum):
    """Tipos de acao de controle de chamada."""
    TRANSFER = "transfer"
    HANGUP = "hangup"


class MessageType(str, Enum):
    """Tipos de mensagem do protocolo."""
    PROTOCOL_CAPABILITIES = "protocol.capabilities"
    SESSION_START = "session.start"
    SESSION_STARTED = "session.started"
    SESSION_UPDATE = "session.update"
    SESSION_UPDATED = "session.updated"
    SESSION_END = "session.end"
    SESSION_ENDED = "session.ended"
    PROTOCOL_ERROR = "protocol.error"
    # Control messages
    AUDIO_SPEECH_START = "audio.speech_start"
    AUDIO_SPEECH_END = "audio.speech_end"
    RESPONSE_START = "response.start"
    RESPONSE_END = "response.end"
    RESPONSE_INTERRUPTED = "response.interrupted"
    # Call control messages
    CALL_ACTION = "call.action"
    # Text messages
    TEXT_UTTERANCE = "text.utterance"
