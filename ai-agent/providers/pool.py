"""
Pool Global de Providers STT/TTS.

Singleton que carrega modelos uma unica vez no startup do servidor.
Sessoes recebem referencias compartilhadas, nao instancias proprias.

Isso reduz memoria de O(n * modelo) para O(1) e elimina warmup por sessao.
"""

import logging
from typing import Optional

from providers.stt import STTProvider, create_stt_provider
from providers.tts import TTSProvider, create_tts_provider

logger = logging.getLogger("ai-agent.pool")


class ProviderPool:
    """Singleton que gerencia instancias compartilhadas de STT e TTS."""

    _instance: Optional["ProviderPool"] = None

    def __init__(self):
        self.stt: Optional[STTProvider] = None
        self.tts: Optional[TTSProvider] = None
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "ProviderPool":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def initialize(self):
        """Carrega modelos uma unica vez (chamado no startup do servidor)."""
        if self._initialized:
            return

        logger.info("Inicializando pool de providers...")

        self.stt = await create_stt_provider()
        logger.info("Pool: STT carregado e aquecido")

        self.tts = await create_tts_provider()
        logger.info("Pool: TTS carregado e aquecido")

        self._initialized = True
        logger.info("Pool de providers inicializado (STT + TTS compartilhados)")

    async def shutdown(self):
        """Libera recursos (chamado no shutdown do servidor)."""
        if self.stt and hasattr(self.stt, 'disconnect'):
            await self.stt.disconnect()
        if self.tts and hasattr(self.tts, 'disconnect'):
            await self.tts.disconnect()
        self._initialized = False
        logger.info("Pool de providers encerrado")

    @property
    def is_ready(self) -> bool:
        return self._initialized and self.stt is not None and self.tts is not None
