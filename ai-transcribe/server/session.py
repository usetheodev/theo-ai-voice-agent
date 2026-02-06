"""
Session Manager - Gerenciamento de sessoes de transcricao
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from config import SESSION_CONFIG, AUDIO_CONFIG
from metrics import ACTIVE_SESSIONS

logger = logging.getLogger("ai-transcribe.session")


@dataclass
class TranscribeSession:
    """
    Sessao de transcricao.

    Armazena dados de uma sessao WebSocket ativa.
    Suporta audio bidirecional (inbound=caller, outbound=agent).
    """
    session_id: str
    call_id: str
    # Audio config da sessao ASP (prioridade sobre AUDIO_CONFIG global)
    sample_rate: int = 0  # 0 = usa AUDIO_CONFIG fallback
    sample_width: int = 0  # 0 = usa AUDIO_CONFIG fallback
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    # Buffer para audio do usuario (inbound)
    audio_buffer: bytearray = field(default_factory=bytearray)
    # Buffer para audio do agente (outbound)
    audio_buffer_outbound: bytearray = field(default_factory=bytearray)
    frames_received: int = 0
    utterances_transcribed: int = 0
    caller_id: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self):
        """Aplica fallback do AUDIO_CONFIG para campos não-setados via ASP."""
        if self.sample_rate == 0:
            self.sample_rate = AUDIO_CONFIG["sample_rate"]
        if self.sample_width == 0:
            self.sample_width = AUDIO_CONFIG["sample_width"]

    def add_audio(self, audio_data: bytes, is_outbound: bool = False) -> None:
        """
        Adiciona audio ao buffer.

        Args:
            audio_data: Dados de audio
            is_outbound: True se audio do agente, False se do usuario
        """
        buffer = self.audio_buffer_outbound if is_outbound else self.audio_buffer
        max_buffer_size = self.sample_rate * self.sample_width * AUDIO_CONFIG["max_buffer_seconds"]

        if len(buffer) + len(audio_data) > max_buffer_size:
            # Remove audio antigo para caber novo
            overflow = len(buffer) + len(audio_data) - max_buffer_size
            if is_outbound:
                self.audio_buffer_outbound = self.audio_buffer_outbound[overflow:]
            else:
                self.audio_buffer = self.audio_buffer[overflow:]
            logger.warning(f"[{self.session_id[:8]}] Buffer overflow ({'outbound' if is_outbound else 'inbound'}), descartando {overflow} bytes")

        buffer.extend(audio_data)
        self.frames_received += 1
        self.last_activity = time.time()

    def flush_audio(self, is_outbound: bool = False) -> bytes:
        """
        Retorna e limpa o buffer de audio.

        Args:
            is_outbound: True para buffer do agente, False para usuario
        """
        if is_outbound:
            audio = bytes(self.audio_buffer_outbound)
            self.audio_buffer_outbound.clear()
        else:
            audio = bytes(self.audio_buffer)
            self.audio_buffer.clear()
        return audio

    def update_activity(self) -> None:
        """Atualiza timestamp de ultima atividade."""
        self.last_activity = time.time()

    @property
    def idle_seconds(self) -> float:
        """Segundos desde ultima atividade."""
        return time.time() - self.last_activity

    @property
    def duration_seconds(self) -> float:
        """Duracao da sessao em segundos."""
        return time.time() - self.created_at

    @property
    def buffer_size(self) -> int:
        """Tamanho atual do buffer em bytes."""
        return len(self.audio_buffer)

    @property
    def buffer_duration_ms(self) -> float:
        """Duracao do buffer em ms."""
        bytes_per_second = self.sample_rate * self.sample_width
        return (len(self.audio_buffer) / bytes_per_second) * 1000


class SessionManager:
    """
    Gerenciador de sessoes de transcricao.

    Gerencia o ciclo de vida das sessoes e limpeza de sessoes inativas.
    """

    def __init__(self):
        self._sessions: Dict[str, TranscribeSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        session_id: str,
        call_id: str,
        caller_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        sample_rate: int = 0,
        sample_width: int = 0,
    ) -> TranscribeSession:
        """
        Cria nova sessao.

        Args:
            session_id: ID da sessao
            call_id: ID da chamada
            caller_id: Numero do chamador (opcional)
            metadata: Metadados adicionais
            sample_rate: Sample rate negociado via ASP (0 = fallback AUDIO_CONFIG)
            sample_width: Sample width negociado via ASP (0 = fallback AUDIO_CONFIG)

        Returns:
            Sessao criada
        """
        async with self._lock:
            if session_id in self._sessions:
                logger.warning(f"Sessao {session_id[:8]} ja existe")
                return self._sessions[session_id]

            session = TranscribeSession(
                session_id=session_id,
                call_id=call_id,
                sample_rate=sample_rate,
                sample_width=sample_width,
                caller_id=caller_id,
                metadata=metadata or {},
            )

            self._sessions[session_id] = session
            ACTIVE_SESSIONS.set(len(self._sessions))

            logger.info(f"[{session_id[:8]}] Sessao criada (call: {call_id})")
            return session

    async def get_session(self, session_id: str) -> Optional[TranscribeSession]:
        """Obtem sessao por ID."""
        return self._sessions.get(session_id)

    async def end_session(self, session_id: str, reason: str = "normal") -> bool:
        """
        Encerra uma sessao.

        Args:
            session_id: ID da sessao
            reason: Motivo do encerramento

        Returns:
            True se sessao foi encerrada
        """
        async with self._lock:
            if session_id not in self._sessions:
                return False

            session = self._sessions.pop(session_id)
            ACTIVE_SESSIONS.set(len(self._sessions))

            logger.info(
                f"[{session_id[:8]}] Sessao encerrada: "
                f"reason={reason}, "
                f"duration={session.duration_seconds:.1f}s, "
                f"frames={session.frames_received}, "
                f"utterances={session.utterances_transcribed}"
            )

            return True

    async def cleanup_stale_sessions(self, max_idle_seconds: Optional[int] = None) -> int:
        """
        Remove sessoes inativas.

        Args:
            max_idle_seconds: Tempo maximo de inatividade

        Returns:
            Numero de sessoes removidas
        """
        max_idle = max_idle_seconds or SESSION_CONFIG["max_idle_seconds"]
        removed = 0

        async with self._lock:
            stale_ids = [
                sid for sid, session in self._sessions.items()
                if session.idle_seconds > max_idle
            ]

            for session_id in stale_ids:
                del self._sessions[session_id]
                removed += 1
                logger.info(f"[{session_id[:8]}] Sessao removida por inatividade")

            if removed > 0:
                ACTIVE_SESSIONS.set(len(self._sessions))

        return removed

    @property
    def active_count(self) -> int:
        """Numero de sessoes ativas."""
        return len(self._sessions)

    def get_all_sessions(self) -> Dict[str, TranscribeSession]:
        """Retorna todas as sessoes (copia)."""
        return dict(self._sessions)
