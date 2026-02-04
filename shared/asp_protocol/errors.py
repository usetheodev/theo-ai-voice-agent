"""
Erros pré-definidos do Audio Session Protocol (ASP)

Códigos de erro e factory functions para criar erros.
"""

from .enums import ErrorCategory
from .config import ProtocolError


# =============================================================================
# CÓDIGOS DE ERRO
# =============================================================================

# Protocol errors (1xxx)
ERROR_INVALID_MESSAGE_FORMAT = 1001
ERROR_HANDSHAKE_TIMEOUT = 1002
ERROR_INVALID_MESSAGE_TYPE = 1003
ERROR_VERSION_MISMATCH = 1004
ERROR_SESSION_ALREADY_ACTIVE = 1005

# Audio errors (2xxx)
ERROR_UNSUPPORTED_SAMPLE_RATE = 2001
ERROR_UNSUPPORTED_ENCODING = 2002
ERROR_INVALID_FRAME_DURATION = 2003
ERROR_AUDIO_PROCESSING = 2004

# VAD errors (3xxx)
ERROR_INVALID_VAD_PARAMETER = 3001
ERROR_VAD_NOT_CONFIGURABLE = 3002
ERROR_VAD_INITIALIZATION = 3003

# Session errors (4xxx)
ERROR_SESSION_NOT_FOUND = 4001
ERROR_SESSION_EXPIRED = 4002
ERROR_SESSION_LIMIT_REACHED = 4003
ERROR_SESSION_UPDATE_NOT_ALLOWED = 4004


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def invalid_message_format(details: dict = None) -> ProtocolError:
    """Erro de formato de mensagem inválido."""
    return ProtocolError(
        code=ERROR_INVALID_MESSAGE_FORMAT,
        category=ErrorCategory.PROTOCOL.value,
        message="Invalid message format: JSON malformed or missing required fields",
        details=details,
        recoverable=True
    )


def handshake_timeout(timeout_seconds: int = 30) -> ProtocolError:
    """Erro de timeout no handshake."""
    return ProtocolError(
        code=ERROR_HANDSHAKE_TIMEOUT,
        category=ErrorCategory.PROTOCOL.value,
        message=f"Handshake timeout: session.start not received within {timeout_seconds}s",
        details={"timeout_seconds": timeout_seconds},
        recoverable=False
    )


def invalid_message_type(msg_type: str) -> ProtocolError:
    """Erro de tipo de mensagem desconhecido."""
    return ProtocolError(
        code=ERROR_INVALID_MESSAGE_TYPE,
        category=ErrorCategory.PROTOCOL.value,
        message=f"Unknown message type: {msg_type}",
        details={"received_type": msg_type},
        recoverable=True
    )


def version_mismatch(client_version: str, server_version: str) -> ProtocolError:
    """Erro de versão incompatível."""
    return ProtocolError(
        code=ERROR_VERSION_MISMATCH,
        category=ErrorCategory.PROTOCOL.value,
        message=f"Protocol version mismatch: client {client_version}, server {server_version}",
        details={
            "client_version": client_version,
            "server_version": server_version
        },
        recoverable=False
    )


def session_already_active(session_id: str) -> ProtocolError:
    """Erro de sessão já ativa."""
    return ProtocolError(
        code=ERROR_SESSION_ALREADY_ACTIVE,
        category=ErrorCategory.PROTOCOL.value,
        message=f"Session already active: {session_id}",
        details={"session_id": session_id},
        recoverable=True
    )


def unsupported_sample_rate(requested: int, supported: list) -> ProtocolError:
    """Erro de sample rate não suportado."""
    return ProtocolError(
        code=ERROR_UNSUPPORTED_SAMPLE_RATE,
        category=ErrorCategory.AUDIO.value,
        message=f"Sample rate {requested}Hz not supported",
        details={
            "requested": requested,
            "supported": supported
        },
        recoverable=True
    )


def unsupported_encoding(requested: str, supported: list) -> ProtocolError:
    """Erro de encoding não suportado."""
    return ProtocolError(
        code=ERROR_UNSUPPORTED_ENCODING,
        category=ErrorCategory.AUDIO.value,
        message=f"Audio encoding '{requested}' not supported",
        details={
            "requested": requested,
            "supported": supported
        },
        recoverable=True
    )


def invalid_frame_duration(requested: int, supported: list) -> ProtocolError:
    """Erro de frame duration inválido."""
    return ProtocolError(
        code=ERROR_INVALID_FRAME_DURATION,
        category=ErrorCategory.AUDIO.value,
        message=f"Frame duration {requested}ms not supported",
        details={
            "requested": requested,
            "supported": supported
        },
        recoverable=True
    )


def audio_processing_error(details: str) -> ProtocolError:
    """Erro de processamento de áudio."""
    return ProtocolError(
        code=ERROR_AUDIO_PROCESSING,
        category=ErrorCategory.AUDIO.value,
        message=f"Audio processing error: {details}",
        details={"error": details},
        recoverable=True
    )


def invalid_vad_parameter(parameter: str, value: any, valid_range: str) -> ProtocolError:
    """Erro de parâmetro VAD inválido."""
    return ProtocolError(
        code=ERROR_INVALID_VAD_PARAMETER,
        category=ErrorCategory.VAD.value,
        message=f"Invalid VAD parameter: {parameter}={value}, valid range: {valid_range}",
        details={
            "parameter": parameter,
            "value": value,
            "valid_range": valid_range
        },
        recoverable=True
    )


def vad_not_configurable() -> ProtocolError:
    """Erro quando VAD não é configurável."""
    return ProtocolError(
        code=ERROR_VAD_NOT_CONFIGURABLE,
        category=ErrorCategory.VAD.value,
        message="VAD is not configurable on this server",
        recoverable=True
    )


def vad_initialization_error(details: str) -> ProtocolError:
    """Erro de inicialização do VAD."""
    return ProtocolError(
        code=ERROR_VAD_INITIALIZATION,
        category=ErrorCategory.VAD.value,
        message=f"VAD initialization error: {details}",
        details={"error": details},
        recoverable=False
    )


def session_not_found(session_id: str) -> ProtocolError:
    """Erro de sessão não encontrada."""
    return ProtocolError(
        code=ERROR_SESSION_NOT_FOUND,
        category=ErrorCategory.SESSION.value,
        message=f"Session not found: {session_id}",
        details={"session_id": session_id},
        recoverable=True
    )


def session_expired(session_id: str) -> ProtocolError:
    """Erro de sessão expirada."""
    return ProtocolError(
        code=ERROR_SESSION_EXPIRED,
        category=ErrorCategory.SESSION.value,
        message=f"Session expired: {session_id}",
        details={"session_id": session_id},
        recoverable=False
    )


def session_limit_reached(max_sessions: int) -> ProtocolError:
    """Erro de limite de sessões atingido."""
    return ProtocolError(
        code=ERROR_SESSION_LIMIT_REACHED,
        category=ErrorCategory.SESSION.value,
        message=f"Session limit reached: maximum {max_sessions} sessions",
        details={"max_sessions": max_sessions},
        recoverable=False
    )


def session_update_not_allowed(session_id: str, current_state: str) -> ProtocolError:
    """Erro quando atualização não é permitida."""
    return ProtocolError(
        code=ERROR_SESSION_UPDATE_NOT_ALLOWED,
        category=ErrorCategory.SESSION.value,
        message=f"Session update not allowed in state: {current_state}",
        details={
            "session_id": session_id,
            "current_state": current_state
        },
        recoverable=True
    )
