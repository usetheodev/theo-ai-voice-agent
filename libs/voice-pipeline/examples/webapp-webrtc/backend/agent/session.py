"""Voice Agent Session - manages a complete voice conversation session."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional

import numpy as np

from voice_pipeline.interfaces.transport import AudioFrame

from ..webrtc.events import DataChannelEventEmitter, EventType
from ..webrtc.transport import WebRTCTransport

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    """State of a voice agent session."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ERROR = "error"
    ENDED = "ended"


@dataclass
class SessionMetrics:
    """Metrics for a voice session."""

    turn_count: int = 0
    total_audio_duration_ms: float = 0.0
    total_processing_time_ms: float = 0.0
    last_vad_start: Optional[float] = None
    last_asr_end: Optional[float] = None
    last_llm_start: Optional[float] = None
    last_llm_first_token: Optional[float] = None
    last_tts_start: Optional[float] = None
    last_tts_first_audio: Optional[float] = None

    # Latency metrics (last turn)
    ttfa: Optional[float] = None  # Time to First Audio (VAD end -> first TTS audio)
    ttft: Optional[float] = None  # Time to First Token (ASR end -> first LLM token)
    e2e: Optional[float] = None  # End to End (VAD start -> first TTS audio)

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "turn_count": self.turn_count,
            "total_audio_duration_ms": self.total_audio_duration_ms,
            "total_processing_time_ms": self.total_processing_time_ms,
            "latency": {
                "ttfa_ms": self.ttfa * 1000 if self.ttfa else None,
                "ttft_ms": self.ttft * 1000 if self.ttft else None,
                "e2e_ms": self.e2e * 1000 if self.e2e else None,
            },
        }


@dataclass
class VADConfig:
    """Voice Activity Detection configuration."""

    threshold: float = 0.3  # Lowered from 0.5 for better sensitivity
    min_speech_duration_ms: int = 250
    min_silence_duration_ms: int = 500
    padding_duration_ms: int = 300
    sample_rate: int = 16000


class VoiceAgentSession:
    """Manages a complete voice conversation session.

    Integrates WebRTC transport with VAD, ASR, LLM, and TTS components.
    """

    def __init__(
        self,
        session_id: str,
        transport: WebRTCTransport,
        vad_config: Optional[VADConfig] = None,
    ):
        """Initialize the voice agent session.

        Args:
            session_id: Unique session identifier.
            transport: WebRTC transport for audio I/O.
            vad_config: VAD configuration.
        """
        self.session_id = session_id
        self.transport = transport
        self.vad_config = vad_config or VADConfig()

        # State
        self._state = SessionState.IDLE
        self._running = False
        self._interrupted = False
        self._metrics = SessionMetrics()

        # Audio buffer for VAD
        self._audio_buffer: list[bytes] = []
        self._speech_buffer: list[bytes] = []

        # VAD state
        self._is_speech = False
        self._speech_start_time: Optional[float] = None
        self._silence_start_time: Optional[float] = None
        self._vad_model: Optional[Any] = None
        self._vad_buffer: np.ndarray = np.array([], dtype=np.int16)  # Buffer for VAD chunking
        self._vad_chunk_size = 512  # Silero VAD requires exactly 512 samples for 16kHz

        # Callbacks
        self._on_speech_start: Optional[Callable[[], Any]] = None
        self._on_speech_end: Optional[Callable[[bytes], Any]] = None
        self._on_state_change: Optional[Callable[[SessionState], None]] = None
        self._on_transcript: Optional[Callable[[str], Any]] = None
        self._on_response: Optional[Callable[[str], Any]] = None

        # Tasks
        self._process_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> SessionState:
        """Current session state."""
        return self._state

    @property
    def metrics(self) -> SessionMetrics:
        """Session metrics."""
        return self._metrics

    @property
    def event_emitter(self) -> DataChannelEventEmitter:
        """Get the event emitter from transport."""
        return self.transport.event_emitter

    def _set_state(self, state: SessionState) -> None:
        """Update state and notify."""
        if self._state != state:
            self._state = state
            logger.info(f"Session {self.session_id} state: {state.value}")

            # Emit state event
            asyncio.create_task(
                self.event_emitter.emit(EventType.AGENT_STATE, {"state": state.value})
            )

            if self._on_state_change:
                try:
                    self._on_state_change(state)
                except Exception as e:
                    logger.error(f"Error in state change callback: {e}")

    def on_speech_start(self, callback: Callable[[], Any]) -> None:
        """Register callback for speech start."""
        self._on_speech_start = callback

    def on_speech_end(self, callback: Callable[[bytes], Any]) -> None:
        """Register callback for speech end (receives audio bytes)."""
        self._on_speech_end = callback

    def on_state_change(self, callback: Callable[[SessionState], None]) -> None:
        """Register callback for state changes."""
        self._on_state_change = callback

    def on_transcript(self, callback: Callable[[str], Any]) -> None:
        """Register callback for ASR transcripts."""
        self._on_transcript = callback

    def on_response(self, callback: Callable[[str], Any]) -> None:
        """Register callback for LLM responses."""
        self._on_response = callback

    async def start(self) -> None:
        """Start the voice session."""
        if self._running:
            return

        self._running = True
        self._set_state(SessionState.LISTENING)

        # Load VAD model
        await self._load_vad_model()

        # Start processing loop
        self._process_task = asyncio.create_task(self._process_loop())

        logger.info(f"Session {self.session_id} started")

    async def stop(self) -> None:
        """Stop the voice session."""
        self._running = False
        self._set_state(SessionState.ENDED)

        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass

        logger.info(f"Session {self.session_id} stopped")

    def interrupt(self) -> None:
        """Interrupt the current response (barge-in)."""
        if self._state == SessionState.SPEAKING:
            self._interrupted = True
            self.transport.clear_output_queue()
            self._set_state(SessionState.INTERRUPTED)
            logger.info(f"Session {self.session_id} interrupted")

    async def _load_vad_model(self) -> None:
        """Load the Silero VAD model."""
        try:
            import torch

            logger.info("Loading Silero VAD model...")
            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                trust_repo=True,
            )
            self._vad_model = model
            self._vad_utils = utils
            # Reset VAD internal state (important for LSTM-based model)
            self._vad_model.reset_states()
            logger.info("*** VAD MODEL LOADED SUCCESSFULLY ***")
        except Exception as e:
            logger.warning(f"Could not load VAD model: {e}. Will use energy-based VAD as fallback.")
            # Will use simple energy-based VAD as fallback

    async def _process_loop(self) -> None:
        """Main processing loop - reads audio and detects speech."""
        frame_count = 0
        try:
            logger.info(f"Session {self.session_id}: Starting process loop, waiting for frames...")
            logger.info(f"Session {self.session_id}: Transport state: {self.transport.state}")
            logger.info(f"Session {self.session_id}: Transport input track: {self.transport._input_track}")

            async for frame in self.transport.read_frames():
                if not self._running:
                    logger.info(f"Session {self.session_id}: Process loop stopped (not running)")
                    break

                frame_count += 1
                if frame_count == 1:
                    logger.info(f"Session {self.session_id}: *** FIRST FRAME RECEIVED *** size={len(frame.data)} bytes")
                elif frame_count % 50 == 0:
                    logger.info(f"Session {self.session_id}: Processed {frame_count} frames, is_speech={self._is_speech}")

                # Process frame through VAD
                is_speech = await self._process_vad(frame)

                if is_speech and not self._is_speech:
                    # Speech started
                    await self._on_speech_started()

                elif not is_speech and self._is_speech:
                    # Check if silence is long enough
                    if self._check_silence_duration():
                        await self._on_speech_ended()

                # Collect audio during speech
                if self._is_speech:
                    self._speech_buffer.append(frame.data)

            logger.info(f"Session {self.session_id}: Process loop ended after {frame_count} frames")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in process loop: {e}")
            self._set_state(SessionState.ERROR)

    async def _process_vad(self, frame: AudioFrame) -> bool:
        """Process a frame through VAD.

        Args:
            frame: Audio frame to process.

        Returns:
            True if speech detected, False otherwise.
        """
        if self._vad_model is not None:
            # Use Silero VAD
            try:
                import torch

                # Convert frame to numpy array
                frame_audio = np.frombuffer(frame.data, dtype=np.int16)

                # Accumulate in buffer
                self._vad_buffer = np.concatenate([self._vad_buffer, frame_audio])

                # Process only if we have enough samples (512 for 16kHz)
                if len(self._vad_buffer) < self._vad_chunk_size:
                    # Not enough data yet, return previous state
                    return self._is_speech

                # Process all complete chunks
                speech_detected = False
                chunk_count = 0

                # Log buffer state
                if not hasattr(self, '_total_chunks'):
                    self._total_chunks = 0

                while len(self._vad_buffer) >= self._vad_chunk_size:
                    # Extract chunk of exactly 512 samples
                    chunk = self._vad_buffer[:self._vad_chunk_size]
                    self._vad_buffer = self._vad_buffer[self._vad_chunk_size:]
                    chunk_count += 1
                    self._total_chunks += 1

                    # Calculate audio energy for debugging
                    audio_energy = np.sqrt(np.mean(chunk.astype(np.float32) ** 2)) / 32768.0

                    # Convert to tensor (float32 normalized)
                    audio_float = chunk.astype(np.float32) / 32768.0
                    audio_tensor = torch.from_numpy(audio_float)

                    # Run VAD - IMPORTANT: use 16000 as sample rate, not frame.sample_rate
                    speech_prob = self._vad_model(audio_tensor, 16000).item()

                    # Log every 50th chunk for debugging
                    if self._total_chunks % 50 == 0:
                        # Debug: check audio range
                        audio_min = chunk.min()
                        audio_max = chunk.max()
                        audio_mean = chunk.mean()
                        logger.info(f"VAD CHUNK #{self._total_chunks}: energy={audio_energy:.4f}, speech_prob={speech_prob:.3f}, min={audio_min}, max={audio_max}, mean={audio_mean:.1f}")

                    # Log speech detection
                    if speech_prob > 0.3:
                        logger.info(f"*** VAD DETECTED *** speech_prob={speech_prob:.3f} energy={audio_energy:.4f}")

                    # Emit VAD level event
                    await self.event_emitter.emit(
                        EventType.VAD_LEVEL, {"level": speech_prob, "threshold": self.vad_config.threshold}
                    )

                    if speech_prob > self.vad_config.threshold:
                        speech_detected = True

                return speech_detected

            except Exception as e:
                logger.error(f"VAD error: {e}")
                return self._energy_vad(frame)
        else:
            # Fallback to energy-based VAD
            is_speech = self._energy_vad(frame)
            if is_speech:
                logger.debug("Energy VAD detected speech")
            return is_speech

    def _energy_vad(self, frame: AudioFrame) -> bool:
        """Simple energy-based VAD fallback.

        Args:
            frame: Audio frame to process.

        Returns:
            True if speech detected based on energy.
        """
        audio = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32)
        energy = np.sqrt(np.mean(audio**2)) / 32768.0
        # Increased threshold to avoid false positives from background noise
        return energy > 0.05  # Was 0.02 - too sensitive

    async def _on_speech_started(self) -> None:
        """Handle speech start event."""
        logger.info(f"*** SPEECH STARTED *** session={self.session_id}")

        self._is_speech = True
        self._speech_start_time = time.time()
        self._silence_start_time = None
        self._speech_buffer = []

        self._metrics.last_vad_start = time.time()

        self._set_state(SessionState.LISTENING)

        await self.event_emitter.emit(EventType.VAD_START, {"timestamp": time.time()})

        if self._on_speech_start:
            result = self._on_speech_start()
            if asyncio.iscoroutine(result):
                await result

        # If agent was speaking, interrupt
        if self._state == SessionState.SPEAKING:
            self.interrupt()

    async def _on_speech_ended(self) -> None:
        """Handle speech end event."""
        self._is_speech = False
        self._vad_buffer = np.array([], dtype=np.int16)  # Reset VAD buffer
        # Reset VAD internal LSTM state for fresh detection
        if self._vad_model is not None:
            self._vad_model.reset_states()
        speech_duration = time.time() - (self._speech_start_time or time.time())

        logger.info(f"*** SPEECH ENDED *** duration={speech_duration*1000:.0f}ms, buffer_size={len(self._speech_buffer)}")

        # Check minimum duration
        if speech_duration * 1000 < self.vad_config.min_speech_duration_ms:
            logger.info(f"Speech too short ({speech_duration*1000:.0f}ms < {self.vad_config.min_speech_duration_ms}ms), ignoring")
            self._speech_buffer = []
            return

        # Combine speech buffer
        audio_bytes = b"".join(self._speech_buffer)
        logger.info(f"*** PROCESSING SPEECH *** {len(audio_bytes)} bytes, {speech_duration*1000:.0f}ms")
        self._speech_buffer = []

        self._metrics.total_audio_duration_ms += speech_duration * 1000
        self._metrics.turn_count += 1

        await self.event_emitter.emit(
            EventType.VAD_END,
            {"timestamp": time.time(), "duration_ms": speech_duration * 1000},
        )

        self._set_state(SessionState.PROCESSING)

        if self._on_speech_end:
            logger.info("Calling on_speech_end callback...")
            result = self._on_speech_end(audio_bytes)
            if asyncio.iscoroutine(result):
                await result
            logger.info("on_speech_end callback completed")
        else:
            logger.warning("No on_speech_end callback registered!")

    def _check_silence_duration(self) -> bool:
        """Check if silence has been long enough to end speech.

        Returns:
            True if silence duration exceeds threshold.
        """
        if self._silence_start_time is None:
            self._silence_start_time = time.time()
            return False

        silence_duration = (time.time() - self._silence_start_time) * 1000
        return silence_duration >= self.vad_config.min_silence_duration_ms

    async def send_audio(self, audio_bytes: bytes) -> None:
        """Send audio to the browser (TTS output).

        Args:
            audio_bytes: PCM16 audio bytes to send.
        """
        if self._interrupted:
            self._interrupted = False
            return

        self._set_state(SessionState.SPEAKING)

        # Track first audio for latency metrics
        if self._metrics.last_tts_first_audio is None:
            self._metrics.last_tts_first_audio = time.time()

            # Calculate TTFA (Time to First Audio)
            if self._metrics.last_vad_start:
                self._metrics.ttfa = self._metrics.last_tts_first_audio - self._metrics.last_vad_start
                self._metrics.e2e = self._metrics.ttfa

        await self.transport.write_bytes(audio_bytes)

    async def send_audio_stream(self, audio_stream: AsyncIterator[bytes]) -> None:
        """Send streaming audio to the browser.

        Args:
            audio_stream: Async iterator of audio chunks.
        """
        self._set_state(SessionState.SPEAKING)
        first_chunk = True

        async for chunk in audio_stream:
            if self._interrupted:
                self._interrupted = False
                break

            if first_chunk:
                first_chunk = False
                self._metrics.last_tts_first_audio = time.time()

                if self._metrics.last_vad_start:
                    self._metrics.ttfa = self._metrics.last_tts_first_audio - self._metrics.last_vad_start
                    self._metrics.e2e = self._metrics.ttfa

            await self.transport.write_bytes(chunk)

        if not self._interrupted:
            self._set_state(SessionState.LISTENING)

    def reset_turn_metrics(self) -> None:
        """Reset per-turn metrics."""
        self._metrics.last_vad_start = None
        self._metrics.last_asr_end = None
        self._metrics.last_llm_start = None
        self._metrics.last_llm_first_token = None
        self._metrics.last_tts_start = None
        self._metrics.last_tts_first_audio = None
        self._metrics.ttfa = None
        self._metrics.ttft = None
        self._metrics.e2e = None
