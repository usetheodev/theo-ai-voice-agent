"""
Media Fork Manager - Orquestrador do Media Forking.

Gerencia o isolamento entre o path crítico de mídia e o path de IA.
Conecta RingBuffer (produtor) com ForkConsumer (consumidor).

Princípio fundamental:
- O RTP callback NUNCA bloqueia
- O áudio é COPIADO (fork) para o buffer
- O consumer consome best-effort
- Se IA falhar, chamada continua

Uso típico:
    # No MediaServer
    fork_manager = MediaForkManager(ai_agent_adapter)
    await fork_manager.initialize()

    # No início da chamada
    await fork_manager.start_session(session_id)

    # No RTP callback (NUNCA bloqueia)
    fork_manager.fork_audio(session_id, audio_data)

    # No fim da chamada
    await fork_manager.stop_session(session_id)
"""

import asyncio
import logging
from typing import Optional, Dict, TYPE_CHECKING
from dataclasses import dataclass, field

from config import MEDIA_FORK_CONFIG, AUDIO_CONFIG
from core.ring_buffer import RingBuffer
from core.fork_consumer import ForkConsumer
from metrics import (
    track_fork_frame_received,
    track_fork_frame_dropped,
    track_fork_overflow,
    track_fork_fallback_active,
)

if TYPE_CHECKING:
    from adapters.ai_agent_adapter import AIAgentAdapter
    from adapters.transcribe_adapter import TranscribeAdapter

logger = logging.getLogger("media-server.fork_manager")


@dataclass
class SessionFork:
    """Dados do fork para uma sessão."""
    session_id: str
    buffer: RingBuffer
    is_active: bool = True
    fallback_active: bool = False
    frames_forked: int = 0
    frames_dropped: int = 0


class MediaForkManager:
    """
    Gerenciador de Media Forking.

    Responsabilidades:
    1. Criar e gerenciar RingBuffers por sessão
    2. Gerenciar ForkConsumer compartilhado
    3. Fornecer método fork_audio() que NUNCA bloqueia
    4. Gerenciar fallback quando AI Agent indisponível

    Args:
        ai_agent_adapter: Adapter para comunicação com AI Agent

    Example:
        manager = MediaForkManager(adapter)
        await manager.initialize()

        # Início da chamada
        await manager.start_session("session-123")

        # No RTP callback (thread separada, não-async)
        manager.fork_audio("session-123", audio_bytes)

        # Fim da chamada
        await manager.stop_session("session-123")
    """

    def __init__(
        self,
        ai_agent_adapter: "AIAgentAdapter",
        transcribe_adapter: Optional["TranscribeAdapter"] = None,
    ):
        self.ai_agent_adapter = ai_agent_adapter
        self.transcribe_adapter = transcribe_adapter

        # Configuração
        self.enabled = MEDIA_FORK_CONFIG.get("enabled", True)
        self.buffer_ms = MEDIA_FORK_CONFIG.get("buffer_ms", 500)
        self.fallback_enabled = MEDIA_FORK_CONFIG.get("fallback_enabled", True)

        # Áudio config para buffers
        self.sample_rate = AUDIO_CONFIG.get("sample_rate", 8000)
        self.sample_width = AUDIO_CONFIG.get("sample_width", 2)
        self.channels = AUDIO_CONFIG.get("channels", 1)

        # Sessions
        self._sessions: Dict[str, SessionFork] = {}

        # Consumer compartilhado (inicializado em initialize())
        self._consumer: Optional[ForkConsumer] = None

        # Estado
        self._initialized = False

        transcribe_status = "enabled" if transcribe_adapter else "disabled"
        logger.info(
            f"MediaForkManager criado: enabled={self.enabled}, "
            f"buffer_ms={self.buffer_ms}, fallback={self.fallback_enabled}, "
            f"transcribe={transcribe_status}"
        )

    async def initialize(self) -> bool:
        """
        Inicializa o manager.

        Deve ser chamado antes de usar o manager.

        Returns:
            True se inicializado com sucesso
        """
        if not self.enabled:
            logger.info("MediaForkManager desabilitado via config")
            return True

        if self._initialized:
            logger.warning("MediaForkManager já inicializado")
            return True

        try:
            # Cria buffer compartilhado para uso do consumer
            # (cada sessão terá seu próprio buffer)
            shared_buffer = RingBuffer(
                capacity_ms=self.buffer_ms,
                sample_rate=self.sample_rate,
                sample_width=self.sample_width,
                channels=self.channels,
            )

            # Cria consumer com suporte a múltiplos destinos
            self._consumer = ForkConsumer(
                ring_buffer=shared_buffer,
                ai_agent_adapter=self.ai_agent_adapter,
                transcribe_adapter=self.transcribe_adapter,
            )

            self._initialized = True
            logger.info("MediaForkManager inicializado")
            return True

        except Exception as e:
            logger.error(f"Erro ao inicializar MediaForkManager: {e}")
            return False

    async def shutdown(self):
        """Encerra o manager e todos os consumers."""
        if self._consumer:
            await self._consumer.stop_all()

        self._sessions.clear()
        self._initialized = False
        logger.info("MediaForkManager encerrado")

    async def start_session(self, session_id: str, call_id: str = None) -> bool:
        """
        Inicia fork para uma sessão.

        Args:
            session_id: ID da sessão
            call_id: ID da chamada (para transcribe)

        Returns:
            True se iniciado com sucesso
        """
        if not self.enabled:
            return True  # Silenciosamente ignora se desabilitado

        if not self._initialized:
            logger.error("MediaForkManager não inicializado")
            return False

        if session_id in self._sessions:
            logger.warning(f"[{session_id[:8]}] Sessão já existe no fork manager")
            return True

        try:
            # Cria buffer dedicado para a sessão
            buffer = RingBuffer(
                capacity_ms=self.buffer_ms,
                sample_rate=self.sample_rate,
                sample_width=self.sample_width,
                channels=self.channels,
            )

            # Cria sessão
            session = SessionFork(
                session_id=session_id,
                buffer=buffer,
            )
            self._sessions[session_id] = session

            # Atualiza consumer para usar este buffer
            # (na implementação atual, cada sessão tem seu consumer)
            self._consumer.ring_buffer = buffer

            # Inicia consumer para esta sessão
            await self._consumer.start(session_id)

            # Inicia sessão no transcribe adapter (se habilitado)
            if self.transcribe_adapter and self.transcribe_adapter.is_connected:
                try:
                    await self.transcribe_adapter.start_session(
                        session_id=session_id,
                        call_id=call_id or session_id[:8],
                    )
                    logger.debug(f"[{session_id[:8]}] Sessão de transcricao iniciada")
                except Exception as e:
                    logger.warning(f"[{session_id[:8]}] Falha ao iniciar transcricao: {e}")

            logger.info(f"[{session_id[:8]}] Fork session iniciada")
            return True

        except Exception as e:
            logger.error(f"[{session_id[:8]}] Erro ao iniciar fork session: {e}")
            return False

    async def stop_session(self, session_id: str) -> bool:
        """
        Para fork de uma sessão.

        Args:
            session_id: ID da sessão

        Returns:
            True se parado com sucesso
        """
        if not self.enabled:
            return True

        if session_id not in self._sessions:
            logger.warning(f"[{session_id[:8]}] Sessão não encontrada no fork manager")
            return False

        try:
            session = self._sessions[session_id]

            # Para consumer
            if self._consumer:
                await self._consumer.stop(session_id)

            # Encerra sessão no transcribe adapter (se habilitado)
            if self.transcribe_adapter and self.transcribe_adapter.is_connected:
                try:
                    await self.transcribe_adapter.end_session(session_id)
                    logger.debug(f"[{session_id[:8]}] Sessão de transcricao encerrada")
                except Exception as e:
                    logger.warning(f"[{session_id[:8]}] Falha ao encerrar transcricao: {e}")

            # Log métricas finais
            buffer_metrics = session.buffer.metrics
            logger.info(
                f"[{session_id[:8]}] Fork session encerrada: "
                f"forked={session.frames_forked}, "
                f"dropped={buffer_metrics.frames_dropped}, "
                f"drop_rate={buffer_metrics.drop_rate:.2%}"
            )

            # Remove sessão
            del self._sessions[session_id]
            return True

        except Exception as e:
            logger.error(f"[{session_id[:8]}] Erro ao parar fork session: {e}")
            return False

    def fork_audio(self, session_id: str, audio_data: bytes) -> bool:
        """
        Faz fork do áudio para o buffer. NUNCA BLOQUEIA.

        Este método é chamado do RTP callback e deve ser extremamente rápido.
        Não faz nenhuma operação de I/O, apenas copia para o buffer.

        Args:
            session_id: ID da sessão
            audio_data: Dados de áudio (PCM)

        Returns:
            True se colocado no buffer (mesmo com overflow)
            False se sessão não existe ou manager desabilitado
        """
        if not self.enabled:
            return False

        session = self._sessions.get(session_id)
        if not session:
            return False

        if not session.is_active:
            return False

        # Push para o buffer - NUNCA bloqueia
        # Se buffer cheio, drop oldest acontece automaticamente
        was_full = session.buffer.is_full
        session.buffer.push(session_id, audio_data)

        # Atualiza contadores
        session.frames_forked += 1
        track_fork_frame_received()

        if was_full:
            session.frames_dropped += 1
            track_fork_frame_dropped()
            track_fork_overflow()

        return True

    async def send_audio_end(self, session_id: str) -> None:
        """
        Envia sinal de fim de audio para o transcribe adapter.

        Chamado quando VAD detecta fim de fala.
        O audio.end para o AI Agent eh enviado pelo streaming_port diretamente.
        Este metodo propaga para o transcribe_adapter.

        Args:
            session_id: ID da sessao
        """
        if not self.transcribe_adapter:
            return

        if session_id not in self._sessions:
            return

        if self.transcribe_adapter.is_connected:
            try:
                await self.transcribe_adapter.send_audio_end(session_id)
                logger.debug(f"[{session_id[:8]}] audio.speech.end enviado para transcribe")
            except Exception as e:
                logger.debug(f"[{session_id[:8]}] Falha ao enviar audio.speech.end: {e}")

    async def send_outbound_audio(self, session_id: str, audio_data: bytes) -> bool:
        """
        Envia audio do agente (TTS) para transcricao.

        Chamado do callback on_response_audio em call.py.
        Este metodo eh async porque envia via WebSocket.

        Args:
            session_id: ID da sessao
            audio_data: Audio do agente (8kHz, 16-bit PCM)

        Returns:
            True se enviado com sucesso
        """
        if not self.enabled:
            return False

        if not self.transcribe_adapter:
            return False

        if session_id not in self._sessions:
            return False

        if self.transcribe_adapter.is_connected:
            try:
                await self.transcribe_adapter.send_outbound_audio(session_id, audio_data)
                return True
            except Exception as e:
                logger.debug(f"[{session_id[:8]}] Falha ao enviar outbound audio: {e}")

        return False

    async def send_outbound_audio_end(self, session_id: str) -> None:
        """
        Envia sinal de fim de audio do agente para transcricao.

        Chamado quando o agente termina de falar (fim do TTS).

        Args:
            session_id: ID da sessao
        """
        if not self.transcribe_adapter:
            return

        if session_id not in self._sessions:
            return

        if self.transcribe_adapter.is_connected:
            try:
                await self.transcribe_adapter.send_audio_end(session_id)
                logger.debug(f"[{session_id[:8]}] audio.speech.end (agente) enviado para transcribe")
            except Exception as e:
                logger.debug(f"[{session_id[:8]}] Falha ao enviar audio.speech.end (agente): {e}")

    def pause_session(self, session_id: str):
        """
        Pausa fork de uma sessão (sem destruir buffer).

        Útil para pausar durante playback de resposta.
        """
        session = self._sessions.get(session_id)
        if session:
            session.is_active = False
            logger.debug(f"[{session_id[:8]}] Fork pausado")

    def resume_session(self, session_id: str):
        """
        Resume fork de uma sessão.
        """
        session = self._sessions.get(session_id)
        if session:
            session.is_active = True
            # Limpa buffer antigo para não processar áudio stale
            session.buffer.clear()
            logger.debug(f"[{session_id[:8]}] Fork resumido")

    def activate_fallback(self, session_id: str):
        """
        Ativa modo fallback para uma sessão.

        Chamado quando AI Agent está indisponível.
        """
        session = self._sessions.get(session_id)
        if session and not session.fallback_active:
            session.fallback_active = True
            track_fork_fallback_active(True)
            logger.warning(f"[{session_id[:8]}] Fallback mode ATIVADO")

    def deactivate_fallback(self, session_id: str):
        """
        Desativa modo fallback para uma sessão.

        Chamado quando AI Agent volta a ficar disponível.
        """
        session = self._sessions.get(session_id)
        if session and session.fallback_active:
            session.fallback_active = False
            track_fork_fallback_active(False)
            logger.info(f"[{session_id[:8]}] Fallback mode DESATIVADO")

    def get_session_metrics(self, session_id: str) -> Optional[dict]:
        """
        Retorna métricas de uma sessão.

        Returns:
            Dict com métricas ou None se sessão não existe
        """
        session = self._sessions.get(session_id)
        if not session:
            return None

        buffer_metrics = session.buffer.metrics.to_dict()
        consumer_metrics = self._consumer.get_session_metrics(session_id) if self._consumer else {}

        return {
            "session_id": session_id,
            "is_active": session.is_active,
            "fallback_active": session.fallback_active,
            "frames_forked": session.frames_forked,
            "buffer": buffer_metrics,
            "consumer": consumer_metrics,
        }

    def get_all_metrics(self) -> dict:
        """Retorna métricas de todas as sessões."""
        return {
            "enabled": self.enabled,
            "initialized": self._initialized,
            "active_sessions": len(self._sessions),
            "sessions": {
                sid: self.get_session_metrics(sid)
                for sid in self._sessions
            }
        }

    @property
    def is_ready(self) -> bool:
        """Verifica se manager está pronto para uso."""
        return self._initialized or not self.enabled

    @property
    def active_sessions_count(self) -> int:
        """Número de sessões ativas."""
        return len(self._sessions)

    @property
    def ai_agent_available(self) -> bool:
        """Status de disponibilidade do AI Agent."""
        if self._consumer:
            return self._consumer.ai_agent_available
        return self.ai_agent_adapter.is_connected
