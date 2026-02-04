"""
Protocolo WebSocket para comunicação Media Server <-> AI Agent

Re-exporta do módulo compartilhado shared/ws/protocol.py
"""

import importlib.util
from pathlib import Path

# Tenta múltiplos paths para funcionar em local e Docker
_possible_paths = [
    Path(__file__).parent.parent.parent / "shared" / "ws" / "protocol.py",  # Local dev
    Path(__file__).parent.parent / "shared" / "ws" / "protocol.py",  # Docker /app/
    Path("/app/shared/ws/protocol.py"),  # Docker absolute
]

_shared_protocol_path = None
for _path in _possible_paths:
    if _path.exists():
        _shared_protocol_path = _path
        break

if _shared_protocol_path is None:
    raise ImportError(f"Não foi possível encontrar shared/ws/protocol.py. Paths tentados: {_possible_paths}")

_spec = importlib.util.spec_from_file_location("shared_ws_protocol", _shared_protocol_path)
_shared_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared_module)

# Re-exporta tudo do módulo compartilhado
MessageType = _shared_module.MessageType
AudioDirection = _shared_module.AudioDirection
AUDIO_MAGIC = _shared_module.AUDIO_MAGIC
AUDIO_HEADER_SIZE = _shared_module.AUDIO_HEADER_SIZE
AudioConfig = _shared_module.AudioConfig
SessionStartMessage = _shared_module.SessionStartMessage
SessionStartedMessage = _shared_module.SessionStartedMessage
SessionEndMessage = _shared_module.SessionEndMessage
AudioEndMessage = _shared_module.AudioEndMessage
ResponseStartMessage = _shared_module.ResponseStartMessage
ResponseEndMessage = _shared_module.ResponseEndMessage
ErrorMessage = _shared_module.ErrorMessage
ControlMessage = _shared_module.ControlMessage
parse_control_message = _shared_module.parse_control_message
session_id_to_hash = _shared_module.session_id_to_hash
hash_to_session_id_prefix = _shared_module.hash_to_session_id_prefix
AudioFrame = _shared_module.AudioFrame
create_audio_frame = _shared_module.create_audio_frame
parse_audio_frame = _shared_module.parse_audio_frame
is_audio_frame = _shared_module.is_audio_frame

__all__ = [
    'MessageType',
    'AudioDirection',
    'AUDIO_MAGIC',
    'AUDIO_HEADER_SIZE',
    'AudioConfig',
    'SessionStartMessage',
    'SessionStartedMessage',
    'SessionEndMessage',
    'AudioEndMessage',
    'ResponseStartMessage',
    'ResponseEndMessage',
    'ErrorMessage',
    'ControlMessage',
    'parse_control_message',
    'session_id_to_hash',
    'hash_to_session_id_prefix',
    'AudioFrame',
    'create_audio_frame',
    'parse_audio_frame',
    'is_audio_frame',
]
