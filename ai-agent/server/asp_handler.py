"""
Handler do Audio Session Protocol (ASP) para AI Agent

Implementa o handshake e negociação de configuração ASP.
"""

import logging
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Optional, Tuple
from websockets.server import WebSocketServerProtocol

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "shared"))

from metrics import (
    track_asp_handshake_success,
    track_asp_handshake_failure,
    track_asp_session_mode,
    track_asp_negotiation_adjustment,
    track_asp_config_value,
    clear_asp_session_metrics,
)

from asp_protocol import (
    # Config
    AudioConfig as ASPAudioConfig,
    VADConfig,
    ProtocolCapabilities,
    NegotiatedConfig,
    # Messages
    ProtocolCapabilitiesMessage,
    SessionStartMessage as ASPSessionStartMessage,
    SessionStartedMessage as ASPSessionStartedMessage,
    SessionUpdateMessage,
    SessionUpdatedMessage,
    SessionEndMessage as ASPSessionEndMessage,
    SessionEndedMessage,
    ProtocolErrorMessage,
    parse_message,
    is_valid_message,
    # Negotiation
    negotiate_config,
    # Enums
    SessionStatus,
    MessageType,
    # Errors
    errors,
)

logger = logging.getLogger("ai-agent.asp")


# Protocol version
ASP_VERSION = "1.0.0"

# Timeout for handshake
HANDSHAKE_TIMEOUT = 30.0  # seconds
CAPS_TIMEOUT = 5.0  # seconds to wait for ASP client


@dataclass
class ASPSession:
    """Sessão ASP com configuração negociada."""
    session_id: str
    call_id: Optional[str]
    negotiated: NegotiatedConfig
    legacy_mode: bool = False
    metadata: Optional[dict] = None


class ASPHandler:
    """Handler do protocolo ASP para o servidor."""

    def __init__(self):
        """Inicializa o handler com capabilities padrão."""
        self._capabilities = ProtocolCapabilities(
            version=ASP_VERSION,
            supported_sample_rates=[8000, 16000],
            supported_encodings=["pcm_s16le", "mulaw", "alaw"],
            supported_frame_durations=[10, 20, 30],
            vad_configurable=True,
            vad_parameters=[
                "silence_threshold_ms",
                "min_speech_ms",
                "threshold",
                "ring_buffer_frames",
                "speech_ratio",
                "prefix_padding_ms"
            ],
            max_session_duration_seconds=3600,
            features=[
                "barge_in",
                "streaming_tts",
                "sentence_pipeline"
            ]
        )

    @property
    def capabilities(self) -> ProtocolCapabilities:
        """Retorna as capabilities do servidor."""
        return self._capabilities

    async def send_capabilities(self, websocket: WebSocketServerProtocol):
        """
        Envia capabilities para o cliente após conexão.

        Args:
            websocket: Conexão WebSocket
        """
        msg = ProtocolCapabilitiesMessage(
            capabilities=self._capabilities,
            version=ASP_VERSION,
            server_id="ai-agent"
        )
        await websocket.send(msg.to_json())
        logger.debug(f"📤 Enviado protocol.capabilities v{ASP_VERSION}")

    async def handle_session_start(
        self,
        websocket: WebSocketServerProtocol,
        message: ASPSessionStartMessage
    ) -> Tuple[bool, Optional[ASPSession]]:
        """
        Processa session.start e retorna resultado da negociação.

        Args:
            websocket: Conexão WebSocket
            message: Mensagem session.start recebida

        Returns:
            Tuple (sucesso, ASPSession se aceito)
        """
        handshake_start = time.perf_counter()
        logger.info(f"📞 ASP session.start: {message.session_id[:8]}")

        # Negocia configuração
        result = negotiate_config(
            self._capabilities,
            message.audio,
            message.vad
        )

        # Prepara resposta
        response = ASPSessionStartedMessage(
            session_id=message.session_id,
            status=result.status,
            negotiated=result.negotiated if result.success else None,
            errors=result.errors if not result.success else None
        )

        await websocket.send(response.to_json())

        # Calcula duração do handshake
        handshake_duration = time.perf_counter() - handshake_start

        if result.success:
            logger.info(f"✅ Sessão ASP aceita: {message.session_id[:8]} (status={result.status.value})")

            # Registra métricas de sucesso
            track_asp_handshake_success(result.status.value, handshake_duration)
            track_asp_session_mode(message.session_id, is_asp=True)

            # Registra valores de config negociados
            neg = result.negotiated
            track_asp_config_value(message.session_id, 'vad_silence_threshold_ms', neg.vad.silence_threshold_ms)
            track_asp_config_value(message.session_id, 'vad_min_speech_ms', neg.vad.min_speech_ms)
            track_asp_config_value(message.session_id, 'vad_threshold', neg.vad.threshold)
            track_asp_config_value(message.session_id, 'audio_sample_rate', neg.audio.sample_rate)

            if result.negotiated.has_adjustments():
                for adj in result.negotiated.adjustments:
                    logger.info(f"   ⚠️ Ajuste: {adj.field}: {adj.requested} → {adj.applied}")
                    track_asp_negotiation_adjustment(adj.field)

            return True, ASPSession(
                session_id=message.session_id,
                call_id=message.call_id,
                negotiated=result.negotiated,
                legacy_mode=False,
                metadata=message.metadata
            )
        else:
            logger.warning(f"❌ Sessão ASP rejeitada: {message.session_id[:8]}")
            for err in result.errors:
                logger.warning(f"   - [{err.code}] {err.message}")
                track_asp_handshake_failure(err.category)
            return False, None

    async def handle_session_update(
        self,
        websocket: WebSocketServerProtocol,
        message: SessionUpdateMessage,
        current_audio: ASPAudioConfig
    ) -> Tuple[bool, Optional[NegotiatedConfig]]:
        """
        Processa session.update durante sessão ativa.

        Args:
            websocket: Conexão WebSocket
            message: Mensagem session.update
            current_audio: Configuração de áudio atual (não pode mudar)

        Returns:
            Tuple (sucesso, NegotiatedConfig atualizada)
        """
        logger.info(f"🔄 ASP session.update: {message.session_id[:8]}")

        # Negocia apenas VAD (áudio não pode mudar mid-session)
        result = negotiate_config(
            self._capabilities,
            current_audio,  # Mantém áudio atual
            message.vad
        )

        response = SessionUpdatedMessage(
            session_id=message.session_id,
            status=result.status,
            negotiated=result.negotiated if result.success else None,
            errors=result.errors if not result.success else None
        )

        await websocket.send(response.to_json())

        if result.success:
            logger.info(f"✅ Sessão ASP atualizada: {message.session_id[:8]}")
            return True, result.negotiated
        else:
            logger.warning(f"❌ Update ASP rejeitado: {message.session_id[:8]}")
            return False, None

    async def handle_session_end(
        self,
        websocket: WebSocketServerProtocol,
        message: ASPSessionEndMessage,
        duration_seconds: float = 0.0,
        statistics: dict = None
    ):
        """
        Processa session.end e envia confirmação.

        Args:
            websocket: Conexão WebSocket
            message: Mensagem session.end
            duration_seconds: Duração da sessão
            statistics: Estatísticas da sessão
        """
        logger.info(f"📴 ASP session.end: {message.session_id[:8]} (reason={message.reason})")

        from asp_protocol import SessionStatistics

        stats = None
        if statistics:
            stats = SessionStatistics(**statistics)

        response = SessionEndedMessage(
            session_id=message.session_id,
            duration_seconds=duration_seconds,
            statistics=stats
        )

        await websocket.send(response.to_json())

        # Limpa métricas da sessão
        clear_asp_session_metrics(message.session_id)

        logger.info(f"✅ Sessão ASP encerrada: {message.session_id[:8]}")

    async def send_error(
        self,
        websocket: WebSocketServerProtocol,
        error: 'ProtocolError',
        session_id: Optional[str] = None
    ):
        """
        Envia mensagem de erro do protocolo.

        Args:
            websocket: Conexão WebSocket
            error: Erro a enviar
            session_id: ID da sessão (se aplicável)
        """
        msg = ProtocolErrorMessage(
            error=error,
            session_id=session_id
        )
        await websocket.send(msg.to_json())
        logger.warning(f"📤 Enviado protocol.error: [{error.code}] {error.message}")

    def is_asp_message(self, data: str) -> bool:
        """
        Verifica se uma mensagem é do protocolo ASP.

        Args:
            data: String JSON da mensagem

        Returns:
            True se for mensagem ASP válida
        """
        return is_valid_message(data)

    def parse_asp_message(self, data: str):
        """
        Parse uma mensagem ASP.

        Args:
            data: String JSON da mensagem

        Returns:
            Objeto da mensagem apropriada
        """
        return parse_message(data)


def create_default_vad_config() -> VADConfig:
    """Cria configuração VAD padrão para clientes legados."""
    return VADConfig(
        enabled=True,
        silence_threshold_ms=500,
        min_speech_ms=250,
        threshold=0.5,
        ring_buffer_frames=5,
        speech_ratio=0.4,
        prefix_padding_ms=300
    )


def create_default_audio_config() -> ASPAudioConfig:
    """Cria configuração de áudio padrão para clientes legados."""
    from asp_protocol import AudioEncoding
    return ASPAudioConfig(
        sample_rate=8000,
        encoding=AudioEncoding.PCM_S16LE,
        channels=1,
        frame_duration_ms=20
    )
