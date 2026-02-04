"""
Adapter para AI Agent via WebSocket

Implementa IAudioDestination encapsulando o WebSocketClient existente.
"""

import logging
from typing import Optional, Callable

from ports.audio_destination import IAudioDestination, SessionInfo, AudioConfig
from ws.client import WebSocketClient

logger = logging.getLogger("media-server.adapter.ai_agent")


class AIAgentAdapter:
    """
    Adapter que conecta ao AI Agent via WebSocket.

    Implementa IAudioDestination delegando para WebSocketClient.
    Mantém retrocompatibilidade com o código existente.
    """

    def __init__(self):
        self._client = WebSocketClient()

        # Callbacks - inicializados como None
        self._on_session_started: Optional[Callable[[str], None]] = None
        self._on_response_start: Optional[Callable[[str, str], None]] = None
        self._on_response_audio: Optional[Callable[[str, bytes], None]] = None
        self._on_response_end: Optional[Callable[[str], None]] = None
        self._on_error: Optional[Callable[[str, str, str], None]] = None

    @property
    def is_connected(self) -> bool:
        """Verifica se está conectado ao AI Agent"""
        return self._client.is_connected

    async def connect(self) -> bool:
        """Estabelece conexão WebSocket com o AI Agent"""
        return await self._client.connect()

    async def disconnect(self) -> None:
        """Desconecta do AI Agent"""
        await self._client.disconnect()

    async def wait_connected(self, timeout: float = 30) -> bool:
        """Aguarda conexão estar pronta (delegado para compatibilidade)"""
        return await self._client.wait_connected(timeout)

    async def start_session(self, session_info: SessionInfo) -> bool:
        """
        Inicia sessão de conversação no AI Agent.

        Args:
            session_info: Informações da sessão

        Returns:
            True se sessão iniciada com sucesso
        """
        return await self._client.start_session(
            session_id=session_info.session_id,
            call_id=session_info.call_id
        )

    async def end_session(self, session_id: str, reason: str = "hangup") -> None:
        """Encerra sessão no AI Agent"""
        await self._client.end_session(session_id, reason)

    async def send_audio(self, session_id: str, audio_data: bytes) -> None:
        """Envia chunk de áudio para o AI Agent"""
        await self._client.send_audio(session_id, audio_data)

    async def send_audio_end(self, session_id: str) -> None:
        """Sinaliza fim da fala do usuário"""
        await self._client.send_audio_end(session_id)

    # Properties para callbacks com sincronização bidirecional

    @property
    def on_session_started(self) -> Optional[Callable[[str], None]]:
        return self._on_session_started

    @on_session_started.setter
    def on_session_started(self, callback: Optional[Callable[[str], None]]) -> None:
        self._on_session_started = callback
        self._client.on_session_started = callback

    @property
    def on_response_start(self) -> Optional[Callable[[str, str], None]]:
        return self._on_response_start

    @on_response_start.setter
    def on_response_start(self, callback: Optional[Callable[[str, str], None]]) -> None:
        self._on_response_start = callback
        self._client.on_response_start = callback

    @property
    def on_response_audio(self) -> Optional[Callable[[str, bytes], None]]:
        return self._on_response_audio

    @on_response_audio.setter
    def on_response_audio(self, callback: Optional[Callable[[str, bytes], None]]) -> None:
        self._on_response_audio = callback
        self._client.on_response_audio = callback

    @property
    def on_response_end(self) -> Optional[Callable[[str], None]]:
        return self._on_response_end

    @on_response_end.setter
    def on_response_end(self, callback: Optional[Callable[[str], None]]) -> None:
        self._on_response_end = callback
        self._client.on_response_end = callback

    @property
    def on_error(self) -> Optional[Callable[[str, str, str], None]]:
        return self._on_error

    @on_error.setter
    def on_error(self, callback: Optional[Callable[[str, str, str], None]]) -> None:
        self._on_error = callback
        self._client.on_error = callback
