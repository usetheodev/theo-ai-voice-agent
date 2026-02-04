"""
Cliente WebSocket para conexão com AI Agent

Suporta o Audio Session Protocol (ASP) para negociação de configuração,
mantendo compatibilidade com servidores legados.
"""

import logging
import asyncio
from typing import Optional, Callable, Dict, Any, Tuple
import websockets
from websockets.client import WebSocketClientProtocol

from config import AI_AGENT_CONFIG, AUDIO_CONFIG
from ws.protocol import (
    AudioConfig,
    AudioDirection,
    SessionStartMessage,
    SessionStartedMessage,
    SessionEndMessage,
    AudioEndMessage,
    ResponseStartMessage,
    ResponseEndMessage,
    ErrorMessage,
    parse_control_message,
    parse_audio_frame,
    create_audio_frame,
    is_audio_frame,
    MessageType,
    session_id_to_hash,
)
from ws.client_asp import (
    ASPClientHandler,
    ASPClientSession,
    create_vad_config_from_local,
    create_audio_config_from_local,
)
from metrics import (
    track_websocket_connected,
    track_websocket_disconnected,
    track_websocket_reconnection,
    WEBSOCKET_STATUS,
)

logger = logging.getLogger("media-server.ws")


class WebSocketClient:
    """Cliente WebSocket com reconexão automática

    Suporta o Audio Session Protocol (ASP) para negociação de configuração
    de áudio e VAD, mantendo compatibilidade com servidores legados.
    """

    def __init__(self):
        self.url = AI_AGENT_CONFIG["url"]
        self.ws: Optional[WebSocketClientProtocol] = None
        self._connected = asyncio.Event()
        self._running = False
        self._reconnect_task: Optional[asyncio.Task] = None

        # ASP Handler
        self._asp_handler = ASPClientHandler()
        self._asp_mode = False  # True se servidor suporta ASP
        self._asp_sessions: Dict[str, ASPClientSession] = {}

        # Callbacks
        self.on_session_started: Optional[Callable[[str], None]] = None
        self.on_response_start: Optional[Callable[[str, str], None]] = None  # session_id, text
        self.on_response_audio: Optional[Callable[[str, bytes], None]] = None  # session_id, audio
        self.on_response_end: Optional[Callable[[str], None]] = None  # session_id
        self.on_error: Optional[Callable[[str, str, str], None]] = None  # session_id, code, message

        # Session state
        self._pending_sessions: Dict[str, asyncio.Future] = {}
        self._pending_asp_sessions: Dict[str, Tuple[asyncio.Future, str]] = {}  # session_id -> (future, call_id)
        self._session_hash_lookup: Dict[str, str] = {}  # Para parse de frames

    async def connect(self) -> bool:
        """Conecta ao AI Agent

        Implementa o handshake ASP:
        1. Conecta via WebSocket
        2. Aguarda protocol.capabilities do servidor
        3. Se receber, entra em modo ASP
        4. Se timeout, assume servidor legado
        """
        self._running = True
        WEBSOCKET_STATUS.state('connecting')

        try:
            logger.info(f"🔌 Conectando ao AI Agent: {self.url}")

            self.ws = await websockets.connect(
                self.url,
                ping_interval=AI_AGENT_CONFIG["ping_interval"],
                ping_timeout=10,
                close_timeout=5,
            )

            logger.info("✅ Conectado ao AI Agent")

            # ASP: Aguarda capabilities do servidor
            success, caps = await self._asp_handler.receive_capabilities(self.ws)

            if success:
                self._asp_mode = True
                logger.info(f"🔒 Modo ASP ativado (server v{caps.version})")
            else:
                self._asp_mode = False
                logger.info("📜 Modo legado (servidor sem ASP)")

            self._connected.set()
            track_websocket_connected()

            # Inicia task de recebimento
            asyncio.create_task(self._receive_loop())

            return True

        except Exception as e:
            logger.error(f"❌ Erro ao conectar: {e}")
            self._connected.clear()
            track_websocket_disconnected()
            return False

    @property
    def is_asp_mode(self) -> bool:
        """Verifica se está em modo ASP."""
        return self._asp_mode

    def get_negotiated_vad_config(self, session_id: str) -> Optional[dict]:
        """Retorna configuração VAD negociada para uma sessão."""
        asp_session = self._asp_sessions.get(session_id)
        if asp_session and asp_session.negotiated:
            return asp_session.negotiated.vad.to_dict()
        return None

    async def disconnect(self):
        """Desconecta do AI Agent"""
        self._running = False
        self._connected.clear()

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

        track_websocket_disconnected()
        logger.info("📴 Desconectado do AI Agent")

    async def wait_connected(self, timeout: float = 30) -> bool:
        """Aguarda conexão estar pronta"""
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @property
    def is_connected(self) -> bool:
        """Verifica se está conectado"""
        return self._connected.is_set() and self.ws is not None

    async def start_session(self, session_id: str, call_id: str) -> bool:
        """Inicia nova sessão de conversação

        Se em modo ASP, usa o protocolo ASP com negociação de configuração.
        Caso contrário, usa protocolo legado.
        """
        if not self.is_connected:
            logger.error("Não conectado ao AI Agent")
            return False

        try:
            if self._asp_mode:
                # Modo ASP: usa handler com negociação
                return await self._start_session_asp(session_id, call_id)
            else:
                # Modo legado
                return await self._start_session_legacy(session_id, call_id)

        except Exception as e:
            logger.error(f"Erro ao iniciar sessão: {e}")
            return False

    async def _start_session_asp(self, session_id: str, call_id: str) -> bool:
        """Inicia sessão usando protocolo ASP."""
        # Cria configs a partir das configurações locais
        audio_config = create_audio_config_from_local(AUDIO_CONFIG)
        vad_config = create_vad_config_from_local(AUDIO_CONFIG)

        # Cria Future para aguardar resposta
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_asp_sessions[session_id] = (future, call_id)

        # Envia session.start (sem aguardar resposta aqui)
        sent = await self._asp_handler.send_session_start(
            websocket=self.ws,
            session_id=session_id,
            call_id=call_id,
            audio_config=audio_config,
            vad_config=vad_config,
            metadata={"source": "media-server"}
        )

        if not sent:
            self._pending_asp_sessions.pop(session_id, None)
            return False

        try:
            # Aguarda resposta via receive loop (timeout 10s)
            asp_session = await asyncio.wait_for(future, timeout=10.0)

            if asp_session:
                # Armazena sessão ASP
                self._asp_sessions[session_id] = asp_session

                # Registra session_id no lookup para parse de frames de áudio
                hash_hex = session_id_to_hash(session_id).hex()
                self._session_hash_lookup[hash_hex] = session_id
                logger.debug(f"[{session_id[:8]}] Hash registrado: {hash_hex}")

                # Log da configuração negociada
                neg = asp_session.negotiated
                logger.info(f"[{session_id[:8]}] Config negociada: "
                           f"sample_rate={neg.audio.sample_rate}, "
                           f"vad.silence={neg.vad.silence_threshold_ms}ms")

                if self.on_session_started:
                    self.on_session_started(session_id)

                return True

            return False

        except asyncio.TimeoutError:
            logger.error(f"[{session_id[:8]}] Timeout aguardando session.started")
            self._pending_asp_sessions.pop(session_id, None)
            return False

    async def _start_session_legacy(self, session_id: str, call_id: str) -> bool:
        """Inicia sessão usando protocolo legado."""
        # Cria mensagem
        audio_config = AudioConfig(
            sample_rate=AUDIO_CONFIG["sample_rate"],
            channels=AUDIO_CONFIG["channels"],
            sample_width=AUDIO_CONFIG["sample_width"]
        )

        msg = SessionStartMessage(
            session_id=session_id,
            call_id=call_id,
            audio_config=audio_config
        )

        # Envia
        await self.ws.send(msg.to_json())

        # Aguarda confirmação (com timeout)
        future = asyncio.get_event_loop().create_future()
        self._pending_sessions[session_id] = future

        try:
            await asyncio.wait_for(future, timeout=10)

            # Registra session_id no lookup para parse de frames de áudio
            hash_hex = session_id_to_hash(session_id).hex()
            self._session_hash_lookup[hash_hex] = session_id
            logger.debug(f"[{session_id[:8]}] Hash registrado: {hash_hex}")

            logger.info(f"✅ Sessão iniciada (legado): {session_id[:8]}")
            return True
        except asyncio.TimeoutError:
            logger.error(f"Timeout ao iniciar sessão: {session_id[:8]}")
            return False
        finally:
            self._pending_sessions.pop(session_id, None)

    async def send_audio(self, session_id: str, audio_data: bytes):
        """Envia áudio para o AI Agent"""
        if not self.is_connected:
            return

        try:
            frame = create_audio_frame(
                session_id=session_id,
                audio_data=audio_data,
                direction=AudioDirection.INBOUND
            )
            await self.ws.send(frame)

        except Exception as e:
            logger.error(f"Erro ao enviar áudio: {e}")

    async def send_audio_end(self, session_id: str):
        """Notifica fim do áudio do usuário"""
        if not self.is_connected:
            return

        try:
            msg = AudioEndMessage(session_id=session_id)
            await self.ws.send(msg.to_json())
            logger.debug(f"[{session_id[:8]}] Audio end enviado")

        except Exception as e:
            logger.error(f"Erro ao enviar audio.end: {e}")

    async def end_session(self, session_id: str, reason: str = "hangup"):
        """Encerra sessão

        Usa ASP se disponível, caso contrário protocolo legado.
        """
        if not self.is_connected:
            return

        try:
            if self._asp_mode and session_id in self._asp_sessions:
                # Modo ASP
                await self._asp_handler.end_session(self.ws, session_id, reason)
                del self._asp_sessions[session_id]
            else:
                # Modo legado
                msg = SessionEndMessage(session_id=session_id, reason=reason)
                await self.ws.send(msg.to_json())

            # Remove session_id do lookup
            hash_hex = session_id_to_hash(session_id).hex()
            self._session_hash_lookup.pop(hash_hex, None)

            logger.info(f"📴 Sessão encerrada: {session_id[:8]}")

        except Exception as e:
            logger.error(f"Erro ao encerrar sessão: {e}")

    async def update_vad_config(self, session_id: str, **vad_params) -> bool:
        """
        Atualiza configuração VAD durante sessão ativa (somente ASP).

        Args:
            session_id: ID da sessão
            **vad_params: Parâmetros VAD a atualizar (silence_threshold_ms, etc.)

        Returns:
            True se atualização aceita
        """
        if not self._asp_mode:
            logger.warning("update_vad_config requer modo ASP")
            return False

        if session_id not in self._asp_sessions:
            logger.warning(f"Sessão ASP não encontrada: {session_id[:8]}")
            return False

        from asp_protocol import VADConfig

        # Merge com config atual
        current = self._asp_sessions[session_id].negotiated.vad
        new_config = current.merge(vad_params)

        success, negotiated = await self._asp_handler.update_session(
            self.ws,
            session_id,
            new_config
        )

        if success and negotiated:
            self._asp_sessions[session_id].negotiated = negotiated
            logger.info(f"[{session_id[:8]}] VAD atualizada via ASP")
            return True

        return False

    async def _receive_loop(self):
        """Loop de recebimento de mensagens"""
        try:
            async for message in self.ws:
                await self._handle_message(message)

        except websockets.ConnectionClosed as e:
            logger.warning(f"Conexão fechada: {e.code}")
        except Exception as e:
            logger.error(f"Erro no receive loop: {e}")
        finally:
            self._connected.clear()
            track_websocket_disconnected()
            if self._running:
                asyncio.create_task(self._reconnect())

    async def _handle_message(self, message):
        """Processa mensagem recebida"""
        try:
            if isinstance(message, bytes):
                # Frame de áudio
                if is_audio_frame(message):
                    await self._handle_audio_frame(message)
            else:
                # Mensagem de controle
                await self._handle_control_message(message)

        except Exception as e:
            logger.error(f"Erro ao processar mensagem: {e}")

    async def _handle_control_message(self, data: str):
        """Processa mensagem de controle

        Suporta mensagens ASP e legadas.
        """
        try:
            # Verifica se é mensagem ASP
            if self._asp_mode and self._asp_handler.is_asp_message(data):
                await self._handle_asp_control_message(data)
                return

            # Processa mensagens de controle padrão (legado)
            msg = parse_control_message(data)

            if isinstance(msg, SessionStartedMessage):
                # Resolve future pendente (modo legado)
                future = self._pending_sessions.get(msg.session_id)
                if future and not future.done():
                    future.set_result(True)
                if self.on_session_started:
                    self.on_session_started(msg.session_id)

            elif isinstance(msg, ResponseStartMessage):
                logger.info(f"[{msg.session_id[:8]}] 🤖 Resposta: {msg.text[:50]}...")
                if self.on_response_start:
                    self.on_response_start(msg.session_id, msg.text)

            elif isinstance(msg, ResponseEndMessage):
                logger.debug(f"[{msg.session_id[:8]}] Resposta concluída")
                if self.on_response_end:
                    self.on_response_end(msg.session_id)

            elif isinstance(msg, ErrorMessage):
                logger.error(f"[{msg.session_id[:8]}] Erro: {msg.code} - {msg.message}")
                if self.on_error:
                    self.on_error(msg.session_id, msg.code, msg.message)

        except Exception as e:
            logger.error(f"Erro ao processar mensagem de controle: {e}")

    async def _handle_asp_control_message(self, data: str):
        """Processa mensagens de controle ASP."""
        import json
        from asp_protocol import (
            parse_message,
            SessionStartedMessage as ASPSessionStartedMessage,
            SessionUpdatedMessage,
            SessionEndedMessage,
            ProtocolErrorMessage,
        )

        try:
            msg = parse_message(data)

            if isinstance(msg, ASPSessionStartedMessage):
                # Resolve future pendente para session.started
                session_id = msg.session_id
                pending = self._pending_asp_sessions.pop(session_id, None)

                if pending:
                    future, call_id = pending
                    # Processa resposta através do handler
                    success, asp_session = self._asp_handler.process_session_started(
                        msg, session_id, call_id
                    )
                    if not future.done():
                        future.set_result(asp_session if success else None)
                else:
                    logger.warning(f"session.started sem pending: {session_id[:8]}")

            elif isinstance(msg, SessionUpdatedMessage):
                logger.debug(f"session.updated: {msg.session_id[:8]}")

            elif isinstance(msg, SessionEndedMessage):
                logger.info(f"session.ended: {msg.session_id[:8]}")

            elif isinstance(msg, ProtocolErrorMessage):
                logger.error(f"ASP protocol.error: {msg.code} - {msg.message}")

        except Exception as e:
            logger.error(f"Erro ao processar mensagem ASP: {e}")

    async def _handle_audio_frame(self, data: bytes):
        """Processa frame de áudio recebido"""
        try:
            frame = parse_audio_frame(data, self._session_hash_lookup)

            if self.on_response_audio:
                self.on_response_audio(frame.session_id, frame.audio_data)

        except Exception as e:
            logger.error(f"Erro ao processar frame de áudio: {e}")

    async def _reconnect(self):
        """Tenta reconectar ao AI Agent"""
        if not self._running:
            return

        interval = AI_AGENT_CONFIG["reconnect_interval"]
        max_attempts = AI_AGENT_CONFIG["max_reconnect_attempts"]

        for attempt in range(max_attempts):
            if not self._running:
                return

            track_websocket_reconnection()
            logger.info(f"🔄 Tentando reconectar ({attempt + 1}/{max_attempts})...")
            await asyncio.sleep(interval)

            if await self.connect():
                return

        logger.error("❌ Falha ao reconectar após múltiplas tentativas")
