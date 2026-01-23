"""WebSocket handler for the OpenAI Realtime API compatible protocol."""

import base64
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.session import RealtimeSession
from ..core.session_manager import SessionManager, get_session_manager
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
from ..models.conversation import ResponseStatus

logger = logging.getLogger(__name__)

router = APIRouter()


class WebSocketHandler:
    """Handles WebSocket connections for the Realtime API."""

    def __init__(
        self,
        websocket: WebSocket,
        session_manager: Optional[SessionManager] = None,
    ):
        """Initialize the handler.

        Args:
            websocket: The WebSocket connection.
            session_manager: Optional session manager.
        """
        self.websocket = websocket
        self.session_manager = session_manager or get_session_manager()
        self.session: Optional[RealtimeSession] = None

    async def handle_connection(self) -> None:
        """Handle the WebSocket connection lifecycle."""
        await self.websocket.accept()
        logger.info("WebSocket connection accepted")

        try:
            # Create session
            self.session = await self.session_manager.create_session()

            # Send session.created event
            event = build_session_created_event(self.session.id, self.session.config)
            await self._send_event(event)

            # Send conversation.created event
            conv_event = ConversationCreatedEvent(
                conversation=ConversationObject(id=self.session.conversation.id)
            )
            await self._send_event(conv_event)

            # Message loop
            await self._message_loop()

        except WebSocketDisconnect:
            logger.info(
                "WebSocket disconnected",
                extra={"session_id": self.session.id if self.session else None},
            )
        except Exception as e:
            logger.exception(f"WebSocket error: {e}")
            try:
                error_event = build_error_event(
                    error_type="server_error",
                    message=str(e),
                    code="internal_error",
                )
                await self._send_event(error_event)
            except Exception:
                pass
        finally:
            await self._cleanup()

    async def _message_loop(self) -> None:
        """Process incoming WebSocket messages."""
        while True:
            try:
                # Receive message (can be text or binary)
                message = await self.websocket.receive()

                if message["type"] == "websocket.receive":
                    if "text" in message:
                        await self._handle_text_message(message["text"])
                    elif "bytes" in message:
                        await self._handle_binary_message(message["bytes"])

                elif message["type"] == "websocket.disconnect":
                    break

            except WebSocketDisconnect:
                raise
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                error_event = build_error_event(
                    error_type="invalid_request_error",
                    message=str(e),
                    code="parse_error",
                )
                await self._send_event(error_event)

    async def _handle_text_message(self, text: str) -> None:
        """Handle a text message (JSON event).

        Args:
            text: The JSON message text.
        """
        try:
            data = json.loads(text)
            event = parse_client_event(data)
            await self._dispatch_event(event)
        except json.JSONDecodeError as e:
            error_event = build_error_event(
                error_type="invalid_request_error",
                message=f"Invalid JSON: {e}",
                code="json_parse_error",
            )
            await self._send_event(error_event)
        except ValueError as e:
            error_event = build_error_event(
                error_type="invalid_request_error",
                message=str(e),
                code="invalid_event",
            )
            await self._send_event(error_event)

    async def _handle_binary_message(self, data: bytes) -> None:
        """Handle a binary message (raw audio).

        Args:
            data: The raw audio bytes.
        """
        if self.session:
            self.session.append_audio(data)
            logger.debug(
                "Received binary audio",
                extra={
                    "session_id": self.session.id,
                    "bytes": len(data),
                },
            )

    async def _dispatch_event(self, event) -> None:
        """Dispatch a client event to the appropriate handler.

        Args:
            event: The parsed client event.
        """
        if not self.session:
            error_event = build_error_event(
                error_type="invalid_request_error",
                message="No active session",
                code="no_session",
            )
            await self._send_event(error_event)
            return

        event_type = event.type

        handlers = {
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

        handler = handlers.get(event_type)
        if handler:
            await handler(event)
        else:
            error_event = build_error_event(
                error_type="invalid_request_error",
                message=f"Unknown event type: {event_type}",
                code="unknown_event_type",
            )
            await self._send_event(error_event)

    async def _handle_session_update(self, event: SessionUpdateEvent) -> None:
        """Handle session.update event."""
        self.session.update_config(event.session)

        response = build_session_updated_event(self.session.id, self.session.config)
        await self._send_event(response)

        logger.info(
            "Session updated",
            extra={"session_id": self.session.id},
        )

    async def _handle_audio_append(self, event: InputAudioBufferAppendEvent) -> None:
        """Handle input_audio_buffer.append event."""
        try:
            audio_data = base64.b64decode(event.audio)
            self.session.append_audio(audio_data)

            logger.debug(
                "Audio appended",
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
            await self._send_event(error_event)

    async def _handle_audio_commit(self, event: InputAudioBufferCommitEvent) -> None:
        """Handle input_audio_buffer.commit event."""
        if self.session.input_audio_buffer.is_empty():
            error_event = build_error_event(
                error_type="invalid_request_error",
                message="Cannot commit empty audio buffer",
                code="empty_buffer",
            )
            await self._send_event(error_event)
            return

        previous_item_id = self.session.get_last_item_id()
        item_id = self.session.commit_audio()

        response = InputAudioBufferCommittedEvent(
            previous_item_id=previous_item_id,
            item_id=item_id,
        )
        await self._send_event(response)

        logger.info(
            "Audio buffer committed",
            extra={
                "session_id": self.session.id,
                "item_id": item_id,
            },
        )

    async def _handle_audio_clear(self, event: InputAudioBufferClearEvent) -> None:
        """Handle input_audio_buffer.clear event."""
        self.session.clear_audio()

        response = InputAudioBufferClearedEvent()
        await self._send_event(response)

        logger.info(
            "Audio buffer cleared",
            extra={"session_id": self.session.id},
        )

    async def _handle_item_create(self, event: ConversationItemCreateEvent) -> None:
        """Handle conversation.item.create event."""
        self.session.add_conversation_item(event.item, event.previous_item_id)

        response = ConversationItemCreatedEvent(
            previous_item_id=event.previous_item_id,
            item=event.item,
        )
        await self._send_event(response)

        logger.info(
            "Conversation item created",
            extra={
                "session_id": self.session.id,
                "item_id": event.item.id,
            },
        )

    async def _handle_item_truncate(self, event: ConversationItemTruncateEvent) -> None:
        """Handle conversation.item.truncate event."""
        success = self.session.truncate_conversation(event.item_id, event.audio_end_ms)

        if success:
            response = ConversationItemTruncatedEvent(
                item_id=event.item_id,
                content_index=event.content_index,
                audio_end_ms=event.audio_end_ms,
            )
            await self._send_event(response)

            logger.info(
                "Conversation item truncated",
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
            await self._send_event(error_event)

    async def _handle_item_delete(self, event: ConversationItemDeleteEvent) -> None:
        """Handle conversation.item.delete event."""
        success = self.session.delete_conversation_item(event.item_id)

        if success:
            response = ConversationItemDeletedEvent(item_id=event.item_id)
            await self._send_event(response)

            logger.info(
                "Conversation item deleted",
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
            await self._send_event(error_event)

    async def _handle_response_create(self, event: ResponseCreateEvent) -> None:
        """Handle response.create event."""
        response = self.session.create_response(event.response)

        response_event = ResponseCreatedEvent(response=response)
        await self._send_event(response_event)

        logger.info(
            "Response created",
            extra={
                "session_id": self.session.id,
                "response_id": response.id,
            },
        )

        # Note: Actual response generation will be implemented in Phase 2
        # For now, we immediately complete the response
        completed = self.session.complete_response()
        if completed:
            done_event = ResponseDoneEvent(response=completed)
            await self._send_event(done_event)

    async def _handle_response_cancel(self, event: ResponseCancelEvent) -> None:
        """Handle response.cancel event."""
        cancelled = self.session.cancel_response()

        if cancelled:
            done_event = ResponseDoneEvent(response=cancelled)
            await self._send_event(done_event)

            logger.info(
                "Response cancelled",
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
            await self._send_event(error_event)

    async def _send_event(self, event) -> None:
        """Send an event to the client.

        Args:
            event: The event to send (must have model_dump method).
        """
        data = event.model_dump(mode="json", exclude_none=True)
        await self.websocket.send_text(json.dumps(data))

    async def _cleanup(self) -> None:
        """Clean up resources when connection closes."""
        if self.session:
            await self.session_manager.delete_session(self.session.id)
            logger.info(
                "Session cleaned up",
                extra={"session_id": self.session.id},
            )


@router.websocket("/v1/realtime")
async def realtime_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for the Realtime API.

    This endpoint implements the OpenAI Realtime API compatible protocol.
    """
    handler = WebSocketHandler(websocket)
    await handler.handle_connection()
