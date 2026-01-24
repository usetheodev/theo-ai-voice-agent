"""Tests for OpenAI Realtime API provider."""

import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import pytest

from voice_pipeline.providers.realtime.openai import (
    OpenAIRealtimeProvider,
    OpenAIRealtimeConfig,
)
from voice_pipeline.interfaces.realtime import (
    RealtimeEvent,
    RealtimeEventType,
    RealtimeSessionConfig,
)
from voice_pipeline.providers.base import ProviderHealth


# =============================================================================
# Test Configuration
# =============================================================================


class TestOpenAIRealtimeConfig:
    """Tests for OpenAIRealtimeConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = OpenAIRealtimeConfig()

        assert config.model == "gpt-4o-realtime-preview"
        assert config.voice == "alloy"
        assert config.modalities == ["text", "audio"]
        assert config.instructions is None
        assert config.input_audio_format == "pcm16"
        assert config.output_audio_format == "pcm16"
        assert config.input_audio_transcription is True
        assert config.temperature == 0.8
        assert config.sample_rate == 24000
        assert config.turn_detection is not None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = OpenAIRealtimeConfig(
            model="gpt-4o-mini-realtime-preview",
            voice="sage",
            modalities=["text"],
            instructions="Be concise.",
            input_audio_format="g711_ulaw",
            output_audio_format="g711_ulaw",
            temperature=0.6,
            max_response_output_tokens=500,
            turn_detection=None,
        )

        assert config.model == "gpt-4o-mini-realtime-preview"
        assert config.voice == "sage"
        assert config.modalities == ["text"]
        assert config.instructions == "Be concise."
        assert config.input_audio_format == "g711_ulaw"
        assert config.temperature == 0.6
        assert config.max_response_output_tokens == 500
        assert config.turn_detection is None


# =============================================================================
# Test Provider Initialization
# =============================================================================


class TestOpenAIRealtimeProviderInit:
    """Tests for OpenAIRealtimeProvider initialization."""

    def test_default_initialization(self):
        """Test initialization with default config."""
        provider = OpenAIRealtimeProvider()

        assert provider._realtime_config.model == "gpt-4o-realtime-preview"
        assert provider._realtime_config.voice == "alloy"
        assert provider._ws is None
        assert provider.provider_name == "openai-realtime"
        assert provider.name == "OpenAIRealtime"

    def test_initialization_with_config(self):
        """Test initialization with custom config."""
        config = OpenAIRealtimeConfig(
            model="gpt-4o-mini-realtime-preview",
            voice="coral",
            instructions="You are a helpful assistant.",
        )
        provider = OpenAIRealtimeProvider(config=config)

        assert provider._realtime_config.model == "gpt-4o-mini-realtime-preview"
        assert provider._realtime_config.voice == "coral"
        assert provider._realtime_config.instructions == "You are a helpful assistant."

    def test_initialization_with_shortcuts(self):
        """Test initialization with shortcut parameters."""
        provider = OpenAIRealtimeProvider(
            model="gpt-4o-realtime-preview",
            voice="echo",
            instructions="Respond briefly.",
        )

        assert provider._realtime_config.model == "gpt-4o-realtime-preview"
        assert provider._realtime_config.voice == "echo"
        assert provider._realtime_config.instructions == "Respond briefly."

    def test_shortcuts_override_config(self):
        """Test that shortcuts override config values."""
        config = OpenAIRealtimeConfig(
            model="gpt-4o-realtime-preview",
            voice="alloy",
        )
        provider = OpenAIRealtimeProvider(
            config=config,
            model="gpt-4o-mini-realtime-preview",
            voice="shimmer",
        )

        assert provider._realtime_config.model == "gpt-4o-mini-realtime-preview"
        assert provider._realtime_config.voice == "shimmer"

    def test_sample_rate_property(self):
        """Test sample_rate property."""
        provider = OpenAIRealtimeProvider()
        assert provider.sample_rate == 24000

    def test_is_connected_property(self):
        """Test is_connected property when not connected."""
        provider = OpenAIRealtimeProvider()
        assert provider.is_connected is False

    def test_repr(self):
        """Test string representation."""
        provider = OpenAIRealtimeProvider(
            model="gpt-4o-realtime-preview",
            voice="alloy",
        )
        repr_str = repr(provider)

        assert "OpenAIRealtimeProvider" in repr_str
        assert "gpt-4o-realtime-preview" in repr_str
        assert "alloy" in repr_str


# =============================================================================
# Test Provider Lifecycle
# =============================================================================


class TestOpenAIRealtimeProviderLifecycle:
    """Tests for provider lifecycle (connect/disconnect)."""

    @pytest.mark.asyncio
    async def test_connect_establishes_websocket(self):
        """Test that connect establishes WebSocket connection."""
        provider = OpenAIRealtimeProvider(api_key="test-key")

        mock_ws = AsyncMock()
        mock_ws.closed = False

        # Create an async context manager for websockets.connect
        async def mock_connect(*args, **kwargs):
            return mock_ws

        with patch("websockets.connect", side_effect=mock_connect):
            # We need to mock the receive loop differently
            with patch.object(provider, "_receive_loop", new_callable=AsyncMock):
                with patch.object(provider, "_wait_for_event", new_callable=AsyncMock) as mock_wait:
                    mock_wait.return_value = RealtimeEvent(
                        event_type=RealtimeEventType.SESSION_CREATED,
                        data={"session": {"id": "sess_123"}},
                    )
                    with patch.object(provider, "_send_session_update", new_callable=AsyncMock):
                        await provider.connect()

                        assert provider._ws is mock_ws
                        assert provider._connected is True

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_connect_raises_without_api_key(self):
        """Test that connect raises ValueError without API key."""
        provider = OpenAIRealtimeProvider()

        with patch.dict("os.environ", {}, clear=True):
            # Remove OPENAI_API_KEY if it exists
            with patch("os.environ.get", return_value=None):
                with pytest.raises(ValueError, match="API key is required"):
                    await provider.connect()

    @pytest.mark.asyncio
    async def test_connect_raises_without_websockets(self):
        """Test that connect raises ImportError if websockets not installed."""
        provider = OpenAIRealtimeProvider(api_key="test-key")

        # Temporarily hide websockets module
        import sys
        original_module = sys.modules.get("websockets")
        sys.modules["websockets"] = None

        try:
            with pytest.raises((ImportError, TypeError)):
                await provider.connect()
        finally:
            # Restore original module
            if original_module is not None:
                sys.modules["websockets"] = original_module
            else:
                sys.modules.pop("websockets", None)

    @pytest.mark.asyncio
    async def test_disconnect_closes_websocket(self):
        """Test that disconnect closes WebSocket connection."""
        provider = OpenAIRealtimeProvider()

        mock_ws = AsyncMock()
        mock_ws.closed = False
        provider._ws = mock_ws
        provider._connected = True
        provider._receive_task = asyncio.create_task(asyncio.sleep(100))

        await provider.disconnect()

        mock_ws.close.assert_called_once()
        assert provider._ws is None
        assert provider._connected is False


# =============================================================================
# Test Health Check
# =============================================================================


class TestOpenAIRealtimeProviderHealthCheck:
    """Tests for provider health check."""

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_when_not_connected(self):
        """Test health check returns unhealthy when not connected."""
        provider = OpenAIRealtimeProvider()

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "not connected" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_when_connected(self):
        """Test health check returns healthy when connected."""
        provider = OpenAIRealtimeProvider()

        mock_ws = AsyncMock()
        mock_ws.closed = False

        # Create a proper coroutine for ping
        async def mock_ping():
            return asyncio.Future()

        mock_ws.ping = mock_ping
        provider._ws = mock_ws
        provider._connected = True
        provider._session_id = "sess_123"

        # Mock the ping to complete immediately
        with patch.object(mock_ws, "ping") as mock_ping_method:
            future = asyncio.Future()
            future.set_result(None)
            mock_ping_method.return_value = future

            result = await provider.health_check()

            assert result.status == ProviderHealth.HEALTHY


# =============================================================================
# Test Event Parsing
# =============================================================================


class TestOpenAIRealtimeProviderEventParsing:
    """Tests for event parsing."""

    def test_parse_session_created_event(self):
        """Test parsing session.created event."""
        provider = OpenAIRealtimeProvider()

        data = {
            "type": "session.created",
            "event_id": "evt_001",
            "session": {"id": "sess_123"},
        }

        event = provider._parse_event(data)

        assert event.event_type == RealtimeEventType.SESSION_CREATED
        assert event.event_id == "evt_001"
        assert event.data["session"]["id"] == "sess_123"

    def test_parse_audio_delta_event(self):
        """Test parsing response.audio.delta event with audio data."""
        provider = OpenAIRealtimeProvider()

        audio_bytes = b"\x00\x01\x02\x03"
        audio_b64 = base64.b64encode(audio_bytes).decode()

        data = {
            "type": "response.audio.delta",
            "event_id": "evt_002",
            "delta": audio_b64,
        }

        event = provider._parse_event(data)

        assert event.event_type == RealtimeEventType.RESPONSE_AUDIO_DELTA
        assert event.audio == audio_bytes

    def test_parse_text_delta_event(self):
        """Test parsing response.text.delta event."""
        provider = OpenAIRealtimeProvider()

        data = {
            "type": "response.text.delta",
            "event_id": "evt_003",
            "delta": "Hello",
        }

        event = provider._parse_event(data)

        assert event.event_type == RealtimeEventType.RESPONSE_TEXT_DELTA
        assert event.text == "Hello"

    def test_parse_transcript_delta_event(self):
        """Test parsing response.audio_transcript.delta event."""
        provider = OpenAIRealtimeProvider()

        data = {
            "type": "response.audio_transcript.delta",
            "event_id": "evt_004",
            "delta": "Hello there",
        }

        event = provider._parse_event(data)

        assert event.event_type == RealtimeEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA
        assert event.transcript == "Hello there"

    def test_parse_error_event(self):
        """Test parsing error event."""
        provider = OpenAIRealtimeProvider()

        data = {
            "type": "error",
            "event_id": "evt_005",
            "error": {
                "message": "Invalid audio format",
                "code": "invalid_format",
            },
        }

        event = provider._parse_event(data)

        assert event.event_type == RealtimeEventType.ERROR
        assert "Invalid audio format" in event.error

    def test_parse_unknown_event(self):
        """Test parsing unknown event type."""
        provider = OpenAIRealtimeProvider()

        data = {
            "type": "some.unknown.event",
            "event_id": "evt_006",
        }

        event = provider._parse_event(data)

        # Unknown events should fall back to ERROR
        assert event.event_type == RealtimeEventType.ERROR


# =============================================================================
# Test Send Methods
# =============================================================================


class TestOpenAIRealtimeProviderSendMethods:
    """Tests for send methods."""

    @pytest.mark.asyncio
    async def test_send_audio_raises_without_connection(self):
        """Test that send_audio raises when not connected."""
        provider = OpenAIRealtimeProvider()

        with pytest.raises(RuntimeError, match="not connected"):
            await provider.send_audio(b"\x00\x01\x02\x03")

    @pytest.mark.asyncio
    async def test_send_audio_sends_base64_encoded(self):
        """Test that send_audio sends base64-encoded audio."""
        provider = OpenAIRealtimeProvider()

        mock_ws = AsyncMock()
        mock_ws.closed = False
        provider._ws = mock_ws
        provider._connected = True

        audio_bytes = b"\x00\x01\x02\x03"
        await provider.send_audio(audio_bytes)

        # Verify send was called
        mock_ws.send.assert_called_once()

        # Parse the sent message
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "input_audio_buffer.append"
        assert sent_data["audio"] == base64.b64encode(audio_bytes).decode()

    @pytest.mark.asyncio
    async def test_send_text_creates_conversation_item(self):
        """Test that send_text creates a conversation item."""
        provider = OpenAIRealtimeProvider()

        mock_ws = AsyncMock()
        mock_ws.closed = False
        provider._ws = mock_ws
        provider._connected = True

        await provider.send_text("Hello, how are you?")

        mock_ws.send.assert_called_once()

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "conversation.item.create"
        assert sent_data["item"]["role"] == "user"
        assert sent_data["item"]["content"][0]["text"] == "Hello, how are you?"

    @pytest.mark.asyncio
    async def test_commit_audio_sends_commit_event(self):
        """Test that commit_audio sends the commit event."""
        provider = OpenAIRealtimeProvider()

        mock_ws = AsyncMock()
        mock_ws.closed = False
        provider._ws = mock_ws
        provider._connected = True

        await provider.commit_audio()

        mock_ws.send.assert_called_once()

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "input_audio_buffer.commit"

    @pytest.mark.asyncio
    async def test_cancel_response_sends_cancel_event(self):
        """Test that cancel_response sends the cancel event."""
        provider = OpenAIRealtimeProvider()

        mock_ws = AsyncMock()
        mock_ws.closed = False
        provider._ws = mock_ws
        provider._connected = True

        await provider.cancel_response()

        mock_ws.send.assert_called_once()

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "response.cancel"

    @pytest.mark.asyncio
    async def test_create_response_sends_create_event(self):
        """Test that create_response sends the create event."""
        provider = OpenAIRealtimeProvider()

        mock_ws = AsyncMock()
        mock_ws.closed = False
        provider._ws = mock_ws
        provider._connected = True

        await provider.create_response()

        mock_ws.send.assert_called_once()

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "response.create"

    @pytest.mark.asyncio
    async def test_clear_audio_buffer(self):
        """Test clear_audio_buffer sends clear event."""
        provider = OpenAIRealtimeProvider()

        mock_ws = AsyncMock()
        mock_ws.closed = False
        provider._ws = mock_ws
        provider._connected = True

        await provider.clear_audio_buffer()

        mock_ws.send.assert_called_once()

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "input_audio_buffer.clear"


# =============================================================================
# Test Session Update
# =============================================================================


class TestOpenAIRealtimeProviderSessionUpdate:
    """Tests for session update."""

    @pytest.mark.asyncio
    async def test_update_session(self):
        """Test updating session configuration."""
        provider = OpenAIRealtimeProvider()

        mock_ws = AsyncMock()
        mock_ws.closed = False
        provider._ws = mock_ws
        provider._connected = True

        new_config = RealtimeSessionConfig(
            modalities=["text"],
            voice="coral",
            instructions="Be brief.",
            temperature=0.5,
        )

        await provider.update_session(new_config)

        mock_ws.send.assert_called_once()

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "session.update"
        assert sent_data["session"]["modalities"] == ["text"]
        assert sent_data["session"]["voice"] == "coral"
        assert sent_data["session"]["instructions"] == "Be brief."
        assert sent_data["session"]["temperature"] == 0.5


# =============================================================================
# Test Callbacks
# =============================================================================


class TestOpenAIRealtimeProviderCallbacks:
    """Tests for callback registration."""

    def test_on_audio_callback(self):
        """Test registering audio callback."""
        provider = OpenAIRealtimeProvider()

        callback = MagicMock()
        provider.on_audio(callback)

        assert provider._audio_callback is callback

    def test_on_text_callback(self):
        """Test registering text callback."""
        provider = OpenAIRealtimeProvider()

        callback = MagicMock()
        provider.on_text(callback)

        assert provider._text_callback is callback

    def test_on_transcript_callback(self):
        """Test registering transcript callback."""
        provider = OpenAIRealtimeProvider()

        callback = MagicMock()
        provider.on_transcript(callback)

        assert provider._transcript_callback is callback

    def test_on_error_callback(self):
        """Test registering error callback."""
        provider = OpenAIRealtimeProvider()

        callback = MagicMock()
        provider.on_error(callback)

        assert provider._error_callback is callback

    @pytest.mark.asyncio
    async def test_dispatch_audio_callback(self):
        """Test that audio callback is dispatched."""
        provider = OpenAIRealtimeProvider()

        callback = MagicMock()
        provider.on_audio(callback)

        event = RealtimeEvent(
            event_type=RealtimeEventType.RESPONSE_AUDIO_DELTA,
            audio=b"\x00\x01\x02\x03",
        )

        await provider._dispatch_callbacks(event)

        callback.assert_called_once_with(b"\x00\x01\x02\x03")

    @pytest.mark.asyncio
    async def test_dispatch_text_callback(self):
        """Test that text callback is dispatched."""
        provider = OpenAIRealtimeProvider()

        callback = MagicMock()
        provider.on_text(callback)

        event = RealtimeEvent(
            event_type=RealtimeEventType.RESPONSE_TEXT_DELTA,
            text="Hello",
        )

        await provider._dispatch_callbacks(event)

        callback.assert_called_once_with("Hello")


# =============================================================================
# Test VoiceRunnable Interface
# =============================================================================


class TestOpenAIRealtimeProviderVoiceRunnable:
    """Tests for VoiceRunnable interface."""

    @pytest.mark.asyncio
    async def test_ainvoke_with_bytes(self):
        """Test ainvoke with audio bytes."""
        provider = OpenAIRealtimeProvider()

        mock_ws = AsyncMock()
        mock_ws.closed = False
        provider._ws = mock_ws
        provider._connected = True

        # Set up event queue with response
        response_event = RealtimeEvent(
            event_type=RealtimeEventType.RESPONSE_DONE,
            data={"response": {"id": "resp_123"}},
        )
        await provider._event_queue.put(response_event)

        result = await provider.ainvoke(b"\x00\x01\x02\x03")

        assert result.event_type == RealtimeEventType.RESPONSE_DONE

    @pytest.mark.asyncio
    async def test_ainvoke_with_text(self):
        """Test ainvoke with text string."""
        provider = OpenAIRealtimeProvider()

        mock_ws = AsyncMock()
        mock_ws.closed = False
        provider._ws = mock_ws
        provider._connected = True

        # Set up event queue with response
        response_event = RealtimeEvent(
            event_type=RealtimeEventType.RESPONSE_DONE,
            data={"response": {"id": "resp_123"}},
        )
        await provider._event_queue.put(response_event)

        result = await provider.ainvoke("Hello")

        assert result.event_type == RealtimeEventType.RESPONSE_DONE

        # Verify text was sent
        calls = mock_ws.send.call_args_list
        assert any(
            "conversation.item.create" in call[0][0]
            for call in calls
        )

    @pytest.mark.asyncio
    async def test_ainvoke_raises_on_error(self):
        """Test that ainvoke raises on error event."""
        provider = OpenAIRealtimeProvider()

        mock_ws = AsyncMock()
        mock_ws.closed = False
        provider._ws = mock_ws
        provider._connected = True

        # Set up event queue with error
        error_event = RealtimeEvent(
            event_type=RealtimeEventType.ERROR,
            error="Something went wrong",
        )
        await provider._event_queue.put(error_event)

        with pytest.raises(RuntimeError, match="Something went wrong"):
            await provider.ainvoke("Hello")


# =============================================================================
# Test RealtimeEvent Dataclass
# =============================================================================


class TestRealtimeEvent:
    """Tests for RealtimeEvent dataclass."""

    def test_post_init_extracts_text(self):
        """Test that __post_init__ extracts text from data."""
        event = RealtimeEvent(
            event_type=RealtimeEventType.RESPONSE_TEXT_DELTA,
            data={"text": "Hello world"},
        )

        assert event.text == "Hello world"

    def test_post_init_extracts_transcript(self):
        """Test that __post_init__ extracts transcript from data."""
        event = RealtimeEvent(
            event_type=RealtimeEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA,
            data={"transcript": "User said hello"},
        )

        assert event.transcript == "User said hello"

    def test_post_init_extracts_error_dict(self):
        """Test that __post_init__ extracts error from dict."""
        event = RealtimeEvent(
            event_type=RealtimeEventType.ERROR,
            data={"error": {"message": "Invalid request", "code": "invalid"}},
        )

        assert event.error == "Invalid request"

    def test_post_init_extracts_error_string(self):
        """Test that __post_init__ extracts error from string."""
        event = RealtimeEvent(
            event_type=RealtimeEventType.ERROR,
            data={"error": "Simple error message"},
        )

        assert event.error == "Simple error message"

    def test_explicit_values_not_overwritten(self):
        """Test that explicit values are not overwritten by __post_init__."""
        event = RealtimeEvent(
            event_type=RealtimeEventType.RESPONSE_TEXT_DELTA,
            data={"text": "From data"},
            text="Explicit text",
        )

        assert event.text == "Explicit text"


# =============================================================================
# Integration Tests (require websockets and API key)
# =============================================================================


@pytest.mark.integration
class TestOpenAIRealtimeProviderIntegration:
    """Integration tests with real OpenAI Realtime API.

    These tests require:
    - websockets to be installed
    - OPENAI_API_KEY environment variable to be set
    - Valid API key with Realtime API access
    """

    @pytest.mark.asyncio
    async def test_real_connection(self):
        """Test real connection to OpenAI Realtime API."""
        pytest.importorskip("websockets")

        import os
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            pytest.skip("OPENAI_API_KEY not set")

        provider = OpenAIRealtimeProvider(
            model="gpt-4o-realtime-preview",
            voice="alloy",
            api_key=api_key,
        )

        try:
            await provider.connect()
            assert provider.is_connected

            # Send a simple text message
            await provider.send_text("Say hello in one word.")
            await provider.create_response()

            # Receive some events
            events_received = 0
            async for event in provider.receive_events():
                events_received += 1
                if event.event_type == RealtimeEventType.RESPONSE_DONE:
                    break
                if events_received > 100:  # Safety limit
                    break

            assert events_received > 0

        finally:
            await provider.disconnect()
