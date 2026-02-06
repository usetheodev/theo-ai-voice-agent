"""
Gerenciamento de Sessões de Conversação
"""

import logging
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional, Literal
from datetime import datetime, timezone

from config import SESSION_CONFIG
from pipeline.conversation import ConversationPipeline
from pipeline.vad import AudioBuffer
from providers.pool import ProviderPool
from ws.protocol import AudioConfig, session_id_to_hash
from metrics import track_session_start, track_session_end, ACTIVE_SESSIONS

logger = logging.getLogger("ai-agent.session")


SessionState = Literal['listening', 'processing', 'responding', 'idle']


@dataclass
class Session:
    """Sessão de conversação"""
    session_id: str
    call_id: str
    audio_config: AudioConfig
    pipeline: ConversationPipeline
    audio_buffer: AudioBuffer
    state: SessionState = 'idle'
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Lock para operações thread-safe
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Contador de interacoes sem resolucao (para escalacao automatica)
    interaction_count: int = 0

    # Contador de frames ignorados (quando state != listening)
    _ignored_frames: int = 0

    # Timestamps para métricas TTFB
    audio_end_timestamp: float = 0.0  # Quando audio.end foi recebido
    ttfb_recorded: bool = False  # Se TTFB já foi registrado para esta resposta

    @property
    def session_hash(self) -> str:
        """Retorna hash hex do session_id (para lookup em frames de áudio)"""
        return session_id_to_hash(self.session_id).hex()

    def update_activity(self):
        """Atualiza timestamp de última atividade"""
        self.last_activity = datetime.now(timezone.utc)

    async def set_state(self, new_state: SessionState):
        """Define estado da sessão (thread-safe)"""
        async with self._lock:
            old_state = self.state
            self.state = new_state
            self.update_activity()
            logger.debug(f"[{self.session_id[:8]}] Estado: {old_state} -> {new_state}")


class SessionManager:
    """Gerenciador de sessões de conversação"""

    def __init__(self, pool: Optional[ProviderPool] = None):
        self.sessions: Dict[str, Session] = {}
        self._hash_to_session: Dict[str, str] = {}  # hash_hex -> session_id
        self._lock = asyncio.Lock()
        self._pool = pool

    async def create_session(
        self,
        session_id: str,
        call_id: str,
        audio_config: AudioConfig
    ) -> Session:
        """Cria nova sessão"""
        async with self._lock:
            if session_id in self.sessions:
                logger.warning(f"Sessão já existe: {session_id}")
                return self.sessions[session_id]

            # Cria pipeline SEM auto_init (evita asyncio.run() em contexto async)
            pipeline = ConversationPipeline(auto_init=False)

            # Usa providers compartilhados do pool (se disponivel)
            if self._pool and self._pool.is_ready:
                pipeline.init_with_shared_providers(self._pool.stt, self._pool.tts)
            else:
                # Fallback: inicializa providers por sessao
                await pipeline.init_providers_async()

            # Cria audio buffer
            audio_buffer = AudioBuffer()

            session = Session(
                session_id=session_id,
                call_id=call_id,
                audio_config=audio_config,
                pipeline=pipeline,
                audio_buffer=audio_buffer,
                state='idle'
            )

            self.sessions[session_id] = session
            self._hash_to_session[session.session_hash] = session_id

            # Registra métricas
            track_session_start()

            logger.info(f" Sessão criada: {session_id[:8]} (call: {call_id})")
            return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Retorna sessão pelo ID"""
        return self.sessions.get(session_id)

    async def get_session_by_hash(self, hash_hex: str) -> Optional[Session]:
        """Retorna sessão pelo hash do ID"""
        session_id = self._hash_to_session.get(hash_hex)
        if session_id:
            return self.sessions.get(session_id)
        return None

    async def end_session(self, session_id: str, reason: str = "hangup") -> bool:
        """Encerra sessão"""
        async with self._lock:
            if session_id not in self.sessions:
                logger.warning(f"Sessão não encontrada: {session_id}")
                return False

            session = self.sessions[session_id]

            # Calcula duração
            duration = (datetime.now(timezone.utc) - session.created_at).total_seconds()

            # Registra métricas
            track_session_end(reason, duration)

            # Remove do lookup de hash
            if session.session_hash in self._hash_to_session:
                del self._hash_to_session[session.session_hash]

            # Remove sessão
            del self.sessions[session_id]

            logger.info(f" Sessão encerrada: {session_id[:8]} (duração: {duration:.1f}s)")
            return True

    def get_session_id_lookup(self) -> Dict[str, str]:
        """Retorna dicionário hash -> session_id para parse de frames"""
        return dict(self._hash_to_session)

    @property
    def active_count(self) -> int:
        """Número de sessões ativas"""
        return len(self.sessions)

    async def cleanup_stale_sessions(self, max_idle_seconds: int = None):
        """Remove sessões inativas"""
        # Usa valor passado ou configuração do SESSION_CONFIG
        if max_idle_seconds is None:
            max_idle_seconds = SESSION_CONFIG.get("max_idle_seconds", 300)

        async with self._lock:
            now = datetime.now(timezone.utc)
            stale = []

            for session_id, session in self.sessions.items():
                idle_time = (now - session.last_activity).total_seconds()
                if idle_time > max_idle_seconds:
                    stale.append(session_id)

            for session_id in stale:
                session = self.sessions[session_id]
                duration = (now - session.created_at).total_seconds()

                # Registra métricas
                track_session_end("timeout", duration)

                if session.session_hash in self._hash_to_session:
                    del self._hash_to_session[session.session_hash]
                del self.sessions[session_id]
                logger.info(f" Sessão removida por inatividade: {session_id[:8]}")

            return len(stale)
