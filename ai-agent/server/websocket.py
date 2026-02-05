"""
Servidor WebSocket para AI Agent

Suporta o Audio Session Protocol (ASP) para negociação de configuração,
mantendo compatibilidade com clientes legados.
"""

import logging
import asyncio
import time
import json
from typing import Set, Optional, Dict
import websockets
from websockets.server import WebSocketServerProtocol

from config import WS_CONFIG, SESSION_CONFIG, AUDIO_CONFIG
from ws.protocol import (
    MessageType,
    AudioConfig,
    AudioDirection,
    SessionStartMessage,
    SessionStartedMessage,
    SessionEndMessage,
    AudioEndMessage,
    ResponseStartMessage,
    ResponseEndMessage,
    ErrorMessage,
    AudioFrame,
    parse_control_message,
    parse_audio_frame,
    create_audio_frame,
    is_audio_frame,
)
from server.session import SessionManager, Session
from server.asp_handler import (
    ASPHandler,
    ASPSession,
)
from metrics import (
    track_websocket_connect,
    track_websocket_disconnect,
    track_audio_received,
    track_audio_sent,
    track_pipeline_error,
    VOICE_TTFB_SECONDS,
)

logger = logging.getLogger("ai-agent.server")


class AIAgentServer:
    """Servidor WebSocket para processamento de conversação

    Suporta o Audio Session Protocol (ASP) para negociação de configuração
    de áudio e VAD, mantendo compatibilidade com clientes legados.
    """

    def __init__(self):
        self.session_manager = SessionManager()
        self.connections: Set[WebSocketServerProtocol] = set()
        self._server: Optional[websockets.WebSocketServer] = None
        self._running = False
        self._asp_handler = ASPHandler()
        # Mapeia websocket -> ASPSession para sessões ASP
        self._asp_sessions: Dict[WebSocketServerProtocol, ASPSession] = {}

    async def start(self, host: str = None, port: int = None):
        """Inicia o servidor WebSocket"""
        host = host or WS_CONFIG["host"]
        port = port or WS_CONFIG["port"]

        self._running = True

        self._server = await websockets.serve(
            self._handle_connection,
            host,
            port,
            ping_interval=WS_CONFIG["ping_interval"],
            ping_timeout=WS_CONFIG["ping_timeout"],
            max_size=WS_CONFIG["max_message_size"],
        )

        logger.info(f" AI Agent Server iniciado em ws://{host}:{port}")

        # Task de limpeza de sessões
        asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        """Para o servidor"""
        self._running = False

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        # Fecha todas as conexões
        for ws in self.connections.copy():
            await ws.close()

        logger.info(" AI Agent Server parado")

    async def _handle_connection(self, websocket: WebSocketServerProtocol):
        """Handler para nova conexão WebSocket

        Implementa o handshake ASP:
        1. Envia protocol.capabilities imediatamente
        2. Aguarda session.start (ASP ou legado)
        3. Negocia e responde com session.started
        """
        self.connections.add(websocket)
        track_websocket_connect()
        client_addr = websocket.remote_address
        logger.info(f" Cliente conectado: {client_addr}")

        try:
            # ASP: Envia capabilities imediatamente após conexão
            await self._asp_handler.send_capabilities(websocket)

            async for message in websocket:
                await self._handle_message(websocket, message)

        except websockets.ConnectionClosed as e:
            logger.info(f" Cliente desconectado: {client_addr} ({e.code})")
        except Exception as e:
            logger.error(f"Erro na conexão {client_addr}: {e}")
        finally:
            # Limpa sessão ASP se existir
            if websocket in self._asp_sessions:
                del self._asp_sessions[websocket]
            self.connections.discard(websocket)
            track_websocket_disconnect()

    async def _handle_message(self, websocket: WebSocketServerProtocol, message):
        """Processa mensagem recebida"""
        try:
            if isinstance(message, bytes):
                # Mensagem de áudio (binary)
                if is_audio_frame(message):
                    await self._handle_audio_frame(websocket, message)
                else:
                    logger.warning(f"Frame binário inválido: {len(message)} bytes")
            else:
                # Mensagem de controle (JSON)
                await self._handle_control_message(websocket, message)

        except Exception as e:
            logger.error(f"Erro ao processar mensagem: {e}")
            import traceback
            traceback.print_exc()

    async def _handle_control_message(self, websocket: WebSocketServerProtocol, data: str):
        """Processa mensagem de controle JSON

        Suporta tanto o protocolo ASP quanto o legado.
        """
        try:
            # Tenta primeiro como mensagem ASP
            if self._asp_handler.is_asp_message(data):
                await self._handle_asp_message(websocket, data)
                return

            # Fallback: protocolo legado
            msg = parse_control_message(data)

            if isinstance(msg, SessionStartMessage):
                await self._handle_session_start(websocket, msg)
            elif isinstance(msg, SessionEndMessage):
                await self._handle_session_end(websocket, msg)
            elif isinstance(msg, AudioEndMessage):
                await self._handle_audio_end(websocket, msg)
            else:
                logger.warning(f"Mensagem de controle inesperada: {msg.type}")

        except Exception as e:
            logger.error(f"Erro ao processar mensagem de controle: {e}")

    async def _handle_asp_message(self, websocket: WebSocketServerProtocol, data: str):
        """Processa mensagem do protocolo ASP"""
        from asp_protocol import (
            SessionUpdateMessage,
            MessageType,
        )

        try:
            msg = self._asp_handler.parse_asp_message(data)
            msg_type = msg.message_type

            if msg_type == MessageType.SESSION_START:
                await self._handle_asp_session_start(websocket, msg)

            elif msg_type == MessageType.SESSION_UPDATE:
                await self._handle_asp_session_update(websocket, msg)

            elif msg_type == MessageType.SESSION_END:
                await self._handle_asp_session_end(websocket, msg)

            else:
                logger.warning(f"Mensagem ASP inesperada: {msg_type}")

        except Exception as e:
            logger.error(f"Erro ao processar mensagem ASP: {e}")
            import traceback
            traceback.print_exc()

    async def _handle_asp_session_start(self, websocket: WebSocketServerProtocol, msg):
        """Handler para session.start ASP"""
        success, asp_session = await self._asp_handler.handle_session_start(websocket, msg)

        if not success:
            return

        # Armazena sessão ASP
        self._asp_sessions[websocket] = asp_session

        # Cria sessão interna usando config negociada
        negotiated = asp_session.negotiated
        audio_config = AudioConfig(
            sample_rate=negotiated.audio.sample_rate,
            channels=negotiated.audio.channels,
            sample_width=2,  # 16-bit
            frame_duration_ms=negotiated.audio.frame_duration_ms
        )

        session = await self.session_manager.create_session(
            session_id=msg.session_id,
            call_id=msg.call_id,
            audio_config=audio_config
        )

        # Aplica config VAD negociada ao pipeline
        if hasattr(session, 'audio_buffer') and session.audio_buffer:
            vad = negotiated.vad
            session.audio_buffer.silence_threshold = vad.silence_threshold_ms
            session.audio_buffer.min_speech_ms = vad.min_speech_ms
            logger.info(f"[{msg.session_id[:8]}] VAD config aplicada: "
                       f"silence={vad.silence_threshold_ms}ms, min_speech={vad.min_speech_ms}ms")

        websocket.session_id = msg.session_id

        # Envia saudação
        await self._send_greeting(websocket, session)

    async def _handle_asp_session_update(self, websocket: WebSocketServerProtocol, msg):
        """Handler para session.update ASP"""
        asp_session = self._asp_sessions.get(websocket)
        if not asp_session:
            logger.warning(f"session.update sem sessão ASP ativa")
            return

        success, new_config = await self._asp_handler.handle_session_update(
            websocket,
            msg,
            asp_session.negotiated.audio
        )

        if success and new_config:
            # Atualiza sessão ASP
            asp_session.negotiated = new_config

            # Atualiza config na sessão interna
            session = await self.session_manager.get_session(msg.session_id)
            if session and hasattr(session, 'audio_buffer') and session.audio_buffer:
                vad = new_config.vad
                session.audio_buffer.silence_threshold = vad.silence_threshold_ms
                session.audio_buffer.min_speech_ms = vad.min_speech_ms
                logger.info(f"[{msg.session_id[:8]}] VAD atualizada: "
                           f"silence={vad.silence_threshold_ms}ms")

    async def _handle_asp_session_end(self, websocket: WebSocketServerProtocol, msg):
        """Handler para session.end ASP"""
        session = await self.session_manager.get_session(msg.session_id)

        duration = 0.0
        statistics = None

        if session:
            duration = time.time() - session.created_at if hasattr(session, 'created_at') else 0.0
            statistics = {
                "audio_frames_received": getattr(session, 'frames_received', 0),
                "audio_frames_sent": getattr(session, 'frames_sent', 0),
                "vad_speech_events": getattr(session, 'speech_events', 0),
                "barge_in_count": getattr(session, 'barge_in_count', 0),
            }

        await self._asp_handler.handle_session_end(
            websocket,
            msg,
            duration_seconds=duration,
            statistics=statistics
        )

        # Encerra sessão interna
        await self.session_manager.end_session(msg.session_id, reason=msg.reason)

        # Remove sessão ASP
        if websocket in self._asp_sessions:
            del self._asp_sessions[websocket]

    async def _handle_session_start(self, websocket: WebSocketServerProtocol, msg: SessionStartMessage):
        """Inicia nova sessão de conversação"""
        logger.info(f" Iniciando sessão: {msg.session_id[:8]} (call: {msg.call_id})")

        # Cria sessão
        session = await self.session_manager.create_session(
            session_id=msg.session_id,
            call_id=msg.call_id,
            audio_config=msg.audio_config
        )

        # Associa websocket à sessão
        websocket.session_id = msg.session_id

        # Confirma sessão iniciada
        response = SessionStartedMessage(session_id=msg.session_id)
        await websocket.send(response.to_json())

        # Gera e envia saudação
        await self._send_greeting(websocket, session)

    async def _send_greeting(self, websocket: WebSocketServerProtocol, session: Session):
        """Envia saudação inicial"""
        await session.set_state('responding')

        try:
            # Usa versão async para não bloquear o event loop
            greeting_text, greeting_audio = await session.pipeline.generate_greeting_async()

            if greeting_audio:
                # Notifica início da resposta
                start_msg = ResponseStartMessage(
                    session_id=session.session_id,
                    text=greeting_text
                )
                await websocket.send(start_msg.to_json())

                # Envia áudio
                await self._send_audio(websocket, session.session_id, greeting_audio)

                # Notifica fim da resposta
                end_msg = ResponseEndMessage(session_id=session.session_id)
                await websocket.send(end_msg.to_json())

        except Exception as e:
            logger.error(f"Erro ao enviar saudação: {e}")

        await session.set_state('listening')

    async def _handle_session_end(self, websocket: WebSocketServerProtocol, msg: SessionEndMessage):
        """Encerra sessão"""
        logger.info(f" Encerrando sessão: {msg.session_id[:8]} (motivo: {msg.reason})")
        await self.session_manager.end_session(msg.session_id, reason=msg.reason)

    async def _handle_audio_frame(self, websocket: WebSocketServerProtocol, data: bytes):
        """Processa frame de áudio recebido"""
        try:
            # Registra métricas de áudio recebido
            track_audio_received(len(data))

            # Parse frame com lookup de session_id
            lookup = self.session_manager.get_session_id_lookup()
            frame = parse_audio_frame(data, lookup)

            # Busca sessão
            session = await self.session_manager.get_session(frame.session_id)
            if not session:
                # Tenta por hash
                session = await self.session_manager.get_session_by_hash(frame.session_id)

            if not session:
                # Log throttled: comum durante race condition no início da sessão
                if not hasattr(self, '_no_session_warn_count'):
                    self._no_session_warn_count = 0
                self._no_session_warn_count += 1
                if self._no_session_warn_count <= 5 or self._no_session_warn_count % 100 == 0:
                    logger.debug(f"Frame de áudio ignorado: sessão não encontrada (count: {self._no_session_warn_count})")
                return

            # Só processa se estiver ouvindo
            if session.state != 'listening':
                # Log apenas ocasionalmente para não poluir
                session._ignored_frames = getattr(session, '_ignored_frames', 0) + 1
                if session._ignored_frames <= 3 or session._ignored_frames % 50 == 0:
                    logger.debug(f"[{frame.session_id[:8]}] ️ Ignorando frames (state={session.state}, count={session._ignored_frames})")
                return

            # Adiciona ao buffer SEM VAD (o media-server já faz VAD e envia audio.end)
            session.audio_buffer.add_audio_raw(frame.audio_data)
            session.update_activity()

        except Exception as e:
            logger.error(f"Erro ao processar frame de áudio: {e}")

    async def _handle_audio_end(self, websocket: WebSocketServerProtocol, msg: AudioEndMessage):
        """Processa fim do áudio do usuário"""
        logger.info(f"[{msg.session_id[:8]}]  Recebido audio.end")

        session = await self.session_manager.get_session(msg.session_id)
        if not session:
            logger.warning(f"Sessão não encontrada: {msg.session_id[:8]}")
            return

        # Guarda timestamp para cálculo de TTFB
        session.audio_end_timestamp = time.perf_counter()
        session.ttfb_recorded = False

        logger.info(f"[{msg.session_id[:8]}] Buffer atual: {len(session.audio_buffer.buffer)} bytes, state={session.state}")

        # Obtém áudio acumulado
        audio_data = session.audio_buffer.flush()

        if not audio_data or len(audio_data) < 1000:  # Menos de ~60ms
            logger.debug(f"[{msg.session_id[:8]}] Áudio muito curto, ignorando")
            return

        logger.info(f"[{msg.session_id[:8]}] Processando {len(audio_data)} bytes de áudio")

        # Processa pelo pipeline
        await self._process_and_respond(websocket, session, audio_data)

    async def _process_and_respond(
        self,
        websocket: WebSocketServerProtocol,
        session: Session,
        audio_data: bytes
    ):
        """Processa áudio e envia resposta (com suporte a streaming)"""
        await session.set_state('processing')

        try:
            loop = asyncio.get_event_loop()

            # Verifica se pipeline suporta streaming
            if session.pipeline.supports_streaming:
                await self._process_and_respond_stream(websocket, session, audio_data)
            else:
                # Fallback: modo batch
                text_response, audio_response = await loop.run_in_executor(
                    None,
                    session.pipeline.process,
                    audio_data
                )

                if not text_response:
                    await session.set_state('listening')
                    return

                await session.set_state('responding')

                # Notifica início da resposta
                start_msg = ResponseStartMessage(
                    session_id=session.session_id,
                    text=text_response
                )
                await websocket.send(start_msg.to_json())

                # Envia áudio da resposta
                if audio_response:
                    await self._send_audio(websocket, session.session_id, audio_response)

                # Notifica fim da resposta
                end_msg = ResponseEndMessage(session_id=session.session_id)
                await websocket.send(end_msg.to_json())

        except Exception as e:
            logger.error(f"Erro no pipeline: {e}")
            import traceback
            traceback.print_exc()

            # Registra erro
            track_pipeline_error("pipeline")

            # Envia erro
            error_msg = ErrorMessage(
                session_id=session.session_id,
                code="PIPELINE_ERROR",
                message=str(e)
            )
            await websocket.send(error_msg.to_json())

        finally:
            await session.set_state('listening')

    async def _process_and_respond_stream(
        self,
        websocket: WebSocketServerProtocol,
        session: Session,
        audio_data: bytes
    ):
        """Processa áudio com streaming REAL de LLM e TTS

        IMPORTANTE: Envia cada chunk imediatamente ao ser gerado,
        sem acumular em lista. Isso reduz latência de 3-6s para ~1-2s.
        """
        await session.set_state('responding')

        # Flag para controlar se já enviamos response.start
        response_started = False
        chunks_sent = 0

        try:
            # Usa o async generator diretamente - streaming real!
            async for text_chunk, audio_chunk in session.pipeline.process_stream_async(audio_data):
                # Envia response.start no primeiro chunk
                if not response_started:
                    start_msg = ResponseStartMessage(
                        session_id=session.session_id,
                        text=text_chunk
                    )
                    await websocket.send(start_msg.to_json())
                    response_started = True
                    logger.info(f"[{session.session_id[:8]}] ️ Streaming iniciado: {text_chunk[:30]}...")

                # Envia chunk IMEDIATAMENTE - sem acumular!
                if audio_chunk:
                    await self._send_audio_chunk(websocket, session.session_id, audio_chunk)
                    chunks_sent += 1

            # Se não enviou nada, não notifica fim
            if not response_started:
                logger.debug(f"[{session.session_id[:8]}] Nenhum chunk gerado")
                return

            logger.info(f"[{session.session_id[:8]}]  Streaming completo: {chunks_sent} chunks enviados")

        except Exception as e:
            logger.error(f"[{session.session_id[:8]}] Erro no streaming: {e}")
            if not response_started:
                return

        # Notifica fim da resposta
        end_msg = ResponseEndMessage(session_id=session.session_id)
        await websocket.send(end_msg.to_json())

    async def _send_audio_chunk(self, websocket: WebSocketServerProtocol, session_id: str, audio_chunk: bytes):
        """Envia um chunk de áudio diretamente"""
        # Registra TTFB no primeiro chunk
        session = await self.session_manager.get_session(session_id)
        if session and session.audio_end_timestamp > 0 and not session.ttfb_recorded:
            ttfb = time.perf_counter() - session.audio_end_timestamp
            VOICE_TTFB_SECONDS.observe(ttfb)
            session.ttfb_recorded = True
            logger.debug(f"[{session_id[:8]}] ️ TTFB: {ttfb*1000:.0f}ms")

        frame = create_audio_frame(
            session_id=session_id,
            audio_data=audio_chunk,
            direction=AudioDirection.OUTBOUND
        )
        await websocket.send(frame)
        track_audio_sent(len(frame))

    async def _send_audio(self, websocket: WebSocketServerProtocol, session_id: str, audio_data: bytes):
        """Envia áudio em chunks otimizados para baixa latência

        Chunk size configurável via AUDIO_CHUNK_SIZE_BYTES
        Sem delay entre chunks - WebSocket já tem flow control
        """
        CHUNK_SIZE = AUDIO_CONFIG["chunk_size_bytes"]

        for i in range(0, len(audio_data), CHUNK_SIZE):
            chunk = audio_data[i:i + CHUNK_SIZE]
            frame = create_audio_frame(
                session_id=session_id,
                audio_data=chunk,
                direction=AudioDirection.OUTBOUND
            )
            await websocket.send(frame)
            track_audio_sent(len(frame))
            # Removido: await asyncio.sleep(0.01) - WebSocket já faz flow control

    async def _cleanup_loop(self):
        """Loop de limpeza de sessões inativas"""
        cleanup_interval = SESSION_CONFIG.get("cleanup_interval", 60)
        max_idle_seconds = SESSION_CONFIG.get("max_idle_seconds", 300)

        while self._running:
            await asyncio.sleep(cleanup_interval)
            try:
                removed = await self.session_manager.cleanup_stale_sessions(max_idle_seconds=max_idle_seconds)
                if removed > 0:
                    logger.info(f" Removidas {removed} sessões inativas")
            except Exception as e:
                logger.error(f"Erro na limpeza: {e}")


async def run_server():
    """Função helper para rodar o servidor"""
    server = AIAgentServer()
    await server.start()

    try:
        # Mantém servidor rodando
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
