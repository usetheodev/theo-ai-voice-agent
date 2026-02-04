"""
Pipeline de Conversação: STT → LLM → TTS

Arquitetura refatorada com suporte a:
- Providers assíncronos com lifecycle (connect/disconnect)
- Warmup para eliminar cold-start
- Streaming para menor latência
- Métricas e health checks

Modos de operação:
- Batch: Processa todo o áudio de uma vez
- Stream: Processa e retorna áudio incrementalmente
"""

import asyncio
import logging
import queue
import threading
import time
from typing import Optional, Tuple, Generator, AsyncGenerator

from config import AUDIO_CONFIG, AGENT_MESSAGES, PIPELINE_CONFIG
from providers.stt import create_stt_provider_sync, STTProvider
from providers.llm import create_llm_provider, LLMProvider
from providers.tts import create_tts_provider_sync, TTSProvider
from metrics import (
    track_component_latency,
    track_pipeline_latency,
    track_pipeline_error,
    PIPELINE_LATENCY,
)

logger = logging.getLogger("ai-agent.pipeline")


class ConversationPipeline:
    """
    Pipeline de conversação: STT → LLM → TTS

    Suporta modo batch e streaming para menor latência.
    Os providers são inicializados de forma síncrona para compatibilidade,
    mas os métodos de transcrição e síntese são executados em threads separadas.
    """

    def __init__(self, auto_init: bool = True):
        """
        Inicializa pipeline.

        Args:
            auto_init: Se True, inicializa providers automaticamente.
                      Se False, chame init_providers() ou init_providers_async() manualmente.
        """
        self.stt: Optional[STTProvider] = None
        self.llm: Optional[LLMProvider] = None
        self.tts: Optional[TTSProvider] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        if auto_init:
            self._init_providers_sync()

    def _init_providers_sync(self):
        """Inicializa provedores de forma síncrona (compatibilidade).

        NOTA: Não tenta conectar/warmup aqui se estiver dentro de um event loop.
        Use init_providers_async() para inicialização completa em contexto async.
        """
        try:
            self.stt = create_stt_provider_sync()
            # Conecta de forma síncrona apenas se NÃO estiver em um event loop
            if hasattr(self.stt, 'connect'):
                try:
                    # Verifica se já existe um event loop rodando
                    loop = asyncio.get_running_loop()
                    # Se chegou aqui, tem loop rodando - não podemos usar asyncio.run()
                    # O connect será feito depois via init_providers_async()
                    logger.info("✅ STT criado (connect pendente - use init_providers_async)")
                except RuntimeError:
                    # Não há loop rodando - podemos usar asyncio.run()
                    asyncio.run(self.stt.connect())
                    asyncio.run(self.stt.warmup())
                    logger.info("✅ STT inicializado e conectado")
        except Exception as e:
            logger.warning(f"STT não disponível: {e}")

        try:
            self.llm = create_llm_provider()
            logger.info("✅ LLM inicializado")
        except Exception as e:
            logger.warning(f"LLM não disponível: {e}")

        try:
            self.tts = create_tts_provider_sync()
            if hasattr(self.tts, 'connect'):
                try:
                    loop = asyncio.get_running_loop()
                    # Loop rodando - connect será feito depois
                    logger.info("✅ TTS criado (connect pendente - use init_providers_async)")
                except RuntimeError:
                    # Não há loop - podemos conectar agora
                    asyncio.run(self.tts.connect())
                    asyncio.run(self.tts.warmup())
                    logger.info("✅ TTS inicializado e conectado")
        except Exception as e:
            logger.warning(f"TTS não disponível: {e}")

    async def init_providers_async(self):
        """Inicializa provedores de forma assíncrona (recomendado)."""
        from providers.stt import create_stt_provider
        from providers.tts import create_tts_provider

        try:
            self.stt = await create_stt_provider()
            logger.info("✅ STT inicializado (async)")
        except Exception as e:
            logger.warning(f"STT não disponível: {e}")

        try:
            self.llm = create_llm_provider()
            logger.info("✅ LLM inicializado")
        except Exception as e:
            logger.warning(f"LLM não disponível: {e}")

        try:
            self.tts = await create_tts_provider()
            logger.info("✅ TTS inicializado (async)")
        except Exception as e:
            logger.warning(f"TTS não disponível: {e}")

    async def disconnect(self):
        """Desconecta todos os providers."""
        if self.stt and hasattr(self.stt, 'disconnect'):
            await self.stt.disconnect()
        if self.tts and hasattr(self.tts, 'disconnect'):
            await self.tts.disconnect()
        logger.info("🔌 Pipeline desconectado")

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

    # ==================== Processing (Sync) ====================

    def process(self, audio_data: bytes) -> Tuple[Optional[str], Optional[bytes]]:
        """
        Processa áudio: STT → LLM → TTS (modo batch)

        Args:
            audio_data: Áudio PCM 8kHz mono 16-bit

        Returns:
            Tuple[text_response, audio_response]
        """
        pipeline_start = time.perf_counter()

        # 1. Speech-to-Text
        text = self._transcribe(audio_data)
        if not text:
            logger.debug("STT não detectou fala")
            return None, None

        logger.info(f"📝 Usuário: {text}")

        # 2. LLM
        response = self._generate_response(text)
        logger.info(f"🤖 Agente: {response}")

        # 3. Text-to-Speech
        audio_response = self._synthesize(response)

        # Registra latência total
        pipeline_elapsed = time.perf_counter() - pipeline_start
        PIPELINE_LATENCY.observe(pipeline_elapsed)
        logger.debug(f"⏱️ Pipeline total: {pipeline_elapsed:.2f}s")

        return response, audio_response

    def process_stream(self, audio_data: bytes) -> Generator[Tuple[str, bytes], None, None]:
        """
        Processa áudio com streaming: STT → LLM stream → TTS stream

        Yield tuplas (text_chunk, audio_chunk) conforme são gerados.

        Args:
            audio_data: Áudio PCM 8kHz mono 16-bit

        Yields:
            Tuple[text_chunk, audio_chunk]: Fragmentos de texto e áudio
        """
        pipeline_start = time.perf_counter()

        # 1. Speech-to-Text (batch)
        text = self._transcribe(audio_data)
        if not text:
            logger.debug("STT não detectou fala")
            return

        logger.info(f"📝 Usuário: {text}")

        # 2+3. LLM → TTS streaming (frase por frase)
        if self.llm and self.llm.supports_streaming and self.tts:
            for sentence in self.llm.generate_sentences(text):
                logger.info(f"🤖 Agente (frase): {sentence}")

                # Sintetiza a frase
                for audio_chunk in self._synthesize_stream_sync(sentence):
                    yield sentence, audio_chunk
        else:
            # Fallback para modo batch
            response = self._generate_response(text)
            audio_response = self._synthesize(response)
            if audio_response:
                yield response, audio_response

        # Registra latência
        pipeline_elapsed = time.perf_counter() - pipeline_start
        PIPELINE_LATENCY.observe(pipeline_elapsed)
        logger.debug(f"⏱️ Pipeline stream total: {pipeline_elapsed:.2f}s")

    # ==================== Processing (Async) ====================

    async def process_async(self, audio_data: bytes) -> Tuple[Optional[str], Optional[bytes]]:
        """
        Processa áudio de forma assíncrona: STT → LLM → TTS

        Args:
            audio_data: Áudio PCM 8kHz mono 16-bit

        Returns:
            Tuple[text_response, audio_response]
        """
        pipeline_start = time.perf_counter()

        # 1. Speech-to-Text (async)
        text = await self._transcribe_async(audio_data)
        if not text:
            logger.debug("STT não detectou fala")
            return None, None

        logger.info(f"📝 Usuário: {text}")

        # 2. LLM (sync in thread)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, self._generate_response, text)
        logger.info(f"🤖 Agente: {response}")

        # 3. Text-to-Speech (async)
        audio_response = await self._synthesize_async(response)

        # Registra latência
        pipeline_elapsed = time.perf_counter() - pipeline_start
        PIPELINE_LATENCY.observe(pipeline_elapsed)
        logger.debug(f"⏱️ Pipeline async total: {pipeline_elapsed:.2f}s")

        return response, audio_response

    async def process_stream_async(
        self,
        audio_data: bytes
    ) -> AsyncGenerator[Tuple[str, bytes], None]:
        """
        Processa áudio com streaming REAL assíncrono usando SentencePipeline.

        O TTS começa a sintetizar assim que o LLM gera a primeira frase.
        Isso reduz significativamente a latência percebida.

        Args:
            audio_data: Áudio PCM 8kHz mono 16-bit

        Yields:
            Tuple[text_chunk, audio_chunk]: Fragmentos de texto e áudio
        """
        pipeline_start = time.perf_counter()

        # 1. Speech-to-Text (async)
        text = await self._transcribe_async(audio_data)
        if not text:
            logger.debug("STT não detectou fala")
            return

        logger.info(f"📝 Usuário: {text}")

        # 2+3. LLM → TTS streaming sentence-level
        if self.llm and self.llm.supports_streaming and self.tts:
            # Usa SentencePipeline para streaming real LLM→TTS
            from pipeline.sentence_pipeline import SentencePipeline

            queue_size = PIPELINE_CONFIG.get("sentence_queue_size", 3)
            sentence_pipeline = SentencePipeline(
                llm=self.llm,
                tts=self.tts,
                queue_size=queue_size
            )

            async for sentence, audio_chunk in sentence_pipeline.process_streaming(text):
                yield sentence, audio_chunk

            # Log métricas do pipeline
            metrics = sentence_pipeline.metrics
            logger.info(
                f"📊 SentencePipeline: first_audio={metrics.first_audio_latency_ms:.0f}ms, "
                f"total={metrics.total_latency_ms:.0f}ms"
            )
        else:
            # Fallback para modo batch
            response = await asyncio.get_event_loop().run_in_executor(
                None, self._generate_response, text
            )
            audio_response = await self._synthesize_async(response)
            if audio_response:
                yield response, audio_response

        # Registra latência total
        pipeline_elapsed = time.perf_counter() - pipeline_start
        PIPELINE_LATENCY.observe(pipeline_elapsed)
        logger.debug(f"⏱️ Pipeline stream async total: {pipeline_elapsed:.2f}s")

    # ==================== Component Methods ====================

    def _transcribe(self, audio_data: bytes) -> Optional[str]:
        """Transcreve áudio para texto (sync wrapper).

        NOTA: Este método NÃO deve ser chamado de contexto async.
        Use _transcribe_async() em vez disso.
        """
        if not self.stt:
            logger.warning("STT não disponível")
            return None

        try:
            with track_component_latency('stt'):
                # Executa método async de forma síncrona
                if hasattr(self.stt, 'transcribe'):
                    if asyncio.iscoroutinefunction(self.stt.transcribe):
                        # Verifica se já existe loop rodando
                        try:
                            loop = asyncio.get_running_loop()
                            # Loop ativo - não podemos usar asyncio.run()
                            # Cria future e roda no loop existente
                            future = asyncio.run_coroutine_threadsafe(
                                self.stt.transcribe(audio_data), loop
                            )
                            text = future.result(timeout=30)
                        except RuntimeError:
                            # Sem loop - usa asyncio.run()
                            text = asyncio.run(self.stt.transcribe(audio_data))
                    else:
                        text = self.stt.transcribe(audio_data)
                else:
                    return None

            if text and len(text.strip()) >= 2:
                return text.strip()
            return None

        except Exception as e:
            logger.error(f"Erro no STT: {e}")
            track_pipeline_error('stt')
            return None

    async def _transcribe_async(self, audio_data: bytes) -> Optional[str]:
        """Transcreve áudio para texto (async)."""
        if not self.stt:
            logger.warning("STT não disponível")
            return None

        try:
            with track_component_latency('stt'):
                text = await self.stt.transcribe(audio_data)

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

    def _synthesize(self, text: str) -> Optional[bytes]:
        """Sintetiza texto em áudio (sync wrapper).

        NOTA: Este método NÃO deve ser chamado de contexto async.
        Use _synthesize_async() em vez disso.
        """
        if not self.tts:
            logger.warning("TTS não disponível")
            return None

        try:
            with track_component_latency('tts'):
                if hasattr(self.tts, 'synthesize'):
                    if asyncio.iscoroutinefunction(self.tts.synthesize):
                        # Verifica se já existe loop rodando
                        try:
                            loop = asyncio.get_running_loop()
                            # Loop ativo - usa run_coroutine_threadsafe
                            future = asyncio.run_coroutine_threadsafe(
                                self.tts.synthesize(text), loop
                            )
                            return future.result(timeout=60)
                        except RuntimeError:
                            # Sem loop - usa asyncio.run()
                            return asyncio.run(self.tts.synthesize(text))
                    else:
                        return self.tts.synthesize(text)
                return None
        except Exception as e:
            logger.error(f"Erro no TTS: {e}")
            track_pipeline_error('tts')
            return None

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

    def _synthesize_stream_sync(self, text: str) -> Generator[bytes, None, None]:
        """Sintetiza texto em áudio com streaming (sync wrapper).

        NOTA: Este método é mantido para compatibilidade, mas prefira
        usar _synthesize_stream_async para streaming real sem bloqueio.
        """
        if not self.tts:
            return

        if hasattr(self.tts, 'synthesize_stream'):
            if asyncio.iscoroutinefunction(self.tts.synthesize_stream):
                # Para async generator em contexto sync, usamos queue
                # para fazer streaming real sem acumular tudo em memória
                import queue
                import threading

                chunk_queue: queue.Queue = queue.Queue()

                def _run_async():
                    async def _stream():
                        try:
                            async for chunk in self.tts.synthesize_stream(text):
                                chunk_queue.put(chunk)
                        except Exception as e:
                            logger.error(f"Erro no TTS streaming: {e}")
                        finally:
                            chunk_queue.put(None)  # Sinaliza fim

                    asyncio.run(_stream())

                # Inicia em thread separada
                thread = threading.Thread(target=_run_async, daemon=True)
                thread.start()

                # Yield chunks assim que disponíveis
                while True:
                    chunk = chunk_queue.get()
                    if chunk is None:
                        break
                    yield chunk

                thread.join(timeout=1)
            else:
                # Sync generator - já é streaming real
                for chunk in self.tts.synthesize_stream(text):
                    yield chunk
        else:
            # Fallback para batch
            audio = self._synthesize(text)
            if audio:
                yield audio

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

    def generate_greeting(self) -> Tuple[str, Optional[bytes]]:
        """Gera saudação inicial."""
        greeting = AGENT_MESSAGES["greeting"]
        audio = self._synthesize(greeting)
        return greeting, audio

    async def generate_greeting_async(self) -> Tuple[str, Optional[bytes]]:
        """Gera saudação inicial (async)."""
        greeting = AGENT_MESSAGES["greeting"]
        audio = await self._synthesize_async(greeting)
        return greeting, audio

    def generate_greeting_stream(self) -> Generator[Tuple[str, bytes], None, None]:
        """Gera saudação inicial com streaming."""
        greeting = AGENT_MESSAGES["greeting"]

        if self.tts and self.tts.supports_streaming:
            for audio_chunk in self._synthesize_stream_sync(greeting):
                yield greeting, audio_chunk
        else:
            audio = self._synthesize(greeting)
            if audio:
                yield greeting, audio

    async def generate_greeting_stream_async(self) -> AsyncGenerator[Tuple[str, bytes], None]:
        """Gera saudação inicial com streaming (async)."""
        greeting = AGENT_MESSAGES["greeting"]

        if self.tts and self.tts.supports_streaming:
            async for audio_chunk in self._synthesize_stream_async(greeting):
                yield greeting, audio_chunk
        else:
            audio = await self._synthesize_async(greeting)
            if audio:
                yield greeting, audio

    def generate_error_response(self) -> Tuple[str, Optional[bytes]]:
        """Gera resposta de erro."""
        error_msg = AGENT_MESSAGES["error"]
        audio = self._synthesize(error_msg)
        return error_msg, audio

    # ==================== Utils ====================

    def reset(self):
        """Reseta estado da conversa."""
        if self.llm:
            self.llm.reset_conversation()
        logger.info("🔄 Pipeline resetado")

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


def create_pipeline() -> ConversationPipeline:
    """
    Factory síncrona para criar pipeline.

    Returns:
        ConversationPipeline com providers inicializados.
    """
    return ConversationPipeline(auto_init=True)
