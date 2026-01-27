"""Mock providers and utilities for voice-pipeline tests.

This module provides reusable mock implementations for testing
the voice pipeline components.

Usage:
    from tests.mocks import MockASR, MockLLM, MockTTS, create_pcm16_audio
"""

import asyncio
import struct
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from voice_pipeline import (
    ASRInterface,
    LLMInterface,
    TTSInterface,
    VADInterface,
    TranscriptionResult,
    LLMChunk,
    AudioChunk,
    VADEvent,
    SpeechState,
)
from voice_pipeline.interfaces.realtime import (
    RealtimeInterface,
    RealtimeEvent,
    RealtimeEventType,
    RealtimeSessionConfig,
)
from voice_pipeline.interfaces.transport import (
    AudioTransportInterface,
    AudioFrame,
    TransportConfig,
    TransportState,
    AudioConfig,
)
from voice_pipeline.providers.base import (
    HealthCheckResult,
    ProviderHealth,
)


# ==============================================================================
# Audio Test Data
# ==============================================================================


def create_pcm16_audio(
    duration_seconds: float = 1.0,
    sample_rate: int = 16000,
    frequency: float = 440.0,
    amplitude: float = 0.5,
) -> bytes:
    """Create PCM16 test audio (sine wave)."""
    import math

    samples = int(sample_rate * duration_seconds)
    data = bytearray()

    for i in range(samples):
        t = i / sample_rate
        value = amplitude * math.sin(2 * math.pi * frequency * t)
        sample = int(value * 32767)
        data.extend(struct.pack("<h", sample))

    return bytes(data)


def create_silence(
    duration_seconds: float = 1.0,
    sample_rate: int = 16000,
) -> bytes:
    """Create silent PCM16 audio."""
    samples = int(sample_rate * duration_seconds)
    return b"\x00\x00" * samples


def create_audio_chunks(
    total_duration: float = 1.0,
    chunk_duration: float = 0.02,
    sample_rate: int = 16000,
) -> list[bytes]:
    """Create a list of audio chunks."""
    chunk_size = int(sample_rate * chunk_duration * 2)
    full_audio = create_pcm16_audio(total_duration, sample_rate)

    chunks = []
    for i in range(0, len(full_audio), chunk_size):
        chunks.append(full_audio[i:i + chunk_size])

    return chunks


# ==============================================================================
# Mock ASR Provider
# ==============================================================================


@dataclass
class MockASRConfig:
    """Configuration for MockASR."""

    response: str = "Hello, how are you?"
    interim_results: bool = True
    latency: float = 0.0
    word_by_word: bool = False
    fail_after: Optional[int] = None
    error_message: str = "Mock ASR error"


class MockASR(ASRInterface):
    """Mock ASR provider for testing."""

    name = "MockASR"

    def __init__(
        self,
        response: str = "Hello, how are you?",
        interim_results: bool = True,
        latency: float = 0.0,
        word_by_word: bool = False,
        fail_after: Optional[int] = None,
        error_message: str = "Mock ASR error",
        **kwargs,
    ):
        self.config = MockASRConfig(
            response=response,
            interim_results=interim_results,
            latency=latency,
            word_by_word=word_by_word,
            fail_after=fail_after,
            error_message=error_message,
        )
        self.chunks_received = 0
        self.total_bytes_received = 0
        self.calls = []

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        """Transcribe audio stream."""
        self.calls.append({
            "method": "transcribe_stream",
            "language": language,
            "timestamp": time.time(),
        })

        async for chunk in audio_stream:
            self.chunks_received += 1
            self.total_bytes_received += len(chunk)

            if self.config.fail_after and self.chunks_received >= self.config.fail_after:
                raise RuntimeError(self.config.error_message)

        if self.config.latency > 0:
            await asyncio.sleep(self.config.latency)

        if self.config.word_by_word:
            words = self.config.response.split()
            for i, word in enumerate(words):
                is_final = i == len(words) - 1
                partial = " ".join(words[:i + 1])

                if self.config.interim_results or is_final:
                    yield TranscriptionResult(
                        text=partial,
                        is_final=is_final,
                        confidence=None,
                        language=language,
                    )
        else:
            if self.config.interim_results:
                yield TranscriptionResult(
                    text=self.config.response[:len(self.config.response) // 2],
                    is_final=False,
                    confidence=None,
                    language=language,
                )

            yield TranscriptionResult(
                text=self.config.response,
                is_final=True,
                confidence=None,
                language=language,
            )


# ==============================================================================
# Mock LLM Provider
# ==============================================================================


@dataclass
class MockLLMConfig:
    """Configuration for MockLLM."""

    response: str = "I'm doing great, thank you for asking!"
    stream_by: str = "word"
    latency: float = 0.0
    chunk_delay: float = 0.0
    fail_on_message: Optional[str] = None
    error_message: str = "Mock LLM error"
    tool_calls: list[dict] = field(default_factory=list)


class MockLLM(LLMInterface):
    """Mock LLM provider for testing."""

    name = "MockLLM"

    def __init__(
        self,
        response: str = "I'm doing great, thank you for asking!",
        stream_by: str = "word",
        latency: float = 0.0,
        chunk_delay: float = 0.0,
        fail_on_message: Optional[str] = None,
        error_message: str = "Mock LLM error",
        tool_calls: Optional[list[dict]] = None,
        **kwargs,
    ):
        self.config = MockLLMConfig(
            response=response,
            stream_by=stream_by,
            latency=latency,
            chunk_delay=chunk_delay,
            fail_on_message=fail_on_message,
            error_message=error_message,
            tool_calls=tool_calls or [],
        )
        self.calls = []
        self.messages_received = []

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        """Generate streaming response."""
        self.calls.append({
            "method": "generate_stream",
            "messages": messages,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "timestamp": time.time(),
        })
        self.messages_received.extend(messages)

        if self.config.fail_on_message:
            for msg in messages:
                if self.config.fail_on_message in msg.get("content", ""):
                    raise RuntimeError(self.config.error_message)

        if self.config.latency > 0:
            await asyncio.sleep(self.config.latency)

        if self.config.tool_calls:
            for tool_call in self.config.tool_calls:
                yield LLMChunk(text="", tool_calls=[tool_call])
            return

        if self.config.stream_by == "word":
            words = self.config.response.split()
            for i, word in enumerate(words):
                text = word + (" " if i < len(words) - 1 else "")
                yield LLMChunk(text=text)

                if self.config.chunk_delay > 0:
                    await asyncio.sleep(self.config.chunk_delay)

        elif self.config.stream_by == "char":
            for char in self.config.response:
                yield LLMChunk(text=char)

                if self.config.chunk_delay > 0:
                    await asyncio.sleep(self.config.chunk_delay)

        elif self.config.stream_by == "sentence":
            sentences = self.config.response.replace(".", ".|").replace("!", "!|").replace("?", "?|").split("|")
            for sentence in sentences:
                if sentence.strip():
                    yield LLMChunk(text=sentence)

                    if self.config.chunk_delay > 0:
                        await asyncio.sleep(self.config.chunk_delay)

        else:
            yield LLMChunk(text=self.config.response)


# ==============================================================================
# Mock TTS Provider
# ==============================================================================


@dataclass
class MockTTSConfig:
    """Configuration for MockTTS."""

    sample_rate: int = 24000
    bytes_per_char: int = 100
    latency: float = 0.0
    chunk_delay: float = 0.0
    fail_on_text: Optional[str] = None
    error_message: str = "Mock TTS error"


class MockTTS(TTSInterface):
    """Mock TTS provider for testing."""

    name = "MockTTS"

    def __init__(
        self,
        sample_rate: int = 24000,
        bytes_per_char: int = 100,
        latency: float = 0.0,
        chunk_delay: float = 0.0,
        fail_on_text: Optional[str] = None,
        error_message: str = "Mock TTS error",
        **kwargs,
    ):
        self.config = MockTTSConfig(
            sample_rate=sample_rate,
            bytes_per_char=bytes_per_char,
            latency=latency,
            chunk_delay=chunk_delay,
            fail_on_text=fail_on_text,
            error_message=error_message,
        )
        self.calls = []
        self.text_received = []

    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        """Synthesize text to audio."""
        self.calls.append({
            "method": "synthesize_stream",
            "voice": voice,
            "speed": speed,
            "timestamp": time.time(),
        })

        if self.config.latency > 0:
            await asyncio.sleep(self.config.latency)

        async for text in text_stream:
            self.text_received.append(text)

            if self.config.fail_on_text and self.config.fail_on_text in text:
                raise RuntimeError(self.config.error_message)

            audio_size = len(text) * self.config.bytes_per_char
            audio_size = audio_size + (audio_size % 2)

            audio_data = create_pcm16_audio(
                duration_seconds=audio_size / (self.config.sample_rate * 2),
                sample_rate=self.config.sample_rate,
            )

            yield AudioChunk(data=audio_data, sample_rate=self.config.sample_rate)

            if self.config.chunk_delay > 0:
                await asyncio.sleep(self.config.chunk_delay)


# ==============================================================================
# Mock VAD Provider
# ==============================================================================


@dataclass
class MockVADConfig:
    """Configuration for MockVAD."""

    speech_pattern: list[bool] = field(default_factory=lambda: [True] * 10 + [False] * 5)
    confidence: float = 0.9
    always_speech: bool = False
    always_silence: bool = False
    fail_after: Optional[int] = None
    error_message: str = "Mock VAD error"


class MockVAD(VADInterface):
    """Mock VAD provider for testing."""

    name = "MockVAD"

    def __init__(
        self,
        speech_pattern: Optional[list[bool]] = None,
        confidence: float = 0.9,
        always_speech: bool = False,
        always_silence: bool = False,
        fail_after: Optional[int] = None,
        error_message: str = "Mock VAD error",
        **kwargs,
    ):
        self.config = MockVADConfig(
            speech_pattern=speech_pattern or [True] * 10 + [False] * 5,
            confidence=confidence,
            always_speech=always_speech,
            always_silence=always_silence,
            fail_after=fail_after,
            error_message=error_message,
        )
        self.call_count = 0
        self.calls = []

    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int,
    ) -> VADEvent:
        """Process audio chunk for voice activity."""
        self.calls.append({
            "method": "process",
            "chunk_size": len(audio_chunk),
            "sample_rate": sample_rate,
            "timestamp": time.time(),
        })

        if self.config.fail_after and self.call_count >= self.config.fail_after:
            raise RuntimeError(self.config.error_message)

        if self.config.always_speech:
            is_speech = True
        elif self.config.always_silence:
            is_speech = False
        else:
            pattern_idx = self.call_count % len(self.config.speech_pattern)
            is_speech = self.config.speech_pattern[pattern_idx]

        self.call_count += 1

        return VADEvent(
            is_speech=is_speech,
            confidence=self.config.confidence if is_speech else 1.0 - self.config.confidence,
            state=SpeechState.SPEECH if is_speech else SpeechState.SILENCE,
        )

    def reset(self) -> None:
        """Reset VAD state."""
        self.call_count = 0


# ==============================================================================
# Mock Realtime Provider
# ==============================================================================


class MockRealtime(RealtimeInterface):
    """Mock Realtime provider for testing."""

    name = "MockRealtime"

    def __init__(
        self,
        response_text: str = "Hello from realtime!",
        response_audio: Optional[bytes] = None,
        simulate_events: bool = True,
        **kwargs,
    ):
        self.response_text = response_text
        self.response_audio = response_audio or create_pcm16_audio(0.5, 24000)
        self.simulate_events = simulate_events

        self._connected = False
        self._event_queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue()
        self._session_config: Optional[RealtimeSessionConfig] = None

        self.audio_sent: list[bytes] = []
        self.text_sent: list[str] = []
        self.calls: list[dict] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True
        self.calls.append({"method": "connect", "timestamp": time.time()})
        await self._event_queue.put(RealtimeEvent(
            event_type=RealtimeEventType.SESSION_CREATED,
            data={"session": {"id": "mock-session-123"}},
        ))

    async def disconnect(self) -> None:
        self._connected = False
        self.calls.append({"method": "disconnect", "timestamp": time.time()})

    async def send_audio(self, audio_chunk: bytes) -> None:
        self.audio_sent.append(audio_chunk)
        self.calls.append({"method": "send_audio", "size": len(audio_chunk), "timestamp": time.time()})

    async def send_text(self, text: str) -> None:
        self.text_sent.append(text)
        self.calls.append({"method": "send_text", "text": text, "timestamp": time.time()})

    async def commit_audio(self) -> None:
        self.calls.append({"method": "commit_audio", "timestamp": time.time()})
        await self._event_queue.put(RealtimeEvent(event_type=RealtimeEventType.INPUT_AUDIO_BUFFER_COMMITTED))

    async def cancel_response(self) -> None:
        self.calls.append({"method": "cancel_response", "timestamp": time.time()})

    async def create_response(self) -> None:
        self.calls.append({"method": "create_response", "timestamp": time.time()})

        if self.simulate_events:
            await self._event_queue.put(RealtimeEvent(event_type=RealtimeEventType.RESPONSE_CREATED))
            await self._event_queue.put(RealtimeEvent(event_type=RealtimeEventType.RESPONSE_TEXT_DELTA, text=self.response_text))
            await self._event_queue.put(RealtimeEvent(event_type=RealtimeEventType.RESPONSE_AUDIO_DELTA, audio=self.response_audio))
            await self._event_queue.put(RealtimeEvent(event_type=RealtimeEventType.RESPONSE_DONE))

    async def update_session(self, config: RealtimeSessionConfig) -> None:
        self._session_config = config
        self.calls.append({"method": "update_session", "config": config, "timestamp": time.time()})

    async def receive_events(self) -> AsyncIterator[RealtimeEvent]:
        while self._connected or not self._event_queue.empty():
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                yield event
            except asyncio.TimeoutError:
                if not self._connected:
                    break


# ==============================================================================
# Mock Transport Provider
# ==============================================================================


class MockTransport(AudioTransportInterface):
    """Mock Audio Transport for testing."""

    name = "MockTransport"

    def __init__(
        self,
        input_audio: Optional[list[bytes]] = None,
        sample_rate: int = 16000,
        **kwargs,
    ):
        self._input_audio = input_audio or []
        self._input_index = 0
        self._output_audio: list[bytes] = []
        self._state = TransportState.IDLE
        self._running = False
        self._config = TransportConfig(
            input_config=AudioConfig(sample_rate=sample_rate),
            output_config=AudioConfig(sample_rate=sample_rate),
        )
        self.calls: list[dict] = []

    def set_input_audio(self, audio_chunks: list[bytes]) -> None:
        self._input_audio = audio_chunks
        self._input_index = 0

    @property
    def state(self) -> TransportState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def config(self) -> TransportConfig:
        return self._config

    async def start(self) -> None:
        self._state = TransportState.RUNNING
        self._running = True
        self.calls.append({"method": "start", "timestamp": time.time()})

    async def stop(self) -> None:
        self._state = TransportState.STOPPED
        self._running = False
        self.calls.append({"method": "stop", "timestamp": time.time()})

    async def read_frames(self) -> AsyncIterator[AudioFrame]:
        while self._input_index < len(self._input_audio) and self._running:
            data = self._input_audio[self._input_index]
            self._input_index += 1
            yield AudioFrame(data=data, sample_rate=self._config.input_config.sample_rate, sequence_number=self._input_index - 1)

    async def write_frame(self, frame: AudioFrame) -> None:
        self._output_audio.append(frame.data)
        self.calls.append({"method": "write_frame", "size": len(frame.data), "timestamp": time.time()})

    async def write_bytes(self, data: bytes) -> None:
        self._output_audio.append(data)
        self.calls.append({"method": "write_bytes", "size": len(data), "timestamp": time.time()})

    def get_output_audio(self) -> list[bytes]:
        return self._output_audio

    async def _do_health_check(self) -> HealthCheckResult:
        return HealthCheckResult(status=ProviderHealth.HEALTHY, message="Mock transport healthy")
