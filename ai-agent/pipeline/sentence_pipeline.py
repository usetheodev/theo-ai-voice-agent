"""
Sentence-level Streaming Pipeline: LLM → TTS

Este módulo implementa um pipeline onde o TTS começa a sintetizar
assim que o LLM gera a primeira frase, sem esperar todo o texto.

Princípios aplicados:
- SRP: Classe focada apenas na orquestração LLM→TTS
- OCP: Extensível via interfaces LLMProvider/TTSProvider
- DIP: Depende de abstrações, não implementações concretas
- KISS: API simples com async generator
- DRY: Reutiliza providers existentes
- YAGNI: Apenas funcionalidade necessária

Uso:
    pipeline = SentencePipeline(llm, tts)
    async for sentence, audio_chunk in pipeline.process_streaming(user_text):
        send_to_client(sentence, audio_chunk)
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from providers.llm import LLMProvider
    from providers.tts import TTSProvider

logger = logging.getLogger("ai-agent.sentence-pipeline")


@dataclass
class PipelineMetrics:
    """Métricas do pipeline para observabilidade."""

    sentences_generated: int = 0
    audio_chunks_produced: int = 0
    first_audio_latency_ms: float = 0.0
    total_latency_ms: float = 0.0


class SentencePipeline:
    """
    Pipeline de streaming sentence-level: LLM → TTS em paralelo.

    O LLM gera frases em streaming e cada frase é imediatamente
    enviada para o TTS, que retorna chunks de áudio assim que prontos.

    Isso reduz a latência percebida pois o usuário começa a ouvir
    a resposta enquanto o LLM ainda está gerando as próximas frases.

    Arquitetura:
        [LLM] --sentences--> [Queue] --sentences--> [TTS] --audio--> [Output]
                              (async)

    Attributes:
        llm: Provedor de LLM para geração de texto
        tts: Provedor de TTS para síntese de áudio
        queue_size: Tamanho máximo da fila de sentenças (backpressure)
    """

    def __init__(
        self,
        llm: "LLMProvider",
        tts: "TTSProvider",
        queue_size: int = 3,
    ):
        """
        Inicializa o pipeline.

        Args:
            llm: Provedor de LLM (deve implementar generate_sentences)
            tts: Provedor de TTS (deve implementar synthesize_stream)
            queue_size: Tamanho máximo da fila de sentenças (default: 3)
                       Limita quantas frases podem ser geradas antes do TTS processar.
                       Valor baixo = menor uso de memória, mas pode causar stalls.
        """
        self._llm = llm
        self._tts = tts
        self._queue_size = queue_size
        self._metrics = PipelineMetrics()

    @property
    def metrics(self) -> PipelineMetrics:
        """Retorna métricas do último processamento."""
        return self._metrics

    async def process_streaming(
        self,
        user_text: str,
    ) -> AsyncGenerator[Tuple[str, bytes], None]:
        """
        Processa texto do usuário e gera áudio em streaming sentence-level.

        O LLM gera frases que são imediatamente sintetizadas pelo TTS.
        Cada yield retorna (sentence, audio_chunk).

        Args:
            user_text: Texto transcrito do usuário

        Yields:
            Tuple[str, bytes]: (sentença, chunk de áudio PCM 8kHz)

        Example:
            async for sentence, audio in pipeline.process_streaming("Olá"):
                print(f"Sentença: {sentence}")
                play_audio(audio)
        """
        self._metrics = PipelineMetrics()
        start_time = time.perf_counter()
        first_audio_time: Optional[float] = None

        # Fila para comunicação LLM → TTS (producer-consumer)
        sentence_queue: asyncio.Queue[Optional[str]] = asyncio.Queue(
            maxsize=self._queue_size
        )

        # Task do produtor (LLM gera sentenças)
        producer_task = asyncio.create_task(
            self._produce_sentences(user_text, sentence_queue)
        )

        try:
            # Consumidor (TTS sintetiza e yield)
            while True:
                # Aguarda próxima sentença (com timeout para detectar problemas)
                try:
                    sentence = await asyncio.wait_for(
                        sentence_queue.get(),
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("Timeout aguardando sentença do LLM")
                    break

                # None sinaliza fim das sentenças
                if sentence is None:
                    break

                self._metrics.sentences_generated += 1
                logger.debug(f"📝 Sentença {self._metrics.sentences_generated}: {sentence[:50]}...")

                # Sintetiza sentença e yield chunks imediatamente
                async for audio_chunk in self._synthesize_sentence(sentence):
                    # Registra latência do primeiro áudio
                    if first_audio_time is None:
                        first_audio_time = time.perf_counter()
                        self._metrics.first_audio_latency_ms = (
                            (first_audio_time - start_time) * 1000
                        )
                        logger.info(
                            f"⚡ Primeiro áudio em {self._metrics.first_audio_latency_ms:.0f}ms"
                        )

                    self._metrics.audio_chunks_produced += 1
                    yield sentence, audio_chunk

        finally:
            # Garante que o produtor é cancelado se consumidor parar
            if not producer_task.done():
                producer_task.cancel()
                try:
                    await producer_task
                except asyncio.CancelledError:
                    pass

            # Registra métricas finais
            self._metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                f"✅ Pipeline: {self._metrics.sentences_generated} sentenças, "
                f"{self._metrics.audio_chunks_produced} chunks, "
                f"total {self._metrics.total_latency_ms:.0f}ms"
            )

    async def _produce_sentences(
        self,
        user_text: str,
        queue: asyncio.Queue,
    ) -> None:
        """
        Produtor: gera sentenças do LLM e coloca na fila.

        Roda em paralelo com o consumidor (TTS).
        """
        try:
            loop = asyncio.get_event_loop()

            # Executa gerador síncrono do LLM em thread
            def _generate():
                sentences = []
                for sentence in self._llm.generate_sentences(user_text):
                    sentences.append(sentence)
                return sentences

            sentences = await loop.run_in_executor(None, _generate)

            # Coloca cada sentença na fila
            for sentence in sentences:
                await queue.put(sentence)
                logger.debug(f"📤 Sentença enfileirada: {sentence[:30]}...")

        except Exception as e:
            logger.error(f"Erro no produtor LLM: {e}")

        finally:
            # Sinaliza fim das sentenças
            await queue.put(None)

    async def _synthesize_sentence(
        self,
        sentence: str,
    ) -> AsyncGenerator[bytes, None]:
        """
        Sintetiza uma sentença e yield chunks de áudio.

        Args:
            sentence: Texto da sentença para sintetizar

        Yields:
            bytes: Chunks de áudio PCM 8kHz
        """
        try:
            # Verifica se TTS suporta streaming real
            if hasattr(self._tts, 'synthesize_stream'):
                async for chunk in self._tts.synthesize_stream(sentence):
                    if chunk and len(chunk) > 0:
                        yield chunk
            else:
                # Fallback: sintetiza tudo e divide em chunks
                audio = await self._tts.synthesize(sentence)
                if audio:
                    chunk_size = 1600  # ~100ms a 8kHz
                    for i in range(0, len(audio), chunk_size):
                        yield audio[i:i + chunk_size]

        except Exception as e:
            logger.error(f"Erro na síntese: {e}")


class SentencePipelineFactory:
    """
    Factory para criar SentencePipeline com providers apropriados.

    Segue o padrão Factory para encapsular a criação de dependências.
    """

    @staticmethod
    async def create(
        llm: Optional["LLMProvider"] = None,
        tts: Optional["TTSProvider"] = None,
    ) -> SentencePipeline:
        """
        Cria pipeline com providers fornecidos ou defaults.

        Args:
            llm: LLM provider (opcional, cria default se não fornecido)
            tts: TTS provider (opcional, cria default se não fornecido)

        Returns:
            SentencePipeline configurado e pronto para uso
        """
        from providers.llm import create_llm_provider
        from providers.tts import create_tts_provider

        if llm is None:
            llm = create_llm_provider()

        if tts is None:
            tts = await create_tts_provider()

        return SentencePipeline(llm=llm, tts=tts)
