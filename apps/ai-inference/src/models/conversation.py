"""Conversation models for the AI Inference service."""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class ItemType(str, Enum):
    """Conversation item types."""

    MESSAGE = "message"
    FUNCTION_CALL = "function_call"
    FUNCTION_CALL_OUTPUT = "function_call_output"


class ItemRole(str, Enum):
    """Message roles."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ItemStatus(str, Enum):
    """Item status."""

    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    INCOMPLETE = "incomplete"


class ContentType(str, Enum):
    """Content types."""

    INPUT_TEXT = "input_text"
    INPUT_AUDIO = "input_audio"
    TEXT = "text"
    AUDIO = "audio"


class TextContent(BaseModel):
    """Text content in a message."""

    type: Literal["input_text", "text"] = Field(..., description="Content type")
    text: str = Field(..., description="Text content")


class AudioContent(BaseModel):
    """Audio content in a message."""

    type: Literal["input_audio", "audio"] = Field(..., description="Content type")
    audio: Optional[str] = Field(default=None, description="Base64-encoded audio")
    transcript: Optional[str] = Field(default=None, description="Audio transcript")


MessageContent = Union[TextContent, AudioContent]


class FunctionCall(BaseModel):
    """Function call content."""

    name: str = Field(..., description="Function name")
    arguments: str = Field(..., description="JSON-encoded arguments")
    call_id: str = Field(..., description="Function call ID")


class FunctionCallOutput(BaseModel):
    """Function call output content."""

    call_id: str = Field(..., description="Function call ID")
    output: str = Field(..., description="Function output")


class ConversationItem(BaseModel):
    """A conversation item (message, function call, or function output)."""

    id: str = Field(..., description="Item ID")
    object: Literal["realtime.item"] = Field(
        default="realtime.item", description="Object type"
    )
    type: ItemType = Field(..., description="Item type")
    status: ItemStatus = Field(
        default=ItemStatus.COMPLETED, description="Item status"
    )
    role: Optional[ItemRole] = Field(default=None, description="Role (for messages)")
    content: Optional[List[MessageContent]] = Field(
        default=None, description="Content (for messages)"
    )
    call_id: Optional[str] = Field(
        default=None, description="Call ID (for function calls/outputs)"
    )
    name: Optional[str] = Field(
        default=None, description="Function name (for function calls)"
    )
    arguments: Optional[str] = Field(
        default=None, description="Function arguments (for function calls)"
    )
    output: Optional[str] = Field(
        default=None, description="Function output (for function call outputs)"
    )


class Conversation(BaseModel):
    """A conversation consisting of multiple items."""

    id: str = Field(..., description="Conversation ID")
    object: Literal["realtime.conversation"] = Field(
        default="realtime.conversation", description="Object type"
    )
    items: List[ConversationItem] = Field(
        default_factory=list, description="Conversation items"
    )

    def add_item(self, item: ConversationItem) -> None:
        """Add an item to the conversation."""
        self.items.append(item)

    def get_item(self, item_id: str) -> Optional[ConversationItem]:
        """Get an item by ID."""
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def truncate_at(self, item_id: str, audio_end_ms: int) -> bool:
        """Truncate conversation at a specific item and audio position."""
        for i, item in enumerate(self.items):
            if item.id == item_id:
                # Truncate items after this one
                self.items = self.items[: i + 1]
                # Note: Audio truncation would be handled by the session
                return True
        return False


class ResponseOutput(BaseModel):
    """Output item in a response."""

    id: str = Field(..., description="Output item ID")
    object: Literal["realtime.item"] = Field(
        default="realtime.item", description="Object type"
    )
    type: ItemType = Field(..., description="Item type")
    status: ItemStatus = Field(..., description="Item status")
    role: Optional[ItemRole] = Field(default=None, description="Role")
    content: Optional[List[MessageContent]] = Field(default=None, description="Content")


class ResponseStatus(str, Enum):
    """Response status."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class ResponseStatusDetails(BaseModel):
    """Details about response status."""

    type: str = Field(..., description="Status detail type")
    reason: Optional[str] = Field(default=None, description="Reason for status")
    error: Optional[Dict[str, Any]] = Field(default=None, description="Error details")


class UsageStats(BaseModel):
    """Token usage statistics."""

    total_tokens: int = Field(default=0, description="Total tokens")
    input_tokens: int = Field(default=0, description="Input tokens")
    output_tokens: int = Field(default=0, description="Output tokens")
    input_token_details: Optional[Dict[str, int]] = Field(
        default=None, description="Input token breakdown"
    )
    output_token_details: Optional[Dict[str, int]] = Field(
        default=None, description="Output token breakdown"
    )


class Response(BaseModel):
    """A response generated by the model."""

    id: str = Field(..., description="Response ID")
    object: Literal["realtime.response"] = Field(
        default="realtime.response", description="Object type"
    )
    status: ResponseStatus = Field(..., description="Response status")
    status_details: Optional[ResponseStatusDetails] = Field(
        default=None, description="Status details"
    )
    output: List[ResponseOutput] = Field(
        default_factory=list, description="Output items"
    )
    usage: Optional[UsageStats] = Field(default=None, description="Usage statistics")
    metadata: Optional[Dict[str, str]] = Field(
        default=None, description="Response metadata"
    )
