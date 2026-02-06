"""
Audio Session Protocol (ASP) - Módulo Compartilhado

Protocolo de negociação de configuração para sessões de áudio em tempo real.

Exemplo de uso (servidor):

    from asp_protocol import (
        ProtocolCapabilities,
        ProtocolCapabilitiesMessage,
        SessionStartMessage,
        SessionStartedMessage,
        negotiate_config,
        parse_message,
    )

    # Ao conectar, enviar capabilities
    caps = ProtocolCapabilities(
        version="1.0.0",
        supported_sample_rates=[8000, 16000],
        supported_encodings=["pcm_s16le"],
    )
    await ws.send(ProtocolCapabilitiesMessage(caps).to_json())

    # Ao receber session.start
    msg = parse_message(await ws.recv())
    if isinstance(msg, SessionStartMessage):
        result = negotiate_config(caps, msg.audio, msg.vad)
        response = SessionStartedMessage(
            session_id=msg.session_id,
            status=result.status,
            negotiated=result.negotiated,
            errors=result.errors
        )
        await ws.send(response.to_json())

Exemplo de uso (cliente):

    from asp_protocol import (
        AudioConfig,
        VADConfig,
        SessionStartMessage,
        parse_message,
    )

    # Aguardar capabilities
    caps_msg = parse_message(await ws.recv())

    # Enviar session.start
    start = SessionStartMessage(
        session_id="uuid-here",
        audio=AudioConfig(sample_rate=8000),
        vad=VADConfig(silence_threshold_ms=500),
    )
    await ws.send(start.to_json())

    # Aguardar session.started
    response = parse_message(await ws.recv())
    if response.is_accepted:
        # Usar response.negotiated.audio e response.negotiated.vad
        pass
"""

__version__ = "1.0.0"

# Enums
from .enums import (
    AudioEncoding,
    SessionStatus,
    ErrorCategory,
    SessionState,
    MessageType,
    CallActionType,
)

# Config classes
from .config import (
    AudioConfig,
    VADConfig,
    ProtocolCapabilities,
    NegotiatedConfig,
    Adjustment,
    ProtocolError,
    SessionStatistics,
    # Constants
    VALID_SAMPLE_RATES,
    VALID_FRAME_DURATIONS,
    VALID_CHANNELS,
    VAD_SILENCE_THRESHOLD_MIN,
    VAD_SILENCE_THRESHOLD_MAX,
    VAD_MIN_SPEECH_MIN,
    VAD_MIN_SPEECH_MAX,
    VAD_THRESHOLD_MIN,
    VAD_THRESHOLD_MAX,
    VAD_RING_BUFFER_MIN,
    VAD_RING_BUFFER_MAX,
    VAD_SPEECH_RATIO_MIN,
    VAD_SPEECH_RATIO_MAX,
    VAD_PREFIX_PADDING_MIN,
    VAD_PREFIX_PADDING_MAX,
)

# Messages
from .messages import (
    ASPMessage,
    ProtocolCapabilitiesMessage,
    SessionStartMessage,
    SessionStartedMessage,
    SessionUpdateMessage,
    SessionUpdatedMessage,
    SessionEndMessage,
    SessionEndedMessage,
    ProtocolErrorMessage,
    AudioSpeechStartMessage,
    AudioSpeechEndMessage,
    ResponseStartMessage,
    ResponseEndMessage,
    CallActionMessage,
    parse_message,
    is_valid_message,
)

# Negotiation
from .negotiation import (
    ConfigNegotiator,
    NegotiationResult,
    negotiate_config,
)

# Errors
from . import errors

__all__ = [
    # Version
    "__version__",
    # Enums
    "AudioEncoding",
    "SessionStatus",
    "ErrorCategory",
    "SessionState",
    "MessageType",
    "CallActionType",
    # Config
    "AudioConfig",
    "VADConfig",
    "ProtocolCapabilities",
    "NegotiatedConfig",
    "Adjustment",
    "ProtocolError",
    "SessionStatistics",
    # Constants
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
    # Messages
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
    "CallActionMessage",
    "parse_message",
    "is_valid_message",
    # Negotiation
    "ConfigNegotiator",
    "NegotiationResult",
    "negotiate_config",
    # Errors module
    "errors",
]
