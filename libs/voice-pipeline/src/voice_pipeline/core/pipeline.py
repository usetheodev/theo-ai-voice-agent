"""Main Pipeline orchestrator.

Connects VAD → ASR → LLM → TTS with streaming and barge-in support.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Optional

from ..interfaces import (
    ASRInterface,
    LLMInterface,
    TTSInterface,
    VADInterface,
    TranscriptionResult,
    AudioChunk,
    VADEvent,
)
from ..interfaces.vad import SpeechState
from .config import PipelineConfig
from .events import EventEmitter, PipelineEvent, PipelineEventType
from .state_machine import ConversationState, ConversationStateMachine

logger = logging.getLogger(__name__)


@dataclass
class PipelineMetrics:
    """Metrics from pipeline processing."""

    # Timing
    total_latency_ms: float = 0.0
    asr_latency_ms: float = 0.0
    llm_ttft_ms: float = 0.0  # Time to First Token
    tts_ttfa_ms: float = 0.0  # Time to First Audio

    # Counts
    asr_words: int = 0
    llm_tokens: int = 0
    tts_chunks: int = 0

    # Barge-in
    barge_in_count: int = 0


@dataclass
class ConversationContext:
    """Context for a conversation turn."""

    messages: list[dict[str, str]] = field(default_factory=list)
    current_transcription: str = ""
    current_response: str = ""
    turn_start_time: float = 0.0


class Pipeline:
    """Voice conversation pipeline.

    Orchestrates the flow: Audio → VAD → ASR → LLM → TTS → Audio

    Features:
    - Streaming at every stage
    - Barge-in (user interruption)
    - State machine for conversation flow
    - Event emission for monitoring

    Example:
        pipeline = Pipeline(
            config=PipelineConfig(system_prompt="You are helpful."),
            asr=MyASR(),
            llm=MyLLM(),
            tts=MyTTS(),
            vad=MyVAD(),
        )

        async for audio_out in pipeline.process(audio_input_stream):
            play_audio(audio_out)
    """

    def __init__(
        self,
        config: PipelineConfig,
        asr: ASRInterface,
        llm: LLMInterface,
        tts: TTSInterface,
        vad: VADInterface,
    ):
        """Initialize pipeline.

        Args:
            config: Pipeline configuration.
            asr: ASR provider.
            llm: LLM provider.
            tts: TTS provider.
            vad: VAD provider.
        """
        self.config = config
        self.asr = asr
        self.llm = llm
        self.tts = tts
        self.vad = vad

        # State
        self.state_machine = ConversationStateMachine()
        self.context = ConversationContext()
        self.metrics = PipelineMetrics()

        # Events
        self._events = EventEmitter()

        # Control
        self._running = False
        self._cancel_event = asyncio.Event()
        self._processing_event = asyncio.Event()
        self._current_task: Optional[asyncio.Task] = None
        self._barge_in_cooldown_until: float = 0.0

        # Audio buffers
        self._input_buffer: asyncio.Queue[bytes] = asyncio.Queue(maxsize=self.config.buffer_maxsize)
        self._output_buffer: asyncio.Queue[AudioChunk] = asyncio.Queue(maxsize=self.config.buffer_maxsize)

    # =========================================================================
    # EVENT HANDLERS
    # =========================================================================

    def on(
        self,
        event_type: PipelineEventType,
        handler: Callable[[PipelineEvent], None],
    ) -> None:
        """Register event handler.

        Args:
            event_type: Event type to listen for.
            handler: Callback function.
        """
        self._events.on(event_type, handler)

    def on_all(self, handler: Callable[[PipelineEvent], None]) -> None:
        """Register handler for all events."""
        self._events.on_all(handler)

    async def _emit(
        self,
        event_type: PipelineEventType,
        data: any = None,
        latency_ms: Optional[float] = None,
    ) -> None:
        """Emit pipeline event."""
        event = PipelineEvent(
            type=event_type,
            data=data,
            latency_ms=latency_ms,
        )
        await self._events.emit(event)

    # =========================================================================
    # MAIN PROCESSING
    # =========================================================================

    async def process(
        self,
        audio_input: AsyncIterator[bytes],
    ) -> AsyncIterator[AudioChunk]:
        """Process audio input stream and yield audio output.

        This is the main entry point. It:
        1. Detects speech (VAD)
        2. Transcribes speech (ASR)
        3. Generates response (LLM)
        4. Synthesizes speech (TTS)
        5. Handles barge-in (interruption)

        Args:
            audio_input: Async iterator of audio chunks (PCM16).

        Yields:
            Audio chunks to play back.
        """
        self._running = True
        self._cancel_event.clear()

        await self._emit(PipelineEventType.PIPELINE_START)

        try:
            # Start concurrent processing tasks
            vad_task = asyncio.create_task(self._vad_loop(audio_input))
            process_task = asyncio.create_task(self._process_loop())

            self._current_task = process_task

            # Yield output audio
            while self._running:
                try:
                    chunk = await asyncio.wait_for(
                        self._output_buffer.get(),
                        timeout=0.1,
                    )
                    yield chunk
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            await self._emit(PipelineEventType.PIPELINE_ERROR, {"error": str(e)})
            raise

        finally:
            self._running = False
            self._cancel_event.set()

            # Cancel tasks
            for task in [vad_task, process_task]:
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            await self._emit(PipelineEventType.PIPELINE_STOP)

    async def _vad_loop(self, audio_input: AsyncIterator[bytes]) -> None:
        """VAD processing loop.

        Monitors audio for speech activity and manages state transitions.
        """
        speech_start_time: Optional[float] = None
        last_speech_time: float = 0.0

        async for chunk in audio_input:
            if not self._running:
                break

            # Check for barge-in during speaking
            if self.state_machine.is_speaking and self.config.enable_barge_in:
                # Skip barge-in during cooldown
                if time.monotonic() < self._barge_in_cooldown_until:
                    continue
                event = await self.vad.process(chunk, self.config.sample_rate)
                if event.is_speech:
                    if speech_start_time is None:
                        speech_start_time = time.time()

                    speech_duration_ms = (time.time() - speech_start_time) * 1000
                    if speech_duration_ms >= self.config.barge_in_threshold_ms:
                        await self._handle_barge_in()
                        speech_start_time = None
                else:
                    speech_start_time = None
                continue

            # Normal VAD processing
            event = await self.vad.process(chunk, self.config.sample_rate)

            if self.state_machine.is_idle:
                if event.is_speech:
                    # Start listening
                    self.state_machine.transition_to(ConversationState.LISTENING)
                    await self._emit(PipelineEventType.VAD_SPEECH_START)
                    self.context.turn_start_time = time.time()

            elif self.state_machine.is_listening:
                # Buffer audio for ASR
                await self._input_buffer.put(chunk)

                if event.is_speech:
                    last_speech_time = time.time()
                else:
                    # Check for end of speech
                    silence_ms = (time.time() - last_speech_time) * 1000
                    if silence_ms >= self.config.vad_silence_ms:
                        await self._emit(PipelineEventType.VAD_SPEECH_END)
                        # Signal end of input
                        await self._input_buffer.put(None)
                        self.state_machine.transition_to(ConversationState.PROCESSING)
                        self._processing_event.set()

    async def _process_loop(self) -> None:
        """Main processing loop: ASR → LLM → TTS."""
        while self._running:
            # Wait for processing state (event-driven, no polling)
            if not self.state_machine.is_processing:
                self._processing_event.clear()
                await self._processing_event.wait()
                if not self._running:
                    break
                continue

            try:
                # 1. ASR: Transcribe user speech
                transcription = await self._run_asr()

                if not transcription or not transcription.strip():
                    self.state_machine.transition_to(ConversationState.IDLE)
                    continue

                self.context.current_transcription = transcription

                await self._emit(
                    PipelineEventType.TRANSCRIPTION,
                    {"text": transcription},
                )

                # 2. LLM: Generate response
                self.state_machine.transition_to(ConversationState.SPEAKING)

                # 3. LLM → TTS streaming
                await self._run_llm_tts(transcription)

                # Done speaking
                self.state_machine.transition_to(ConversationState.IDLE)
                self.vad.reset()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Processing error: {e}")
                await self._emit(PipelineEventType.PIPELINE_ERROR, {"error": str(e)})
                self.state_machine.force_transition(ConversationState.IDLE)

    async def _run_asr(self) -> str:
        """Run ASR on buffered audio."""
        await self._emit(PipelineEventType.ASR_START)
        asr_start = time.time()

        # Collect audio from buffer
        async def audio_generator():
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self._input_buffer.get(), timeout=30.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("Input buffer timeout - ending ASR collection")
                    break
                if chunk is None:
                    break
                yield chunk

        # Transcribe
        transcription_text = ""

        try:
            async for result in self.asr.transcribe_stream(
                audio_generator(),
                language=self.config.language,
            ):
                if result.is_final:
                    transcription_text = result.text
                    await self._emit(
                        PipelineEventType.ASR_FINAL,
                        {"text": result.text, "confidence": result.confidence},
                    )
                else:
                    await self._emit(
                        PipelineEventType.ASR_PARTIAL,
                        {"text": result.text},
                    )

        except Exception as e:
            await self._emit(PipelineEventType.ASR_ERROR, {"error": str(e)})
            raise

        # Record metrics
        self.metrics.asr_latency_ms = (time.time() - asr_start) * 1000

        return transcription_text

    async def _run_llm_tts(self, transcription: str) -> None:
        """Run LLM and TTS in parallel streaming fashion.

        Uses sentence-level streaming: LLM generates text,
        complete sentences are sent to TTS immediately.
        """
        await self._emit(PipelineEventType.LLM_START)
        llm_start = time.time()
        first_token_received = False
        tts_started = False

        # Add user message to context
        self.context.messages.append({
            "role": "user",
            "content": transcription,
        })

        # Sentence buffer for TTS
        sentence_buffer = ""
        response_text = ""

        # TTS queue
        tts_queue: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=self.config.tts_queue_maxsize)

        # Start TTS consumer task
        async def tts_consumer():
            nonlocal tts_started
            await self._emit(PipelineEventType.TTS_START)
            tts_start = time.time()

            async def sentence_generator():
                while True:
                    try:
                        sentence = await asyncio.wait_for(
                            tts_queue.get(), timeout=30.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning("TTS queue timeout")
                        break
                    if sentence is None:
                        break
                    yield sentence

            try:
                async for audio_chunk in self.tts.synthesize_stream(
                    sentence_generator(),
                    voice=self.config.tts_voice,
                ):
                    if self._cancel_event.is_set():
                        break

                    if not tts_started:
                        tts_started = True
                        self.metrics.tts_ttfa_ms = (time.time() - tts_start) * 1000

                    await self._output_buffer.put(audio_chunk)
                    await self._emit(PipelineEventType.TTS_CHUNK)

                await self._emit(PipelineEventType.TTS_COMPLETE)

            except Exception as e:
                await self._emit(PipelineEventType.TTS_ERROR, {"error": str(e)})

        tts_task = asyncio.create_task(tts_consumer())

        try:
            # Generate LLM response
            async for chunk in self.llm.generate_stream(
                self.context.messages,
                system_prompt=self.config.system_prompt,
                temperature=self.config.llm_temperature,
                max_tokens=self.config.llm_max_tokens,
            ):
                if self._cancel_event.is_set():
                    break

                if not first_token_received:
                    first_token_received = True
                    self.metrics.llm_ttft_ms = (time.time() - llm_start) * 1000

                await self._emit(PipelineEventType.LLM_CHUNK, {"text": chunk.text})

                sentence_buffer += chunk.text
                response_text += chunk.text

                # Check for sentence boundaries
                sentences = self._extract_sentences(sentence_buffer)
                for sentence in sentences[:-1]:  # All complete sentences
                    await tts_queue.put(sentence)
                sentence_buffer = sentences[-1] if sentences else ""

            # Send remaining text
            if sentence_buffer.strip():
                await tts_queue.put(sentence_buffer.strip())

            # Signal TTS completion
            await tts_queue.put(None)

            await self._emit(
                PipelineEventType.LLM_COMPLETE,
                {"text": response_text},
            )

            await self._emit(
                PipelineEventType.LLM_RESPONSE,
                {"text": response_text},
            )

            # Add assistant message to context
            self.context.messages.append({
                "role": "assistant",
                "content": response_text,
            })
            self.context.current_response = response_text

        except Exception as e:
            await self._emit(PipelineEventType.LLM_ERROR, {"error": str(e)})
            await tts_queue.put(None)
            raise

        finally:
            await tts_task

        # Record total latency
        self.metrics.total_latency_ms = (time.time() - self.context.turn_start_time) * 1000

    def _extract_sentences(self, text: str) -> list[str]:
        """Extract complete sentences from text.

        Returns list where all but last element are complete sentences.
        """
        if not text:
            return [""]

        sentences = []
        current = ""

        for char in text:
            current += char
            if char in self.config.sentence_end_chars:
                if len(current.strip()) >= self.config.min_tts_chars:
                    sentences.append(current.strip())
                    current = ""

        # Add remaining (incomplete sentence)
        sentences.append(current)

        return sentences

    async def _handle_barge_in(self) -> None:
        """Handle user interruption (barge-in).

        Uses a non-blocking cooldown timestamp instead of sleep,
        so VAD continues reading frames during the backoff period.
        """
        logger.info("Barge-in detected")

        self.metrics.barge_in_count += 1

        # Signal cancellation
        self._cancel_event.set()

        # Clear output buffer
        while not self._output_buffer.empty():
            try:
                self._output_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break

        await self._emit(PipelineEventType.BARGE_IN)

        # Transition to listening
        self.state_machine.force_transition(ConversationState.LISTENING)

        # Non-blocking backoff: store timestamp instead of sleeping
        self._barge_in_cooldown_until = (
            time.monotonic() + self.config.barge_in_backoff_ms / 1000
        )

        self._cancel_event.clear()
        self.vad.reset()

    # =========================================================================
    # CONTROL METHODS
    # =========================================================================

    def stop(self) -> None:
        """Stop the pipeline."""
        self._running = False
        self._cancel_event.set()
        self._processing_event.set()  # Unblock _process_loop

    def reset(self) -> None:
        """Reset pipeline state."""
        self.state_machine.reset()
        self.context = ConversationContext()
        self.metrics = PipelineMetrics()
        self.vad.reset()

        # Clear buffers
        while not self._input_buffer.empty():
            try:
                self._input_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break

        while not self._output_buffer.empty():
            try:
                self._output_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break

    def get_metrics(self) -> PipelineMetrics:
        """Get current pipeline metrics."""
        return self.metrics
