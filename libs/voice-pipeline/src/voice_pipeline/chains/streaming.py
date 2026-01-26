"""
StreamingChain for optimized end-to-end streaming.

Provides pipelines optimized for minimal latency by streaming
between components as early as possible.

This implements sentence-level streaming between LLM and TTS:
- LLM generates tokens incrementally
- SentenceStreamer buffers tokens and emits complete sentences
- TTS synthesizes each sentence immediately (in parallel)

This reduces TTFA (Time to First Audio) from ~2-3s to ~0.6-0.8s.

With Streaming ASR (e.g., Deepgram):
- ASR provides partial transcriptions as audio is received
- LLM can start generating before ASR is complete
- Additional ~200-300ms latency reduction

Reference:
- https://arxiv.org/html/2508.04721v1 (Low-Latency Voice Agents)
- https://github.com/pipecat-ai/pipecat (SentenceAggregator pattern)
"""

import asyncio
import logging
from typing import AsyncIterator, Optional

from voice_pipeline.callbacks.context import (
    emit_asr_end,
    emit_asr_start,
    emit_llm_end,
    emit_llm_start,
    emit_llm_token,
    emit_tts_chunk,
    emit_tts_end,
    emit_tts_start,
)
from voice_pipeline.interfaces import (
    ASRInterface,
    AudioChunk,
    InterruptionStrategy,
    LLMChunk,
    LLMInterface,
    RAGInterface,
    TTSInterface,
    TranscriptionResult,
    TurnTakingController,
)
from voice_pipeline.chains.base_voice_chain import BaseVoiceChain
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable, ensure_config
from voice_pipeline.streaming import SentenceStreamer, SentenceStreamerConfig
from voice_pipeline.streaming.metrics import StreamingMetrics
from voice_pipeline.streaming.strategy import StreamingStrategy
from voice_pipeline.streaming.sentence_strategy import SentenceStreamingStrategy

logger = logging.getLogger(__name__)




class StreamingVoiceChain(BaseVoiceChain):
    """
    Voice chain optimized for streaming with minimal latency.

    This chain starts TTS synthesis as soon as complete sentences
    are available from the LLM, rather than waiting for the full
    response. This significantly reduces time-to-first-audio.

    Architecture (Batch ASR):
        Audio → ASR → LLM (streaming) → Sentence Buffer → TTS (streaming) → Audio
                            ↓
                     [sentence ready]
                            ↓
                      TTS starts

    Architecture (Streaming ASR - e.g., Deepgram):
        Audio stream → ASR (streaming) → [partial text] → LLM starts early
                                              ↓
                              LLM (streaming) → Sentence Buffer → TTS → Audio

    Example:
        >>> chain = StreamingVoiceChain(
        ...     asr=whisper_asr,
        ...     llm=ollama_llm,
        ...     tts=piper_tts,
        ...     min_sentence_chars=20,
        ...     auto_warmup=True,  # Eliminate cold start
        ... )
        >>>
        >>> # Audio arrives as soon as first sentence is ready
        >>> async for audio in chain.astream(audio_bytes):
        ...     play(audio)  # Low latency!
        >>>
        >>> # With Deepgram streaming ASR
        >>> chain = StreamingVoiceChain(
        ...     asr=deepgram_asr,  # Real-time ASR
        ...     llm=ollama_llm,
        ...     tts=kokoro_tts,
        ...     use_streaming_asr=True,  # Enable streaming ASR
        ... )
    """

    name: str = "StreamingVoiceChain"

    _QUEUE_TIMEOUT_S: float = 30.0
    """Safety timeout for queue operations in seconds."""

    _ASR_CHUNK_SIZE: int = 4000
    """Size of audio chunks sent to streaming ASR (~250ms at 16kHz)."""

    def __init__(
        self,
        asr: ASRInterface,
        llm: LLMInterface,
        tts: TTSInterface,
        rag: Optional[RAGInterface] = None,
        rag_k: int = 5,
        system_prompt: Optional[str] = None,
        language: Optional[str] = None,
        tts_voice: Optional[str] = None,
        llm_temperature: float = 0.7,
        min_sentence_chars: int = 20,
        max_sentence_chars: int = 200,
        sentence_end_chars: Optional[list[str]] = None,
        auto_warmup: bool = True,
        use_streaming_asr: bool = True,
        streaming_asr_min_words: int = 3,
        max_messages: int = 20,
        turn_taking_controller: Optional[TurnTakingController] = None,
        streaming_strategy: Optional[StreamingStrategy] = None,
        interruption_strategy: Optional[InterruptionStrategy] = None,
    ):
        """
        Initialize the streaming chain.

        Args:
            asr: ASR provider.
            llm: LLM provider.
            tts: TTS provider.
            rag: Optional RAG provider for knowledge-augmented responses.
            rag_k: Number of documents to retrieve for RAG (default: 5).
            system_prompt: System prompt for the LLM.
            language: Language code for ASR.
            tts_voice: Voice identifier for TTS.
            llm_temperature: LLM sampling temperature.
            min_sentence_chars: Minimum characters before emitting sentence.
            max_sentence_chars: Maximum characters before forcing emission.
            sentence_end_chars: Characters that end sentences.
            auto_warmup: If True, automatically warm up TTS on connect().
                        This eliminates cold-start latency on first synthesis.
                        Default: True (recommended for production).
            use_streaming_asr: If True, use streaming ASR when available.
                              This starts LLM before ASR completes, reducing
                              latency by ~200-300ms. Default: True.
            streaming_asr_min_words: Minimum words before starting LLM
                                    (only for streaming ASR). Default: 3.
            max_messages: Maximum conversation messages to retain in history.
                         Older messages are trimmed. Default: 20.
                         Set to 0 for unlimited (not recommended).
            turn_taking_controller: Optional pluggable turn-taking strategy.
                                   Controls when user's turn ends. If None,
                                   the chain does not manage turn-taking
                                   (caller is responsible).
            streaming_strategy: Optional pluggable streaming strategy.
                               Controls how LLM tokens are buffered and
                               emitted to TTS (word, clause, or sentence
                               granularity). If None, defaults to sentence-level
                               streaming using SentenceStreamer config.
            interruption_strategy: Optional pluggable interruption strategy.
                                  Controls how the chain responds to user
                                  speech during agent output (immediate,
                                  graceful, or backchannel-aware). If None,
                                  the chain uses the existing interrupt()
                                  behavior (caller-managed).
        """
        super().__init__(
            asr=asr,
            llm=llm,
            tts=tts,
            system_prompt=system_prompt,
            language=language,
            tts_voice=tts_voice,
            llm_temperature=llm_temperature,
            max_messages=max_messages,
        )
        self.rag = rag
        self.rag_k = rag_k
        self.auto_warmup = auto_warmup
        self.use_streaming_asr = use_streaming_asr
        self.streaming_asr_min_words = streaming_asr_min_words
        self.turn_taking_controller = turn_taking_controller
        self.streaming_strategy = streaming_strategy
        self.interruption_strategy = interruption_strategy

        # Sentence streamer config
        self.streamer_config = SentenceStreamerConfig(
            min_chars=min_sentence_chars,
            max_chars=max_sentence_chars,
            sentence_end_chars=sentence_end_chars or [".", "!", "?", "\n"],
        )

        self._interrupted: bool = False

        # Metrics from last run
        self.metrics: Optional[StreamingMetrics] = None

        # Warmup metrics
        self.warmup_time_ms: Optional[float] = None
        self.llm_warmup_time_ms: Optional[float] = None

        # Track if streaming ASR is being used
        self._using_streaming_asr: bool = False

    def _get_strategy(self) -> StreamingStrategy:
        """Get the streaming strategy to use.

        Returns the configured strategy if set, otherwise creates
        a default SentenceStreamingStrategy from streamer_config.
        The strategy is reset before returning to ensure clean state.
        """
        if self.streaming_strategy is not None:
            self.streaming_strategy.reset()
            return self.streaming_strategy
        return SentenceStreamingStrategy(self.streamer_config)

    async def connect(self) -> None:
        """Connect all providers and optionally warm up TTS.

        If auto_warmup is enabled (default), this method will also
        call tts.warmup() to eliminate cold-start latency.

        The warmup time is stored in self.warmup_time_ms.
        """
        await self.asr.connect()
        await self.llm.connect()
        await self.tts.connect()

        # Connect turn-taking controller (may load models)
        if self.turn_taking_controller is not None:
            await self.turn_taking_controller.connect()

        # Warm up TTS to eliminate cold-start latency
        from voice_pipeline.interfaces import Warmable
        if self.auto_warmup and isinstance(self.tts, Warmable):
            self.warmup_time_ms = await self.tts.warmup()
            logger.info(f"TTS warmed up in {self.warmup_time_ms:.1f}ms")

        # Warm up LLM to eliminate cold-start latency
        if self.auto_warmup and isinstance(self.llm, Warmable):
            self.llm_warmup_time_ms = await self.llm.warmup()
            logger.info(f"LLM warmed up in {self.llm_warmup_time_ms:.1f}ms")

    async def disconnect(self) -> None:
        """Disconnect all providers."""
        if hasattr(self.asr, 'disconnect'):
            await self.asr.disconnect()
        if hasattr(self.llm, 'disconnect'):
            await self.llm.disconnect()
        if hasattr(self.tts, 'disconnect'):
            await self.tts.disconnect()
        if self.turn_taking_controller is not None:
            await self.turn_taking_controller.disconnect()

    async def __aenter__(self):
        """Enter async context: connect all providers."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context: disconnect all providers."""
        await self.disconnect()
        return False

    def interrupt(self) -> None:
        """Interrupt current response (barge-in).

        Sets an interruption flag that is checked by the LLM producer
        and TTS consumer loops, causing them to stop processing.
        The flag is automatically reset at the start of each astream() call.
        """
        self._interrupted = True
        logger.info("Interrupt requested")

    async def _augment_with_rag(self, user_text: str) -> str:
        """Augment user text with RAG context if available.

        Args:
            user_text: Original user text.

        Returns:
            Augmented text with RAG context, or original if no RAG.
        """
        if self.rag is None:
            return user_text

        try:
            context, results = await self.rag.query(user_text, k=self.rag_k)
            if context:
                augmented = self.rag.build_rag_prompt(
                    query=user_text,
                    context=context,
                )
                logger.info(f"RAG: Retrieved {len(results)} documents")
                return augmented
        except Exception as e:
            logger.warning(f"RAG error (falling back to direct): {e}")

        return user_text

    async def astream(
        self,
        input: bytes,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[AudioChunk]:
        """
        Process audio with optimized streaming.

        Uses a sentence buffer to start TTS as soon as complete
        sentences are available from the LLM.

        If use_streaming_asr=True and the ASR provider supports real-time
        streaming (like Deepgram), the pipeline will start LLM generation
        before ASR is complete, reducing latency by ~200-300ms.

        Metrics are collected and available via self.metrics after completion.
        """
        config = ensure_config(config)

        # Reset interrupt flag for new stream
        self._interrupted = False

        # Initialize metrics
        self.metrics = StreamingMetrics()
        self.metrics.start()

        # Check if we should use streaming ASR
        self._using_streaming_asr = (
            self.use_streaming_asr and self.asr.supports_streaming_input
        )

        if self._using_streaming_asr:
            logger.info("Using streaming ASR mode")

        try:
            # Step 1: ASR
            self.metrics.mark_asr_start()
            await emit_asr_start(input)

            asr_config = RunnableConfig(
                configurable={"language": self.language},
            ).merge(config)

            # Use streaming ASR if available and enabled
            if self._using_streaming_asr:
                async for audio_chunk in self._stream_with_streaming_asr(
                    input, asr_config, config
                ):
                    yield audio_chunk
            else:
                # Standard batch ASR mode
                transcription = await self.asr.ainvoke(input, asr_config)
                await emit_asr_end(transcription)
                self.metrics.mark_asr_end()

                if not transcription.text.strip():
                    return

                logger.info(f"ASR: {transcription.text}")

                # Augment with RAG context if available
                user_content = await self._augment_with_rag(transcription.text)

                # Add user message
                self._add_message("user", user_content)

                # Step 2: LLM with sentence streaming
                await emit_llm_start(self._messages)

                llm_config = RunnableConfig(
                    configurable={
                        "system_prompt": self.system_prompt,
                        "temperature": self.llm_temperature,
                    },
                ).merge(config)

                tts_config = RunnableConfig(
                    configurable={"voice": self.tts_voice},
                ).merge(config)

                # Stream LLM -> Sentence Buffer -> TTS
                async for audio_chunk in self._stream_with_buffer(llm_config, tts_config):
                    yield audio_chunk

        finally:
            self.metrics.end()
            logger.info(f"Streaming metrics: {self.metrics}")

    async def _stream_with_streaming_asr(
        self,
        audio_input: bytes,
        asr_config: RunnableConfig,
        config: RunnableConfig,
    ) -> AsyncIterator[AudioChunk]:
        """
        Stream with real-time ASR for lower latency.

        With streaming ASR (like Deepgram), we can start the LLM
        as soon as we have enough partial transcription, rather than
        waiting for the complete transcription.

        Flow:
        1. Start ASR streaming
        2. Collect partial transcriptions
        3. When we have enough words, start LLM
        4. Continue collecting ASR updates
        5. LLM generates response based on partial input
        6. TTS synthesizes

        This can reduce latency by ~200-300ms compared to batch ASR.
        """
        llm_config = RunnableConfig(
            configurable={
                "system_prompt": self.system_prompt,
                "temperature": self.llm_temperature,
            },
        ).merge(config)

        tts_config = RunnableConfig(
            configurable={"voice": self.tts_voice},
        ).merge(config)

        # Track transcription state
        partial_text = ""
        final_text = ""
        llm_started = False
        llm_task: Optional[asyncio.Task] = None

        # Queue for partial/final transcriptions
        transcription_queue: asyncio.Queue[Optional[TranscriptionResult]] = asyncio.Queue()

        # Queue for sentences (from LLM)
        sentence_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        async def asr_producer():
            """Stream audio through ASR and collect transcriptions."""
            nonlocal partial_text, final_text

            async def audio_generator():
                # Send audio in chunks for streaming
                chunk_size = self._ASR_CHUNK_SIZE
                for i in range(0, len(audio_input), chunk_size):
                    yield audio_input[i:i + chunk_size]
                    await asyncio.sleep(0.01)  # Small delay to simulate real-time

            try:
                async for result in self.asr.astream(audio_generator(), asr_config):
                    if result.is_final:
                        final_text += result.text + " "
                    else:
                        partial_text = result.text

                    await transcription_queue.put(result)

                # Signal completion
                await transcription_queue.put(None)
                await emit_asr_end(TranscriptionResult(
                    text=final_text.strip() or partial_text,
                    is_final=True
                ))
                self.metrics.mark_asr_end()

            except Exception as e:
                logger.exception(f"ASR streaming error: {e}")
                await transcription_queue.put(None)

        async def llm_producer(input_text: str):
            """Produce sentences from LLM stream."""
            response_text = ""

            self.metrics.mark_llm_start()
            strategy = self._get_strategy()

            async for chunk in self.llm.astream(self._messages, llm_config):
                if self._interrupted:
                    logger.info("LLM producer interrupted")
                    break
                token = chunk.text if isinstance(chunk, LLMChunk) else str(chunk)
                response_text += token
                await emit_llm_token(token)

                # Mark first token
                self.metrics.mark_first_token()
                self.metrics.add_token()

                # Check for complete chunks (sentences/clauses/words)
                chunks = strategy.process(token)
                for text_chunk in chunks:
                    self.metrics.add_sentence()
                    await sentence_queue.put(text_chunk)

            # Flush remaining text
            remaining = strategy.flush()
            if remaining:
                self.metrics.add_sentence()
                await sentence_queue.put(remaining)

            # Signal completion
            await sentence_queue.put(None)
            await emit_llm_end(response_text)
            self.metrics.mark_llm_end()

            # Add assistant message
            self._add_message("assistant", response_text)
            logger.info(f"LLM response: {response_text[:100]}...")

        async def tts_consumer():
            """Consume sentences and produce audio."""
            self.metrics.mark_tts_start()
            tts_started = False

            while True:
                try:
                    sentence = await asyncio.wait_for(
                        sentence_queue.get(),
                        timeout=self._QUEUE_TIMEOUT_S,
                    )
                except asyncio.TimeoutError:
                    logger.warning("TTS consumer timeout")
                    break

                if sentence is None:
                    break

                if self._interrupted:
                    logger.info("TTS consumer interrupted")
                    break

                if not sentence.strip():
                    continue

                if not tts_started:
                    await emit_tts_start(sentence)
                    tts_started = True

                logger.debug(f"TTS synthesizing: {sentence[:50]}...")

                async for audio_chunk in self.tts.astream(sentence, tts_config):
                    self.metrics.mark_first_audio()
                    self.metrics.add_audio_chunk(
                        len(audio_chunk.data),
                        audio_chunk.sample_rate,
                    )

                    await emit_tts_chunk(audio_chunk)
                    yield audio_chunk

            if tts_started:
                await emit_tts_end()

            self.metrics.mark_tts_end()

        # Start ASR streaming
        asr_task = asyncio.create_task(asr_producer())

        try:
            # Process transcriptions as they arrive
            while True:
                try:
                    result = await asyncio.wait_for(
                        transcription_queue.get(),
                        timeout=self._QUEUE_TIMEOUT_S,
                    )
                except asyncio.TimeoutError:
                    break

                if result is None:
                    break

                # Check if we should start LLM
                current_text = final_text + partial_text
                word_count = len(current_text.split())

                if not llm_started and word_count >= self.streaming_asr_min_words:
                    # Start LLM with partial transcription
                    llm_started = True
                    user_text = current_text.strip()

                    logger.info(f"Starting LLM with partial ASR: '{user_text}'")

                    # Augment with RAG if available
                    user_content = await self._augment_with_rag(user_text)
                    self._add_message("user", user_content)
                    await emit_llm_start(self._messages)

                    llm_task = asyncio.create_task(llm_producer(user_text))

            # If LLM wasn't started (short utterance), start it now
            if not llm_started:
                user_text = (final_text + partial_text).strip()
                if user_text:
                    # Augment with RAG if available
                    user_content = await self._augment_with_rag(user_text)
                    self._add_message("user", user_content)
                    await emit_llm_start(self._messages)
                    llm_task = asyncio.create_task(llm_producer(user_text))
                else:
                    return

            # Consume TTS output
            async for audio_chunk in tts_consumer():
                yield audio_chunk

        finally:
            # Ensure tasks complete
            await asr_task
            if llm_task:
                await llm_task

    async def _stream_with_buffer(
        self,
        llm_config: RunnableConfig,
        tts_config: RunnableConfig,
    ) -> AsyncIterator[AudioChunk]:
        """
        Stream LLM response through sentence buffer to TTS.

        Uses asyncio.Queue to connect LLM streaming to TTS processing.
        This is the producer-consumer pattern for low-latency streaming.
        """
        sentence_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        response_text = ""
        tts_started = False
        metrics = self.metrics  # Capture for closures

        async def llm_producer():
            """Produce sentences from LLM stream."""
            nonlocal response_text

            metrics.mark_llm_start()
            strategy = self._get_strategy()

            async for chunk in self.llm.astream(self._messages, llm_config):
                if self._interrupted:
                    logger.info("LLM producer interrupted")
                    break
                token = chunk.text if isinstance(chunk, LLMChunk) else str(chunk)
                response_text += token
                await emit_llm_token(token)

                # Mark first token
                metrics.mark_first_token()
                metrics.add_token()

                # Check for complete chunks (sentences/clauses/words)
                chunks = strategy.process(token)
                for text_chunk in chunks:
                    metrics.add_sentence()
                    await sentence_queue.put(text_chunk)

            # Flush remaining text
            remaining = strategy.flush()
            if remaining:
                metrics.add_sentence()
                await sentence_queue.put(remaining)

            # Signal completion
            await sentence_queue.put(None)
            await emit_llm_end(response_text)
            metrics.mark_llm_end()

            # Add assistant message
            self._add_message("assistant", response_text)
            logger.info(f"LLM response: {response_text[:100]}...")

        async def tts_consumer():
            """Consume sentences and produce audio."""
            nonlocal tts_started

            metrics.mark_tts_start()

            while True:
                try:
                    sentence = await asyncio.wait_for(
                        sentence_queue.get(),
                        timeout=self._QUEUE_TIMEOUT_S,
                    )
                except asyncio.TimeoutError:
                    logger.warning("TTS consumer timeout waiting for sentence")
                    break

                if sentence is None:
                    break

                if self._interrupted:
                    logger.info("TTS consumer interrupted")
                    break

                if not sentence.strip():
                    continue

                if not tts_started:
                    await emit_tts_start(sentence)
                    tts_started = True

                logger.debug(f"TTS synthesizing: {sentence[:50]}...")

                async for audio_chunk in self.tts.astream(sentence, tts_config):
                    # Mark first audio
                    metrics.mark_first_audio()
                    metrics.add_audio_chunk(
                        len(audio_chunk.data),
                        audio_chunk.sample_rate,
                    )

                    await emit_tts_chunk(audio_chunk)
                    yield audio_chunk

            if tts_started:
                await emit_tts_end()

            metrics.mark_tts_end()

        # Start producer in background
        producer_task = asyncio.create_task(llm_producer())

        try:
            # Yield audio from consumer
            async for audio_chunk in tts_consumer():
                yield audio_chunk
        finally:
            # Ensure producer completes
            await producer_task


class ParallelStreamingChain(BaseVoiceChain):
    """
    Chain that processes LLM and TTS in parallel.

    Similar to StreamingVoiceChain but uses parallel tasks
    for even lower latency in some scenarios.
    """

    name: str = "ParallelStreamingChain"

    def __init__(
        self,
        asr: ASRInterface,
        llm: LLMInterface,
        tts: TTSInterface,
        system_prompt: Optional[str] = None,
        language: Optional[str] = None,
        tts_voice: Optional[str] = None,
        buffer_size: int = 3,
        max_messages: int = 20,
    ):
        """
        Initialize the parallel streaming chain.

        Args:
            asr: ASR provider.
            llm: LLM provider.
            tts: TTS provider.
            system_prompt: System prompt.
            language: Language code.
            tts_voice: TTS voice.
            buffer_size: Number of sentences to buffer ahead.
            max_messages: Maximum conversation messages to retain in history.
                         Older messages are trimmed. Default: 20.
                         Set to 0 for unlimited (not recommended).
        """
        super().__init__(
            asr=asr,
            llm=llm,
            tts=tts,
            system_prompt=system_prompt,
            language=language,
            tts_voice=tts_voice,
            max_messages=max_messages,
        )
        self.buffer_size = buffer_size

    async def astream(
        self,
        input: bytes,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[AudioChunk]:
        """
        Process audio with parallel streaming.

        Uses bounded queue to control memory usage while
        allowing LLM and TTS to run in parallel.
        """
        config = ensure_config(config)

        # ASR first (cannot parallelize)
        await emit_asr_start(input)

        asr_config = RunnableConfig(
            configurable={"language": self.language},
        ).merge(config)

        transcription = await self.asr.ainvoke(input, asr_config)
        await emit_asr_end(transcription)

        if not transcription.text.strip():
            return

        self._add_message("user", transcription.text)

        # Parallel LLM -> TTS
        await emit_llm_start(self._messages)

        llm_config = RunnableConfig(
            configurable={
                "system_prompt": self.system_prompt,
            },
        ).merge(config)

        tts_config = RunnableConfig(
            configurable={"voice": self.tts_voice},
        ).merge(config)

        # Use bounded queue for backpressure
        sentence_queue: asyncio.Queue[Optional[str]] = asyncio.Queue(
            maxsize=self.buffer_size
        )
        response_text = ""

        async def producer():
            nonlocal response_text
            buffer = ""
            sentence_ends = {".", "!", "?", "\n"}

            async for chunk in self.llm.astream(self._messages, llm_config):
                token = chunk.text if isinstance(chunk, LLMChunk) else str(chunk)
                response_text += token
                await emit_llm_token(token)

                buffer += token

                # Check for sentence boundary
                for i, char in enumerate(buffer):
                    if char in sentence_ends and i > 10:  # Min length
                        sentence = buffer[: i + 1].strip()
                        if sentence:
                            await sentence_queue.put(sentence)
                        buffer = buffer[i + 1 :]
                        break

            # Flush remaining
            if buffer.strip():
                await sentence_queue.put(buffer.strip())

            await sentence_queue.put(None)
            await emit_llm_end(response_text)
            self._add_message("assistant", response_text)

        # Start producer
        producer_task = asyncio.create_task(producer())
        tts_started = False

        try:
            while True:
                sentence = await sentence_queue.get()
                if sentence is None:
                    break

                if not tts_started:
                    await emit_tts_start(sentence)
                    tts_started = True

                async for audio in self.tts.astream(sentence, tts_config):
                    yield audio

            if tts_started:
                await emit_tts_end()

        finally:
            await producer_task
