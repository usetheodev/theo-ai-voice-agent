"""
Mensagens do Audio Session Protocol (ASP)

Classes para todas as mensagens do protocolo com serialização JSON.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any, Type, Union
import json

from .enums import MessageType, SessionStatus, CallActionType
from .config import (
    AudioConfig,
    VADConfig,
    ProtocolCapabilities,
    NegotiatedConfig,
    ProtocolError,
    SessionStatistics,
)


def _get_timestamp() -> str:
    """Gera timestamp ISO 8601."""
    return datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'


class ASPMessage(ABC):
    """Classe base abstrata para mensagens ASP."""

    @property
    @abstractmethod
    def message_type(self) -> MessageType:
        """Retorna o tipo da mensagem."""
        pass

    @abstractmethod
    def to_dict(self) -> dict:
        """Converte mensagem para dicionário."""
        pass

    def to_json(self) -> str:
        """Converte mensagem para JSON."""
        return json.dumps(self.to_dict())

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict) -> "ASPMessage":
        """Cria mensagem a partir de dicionário."""
        pass

    @classmethod
    def from_json(cls, json_str: str) -> "ASPMessage":
        """Cria mensagem a partir de JSON."""
        return cls.from_dict(json.loads(json_str))


@dataclass
class ProtocolCapabilitiesMessage(ASPMessage):
    """
    Mensagem protocol.capabilities enviada pelo servidor.

    Informa ao cliente as capacidades e limitações do servidor.
    """
    capabilities: ProtocolCapabilities
    version: str = "1.0.0"
    server_id: Optional[str] = None
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.PROTOCOL_CAPABILITIES

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()

    def to_dict(self) -> dict:
        d = {
            "type": self.message_type.value,
            "version": self.version,
            "capabilities": self.capabilities.to_dict(),
            "timestamp": self.timestamp
        }
        if self.server_id:
            d["server_id"] = self.server_id
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ProtocolCapabilitiesMessage":
        return cls(
            capabilities=ProtocolCapabilities.from_dict(data.get("capabilities", {})),
            version=data.get("version", "1.0.0"),
            server_id=data.get("server_id"),
            timestamp=data.get("timestamp")
        )


@dataclass
class SessionStartMessage(ASPMessage):
    """
    Mensagem session.start enviada pelo cliente.

    Inicia uma sessão de áudio com a configuração desejada.
    """
    session_id: str
    audio: Optional[AudioConfig] = None
    vad: Optional[VADConfig] = None
    call_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.SESSION_START

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()
        if self.audio is None:
            self.audio = AudioConfig()
        if self.vad is None:
            self.vad = VADConfig()

    def to_dict(self) -> dict:
        d = {
            "type": self.message_type.value,
            "session_id": self.session_id,
            "audio": self.audio.to_dict() if self.audio else None,
            "vad": self.vad.to_dict() if self.vad else None,
            "timestamp": self.timestamp
        }
        if self.call_id:
            d["call_id"] = self.call_id
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SessionStartMessage":
        audio = None
        if "audio" in data and data["audio"]:
            audio = AudioConfig.from_dict(data["audio"])

        vad = None
        if "vad" in data and data["vad"]:
            vad = VADConfig.from_dict(data["vad"])

        return cls(
            session_id=data["session_id"],
            audio=audio,
            vad=vad,
            call_id=data.get("call_id"),
            metadata=data.get("metadata"),
            timestamp=data.get("timestamp")
        )


@dataclass
class SessionStartedMessage(ASPMessage):
    """
    Mensagem session.started enviada pelo servidor.

    Confirma ou rejeita o início da sessão.
    """
    session_id: str
    status: SessionStatus
    negotiated: Optional[NegotiatedConfig] = None
    errors: Optional[List[ProtocolError]] = None
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.SESSION_STARTED

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()

    @property
    def is_accepted(self) -> bool:
        """Verifica se a sessão foi aceita."""
        return self.status in [SessionStatus.ACCEPTED, SessionStatus.ACCEPTED_WITH_CHANGES]

    @property
    def is_rejected(self) -> bool:
        """Verifica se a sessão foi rejeitada."""
        return self.status == SessionStatus.REJECTED

    def to_dict(self) -> dict:
        d = {
            "type": self.message_type.value,
            "session_id": self.session_id,
            "status": self.status.value if isinstance(self.status, SessionStatus) else self.status,
            "timestamp": self.timestamp
        }
        if self.negotiated:
            d["negotiated"] = self.negotiated.to_dict()
        if self.errors:
            d["errors"] = [e.to_dict() for e in self.errors]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SessionStartedMessage":
        status = data["status"]
        if isinstance(status, str):
            status = SessionStatus(status)

        negotiated = None
        if "negotiated" in data and data["negotiated"]:
            negotiated = NegotiatedConfig.from_dict(data["negotiated"])

        errors = None
        if "errors" in data and data["errors"]:
            errors = [ProtocolError.from_dict(e) for e in data["errors"]]

        return cls(
            session_id=data["session_id"],
            status=status,
            negotiated=negotiated,
            errors=errors,
            timestamp=data.get("timestamp")
        )


@dataclass
class SessionUpdateMessage(ASPMessage):
    """
    Mensagem session.update enviada pelo cliente.

    Atualiza a configuração durante uma sessão ativa.
    """
    session_id: str
    vad: Optional[VADConfig] = None
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.SESSION_UPDATE

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()

    def to_dict(self) -> dict:
        d = {
            "type": self.message_type.value,
            "session_id": self.session_id,
            "timestamp": self.timestamp
        }
        if self.vad:
            d["vad"] = self.vad.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SessionUpdateMessage":
        vad = None
        if "vad" in data and data["vad"]:
            vad = VADConfig.from_dict(data["vad"])

        return cls(
            session_id=data["session_id"],
            vad=vad,
            timestamp=data.get("timestamp")
        )


@dataclass
class SessionUpdatedMessage(ASPMessage):
    """
    Mensagem session.updated enviada pelo servidor.

    Confirma atualização da configuração.
    """
    session_id: str
    status: SessionStatus
    negotiated: Optional[NegotiatedConfig] = None
    errors: Optional[List[ProtocolError]] = None
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.SESSION_UPDATED

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()

    def to_dict(self) -> dict:
        d = {
            "type": self.message_type.value,
            "session_id": self.session_id,
            "status": self.status.value if isinstance(self.status, SessionStatus) else self.status,
            "timestamp": self.timestamp
        }
        if self.negotiated:
            d["negotiated"] = self.negotiated.to_dict()
        if self.errors:
            d["errors"] = [e.to_dict() for e in self.errors]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SessionUpdatedMessage":
        status = data["status"]
        if isinstance(status, str):
            status = SessionStatus(status)

        negotiated = None
        if "negotiated" in data and data["negotiated"]:
            negotiated = NegotiatedConfig.from_dict(data["negotiated"])

        errors = None
        if "errors" in data and data["errors"]:
            errors = [ProtocolError.from_dict(e) for e in data["errors"]]

        return cls(
            session_id=data["session_id"],
            status=status,
            negotiated=negotiated,
            errors=errors,
            timestamp=data.get("timestamp")
        )


@dataclass
class SessionEndMessage(ASPMessage):
    """
    Mensagem session.end enviada pelo cliente.

    Encerra uma sessão de forma graciosa.
    """
    session_id: str
    reason: Optional[str] = None
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.SESSION_END

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()

    def to_dict(self) -> dict:
        d = {
            "type": self.message_type.value,
            "session_id": self.session_id,
            "timestamp": self.timestamp
        }
        if self.reason:
            d["reason"] = self.reason
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SessionEndMessage":
        return cls(
            session_id=data["session_id"],
            reason=data.get("reason"),
            timestamp=data.get("timestamp")
        )


@dataclass
class SessionEndedMessage(ASPMessage):
    """
    Mensagem session.ended enviada pelo servidor.

    Confirma encerramento da sessão com estatísticas.
    """
    session_id: str
    duration_seconds: Optional[float] = None
    statistics: Optional[SessionStatistics] = None
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.SESSION_ENDED

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()

    def to_dict(self) -> dict:
        d = {
            "type": self.message_type.value,
            "session_id": self.session_id,
            "timestamp": self.timestamp
        }
        if self.duration_seconds is not None:
            d["duration_seconds"] = self.duration_seconds
        if self.statistics:
            d["statistics"] = self.statistics.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SessionEndedMessage":
        statistics = None
        if "statistics" in data and data["statistics"]:
            statistics = SessionStatistics.from_dict(data["statistics"])

        return cls(
            session_id=data["session_id"],
            duration_seconds=data.get("duration_seconds"),
            statistics=statistics,
            timestamp=data.get("timestamp")
        )


@dataclass
class ProtocolErrorMessage(ASPMessage):
    """
    Mensagem protocol.error enviada pelo servidor.

    Informa erro de protocolo que pode resultar em desconexão.
    """
    error: ProtocolError
    session_id: Optional[str] = None
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.PROTOCOL_ERROR

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()

    def to_dict(self) -> dict:
        d = {
            "type": self.message_type.value,
            "error": self.error.to_dict(),
            "timestamp": self.timestamp
        }
        if self.session_id:
            d["session_id"] = self.session_id
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ProtocolErrorMessage":
        return cls(
            error=ProtocolError.from_dict(data["error"]),
            session_id=data.get("session_id"),
            timestamp=data.get("timestamp")
        )


# Control messages (for audio streaming state)

@dataclass
class AudioSpeechStartMessage(ASPMessage):
    """Indica início de fala detectada pelo VAD."""
    session_id: str
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.AUDIO_SPEECH_START

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()

    def to_dict(self) -> dict:
        return {
            "type": self.message_type.value,
            "session_id": self.session_id,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AudioSpeechStartMessage":
        return cls(
            session_id=data["session_id"],
            timestamp=data.get("timestamp")
        )


@dataclass
class AudioSpeechEndMessage(ASPMessage):
    """Indica fim de fala detectada pelo VAD."""
    session_id: str
    duration_ms: Optional[int] = None
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.AUDIO_SPEECH_END

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()

    def to_dict(self) -> dict:
        d = {
            "type": self.message_type.value,
            "session_id": self.session_id,
            "timestamp": self.timestamp
        }
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AudioSpeechEndMessage":
        return cls(
            session_id=data["session_id"],
            duration_ms=data.get("duration_ms"),
            timestamp=data.get("timestamp")
        )


@dataclass
class ResponseStartMessage(ASPMessage):
    """Indica início de resposta do agente."""
    session_id: str
    response_id: str
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.RESPONSE_START

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()

    def to_dict(self) -> dict:
        return {
            "type": self.message_type.value,
            "session_id": self.session_id,
            "response_id": self.response_id,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResponseStartMessage":
        return cls(
            session_id=data["session_id"],
            response_id=data["response_id"],
            timestamp=data.get("timestamp")
        )


@dataclass
class ResponseEndMessage(ASPMessage):
    """Indica fim de resposta do agente."""
    session_id: str
    response_id: str
    interrupted: bool = False
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.RESPONSE_END

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()

    def to_dict(self) -> dict:
        return {
            "type": self.message_type.value,
            "session_id": self.session_id,
            "response_id": self.response_id,
            "interrupted": self.interrupted,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResponseEndMessage":
        return cls(
            session_id=data["session_id"],
            response_id=data["response_id"],
            interrupted=data.get("interrupted", False),
            timestamp=data.get("timestamp")
        )


@dataclass
class CallActionMessage(ASPMessage):
    """
    Mensagem call.action enviada pelo AI Agent para o Media Server.

    Comunica uma acao de controle de chamada decidida pela IA
    (ex: transferir chamada, encerrar chamada).

    O Media Server executa a acao via AMI apos o playback completar.
    """
    session_id: str
    action: Union[str, CallActionType]
    target: Optional[str] = None
    reason: Optional[str] = None
    timestamp: Optional[str] = None

    @property
    def message_type(self) -> MessageType:
        return MessageType.CALL_ACTION

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _get_timestamp()

    def to_dict(self) -> dict:
        result = {
            "type": self.message_type.value,
            "session_id": self.session_id,
            "action": self.action.value if isinstance(self.action, CallActionType) else self.action,
            "timestamp": self.timestamp
        }
        if self.target is not None:
            result["target"] = self.target
        if self.reason is not None:
            result["reason"] = self.reason
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "CallActionMessage":
        return cls(
            session_id=data["session_id"],
            action=data["action"],
            target=data.get("target"),
            reason=data.get("reason"),
            timestamp=data.get("timestamp")
        )


# Message registry for parsing
_MESSAGE_TYPES: Dict[str, Type[ASPMessage]] = {
    MessageType.PROTOCOL_CAPABILITIES.value: ProtocolCapabilitiesMessage,
    MessageType.SESSION_START.value: SessionStartMessage,
    MessageType.SESSION_STARTED.value: SessionStartedMessage,
    MessageType.SESSION_UPDATE.value: SessionUpdateMessage,
    MessageType.SESSION_UPDATED.value: SessionUpdatedMessage,
    MessageType.SESSION_END.value: SessionEndMessage,
    MessageType.SESSION_ENDED.value: SessionEndedMessage,
    MessageType.PROTOCOL_ERROR.value: ProtocolErrorMessage,
    MessageType.AUDIO_SPEECH_START.value: AudioSpeechStartMessage,
    MessageType.AUDIO_SPEECH_END.value: AudioSpeechEndMessage,
    MessageType.RESPONSE_START.value: ResponseStartMessage,
    MessageType.RESPONSE_END.value: ResponseEndMessage,
    MessageType.CALL_ACTION.value: CallActionMessage,
}


def parse_message(data: str | dict) -> ASPMessage:
    """
    Parse uma mensagem ASP de JSON ou dict.

    Args:
        data: String JSON ou dicionário

    Returns:
        Instância da mensagem apropriada

    Raises:
        ValueError: Se tipo de mensagem desconhecido
    """
    if isinstance(data, str):
        data = json.loads(data)

    msg_type = data.get("type")
    if msg_type not in _MESSAGE_TYPES:
        raise ValueError(f"Unknown message type: {msg_type}")

    return _MESSAGE_TYPES[msg_type].from_dict(data)


def is_valid_message(data: str | dict) -> bool:
    """
    Verifica se é uma mensagem ASP válida.

    Args:
        data: String JSON ou dicionário

    Returns:
        True se válido, False caso contrário
    """
    try:
        parse_message(data)
        return True
    except (ValueError, KeyError, json.JSONDecodeError):
        return False
