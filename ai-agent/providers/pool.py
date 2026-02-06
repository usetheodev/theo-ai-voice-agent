"""
Pool Global de Providers STT/TTS.

Singleton que carrega modelos uma unica vez no startup do servidor.
Sessoes recebem referencias compartilhadas, nao instancias proprias.

Isso reduz memoria de O(n * modelo) para O(1) e elimina warmup por sessao.

Suporta fallback automatico: se o provider principal estiver com circuit
breaker OPEN, retorna o provider de fallback (se configurado).
"""

import logging
import time
from typing import Optional

from config import STT_CONFIG, TTS_CONFIG, LLM_CONFIG
from providers.stt import STTProvider, create_stt_provider
from providers.tts import TTSProvider, create_tts_provider
from providers.base import CircuitState

logger = logging.getLogger("ai-agent.pool")


class ProviderPool:
    """Singleton que gerencia instancias compartilhadas de STT e TTS."""

    _instance: Optional["ProviderPool"] = None

    def __init__(self):
        self.stt: Optional[STTProvider] = None
        self.tts: Optional[TTSProvider] = None
        self._stt_fallback: Optional[STTProvider] = None
        self._tts_fallback: Optional[TTSProvider] = None
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

        # Warmup LLM: força Docker Model Runner a carregar modelo na memória
        await self._warmup_llm()

        # Carrega fallbacks se configurados (lazy - não faz warmup)
        stt_fallback_name = STT_CONFIG.get("fallback_provider", "")
        if stt_fallback_name and stt_fallback_name != STT_CONFIG["provider"]:
            try:
                self._stt_fallback = await create_stt_provider(provider_name=stt_fallback_name)
                logger.info(f"Pool: STT fallback carregado ({stt_fallback_name})")
            except Exception as e:
                logger.warning(f"Pool: Falha ao carregar STT fallback ({stt_fallback_name}): {e}")

        tts_fallback_name = TTS_CONFIG.get("fallback_provider", "")
        if tts_fallback_name and tts_fallback_name != TTS_CONFIG["provider"]:
            try:
                self._tts_fallback = await create_tts_provider(provider_name=tts_fallback_name)
                logger.info(f"Pool: TTS fallback carregado ({tts_fallback_name})")
            except Exception as e:
                logger.warning(f"Pool: Falha ao carregar TTS fallback ({tts_fallback_name}): {e}")

        self._initialized = True
        logger.info("Pool de providers inicializado (STT + TTS compartilhados)")

    async def _warmup_llm(self):
        """Envia request mínimo ao LLM para forçar carregamento do modelo.

        O Docker Model Runner (e similares) só carrega o modelo na primeira
        inferência. Sem warmup, a primeira chamada real leva 27-30s.
        Este warmup descartável força o carregamento no startup do servidor.
        """
        provider = LLM_CONFIG.get("provider", "mock")
        if provider == "mock":
            logger.info("Pool: LLM mock, warmup desnecessário")
            return

        try:
            from providers.llm import create_llm_provider
            import asyncio

            start = time.perf_counter()
            llm = create_llm_provider()

            # Envia request mínimo (1 token) para forçar carregamento do modelo
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, llm.generate, "Oi"
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info(f"Pool: LLM aquecido em {elapsed_ms:.0f}ms (provider={provider})")
        except Exception as e:
            logger.warning(f"Pool: LLM warmup falhou (não crítico): {e}")

    def get_stt(self, allow_fallback: bool = True) -> Optional[STTProvider]:
        """Retorna provider STT saudável.

        Se o principal está em circuit breaker OPEN e fallback está disponível
        e conectado, retorna o fallback automaticamente.
        """
        if self.stt and self.stt.circuit_state == CircuitState.OPEN:
            if allow_fallback and self._stt_fallback and self._stt_fallback.is_connected:
                logger.warning(
                    f"STT primary unavailable (circuit OPEN), using fallback: "
                    f"{self._stt_fallback.provider_name}"
                )
                return self._stt_fallback
        return self.stt

    def get_tts(self, allow_fallback: bool = True) -> Optional[TTSProvider]:
        """Retorna provider TTS saudável.

        Se o principal está em circuit breaker OPEN e fallback está disponível
        e conectado, retorna o fallback automaticamente.
        """
        if self.tts and self.tts.circuit_state == CircuitState.OPEN:
            if allow_fallback and self._tts_fallback and self._tts_fallback.is_connected:
                logger.warning(
                    f"TTS primary unavailable (circuit OPEN), using fallback: "
                    f"{self._tts_fallback.provider_name}"
                )
                return self._tts_fallback
        return self.tts

    async def shutdown(self):
        """Libera recursos (chamado no shutdown do servidor)."""
        for provider in [self.stt, self.tts, self._stt_fallback, self._tts_fallback]:
            if provider:
                try:
                    await provider.disconnect()
                except Exception as e:
                    logger.warning(f"Erro ao desconectar {provider.provider_name}: {e}")
        self._initialized = False
        logger.info("Pool de providers encerrado")

    @property
    def is_ready(self) -> bool:
        return self._initialized and self.stt is not None and self.tts is not None
