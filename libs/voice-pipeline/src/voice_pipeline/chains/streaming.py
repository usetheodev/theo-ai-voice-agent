"""
StreamingChain for optimized end-to-end streaming.

Provides pipelines optimized for minimal latency by streaming
between components as early as possible.
"""

import asyncio
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
    LLMChunk,
    LLMInterface,
    TTSInterface,
)
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable, ensure_config
from voice_pipeline.streaming import SentenceStreamer, SentenceStreamerConfig


class StreamingVoiceChain(VoiceRunnable[bytes, AudioChunk]):
    """
    Voice chain optimized for streaming with minimal latency.

    This chain starts TTS synthesis as soon as complete sentences
    are available from the LLM, rather than waiting for the full
    response. This significantly reduces time-to-first-audio.

    Architecture:
        Audio → ASR → LLM (streaming) → Sentence Buffer → TTS (streaming) → Audio
                            ↓
                     [sentence ready]
                            ↓
                      TTS starts

    Example:
        >>> chain = StreamingVoiceChain(
        ...     asr=whisper_asr,
        ...     llm=ollama_llm,
        ...     tts=piper_tts,
        ...     min_sentence_chars=20,
        ... )
        >>>
        >>> # Audio arrives as soon as first sentence is ready
        >>> async for audio in chain.astream(audio_bytes):
        ...     play(audio)  # Low latency!
    """

    name: str = "StreamingVoiceChain"

    def __init__(
        self,
        asr: ASRInterface,
        llm: LLMInterface,
        tts: TTSInterface,
        system_prompt: Optional[str] = None,
        language: Optional[str] = None,
        tts_voice: Optional[str] = None,
        llm_temperature: float = 0.7,
        min_sentence_chars: int = 20,
        max_sentence_chars: int = 200,
        sentence_end_chars: Optional[list[str]] = None,
    ):
        """
        Initialize the streaming chain.

        Args:
            asr: ASR provider.
            llm: LLM provider.
            tts: TTS provider.
            system_prompt: System prompt for the LLM.
            language: Language code for ASR.
            tts_voice: Voice identifier for TTS.
            llm_temperature: LLM sampling temperature.
            min_sentence_chars: Minimum characters before emitting sentence.
            max_sentence_chars: Maximum characters before forcing emission.
            sentence_end_chars: Characters that end sentences.
        """
        self.asr = asr
        self.llm = llm
        self.tts = tts
        self.system_prompt = system_prompt
        self.language = language
        self.tts_voice = tts_voice
        self.llm_temperature = llm_temperature

        # Sentence streamer config
        self.streamer_config = SentenceStreamerConfig(
            min_chars=min_sentence_chars,
            max_chars=max_sentence_chars,
            sentence_end_chars=sentence_end_chars or [".", "!", "?", "\n"],
        )

        self._messages: list[dict[str, str]] = []

    def reset(self) -> None:
        """Reset conversation history."""
        self._messages.clear()

    async def ainvoke(
        self,
        input: bytes,
        config: Optional[RunnableConfig] = None,
    ) -> AudioChunk:
        """Process audio and return response."""
        chunks: list[bytes] = []
        async for chunk in self.astream(input, config):
            chunks.append(chunk.data)

        return AudioChunk(
            data=b"".join(chunks),
            sample_rate=24000,
        )

    async def astream(
        self,
        input: bytes,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[AudioChunk]:
        """
        Process audio with optimized streaming.

        Uses a sentence buffer to start TTS as soon as complete
        sentences are available from the LLM.
        """
        config = ensure_config(config)

        # Step 1: ASR
        await emit_asr_start(input)

        asr_config = RunnableConfig(
            configurable={"language": self.language},
        ).merge(config)

        transcription = await self.asr.ainvoke(input, asr_config)
        await emit_asr_end(transcription)

        if not transcription.text.strip():
            return

        # Add user message
        self._messages.append({"role": "user", "content": transcription.text})

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

    async def _stream_with_buffer(
        self,
        llm_config: RunnableConfig,
        tts_config: RunnableConfig,
    ) -> AsyncIterator[AudioChunk]:
        """
        Stream LLM response through sentence buffer to TTS.

        Uses asyncio.Queue to connect LLM streaming to TTS processing.
        """
        sentence_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        response_text = ""
        tts_started = False

        async def llm_producer():
            """Produce sentences from LLM stream."""
            nonlocal response_text

            streamer = SentenceStreamer(self.streamer_config)
            text_buffer = ""

            async for chunk in self.llm.astream(self._messages, llm_config):
                token = chunk.text if isinstance(chunk, LLMChunk) else str(chunk)
                response_text += token
                text_buffer += token
                await emit_llm_token(token)

                # Check for complete sentences
                sentences = streamer.process(token)
                for sentence in sentences:
                    await sentence_queue.put(sentence)

            # Flush remaining text
            remaining = streamer.flush()
            if remaining:
                await sentence_queue.put(remaining)

            # Signal completion
            await sentence_queue.put(None)
            await emit_llm_end(response_text)

            # Add assistant message
            self._messages.append({"role": "assistant", "content": response_text})

        async def tts_consumer():
            """Consume sentences and produce audio."""
            nonlocal tts_started

            while True:
                sentence = await sentence_queue.get()

                if sentence is None:
                    break

                if not sentence.strip():
                    continue

                if not tts_started:
                    await emit_tts_start(sentence)
                    tts_started = True

                async for audio_chunk in self.tts.astream(sentence, tts_config):
                    await emit_tts_chunk(audio_chunk)
                    yield audio_chunk

            if tts_started:
                await emit_tts_end()

        # Start producer in background
        producer_task = asyncio.create_task(llm_producer())

        try:
            # Yield audio from consumer
            async for audio_chunk in tts_consumer():
                yield audio_chunk
        finally:
            # Ensure producer completes
            await producer_task


class ParallelStreamingChain(VoiceRunnable[bytes, AudioChunk]):
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
        """
        self.asr = asr
        self.llm = llm
        self.tts = tts
        self.system_prompt = system_prompt
        self.language = language
        self.tts_voice = tts_voice
        self.buffer_size = buffer_size

        self._messages: list[dict[str, str]] = []

    def reset(self) -> None:
        """Reset conversation history."""
        self._messages.clear()

    async def ainvoke(
        self,
        input: bytes,
        config: Optional[RunnableConfig] = None,
    ) -> AudioChunk:
        """Process audio and return response."""
        chunks: list[bytes] = []
        async for chunk in self.astream(input, config):
            chunks.append(chunk.data)

        return AudioChunk(
            data=b"".join(chunks),
            sample_rate=24000,
        )

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

        self._messages.append({"role": "user", "content": transcription.text})

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
                buffer += token
                await emit_llm_token(token)

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
            self._messages.append({"role": "assistant", "content": response_text})

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
