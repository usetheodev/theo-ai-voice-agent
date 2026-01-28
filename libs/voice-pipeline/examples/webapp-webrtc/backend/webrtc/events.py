"""DataChannel event emitter for WebRTC communication."""

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import msgpack

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Types of events that can be sent via DataChannel."""

    # Connection events
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"

    # VAD events
    VAD_START = "vad_start"
    VAD_END = "vad_end"
    VAD_LEVEL = "vad_level"

    # ASR events
    ASR_START = "asr_start"
    ASR_PARTIAL = "asr_partial"
    ASR_FINAL = "asr_final"

    # LLM events
    LLM_START = "llm_start"
    LLM_TOKEN = "llm_token"
    LLM_END = "llm_end"

    # TTS events
    TTS_START = "tts_start"
    TTS_CHUNK = "tts_chunk"
    TTS_END = "tts_end"

    # Tool events
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_FEEDBACK = "tool_feedback"

    # Memory events
    MEMORY_RECALL = "memory_recall"
    MEMORY_SAVE = "memory_save"

    # Permission events
    PERMISSION_REQUEST = "permission_request"
    PERMISSION_RESPONSE = "permission_response"

    # MCP events
    MCP_CONNECTED = "mcp_connected"
    MCP_DISCONNECTED = "mcp_disconnected"
    MCP_TOOLS = "mcp_tools"

    # Agent state events
    AGENT_STATE = "agent_state"
    AGENT_TURN = "agent_turn"
    AGENT_READY = "agent_ready"

    # Metrics
    METRICS = "metrics"


@dataclass
class Event:
    """An event to be sent via DataChannel."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    sequence: int = 0

    def to_msgpack(self) -> bytes:
        """Serialize event to msgpack bytes."""
        return msgpack.packb(
            {
                "type": self.type.value,
                "data": self.data,
                "timestamp": self.timestamp,
                "sequence": self.sequence,
            }
        )

    @classmethod
    def from_msgpack(cls, data: bytes) -> "Event":
        """Deserialize event from msgpack bytes."""
        unpacked = msgpack.unpackb(data, raw=False)
        return cls(
            type=EventType(unpacked["type"]),
            data=unpacked.get("data", {}),
            timestamp=unpacked.get("timestamp", time.time()),
            sequence=unpacked.get("sequence", 0),
        )


EventHandler = Callable[[Event], None]
AsyncEventHandler = Callable[[Event], Any]


class DataChannelEventEmitter:
    """Emitter for events over WebRTC DataChannel."""

    def __init__(self):
        """Initialize the event emitter."""
        self._datachannel: Optional[Any] = None  # RTCDataChannel
        self._handlers: dict[EventType, list[AsyncEventHandler]] = {}
        self._sequence = 0
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._running = False
        self._send_task: Optional[asyncio.Task] = None

    def set_datachannel(self, datachannel: Any) -> None:
        """Set the DataChannel to use for sending events.

        Args:
            datachannel: RTCDataChannel instance from aiortc.
        """
        self._datachannel = datachannel

        # Set up message handler
        @datachannel.on("message")
        async def on_message(message: bytes | str):
            try:
                if isinstance(message, str):
                    message = message.encode()
                event = Event.from_msgpack(message)
                await self._dispatch(event)
            except Exception as e:
                logger.error(f"Error parsing DataChannel message: {e}")

    def on(self, event_type: EventType, handler: AsyncEventHandler) -> None:
        """Register an event handler.

        Args:
            event_type: Type of event to handle.
            handler: Async function to call when event is received.
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def off(self, event_type: EventType, handler: AsyncEventHandler) -> None:
        """Unregister an event handler.

        Args:
            event_type: Type of event.
            handler: Handler to remove.
        """
        if event_type in self._handlers:
            self._handlers[event_type] = [h for h in self._handlers[event_type] if h != handler]

    async def emit(self, event_type: EventType, data: Optional[dict[str, Any]] = None) -> None:
        """Emit an event to the remote peer.

        Args:
            event_type: Type of event to emit.
            data: Event data payload.
        """
        self._sequence += 1
        event = Event(type=event_type, data=data or {}, sequence=self._sequence)

        if self._datachannel and self._datachannel.readyState == "open":
            try:
                self._datachannel.send(event.to_msgpack())
                logger.debug(f"Sent event: {event_type.value}")
            except Exception as e:
                logger.error(f"Error sending event: {e}")
                # Queue for later if send fails
                await self._queue.put(event)
        else:
            # Queue event for when channel is ready
            await self._queue.put(event)

    def emit_sync(self, event_type: EventType, data: Optional[dict[str, Any]] = None) -> None:
        """Emit an event synchronously (fire and forget).

        Args:
            event_type: Type of event to emit.
            data: Event data payload.
        """
        self._sequence += 1
        event = Event(type=event_type, data=data or {}, sequence=self._sequence)

        if self._datachannel and self._datachannel.readyState == "open":
            try:
                self._datachannel.send(event.to_msgpack())
            except Exception as e:
                logger.error(f"Error sending event: {e}")

    async def _dispatch(self, event: Event) -> None:
        """Dispatch a received event to registered handlers.

        Args:
            event: Event to dispatch.
        """
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Error in event handler for {event.type}: {e}")

    async def start(self) -> None:
        """Start the event emitter background task."""
        self._running = True
        self._send_task = asyncio.create_task(self._send_loop())

    async def stop(self) -> None:
        """Stop the event emitter."""
        self._running = False
        if self._send_task:
            self._send_task.cancel()
            try:
                await self._send_task
            except asyncio.CancelledError:
                pass

    async def _send_loop(self) -> None:
        """Background task to send queued events."""
        while self._running:
            try:
                # Wait for events with timeout
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)

                # Try to send if channel is ready
                if self._datachannel and self._datachannel.readyState == "open":
                    try:
                        self._datachannel.send(event.to_msgpack())
                    except Exception as e:
                        logger.error(f"Error sending queued event: {e}")
                        # Re-queue if failed
                        await self._queue.put(event)
                        await asyncio.sleep(0.1)
                else:
                    # Re-queue if channel not ready
                    await self._queue.put(event)
                    await asyncio.sleep(0.1)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in send loop: {e}")
                await asyncio.sleep(0.1)

    async def flush_queue(self) -> None:
        """Send all queued events."""
        while not self._queue.empty():
            event = await self._queue.get()
            if self._datachannel and self._datachannel.readyState == "open":
                try:
                    self._datachannel.send(event.to_msgpack())
                except Exception as e:
                    logger.error(f"Error flushing event: {e}")
