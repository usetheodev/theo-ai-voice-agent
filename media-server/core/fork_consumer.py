"""
Fork Consumer - Worker assíncrono para envio de áudio ao AI Agent.

Consome frames do RingBuffer e envia para o AI Agent via WebSocket.
Características:
- Nunca bloqueia o producer (RTP callback)
- Best-effort: se não conseguir enviar, descarta e continua
- Backoff exponencial para reconexão
- Métricas de lag e erros

Uso típico:
    consumer = ForkConsumer(ring_buffer, ai_agent_adapter, config)
    await consumer.start(session_id)
    # ... durante a chamada ...
    await consumer.stop(session_id)
"""

import asyncio
import logging
import time
from typing import Optional, Dict, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum

from config import MEDIA_FORK_CONFIG
from metrics import (
    track_fork_consumer_lag,
    track_fork_consumer_error,
    track_fork_ai_agent_available,
    track_fork_buffer_size,
)

if TYPE_CHECKING:
    from core.ring_buffer import RingBuffer
    from adapters.ai_agent_adapter import AIAgentAdapter
    from adapters.transcribe_adapter import TranscribeAdapter

logger = logging.getLogger("media-server.fork_consumer")


class ConsumerState(Enum):
    """Estados do consumer."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class ConsumerMetrics:
    """Métricas do ForkConsumer."""
    frames_sent: int = 0
    frames_failed: int = 0
    bytes_sent: int = 0
    total_lag_ms: float = 0.0
    max_lag_ms: float = 0.0
    reconnect_attempts: int = 0
    last_send_timestamp: float = 0.0
    last_error_timestamp: float = 0.0
    last_error_message: str = ""

    @property
    def avg_lag_ms(self) -> float:
        """Lag médio em ms."""
        if self.frames_sent == 0:
            return 0.0
        return self.total_lag_ms / self.frames_sent

    @property
    def success_rate(self) -> float:
        """Taxa de sucesso (0.0 a 1.0)."""
        total = self.frames_sent + self.frames_failed
        if total == 0:
            return 1.0
        return self.frames_sent / total

    def record_send(self, lag_ms: float, bytes_count: int):
        """Registra envio bem-sucedido."""
        self.frames_sent += 1
        self.bytes_sent += bytes_count
        self.total_lag_ms += lag_ms
        self.max_lag_ms = max(self.max_lag_ms, lag_ms)
        self.last_send_timestamp = time.perf_counter()

    def record_failure(self, error_message: str):
        """Registra falha de envio."""
        self.frames_failed += 1
        self.last_error_timestamp = time.perf_counter()
        self.last_error_message = error_message

    def to_dict(self) -> dict:
        """Exporta métricas como dicionário."""
        return {
            "frames_sent": self.frames_sent,
            "frames_failed": self.frames_failed,
            "bytes_sent": self.bytes_sent,
            "avg_lag_ms": self.avg_lag_ms,
            "max_lag_ms": self.max_lag_ms,
            "success_rate": self.success_rate,
            "reconnect_attempts": self.reconnect_attempts,
        }


@dataclass
class SessionConsumer:
    """Consumer para uma sessão específica."""
    session_id: str
    task: Optional[asyncio.Task] = None
    state: ConsumerState = ConsumerState.STOPPED
    metrics: ConsumerMetrics = field(default_factory=ConsumerMetrics)
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)


class ForkConsumer:
    """
    Consumer assíncrono que lê do RingBuffer e envia para múltiplos destinos.

    Implementa:
    - Polling do buffer em intervalo configurável
    - Best-effort sending (não bloqueia se falhar)
    - Backoff exponencial para reconexão
    - Métricas de lag para observabilidade
    - Envio para AI Agent (conversação) e AI Transcribe (transcrição)

    Args:
        ring_buffer: Buffer de onde ler os frames
        ai_agent_adapter: Adapter para enviar ao AI Agent
        transcribe_adapter: Adapter para enviar ao AI Transcribe (opcional)
        poll_interval_ms: Intervalo de polling em ms (default: 10)
        lag_warning_threshold_ms: Threshold para warning de lag (default: 100)
    """

    def __init__(
        self,
        ring_buffer: "RingBuffer",
        ai_agent_adapter: "AIAgentAdapter",
        transcribe_adapter: Optional["TranscribeAdapter"] = None,
        poll_interval_ms: int = None,
        lag_warning_threshold_ms: int = None,
    ):
        self.ring_buffer = ring_buffer
        self.ai_agent_adapter = ai_agent_adapter
        self.transcribe_adapter = transcribe_adapter

        # Configuração
        self.poll_interval_ms = poll_interval_ms or MEDIA_FORK_CONFIG.get("consumer_poll_ms", 10)
        self.lag_warning_threshold_ms = lag_warning_threshold_ms or MEDIA_FORK_CONFIG.get("lag_warning_threshold_ms", 100)

        # Backoff config
        self.reconnect_initial_s = MEDIA_FORK_CONFIG.get("reconnect_initial_s", 0.1)
        self.reconnect_max_s = MEDIA_FORK_CONFIG.get("reconnect_max_s", 5.0)
        self.reconnect_multiplier = MEDIA_FORK_CONFIG.get("reconnect_multiplier", 2.0)

        # Sessions
        self._sessions: Dict[str, SessionConsumer] = {}

        # Estado global
        self._ai_agent_available = False
        self._current_backoff = self.reconnect_initial_s

        transcribe_status = "enabled" if transcribe_adapter else "disabled"
        logger.info(
            f"ForkConsumer criado: poll_interval={self.poll_interval_ms}ms, "
            f"lag_warning={self.lag_warning_threshold_ms}ms, transcribe={transcribe_status}"
        )

    async def start(self, session_id: str) -> bool:
        """
        Inicia consumer para uma sessão.

        Args:
            session_id: ID da sessão

        Returns:
            True se iniciado com sucesso
        """
        if session_id in self._sessions:
            session = self._sessions[session_id]
            if session.state == ConsumerState.RUNNING:
                logger.warning(f"[{session_id[:8]}] Consumer já está rodando")
                return True

        # Cria ou recupera sessão
        session = SessionConsumer(session_id=session_id)
        session.state = ConsumerState.STARTING
        session.stop_event.clear()
        self._sessions[session_id] = session

        # Inicia task do consumer
        session.task = asyncio.create_task(
            self._consumer_loop(session),
            name=f"fork_consumer_{session_id[:8]}"
        )

        logger.info(f"[{session_id[:8]}] ForkConsumer iniciado")
        return True

    async def stop(self, session_id: str) -> bool:
        """
        Para consumer de uma sessão.

        Args:
            session_id: ID da sessão

        Returns:
            True se parado com sucesso
        """
        if session_id not in self._sessions:
            logger.warning(f"[{session_id[:8]}] Consumer não encontrado")
            return False

        session = self._sessions[session_id]
        session.state = ConsumerState.STOPPING
        session.stop_event.set()

        # Aguarda task finalizar
        if session.task and not session.task.done():
            try:
                await asyncio.wait_for(session.task, timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning(f"[{session_id[:8]}] Timeout aguardando consumer parar")
                session.task.cancel()
                try:
                    await session.task
                except asyncio.CancelledError:
                    pass

        session.state = ConsumerState.STOPPED
        logger.info(
            f"[{session_id[:8]}] ForkConsumer parado: "
            f"sent={session.metrics.frames_sent}, "
            f"failed={session.metrics.frames_failed}, "
            f"avg_lag={session.metrics.avg_lag_ms:.1f}ms"
        )

        # Remove sessão
        del self._sessions[session_id]
        return True

    async def stop_all(self):
        """Para todos os consumers."""
        session_ids = list(self._sessions.keys())
        for session_id in session_ids:
            await self.stop(session_id)

    async def _consumer_loop(self, session: SessionConsumer):
        """
        Loop principal do consumer.

        Faz polling do buffer e envia frames para o AI Agent.
        """
        session.state = ConsumerState.RUNNING
        poll_interval_s = self.poll_interval_ms / 1000.0

        logger.debug(f"[{session.session_id[:8]}] Consumer loop iniciado")

        while not session.stop_event.is_set():
            try:
                # Verifica disponibilidade do AI Agent
                ai_available = self._check_ai_agent_available()

                if not ai_available:
                    # Backoff exponencial
                    await self._handle_ai_unavailable(session)
                    continue

                # Reset backoff quando AI Agent está disponível
                self._current_backoff = self.reconnect_initial_s

                # Processa frames do buffer
                frames_processed = await self._process_buffer_frames(session)

                # Atualiza métricas do buffer
                self._update_buffer_metrics()

                # Se não processou nada, aguarda intervalo de polling
                if frames_processed == 0:
                    await asyncio.sleep(poll_interval_s)

            except asyncio.CancelledError:
                logger.debug(f"[{session.session_id[:8]}] Consumer cancelado")
                break
            except Exception as e:
                logger.error(f"[{session.session_id[:8]}] Erro no consumer loop: {e}")
                session.metrics.record_failure(str(e))
                track_fork_consumer_error("loop_error")
                await asyncio.sleep(poll_interval_s)

        session.state = ConsumerState.STOPPED
        logger.debug(f"[{session.session_id[:8]}] Consumer loop finalizado")

    async def _process_buffer_frames(self, session: SessionConsumer) -> int:
        """
        Processa frames disponíveis no buffer.

        Returns:
            Número de frames processados
        """
        frames_processed = 0
        max_batch = 10  # Processa até 10 frames por iteração para não travar

        while frames_processed < max_batch:
            # Pop frame do buffer (não bloqueia)
            frame = self.ring_buffer.pop()
            if frame is None:
                break

            # Filtra por sessão (se buffer é compartilhado)
            if frame.session_id != session.session_id:
                # Re-insere frame de outra sessão (edge case)
                # Na prática, cada sessão deve ter seu próprio buffer
                continue

            # Calcula lag
            lag_ms = frame.age_ms
            track_fork_consumer_lag(lag_ms)

            # Warning se lag alto
            if lag_ms > self.lag_warning_threshold_ms:
                logger.warning(
                    f"[{session.session_id[:8]}] Consumer lag alto: {lag_ms:.1f}ms "
                    f"(threshold: {self.lag_warning_threshold_ms}ms)"
                )

            # Tenta enviar
            success = await self._send_frame(session, frame.data)

            if success:
                session.metrics.record_send(lag_ms, len(frame.data))
            else:
                session.metrics.record_failure("send_failed")

            frames_processed += 1

        return frames_processed

    async def _send_frame(self, session: SessionConsumer, audio_data: bytes) -> bool:
        """
        Envia frame para múltiplos destinos (AI Agent e AI Transcribe).

        Args:
            session: Sessão do consumer
            audio_data: Dados de áudio

        Returns:
            True se enviado com sucesso para pelo menos um destino
        """
        ai_agent_success = False
        transcribe_success = False

        # Envia para AI Agent (destino principal)
        try:
            await self.ai_agent_adapter.send_audio(session.session_id, audio_data)
            ai_agent_success = True
        except Exception as e:
            logger.debug(f"[{session.session_id[:8]}] Falha ao enviar para AI Agent: {e}")
            track_fork_consumer_error("send_failed_ai_agent")

        # Envia para AI Transcribe (se habilitado)
        if self.transcribe_adapter and self.transcribe_adapter.is_connected:
            try:
                await self.transcribe_adapter.send_audio(session.session_id, audio_data)
                transcribe_success = True
            except Exception as e:
                logger.debug(f"[{session.session_id[:8]}] Falha ao enviar para Transcribe: {e}")
                # Não registra erro - transcribe é secundário

        # Considera sucesso se enviou para AI Agent
        return ai_agent_success

    def _check_ai_agent_available(self) -> bool:
        """Verifica se AI Agent está disponível."""
        available = self.ai_agent_adapter.is_connected

        # Atualiza métrica se mudou
        if available != self._ai_agent_available:
            self._ai_agent_available = available
            track_fork_ai_agent_available(available)

            if available:
                logger.info("AI Agent disponível")
            else:
                logger.warning("AI Agent indisponível")

        return available

    async def _handle_ai_unavailable(self, session: SessionConsumer):
        """
        Trata indisponibilidade do AI Agent com backoff exponencial.
        """
        session.metrics.reconnect_attempts += 1
        track_fork_consumer_error("connection_lost")

        logger.debug(
            f"[{session.session_id[:8]}] AI Agent indisponível, "
            f"backoff={self._current_backoff:.2f}s"
        )

        # Aguarda com backoff
        await asyncio.sleep(self._current_backoff)

        # Aumenta backoff para próxima vez (com cap)
        self._current_backoff = min(
            self._current_backoff * self.reconnect_multiplier,
            self.reconnect_max_s
        )

    def _update_buffer_metrics(self):
        """Atualiza métricas do buffer."""
        track_fork_buffer_size(
            size_bytes=self.ring_buffer.size_bytes,
            size_ms=self.ring_buffer.size_ms,
            fill_ratio=self.ring_buffer.fill_ratio
        )

    def get_session_metrics(self, session_id: str) -> Optional[dict]:
        """Retorna métricas de uma sessão."""
        if session_id in self._sessions:
            return self._sessions[session_id].metrics.to_dict()
        return None

    def get_all_metrics(self) -> dict:
        """Retorna métricas de todas as sessões."""
        return {
            session_id: session.metrics.to_dict()
            for session_id, session in self._sessions.items()
        }

    @property
    def active_sessions(self) -> int:
        """Número de sessões ativas."""
        return len(self._sessions)

    @property
    def ai_agent_available(self) -> bool:
        """Status de disponibilidade do AI Agent."""
        return self._ai_agent_available
