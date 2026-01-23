"""Realtime session state machine."""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from ..models.audio import AudioBuffer, AudioFormat
from ..models.conversation import (
    AudioContent,
    Conversation,
    ConversationItem,
    ItemRole,
    ItemStatus,
    ItemType,
    Response,
    ResponseStatus,
)
from ..models.session import ResponseConfig, SessionConfig


class SessionState(str, Enum):
    """Session state machine states."""

    CREATED = "created"
    ACTIVE = "active"
    LISTENING = "listening"
    PROCESSING = "processing"
    RESPONDING = "responding"
    CLOSED = "closed"


def generate_id(prefix: str = "") -> str:
    """Generate a unique ID with optional prefix."""
    return f"{prefix}{uuid.uuid4().hex[:24]}"


class RealtimeSession:
    """Manages the state of a realtime session.

    This class implements the session state machine for the OpenAI Realtime API
    compatible protocol.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        config: Optional[SessionConfig] = None,
    ):
        """Initialize a new realtime session.

        Args:
            session_id: Optional session ID. Generated if not provided.
            config: Optional session configuration. Uses defaults if not provided.
        """
        self.id = session_id or generate_id("sess_")
        self.config = config or SessionConfig()
        self.state = SessionState.CREATED
        self.created_at = datetime.now(timezone.utc)
        self.last_activity = self.created_at

        # Conversation state
        self.conversation = Conversation(id=generate_id("conv_"))
        self.input_audio_buffer = AudioBuffer(format=self.config.input_audio_format)

        # Response state
        self.current_response: Optional[Response] = None
        self._response_queue: List[Response] = []

        # Audio tracking
        self._speech_started = False
        self._speech_start_ms = 0
        self._total_audio_ms = 0

    def update_config(self, new_config: SessionConfig) -> None:
        """Update session configuration.

        Args:
            new_config: New configuration to apply.
        """
        # Merge configurations - only update provided fields
        if new_config.modalities:
            self.config.modalities = new_config.modalities
        if new_config.instructions is not None:
            self.config.instructions = new_config.instructions
        if new_config.voice:
            self.config.voice = new_config.voice
        if new_config.input_audio_format:
            self.config.input_audio_format = new_config.input_audio_format
            self.input_audio_buffer.format = new_config.input_audio_format
        if new_config.output_audio_format:
            self.config.output_audio_format = new_config.output_audio_format
        if new_config.input_audio_transcription:
            self.config.input_audio_transcription = new_config.input_audio_transcription
        if new_config.turn_detection is not None:
            self.config.turn_detection = new_config.turn_detection
        if new_config.tools:
            self.config.tools = new_config.tools
        if new_config.tool_choice:
            self.config.tool_choice = new_config.tool_choice
        if new_config.temperature is not None:
            self.config.temperature = new_config.temperature
        if new_config.max_response_output_tokens is not None:
            self.config.max_response_output_tokens = new_config.max_response_output_tokens

        self._touch()

    def append_audio(self, audio_data: bytes) -> None:
        """Append audio data to the input buffer.

        Args:
            audio_data: Raw audio bytes to append.
        """
        self.input_audio_buffer.append(audio_data)
        self._total_audio_ms = self.input_audio_buffer.total_duration_ms
        self.state = SessionState.LISTENING
        self._touch()

    def commit_audio(self) -> str:
        """Commit the current input audio buffer as a conversation item.

        Returns:
            The ID of the created conversation item.
        """
        item_id = generate_id("item_")

        # Create conversation item with audio content
        item = ConversationItem(
            id=item_id,
            type=ItemType.MESSAGE,
            role=ItemRole.USER,
            status=ItemStatus.COMPLETED,
            content=[
                AudioContent(
                    type="input_audio",
                    audio=None,  # Audio stored separately
                    transcript=None,  # Will be filled by transcription
                )
            ],
        )

        self.conversation.add_item(item)
        self.clear_audio()
        self.state = SessionState.ACTIVE
        self._touch()

        return item_id

    def clear_audio(self) -> None:
        """Clear the input audio buffer."""
        self.input_audio_buffer.clear()
        self._speech_started = False
        self._speech_start_ms = 0
        self._touch()

    def create_response(self, config: Optional[ResponseConfig] = None) -> Response:
        """Create a new response.

        Args:
            config: Optional response configuration override.

        Returns:
            The created response object.
        """
        response_id = generate_id("resp_")

        response = Response(
            id=response_id,
            status=ResponseStatus.IN_PROGRESS,
            output=[],
            metadata=config.metadata if config else None,
        )

        self.current_response = response
        self.state = SessionState.PROCESSING
        self._touch()

        return response

    def cancel_response(self) -> Optional[Response]:
        """Cancel the current response if one is in progress.

        Returns:
            The cancelled response, or None if no response was in progress.
        """
        if self.current_response and self.current_response.status == ResponseStatus.IN_PROGRESS:
            self.current_response.status = ResponseStatus.CANCELLED
            cancelled = self.current_response
            self.current_response = None
            self.state = SessionState.ACTIVE
            self._touch()
            return cancelled
        return None

    def complete_response(self) -> Optional[Response]:
        """Mark the current response as completed.

        Returns:
            The completed response, or None if no response was in progress.
        """
        if self.current_response:
            self.current_response.status = ResponseStatus.COMPLETED
            completed = self.current_response
            self.current_response = None
            self.state = SessionState.ACTIVE
            self._touch()
            return completed
        return None

    def add_conversation_item(
        self, item: ConversationItem, previous_item_id: Optional[str] = None
    ) -> None:
        """Add a conversation item.

        Args:
            item: The item to add.
            previous_item_id: Optional ID of item to insert after.
        """
        if previous_item_id:
            # Find position and insert after
            for i, existing in enumerate(self.conversation.items):
                if existing.id == previous_item_id:
                    self.conversation.items.insert(i + 1, item)
                    self._touch()
                    return
        # Append to end if no previous_item_id or not found
        self.conversation.add_item(item)
        self._touch()

    def truncate_conversation(self, item_id: str, audio_end_ms: int) -> bool:
        """Truncate conversation at a specific item.

        Args:
            item_id: ID of the item to truncate at.
            audio_end_ms: Audio end position in milliseconds.

        Returns:
            True if truncation was successful, False otherwise.
        """
        result = self.conversation.truncate_at(item_id, audio_end_ms)
        if result:
            self._touch()
        return result

    def delete_conversation_item(self, item_id: str) -> bool:
        """Delete a conversation item.

        Args:
            item_id: ID of the item to delete.

        Returns:
            True if deletion was successful, False otherwise.
        """
        for i, item in enumerate(self.conversation.items):
            if item.id == item_id:
                self.conversation.items.pop(i)
                self._touch()
                return True
        return False

    def mark_speech_started(self, audio_start_ms: int) -> str:
        """Mark that speech has started.

        Args:
            audio_start_ms: Audio position where speech started.

        Returns:
            The ID of the item being created.
        """
        self._speech_started = True
        self._speech_start_ms = audio_start_ms
        self.state = SessionState.LISTENING

        # Pre-create item ID for the speech
        item_id = generate_id("item_")
        self._touch()
        return item_id

    def mark_speech_stopped(self, audio_end_ms: int) -> None:
        """Mark that speech has stopped.

        Args:
            audio_end_ms: Audio position where speech stopped.
        """
        self._speech_started = False
        self._touch()

    def get_last_item_id(self) -> Optional[str]:
        """Get the ID of the last conversation item.

        Returns:
            The ID of the last item, or None if conversation is empty.
        """
        if self.conversation.items:
            return self.conversation.items[-1].id
        return None

    def close(self) -> None:
        """Close the session."""
        self.state = SessionState.CLOSED
        self.clear_audio()
        if self.current_response:
            self.current_response.status = ResponseStatus.CANCELLED
            self.current_response = None

    def is_expired(self, timeout_seconds: int) -> bool:
        """Check if the session has expired.

        Args:
            timeout_seconds: Timeout in seconds.

        Returns:
            True if expired, False otherwise.
        """
        if self.state == SessionState.CLOSED:
            return True
        elapsed = (datetime.now(timezone.utc) - self.last_activity).total_seconds()
        return elapsed > timeout_seconds

    def _touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        """Convert session to dictionary representation.

        Returns:
            Dictionary with session details.
        """
        return {
            "id": self.id,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "config": self.config.model_dump(),
            "conversation_id": self.conversation.id,
            "conversation_items": len(self.conversation.items),
            "audio_buffer_size": len(self.input_audio_buffer.data),
            "audio_buffer_duration_ms": self.input_audio_buffer.total_duration_ms,
            "has_active_response": self.current_response is not None,
        }
