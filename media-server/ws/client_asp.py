"""
Handler ASP para o cliente WebSocket do Media Server

Implementa o handshake e negociação de configuração ASP no lado do cliente.
"""

import logging
import asyncio
import json
from dataclasses import dataclass
from typing import Optional, Tuple
from websockets.client import WebSocketClientProtocol

from asp_protocol import (
    # Config
    AudioConfig as ASPAudioConfig,
    VADConfig,
    ProtocolCapabilities,
    NegotiatedConfig,
    AudioEncoding,
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
    # Enums
    SessionStatus,
    MessageType,
)
from config import ASP_CONFIG

logger = logging.getLogger("media-server.asp")


# Timeouts do ASP (configuráveis via ambiente)
CAPS_TIMEOUT = ASP_CONFIG["caps_timeout"]
SESSION_START_TIMEOUT = ASP_CONFIG["session_start_timeout"]


@dataclass
class ASPClientSession:
    """Sessão ASP do cliente com configuração negociada."""
    session_id: str
    call_id: Optional[str]
    negotiated: NegotiatedConfig
    server_capabilities: ProtocolCapabilities
    legacy_mode: bool = False


class ASPClientHandler:
    """Handler ASP para o cliente Media Server."""

    def __init__(self):
        """Inicializa o handler."""
        self._server_capabilities: Optional[ProtocolCapabilities] = None
        self._session: Optional[ASPClientSession] = None

    @property
    def server_capabilities(self) -> Optional[ProtocolCapabilities]:
        """Retorna as capabilities do servidor (após handshake)."""
        return self._server_capabilities

    @property
    def current_session(self) -> Optional[ASPClientSession]:
        """Retorna a sessão atual."""
        return self._session

    @property
    def is_asp_session(self) -> bool:
        """Verifica se está em sessão ASP (não legada)."""
        return self._session is not None and not self._session.legacy_mode

    async def receive_capabilities(
        self,
        websocket: WebSocketClientProtocol,
        timeout: float = CAPS_TIMEOUT
    ) -> Tuple[bool, Optional[ProtocolCapabilities]]:
        """
        Aguarda e processa protocol.capabilities do servidor.

        Args:
            websocket: Conexão WebSocket
            timeout: Tempo máximo de espera

        Returns:
            Tuple (sucesso, capabilities)
        """
        try:
            # Aguarda mensagem com timeout
            message = await asyncio.wait_for(websocket.recv(), timeout=timeout)

            # Parse da mensagem
            if isinstance(message, bytes):
                logger.warning("Recebido frame binário antes de capabilities")
                return False, None

            if not is_valid_message(message):
                logger.warning("Servidor não enviou mensagem ASP válida - assumindo legado")
                return False, None

            msg = parse_message(message)

            if not isinstance(msg, ProtocolCapabilitiesMessage):
                logger.warning(f"Esperava capabilities, recebeu {type(msg).__name__}")
                return False, None

            self._server_capabilities = msg.capabilities
            logger.info(f" Recebido capabilities v{msg.capabilities.version}")
            logger.debug(f"   Sample rates: {msg.capabilities.supported_sample_rates}")
            logger.debug(f"   Encodings: {msg.capabilities.supported_encodings}")
            logger.debug(f"   Features: {msg.capabilities.features}")

            return True, msg.capabilities

        except asyncio.TimeoutError:
            logger.warning("Timeout aguardando capabilities - assumindo servidor legado")
            return False, None
        except Exception as e:
            logger.error(f"Erro ao receber capabilities: {e}")
            return False, None

    async def send_session_start(
        self,
        websocket: WebSocketClientProtocol,
        session_id: str,
        call_id: Optional[str] = None,
        audio_config: Optional[ASPAudioConfig] = None,
        vad_config: Optional[VADConfig] = None,
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        Envia session.start (sem aguardar resposta).

        A resposta deve ser processada pelo receive loop via process_session_started().

        Returns:
            True se enviado com sucesso
        """
        # Usa defaults se não especificado
        if audio_config is None:
            audio_config = ASPAudioConfig(
                sample_rate=8000,
                encoding=AudioEncoding.PCM_S16LE,
                channels=1,
                frame_duration_ms=20
            )

        if vad_config is None:
            vad_config = VADConfig()

        # Cria e envia session.start
        msg = ASPSessionStartMessage(
            session_id=session_id,
            call_id=call_id,
            audio=audio_config,
            vad=vad_config,
            metadata=metadata
        )

        try:
            await websocket.send(msg.to_json())
            logger.info(f" Enviado session.start: {session_id[:8]}")
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar session.start: {e}")
            return False

    def process_session_started(
        self,
        response: ASPSessionStartedMessage,
        session_id: str,
        call_id: Optional[str] = None
    ) -> Tuple[bool, Optional[ASPClientSession]]:
        """
        Processa resposta session.started recebida pelo receive loop.

        Args:
            response: Mensagem session.started recebida
            session_id: ID da sessão
            call_id: ID da chamada SIP

        Returns:
            Tuple (sucesso, ASPClientSession se aceita)
        """
        if response.is_accepted:
            logger.info(f" Sessão ASP aceita: {session_id[:8]} (status={response.status.value})")

            if response.negotiated and response.negotiated.has_adjustments():
                for adj in response.negotiated.adjustments:
                    logger.info(f"   ️ Ajuste: {adj.field}: {adj.requested} → {adj.applied}")

            self._session = ASPClientSession(
                session_id=session_id,
                call_id=call_id,
                negotiated=response.negotiated,
                server_capabilities=self._server_capabilities,
                legacy_mode=False
            )

            return True, self._session

        else:
            logger.warning(f" Sessão ASP rejeitada: {session_id[:8]}")
            if response.errors:
                for err in response.errors:
                    logger.warning(f"   - [{err.code}] {err.message}")
            return False, None

    async def update_session(
        self,
        websocket: WebSocketClientProtocol,
        session_id: str,
        vad_config: VADConfig,
        timeout: float = 5.0
    ) -> Tuple[bool, Optional[NegotiatedConfig]]:
        """
        Atualiza configuração VAD durante sessão ativa.

        Args:
            websocket: Conexão WebSocket
            session_id: ID da sessão
            vad_config: Nova configuração de VAD
            timeout: Tempo máximo de espera

        Returns:
            Tuple (sucesso, NegotiatedConfig atualizada)
        """
        msg = SessionUpdateMessage(
            session_id=session_id,
            vad=vad_config
        )

        await websocket.send(msg.to_json())
        logger.info(f" Enviado session.update: {session_id[:8]}")

        try:
            response_data = await asyncio.wait_for(websocket.recv(), timeout=timeout)

            if isinstance(response_data, bytes):
                return False, None

            response = parse_message(response_data)

            if isinstance(response, SessionUpdatedMessage):
                if response.status in [SessionStatus.ACCEPTED, SessionStatus.ACCEPTED_WITH_CHANGES]:
                    logger.info(f" Sessão atualizada: {session_id[:8]}")
                    if self._session:
                        self._session.negotiated = response.negotiated
                    return True, response.negotiated
                else:
                    logger.warning(f" Update rejeitado: {session_id[:8]}")
                    return False, None

            return False, None

        except asyncio.TimeoutError:
            logger.error(f"Timeout em session.update: {session_id[:8]}")
            return False, None
        except Exception as e:
            logger.error(f"Erro em update_session: {e}")
            return False, None

    async def end_session(
        self,
        websocket: WebSocketClientProtocol,
        session_id: str,
        reason: str = "hangup"
    ):
        """
        Envia session.end para encerrar sessão ASP.

        Args:
            websocket: Conexão WebSocket
            session_id: ID da sessão
            reason: Motivo do encerramento
        """
        msg = ASPSessionEndMessage(
            session_id=session_id,
            reason=reason
        )

        try:
            await websocket.send(msg.to_json())
            logger.info(f" Enviado session.end: {session_id[:8]}")

            # Não aguardamos session.ended - encerramento é fire-and-forget
            self._session = None

        except Exception as e:
            logger.error(f"Erro ao enviar session.end: {e}")

    def is_asp_message(self, data: str) -> bool:
        """Verifica se é uma mensagem ASP."""
        return is_valid_message(data)

    def parse_asp_message(self, data: str):
        """Parse uma mensagem ASP."""
        return parse_message(data)

    def clear_session(self):
        """Limpa sessão atual."""
        self._session = None
        self._server_capabilities = None


def create_vad_config_from_local(local_config: dict) -> VADConfig:
    """
    Cria VADConfig ASP a partir de configuração local.

    Args:
        local_config: Dicionário de configuração local (AUDIO_CONFIG)

    Returns:
        VADConfig configurado
    """
    return VADConfig(
        enabled=True,
        silence_threshold_ms=local_config.get("silence_threshold_ms", 500),
        min_speech_ms=local_config.get("min_speech_ms", 250),
        threshold=0.5,
        ring_buffer_frames=local_config.get("ring_buffer_frames", 5),
        speech_ratio=local_config.get("speech_ratio", 0.4),
        prefix_padding_ms=300
    )


def create_audio_config_from_local(local_config: dict) -> ASPAudioConfig:
    """
    Cria AudioConfig ASP a partir de configuração local.

    Args:
        local_config: Dicionário de configuração local (AUDIO_CONFIG)

    Returns:
        ASPAudioConfig configurado
    """
    return ASPAudioConfig(
        sample_rate=local_config.get("sample_rate", 8000),
        encoding=AudioEncoding.PCM_S16LE,
        channels=local_config.get("channels", 1),
        frame_duration_ms=local_config.get("frame_duration_ms", 20)
    )
