"""DataChannel handler for WebRTC event communication."""

import base64
import json
import logging
from typing import Any, Dict, Optional

from aiortc import RTCDataChannel

from ..core.session import RealtimeSession
from ..events import (
    ClientEventType,
    ConversationItemCreateEvent,
    ConversationItemDeleteEvent,
    ConversationItemTruncateEvent,
    InputAudioBufferAppendEvent,
    InputAudioBufferClearEvent,
    InputAudioBufferCommitEvent,
    ResponseCancelEvent,
    ResponseCreateEvent,
    SessionUpdateEvent,
    parse_client_event,
)
from ..events.server_events import (
    ConversationCreatedEvent,
    ConversationItemCreatedEvent,
    ConversationItemDeletedEvent,
    ConversationItemTruncatedEvent,
    ConversationObject,
    InputAudioBufferClearedEvent,
    InputAudioBufferCommittedEvent,
    ResponseCreatedEvent,
    ResponseDoneEvent,
    build_error_event,
    build_session_created_event,
    build_session_updated_event,
)

logger = logging.getLogger(__name__)


class DataChannelHandler:
    """Handles event communication via WebRTC DataChannel.

    This class processes JSON events sent through the DataChannel,
    implementing the same protocol as the WebSocket handler but over
    WebRTC's SCTP-based DataChannel.
    """

    def __init__(
        self,
        session: RealtimeSession,
        datachannel: RTCDataChannel,
    ):
        """Initialize the DataChannel handler.

        Args:
            session: The associated RealtimeSession instance.
            datachannel: The RTCDataChannel for communication.
        """
        self.session = session
        self.datachannel = datachannel

        # Event type to handler mapping
        self._handlers = {
            ClientEventType.SESSION_UPDATE: self._handle_session_update,
            ClientEventType.INPUT_AUDIO_BUFFER_APPEND: self._handle_audio_append,
            ClientEventType.INPUT_AUDIO_BUFFER_COMMIT: self._handle_audio_commit,
            ClientEventType.INPUT_AUDIO_BUFFER_CLEAR: self._handle_audio_clear,
            ClientEventType.CONVERSATION_ITEM_CREATE: self._handle_item_create,
            ClientEventType.CONVERSATION_ITEM_TRUNCATE: self._handle_item_truncate,
            ClientEventType.CONVERSATION_ITEM_DELETE: self._handle_item_delete,
            ClientEventType.RESPONSE_CREATE: self._handle_response_create,
            ClientEventType.RESPONSE_CANCEL: self._handle_response_cancel,
        }

    async def send_session_created(self) -> None:
        """Send initial session.created and conversation.created events."""
        # Send session.created
        session_event = build_session_created_event(
            self.session.id,
            self.session.config,
        )
        await self.send_event(session_event)

        # Send conversation.created
        conv_event = ConversationCreatedEvent(
            conversation=ConversationObject(id=self.session.conversation.id)
        )
        await self.send_event(conv_event)

        logger.info(
            "Session events sent via DataChannel",
            extra={"session_id": self.session.id},
        )

    async def on_message(self, message: str) -> None:
        """Process incoming DataChannel message.

        Args:
            message: The JSON message string.
        """
        try:
            data = json.loads(message)
            event = parse_client_event(data)
            await self._dispatch_event(event)

        except json.JSONDecodeError as e:
            logger.warning(
                "Invalid JSON in DataChannel message",
                extra={
                    "session_id": self.session.id,
                    "error": str(e),
                },
            )
            error_event = build_error_event(
                error_type="invalid_request_error",
                message=f"Invalid JSON: {e}",
                code="json_parse_error",
            )
            await self.send_event(error_event)

        except ValueError as e:
            logger.warning(
                "Invalid event in DataChannel message",
                extra={
                    "session_id": self.session.id,
                    "error": str(e),
                },
            )
            error_event = build_error_event(
                error_type="invalid_request_error",
                message=str(e),
                code="invalid_event",
            )
            await self.send_event(error_event)

        except Exception as e:
            logger.exception(
                "Error processing DataChannel message",
                extra={"session_id": self.session.id},
            )
            error_event = build_error_event(
                error_type="server_error",
                message=str(e),
                code="internal_error",
            )
            await self.send_event(error_event)

    async def _dispatch_event(self, event: Any) -> None:
        """Dispatch event to appropriate handler.

        Args:
            event: The parsed client event.
        """
        handler = self._handlers.get(event.type)

        if handler:
            await handler(event)
        else:
            logger.warning(
                "Unknown event type",
                extra={
                    "session_id": self.session.id,
                    "event_type": event.type,
                },
            )
            error_event = build_error_event(
                error_type="invalid_request_error",
                message=f"Unknown event type: {event.type}",
                code="unknown_event_type",
            )
            await self.send_event(error_event)

    async def send_event(self, event: Any) -> None:
        """Send event to client via DataChannel.

        Args:
            event: The event to send (must have model_dump method).
        """
        if self.datachannel.readyState != "open":
            logger.warning(
                "Cannot send event, DataChannel not open",
                extra={
                    "session_id": self.session.id,
                    "state": self.datachannel.readyState,
                },
            )
            return

        data = event.model_dump(mode="json", exclude_none=True)
        self.datachannel.send(json.dumps(data))

    # Event Handlers (mirroring WebSocket handler logic)

    async def _handle_session_update(self, event: SessionUpdateEvent) -> None:
        """Handle session.update event."""
        self.session.update_config(event.session)

        response = build_session_updated_event(
            self.session.id,
            self.session.config,
        )
        await self.send_event(response)

        logger.info(
            "Session updated via DataChannel",
            extra={"session_id": self.session.id},
        )

    async def _handle_audio_append(self, event: InputAudioBufferAppendEvent) -> None:
        """Handle input_audio_buffer.append event."""
        try:
            audio_data = base64.b64decode(event.audio)
            self.session.append_audio(audio_data)

            logger.debug(
                "Audio appended via DataChannel",
                extra={
                    "session_id": self.session.id,
                    "bytes": len(audio_data),
                    "total_duration_ms": self.session.input_audio_buffer.total_duration_ms,
                },
            )
        except Exception as e:
            error_event = build_error_event(
                error_type="invalid_request_error",
                message=f"Invalid audio data: {e}",
                code="invalid_audio",
            )
            await self.send_event(error_event)

    async def _handle_audio_commit(self, event: InputAudioBufferCommitEvent) -> None:
        """Handle input_audio_buffer.commit event."""
        if self.session.input_audio_buffer.is_empty():
            error_event = build_error_event(
                error_type="invalid_request_error",
                message="Cannot commit empty audio buffer",
                code="empty_buffer",
            )
            await self.send_event(error_event)
            return

        previous_item_id = self.session.get_last_item_id()
        item_id = self.session.commit_audio()

        response = InputAudioBufferCommittedEvent(
            previous_item_id=previous_item_id,
            item_id=item_id,
        )
        await self.send_event(response)

        logger.info(
            "Audio buffer committed via DataChannel",
            extra={
                "session_id": self.session.id,
                "item_id": item_id,
            },
        )

    async def _handle_audio_clear(self, event: InputAudioBufferClearEvent) -> None:
        """Handle input_audio_buffer.clear event."""
        self.session.clear_audio()

        response = InputAudioBufferClearedEvent()
        await self.send_event(response)

        logger.info(
            "Audio buffer cleared via DataChannel",
            extra={"session_id": self.session.id},
        )

    async def _handle_item_create(self, event: ConversationItemCreateEvent) -> None:
        """Handle conversation.item.create event."""
        self.session.add_conversation_item(event.item, event.previous_item_id)

        response = ConversationItemCreatedEvent(
            previous_item_id=event.previous_item_id,
            item=event.item,
        )
        await self.send_event(response)

        logger.info(
            "Conversation item created via DataChannel",
            extra={
                "session_id": self.session.id,
                "item_id": event.item.id,
            },
        )

    async def _handle_item_truncate(self, event: ConversationItemTruncateEvent) -> None:
        """Handle conversation.item.truncate event."""
        success = self.session.truncate_conversation(
            event.item_id,
            event.audio_end_ms,
        )

        if success:
            response = ConversationItemTruncatedEvent(
                item_id=event.item_id,
                content_index=event.content_index,
                audio_end_ms=event.audio_end_ms,
            )
            await self.send_event(response)

            logger.info(
                "Conversation item truncated via DataChannel",
                extra={
                    "session_id": self.session.id,
                    "item_id": event.item_id,
                },
            )
        else:
            error_event = build_error_event(
                error_type="invalid_request_error",
                message=f"Item {event.item_id} not found",
                code="item_not_found",
            )
            await self.send_event(error_event)

    async def _handle_item_delete(self, event: ConversationItemDeleteEvent) -> None:
        """Handle conversation.item.delete event."""
        success = self.session.delete_conversation_item(event.item_id)

        if success:
            response = ConversationItemDeletedEvent(item_id=event.item_id)
            await self.send_event(response)

            logger.info(
                "Conversation item deleted via DataChannel",
                extra={
                    "session_id": self.session.id,
                    "item_id": event.item_id,
                },
            )
        else:
            error_event = build_error_event(
                error_type="invalid_request_error",
                message=f"Item {event.item_id} not found",
                code="item_not_found",
            )
            await self.send_event(error_event)

    async def _handle_response_create(self, event: ResponseCreateEvent) -> None:
        """Handle response.create event."""
        response = self.session.create_response(event.response)

        response_event = ResponseCreatedEvent(response=response)
        await self.send_event(response_event)

        logger.info(
            "Response created via DataChannel",
            extra={
                "session_id": self.session.id,
                "response_id": response.id,
            },
        )

        # Note: Actual response generation will be implemented in Phase 2
        # For now, immediately complete the response
        completed = self.session.complete_response()
        if completed:
            done_event = ResponseDoneEvent(response=completed)
            await self.send_event(done_event)

    async def _handle_response_cancel(self, event: ResponseCancelEvent) -> None:
        """Handle response.cancel event."""
        cancelled = self.session.cancel_response()

        if cancelled:
            done_event = ResponseDoneEvent(response=cancelled)
            await self.send_event(done_event)

            logger.info(
                "Response cancelled via DataChannel",
                extra={
                    "session_id": self.session.id,
                    "response_id": cancelled.id,
                },
            )
        else:
            error_event = build_error_event(
                error_type="invalid_request_error",
                message="No response to cancel",
                code="no_active_response",
            )
            await self.send_event(error_event)
