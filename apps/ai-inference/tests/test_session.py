"""Tests for the RealtimeSession and SessionManager."""

import pytest
import pytest_asyncio

from src.core.session import RealtimeSession, SessionState
from src.core.session_manager import SessionManager
from src.models.audio import AudioFormat
from src.models.conversation import ConversationItem, ItemRole, ItemType
from src.models.session import Modality, SessionConfig, TurnDetectionConfig


class TestRealtimeSession:
    """Tests for RealtimeSession."""

    def test_session_creation(self):
        """Test session is created with defaults."""
        session = RealtimeSession()

        assert session.id.startswith("sess_")
        assert session.state == SessionState.CREATED
        assert session.config is not None
        assert session.conversation is not None
        assert session.input_audio_buffer.is_empty()

    def test_session_with_custom_id(self):
        """Test session with custom ID."""
        session = RealtimeSession(session_id="custom_session_123")
        assert session.id == "custom_session_123"

    def test_session_with_custom_config(self):
        """Test session with custom configuration."""
        config = SessionConfig(
            modalities=[Modality.TEXT],
            instructions="You are a helpful assistant",
            voice="nova",
            temperature=0.5,
        )
        session = RealtimeSession(config=config)

        assert session.config.modalities == [Modality.TEXT]
        assert session.config.instructions == "You are a helpful assistant"
        assert session.config.voice == "nova"
        assert session.config.temperature == 0.5

    def test_update_config(self):
        """Test updating session configuration."""
        session = RealtimeSession()

        new_config = SessionConfig(
            instructions="New instructions",
            voice="echo",
        )
        session.update_config(new_config)

        assert session.config.instructions == "New instructions"
        assert session.config.voice == "echo"

    def test_append_audio(self):
        """Test appending audio to buffer."""
        session = RealtimeSession()

        # PCM16: 2 bytes per sample, 24000 Hz
        # 48000 bytes = 24000 samples = 1 second
        audio_data = b"\x00" * 48000
        session.append_audio(audio_data)

        assert not session.input_audio_buffer.is_empty()
        assert session.input_audio_buffer.total_duration_ms == 1000
        assert session.state == SessionState.LISTENING

    def test_commit_audio(self):
        """Test committing audio buffer."""
        session = RealtimeSession()
        session.append_audio(b"\x00" * 4800)  # 100ms

        item_id = session.commit_audio()

        assert item_id.startswith("item_")
        assert session.input_audio_buffer.is_empty()
        assert len(session.conversation.items) == 1
        assert session.conversation.items[0].id == item_id
        assert session.state == SessionState.ACTIVE

    def test_clear_audio(self):
        """Test clearing audio buffer."""
        session = RealtimeSession()
        session.append_audio(b"\x00" * 4800)
        session.clear_audio()

        assert session.input_audio_buffer.is_empty()

    def test_create_response(self):
        """Test creating a response."""
        session = RealtimeSession()
        response = session.create_response()

        assert response.id.startswith("resp_")
        assert session.current_response is not None
        assert session.state == SessionState.PROCESSING

    def test_cancel_response(self):
        """Test cancelling a response."""
        session = RealtimeSession()
        session.create_response()

        cancelled = session.cancel_response()

        assert cancelled is not None
        assert session.current_response is None
        assert session.state == SessionState.ACTIVE

    def test_complete_response(self):
        """Test completing a response."""
        session = RealtimeSession()
        session.create_response()

        completed = session.complete_response()

        assert completed is not None
        assert session.current_response is None
        assert session.state == SessionState.ACTIVE

    def test_add_conversation_item(self):
        """Test adding a conversation item."""
        session = RealtimeSession()

        item = ConversationItem(
            id="test_item_1",
            type=ItemType.MESSAGE,
            role=ItemRole.USER,
        )
        session.add_conversation_item(item)

        assert len(session.conversation.items) == 1
        assert session.conversation.items[0].id == "test_item_1"

    def test_delete_conversation_item(self):
        """Test deleting a conversation item."""
        session = RealtimeSession()

        item = ConversationItem(
            id="test_item_1",
            type=ItemType.MESSAGE,
            role=ItemRole.USER,
        )
        session.add_conversation_item(item)

        success = session.delete_conversation_item("test_item_1")

        assert success
        assert len(session.conversation.items) == 0

    def test_close_session(self):
        """Test closing a session."""
        session = RealtimeSession()
        session.append_audio(b"\x00" * 4800)
        session.create_response()

        session.close()

        assert session.state == SessionState.CLOSED
        assert session.input_audio_buffer.is_empty()
        assert session.current_response is None

    def test_session_expiry(self):
        """Test session expiry check."""
        session = RealtimeSession()

        # Not expired with long timeout
        assert not session.is_expired(3600)

        # Closed sessions are considered expired
        session.close()
        assert session.is_expired(3600)

    def test_to_dict(self):
        """Test session serialization."""
        session = RealtimeSession()
        data = session.to_dict()

        assert "id" in data
        assert "state" in data
        assert "created_at" in data
        assert "config" in data
        assert "conversation_id" in data


class TestSessionManager:
    """Tests for SessionManager."""

    @pytest.mark.asyncio
    async def test_create_session(self, session_manager: SessionManager):
        """Test creating a session."""
        session = await session_manager.create_session()

        assert session is not None
        assert session.id.startswith("sess_")

    @pytest.mark.asyncio
    async def test_create_session_with_id(self, session_manager: SessionManager):
        """Test creating a session with custom ID."""
        session = await session_manager.create_session(session_id="custom_123")
        assert session.id == "custom_123"

    @pytest.mark.asyncio
    async def test_get_session(self, session_manager: SessionManager):
        """Test getting a session."""
        created = await session_manager.create_session()
        retrieved = await session_manager.get_session(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, session_manager: SessionManager):
        """Test getting a nonexistent session."""
        session = await session_manager.get_session("nonexistent")
        assert session is None

    @pytest.mark.asyncio
    async def test_delete_session(self, session_manager: SessionManager):
        """Test deleting a session."""
        session = await session_manager.create_session()
        deleted = await session_manager.delete_session(session.id)

        assert deleted
        assert await session_manager.get_session(session.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_session(self, session_manager: SessionManager):
        """Test deleting a nonexistent session."""
        deleted = await session_manager.delete_session("nonexistent")
        assert not deleted

    @pytest.mark.asyncio
    async def test_list_sessions(self, session_manager: SessionManager):
        """Test listing sessions."""
        await session_manager.create_session()
        await session_manager.create_session()

        sessions = await session_manager.list_sessions()
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_max_sessions_limit(self, session_manager: SessionManager):
        """Test maximum sessions limit."""
        # Create max sessions
        for _ in range(session_manager.max_sessions):
            await session_manager.create_session()

        # Should raise error on next create
        with pytest.raises(RuntimeError, match="Maximum sessions limit"):
            await session_manager.create_session()

    @pytest.mark.asyncio
    async def test_get_session_stats(self, session_manager: SessionManager):
        """Test getting session statistics."""
        await session_manager.create_session()
        await session_manager.create_session()

        stats = await session_manager.get_session_stats()

        assert stats["total_sessions"] == 2
        assert stats["max_sessions"] == 10

    @pytest.mark.asyncio
    async def test_close_all(self, session_manager: SessionManager):
        """Test closing all sessions."""
        await session_manager.create_session()
        await session_manager.create_session()

        await session_manager.close_all()

        count = await session_manager.get_session_count()
        assert count == 0
