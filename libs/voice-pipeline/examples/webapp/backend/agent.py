"""Voice Agent Session - WebSocket handler using voice-pipeline.

Uses sentence-level streaming for low latency (TTFA ~0.6-0.8s).

Implemented optimizations:
- TTS Warmup: Eliminates TTS cold-start (auto_warmup=True by default)
- Sentence Streaming: LLM and TTS run in parallel
- Producer-Consumer: asyncio.Queue connects LLM→TTS
- msgpack (optional): Binary serialization ~10x faster than JSON
- Provider Singleton: Models shared between sessions
- Limited Buffers: Prevents unbounded memory consumption

Features (Phase 7-9):
- Adaptive Turn-Taking: Contextual silence for end-of-turn detection
- Streaming Granularity: Clause-level for latency/naturalness balance
- Interruption Strategy: Backchannel-aware (distinguishes "uh-huh" from real interruption)
- Full-Duplex State: Supports simultaneous speech with intelligent decision-making
"""

import asyncio
import logging
import os
import time
from typing import Any, Optional, Union

from fastapi import WebSocket

from voice_pipeline import VoiceAgent
from voice_pipeline.chains import StreamingVoiceChain
from voice_pipeline.interfaces.turn_taking import TurnTakingContext, TurnTakingDecision
from voice_pipeline.interfaces.interruption import (
    InterruptionContext,
    InterruptionDecision,
)

logger = logging.getLogger(__name__)

# Maximum concurrent sessions
MAX_CONCURRENT_SESSIONS = 3

# Active sessions control
_active_sessions: set["VoiceAgentSession"] = set()
_sessions_lock = asyncio.Lock()

# Singleton: chain and VAD shared between sessions
_shared_chain: Optional[StreamingVoiceChain] = None
_shared_vad = None
_shared_chain_lock = asyncio.Lock()

# Model configuration via environment variables
LLM_MODEL = os.environ.get("VP_LLM_MODEL", "llama3.2:1b")
TTS_PROVIDER = os.environ.get("VP_TTS_PROVIDER", "kokoro")
TTS_VOICE = os.environ.get("VP_TTS_VOICE", None) or None
VP_LANGUAGE = os.environ.get("VP_LANGUAGE", None) or None
VP_SYSTEM_PROMPT = os.environ.get("VP_SYSTEM_PROMPT", None) or None

# Buffer limits
AUDIO_BUFFER_MAX_SIZE = 100  # ~100 chunks of 1024 bytes = ~100KB
VAD_BUFFER_MAX_BYTES = 32768  # 32KB maximum in VAD buffer
POST_SPEECH_COOLDOWN_MS = 500  # Cooldown after agent speaks (avoid echo)
BUFFER_OVERFLOW_LOG_INTERVAL = 50  # Log warning every N overflows


# =============================================================================
# Optimized serialization (optional msgpack)
# =============================================================================

def _has_msgpack() -> bool:
    """Check if msgpack is available."""
    try:
        import msgpack
        return True
    except ImportError:
        return False


class WebSocketSerializer:
    """WebSocket serializer with msgpack support.

    Uses msgpack if available and enabled, otherwise uses JSON.
    msgpack is ~10x faster and ~50% smaller than JSON.

    To enable msgpack in the JavaScript client:
    ```javascript
    import msgpack from '@msgpack/msgpack';

    ws.onmessage = (event) => {
        if (event.data instanceof Blob) {
            // Check if it's a msgpack message (starts with specific bytes)
            // or raw audio (PCM16)
            event.data.arrayBuffer().then(buf => {
                try {
                    const data = msgpack.decode(new Uint8Array(buf));
                    handleControlMessage(data);
                } catch {
                    handleAudioData(buf);
                }
            });
        }
    };
    ```
    """

    def __init__(self, use_msgpack: bool = False):
        """Initialize serializer.

        Args:
            use_msgpack: If True, use msgpack for control messages.
                        Requires msgpack installed and client support.
        """
        self.use_msgpack = use_msgpack and _has_msgpack()
        if use_msgpack and not _has_msgpack():
            logger.warning("msgpack requested but not installed. Using JSON.")

    async def send_json(self, websocket: WebSocket, data: dict[str, Any]) -> None:
        """Send control message (JSON or msgpack)."""
        if self.use_msgpack:
            import msgpack
            await websocket.send_bytes(msgpack.packb(data, use_bin_type=True))
        else:
            await websocket.send_json(data)


class VoiceAgentSession:
    """WebSocket session for real-time voice conversation.

    Uses VoiceAgent.builder() with streaming=True for low latency.

    Architecture:
        Audio → ASR → LLM (streaming) → StreamingStrategy → TTS → Audio
                            ↓
                    [chunk ready (clause/sentence/word)]
                            ↓
                      TTS starts

    Features:
        - Adaptive Turn-Taking: Contextual silence
        - Streaming Granularity: Clause-level (~200-400ms TTFA)
        - Backchannel Detection: "uh-huh", "yes" don't interrupt
        - Full-Duplex: Simultaneous speech with intelligent decision
        - TTS Warmup: Eliminates cold-start (~200-500ms savings)
        - msgpack (optional): ~10x faster serialization
    """

    def __init__(self, websocket: WebSocket, use_msgpack: bool = False):
        """Initialize voice agent session.

        Args:
            websocket: FastAPI WebSocket connection.
            use_msgpack: If True, use msgpack for control messages.
                        Default: False (JSON for browser compatibility).
        """
        self.websocket = websocket
        self.sample_rate = 16000

        # Serializer (JSON or msgpack)
        self._serializer = WebSocketSerializer(use_msgpack=use_msgpack)

        # Shared pipeline (singleton)
        self._chain: Optional[StreamingVoiceChain] = None
        self._vad = None
        self._is_listening = False
        # Limited buffer to prevent unbounded memory consumption
        self._audio_buffer: asyncio.Queue[bytes] = asyncio.Queue(
            maxsize=AUDIO_BUFFER_MAX_SIZE
        )
        self._speech_started = False
        self._speech_start_time = 0.0
        self._last_speech_time = 0.0
        # Flag to ignore audio during response processing
        self._is_processing = False
        # Mutable VAD buffer (bytearray avoids immutable bytes copies)
        self._vad_buffer = bytearray()
        # Turn-taking: number of complete turns in the conversation
        self._turn_count = 0
        self._last_agent_response_length = 0
        # Interruption tracking
        self._last_interruption_time = 0.0
        self._barge_in_speech_start = 0.0
        self._backchannel_count = 0
        self._interruption_count = 0
        # Post-speech cooldown (avoid TTS echo in microphone)
        self._processing_end_time = 0.0
        # Rate-limit for buffer overflow logging
        self._buffer_overflow_count = 0

    async def initialize(self):
        """Initialize voice agent with low-latency streaming.

        Uses singleton to share models between sessions,
        avoiding multiple copies of models in memory.
        """
        global _shared_chain, _shared_vad

        # Check session limit
        async with _sessions_lock:
            if len(_active_sessions) >= MAX_CONCURRENT_SESSIONS:
                raise RuntimeError(
                    f"Maximum of {MAX_CONCURRENT_SESSIONS} concurrent sessions reached"
                )
            _active_sessions.add(self)

        async with _shared_chain_lock:
            if _shared_chain is None:
                # Optimized for CPU (maximum speed, minimal memory):
                # Config via env vars: VP_LLM_MODEL, VP_TTS_PROVIDER, VP_TTS_VOICE
                # Ex: VP_TTS_PROVIDER=piper VP_TTS_VOICE=pt_BR-faber-medium
                #     VP_LLM_MODEL=llama3.2:1b
                logger.info(
                    f"Initializing shared providers (first session)...\n"
                    f"  LLM: {LLM_MODEL}, TTS: {TTS_PROVIDER} ({TTS_VOICE})"
                )

                builder = (
                    VoiceAgent.builder()
                    .asr("faster-whisper", model="base", language=VP_LANGUAGE,
                         compute_type="int8", vad_filter=True, beam_size=1,
                         vad_parameters={
                             "threshold": 0.5,
                             "min_silence_duration_ms": 250,
                             "speech_pad_ms": 200,
                         })
                    .llm("ollama", model=LLM_MODEL, keep_alive="-1")
                    .tts(TTS_PROVIDER, voice=TTS_VOICE)
                    .vad("silero")
                    .turn_taking("adaptive", base_threshold_ms=600)
                    .streaming_granularity("adaptive", first_chunk_words=3, clause_min_chars=10, language=VP_LANGUAGE or "en")
                    .interruption("backchannel", language=VP_LANGUAGE or "en")
                    .system_prompt(
                        VP_SYSTEM_PROMPT or
                        "You are a helpful voice assistant. "
                        "Respond very briefly (1-2 short sentences). "
                        "Be direct and concise."
                    )
                    .streaming(True)
                )

                _shared_chain = await builder.build_async()
                _shared_vad = builder._vad

                if hasattr(_shared_chain, 'warmup_time_ms') and _shared_chain.warmup_time_ms:
                    logger.info(f"TTS warmup completed in {_shared_chain.warmup_time_ms:.1f}ms")

                logger.info("Shared providers ready")
                logger.info(
                    f"Strategies: "
                    f"turn_taking={type(_shared_chain.turn_taking_controller).__name__ if _shared_chain.turn_taking_controller else 'None'}, "
                    f"streaming={_shared_chain.streaming_strategy.name if _shared_chain.streaming_strategy else 'SentenceDefault'}, "
                    f"interruption={_shared_chain.interruption_strategy.name if _shared_chain.interruption_strategy else 'None'}"
                )
            else:
                logger.info("Reusing shared providers")

        self._chain = _shared_chain
        self._vad = _shared_vad

        # Send active strategy info to frontend
        await self._send_strategy_info()

        logger.info("Voice agent ready (StreamingVoiceChain with optimizations)")

    async def _send_strategy_info(self):
        """Send active strategy information to the frontend."""
        chain = self._chain
        if not chain:
            return

        info = {
            "type": "strategy_info",
            "turn_taking": type(chain.turn_taking_controller).__name__ if chain.turn_taking_controller else "FixedSilence",
            "streaming": chain.streaming_strategy.name if chain.streaming_strategy else "SentenceStreamingStrategy(sentence)",
            "interruption": chain.interruption_strategy.name if chain.interruption_strategy else "ImmediateInterruption",
        }
        await self._serializer.send_json(self.websocket, info)

    async def configure(self, sample_rate: int = 16000, language: str = "pt"):
        """Update configuration."""
        self.sample_rate = sample_rate

    async def start_listening(self):
        """Start listening."""
        self._is_listening = True
        self._speech_started = False
        await self._send_status("listening")

    async def stop_listening(self):
        """Stop listening."""
        self._is_listening = False
        await self._send_status("idle")

    async def process_audio(self, audio_chunk: bytes):
        """Process audio chunk from client.

        Uses pluggable TurnTakingController to decide when the
        user's turn has ended. The controller receives full context
        (VAD, silence, speech duration) and returns a decision
        (CONTINUE, END_OF_TURN, BARGE_IN).

        When the agent is speaking (is_processing=True), VAD
        continues running to detect barge-in. The InterruptionStrategy
        decides if it's a backchannel ("uh-huh") or real interruption.

        Silero VAD expects chunks of 512 samples (for 16kHz).
        Frontend sends larger chunks, so we split here.
        """
        if not self._is_listening or not self._vad:
            return

        # Post-processing cooldown: ignore audio to avoid echo
        if self._processing_end_time > 0:
            elapsed_ms = (time.time() - self._processing_end_time) * 1000
            if elapsed_ms < POST_SPEECH_COOLDOWN_MS:
                return  # Still in cooldown, discard audio (likely echo)
            else:
                self._processing_end_time = 0.0  # Cooldown expired

        # Silero VAD expects 512 samples for 16kHz (1024 bytes in PCM16)
        VAD_CHUNK_SIZE = 512 * 2  # 512 samples * 2 bytes/sample

        # Accumulate in VAD buffer (mutable bytearray - no copies)
        self._vad_buffer.extend(audio_chunk)

        # Protect against excessive accumulation (discard old data)
        if len(self._vad_buffer) > VAD_BUFFER_MAX_BYTES:
            excess = len(self._vad_buffer) - VAD_BUFFER_MAX_BYTES
            del self._vad_buffer[:excess]
            logger.warning(f"VAD buffer overflow: discarded {excess} bytes")

        # Process correctly-sized chunks for VAD
        while len(self._vad_buffer) >= VAD_CHUNK_SIZE:
            vad_chunk = bytes(self._vad_buffer[:VAD_CHUNK_SIZE])
            del self._vad_buffer[:VAD_CHUNK_SIZE]

            vad_event = await self._vad.process(vad_chunk, self.sample_rate)

            # === Full-Duplex mode: VAD runs even during processing ===
            if self._is_processing:
                await self._handle_barge_in(vad_event)
                continue

            # === Normal mode: collect audio and detect end of turn ===
            if vad_event.is_speech:
                if not self._speech_started:
                    self._speech_started = True
                    self._speech_start_time = time.time()
                    await self._serializer.send_json(self.websocket, {"type": "vad", "event": "speech_start"})

                self._last_speech_time = time.time()
                # put_nowait with fallback: discard oldest chunk if buffer is full
                if self._audio_buffer.full():
                    try:
                        self._audio_buffer.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    self._buffer_overflow_count += 1
                    if self._buffer_overflow_count % BUFFER_OVERFLOW_LOG_INTERVAL == 1:
                        logger.warning(
                            f"Audio buffer full: discarded {self._buffer_overflow_count} chunks so far"
                        )
                await self._audio_buffer.put(vad_chunk)

            # Query TurnTakingController for decision
            turn_controller = (
                self._chain.turn_taking_controller if self._chain else None
            )
            if turn_controller and self._speech_started:
                now = time.time()
                silence_ms = (now - self._last_speech_time) * 1000 if not vad_event.is_speech else 0.0
                speech_ms = (self._last_speech_time - self._speech_start_time) * 1000

                context = TurnTakingContext(
                    is_speech=vad_event.is_speech,
                    speech_confidence=vad_event.confidence,
                    silence_duration_ms=silence_ms,
                    speech_duration_ms=speech_ms,
                    agent_is_speaking=self._is_processing,
                    conversation_turn_count=self._turn_count,
                    last_agent_response_length=self._last_agent_response_length,
                    sample_rate=self.sample_rate,
                )

                decision = await turn_controller.decide(context)

                if decision == TurnTakingDecision.END_OF_TURN:
                    await self._serializer.send_json(self.websocket, {"type": "vad", "event": "speech_end"})
                    turn_controller.reset()
                    await self._process_speech()
                    self._speech_started = False
                elif decision == TurnTakingDecision.BARGE_IN:
                    await self.interrupt()

            elif not turn_controller and self._speech_started and not vad_event.is_speech:
                # Fallback: fixed 800ms silence if no controller
                silence_ms = (time.time() - self._last_speech_time) * 1000
                if silence_ms >= 800:
                    await self._serializer.send_json(self.websocket, {"type": "vad", "event": "speech_end"})
                    await self._process_speech()
                    self._speech_started = False

    async def _handle_barge_in(self, vad_event):
        """Handle barge-in using InterruptionStrategy.

        When the agent is speaking and VAD detects user speech,
        queries the InterruptionStrategy to decide:
        - IGNORE: Noise or very short speech, ignore
        - BACKCHANNEL: "uh-huh", "ok" -- agent continues speaking
        - INTERRUPT_IMMEDIATE: Stop TTS immediately
        - INTERRUPT_GRACEFUL: Finish current chunk and stop
        """
        interruption_strategy = (
            self._chain.interruption_strategy if self._chain else None
        )

        if not interruption_strategy:
            # Fallback: old behavior (interrupt immediately)
            if vad_event.is_speech:
                if not self._barge_in_speech_start:
                    self._barge_in_speech_start = time.time()
                speech_ms = (time.time() - self._barge_in_speech_start) * 1000
                if speech_ms >= 200:
                    await self.interrupt()
                    self._barge_in_speech_start = 0.0
            else:
                self._barge_in_speech_start = 0.0
            return

        # Track speech start during barge-in
        if vad_event.is_speech:
            if not self._barge_in_speech_start:
                self._barge_in_speech_start = time.time()
                # Notify frontend that full-duplex mode started
                await self._serializer.send_json(self.websocket, {
                    "type": "full_duplex",
                    "event": "start",
                })
        else:
            if self._barge_in_speech_start:
                # Speech stopped during barge-in
                self._barge_in_speech_start = 0.0
                await self._serializer.send_json(self.websocket, {
                    "type": "full_duplex",
                    "event": "end",
                })
            return

        # Calculate context for InterruptionStrategy
        now = time.time()
        speech_duration_ms = (now - self._barge_in_speech_start) * 1000
        time_since_last = (
            (now - self._last_interruption_time) * 1000
            if self._last_interruption_time > 0 else 0.0
        )

        context = InterruptionContext(
            user_is_speaking=vad_event.is_speech,
            user_speech_duration_ms=speech_duration_ms,
            user_speech_confidence=vad_event.confidence,
            agent_is_speaking=True,
            time_since_last_interruption_ms=time_since_last,
            conversation_turn_count=self._turn_count,
            agent_response_text="",  # Not easily accessible here
        )

        decision = await interruption_strategy.decide(context)

        if decision == InterruptionDecision.IGNORE:
            return

        elif decision == InterruptionDecision.BACKCHANNEL:
            self._backchannel_count += 1
            # Notify frontend of backchannel (agent continues speaking)
            await self._serializer.send_json(self.websocket, {
                "type": "backchannel",
                "count": self._backchannel_count,
            })
            logger.debug(f"Backchannel #{self._backchannel_count} detected")
            # Reset speech timer to avoid re-trigger
            self._barge_in_speech_start = 0.0

        elif decision in (
            InterruptionDecision.INTERRUPT_IMMEDIATE,
            InterruptionDecision.INTERRUPT_GRACEFUL,
        ):
            self._interruption_count += 1
            self._last_interruption_time = time.time()
            interruption_strategy.on_interruption_executed(decision)

            # Notify interruption type
            await self._serializer.send_json(self.websocket, {
                "type": "interruption",
                "mode": decision.value,
                "count": self._interruption_count,
            })
            logger.info(
                f"Interruption #{self._interruption_count} ({decision.value}): "
                f"speech={speech_duration_ms:.0f}ms"
            )

            await self.interrupt()
            self._barge_in_speech_start = 0.0

    async def _process_speech(self):
        """Process collected speech with low-latency streaming."""
        self._is_processing = True
        await self._send_status("processing")

        try:
            # Collect audio
            chunks = []
            while not self._audio_buffer.empty():
                chunks.append(await self._audio_buffer.get())

            if not chunks:
                await self._send_status("listening")
                return

            audio_data = b"".join(chunks)

            # Stream response audio (low latency)
            await self._send_status("speaking")
            first_audio = True

            async for audio_chunk in self._chain.astream(audio_data):
                # Notify first audio
                if first_audio:
                    first_audio = False
                    # Send partial metrics
                    if self._chain.metrics and self._chain.metrics.ttfa:
                        await self._serializer.send_json(self.websocket, {
                            "type": "metrics",
                            "ttfa": round(self._chain.metrics.ttfa, 3),
                        })

                await self.websocket.send_bytes(audio_chunk.data)

            # Send final metrics
            if self._chain.metrics:
                metrics = self._chain.metrics
                strategy_name = (
                    self._chain.streaming_strategy.name
                    if self._chain.streaming_strategy
                    else "SentenceStreamer"
                )
                await self._serializer.send_json(self.websocket, {
                    "type": "metrics",
                    "ttft": round(metrics.ttft, 3) if metrics.ttft else None,
                    "ttfa": round(metrics.ttfa, 3) if metrics.ttfa else None,
                    "total": round(metrics.total_time, 3) if metrics.total_time else None,
                    "sentences": metrics.sentences_count,
                    "tokens": metrics.tokens_count,
                    "rtf": round(metrics.rtf, 2) if metrics.rtf else None,
                    "streaming_strategy": strategy_name,
                })

            # Text response + update context for turn-taking
            if self._chain.messages:
                last = self._chain.messages[-1]
                if last.get("role") == "assistant":
                    response_text = last.get("content", "")
                    await self._serializer.send_json(self.websocket, {
                        "type": "response",
                        "text": response_text,
                    })
                    # Update context for the TurnTakingController
                    self._turn_count += 1
                    self._last_agent_response_length = len(response_text)

        except Exception as e:
            logger.error(f"Speech processing error: {e}", exc_info=True)
            try:
                await self._serializer.send_json(self.websocket, {"type": "error", "message": str(e)})
            except Exception:
                logger.debug("WebSocket already disconnected, could not send error")

        finally:
            self._is_processing = False
            self._vad_buffer.clear()
            self._barge_in_speech_start = 0.0
            self._speech_started = False
            # Activate cooldown to avoid TTS echo
            self._processing_end_time = time.time()
            # Drain audio buffer (avoid processing stale/echo audio)
            while not self._audio_buffer.empty():
                try:
                    self._audio_buffer.get_nowait()
                except asyncio.QueueEmpty:
                    break
            if self._buffer_overflow_count > 0:
                logger.info(f"Total buffer overflow this turn: {self._buffer_overflow_count} chunks discarded")
                self._buffer_overflow_count = 0
            try:
                await self._send_status("listening")
            except Exception:
                pass

    async def _send_status(self, state: str):
        """Send status."""
        await self._serializer.send_json(self.websocket, {"type": "status", "state": state})

    async def interrupt(self):
        """Interrupt response (barge-in)."""
        if self._chain:
            self._chain.interrupt()
        self._speech_started = False
        await self._send_status("listening")
        await self._serializer.send_json(self.websocket, {"type": "interrupted"})

    async def reset(self):
        """Reset conversation."""
        if self._chain:
            self._chain.reset()
        self._vad_buffer.clear()
        self._turn_count = 0
        self._last_agent_response_length = 0
        self._backchannel_count = 0
        self._interruption_count = 0
        self._last_interruption_time = 0.0

    async def cleanup(self):
        """Clean up session resources.

        Releases buffers and removes the session from global control.
        Shared providers (chain, vad) are NOT disconnected
        as they are reused by other sessions.
        """
        self._is_listening = False
        self._vad_buffer.clear()

        # Drain audio buffer
        while not self._audio_buffer.empty():
            try:
                self._audio_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Remove from active sessions control
        async with _sessions_lock:
            _active_sessions.discard(self)
            remaining = len(_active_sessions)

        # Clear local references (without disconnecting the singleton)
        self._chain = None
        self._vad = None

        logger.info(f"Session cleaned up. Remaining active sessions: {remaining}")
