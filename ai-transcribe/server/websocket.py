"""
Servidor WebSocket para AI Transcribe

Recebe audio via ASP Protocol, transcreve e indexa no Elasticsearch.
"""

import sys
import logging
import asyncio
import time
from typing import Set, Dict, Optional

import websockets
from websockets.server import WebSocketServerProtocol

# Adiciona shared ao path
sys.path.insert(0, "/app/shared")
sys.path.insert(0, "./shared")

from config import WS_CONFIG, SESSION_CONFIG
from server.session import SessionManager, TranscribeSession
from transcriber.stt_provider import STTProvider
from indexer.elasticsearch_client import ElasticsearchClient
from indexer.document_builder import DocumentBuilder
from indexer.bulk_indexer import BulkIndexer
from metrics import (
    track_websocket_connect,
    track_websocket_disconnect,
    track_audio_received,
    track_transcription,
    track_es_index,
    track_es_connection_status,
    track_embedding,
)
from embeddings import EmbeddingProvider

logger = logging.getLogger("ai-transcribe.server")


# Protocolo de audio - usa modulo compartilhado para evitar desincronizacao
from ws.protocol import (
    AUDIO_MAGIC,
    AUDIO_HEADER_SIZE,
    AudioDirection,
    is_audio_frame as _is_audio_frame,
    parse_audio_frame as _parse_audio_frame_full,
    session_id_to_hash,
)

# Direcoes do audio (re-export para compatibilidade)
DIRECTION_INBOUND = AudioDirection.INBOUND
DIRECTION_OUTBOUND = AudioDirection.OUTBOUND


def _parse_audio_frame(data: bytes) -> tuple:
    """
    Parse de frame de audio usando modulo compartilhado.

    Returns:
        Tuple (session_hash_hex, direction, audio_data)
    """
    if not _is_audio_frame(data):
        return None, None, None

    direction = data[1]  # 0=inbound, 1=outbound
    session_hash = data[2:10]  # 8 bytes de hash
    audio_data = data[AUDIO_HEADER_SIZE:]
    return session_hash.hex(), direction, audio_data


class TranscribeServer:
    """
    Servidor WebSocket para transcricao em tempo real.

    Recebe audio via ASP Protocol, transcreve com Faster-Whisper
    e indexa no Elasticsearch.
    """

    def __init__(
        self,
        stt_provider: STTProvider,
        es_client: ElasticsearchClient,
        bulk_indexer: BulkIndexer,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ):
        self.stt = stt_provider
        self.es_client = es_client
        self.bulk_indexer = bulk_indexer
        self.embedding_provider = embedding_provider
        self.doc_builder = DocumentBuilder()

        self.session_manager = SessionManager()
        self.connections: Set[WebSocketServerProtocol] = set()

        # Mapeamento session_hash_hex -> session_id
        self._hash_to_session: Dict[str, str] = {}

        self._server: Optional[websockets.WebSocketServer] = None
        self._running = False

    async def start(self, host: str = None, port: int = None):
        """Inicia o servidor WebSocket."""
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

        logger.info(f"AI Transcribe Server iniciado em ws://{host}:{port}")

        # Task de limpeza de sessoes
        asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        """Para o servidor."""
        self._running = False

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        # Fecha conexoes
        for ws in self.connections.copy():
            await ws.close()

        logger.info("AI Transcribe Server parado")

    async def _handle_connection(self, websocket: WebSocketServerProtocol):
        """Handler para nova conexao WebSocket."""
        self.connections.add(websocket)
        track_websocket_connect()
        client_addr = websocket.remote_address
        logger.info(f"Cliente conectado: {client_addr}")

        # Envia capabilities (ASP Protocol)
        await self._send_capabilities(websocket)

        try:
            async for message in websocket:
                await self._handle_message(websocket, message)

        except websockets.ConnectionClosed as e:
            logger.info(f"Cliente desconectado: {client_addr} ({e.code})")
        except Exception as e:
            logger.error(f"Erro na conexao {client_addr}: {e}")
        finally:
            self.connections.discard(websocket)
            track_websocket_disconnect()

    async def _send_capabilities(self, websocket: WebSocketServerProtocol):
        """Envia capabilities do protocolo ASP."""
        try:
            from asp_protocol import ProtocolCapabilities, ProtocolCapabilitiesMessage

            caps = ProtocolCapabilities(
                version="1.0.0",
                supported_sample_rates=[8000, 16000],
                supported_encodings=["pcm_s16le"],
                supported_frame_durations=[10, 20, 30],
            )
            msg = ProtocolCapabilitiesMessage(capabilities=caps)
            await websocket.send(msg.to_json())
            logger.debug("Capabilities enviadas")
        except Exception as e:
            logger.error(f"Erro ao enviar capabilities: {e}")

    async def _handle_message(self, websocket: WebSocketServerProtocol, message):
        """Processa mensagem recebida."""
        try:
            if isinstance(message, bytes):
                # Frame de audio (binary)
                if _is_audio_frame(message):
                    await self._handle_audio_frame(websocket, message)
                else:
                    logger.warning(f"Frame binario invalido: {len(message)} bytes")
            else:
                # Mensagem de controle (JSON)
                await self._handle_control_message(websocket, message)

        except Exception as e:
            logger.error(f"Erro ao processar mensagem: {e}")
            import traceback
            traceback.print_exc()

    async def _handle_control_message(self, websocket: WebSocketServerProtocol, data: str):
        """Processa mensagem de controle JSON (ASP Protocol)."""
        try:
            from asp_protocol import (
                parse_message,
                MessageType,
                SessionStartMessage,
                SessionStartedMessage,
                SessionEndMessage,
                SessionEndedMessage,
                AudioSpeechEndMessage,
                negotiate_config,
                ProtocolCapabilities,
                SessionStatus,
            )

            msg = parse_message(data)
            if msg is None:
                logger.warning(f"Mensagem invalida: {data[:100]}")
                return

            msg_type = msg.message_type

            if msg_type == MessageType.SESSION_START:
                await self._handle_session_start(websocket, msg)

            elif msg_type == MessageType.SESSION_END:
                await self._handle_session_end(websocket, msg)

            elif msg_type == MessageType.AUDIO_SPEECH_END:
                await self._handle_audio_end(websocket, msg)

            else:
                logger.debug(f"Mensagem ignorada: {msg_type}")

        except Exception as e:
            logger.error(f"Erro ao processar controle: {e}")
            import traceback
            traceback.print_exc()

    async def _handle_session_start(self, websocket: WebSocketServerProtocol, msg):
        """Handler para session.start."""
        from asp_protocol import (
            SessionStartedMessage,
            negotiate_config,
            ProtocolCapabilities,
            SessionStatus,
        )

        logger.info(f"[{msg.session_id[:8]}] session.start recebido (call: {msg.call_id})")

        # Negocia configuracao
        caps = ProtocolCapabilities(
            version="1.0.0",
            supported_sample_rates=[8000, 16000],
            supported_encodings=["pcm_s16le"],
        )

        result = negotiate_config(caps, msg.audio, msg.vad)

        # Responde com session.started
        response = SessionStartedMessage(
            session_id=msg.session_id,
            status=result.status,
            negotiated=result.negotiated,
            errors=result.errors,
        )
        await websocket.send(response.to_json())

        if result.status != SessionStatus.ACCEPTED:
            logger.warning(f"[{msg.session_id[:8]}] Sessao rejeitada: {result.errors}")
            return

        # Extrai config negociado via ASP para passar à sessao
        negotiated_sample_rate = 0
        negotiated_sample_width = 0
        if result.negotiated and result.negotiated.audio:
            negotiated_sample_rate = getattr(result.negotiated.audio, 'sample_rate', 0) or 0
            # ASP negocia encoding (pcm_s16le = 2 bytes), converte para sample_width
            encoding = getattr(result.negotiated.audio, 'encoding', 'pcm_s16le')
            negotiated_sample_width = 2 if encoding == 'pcm_s16le' else 2

        # Cria sessao com config ASP negociado
        session = await self.session_manager.create_session(
            session_id=msg.session_id,
            call_id=msg.call_id,
            caller_id=getattr(msg, 'caller_id', None),
            sample_rate=negotiated_sample_rate,
            sample_width=negotiated_sample_width,
        )

        logger.info(
            f"[{msg.session_id[:8]}] ASP config: "
            f"sample_rate={session.sample_rate}, sample_width={session.sample_width}"
        )

        # Mapeia hash -> session_id (usa mesmo hash do protocolo compartilhado)
        session_hash_hex = session_id_to_hash(msg.session_id).hex()
        self._hash_to_session[session_hash_hex] = msg.session_id

        # Associa websocket a sessao
        websocket.session_id = msg.session_id

        logger.info(f"[{msg.session_id[:8]}] Sessao iniciada")

    async def _handle_session_end(self, websocket: WebSocketServerProtocol, msg):
        """Handler para session.end."""
        from asp_protocol import SessionEndedMessage

        logger.info(f"[{msg.session_id[:8]}] session.end recebido (reason: {msg.reason})")

        session = await self.session_manager.get_session(msg.session_id)
        duration = 0.0
        if session:
            duration = session.duration_seconds

        # Responde com session.ended
        response = SessionEndedMessage(
            session_id=msg.session_id,
            duration_seconds=duration,
        )
        await websocket.send(response.to_json())

        # Encerra sessao
        await self.session_manager.end_session(msg.session_id, reason=msg.reason)

        # Remove mapeamento de hash
        session_hash_hex = session_id_to_hash(msg.session_id).hex()
        self._hash_to_session.pop(session_hash_hex, None)

    async def _handle_audio_frame(self, websocket: WebSocketServerProtocol, data: bytes):
        """Processa frame de audio recebido."""
        session_hash, direction, audio_data = _parse_audio_frame(data)
        if audio_data is None:
            return

        # Registra metricas
        track_audio_received(len(audio_data))

        # Busca sessao por hash
        session_id = self._hash_to_session.get(session_hash)
        if not session_id:
            # Tenta por websocket
            session_id = getattr(websocket, 'session_id', None)

        if not session_id:
            return

        session = await self.session_manager.get_session(session_id)
        if not session:
            return

        # Adiciona ao buffer correto baseado na direction
        is_outbound = (direction == DIRECTION_OUTBOUND)
        session.add_audio(audio_data, is_outbound=is_outbound)

    async def _handle_audio_end(self, websocket: WebSocketServerProtocol, msg):
        """Processa fim do audio (audio.speech.end)."""
        logger.debug(f"[{msg.session_id[:8]}] audio.speech.end recebido")

        session = await self.session_manager.get_session(msg.session_id)
        if not session:
            logger.warning(f"Sessao nao encontrada: {msg.session_id[:8]}")
            return

        # Processa audio inbound (usuario/caller)
        audio_inbound = session.flush_audio(is_outbound=False)
        if audio_inbound and len(audio_inbound) >= 1000:  # >= 60ms
            await self._transcribe_and_index(session, audio_inbound, speaker="caller")

        # Processa audio outbound (agente)
        audio_outbound = session.flush_audio(is_outbound=True)
        if audio_outbound and len(audio_outbound) >= 1000:  # >= 60ms
            await self._transcribe_and_index(session, audio_outbound, speaker="agent")

    async def _transcribe_and_index(
        self,
        session: TranscribeSession,
        audio_data: bytes,
        speaker: str = "caller",
    ):
        """
        Transcreve audio e indexa no Elasticsearch.

        Args:
            session: Sessao de transcricao
            audio_data: Dados de audio PCM
            speaker: Quem falou ("caller" ou "agent")
        """
        start_time = time.perf_counter()

        try:
            # Transcreve (passa sample_rate da sessao ASP para WAV header correto)
            result = await self.stt.transcribe(audio_data, input_sample_rate=session.sample_rate)

            if result.is_empty:
                track_transcription(
                    latency_seconds=result.latency_ms / 1000,
                    audio_duration_seconds=result.audio_duration_ms / 1000,
                    word_count=0,
                    status="empty"
                )
                return

            # Conta palavras
            word_count = len(result.text.split())

            # Registra metricas de transcricao
            track_transcription(
                latency_seconds=result.latency_ms / 1000,
                audio_duration_seconds=result.audio_duration_ms / 1000,
                word_count=word_count,
                status="success"
            )

            # Gera embedding se disponivel
            text_embedding = None
            embedding_model = None
            embedding_latency_ms = None

            if self.embedding_provider and self.embedding_provider.is_connected:
                try:
                    embedding_result = await self.embedding_provider.embed(result.text)
                    text_embedding = embedding_result.embedding
                    embedding_model = embedding_result.model_name
                    embedding_latency_ms = embedding_result.latency_ms

                    # Registra metricas de embedding
                    track_embedding(
                        latency_seconds=embedding_result.latency_ms / 1000,
                        status="success"
                    )

                    logger.debug(
                        f"[{session.session_id[:8]}] Embedding gerado: "
                        f"{len(text_embedding)} dims, {embedding_latency_ms:.0f}ms"
                    )

                except Exception as e:
                    logger.warning(f"[{session.session_id[:8]}] Erro ao gerar embedding: {e}")
                    track_embedding(latency_seconds=0, status="error")

            # Cria documento com embedding
            doc = self.doc_builder.build(
                session_id=session.session_id,
                call_id=session.call_id,
                text=result.text,
                audio_duration_ms=int(result.audio_duration_ms),
                transcription_latency_ms=int(result.latency_ms),
                language=result.language,
                language_probability=result.language_probability,
                speaker=speaker,
                caller_id=session.caller_id,
                metadata=session.metadata,
                text_embedding=text_embedding,
                embedding_model=embedding_model,
                embedding_latency_ms=embedding_latency_ms,
            )

            # Adiciona ao bulk indexer
            await self.bulk_indexer.add(doc)

            # Atualiza contador da sessao
            session.utterances_transcribed += 1

            logger.info(
                f"[{session.session_id[:8]}] [{speaker}] Transcrito: '{result.text}' "
                f"({result.latency_ms:.0f}ms)"
            )

        except Exception as e:
            logger.error(f"[{session.session_id[:8]}] Erro na transcricao: {e}")
            track_transcription(
                latency_seconds=(time.perf_counter() - start_time),
                audio_duration_seconds=0,
                word_count=0,
                status="error"
            )

    async def _cleanup_loop(self):
        """Loop de limpeza de sessoes inativas."""
        cleanup_interval = SESSION_CONFIG.get("cleanup_interval", 60)
        max_idle_seconds = SESSION_CONFIG.get("max_idle_seconds", 300)

        while self._running:
            await asyncio.sleep(cleanup_interval)
            try:
                removed = await self.session_manager.cleanup_stale_sessions(
                    max_idle_seconds=max_idle_seconds
                )
                if removed > 0:
                    logger.info(f"Removidas {removed} sessoes inativas")
            except Exception as e:
                logger.error(f"Erro na limpeza: {e}")


async def run_server(
    stt_provider: STTProvider,
    es_client: ElasticsearchClient,
    bulk_indexer: BulkIndexer,
    embedding_provider: Optional[EmbeddingProvider] = None,
):
    """Funcao helper para rodar o servidor."""
    server = TranscribeServer(
        stt_provider,
        es_client,
        bulk_indexer,
        embedding_provider,
    )
    await server.start()

    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
