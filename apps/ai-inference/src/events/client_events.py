"""Client event models for the OpenAI Realtime API compatible protocol.

These are events sent from the client to the server.
"""

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from ..models.conversation import ConversationItem
from ..models.session import ResponseConfig, SessionConfig
from .types import ClientEventType


class BaseClientEvent(BaseModel):
    """Base class for all client events."""

    event_id: Optional[str] = Field(default=None, description="Optional event ID")


class SessionUpdateEvent(BaseClientEvent):
    """Update session configuration."""

    type: Literal[ClientEventType.SESSION_UPDATE] = ClientEventType.SESSION_UPDATE
    session: SessionConfig = Field(..., description="Session configuration to update")


class InputAudioBufferAppendEvent(BaseClientEvent):
    """Append audio data to the input buffer."""

    type: Literal[ClientEventType.INPUT_AUDIO_BUFFER_APPEND] = (
        ClientEventType.INPUT_AUDIO_BUFFER_APPEND
    )
    audio: str = Field(..., description="Base64-encoded audio data")


class InputAudioBufferCommitEvent(BaseClientEvent):
    """Commit the current input audio buffer."""

    type: Literal[ClientEventType.INPUT_AUDIO_BUFFER_COMMIT] = (
        ClientEventType.INPUT_AUDIO_BUFFER_COMMIT
    )


class InputAudioBufferClearEvent(BaseClientEvent):
    """Clear the input audio buffer."""

    type: Literal[ClientEventType.INPUT_AUDIO_BUFFER_CLEAR] = (
        ClientEventType.INPUT_AUDIO_BUFFER_CLEAR
    )


class ConversationItemCreateEvent(BaseClientEvent):
    """Create a new conversation item."""

    type: Literal[ClientEventType.CONVERSATION_ITEM_CREATE] = (
        ClientEventType.CONVERSATION_ITEM_CREATE
    )
    previous_item_id: Optional[str] = Field(
        default=None, description="ID of item to insert after"
    )
    item: ConversationItem = Field(..., description="Conversation item to create")


class ConversationItemTruncateEvent(BaseClientEvent):
    """Truncate a conversation item's audio."""

    type: Literal[ClientEventType.CONVERSATION_ITEM_TRUNCATE] = (
        ClientEventType.CONVERSATION_ITEM_TRUNCATE
    )
    item_id: str = Field(..., description="ID of item to truncate")
    content_index: int = Field(..., description="Index of content to truncate")
    audio_end_ms: int = Field(..., description="Audio end position in milliseconds")


class ConversationItemDeleteEvent(BaseClientEvent):
    """Delete a conversation item."""

    type: Literal[ClientEventType.CONVERSATION_ITEM_DELETE] = (
        ClientEventType.CONVERSATION_ITEM_DELETE
    )
    item_id: str = Field(..., description="ID of item to delete")


class ResponseCreateEvent(BaseClientEvent):
    """Create a new response."""

    type: Literal[ClientEventType.RESPONSE_CREATE] = ClientEventType.RESPONSE_CREATE
    response: Optional[ResponseConfig] = Field(
        default=None, description="Response configuration"
    )


class ResponseCancelEvent(BaseClientEvent):
    """Cancel the current response."""

    type: Literal[ClientEventType.RESPONSE_CANCEL] = ClientEventType.RESPONSE_CANCEL


# Union type for all client events with discriminator
ClientEvent = Annotated[
    Union[
        SessionUpdateEvent,
        InputAudioBufferAppendEvent,
        InputAudioBufferCommitEvent,
        InputAudioBufferClearEvent,
        ConversationItemCreateEvent,
        ConversationItemTruncateEvent,
        ConversationItemDeleteEvent,
        ResponseCreateEvent,
        ResponseCancelEvent,
    ],
    Field(discriminator="type"),
]


def parse_client_event(data: Dict[str, Any]) -> ClientEvent:
    """Parse a client event from a dictionary.

    Args:
        data: Dictionary containing the event data

    Returns:
        Parsed client event

    Raises:
        ValueError: If the event type is unknown or data is invalid
    """
    event_type = data.get("type")
    if not event_type:
        raise ValueError("Missing event type")

    event_map = {
        ClientEventType.SESSION_UPDATE: SessionUpdateEvent,
        ClientEventType.INPUT_AUDIO_BUFFER_APPEND: InputAudioBufferAppendEvent,
        ClientEventType.INPUT_AUDIO_BUFFER_COMMIT: InputAudioBufferCommitEvent,
        ClientEventType.INPUT_AUDIO_BUFFER_CLEAR: InputAudioBufferClearEvent,
        ClientEventType.CONVERSATION_ITEM_CREATE: ConversationItemCreateEvent,
        ClientEventType.CONVERSATION_ITEM_TRUNCATE: ConversationItemTruncateEvent,
        ClientEventType.CONVERSATION_ITEM_DELETE: ConversationItemDeleteEvent,
        ClientEventType.RESPONSE_CREATE: ResponseCreateEvent,
        ClientEventType.RESPONSE_CANCEL: ResponseCancelEvent,
    }

    event_class = event_map.get(event_type)
    if not event_class:
        raise ValueError(f"Unknown event type: {event_type}")

    return event_class.model_validate(data)
