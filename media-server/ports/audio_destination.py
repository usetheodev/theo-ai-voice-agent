"""
Interface para destino de áudio - Porta do Media Server

Define o contrato que qualquer destino de áudio deve implementar,
permitindo conectar em AI Agent, Softphone, WebRTC, etc.
"""

from typing import Protocol, Callable, Optional, runtime_checkable
from dataclasses import dataclass, field
from enum import Enum


class SessionState(Enum):
    """Estado da conexão com o destino de áudio"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class AudioConfig:
    """Configuração de áudio para a sessão"""
    sample_rate: int = 8000
    channels: int = 1
    sample_width: int = 2  # bytes (16-bit)


@dataclass
class SessionInfo:
    """Informações da sessão de áudio"""
    session_id: str
    call_id: str
    audio_config: AudioConfig = field(default_factory=AudioConfig)


@runtime_checkable
class IAudioDestination(Protocol):
    """
    Interface para destino de áudio (AI Agent, Softphone, WebRTC, etc.)

    Esta interface define o contrato que qualquer adaptador de destino
    de áudio deve implementar para ser usado pelo Media Server.

    Fluxo típico:
        1. connect() - Estabelece conexão com o destino
        2. start_session() - Inicia sessão de conversação
        3. send_audio() - Envia chunks de áudio do usuário
        4. send_audio_end() - Sinaliza fim de fala do usuário
        5. end_session() - Encerra sessão
        6. disconnect() - Desconecta do destino

    Callbacks são atribuídos externamente para receber eventos:
        - on_session_started: Sessão iniciada com sucesso
        - on_response_start: AI iniciou resposta (com texto)
        - on_response_audio: Chunk de áudio da resposta
        - on_response_end: Resposta concluída
        - on_error: Erro na sessão
    """

    @property
    def is_connected(self) -> bool:
        """Verifica se está conectado ao destino"""
        ...

    async def connect(self) -> bool:
        """
        Estabelece conexão com o destino de áudio.

        Returns:
            True se conectou com sucesso, False caso contrário
        """
        ...

    async def disconnect(self) -> None:
        """Desconecta do destino de áudio"""
        ...

    async def start_session(self, session_info: SessionInfo) -> bool:
        """
        Inicia nova sessão de conversação.

        Args:
            session_info: Informações da sessão (IDs, config de áudio)

        Returns:
            True se sessão iniciada com sucesso
        """
        ...

    async def end_session(self, session_id: str, reason: str = "hangup") -> None:
        """
        Encerra sessão de conversação.

        Args:
            session_id: ID da sessão
            reason: Motivo do encerramento
        """
        ...

    async def send_audio(self, session_id: str, audio_data: bytes) -> None:
        """
        Envia chunk de áudio do usuário.

        Args:
            session_id: ID da sessão
            audio_data: Dados de áudio PCM
        """
        ...

    async def send_audio_end(self, session_id: str) -> None:
        """
        Sinaliza fim da fala do usuário.

        Args:
            session_id: ID da sessão
        """
        ...

    # Event handlers (atribuídos externamente)
    on_session_started: Optional[Callable[[str], None]]
    on_response_start: Optional[Callable[[str, str], None]]  # session_id, text
    on_response_audio: Optional[Callable[[str, bytes], None]]  # session_id, audio
    on_response_end: Optional[Callable[[str], None]]  # session_id
    on_error: Optional[Callable[[str, str, str], None]]  # session_id, code, message
