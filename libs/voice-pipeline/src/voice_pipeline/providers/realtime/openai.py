"""OpenAI Realtime API provider.

Real-time speech-to-speech communication using OpenAI's Realtime API.
Supports bidirectional audio streaming over WebSocket.

Reference: https://platform.openai.com/docs/guides/realtime-websocket
"""

import asyncio
import base64
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Literal, Optional

from voice_pipeline.interfaces.realtime import (
    RealtimeEvent,
    RealtimeEventType,
    RealtimeInterface,
    RealtimeSessionConfig,
)
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)


# Available voices for OpenAI Realtime
OpenAIRealtimeVoice = Literal[
    "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"
]

# Available models
OpenAIRealtimeModel = Literal[
    "gpt-4o-realtime-preview",
    "gpt-4o-realtime-preview-2024-10-01",
    "gpt-4o-realtime-preview-2024-12-17",
    "gpt-4o-mini-realtime-preview",
    "gpt-4o-mini-realtime-preview-2024-12-17",
]

# Audio formats
OpenAIAudioFormat = Literal["pcm16", "g711_ulaw", "g711_alaw"]


@dataclass
class OpenAIRealtimeConfig(ProviderConfig):
    """Configuration for OpenAI Realtime API provider.

    Attributes:
        model: Model to use for realtime.
        voice: Voice for audio output.
        modalities: Enabled modalities (text, audio).
        instructions: System instructions for the model.
        input_audio_format: Format for input audio.
        output_audio_format: Format for output audio.
        temperature: Sampling temperature.
        max_response_output_tokens: Maximum tokens in response.
        turn_detection: Server-side VAD configuration.

    Example:
        >>> config = OpenAIRealtimeConfig(
        ...     model="gpt-4o-realtime-preview",
        ...     voice="alloy",
        ...     instructions="You are a helpful assistant.",
        ... )
        >>> realtime = OpenAIRealtimeProvider(config=config)
    """

    model: str = "gpt-4o-realtime-preview"
    """Model to use for realtime conversations."""

    voice: OpenAIRealtimeVoice = "alloy"
    """Voice for audio output."""

    modalities: list[str] = field(default_factory=lambda: ["text", "audio"])
    """Enabled modalities (text, audio)."""

    instructions: Optional[str] = None
    """System instructions for the model."""

    input_audio_format: OpenAIAudioFormat = "pcm16"
    """Format for input audio (pcm16, g711_ulaw, g711_alaw)."""

    output_audio_format: OpenAIAudioFormat = "pcm16"
    """Format for output audio (pcm16, g711_ulaw, g711_alaw)."""

    input_audio_transcription: bool = True
    """Enable transcription of input audio."""

    transcription_model: str = "whisper-1"
    """Model to use for input audio transcription."""

    temperature: float = 0.8
    """Sampling temperature (0.6 to 1.2)."""

    max_response_output_tokens: Optional[int] = None
    """Maximum tokens in the response. None for infinite."""

    turn_detection: Optional[dict] = field(default_factory=lambda: {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 500,
    })
    """Server-side VAD configuration. None to disable."""

    tools: list[dict] = field(default_factory=list)
    """Tools available to the model."""

    sample_rate: int = 24000
    """Sample rate for audio (24000 Hz for OpenAI Realtime)."""


class OpenAIRealtimeProvider(BaseProvider, RealtimeInterface):
    """OpenAI Realtime API provider for speech-to-speech communication.

    Uses WebSocket connection for bidirectional real-time audio streaming.
    Combines ASR, LLM, and TTS in a single low-latency connection.

    Features:
    - Real-time speech-to-speech
    - Server-side VAD (voice activity detection)
    - Function calling support
    - Interruption handling (barge-in)
    - Multiple voices

    Models:
    - gpt-4o-realtime-preview: Full model with all features
    - gpt-4o-mini-realtime-preview: Smaller, faster model

    Voices:
    - alloy, ash, ballad, coral, echo, sage, shimmer, verse

    Example:
        >>> realtime = OpenAIRealtimeProvider(
        ...     model="gpt-4o-realtime-preview",
        ...     voice="alloy",
        ...     instructions="You are a helpful assistant.",
        ... )
        >>> await realtime.connect()
        >>>
        >>> # Send audio and receive events
        >>> await realtime.send_audio(audio_chunk)
        >>> await realtime.commit_audio()
        >>> await realtime.create_response()
        >>>
        >>> async for event in realtime.receive_events():
        ...     if event.event_type == RealtimeEventType.RESPONSE_AUDIO_DELTA:
        ...         play_audio(event.audio)

    Attributes:
        provider_name: "openai-realtime"
        name: "OpenAIRealtime" (for VoiceRunnable)
    """

    provider_name: str = "openai-realtime"
    name: str = "OpenAIRealtime"

    def __init__(
        self,
        config: Optional[OpenAIRealtimeConfig] = None,
        model: Optional[str] = None,
        voice: Optional[str] = None,
        instructions: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs,
    ):
        """Initialize OpenAI Realtime provider.

        Args:
            config: Full configuration object.
            model: Model name (shortcut).
            voice: Voice name (shortcut).
            instructions: System instructions (shortcut).
            api_key: OpenAI API key (shortcut).
            **kwargs: Additional configuration options.
        """
        # Build config from parameters
        if config is None:
            config = OpenAIRealtimeConfig()

        # Apply shortcuts
        if model is not None:
            config.model = model
        if voice is not None:
            config.voice = voice
        if instructions is not None:
            config.instructions = instructions
        if api_key is not None:
            config.api_key = api_key

        super().__init__(config=config, **kwargs)

        self._realtime_config: OpenAIRealtimeConfig = config
        self._ws = None
        self._session_id: Optional[str] = None
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._receive_task: Optional[asyncio.Task] = None

        # Callbacks
        self._audio_callback: Optional[Callable[[bytes], None]] = None
        self._text_callback: Optional[Callable[[str], None]] = None
        self._transcript_callback: Optional[Callable[[str], None]] = None
        self._error_callback: Optional[Callable[[str], None]] = None

    @property
    def sample_rate(self) -> int:
        """Sample rate for audio."""
        return self._realtime_config.sample_rate

    @property
    def is_connected(self) -> bool:
        """Whether WebSocket connection is active."""
        return self._ws is not None and not self._ws.closed

    async def connect(self) -> None:
        """Establish WebSocket connection to OpenAI Realtime API."""
        await super().connect()

        try:
            import websockets
        except ImportError:
            raise ImportError(
                "websockets is required for OpenAI Realtime. "
                "Install with: pip install websockets"
            )

        # Get API key
        api_key = self._realtime_config.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenAI API key is required. "
                "Set OPENAI_API_KEY environment variable or pass api_key parameter."
            )

        # Build WebSocket URL
        base_url = self._realtime_config.api_base or "wss://api.openai.com/v1/realtime"
        url = f"{base_url}?model={self._realtime_config.model}"

        # Connect with authentication headers
        headers = {
            "Authorization": f"Bearer {api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        self._ws = await websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=30,
            ping_timeout=10,
        )

        # Start background receiver
        self._receive_task = asyncio.create_task(self._receive_loop())

        # Wait for session.created event
        event = await self._wait_for_event(RealtimeEventType.SESSION_CREATED, timeout=10.0)
        if event:
            self._session_id = event.data.get("session", {}).get("id")

        # Update session with our configuration
        await self._send_session_update()

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        self._session_id = None
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if connection is healthy."""
        if not self.is_connected:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="WebSocket not connected. Call connect() first.",
            )

        try:
            # Send a ping to check connection
            pong = await self._ws.ping()
            await asyncio.wait_for(pong, timeout=5.0)

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"OpenAI Realtime connected. Model: {self._realtime_config.model}",
                details={
                    "model": self._realtime_config.model,
                    "voice": self._realtime_config.voice,
                    "session_id": self._session_id,
                },
            )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"Connection health check failed: {e}",
            )

    async def _receive_loop(self) -> None:
        """Background task to receive WebSocket messages."""
        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                    event = self._parse_event(data)
                    await self._event_queue.put(event)

                    # Call registered callbacks
                    await self._dispatch_callbacks(event)

                except json.JSONDecodeError:
                    continue

        except asyncio.CancelledError:
            pass
        except Exception as e:
            error_event = RealtimeEvent(
                event_type=RealtimeEventType.ERROR,
                error=str(e),
            )
            await self._event_queue.put(error_event)

    def _parse_event(self, data: dict) -> RealtimeEvent:
        """Parse raw event data into RealtimeEvent.

        Args:
            data: Raw JSON event data.

        Returns:
            Parsed RealtimeEvent.
        """
        event_type_str = data.get("type", "")

        # Map string to enum
        try:
            event_type = RealtimeEventType(event_type_str)
        except ValueError:
            # Unknown event type, use ERROR as fallback
            event_type = RealtimeEventType.ERROR

        event = RealtimeEvent(
            event_type=event_type,
            event_id=data.get("event_id"),
            data=data,
        )

        # Extract audio if present
        if event_type == RealtimeEventType.RESPONSE_AUDIO_DELTA:
            delta = data.get("delta", "")
            if delta:
                event.audio = base64.b64decode(delta)

        # Extract text if present
        if event_type == RealtimeEventType.RESPONSE_TEXT_DELTA:
            event.text = data.get("delta", "")

        # Extract transcript if present
        if event_type == RealtimeEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA:
            event.transcript = data.get("delta", "")

        return event

    async def _dispatch_callbacks(self, event: RealtimeEvent) -> None:
        """Dispatch event to registered callbacks.

        Args:
            event: Event to dispatch.
        """
        if event.event_type == RealtimeEventType.RESPONSE_AUDIO_DELTA and self._audio_callback:
            if event.audio:
                self._audio_callback(event.audio)

        elif event.event_type == RealtimeEventType.RESPONSE_TEXT_DELTA and self._text_callback:
            if event.text:
                self._text_callback(event.text)

        elif event.event_type == RealtimeEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA and self._transcript_callback:
            if event.transcript:
                self._transcript_callback(event.transcript)

        elif event.event_type == RealtimeEventType.ERROR and self._error_callback:
            if event.error:
                self._error_callback(event.error)

    async def _wait_for_event(
        self,
        event_type: RealtimeEventType,
        timeout: float = 5.0,
    ) -> Optional[RealtimeEvent]:
        """Wait for a specific event type.

        Args:
            event_type: Event type to wait for.
            timeout: Maximum time to wait in seconds.

        Returns:
            The event if received, None if timeout.
        """
        try:
            deadline = time.time() + timeout
            while time.time() < deadline:
                remaining = deadline - time.time()
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=remaining,
                )
                if event.event_type == event_type:
                    return event
                # Put back events we're not waiting for
                await self._event_queue.put(event)
                await asyncio.sleep(0.01)
        except asyncio.TimeoutError:
            pass
        return None

    async def _send_event(self, event_type: str, **kwargs) -> None:
        """Send an event to the server.

        Args:
            event_type: Type of client event.
            **kwargs: Event payload.
        """
        if not self.is_connected:
            raise RuntimeError("WebSocket not connected. Call connect() first.")

        event = {
            "type": event_type,
            "event_id": str(uuid.uuid4()),
            **kwargs,
        }

        await self._ws.send(json.dumps(event))

    async def _send_session_update(self) -> None:
        """Send session.update event with current configuration."""
        session_config = {
            "modalities": self._realtime_config.modalities,
            "instructions": self._realtime_config.instructions,
            "voice": self._realtime_config.voice,
            "input_audio_format": self._realtime_config.input_audio_format,
            "output_audio_format": self._realtime_config.output_audio_format,
            "temperature": self._realtime_config.temperature,
        }

        if self._realtime_config.input_audio_transcription:
            session_config["input_audio_transcription"] = {
                "model": self._realtime_config.transcription_model,
            }

        if self._realtime_config.turn_detection:
            session_config["turn_detection"] = self._realtime_config.turn_detection

        if self._realtime_config.tools:
            session_config["tools"] = self._realtime_config.tools

        if self._realtime_config.max_response_output_tokens:
            session_config["max_response_output_tokens"] = (
                self._realtime_config.max_response_output_tokens
            )

        await self._send_event("session.update", session=session_config)

    # ==================== RealtimeInterface Implementation ====================

    async def send_audio(self, audio_chunk: bytes) -> None:
        """Send audio chunk to the service.

        Args:
            audio_chunk: Audio data (PCM16, mono, 24kHz).
        """
        if not self.is_connected:
            raise RuntimeError("WebSocket not connected. Call connect() first.")

        # Encode audio to base64
        audio_b64 = base64.b64encode(audio_chunk).decode("utf-8")

        await self._send_event(
            "input_audio_buffer.append",
            audio=audio_b64,
        )

    async def send_text(self, text: str) -> None:
        """Send text message to the service.

        Args:
            text: Text message to send.
        """
        if not self.is_connected:
            raise RuntimeError("WebSocket not connected. Call connect() first.")

        # Create a conversation item with the text
        await self._send_event(
            "conversation.item.create",
            item={
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": text,
                    }
                ],
            },
        )

    async def commit_audio(self) -> None:
        """Commit the audio buffer for processing."""
        await self._send_event("input_audio_buffer.commit")

    async def cancel_response(self) -> None:
        """Cancel the current response (barge-in)."""
        await self._send_event("response.cancel")

    async def create_response(self) -> None:
        """Trigger response generation."""
        await self._send_event("response.create")

    async def update_session(self, config: RealtimeSessionConfig) -> None:
        """Update session configuration.

        Args:
            config: New session configuration.
        """
        session_config = {
            "modalities": config.modalities,
            "voice": config.voice,
            "input_audio_format": config.input_audio_format,
            "output_audio_format": config.output_audio_format,
            "temperature": config.temperature,
        }

        if config.instructions:
            session_config["instructions"] = config.instructions

        if config.input_audio_transcription:
            session_config["input_audio_transcription"] = config.input_audio_transcription

        if config.turn_detection:
            session_config["turn_detection"] = config.turn_detection

        if config.tools:
            session_config["tools"] = config.tools

        if config.max_response_output_tokens:
            session_config["max_response_output_tokens"] = config.max_response_output_tokens

        await self._send_event("session.update", session=session_config)

    async def receive_events(self) -> AsyncIterator[RealtimeEvent]:
        """Receive events from the service.

        Yields:
            RealtimeEvent objects as they arrive.
        """
        while self.is_connected:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=0.1,
                )
                self._metrics.record_success(0.0)
                yield event
            except asyncio.TimeoutError:
                continue

    async def clear_audio_buffer(self) -> None:
        """Clear the input audio buffer."""
        await self._send_event("input_audio_buffer.clear")

    async def truncate_conversation(
        self,
        item_id: str,
        content_index: int,
        audio_end_ms: int,
    ) -> None:
        """Truncate a conversation item.

        Used when the user interrupts to remove unplayed audio.

        Args:
            item_id: ID of the conversation item.
            content_index: Index of the content part.
            audio_end_ms: Audio end position in milliseconds.
        """
        await self._send_event(
            "conversation.item.truncate",
            item_id=item_id,
            content_index=content_index,
            audio_end_ms=audio_end_ms,
        )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"OpenAIRealtimeProvider("
            f"model={self._realtime_config.model!r}, "
            f"voice={self._realtime_config.voice!r}, "
            f"connected={self.is_connected})"
        )
