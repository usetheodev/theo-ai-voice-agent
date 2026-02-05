"""
Adapter para AI Transcribe via WebSocket

Envia audio para o servico de transcricao em tempo real.
Implementa protocolo ASP simplificado (apenas envio de audio).
"""

import logging
import asyncio
from typing import Optional, Dict

import websockets
from websockets.client import WebSocketClientProtocol

from config import TRANSCRIBE_CONFIG, AUDIO_CONFIG
from ws.protocol import (
    AudioDirection,
    create_audio_frame,
    session_id_to_hash,
)

logger = logging.getLogger("media-server.adapter.transcribe")


class TranscribeAdapter:
    """
    Adapter para envio de audio ao AI Transcribe.

    Conecta via WebSocket e envia audio usando protocolo ASP.
    Nao recebe respostas (transcricao vai direto para Elasticsearch).

    Example:
        adapter = TranscribeAdapter()
        await adapter.connect()

        await adapter.start_session(session_id, call_id)
        await adapter.send_audio(session_id, audio_data)
        await adapter.send_audio_end(session_id)
        await adapter.end_session(session_id)

        await adapter.disconnect()
    """

    def __init__(self):
        self.url = TRANSCRIBE_CONFIG["url"]
        self.ws: Optional[WebSocketClientProtocol] = None
        self._connected = asyncio.Event()
        self._running = False
        self._reconnect_task: Optional[asyncio.Task] = None

        # Sessoes ativas
        self._sessions: Dict[str, str] = {}  # session_id -> call_id
        self._session_hash_lookup: Dict[str, str] = {}

    @property
    def is_connected(self) -> bool:
        """Verifica se esta conectado."""
        return self._connected.is_set() and self.ws is not None

    @property
    def is_enabled(self) -> bool:
        """Verifica se transcricao esta habilitada."""
        return TRANSCRIBE_CONFIG.get("enabled", False)

    async def connect(self) -> bool:
        """
        Conecta ao AI Transcribe.

        Returns:
            True se conectou com sucesso
        """
        if not self.is_enabled:
            logger.info("Transcricao desabilitada via config")
            return False

        self._running = True

        try:
            logger.info(f"Conectando ao AI Transcribe: {self.url}")

            self.ws = await websockets.connect(
                self.url,
                ping_interval=TRANSCRIBE_CONFIG.get("ping_interval", 30),
                ping_timeout=TRANSCRIBE_CONFIG.get("ping_timeout", 10),
            )

            # Aguarda capabilities (ASP handshake)
            await self._receive_capabilities()

            self._connected.set()

            # Inicia loop de recebimento (para manter conexao e processar pongs)
            asyncio.create_task(self._receive_loop())

            logger.info("Conectado ao AI Transcribe")
            return True

        except Exception as e:
            logger.error(f"Erro ao conectar ao AI Transcribe: {e}")
            self._connected.clear()
            return False

    async def _receive_capabilities(self):
        """Recebe e processa protocol.capabilities."""
        try:
            msg = await asyncio.wait_for(self.ws.recv(), timeout=5.0)
            # Apenas loga, nao precisa processar
            logger.debug(f"Capabilities recebidas: {msg[:100]}...")
        except asyncio.TimeoutError:
            logger.warning("Timeout aguardando capabilities do AI Transcribe")
        except Exception as e:
            logger.warning(f"Erro ao receber capabilities: {e}")

    async def disconnect(self) -> None:
        """Desconecta do AI Transcribe."""
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

        logger.info("Desconectado do AI Transcribe")

    async def wait_connected(self, timeout: float = 30) -> bool:
        """Aguarda conexao estar pronta."""
        if not self.is_enabled:
            return False
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def start_session(self, session_id: str, call_id: str) -> bool:
        """
        Inicia sessao de transcricao.

        Args:
            session_id: ID da sessao
            call_id: ID da chamada

        Returns:
            True se sessao iniciada
        """
        if not self.is_connected:
            return False

        try:
            import json
            from asp_protocol import (
                AudioConfig,
                VADConfig,
                SessionStartMessage,
            )

            # Cria configs
            audio_config = AudioConfig(
                sample_rate=AUDIO_CONFIG["sample_rate"],
                channels=AUDIO_CONFIG["channels"],
                frame_duration_ms=AUDIO_CONFIG["frame_duration_ms"],
            )

            vad_config = VADConfig(
                silence_threshold_ms=AUDIO_CONFIG.get("silence_threshold_ms", 500),
                min_speech_ms=AUDIO_CONFIG.get("min_speech_ms", 250),
            )

            # Envia session.start
            msg = SessionStartMessage(
                session_id=session_id,
                call_id=call_id,
                audio=audio_config,
                vad=vad_config,
            )

            await self.ws.send(msg.to_json())

            # Registra sessao
            self._sessions[session_id] = call_id
            hash_hex = session_id_to_hash(session_id).hex()
            self._session_hash_lookup[hash_hex] = session_id

            logger.info(f"[{session_id[:8]}] Sessao de transcricao iniciada")
            return True

        except Exception as e:
            logger.error(f"[{session_id[:8]}] Erro ao iniciar sessao: {e}")
            return False

    async def end_session(self, session_id: str, reason: str = "hangup") -> None:
        """
        Encerra sessao de transcricao.

        Args:
            session_id: ID da sessao
            reason: Motivo do encerramento
        """
        if not self.is_connected:
            return

        if session_id not in self._sessions:
            return

        try:
            from asp_protocol import SessionEndMessage

            msg = SessionEndMessage(
                session_id=session_id,
                reason=reason,
            )

            await self.ws.send(msg.to_json())

            # Remove sessao
            self._sessions.pop(session_id, None)
            hash_hex = session_id_to_hash(session_id).hex()
            self._session_hash_lookup.pop(hash_hex, None)

            logger.info(f"[{session_id[:8]}] Sessao de transcricao encerrada")

        except Exception as e:
            logger.error(f"[{session_id[:8]}] Erro ao encerrar sessao: {e}")

    async def send_audio(
        self,
        session_id: str,
        audio_data: bytes,
        direction: AudioDirection = AudioDirection.INBOUND,
    ) -> None:
        """
        Envia audio para transcricao.

        Args:
            session_id: ID da sessao
            audio_data: Dados de audio PCM
            direction: Direcao do audio (INBOUND=usuario, OUTBOUND=agente)
        """
        if not self.is_connected:
            return

        if session_id not in self._sessions:
            return

        try:
            frame = create_audio_frame(
                session_id=session_id,
                audio_data=audio_data,
                direction=direction,
            )
            await self.ws.send(frame)

        except Exception as e:
            logger.debug(f"[{session_id[:8]}] Erro ao enviar audio: {e}")

    async def send_outbound_audio(self, session_id: str, audio_data: bytes) -> None:
        """
        Envia audio do agente (TTS) para transcricao.

        Args:
            session_id: ID da sessao
            audio_data: Dados de audio PCM do agente
        """
        await self.send_audio(session_id, audio_data, AudioDirection.OUTBOUND)

    async def send_audio_end(self, session_id: str) -> None:
        """
        Notifica fim do audio (para trigger de transcricao).

        Args:
            session_id: ID da sessao
        """
        if not self.is_connected:
            return

        if session_id not in self._sessions:
            return

        try:
            from asp_protocol import AudioSpeechEndMessage

            msg = AudioSpeechEndMessage(session_id=session_id)
            await self.ws.send(msg.to_json())

            logger.debug(f"[{session_id[:8]}] audio.speech.end enviado para transcricao")

        except Exception as e:
            logger.debug(f"[{session_id[:8]}] Erro ao enviar audio.speech.end: {e}")

    async def _receive_loop(self):
        """Loop de recebimento (para manter conexao)."""
        try:
            async for message in self.ws:
                # Ignora mensagens - transcricao vai direto para ES
                pass

        except websockets.ConnectionClosed as e:
            logger.warning(f"Conexao com AI Transcribe fechada: {e.code}")
        except Exception as e:
            logger.error(f"Erro no receive loop: {e}")
        finally:
            self._connected.clear()
            if self._running:
                asyncio.create_task(self._reconnect())

    async def _reconnect(self):
        """Tenta reconectar ao AI Transcribe."""
        if not self._running:
            return

        interval = TRANSCRIBE_CONFIG.get("reconnect_interval", 5)
        max_attempts = TRANSCRIBE_CONFIG.get("max_reconnect_attempts", 10)

        for attempt in range(max_attempts):
            if not self._running:
                return

            logger.info(f"Tentando reconectar ao AI Transcribe ({attempt + 1}/{max_attempts})...")
            await asyncio.sleep(interval)

            if await self.connect():
                # Re-inicia sessoes ativas
                for session_id, call_id in list(self._sessions.items()):
                    await self.start_session(session_id, call_id)
                return

        logger.error("Falha ao reconectar ao AI Transcribe")
