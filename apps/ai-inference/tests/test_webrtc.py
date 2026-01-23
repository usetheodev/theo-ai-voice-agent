"""Tests for WebRTC components."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.core.config import reset_settings
from src.core.session import RealtimeSession
from src.models.session import SessionConfig
from src.webrtc.datachannel import DataChannelHandler
from src.webrtc.tracks import AudioOutputTrack, SAMPLE_RATE, SAMPLES_PER_FRAME


@pytest.fixture(autouse=True)
def reset_config():
    """Reset config before each test."""
    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def session():
    """Create a test session."""
    return RealtimeSession(config=SessionConfig())


class TestDataChannelHandler:
    """Tests for DataChannelHandler."""

    @pytest.fixture
    def mock_datachannel(self):
        """Create a mock DataChannel."""
        channel = MagicMock()
        channel.readyState = "open"
        channel.send = MagicMock()
        return channel

    @pytest.fixture
    def handler(self, session, mock_datachannel):
        """Create a DataChannelHandler."""
        return DataChannelHandler(
            session=session,
            datachannel=mock_datachannel,
        )

    @pytest.mark.asyncio
    async def test_send_session_created(self, handler, mock_datachannel):
        """Test sending session created events."""
        await handler.send_session_created()

        # Should have sent two events (session.created and conversation.created)
        assert mock_datachannel.send.call_count == 2

        # Verify first event is session.created
        first_call = mock_datachannel.send.call_args_list[0]
        first_event = json.loads(first_call[0][0])
        assert first_event["type"] == "session.created"

        # Verify second event is conversation.created
        second_call = mock_datachannel.send.call_args_list[1]
        second_event = json.loads(second_call[0][0])
        assert second_event["type"] == "conversation.created"

    @pytest.mark.asyncio
    async def test_on_message_session_update(self, handler, mock_datachannel, session):
        """Test handling session.update event."""
        message = json.dumps({
            "type": "session.update",
            "session": {
                "instructions": "New instructions",
            },
        })

        await handler.on_message(message)

        # Verify session was updated
        assert session.config.instructions == "New instructions"

        # Verify response was sent
        assert mock_datachannel.send.call_count == 1
        response = json.loads(mock_datachannel.send.call_args[0][0])
        assert response["type"] == "session.updated"

    @pytest.mark.asyncio
    async def test_on_message_invalid_json(self, handler, mock_datachannel):
        """Test handling invalid JSON."""
        await handler.on_message("not valid json")

        # Should send error event
        assert mock_datachannel.send.call_count == 1
        response = json.loads(mock_datachannel.send.call_args[0][0])
        assert response["type"] == "error"
        assert "json" in response["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_on_message_unknown_event(self, handler, mock_datachannel):
        """Test handling unknown event type."""
        message = json.dumps({
            "type": "unknown.event.type",
        })

        await handler.on_message(message)

        # Should send error event
        assert mock_datachannel.send.call_count == 1
        response = json.loads(mock_datachannel.send.call_args[0][0])
        assert response["type"] == "error"
        assert "unknown" in response["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_send_event_closed_channel(self, handler, mock_datachannel):
        """Test sending event when channel is closed."""
        mock_datachannel.readyState = "closed"

        await handler.send_event(MagicMock(model_dump=lambda **_: {}))

        # Should not try to send
        assert mock_datachannel.send.call_count == 0


class TestAudioOutputTrack:
    """Tests for AudioOutputTrack."""

    @pytest.fixture
    def track(self, session):
        """Create an AudioOutputTrack."""
        return AudioOutputTrack(session=session)

    @pytest.mark.asyncio
    async def test_recv_silence_when_empty(self, track):
        """Test receiving silence when queue is empty."""
        frame = await track.recv()

        assert frame is not None
        assert frame.sample_rate == SAMPLE_RATE
        assert frame.samples == SAMPLES_PER_FRAME

    @pytest.mark.asyncio
    async def test_queue_audio(self, track):
        """Test queueing audio data."""
        # Create some test audio data (1 frame worth)
        audio_data = bytes(SAMPLES_PER_FRAME * 2)  # 2 bytes per sample

        result = track.queue_audio(audio_data)
        assert result is True

    def test_queue_audio_full(self, track):
        """Test queueing when queue is full."""
        # Fill the queue
        audio_data = bytes(SAMPLES_PER_FRAME * 2)
        for _ in range(100):  # maxsize is 100
            track.queue_audio(audio_data)

        # Next one should fail
        result = track.queue_audio(audio_data)
        assert result is False

    def test_clear_queue(self, track):
        """Test clearing the audio queue."""
        # Add some audio
        audio_data = bytes(SAMPLES_PER_FRAME * 2)
        track.queue_audio(audio_data)
        track.queue_audio(audio_data)

        # Clear
        track.clear_queue()

        # Queue should be empty
        assert track._audio_queue.empty()

    @pytest.mark.asyncio
    async def test_recv_queued_audio(self, track):
        """Test receiving queued audio."""
        # Queue audio
        audio_data = bytes(SAMPLES_PER_FRAME * 2)
        track.queue_audio(audio_data)

        # Receive frame
        frame = await track.recv()

        assert frame is not None
        assert frame.sample_rate == SAMPLE_RATE

    @pytest.mark.asyncio
    async def test_pts_increments(self, track):
        """Test that PTS increments correctly."""
        frame1 = await track.recv()
        frame2 = await track.recv()

        assert frame1.pts == 0
        assert frame2.pts == SAMPLES_PER_FRAME


class TestRealtimeConnection:
    """Tests for RealtimeConnection (integration tests)."""

    def _create_mock_pc(self):
        """Create a properly configured mock RTCPeerConnection."""
        mock_pc = MagicMock()
        mock_pc.connectionState = "connected"
        mock_pc.iceConnectionState = "connected"
        mock_pc.close = AsyncMock()
        # The 'on' method should work as a decorator
        mock_pc.on = MagicMock(side_effect=lambda event: lambda func: func)
        return mock_pc

    @pytest.mark.asyncio
    async def test_connection_creation(self, session):
        """Test creating a RealtimeConnection."""
        from src.webrtc.connection import RealtimeConnection

        with patch("src.webrtc.connection.RTCPeerConnection") as mock_pc_class:
            mock_pc = self._create_mock_pc()
            mock_pc_class.return_value = mock_pc

            connection = RealtimeConnection(session=session)

            assert connection.session == session
            assert connection.pc is not None
            assert not connection._closed

    @pytest.mark.asyncio
    async def test_connection_close(self, session):
        """Test closing a RealtimeConnection."""
        from src.webrtc.connection import RealtimeConnection

        close_callback = MagicMock()

        with patch("src.webrtc.connection.RTCPeerConnection") as mock_pc_class:
            mock_pc = self._create_mock_pc()
            mock_pc_class.return_value = mock_pc

            connection = RealtimeConnection(
                session=session,
                on_close=close_callback,
            )

            await connection.close()

            assert connection._closed
            mock_pc.close.assert_called_once()
            close_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_connection_close_idempotent(self, session):
        """Test that closing connection multiple times is safe."""
        from src.webrtc.connection import RealtimeConnection

        with patch("src.webrtc.connection.RTCPeerConnection") as mock_pc_class:
            mock_pc = self._create_mock_pc()
            mock_pc_class.return_value = mock_pc

            connection = RealtimeConnection(session=session)

            await connection.close()
            await connection.close()  # Second close should be no-op

            # close should only be called once
            mock_pc.close.assert_called_once()

    def test_is_connected_property(self, session):
        """Test is_connected property."""
        from src.webrtc.connection import RealtimeConnection

        with patch("src.webrtc.connection.RTCPeerConnection") as mock_pc_class:
            mock_pc = self._create_mock_pc()
            mock_pc_class.return_value = mock_pc

            connection = RealtimeConnection(session=session)

            assert connection.is_connected is True

            mock_pc.connectionState = "disconnected"
            assert connection.is_connected is False

            connection._closed = True
            mock_pc.connectionState = "connected"
            assert connection.is_connected is False
