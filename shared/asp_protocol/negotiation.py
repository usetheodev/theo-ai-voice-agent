"""
Negociação de configuração do Audio Session Protocol (ASP)

Implementa a lógica de negociação entre cliente e servidor.
"""

import logging
from dataclasses import dataclass
from typing import List, Tuple, Optional

from .enums import SessionStatus, ErrorCategory
from .config import (
    AudioConfig,
    VADConfig,
    ProtocolCapabilities,
    NegotiatedConfig,
    Adjustment,
    ProtocolError,
    VALID_SAMPLE_RATES,
    VALID_FRAME_DURATIONS,
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

logger = logging.getLogger("asp.negotiation")


@dataclass
class NegotiationResult:
    """
    Resultado da negociação de configuração.

    Attributes:
        success: Se a negociação foi bem-sucedida
        status: Status da negociação
        negotiated: Configuração negociada (se sucesso)
        errors: Lista de erros (se falha)
    """
    success: bool
    status: SessionStatus
    negotiated: Optional[NegotiatedConfig] = None
    errors: Optional[List[ProtocolError]] = None


class ConfigNegotiator:
    """
    Negociador de configuração ASP.

    Valida e ajusta configurações solicitadas pelo cliente
    de acordo com as capacidades do servidor.
    """

    def __init__(self, capabilities: ProtocolCapabilities):
        """
        Inicializa o negociador.

        Args:
            capabilities: Capacidades do servidor
        """
        self._capabilities = capabilities

    def negotiate(
        self,
        requested_audio: Optional[AudioConfig],
        requested_vad: Optional[VADConfig]
    ) -> NegotiationResult:
        """
        Negocia configuração solicitada.

        Args:
            requested_audio: Configuração de áudio solicitada
            requested_vad: Configuração de VAD solicitada

        Returns:
            Resultado da negociação
        """
        errors: List[ProtocolError] = []
        adjustments: List[Adjustment] = []

        # Use defaults se não especificado
        audio = requested_audio or AudioConfig()
        vad = requested_vad or VADConfig()

        # Negocia áudio
        negotiated_audio, audio_errors, audio_adjustments = self._negotiate_audio(audio)
        errors.extend(audio_errors)
        adjustments.extend(audio_adjustments)

        # Negocia VAD
        negotiated_vad, vad_errors, vad_adjustments = self._negotiate_vad(vad)
        errors.extend(vad_errors)
        adjustments.extend(vad_adjustments)

        # Determina resultado
        if errors:
            logger.warning(f"Negotiation failed with errors: {errors}")
            return NegotiationResult(
                success=False,
                status=SessionStatus.REJECTED,
                errors=errors
            )

        # Sucesso
        negotiated = NegotiatedConfig(
            audio=negotiated_audio,
            vad=negotiated_vad,
            adjustments=adjustments
        )

        if adjustments:
            logger.info(f"Negotiation accepted with {len(adjustments)} adjustments")
            for adj in adjustments:
                logger.info(f"  - {adj.field}: {adj.requested} -> {adj.applied} ({adj.reason})")

            return NegotiationResult(
                success=True,
                status=SessionStatus.ACCEPTED_WITH_CHANGES,
                negotiated=negotiated
            )
        else:
            logger.info("Negotiation accepted without changes")
            return NegotiationResult(
                success=True,
                status=SessionStatus.ACCEPTED,
                negotiated=negotiated
            )

    def _negotiate_audio(
        self,
        requested: AudioConfig
    ) -> Tuple[AudioConfig, List[ProtocolError], List[Adjustment]]:
        """
        Negocia configuração de áudio.

        Returns:
            Tuple de (config negociada, erros, ajustes)
        """
        errors: List[ProtocolError] = []
        adjustments: List[Adjustment] = []

        # Valores finais começam com os solicitados
        sample_rate = requested.sample_rate
        encoding = requested.encoding
        channels = requested.channels
        frame_duration = requested.frame_duration_ms

        # Valida sample_rate
        if not self._capabilities.supports_sample_rate(sample_rate):
            # Tenta ajustar para rate mais próximo suportado
            closest = self._find_closest_sample_rate(sample_rate)
            if closest:
                adjustments.append(Adjustment(
                    field="audio.sample_rate",
                    requested=sample_rate,
                    applied=closest,
                    reason=f"Requested rate not supported, using closest: {closest}Hz"
                ))
                sample_rate = closest
            else:
                errors.append(ProtocolError(
                    code=2001,
                    category=ErrorCategory.AUDIO.value,
                    message=f"Sample rate {sample_rate}Hz not supported",
                    details={
                        "requested": sample_rate,
                        "supported": self._capabilities.supported_sample_rates
                    },
                    recoverable=True
                ))

        # Valida encoding
        enc_value = encoding.value if hasattr(encoding, 'value') else encoding
        if not self._capabilities.supports_encoding(enc_value):
            # Usa encoding padrão
            default_encoding = self._capabilities.supported_encodings[0]
            adjustments.append(Adjustment(
                field="audio.encoding",
                requested=enc_value,
                applied=default_encoding,
                reason=f"Requested encoding not supported, using: {default_encoding}"
            ))
            encoding = default_encoding

        # Valida frame_duration
        if frame_duration not in self._capabilities.supported_frame_durations:
            # Usa duração padrão
            default_duration = 20
            if default_duration in self._capabilities.supported_frame_durations:
                adjustments.append(Adjustment(
                    field="audio.frame_duration_ms",
                    requested=frame_duration,
                    applied=default_duration,
                    reason=f"Requested frame duration not supported, using: {default_duration}ms"
                ))
                frame_duration = default_duration

        # Channels sempre 1 nesta versão
        if channels != 1:
            adjustments.append(Adjustment(
                field="audio.channels",
                requested=channels,
                applied=1,
                reason="Only mono (1 channel) supported in this version"
            ))
            channels = 1

        # Cria config negociada
        from .enums import AudioEncoding
        if isinstance(encoding, str):
            encoding = AudioEncoding(encoding)

        negotiated = AudioConfig(
            sample_rate=sample_rate,
            encoding=encoding,
            channels=channels,
            frame_duration_ms=frame_duration
        )

        return negotiated, errors, adjustments

    def _negotiate_vad(
        self,
        requested: VADConfig
    ) -> Tuple[VADConfig, List[ProtocolError], List[Adjustment]]:
        """
        Negocia configuração de VAD.

        Returns:
            Tuple de (config negociada, erros, ajustes)
        """
        errors: List[ProtocolError] = []
        adjustments: List[Adjustment] = []

        # Se VAD não é configurável, usa defaults
        if not self._capabilities.vad_configurable:
            return VADConfig(), errors, adjustments

        # Valores finais
        enabled = requested.enabled
        silence_threshold = requested.silence_threshold_ms
        min_speech = requested.min_speech_ms
        threshold = requested.threshold
        ring_buffer = requested.ring_buffer_frames
        speech_ratio = requested.speech_ratio
        prefix_padding = requested.prefix_padding_ms

        # Ajusta silence_threshold_ms
        silence_threshold, adj = self._clamp_value(
            "vad.silence_threshold_ms",
            silence_threshold,
            VAD_SILENCE_THRESHOLD_MIN,
            VAD_SILENCE_THRESHOLD_MAX
        )
        if adj:
            adjustments.append(adj)

        # Ajusta min_speech_ms
        min_speech, adj = self._clamp_value(
            "vad.min_speech_ms",
            min_speech,
            VAD_MIN_SPEECH_MIN,
            VAD_MIN_SPEECH_MAX
        )
        if adj:
            adjustments.append(adj)

        # Ajusta threshold
        threshold, adj = self._clamp_value(
            "vad.threshold",
            threshold,
            VAD_THRESHOLD_MIN,
            VAD_THRESHOLD_MAX
        )
        if adj:
            adjustments.append(adj)

        # Ajusta ring_buffer_frames
        ring_buffer, adj = self._clamp_value(
            "vad.ring_buffer_frames",
            ring_buffer,
            VAD_RING_BUFFER_MIN,
            VAD_RING_BUFFER_MAX
        )
        if adj:
            adjustments.append(adj)

        # Ajusta speech_ratio
        speech_ratio, adj = self._clamp_value(
            "vad.speech_ratio",
            speech_ratio,
            VAD_SPEECH_RATIO_MIN,
            VAD_SPEECH_RATIO_MAX
        )
        if adj:
            adjustments.append(adj)

        # Ajusta prefix_padding_ms
        prefix_padding, adj = self._clamp_value(
            "vad.prefix_padding_ms",
            prefix_padding,
            VAD_PREFIX_PADDING_MIN,
            VAD_PREFIX_PADDING_MAX
        )
        if adj:
            adjustments.append(adj)

        # Cria config negociada
        negotiated = VADConfig(
            enabled=enabled,
            silence_threshold_ms=int(silence_threshold),
            min_speech_ms=int(min_speech),
            threshold=float(threshold),
            ring_buffer_frames=int(ring_buffer),
            speech_ratio=float(speech_ratio),
            prefix_padding_ms=int(prefix_padding)
        )

        return negotiated, errors, adjustments

    def _find_closest_sample_rate(self, requested: int) -> Optional[int]:
        """Encontra sample rate mais próximo suportado."""
        supported = self._capabilities.supported_sample_rates
        if not supported:
            return None

        # Ordena por distância do solicitado
        sorted_rates = sorted(supported, key=lambda x: abs(x - requested))
        return sorted_rates[0]

    def _clamp_value(
        self,
        field: str,
        value: float,
        min_val: float,
        max_val: float
    ) -> Tuple[float, Optional[Adjustment]]:
        """
        Ajusta valor para dentro do range válido.

        Returns:
            Tuple de (valor ajustado, ajuste se houve)
        """
        if value < min_val:
            return min_val, Adjustment(
                field=field,
                requested=value,
                applied=min_val,
                reason=f"Value below minimum ({min_val})"
            )
        elif value > max_val:
            return max_val, Adjustment(
                field=field,
                requested=value,
                applied=max_val,
                reason=f"Value above maximum ({max_val})"
            )
        return value, None


def negotiate_config(
    capabilities: ProtocolCapabilities,
    requested_audio: Optional[AudioConfig],
    requested_vad: Optional[VADConfig]
) -> NegotiationResult:
    """
    Função de conveniência para negociar configuração.

    Args:
        capabilities: Capacidades do servidor
        requested_audio: Configuração de áudio solicitada
        requested_vad: Configuração de VAD solicitada

    Returns:
        Resultado da negociação
    """
    negotiator = ConfigNegotiator(capabilities)
    return negotiator.negotiate(requested_audio, requested_vad)
