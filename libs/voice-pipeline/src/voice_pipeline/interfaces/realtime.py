"""Realtime (Speech-to-Speech) interface.

Interface for providers that support real-time bidirectional voice communication,
combining ASR, LLM, and TTS in a single connection.
"""

from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional, Union

from voice_pipeline.runnable import RunnableConfig, VoiceRunnable


class RealtimeEventType(Enum):
    """Types of realtime events."""

    # Connection events
    SESSION_CREATED = "session.created"
    SESSION_UPDATED = "session.updated"
    ERROR = "error"

    # Input events
    INPUT_AUDIO_BUFFER_COMMITTED = "input_audio_buffer.committed"
    INPUT_AUDIO_BUFFER_CLEARED = "input_audio_buffer.cleared"
    INPUT_AUDIO_BUFFER_SPEECH_STARTED = "input_audio_buffer.speech_started"
    INPUT_AUDIO_BUFFER_SPEECH_STOPPED = "input_audio_buffer.speech_stopped"

    # Conversation events
    CONVERSATION_ITEM_CREATED = "conversation.item.created"
    CONVERSATION_ITEM_DELETED = "conversation.item.deleted"
    CONVERSATION_ITEM_TRUNCATED = "conversation.item.truncated"

    # Response events
    RESPONSE_CREATED = "response.created"
    RESPONSE_DONE = "response.done"
    RESPONSE_OUTPUT_ITEM_ADDED = "response.output_item.added"
    RESPONSE_OUTPUT_ITEM_DONE = "response.output_item.done"
    RESPONSE_CONTENT_PART_ADDED = "response.content_part.added"
    RESPONSE_CONTENT_PART_DONE = "response.content_part.done"
    RESPONSE_TEXT_DELTA = "response.text.delta"
    RESPONSE_TEXT_DONE = "response.text.done"
    RESPONSE_AUDIO_DELTA = "response.audio.delta"
    RESPONSE_AUDIO_DONE = "response.audio.done"
    RESPONSE_AUDIO_TRANSCRIPT_DELTA = "response.audio_transcript.delta"
    RESPONSE_AUDIO_TRANSCRIPT_DONE = "response.audio_transcript.done"
    RESPONSE_FUNCTION_CALL_ARGUMENTS_DELTA = "response.function_call_arguments.delta"
    RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE = "response.function_call_arguments.done"

    # Rate limit events
    RATE_LIMITS_UPDATED = "rate_limits.updated"


@dataclass
class RealtimeEvent:
    """Event from realtime API."""

    event_type: RealtimeEventType
    """Type of the event."""

    event_id: Optional[str] = None
    """Unique event ID."""

    data: dict = field(default_factory=dict)
    """Event payload data."""

    # Convenience fields for common events
    text: Optional[str] = None
    """Text content (for text events)."""

    audio: Optional[bytes] = None
    """Audio content (for audio events)."""

    transcript: Optional[str] = None
    """Transcript content (for transcript events)."""

    error: Optional[str] = None
    """Error message (for error events)."""

    def __post_init__(self):
        """Extract convenience fields from data if not provided."""
        if self.text is None and "text" in self.data:
            self.text = self.data["text"]
        if self.transcript is None and "transcript" in self.data:
            self.transcript = self.data["transcript"]
        if self.error is None and "error" in self.data:
            error_data = self.data["error"]
            if isinstance(error_data, dict):
                self.error = error_data.get("message", str(error_data))
            else:
                self.error = str(error_data)


@dataclass
class RealtimeSessionConfig:
    """Configuration for a realtime session."""

    modalities: list[str] = field(default_factory=lambda: ["text", "audio"])
    """Modalities to enable (text, audio)."""

    voice: str = "alloy"
    """Voice for audio output."""

    instructions: Optional[str] = None
    """System instructions for the model."""

    input_audio_format: str = "pcm16"
    """Format for input audio (pcm16, g711_ulaw, g711_alaw)."""

    output_audio_format: str = "pcm16"
    """Format for output audio (pcm16, g711_ulaw, g711_alaw)."""

    input_audio_transcription: Optional[dict] = None
    """Configuration for input audio transcription."""

    turn_detection: Optional[dict] = None
    """Configuration for server-side turn detection (VAD)."""

    tools: list[dict] = field(default_factory=list)
    """Tools available to the model."""

    tool_choice: str = "auto"
    """How the model should choose tools."""

    temperature: float = 0.8
    """Sampling temperature."""

    max_response_output_tokens: Optional[int] = None
    """Maximum tokens in the response."""


# Input type for realtime: audio bytes or text
RealtimeInput = Union[bytes, str, dict]


class RealtimeInterface(VoiceRunnable[RealtimeInput, RealtimeEvent]):
    """Interface for Realtime (Speech-to-Speech) providers.

    Implementations should provide bidirectional real-time communication
    combining ASR, LLM, and TTS capabilities.

    Features:
    - Real-time audio input/output
    - Server-side VAD (voice activity detection)
    - Function calling support
    - Interruption handling (barge-in)

    Example implementation:
        class MyRealtime(RealtimeInterface):
            async def connect(self):
                self.ws = await websockets.connect(url)

            async def send_audio(self, audio_chunk):
                await self.ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(audio_chunk).decode()
                }))

            async def receive_events(self):
                async for message in self.ws:
                    event = parse_event(message)
                    yield event
    """

    name: str = "Realtime"

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the realtime service."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the realtime service."""
        pass

    @abstractmethod
    async def send_audio(self, audio_chunk: bytes) -> None:
        """Send audio chunk to the service.

        Args:
            audio_chunk: Audio data in the configured format.
        """
        pass

    @abstractmethod
    async def send_text(self, text: str) -> None:
        """Send text message to the service.

        Args:
            text: Text message to send.
        """
        pass

    @abstractmethod
    async def commit_audio(self) -> None:
        """Commit the audio buffer for processing.

        Call this when the user has finished speaking.
        """
        pass

    @abstractmethod
    async def cancel_response(self) -> None:
        """Cancel the current response (barge-in).

        Used when the user interrupts the assistant.
        """
        pass

    @abstractmethod
    async def create_response(self) -> None:
        """Trigger response generation.

        Usually called after committing audio or sending text.
        """
        pass

    @abstractmethod
    async def update_session(self, config: RealtimeSessionConfig) -> None:
        """Update session configuration.

        Args:
            config: New session configuration.
        """
        pass

    @abstractmethod
    def receive_events(self) -> AsyncIterator[RealtimeEvent]:
        """Receive events from the service.

        Yields:
            RealtimeEvent objects as they arrive.
        """
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the connection is active."""
        pass

    # Event handlers (optional, for convenience)
    def on_audio(self, callback: Callable[[bytes], None]) -> None:
        """Register callback for audio output.

        Args:
            callback: Function to call with audio chunks.
        """
        self._audio_callback = callback

    def on_text(self, callback: Callable[[str], None]) -> None:
        """Register callback for text output.

        Args:
            callback: Function to call with text.
        """
        self._text_callback = callback

    def on_transcript(self, callback: Callable[[str], None]) -> None:
        """Register callback for transcripts.

        Args:
            callback: Function to call with transcripts.
        """
        self._transcript_callback = callback

    def on_error(self, callback: Callable[[str], None]) -> None:
        """Register callback for errors.

        Args:
            callback: Function to call with error messages.
        """
        self._error_callback = callback

    # ==================== VoiceRunnable Implementation ====================

    async def ainvoke(
        self,
        input: RealtimeInput,
        config: Optional[RunnableConfig] = None,
    ) -> RealtimeEvent:
        """Send input and wait for response.

        For realtime APIs, this sends the input and returns the
        final response event.

        Args:
            input: Audio bytes, text string, or dict with both.
            config: Optional configuration.

        Returns:
            Final response event.
        """
        if isinstance(input, bytes):
            await self.send_audio(input)
            await self.commit_audio()
        elif isinstance(input, str):
            await self.send_text(input)
        elif isinstance(input, dict):
            if "audio" in input:
                await self.send_audio(input["audio"])
                await self.commit_audio()
            if "text" in input:
                await self.send_text(input["text"])

        await self.create_response()

        # Wait for response done event
        async for event in self.receive_events():
            if event.event_type == RealtimeEventType.RESPONSE_DONE:
                return event
            if event.event_type == RealtimeEventType.ERROR:
                raise RuntimeError(event.error or "Unknown error")

        raise RuntimeError("Connection closed without response")

    async def astream(
        self,
        input: RealtimeInput,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[RealtimeEvent]:
        """Stream events from the realtime service.

        Args:
            input: Audio bytes, text string, or dict with both.
            config: Optional configuration.

        Yields:
            RealtimeEvent objects as they arrive.
        """
        if isinstance(input, bytes):
            await self.send_audio(input)
            await self.commit_audio()
        elif isinstance(input, str):
            await self.send_text(input)
        elif isinstance(input, dict):
            if "audio" in input:
                await self.send_audio(input["audio"])
                await self.commit_audio()
            if "text" in input:
                await self.send_text(input["text"])

        await self.create_response()

        async for event in self.receive_events():
            yield event
            if event.event_type == RealtimeEventType.RESPONSE_DONE:
                break
