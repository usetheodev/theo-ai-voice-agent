"""
Pipeline de Conversação: STT → LLM → TTS

Arquitetura full-async com suporte a:
- Providers assíncronos com lifecycle (connect/disconnect)
- Warmup para eliminar cold-start
- Streaming para menor latência
- Métricas e health checks

Modos de operação:
- Batch: Processa todo o áudio de uma vez (process_async)
- Stream: Processa e retorna áudio incrementalmente (process_stream_async)
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple, AsyncGenerator

from config import AUDIO_CONFIG, AGENT_MESSAGES, PIPELINE_CONFIG
from providers.llm import create_llm_provider, LLMProvider
from utils.logging import get_session_logger
from metrics import (
    track_component_latency,
    track_pipeline_latency,
    track_pipeline_error,
    PIPELINE_LATENCY,
)

logger = logging.getLogger("ai-agent.pipeline")


class ConversationPipeline:
    """
    Pipeline de conversação: STT → LLM → TTS (full-async)

    Suporta modo batch e streaming para menor latência.
    Todos os métodos de processamento são assíncronos.
    """

    def __init__(self, auto_init: bool = False):
        """
        Inicializa pipeline.

        Args:
            auto_init: Ignorado (mantido para compatibilidade de assinatura).
                      Use init_providers_async() ou init_with_shared_providers().
        """
        from providers.stt import STTProvider
        from providers.tts import TTSProvider

        self.stt: Optional[STTProvider] = None
        self.llm: Optional[LLMProvider] = None
        self.tts: Optional[TTSProvider] = None
        self._shared_providers: bool = False

    @property
    def pending_tool_calls(self) -> List[Dict]:
        """Delega ao LLM provider (single source of truth, sem cópias intermediárias)."""
        return self.llm.pending_tool_calls if self.llm else []

    @pending_tool_calls.setter
    def pending_tool_calls(self, value: List[Dict]):
        """Seta pending_tool_calls no LLM provider."""
        if self.llm:
            self.llm.pending_tool_calls = value

    async def init_providers_async(self):
        """Inicializa provedores de forma assíncrona (recomendado)."""
        from providers.stt import create_stt_provider
        from providers.tts import create_tts_provider

        try:
            self.stt = await create_stt_provider()
            logger.info(" STT inicializado (async)")
        except Exception as e:
            logger.warning(f"STT não disponível: {e}")

        try:
            self.llm = create_llm_provider()
            logger.info(" LLM inicializado")
        except Exception as e:
            logger.warning(f"LLM não disponível: {e}")

        try:
            self.tts = await create_tts_provider()
            logger.info(" TTS inicializado (async)")
        except Exception as e:
            logger.warning(f"TTS não disponível: {e}")

    def init_with_shared_providers(self, stt, tts):
        """Inicializa pipeline com providers compartilhados do pool global.

        STT e TTS sao referencias compartilhadas (lifecycle gerenciado pelo pool).
        LLM e criado localmente (stateful, mantem historico por sessao).
        """
        self.stt = stt
        self.tts = tts
        self._shared_providers = True

        try:
            self.llm = create_llm_provider()
            logger.info(" LLM inicializado (por sessao)")
        except Exception as e:
            logger.warning(f"LLM não disponível: {e}")

    async def disconnect(self):
        """Desconecta providers locais. Providers compartilhados sao gerenciados pelo pool."""
        if not self._shared_providers:
            if self.stt and hasattr(self.stt, 'disconnect'):
                await self.stt.disconnect()
            if self.tts and hasattr(self.tts, 'disconnect'):
                await self.tts.disconnect()
        logger.info(" Pipeline desconectado")

    # ==================== Health Check ====================

    async def health_check(self) -> dict:
        """Verifica saúde de todos os providers."""
        health = {"status": "healthy", "providers": {}}

        if self.stt and hasattr(self.stt, 'health_check'):
            result = await self.stt.health_check()
            health["providers"]["stt"] = {
                "status": result.status.value,
                "message": result.message,
                "latency_ms": result.latency_ms,
            }
            if result.status.value != "healthy":
                health["status"] = "degraded"

        if self.tts and hasattr(self.tts, 'health_check'):
            result = await self.tts.health_check()
            health["providers"]["tts"] = {
                "status": result.status.value,
                "message": result.message,
                "latency_ms": result.latency_ms,
            }
            if result.status.value != "healthy":
                health["status"] = "degraded"

        health["providers"]["llm"] = {
            "status": "healthy" if self.llm else "unhealthy",
        }

        return health

    # ==================== Métricas ====================

    def get_metrics(self) -> dict:
        """Retorna métricas de todos os providers."""
        metrics = {}

        if self.stt and hasattr(self.stt, 'metrics'):
            m = self.stt.metrics
            metrics["stt"] = {
                "total_requests": m.total_requests,
                "successful_requests": m.successful_requests,
                "failed_requests": m.failed_requests,
                "avg_latency_ms": m.avg_latency_ms,
                "success_rate": m.success_rate,
            }

        if self.tts and hasattr(self.tts, 'metrics'):
            m = self.tts.metrics
            metrics["tts"] = {
                "total_requests": m.total_requests,
                "successful_requests": m.successful_requests,
                "failed_requests": m.failed_requests,
                "avg_latency_ms": m.avg_latency_ms,
                "success_rate": m.success_rate,
            }

        return metrics

    # ==================== Processing (Async) ====================

    async def process_async(
        self,
        audio_data: bytes,
        latency_budget=None,
        session_id: str = "",
        input_sample_rate: int = 0,
    ) -> Tuple[Optional[str], Optional[bytes]]:
        """
        Processa áudio de forma assíncrona: STT → LLM → TTS

        Args:
            audio_data: Áudio PCM mono 16-bit
            latency_budget: LatencyBudget opcional para rastrear E2E
            session_id: ID da sessão para structured logging
            input_sample_rate: Sample rate do áudio (da sessão ASP). 0 = usa config do provider.

        Returns:
            Tuple[text_response, audio_response]
        """
        slog = get_session_logger("ai-agent.pipeline", session_id) if session_id else logger
        pipeline_start = time.perf_counter()

        # 1. Speech-to-Text (async)
        stt_start = time.perf_counter()
        text = await self._transcribe_async(audio_data, input_sample_rate=input_sample_rate)
        stt_ms = (time.perf_counter() - stt_start) * 1000
        if latency_budget:
            latency_budget.record_stage('stt', stt_ms)

        if not text:
            sr = input_sample_rate or AUDIO_CONFIG.get("sample_rate", 8000)
            audio_duration_ms = len(audio_data) / 2 / sr * 1000
            slog.info(
                f"STT vazio (audio: {audio_duration_ms:.0f}ms, stt_latency: {stt_ms:.0f}ms)",
                extra={"stage": "stt"}
            )
            return None, None

        slog.info(f"Transcribed: \"{text}\"", extra={"stage": "stt", "duration_ms": stt_ms})

        # 2. LLM (sync in thread)
        llm_start = time.perf_counter()
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, self._generate_response, text)
        llm_ms = (time.perf_counter() - llm_start) * 1000
        if latency_budget:
            latency_budget.record_stage('llm', llm_ms)
        slog.info(f"Response: \"{response[:60]}...\"", extra={"stage": "llm", "duration_ms": llm_ms})

        # 3. Text-to-Speech (async)
        tts_start = time.perf_counter()
        audio_response = await self._synthesize_async(response)
        tts_ms = (time.perf_counter() - tts_start) * 1000
        if latency_budget:
            latency_budget.record_stage('tts', tts_ms)
        slog.info(f"Synthesized {len(audio_response) if audio_response else 0} bytes", extra={"stage": "tts", "duration_ms": tts_ms})

        # Registra latência
        pipeline_elapsed = time.perf_counter() - pipeline_start
        PIPELINE_LATENCY.observe(pipeline_elapsed)
        slog.info(f"Pipeline batch total: {pipeline_elapsed:.2f}s")

        return response, audio_response

    async def process_stream_async(
        self,
        audio_data: bytes,
        latency_budget=None,
        session_id: str = "",
        input_sample_rate: int = 0,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncGenerator[Tuple[str, bytes], None]:
        """
        Processa áudio com streaming REAL assíncrono usando SentencePipeline.

        O TTS começa a sintetizar assim que o LLM gera a primeira frase.
        Isso reduz significativamente a latência percebida.

        Args:
            audio_data: Áudio PCM mono 16-bit
            latency_budget: LatencyBudget opcional para rastrear E2E
            session_id: ID da sessão para structured logging
            input_sample_rate: Sample rate do áudio (da sessão ASP). 0 = usa config do provider.

        Yields:
            Tuple[text_chunk, audio_chunk]: Fragmentos de texto e áudio
        """
        slog = get_session_logger("ai-agent.pipeline", session_id) if session_id else logger
        pipeline_start = time.perf_counter()

        # 1. Speech-to-Text (async)
        stt_start = time.perf_counter()
        text = await self._transcribe_async(audio_data, input_sample_rate=input_sample_rate)
        stt_ms = (time.perf_counter() - stt_start) * 1000
        if latency_budget:
            latency_budget.record_stage('stt', stt_ms)

        if not text:
            sr = input_sample_rate or AUDIO_CONFIG.get("sample_rate", 8000)
            audio_duration_ms = len(audio_data) / 2 / sr * 1000
            slog.info(
                f"STT vazio (audio: {audio_duration_ms:.0f}ms, stt_latency: {stt_ms:.0f}ms)",
                extra={"stage": "stt"}
            )
            return

        slog.info(f"Transcribed: \"{text}\"", extra={"stage": "stt", "duration_ms": stt_ms})

        # 2+3. LLM → TTS streaming sentence-level
        if self.llm and self.llm.supports_streaming and self.tts:
            # Usa SentencePipeline para streaming real LLM→TTS
            from pipeline.sentence_pipeline import SentencePipeline

            queue_size = PIPELINE_CONFIG.get("sentence_queue_size", 3)
            sentence_pipeline = SentencePipeline(
                llm=self.llm,
                tts=self.tts,
                queue_size=queue_size,
                cancel_event=cancel_event,
            )

            first_audio_yielded = False
            async for sentence, audio_chunk in sentence_pipeline.process_streaming(text):
                if not first_audio_yielded and latency_budget:
                    # Registra latência LLM+TTS no primeiro áudio
                    first_audio_ms = (time.perf_counter() - pipeline_start) * 1000 - stt_ms
                    latency_budget.record_stage('llm+tts_first', first_audio_ms)
                    first_audio_yielded = True
                yield sentence, audio_chunk

            # Log métricas do pipeline
            metrics = sentence_pipeline.metrics
            if latency_budget:
                latency_budget.record_stage('llm_tts_total', metrics.total_latency_ms)
            slog.info(
                f"SentencePipeline: first_audio={metrics.first_audio_latency_ms:.0f}ms, "
                f"total={metrics.total_latency_ms:.0f}ms",
                extra={"stage": "llm+tts"}
            )
        else:
            # Fallback para modo batch
            llm_start = time.perf_counter()
            response = await asyncio.get_running_loop().run_in_executor(
                None, self._generate_response, text
            )
            llm_ms = (time.perf_counter() - llm_start) * 1000
            if latency_budget:
                latency_budget.record_stage('llm', llm_ms)
            slog.info(f"Response: \"{response[:60]}...\"", extra={"stage": "llm", "duration_ms": llm_ms})

            tts_start = time.perf_counter()
            audio_response = await self._synthesize_async(response)
            tts_ms = (time.perf_counter() - tts_start) * 1000
            if latency_budget:
                latency_budget.record_stage('tts', tts_ms)
            slog.info(f"Synthesized {len(audio_response) if audio_response else 0} bytes", extra={"stage": "tts", "duration_ms": tts_ms})

            if audio_response:
                yield response, audio_response

        # Registra latência total
        pipeline_elapsed = time.perf_counter() - pipeline_start
        PIPELINE_LATENCY.observe(pipeline_elapsed)
        slog.info(f"Pipeline stream total: {pipeline_elapsed:.2f}s")

    # ==================== Sync wrapper (único ponto de entrada) ====================

    def process_sync(self, audio_data: bytes) -> Tuple[Optional[str], Optional[bytes]]:
        """
        Wrapper síncrono fino para process_async.

        ATENÇÃO: Só deve ser usado fora de um event loop (ex: CLI, scripts).
        Nunca use dentro de métodos async ou callbacks.
        """
        return asyncio.run(self.process_async(audio_data))

    # ==================== Component Methods ====================

    async def _transcribe_async(self, audio_data: bytes, input_sample_rate: int = 0) -> Optional[str]:
        """Transcreve áudio para texto (async).

        Args:
            audio_data: Áudio PCM 16-bit signed
            input_sample_rate: Sample rate da sessão ASP (0 = usa config do provider)
        """
        if not self.stt:
            logger.warning("STT não disponível")
            return None

        try:
            with track_component_latency('stt'):
                text = await self.stt.transcribe(audio_data, input_sample_rate=input_sample_rate)

            if text and len(text.strip()) >= 2:
                return text.strip()
            return None

        except Exception as e:
            logger.error(f"Erro no STT: {e}")
            track_pipeline_error('stt')
            return None

    def _generate_response(self, text: str) -> str:
        """Gera resposta do LLM."""
        if not self.llm:
            return f"Você disse: {text}"

        try:
            with track_component_latency('llm'):
                return self.llm.generate(text)
        except Exception as e:
            logger.error(f"Erro no LLM: {e}")
            track_pipeline_error('llm')
            return AGENT_MESSAGES["error"]

    async def synthesize_text_async(self, text: str) -> Optional[bytes]:
        """Sintetiza texto em áudio (async) - API pública para uso externo."""
        return await self._synthesize_async(text)

    async def _synthesize_async(self, text: str) -> Optional[bytes]:
        """Sintetiza texto em áudio (async)."""
        if not self.tts:
            logger.warning("TTS não disponível")
            return None

        try:
            with track_component_latency('tts'):
                return await self.tts.synthesize(text)
        except Exception as e:
            logger.error(f"Erro no TTS: {e}")
            track_pipeline_error('tts')
            return None

    async def _synthesize_stream_async(self, text: str) -> AsyncGenerator[bytes, None]:
        """Sintetiza texto em áudio com streaming (async)."""
        if not self.tts:
            return

        if hasattr(self.tts, 'synthesize_stream'):
            async for chunk in self.tts.synthesize_stream(text):
                yield chunk
        else:
            # Fallback para batch
            audio = await self._synthesize_async(text)
            if audio:
                yield audio

    # ==================== Greeting / Error ====================

    async def generate_greeting_async(self) -> Tuple[str, Optional[bytes]]:
        """Gera saudação inicial (async)."""
        greeting = AGENT_MESSAGES["greeting"]
        audio = await self._synthesize_async(greeting)
        return greeting, audio

    # ==================== Utils ====================

    def reset(self):
        """Reseta estado da conversa."""
        if self.llm:
            self.llm.reset_conversation()
        logger.info(" Pipeline resetado")

    @property
    def is_ready(self) -> bool:
        """Verifica se pipeline está pronto."""
        return self.stt is not None and self.llm is not None and self.tts is not None

    @property
    def supports_streaming(self) -> bool:
        """Verifica se pipeline suporta streaming completo."""
        llm_stream = self.llm.supports_streaming if self.llm else False
        tts_stream = self.tts.supports_streaming if self.tts else False
        return llm_stream and tts_stream

    @property
    def supports_streaming_stt(self) -> bool:
        """Verifica se STT provider suporta transcrição incremental."""
        return self.stt.supports_streaming_stt if self.stt else False


# ==================== Factory ====================

async def create_pipeline_async() -> ConversationPipeline:
    """
    Factory assíncrona para criar pipeline com providers inicializados.

    Returns:
        ConversationPipeline com providers conectados e aquecidos.
    """
    pipeline = ConversationPipeline(auto_init=False)
    await pipeline.init_providers_async()
    return pipeline
