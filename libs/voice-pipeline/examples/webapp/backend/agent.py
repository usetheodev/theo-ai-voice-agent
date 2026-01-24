"""Voice Agent Session using voice-pipeline framework.

This module implements the voice agent that processes audio
and generates responses using the voice-pipeline components.
"""

import asyncio
import logging
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Optional

from fastapi import WebSocket

# Voice Pipeline imports
import sys
import os

# Add voice-pipeline to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from voice_pipeline import (
    PipelineBuilder,
    PipelineConfig,
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

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Voice agent states."""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


@dataclass
class ConversationMessage:
    """A message in the conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)


class VoiceAgentSession:
    """Voice agent session for a single WebSocket connection.

    Handles the full voice conversation flow:
    1. Receive audio from client
    2. Detect speech (VAD)
    3. Transcribe speech (ASR)
    4. Generate response (LLM)
    5. Synthesize speech (TTS)
    6. Send audio back to client
    """

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.state = AgentState.IDLE

        # Configuration
        self.sample_rate = 16000
        self.language = "pt"  # Português brasileiro
        self.system_prompt = """Você é um assistente de voz prestativo e amigável.
Mantenha suas respostas concisas e conversacionais, adequadas para diálogo falado.
Responda naturalmente como se estivesse tendo uma conversa real.
IMPORTANTE: Sempre responda em português brasileiro."""

        # Conversation history
        self.messages: list[ConversationMessage] = []

        # Audio buffers
        self._audio_buffer: asyncio.Queue[bytes] = asyncio.Queue()
        self._is_listening = False

        # Processing tasks
        self._process_task: Optional[asyncio.Task] = None
        self._speak_task: Optional[asyncio.Task] = None

        # Providers (initialized in initialize())
        self._asr: Optional[ASRInterface] = None
        self._llm: Optional[LLMInterface] = None
        self._tts: Optional[TTSInterface] = None
        self._vad: Optional[VADInterface] = None

        # VAD state
        self._speech_started = False
        self._last_speech_time = 0.0
        self._silence_threshold_ms = 800  # End of speech after 800ms silence

    async def initialize(self):
        """Initialize the voice agent with providers."""
        logger.info("Initializing voice agent session")

        # Create and connect ASR
        self._asr = await self._create_and_connect_asr()

        # Create and connect LLM
        self._llm = await self._create_and_connect_llm()

        # Create and connect TTS
        self._tts = await self._create_and_connect_tts()

        # Create and connect VAD
        self._vad = await self._create_and_connect_vad()

        logger.info(f"Providers ready: ASR={type(self._asr).__name__}, "
                   f"LLM={type(self._llm).__name__}, "
                   f"TTS={type(self._tts).__name__}, "
                   f"VAD={type(self._vad).__name__}")

    async def _create_and_connect_asr(self) -> ASRInterface:
        """Create and connect ASR provider, fallback to mock."""
        try:
            from voice_pipeline.providers.asr.whispercpp import WhisperCppASRProvider
            # Usar modelo base (multilingual) com idioma PT-BR
            provider = WhisperCppASRProvider(model="base", language="pt")
            await provider.connect()
            logger.info(f"WhisperCppASRProvider connected (language={self.language})")
            return provider
        except Exception as e:
            logger.warning(f"Whisper failed ({e}), using mock ASR")
            return MockASR()

    async def _create_and_connect_llm(self) -> LLMInterface:
        """Create and connect LLM provider, fallback to mock."""
        try:
            from voice_pipeline.providers.llm.ollama import OllamaLLMProvider
            provider = OllamaLLMProvider(model="llama3.2:1b")
            await provider.connect()
            logger.info("OllamaLLMProvider connected")
            return provider
        except Exception as e:
            logger.warning(f"Ollama failed ({e}), using mock LLM")
            return MockLLM()

    async def _create_and_connect_tts(self) -> TTSInterface:
        """Create and connect TTS provider, fallback to mock."""
        try:
            # Use kokoro-onnx directly (lighter dependency)
            # pf_dora = voz feminina portuguesa
            tts = KokoroOnnxTTS(voice="pf_dora")
            await tts.connect()
            return tts
        except Exception as e:
            logger.warning(f"KokoroOnnx failed ({e}), using mock TTS")
            return MockTTS()

    async def _create_and_connect_vad(self) -> VADInterface:
        """Create and connect VAD provider, fallback to mock."""
        try:
            from voice_pipeline.providers.vad.silero import SileroVADProvider
            provider = SileroVADProvider()
            await provider.connect()
            logger.info("SileroVADProvider connected")
            return provider
        except Exception as e:
            logger.warning(f"Silero failed ({e}), using mock VAD")
            return MockVAD()

    async def configure(self, sample_rate: int = 16000, language: str = "en"):
        """Update session configuration."""
        self.sample_rate = sample_rate
        self.language = language
        logger.info(f"Configured: sample_rate={sample_rate}, language={language}")

    async def start_listening(self):
        """Start listening for user speech."""
        self._is_listening = True
        self._speech_started = False
        await self._set_state(AgentState.LISTENING)
        logger.info("Started listening")

    async def stop_listening(self):
        """Stop listening for user speech."""
        self._is_listening = False
        await self._set_state(AgentState.IDLE)
        logger.info("Stopped listening")

    async def interrupt(self):
        """Interrupt current response (barge-in)."""
        logger.info("Interrupt requested")

        # Cancel speaking task
        if self._speak_task and not self._speak_task.done():
            self._speak_task.cancel()
            try:
                await self._speak_task
            except asyncio.CancelledError:
                pass

        # Reset to listening
        await self._set_state(AgentState.LISTENING)
        self._speech_started = False

        await self.websocket.send_json({
            "type": "interrupted",
            "message": "Response interrupted"
        })

    async def reset(self):
        """Reset conversation history."""
        self.messages.clear()
        await self._set_state(AgentState.IDLE)
        logger.info("Conversation reset")

    async def process_audio(self, audio_chunk: bytes):
        """Process incoming audio chunk from client."""
        if not self._is_listening:
            return

        # Run VAD
        vad_event = await self._vad.process(audio_chunk, self.sample_rate)

        if vad_event.is_speech:
            if not self._speech_started:
                # Speech started
                self._speech_started = True
                logger.info("Speech detected")
                await self.websocket.send_json({
                    "type": "vad",
                    "event": "speech_start"
                })

            self._last_speech_time = time.time()
            await self._audio_buffer.put(audio_chunk)

        elif self._speech_started:
            # Check for end of speech
            silence_duration_ms = (time.time() - self._last_speech_time) * 1000

            if silence_duration_ms >= self._silence_threshold_ms:
                # Speech ended
                logger.info(f"Speech ended (silence: {silence_duration_ms:.0f}ms)")
                await self.websocket.send_json({
                    "type": "vad",
                    "event": "speech_end"
                })

                # Process the collected audio
                await self._process_speech()
                self._speech_started = False

    async def _process_speech(self):
        """Process collected speech audio."""
        await self._set_state(AgentState.PROCESSING)

        try:
            # Collect all buffered audio
            audio_chunks = []
            while not self._audio_buffer.empty():
                chunk = await self._audio_buffer.get()
                audio_chunks.append(chunk)

            if not audio_chunks:
                await self._set_state(AgentState.LISTENING)
                return

            audio_data = b"".join(audio_chunks)
            logger.info(f"Processing {len(audio_data)} bytes of audio")

            # Transcribe
            transcription = await self._transcribe(audio_data)

            if not transcription or not transcription.strip():
                logger.info("Empty transcription, ignoring")
                await self._set_state(AgentState.LISTENING)
                return

            logger.info(f"Transcription: {transcription}")

            # Send transcription to client
            await self.websocket.send_json({
                "type": "transcript",
                "text": transcription,
                "is_final": True
            })

            # Add to conversation
            self.messages.append(ConversationMessage(
                role="user",
                content=transcription
            ))

            # Generate and speak response
            await self._generate_response(transcription)

        except Exception as e:
            logger.error(f"Error processing speech: {e}")
            await self.websocket.send_json({
                "type": "error",
                "message": str(e)
            })
            await self._set_state(AgentState.LISTENING)

    async def _transcribe(self, audio_data: bytes) -> str:
        """Transcribe audio using ASR."""
        async def audio_generator():
            yield audio_data

        logger.info(f"Transcribing with language={self.language}")

        text = ""
        async for result in self._asr.transcribe_stream(
            audio_generator(),
            language=self.language
        ):
            logger.debug(f"ASR result: text='{result.text}', lang={result.language}, final={result.is_final}")
            if result.is_final:
                text = result.text

        return text

    async def _generate_response(self, user_text: str):
        """Generate and speak LLM response."""
        await self._set_state(AgentState.SPEAKING)

        try:
            # Build messages for LLM
            llm_messages = [
                {"role": msg.role, "content": msg.content}
                for msg in self.messages
            ]

            # Generate response
            response_text = ""
            sentence_buffer = ""

            # Create TTS task
            tts_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

            async def tts_worker():
                """Worker that converts text to speech and sends to client."""
                async def sentence_generator():
                    while True:
                        sentence = await tts_queue.get()
                        if sentence is None:
                            break
                        yield sentence

                async for audio_chunk in self._tts.synthesize_stream(
                    sentence_generator()
                ):
                    # Send audio to client
                    await self.websocket.send_bytes(audio_chunk.data)

            # Start TTS worker
            self._speak_task = asyncio.create_task(tts_worker())

            # Stream LLM response
            async for chunk in self._llm.generate_stream(
                llm_messages,
                system_prompt=self.system_prompt,
                temperature=0.7,
            ):
                response_text += chunk.text
                sentence_buffer += chunk.text

                # Send text chunk to client
                await self.websocket.send_json({
                    "type": "response_chunk",
                    "text": chunk.text
                })

                # Check for sentence boundaries
                sentences = self._extract_sentences(sentence_buffer)
                for sentence in sentences[:-1]:
                    if sentence.strip():
                        await tts_queue.put(sentence)
                sentence_buffer = sentences[-1] if sentences else ""

            # Send remaining text
            if sentence_buffer.strip():
                await tts_queue.put(sentence_buffer.strip())

            # Signal TTS completion
            await tts_queue.put(None)

            # Wait for TTS to finish
            await self._speak_task

            # Send complete response
            await self.websocket.send_json({
                "type": "response",
                "text": response_text
            })

            # Add to conversation
            self.messages.append(ConversationMessage(
                role="assistant",
                content=response_text
            ))

            logger.info(f"Response: {response_text[:100]}...")

        except asyncio.CancelledError:
            logger.info("Response generation cancelled")
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            await self.websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        finally:
            await self._set_state(AgentState.LISTENING)

    def _extract_sentences(self, text: str) -> list[str]:
        """Extract complete sentences from text."""
        if not text:
            return [""]

        sentences = []
        current = ""
        min_chars = 20

        for char in text:
            current += char
            if char in ".!?\n":
                if len(current.strip()) >= min_chars:
                    sentences.append(current.strip())
                    current = ""

        sentences.append(current)
        return sentences

    async def _set_state(self, state: AgentState):
        """Update agent state and notify client."""
        self.state = state
        await self.websocket.send_json({
            "type": "status",
            "state": state.value
        })
        logger.debug(f"State: {state.value}")

    async def cleanup(self):
        """Cleanup session resources."""
        logger.info("Cleaning up session")

        # Cancel tasks
        if self._process_task and not self._process_task.done():
            self._process_task.cancel()
        if self._speak_task and not self._speak_task.done():
            self._speak_task.cancel()

        # Clear buffers
        while not self._audio_buffer.empty():
            try:
                self._audio_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break


# ==============================================================================
# Mock Providers (fallback when real providers not available)
# ==============================================================================


class MockASR(ASRInterface):
    """Mock ASR for testing without Whisper."""

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        # Consume audio
        audio_size = 0
        async for chunk in audio_stream:
            audio_size += len(chunk)

        # Return mock transcription
        yield TranscriptionResult(
            text="Hello, this is a test message.",
            is_final=True,
            confidence=0.95,
            language=language,
        )


class MockLLM(LLMInterface):
    """Mock LLM for testing without Ollama."""

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        response = "I'm a mock assistant. In a real setup, I would be powered by a language model like Llama or GPT. How can I help you today?"

        words = response.split()
        for i, word in enumerate(words):
            text = word + (" " if i < len(words) - 1 else "")
            yield LLMChunk(text=text)
            await asyncio.sleep(0.05)


class KokoroOnnxTTS(TTSInterface):
    """TTS using kokoro-onnx directly."""

    def __init__(self, voice: str = "af_bella"):
        self._voice = voice
        self._kokoro = None
        self._sample_rate = 24000

    async def connect(self):
        """Initialize kokoro-onnx."""
        from kokoro_onnx import Kokoro

        # Find model files relative to this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(script_dir, "kokoro-v1.0.onnx")
        voices_path = os.path.join(script_dir, "voices-v1.0.bin")

        self._kokoro = Kokoro(model_path, voices_path)
        logger.info("KokoroOnnxTTS connected")

    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        voice_name = voice or self._voice

        async for text in text_stream:
            if not text.strip():
                continue

            try:
                # Run synthesis in executor to not block
                loop = asyncio.get_event_loop()
                samples, sr = await loop.run_in_executor(
                    None,
                    lambda: self._kokoro.create(text, voice=voice_name, speed=speed)
                )

                # Convert float32 samples to int16 PCM
                import numpy as np
                audio_int16 = (samples * 32767).astype(np.int16)
                audio_bytes = audio_int16.tobytes()

                yield AudioChunk(data=audio_bytes, sample_rate=sr)

            except Exception as e:
                logger.error(f"TTS error: {e}")
                # Yield silence on error
                duration_samples = len(text) * 2400
                yield AudioChunk(data=b"\x00\x00" * duration_samples, sample_rate=24000)


class MockTTS(TTSInterface):
    """Mock TTS for testing without Kokoro."""

    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        async for text in text_stream:
            # Generate silence (proper audio would need a real TTS)
            # 24kHz, 16-bit, mono - about 100ms per character
            duration_samples = len(text) * 2400  # ~100ms per char at 24kHz
            audio_data = b"\x00\x00" * duration_samples
            yield AudioChunk(data=audio_data, sample_rate=24000)
            await asyncio.sleep(len(text) * 0.05)  # Simulate synthesis time


class MockVAD(VADInterface):
    """Mock VAD for testing without Silero."""

    def __init__(self):
        self._frame_count = 0
        self._threshold = 500  # Threshold for "speech" detection

    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int,
    ) -> VADEvent:
        # Simple energy-based VAD
        if len(audio_chunk) < 2:
            return VADEvent(is_speech=False, confidence=0.0, state=SpeechState.SILENCE)

        # Calculate RMS energy
        samples = struct.unpack(f"<{len(audio_chunk)//2}h", audio_chunk)
        energy = sum(s * s for s in samples) / len(samples)
        rms = energy ** 0.5

        is_speech = rms > self._threshold
        confidence = min(rms / 5000, 1.0)

        return VADEvent(
            is_speech=is_speech,
            confidence=confidence,
            state=SpeechState.SPEECH if is_speech else SpeechState.SILENCE,
        )

    def reset(self) -> None:
        self._frame_count = 0
