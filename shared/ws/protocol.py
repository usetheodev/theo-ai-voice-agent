"""
Protocolo WebSocket para comunicação Media Server <-> AI Agent

Mensagens de Controle (JSON):
- session.start: Inicia nova sessão de conversação
- session.started: Confirmação de sessão iniciada
- session.end: Encerra sessão
- audio.end: Fim do áudio do usuário (silêncio detectado)
- response.start: Início da resposta do agente
- response.end: Fim da resposta do agente
- error: Erro no processamento

Mensagens de Áudio (Binary):
Header (12 bytes):
[0]     Magic: 0x01
[1]     Direction: 0x00=inbound (user->agent), 0x01=outbound (agent->user)
[2-9]   Session ID hash (8 bytes)
[10-11] Reserved

[12+]   PCM Audio (16-bit signed LE, 8kHz mono)
"""

import json
import hashlib
from dataclasses import dataclass, asdict
from typing import Optional, Union
from enum import IntEnum


class MessageType:
    """Tipos de mensagens de controle"""
    SESSION_START = "session.start"
    SESSION_STARTED = "session.started"
    SESSION_END = "session.end"
    AUDIO_END = "audio.end"
    RESPONSE_START = "response.start"
    RESPONSE_END = "response.end"
    ERROR = "error"


class AudioDirection(IntEnum):
    """Direção do áudio"""
    INBOUND = 0x00   # Usuário -> Agente
    OUTBOUND = 0x01  # Agente -> Usuário


AUDIO_MAGIC = 0x01
AUDIO_HEADER_SIZE = 12


@dataclass
class AudioConfig:
    """Configuração de áudio da sessão"""
    sample_rate: int = 8000
    channels: int = 1
    sample_width: int = 2  # 16-bit
    frame_duration_ms: int = 20  # Duração do frame em ms


@dataclass
class SessionStartMessage:
    """Mensagem de início de sessão (Media Server -> AI Agent)"""
    session_id: str
    call_id: str
    audio_config: AudioConfig
    type: str = MessageType.SESSION_START

    def to_json(self) -> str:
        data = {
            "type": self.type,
            "session_id": self.session_id,
            "call_id": self.call_id,
            "audio_config": asdict(self.audio_config)
        }
        return json.dumps(data)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionStartMessage":
        audio_config = AudioConfig(**data.get("audio_config", {}))
        return cls(
            session_id=data["session_id"],
            call_id=data["call_id"],
            audio_config=audio_config
        )


@dataclass
class SessionStartedMessage:
    """Confirmação de sessão iniciada (AI Agent -> Media Server)"""
    session_id: str
    type: str = MessageType.SESSION_STARTED

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "session_id": self.session_id})

    @classmethod
    def from_dict(cls, data: dict) -> "SessionStartedMessage":
        return cls(session_id=data["session_id"])


@dataclass
class SessionEndMessage:
    """Mensagem de fim de sessão (Media Server -> AI Agent)"""
    session_id: str
    reason: str = "hangup"
    type: str = MessageType.SESSION_END

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type,
            "session_id": self.session_id,
            "reason": self.reason
        })

    @classmethod
    def from_dict(cls, data: dict) -> "SessionEndMessage":
        return cls(
            session_id=data["session_id"],
            reason=data.get("reason", "hangup")
        )


@dataclass
class AudioEndMessage:
    """Mensagem de fim de áudio do usuário (Media Server -> AI Agent)"""
    session_id: str
    type: str = MessageType.AUDIO_END

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "session_id": self.session_id})

    @classmethod
    def from_dict(cls, data: dict) -> "AudioEndMessage":
        return cls(session_id=data["session_id"])


@dataclass
class ResponseStartMessage:
    """Início da resposta do agente (AI Agent -> Media Server)"""
    session_id: str
    text: str = ""
    type: str = MessageType.RESPONSE_START

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type,
            "session_id": self.session_id,
            "text": self.text
        })

    @classmethod
    def from_dict(cls, data: dict) -> "ResponseStartMessage":
        return cls(
            session_id=data["session_id"],
            text=data.get("text", "")
        )


@dataclass
class ResponseEndMessage:
    """Fim da resposta do agente (AI Agent -> Media Server)"""
    session_id: str
    type: str = MessageType.RESPONSE_END

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "session_id": self.session_id})

    @classmethod
    def from_dict(cls, data: dict) -> "ResponseEndMessage":
        return cls(session_id=data["session_id"])


@dataclass
class ErrorMessage:
    """Mensagem de erro"""
    session_id: str
    code: str
    message: str
    type: str = MessageType.ERROR

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type,
            "session_id": self.session_id,
            "code": self.code,
            "message": self.message
        })

    @classmethod
    def from_dict(cls, data: dict) -> "ErrorMessage":
        return cls(
            session_id=data["session_id"],
            code=data["code"],
            message=data["message"]
        )


# Union type para todas as mensagens de controle
ControlMessage = Union[
    SessionStartMessage,
    SessionStartedMessage,
    SessionEndMessage,
    AudioEndMessage,
    ResponseStartMessage,
    ResponseEndMessage,
    ErrorMessage
]


def parse_control_message(data: str) -> ControlMessage:
    """Parse mensagem JSON de controle"""
    msg = json.loads(data)
    msg_type = msg.get("type")

    if msg_type == MessageType.SESSION_START:
        return SessionStartMessage.from_dict(msg)
    elif msg_type == MessageType.SESSION_STARTED:
        return SessionStartedMessage.from_dict(msg)
    elif msg_type == MessageType.SESSION_END:
        return SessionEndMessage.from_dict(msg)
    elif msg_type == MessageType.AUDIO_END:
        return AudioEndMessage.from_dict(msg)
    elif msg_type == MessageType.RESPONSE_START:
        return ResponseStartMessage.from_dict(msg)
    elif msg_type == MessageType.RESPONSE_END:
        return ResponseEndMessage.from_dict(msg)
    elif msg_type == MessageType.ERROR:
        return ErrorMessage.from_dict(msg)
    else:
        raise ValueError(f"Tipo de mensagem desconhecido: {msg_type}")


def session_id_to_hash(session_id: str) -> bytes:
    """Converte session_id para hash de 8 bytes (16 chars hex)"""
    h = hashlib.md5(session_id.encode()).digest()
    return h[:8]


def hash_to_session_id_prefix(hash_bytes: bytes) -> str:
    """Converte hash de volta para prefixo hex (para debug)"""
    return hash_bytes.hex()


@dataclass
class AudioFrame:
    """Frame de áudio"""
    session_id: str
    direction: AudioDirection
    audio_data: bytes

    def to_bytes(self) -> bytes:
        """Serializa frame para bytes"""
        header = bytearray(AUDIO_HEADER_SIZE)
        header[0] = AUDIO_MAGIC
        header[1] = self.direction
        header[2:10] = session_id_to_hash(self.session_id)
        # bytes 10-11 reservados (zeros)
        return bytes(header) + self.audio_data

    @classmethod
    def from_bytes(cls, data: bytes, session_id_lookup: Optional[dict] = None) -> "AudioFrame":
        """Deserializa frame de bytes

        Args:
            data: Bytes do frame
            session_id_lookup: Dict opcional {hash_hex: session_id} para lookup
        """
        if len(data) < AUDIO_HEADER_SIZE:
            raise ValueError(f"Frame muito pequeno: {len(data)} bytes")

        magic = data[0]
        if magic != AUDIO_MAGIC:
            raise ValueError(f"Magic inválido: {magic:#x}")

        direction = AudioDirection(data[1])
        session_hash = data[2:10]
        audio_data = data[AUDIO_HEADER_SIZE:]

        # Tenta recuperar session_id do lookup ou usa hash como fallback
        session_hash_hex = session_hash.hex()
        if session_id_lookup and session_hash_hex in session_id_lookup:
            session_id = session_id_lookup[session_hash_hex]
        else:
            session_id = session_hash_hex

        return cls(
            session_id=session_id,
            direction=direction,
            audio_data=audio_data
        )


def create_audio_frame(session_id: str, audio_data: bytes,
                       direction: AudioDirection = AudioDirection.INBOUND) -> bytes:
    """Helper para criar frame de áudio serializado"""
    frame = AudioFrame(session_id=session_id, direction=direction, audio_data=audio_data)
    return frame.to_bytes()


def parse_audio_frame(data: bytes, session_id_lookup: Optional[dict] = None) -> AudioFrame:
    """Helper para parse de frame de áudio"""
    return AudioFrame.from_bytes(data, session_id_lookup)


def is_audio_frame(data: bytes) -> bool:
    """Verifica se dados são um frame de áudio"""
    return len(data) >= AUDIO_HEADER_SIZE and data[0] == AUDIO_MAGIC
