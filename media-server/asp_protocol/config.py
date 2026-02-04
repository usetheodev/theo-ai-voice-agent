"""
Configurações do Audio Session Protocol (ASP)

Classes de configuração para áudio e VAD com validação.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Any
import json

from .enums import AudioEncoding


# Constantes de validação
VALID_SAMPLE_RATES = [8000, 16000, 24000, 48000]
VALID_FRAME_DURATIONS = [10, 20, 30]
VALID_CHANNELS = [1]  # Apenas mono nesta versão

# Ranges de VAD
VAD_SILENCE_THRESHOLD_MIN = 100
VAD_SILENCE_THRESHOLD_MAX = 2000
VAD_MIN_SPEECH_MIN = 100
VAD_MIN_SPEECH_MAX = 1000
VAD_THRESHOLD_MIN = 0.0
VAD_THRESHOLD_MAX = 1.0
VAD_RING_BUFFER_MIN = 3
VAD_RING_BUFFER_MAX = 10
VAD_SPEECH_RATIO_MIN = 0.2
VAD_SPEECH_RATIO_MAX = 0.8
VAD_PREFIX_PADDING_MIN = 0
VAD_PREFIX_PADDING_MAX = 500


@dataclass
class AudioConfig:
    """
    Configuração de formato de áudio.

    Attributes:
        sample_rate: Taxa de amostragem em Hz (8000, 16000, 24000, 48000)
        encoding: Codificação do áudio (pcm_s16le, mulaw, alaw)
        channels: Número de canais (1 = mono)
        frame_duration_ms: Duração de cada frame em milissegundos
    """
    sample_rate: int = 8000
    encoding: AudioEncoding = AudioEncoding.PCM_S16LE
    channels: int = 1
    frame_duration_ms: int = 20

    def validate(self) -> List[str]:
        """
        Valida a configuração de áudio.

        Returns:
            Lista de erros encontrados (vazia se válido)
        """
        errors = []

        if self.sample_rate not in VALID_SAMPLE_RATES:
            errors.append(
                f"sample_rate must be one of {VALID_SAMPLE_RATES}, got {self.sample_rate}"
            )

        if isinstance(self.encoding, str):
            try:
                AudioEncoding(self.encoding)
            except ValueError:
                errors.append(
                    f"encoding must be one of {[e.value for e in AudioEncoding]}, got {self.encoding}"
                )

        if self.channels not in VALID_CHANNELS:
            errors.append(
                f"channels must be one of {VALID_CHANNELS}, got {self.channels}"
            )

        if self.frame_duration_ms not in VALID_FRAME_DURATIONS:
            errors.append(
                f"frame_duration_ms must be one of {VALID_FRAME_DURATIONS}, got {self.frame_duration_ms}"
            )

        return errors

    def is_valid(self) -> bool:
        """Verifica se a configuração é válida."""
        return len(self.validate()) == 0

    def to_dict(self) -> dict:
        """Converte para dicionário."""
        d = asdict(self)
        if isinstance(self.encoding, AudioEncoding):
            d["encoding"] = self.encoding.value
        return d

    def to_json(self) -> str:
        """Converte para JSON."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "AudioConfig":
        """Cria instância a partir de dicionário."""
        # Filter only valid fields
        filtered = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        if "encoding" in filtered and isinstance(filtered["encoding"], str):
            filtered["encoding"] = AudioEncoding(filtered["encoding"])
        return cls(**filtered)

    @classmethod
    def from_json(cls, json_str: str) -> "AudioConfig":
        """Cria instância a partir de JSON."""
        return cls.from_dict(json.loads(json_str))

    @property
    def bytes_per_frame(self) -> int:
        """Calcula bytes por frame baseado na configuração."""
        samples_per_frame = int(self.sample_rate * self.frame_duration_ms / 1000)
        bytes_per_sample = 2 if self.encoding == AudioEncoding.PCM_S16LE else 1
        return samples_per_frame * bytes_per_sample * self.channels


@dataclass
class VADConfig:
    """
    Configuração do Voice Activity Detection.

    Attributes:
        enabled: Se VAD está habilitado
        silence_threshold_ms: Silêncio para considerar fim de fala (100-2000ms)
        min_speech_ms: Duração mínima de fala válida (100-1000ms)
        threshold: Sensibilidade de detecção (0.0-1.0)
        ring_buffer_frames: Frames para suavização (3-10)
        speech_ratio: Proporção mínima de fala no buffer (0.2-0.8)
        prefix_padding_ms: Áudio incluído antes da fala detectada (0-500ms)
    """
    enabled: bool = True
    silence_threshold_ms: int = 500
    min_speech_ms: int = 250
    threshold: float = 0.5
    ring_buffer_frames: int = 5
    speech_ratio: float = 0.4
    prefix_padding_ms: int = 300

    def validate(self) -> List[str]:
        """
        Valida a configuração de VAD.

        Returns:
            Lista de erros encontrados (vazia se válido)
        """
        errors = []

        if not VAD_SILENCE_THRESHOLD_MIN <= self.silence_threshold_ms <= VAD_SILENCE_THRESHOLD_MAX:
            errors.append(
                f"silence_threshold_ms must be {VAD_SILENCE_THRESHOLD_MIN}-{VAD_SILENCE_THRESHOLD_MAX}ms, "
                f"got {self.silence_threshold_ms}"
            )

        if not VAD_MIN_SPEECH_MIN <= self.min_speech_ms <= VAD_MIN_SPEECH_MAX:
            errors.append(
                f"min_speech_ms must be {VAD_MIN_SPEECH_MIN}-{VAD_MIN_SPEECH_MAX}ms, "
                f"got {self.min_speech_ms}"
            )

        if not VAD_THRESHOLD_MIN <= self.threshold <= VAD_THRESHOLD_MAX:
            errors.append(
                f"threshold must be {VAD_THRESHOLD_MIN}-{VAD_THRESHOLD_MAX}, "
                f"got {self.threshold}"
            )

        if not VAD_RING_BUFFER_MIN <= self.ring_buffer_frames <= VAD_RING_BUFFER_MAX:
            errors.append(
                f"ring_buffer_frames must be {VAD_RING_BUFFER_MIN}-{VAD_RING_BUFFER_MAX}, "
                f"got {self.ring_buffer_frames}"
            )

        if not VAD_SPEECH_RATIO_MIN <= self.speech_ratio <= VAD_SPEECH_RATIO_MAX:
            errors.append(
                f"speech_ratio must be {VAD_SPEECH_RATIO_MIN}-{VAD_SPEECH_RATIO_MAX}, "
                f"got {self.speech_ratio}"
            )

        if not VAD_PREFIX_PADDING_MIN <= self.prefix_padding_ms <= VAD_PREFIX_PADDING_MAX:
            errors.append(
                f"prefix_padding_ms must be {VAD_PREFIX_PADDING_MIN}-{VAD_PREFIX_PADDING_MAX}ms, "
                f"got {self.prefix_padding_ms}"
            )

        return errors

    def is_valid(self) -> bool:
        """Verifica se a configuração é válida."""
        return len(self.validate()) == 0

    def to_dict(self) -> dict:
        """Converte para dicionário."""
        return asdict(self)

    def to_json(self) -> str:
        """Converte para JSON."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "VADConfig":
        """Cria instância a partir de dicionário."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, json_str: str) -> "VADConfig":
        """Cria instância a partir de JSON."""
        return cls.from_dict(json.loads(json_str))

    def merge(self, updates: dict) -> "VADConfig":
        """
        Cria nova config com atualizações aplicadas.

        Args:
            updates: Campos a atualizar

        Returns:
            Nova instância com updates aplicados
        """
        current = self.to_dict()
        current.update(updates)
        return VADConfig.from_dict(current)


@dataclass
class ProtocolCapabilities:
    """
    Capacidades suportadas pelo servidor.

    Attributes:
        version: Versão do protocolo (semver)
        supported_sample_rates: Sample rates suportados
        supported_encodings: Encodings suportados
        supported_frame_durations: Frame durations suportados
        vad_configurable: Se VAD é configurável
        vad_parameters: Parâmetros VAD configuráveis
        max_session_duration_seconds: Duração máxima da sessão
        features: Features suportadas
    """
    version: str = "1.0.0"
    supported_sample_rates: List[int] = field(default_factory=lambda: [8000, 16000])
    supported_encodings: List[str] = field(default_factory=lambda: ["pcm_s16le"])
    supported_frame_durations: List[int] = field(default_factory=lambda: [10, 20, 30])
    vad_configurable: bool = True
    vad_parameters: List[str] = field(default_factory=lambda: [
        "silence_threshold_ms",
        "min_speech_ms",
        "threshold",
        "ring_buffer_frames",
        "speech_ratio",
        "prefix_padding_ms"
    ])
    max_session_duration_seconds: Optional[int] = 3600
    features: List[str] = field(default_factory=lambda: [
        "barge_in",
        "streaming_tts",
        "sentence_pipeline"
    ])

    def supports_sample_rate(self, rate: int) -> bool:
        """Verifica se sample rate é suportado."""
        return rate in self.supported_sample_rates

    def supports_encoding(self, encoding: str) -> bool:
        """Verifica se encoding é suportado."""
        enc_value = encoding.value if isinstance(encoding, AudioEncoding) else encoding
        return enc_value in self.supported_encodings

    def supports_feature(self, feature: str) -> bool:
        """Verifica se feature é suportada."""
        return feature in self.features

    def to_dict(self) -> dict:
        """Converte para dicionário."""
        return asdict(self)

    def to_json(self) -> str:
        """Converte para JSON."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "ProtocolCapabilities":
        """Cria instância a partir de dicionário."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, json_str: str) -> "ProtocolCapabilities":
        """Cria instância a partir de JSON."""
        return cls.from_dict(json.loads(json_str))


@dataclass
class Adjustment:
    """
    Ajuste feito durante negociação.

    Attributes:
        field: Campo ajustado (ex: "vad.threshold")
        requested: Valor solicitado
        applied: Valor aplicado
        reason: Motivo do ajuste
    """
    field: str
    requested: Any
    applied: Any
    reason: str

    def to_dict(self) -> dict:
        """Converte para dicionário."""
        return asdict(self)


@dataclass
class NegotiatedConfig:
    """
    Configuração efetiva após negociação.

    Attributes:
        audio: Configuração de áudio negociada
        vad: Configuração de VAD negociada
        adjustments: Lista de ajustes feitos
    """
    audio: AudioConfig
    vad: VADConfig
    adjustments: List[Adjustment] = field(default_factory=list)

    def has_adjustments(self) -> bool:
        """Verifica se houve ajustes."""
        return len(self.adjustments) > 0

    def to_dict(self) -> dict:
        """Converte para dicionário."""
        return {
            "audio": self.audio.to_dict(),
            "vad": self.vad.to_dict(),
            "adjustments": [adj.to_dict() for adj in self.adjustments]
        }

    def to_json(self) -> str:
        """Converte para JSON."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "NegotiatedConfig":
        """Cria instância a partir de dicionário."""
        return cls(
            audio=AudioConfig.from_dict(data.get("audio", {})),
            vad=VADConfig.from_dict(data.get("vad", {})),
            adjustments=[
                Adjustment(**adj) for adj in data.get("adjustments", [])
            ]
        )


@dataclass
class ProtocolError:
    """
    Erro de protocolo.

    Attributes:
        code: Código do erro
        category: Categoria do erro
        message: Mensagem human-readable
        details: Detalhes adicionais
        recoverable: Se o erro é recuperável
    """
    code: int
    category: str
    message: str
    details: Optional[dict] = None
    recoverable: bool = True

    def to_dict(self) -> dict:
        """Converte para dicionário."""
        d = {
            "code": self.code,
            "category": self.category,
            "message": self.message,
            "recoverable": self.recoverable
        }
        if self.details:
            d["details"] = self.details
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ProtocolError":
        """Cria instância a partir de dicionário."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SessionStatistics:
    """
    Estatísticas de uma sessão.

    Attributes:
        audio_frames_received: Total de frames de áudio recebidos
        audio_frames_sent: Total de frames de áudio enviados
        vad_speech_events: Número de eventos de fala detectados
        barge_in_count: Número de barge-ins
        average_response_latency_ms: Latência média de resposta
    """
    audio_frames_received: int = 0
    audio_frames_sent: int = 0
    vad_speech_events: int = 0
    barge_in_count: int = 0
    average_response_latency_ms: float = 0.0

    def to_dict(self) -> dict:
        """Converte para dicionário."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionStatistics":
        """Cria instância a partir de dicionário."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
