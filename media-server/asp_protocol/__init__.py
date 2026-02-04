"""
Audio Session Protocol (ASP) - Re-export do módulo compartilhado

Este módulo re-exporta tudo de shared/asp_protocol para manter
compatibilidade com imports existentes.
"""

import sys
from pathlib import Path

# Tenta múltiplos paths para funcionar em local e Docker
_possible_paths = [
    Path(__file__).parent.parent.parent / "shared",  # Local dev
    Path(__file__).parent.parent / "shared",  # Docker /app/
    Path("/app/shared"),  # Docker absolute
]

_shared_path = None
for _path in _possible_paths:
    if (_path / "asp_protocol" / "__init__.py").exists():
        _shared_path = str(_path)
        break

if _shared_path is None:
    raise ImportError(f"Não foi possível encontrar shared/asp_protocol. Paths tentados: {_possible_paths}")

# Remove módulo atual do cache se existir para evitar conflito
_current_module = sys.modules.get("asp_protocol")
if _current_module is not None:
    del sys.modules["asp_protocol"]

# Adiciona shared ao path como primeiro elemento
sys.path.insert(0, _shared_path)

# Importa o módulo shared (agora é encontrado primeiro)
import asp_protocol as _shared_asp

# Remove do path para evitar conflitos
sys.path.remove(_shared_path)

# Restaura este módulo no cache com os re-exports
sys.modules["asp_protocol"] = sys.modules[__name__]

# Re-exporta tudo
__version__ = _shared_asp.__version__

# Enums
AudioEncoding = _shared_asp.AudioEncoding
SessionStatus = _shared_asp.SessionStatus
ErrorCategory = _shared_asp.ErrorCategory
SessionState = _shared_asp.SessionState
MessageType = _shared_asp.MessageType

# Config
AudioConfig = _shared_asp.AudioConfig
VADConfig = _shared_asp.VADConfig
ProtocolCapabilities = _shared_asp.ProtocolCapabilities
NegotiatedConfig = _shared_asp.NegotiatedConfig
Adjustment = _shared_asp.Adjustment
ProtocolError = _shared_asp.ProtocolError
SessionStatistics = _shared_asp.SessionStatistics

# Constants
VALID_SAMPLE_RATES = _shared_asp.VALID_SAMPLE_RATES
VALID_FRAME_DURATIONS = _shared_asp.VALID_FRAME_DURATIONS
VALID_CHANNELS = _shared_asp.VALID_CHANNELS
VAD_SILENCE_THRESHOLD_MIN = _shared_asp.VAD_SILENCE_THRESHOLD_MIN
VAD_SILENCE_THRESHOLD_MAX = _shared_asp.VAD_SILENCE_THRESHOLD_MAX
VAD_MIN_SPEECH_MIN = _shared_asp.VAD_MIN_SPEECH_MIN
VAD_MIN_SPEECH_MAX = _shared_asp.VAD_MIN_SPEECH_MAX
VAD_THRESHOLD_MIN = _shared_asp.VAD_THRESHOLD_MIN
VAD_THRESHOLD_MAX = _shared_asp.VAD_THRESHOLD_MAX
VAD_RING_BUFFER_MIN = _shared_asp.VAD_RING_BUFFER_MIN
VAD_RING_BUFFER_MAX = _shared_asp.VAD_RING_BUFFER_MAX
VAD_SPEECH_RATIO_MIN = _shared_asp.VAD_SPEECH_RATIO_MIN
VAD_SPEECH_RATIO_MAX = _shared_asp.VAD_SPEECH_RATIO_MAX
VAD_PREFIX_PADDING_MIN = _shared_asp.VAD_PREFIX_PADDING_MIN
VAD_PREFIX_PADDING_MAX = _shared_asp.VAD_PREFIX_PADDING_MAX

# Messages
ASPMessage = _shared_asp.ASPMessage
ProtocolCapabilitiesMessage = _shared_asp.ProtocolCapabilitiesMessage
SessionStartMessage = _shared_asp.SessionStartMessage
SessionStartedMessage = _shared_asp.SessionStartedMessage
SessionUpdateMessage = _shared_asp.SessionUpdateMessage
SessionUpdatedMessage = _shared_asp.SessionUpdatedMessage
SessionEndMessage = _shared_asp.SessionEndMessage
SessionEndedMessage = _shared_asp.SessionEndedMessage
ProtocolErrorMessage = _shared_asp.ProtocolErrorMessage
AudioSpeechStartMessage = _shared_asp.AudioSpeechStartMessage
AudioSpeechEndMessage = _shared_asp.AudioSpeechEndMessage
ResponseStartMessage = _shared_asp.ResponseStartMessage
ResponseEndMessage = _shared_asp.ResponseEndMessage
parse_message = _shared_asp.parse_message
is_valid_message = _shared_asp.is_valid_message

# Negotiation
ConfigNegotiator = _shared_asp.ConfigNegotiator
NegotiationResult = _shared_asp.NegotiationResult
negotiate_config = _shared_asp.negotiate_config

# Errors module
errors = _shared_asp.errors

__all__ = [
    "__version__",
    "AudioEncoding",
    "SessionStatus",
    "ErrorCategory",
    "SessionState",
    "MessageType",
    "AudioConfig",
    "VADConfig",
    "ProtocolCapabilities",
    "NegotiatedConfig",
    "Adjustment",
    "ProtocolError",
    "SessionStatistics",
    "VALID_SAMPLE_RATES",
    "VALID_FRAME_DURATIONS",
    "VALID_CHANNELS",
    "VAD_SILENCE_THRESHOLD_MIN",
    "VAD_SILENCE_THRESHOLD_MAX",
    "VAD_MIN_SPEECH_MIN",
    "VAD_MIN_SPEECH_MAX",
    "VAD_THRESHOLD_MIN",
    "VAD_THRESHOLD_MAX",
    "VAD_RING_BUFFER_MIN",
    "VAD_RING_BUFFER_MAX",
    "VAD_SPEECH_RATIO_MIN",
    "VAD_SPEECH_RATIO_MAX",
    "VAD_PREFIX_PADDING_MIN",
    "VAD_PREFIX_PADDING_MAX",
    "ASPMessage",
    "ProtocolCapabilitiesMessage",
    "SessionStartMessage",
    "SessionStartedMessage",
    "SessionUpdateMessage",
    "SessionUpdatedMessage",
    "SessionEndMessage",
    "SessionEndedMessage",
    "ProtocolErrorMessage",
    "AudioSpeechStartMessage",
    "AudioSpeechEndMessage",
    "ResponseStartMessage",
    "ResponseEndMessage",
    "parse_message",
    "is_valid_message",
    "ConfigNegotiator",
    "NegotiationResult",
    "negotiate_config",
    "errors",
]
