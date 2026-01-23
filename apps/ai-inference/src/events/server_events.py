"""Server event models for the OpenAI Realtime API compatible protocol.

These are events sent from the server to the client.
"""

import uuid
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..models.conversation import ConversationItem, Response, ResponseOutput
from ..models.session import SessionConfig
from .types import ServerEventType


def generate_event_id() -> str:
    """Generate a unique event ID."""
    return f"event_{uuid.uuid4().hex[:24]}"


class BaseServerEvent(BaseModel):
    """Base class for all server events."""

    event_id: str = Field(default_factory=generate_event_id, description="Event ID")


# Error Events


class ErrorDetail(BaseModel):
    """Error detail information."""

    type: str = Field(..., description="Error type")
    code: Optional[str] = Field(default=None, description="Error code")
    message: str = Field(..., description="Error message")
    param: Optional[str] = Field(default=None, description="Parameter that caused error")


class ErrorEvent(BaseServerEvent):
    """Error event sent when an error occurs."""

    type: Literal[ServerEventType.ERROR] = ServerEventType.ERROR
    error: ErrorDetail = Field(..., description="Error details")


# Session Events


class SessionObject(BaseModel):
    """Session object in events."""

    id: str = Field(..., description="Session ID")
    object: Literal["realtime.session"] = "realtime.session"
    model: str = Field(default="gpt-4o-realtime", description="Model name")
    modalities: List[str] = Field(default=["text", "audio"], description="Modalities")
    instructions: Optional[str] = Field(default=None, description="Instructions")
    voice: str = Field(default="alloy", description="Voice")
    input_audio_format: str = Field(default="pcm16", description="Input audio format")
    output_audio_format: str = Field(default="pcm16", description="Output audio format")
    input_audio_transcription: Optional[Dict[str, Any]] = Field(
        default=None, description="Input transcription config"
    )
    turn_detection: Optional[Dict[str, Any]] = Field(
        default=None, description="Turn detection config"
    )
    tools: List[Dict[str, Any]] = Field(default_factory=list, description="Tools")
    tool_choice: str = Field(default="auto", description="Tool choice")
    temperature: float = Field(default=0.8, description="Temperature")
    max_response_output_tokens: Optional[int] = Field(
        default=None, description="Max output tokens"
    )


class SessionCreatedEvent(BaseServerEvent):
    """Event sent when a session is created."""

    type: Literal[ServerEventType.SESSION_CREATED] = ServerEventType.SESSION_CREATED
    session: SessionObject = Field(..., description="Session details")


class SessionUpdatedEvent(BaseServerEvent):
    """Event sent when a session is updated."""

    type: Literal[ServerEventType.SESSION_UPDATED] = ServerEventType.SESSION_UPDATED
    session: SessionObject = Field(..., description="Updated session details")


# Conversation Events


class ConversationObject(BaseModel):
    """Conversation object in events."""

    id: str = Field(..., description="Conversation ID")
    object: Literal["realtime.conversation"] = "realtime.conversation"


class ConversationCreatedEvent(BaseServerEvent):
    """Event sent when a conversation is created."""

    type: Literal[ServerEventType.CONVERSATION_CREATED] = (
        ServerEventType.CONVERSATION_CREATED
    )
    conversation: ConversationObject = Field(..., description="Conversation details")


class ConversationItemCreatedEvent(BaseServerEvent):
    """Event sent when a conversation item is created."""

    type: Literal[ServerEventType.CONVERSATION_ITEM_CREATED] = (
        ServerEventType.CONVERSATION_ITEM_CREATED
    )
    previous_item_id: Optional[str] = Field(
        default=None, description="ID of previous item"
    )
    item: ConversationItem = Field(..., description="Created item")


class TranscriptionCompletedEvent(BaseServerEvent):
    """Event sent when input audio transcription completes."""

    type: Literal[
        ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED
    ] = ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED
    item_id: str = Field(..., description="Item ID")
    content_index: int = Field(..., description="Content index")
    transcript: str = Field(..., description="Transcription text")


class TranscriptionFailedEvent(BaseServerEvent):
    """Event sent when input audio transcription fails."""

    type: Literal[
        ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_FAILED
    ] = ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_FAILED
    item_id: str = Field(..., description="Item ID")
    content_index: int = Field(..., description="Content index")
    error: ErrorDetail = Field(..., description="Error details")


class ConversationItemTruncatedEvent(BaseServerEvent):
    """Event sent when a conversation item is truncated."""

    type: Literal[ServerEventType.CONVERSATION_ITEM_TRUNCATED] = (
        ServerEventType.CONVERSATION_ITEM_TRUNCATED
    )
    item_id: str = Field(..., description="Item ID")
    content_index: int = Field(..., description="Content index")
    audio_end_ms: int = Field(..., description="Audio end position")


class ConversationItemDeletedEvent(BaseServerEvent):
    """Event sent when a conversation item is deleted."""

    type: Literal[ServerEventType.CONVERSATION_ITEM_DELETED] = (
        ServerEventType.CONVERSATION_ITEM_DELETED
    )
    item_id: str = Field(..., description="Deleted item ID")


# Input Audio Buffer Events


class InputAudioBufferCommittedEvent(BaseServerEvent):
    """Event sent when input audio buffer is committed."""

    type: Literal[ServerEventType.INPUT_AUDIO_BUFFER_COMMITTED] = (
        ServerEventType.INPUT_AUDIO_BUFFER_COMMITTED
    )
    previous_item_id: Optional[str] = Field(
        default=None, description="ID of previous item"
    )
    item_id: str = Field(..., description="Created item ID")


class InputAudioBufferClearedEvent(BaseServerEvent):
    """Event sent when input audio buffer is cleared."""

    type: Literal[ServerEventType.INPUT_AUDIO_BUFFER_CLEARED] = (
        ServerEventType.INPUT_AUDIO_BUFFER_CLEARED
    )


class SpeechStartedEvent(BaseServerEvent):
    """Event sent when speech is detected in input audio."""

    type: Literal[ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED] = (
        ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED
    )
    audio_start_ms: int = Field(..., description="Audio start position")
    item_id: str = Field(..., description="Item ID being created")


class SpeechStoppedEvent(BaseServerEvent):
    """Event sent when speech ends in input audio."""

    type: Literal[ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED] = (
        ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED
    )
    audio_end_ms: int = Field(..., description="Audio end position")
    item_id: str = Field(..., description="Item ID")


# Response Events


class ResponseCreatedEvent(BaseServerEvent):
    """Event sent when a response is created."""

    type: Literal[ServerEventType.RESPONSE_CREATED] = ServerEventType.RESPONSE_CREATED
    response: Response = Field(..., description="Response details")


class ResponseDoneEvent(BaseServerEvent):
    """Event sent when a response is complete."""

    type: Literal[ServerEventType.RESPONSE_DONE] = ServerEventType.RESPONSE_DONE
    response: Response = Field(..., description="Completed response")


class ResponseOutputItemAddedEvent(BaseServerEvent):
    """Event sent when an output item is added to a response."""

    type: Literal[ServerEventType.RESPONSE_OUTPUT_ITEM_ADDED] = (
        ServerEventType.RESPONSE_OUTPUT_ITEM_ADDED
    )
    response_id: str = Field(..., description="Response ID")
    output_index: int = Field(..., description="Output index")
    item: ResponseOutput = Field(..., description="Output item")


class ResponseOutputItemDoneEvent(BaseServerEvent):
    """Event sent when an output item is complete."""

    type: Literal[ServerEventType.RESPONSE_OUTPUT_ITEM_DONE] = (
        ServerEventType.RESPONSE_OUTPUT_ITEM_DONE
    )
    response_id: str = Field(..., description="Response ID")
    output_index: int = Field(..., description="Output index")
    item: ResponseOutput = Field(..., description="Completed output item")


class ContentPart(BaseModel):
    """Content part in a response."""

    type: str = Field(..., description="Content type")
    text: Optional[str] = Field(default=None, description="Text content")
    audio: Optional[str] = Field(default=None, description="Audio content")
    transcript: Optional[str] = Field(default=None, description="Transcript")


class ResponseContentPartAddedEvent(BaseServerEvent):
    """Event sent when a content part is added."""

    type: Literal[ServerEventType.RESPONSE_CONTENT_PART_ADDED] = (
        ServerEventType.RESPONSE_CONTENT_PART_ADDED
    )
    response_id: str = Field(..., description="Response ID")
    item_id: str = Field(..., description="Item ID")
    output_index: int = Field(..., description="Output index")
    content_index: int = Field(..., description="Content index")
    part: ContentPart = Field(..., description="Content part")


class ResponseContentPartDoneEvent(BaseServerEvent):
    """Event sent when a content part is complete."""

    type: Literal[ServerEventType.RESPONSE_CONTENT_PART_DONE] = (
        ServerEventType.RESPONSE_CONTENT_PART_DONE
    )
    response_id: str = Field(..., description="Response ID")
    item_id: str = Field(..., description="Item ID")
    output_index: int = Field(..., description="Output index")
    content_index: int = Field(..., description="Content index")
    part: ContentPart = Field(..., description="Completed content part")


class ResponseTextDeltaEvent(BaseServerEvent):
    """Event sent for text delta in a response."""

    type: Literal[ServerEventType.RESPONSE_TEXT_DELTA] = (
        ServerEventType.RESPONSE_TEXT_DELTA
    )
    response_id: str = Field(..., description="Response ID")
    item_id: str = Field(..., description="Item ID")
    output_index: int = Field(..., description="Output index")
    content_index: int = Field(..., description="Content index")
    delta: str = Field(..., description="Text delta")


class ResponseTextDoneEvent(BaseServerEvent):
    """Event sent when text output is complete."""

    type: Literal[ServerEventType.RESPONSE_TEXT_DONE] = (
        ServerEventType.RESPONSE_TEXT_DONE
    )
    response_id: str = Field(..., description="Response ID")
    item_id: str = Field(..., description="Item ID")
    output_index: int = Field(..., description="Output index")
    content_index: int = Field(..., description="Content index")
    text: str = Field(..., description="Complete text")


class ResponseAudioTranscriptDeltaEvent(BaseServerEvent):
    """Event sent for audio transcript delta."""

    type: Literal[ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA] = (
        ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA
    )
    response_id: str = Field(..., description="Response ID")
    item_id: str = Field(..., description="Item ID")
    output_index: int = Field(..., description="Output index")
    content_index: int = Field(..., description="Content index")
    delta: str = Field(..., description="Transcript delta")


class ResponseAudioTranscriptDoneEvent(BaseServerEvent):
    """Event sent when audio transcript is complete."""

    type: Literal[ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE] = (
        ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE
    )
    response_id: str = Field(..., description="Response ID")
    item_id: str = Field(..., description="Item ID")
    output_index: int = Field(..., description="Output index")
    content_index: int = Field(..., description="Content index")
    transcript: str = Field(..., description="Complete transcript")


class ResponseAudioDeltaEvent(BaseServerEvent):
    """Event sent for audio delta in a response."""

    type: Literal[ServerEventType.RESPONSE_AUDIO_DELTA] = (
        ServerEventType.RESPONSE_AUDIO_DELTA
    )
    response_id: str = Field(..., description="Response ID")
    item_id: str = Field(..., description="Item ID")
    output_index: int = Field(..., description="Output index")
    content_index: int = Field(..., description="Content index")
    delta: str = Field(..., description="Base64-encoded audio delta")


class ResponseAudioDoneEvent(BaseServerEvent):
    """Event sent when audio output is complete."""

    type: Literal[ServerEventType.RESPONSE_AUDIO_DONE] = (
        ServerEventType.RESPONSE_AUDIO_DONE
    )
    response_id: str = Field(..., description="Response ID")
    item_id: str = Field(..., description="Item ID")
    output_index: int = Field(..., description="Output index")
    content_index: int = Field(..., description="Content index")


class ResponseFunctionCallArgumentsDeltaEvent(BaseServerEvent):
    """Event sent for function call arguments delta."""

    type: Literal[ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DELTA] = (
        ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DELTA
    )
    response_id: str = Field(..., description="Response ID")
    item_id: str = Field(..., description="Item ID")
    output_index: int = Field(..., description="Output index")
    call_id: str = Field(..., description="Function call ID")
    delta: str = Field(..., description="Arguments delta")


class ResponseFunctionCallArgumentsDoneEvent(BaseServerEvent):
    """Event sent when function call arguments are complete."""

    type: Literal[ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE] = (
        ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE
    )
    response_id: str = Field(..., description="Response ID")
    item_id: str = Field(..., description="Item ID")
    output_index: int = Field(..., description="Output index")
    call_id: str = Field(..., description="Function call ID")
    arguments: str = Field(..., description="Complete arguments JSON")


# Rate Limit Events


class RateLimitInfo(BaseModel):
    """Rate limit information."""

    name: str = Field(..., description="Rate limit name")
    limit: int = Field(..., description="Rate limit")
    remaining: int = Field(..., description="Remaining quota")
    reset_seconds: float = Field(..., description="Seconds until reset")


class RateLimitsUpdatedEvent(BaseServerEvent):
    """Event sent when rate limits are updated."""

    type: Literal[ServerEventType.RATE_LIMITS_UPDATED] = (
        ServerEventType.RATE_LIMITS_UPDATED
    )
    rate_limits: List[RateLimitInfo] = Field(..., description="Rate limit info")


# Builder Functions


def build_error_event(
    error_type: str,
    message: str,
    code: Optional[str] = None,
    param: Optional[str] = None,
) -> ErrorEvent:
    """Build an error event."""
    return ErrorEvent(
        error=ErrorDetail(type=error_type, message=message, code=code, param=param)
    )


def build_session_created_event(
    session_id: str, config: SessionConfig
) -> SessionCreatedEvent:
    """Build a session created event."""
    turn_detection_dict = None
    if config.turn_detection:
        turn_detection_dict = config.turn_detection.model_dump()

    input_transcription_dict = None
    if config.input_audio_transcription:
        input_transcription_dict = config.input_audio_transcription.model_dump()

    session = SessionObject(
        id=session_id,
        modalities=[m.value for m in config.modalities],
        instructions=config.instructions,
        voice=config.voice,
        input_audio_format=config.input_audio_format.value,
        output_audio_format=config.output_audio_format.value,
        input_audio_transcription=input_transcription_dict,
        turn_detection=turn_detection_dict,
        tools=[t.model_dump() for t in config.tools],
        tool_choice=config.tool_choice.value,
        temperature=config.temperature,
        max_response_output_tokens=config.max_response_output_tokens,
    )
    return SessionCreatedEvent(session=session)


def build_session_updated_event(
    session_id: str, config: SessionConfig
) -> SessionUpdatedEvent:
    """Build a session updated event."""
    turn_detection_dict = None
    if config.turn_detection:
        turn_detection_dict = config.turn_detection.model_dump()

    input_transcription_dict = None
    if config.input_audio_transcription:
        input_transcription_dict = config.input_audio_transcription.model_dump()

    session = SessionObject(
        id=session_id,
        modalities=[m.value for m in config.modalities],
        instructions=config.instructions,
        voice=config.voice,
        input_audio_format=config.input_audio_format.value,
        output_audio_format=config.output_audio_format.value,
        input_audio_transcription=input_transcription_dict,
        turn_detection=turn_detection_dict,
        tools=[t.model_dump() for t in config.tools],
        tool_choice=config.tool_choice.value,
        temperature=config.temperature,
        max_response_output_tokens=config.max_response_output_tokens,
    )
    return SessionUpdatedEvent(session=session)
