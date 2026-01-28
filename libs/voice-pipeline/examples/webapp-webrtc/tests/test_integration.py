"""Integration tests for WebRTC Voice Pipeline Demo."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.config import AppConfig, load_config
from backend.agent.session import VoiceAgentSession, SessionState, VADConfig
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.features.demo_tools import (
    get_current_time,
    get_weather,
    calculate,
    get_demo_tools,
)


class TestConfig:
    """Tests for configuration."""

    def test_load_config(self):
        """Test loading configuration."""
        config = load_config()
        assert isinstance(config, AppConfig)
        assert config.host is not None
        assert config.port > 0

    def test_config_defaults(self):
        """Test configuration defaults."""
        config = AppConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 8000
        assert config.webrtc.sample_rate == 16000


class TestDemoTools:
    """Tests for demo tools."""

    @pytest.mark.asyncio
    async def test_get_current_time(self):
        """Test get_current_time tool."""
        result = await get_current_time()
        assert result.success
        assert "time" in result.output
        assert "date" in result.output
        assert "formatted" in result.output

    @pytest.mark.asyncio
    async def test_get_current_time_with_timezone(self):
        """Test get_current_time with specific timezone."""
        result = await get_current_time(timezone="America/New_York")
        assert result.success
        assert result.output["timezone"] == "America/New_York"

    @pytest.mark.asyncio
    async def test_get_weather(self):
        """Test get_weather tool."""
        result = await get_weather(city="Sao Paulo")
        assert result.success
        assert result.output["city"] == "Sao Paulo"
        assert "temperature_celsius" in result.output
        assert "condition" in result.output

    @pytest.mark.asyncio
    async def test_calculate_simple(self):
        """Test calculate tool with simple expression."""
        result = await calculate("2 + 2")
        assert result.success
        assert result.output["result"] == 4

    @pytest.mark.asyncio
    async def test_calculate_complex(self):
        """Test calculate tool with complex expression."""
        result = await calculate("10 * 5 + 3")
        assert result.success
        assert result.output["result"] == 53

    @pytest.mark.asyncio
    async def test_calculate_invalid(self):
        """Test calculate tool with invalid expression."""
        result = await calculate("import os")  # Should be blocked
        assert not result.success

    def test_get_demo_tools(self):
        """Test getting all demo tools."""
        tools = get_demo_tools()
        assert len(tools) >= 5
        tool_names = [t.name for t in tools]
        assert "get_current_time" in tool_names
        assert "get_weather" in tool_names
        assert "calculate" in tool_names


class TestVoiceAgentSession:
    """Tests for VoiceAgentSession."""

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport."""
        transport = MagicMock()
        transport.event_emitter = MagicMock()
        transport.event_emitter.emit = AsyncMock()
        transport.read_frames = AsyncMock(return_value=iter([]))
        transport.write_bytes = AsyncMock()
        transport.clear_output_queue = MagicMock()
        return transport

    def test_session_initialization(self, mock_transport):
        """Test session initialization."""
        session = VoiceAgentSession(
            session_id="test-123",
            transport=mock_transport,
        )
        assert session.session_id == "test-123"
        assert session.state == SessionState.IDLE

    def test_session_state_transitions(self, mock_transport):
        """Test session state transitions."""
        session = VoiceAgentSession(
            session_id="test-123",
            transport=mock_transport,
        )

        states = []
        session.on_state_change(lambda s: states.append(s))

        session._set_state(SessionState.LISTENING)
        session._set_state(SessionState.PROCESSING)
        session._set_state(SessionState.SPEAKING)

        assert states == [SessionState.LISTENING, SessionState.PROCESSING, SessionState.SPEAKING]

    def test_interrupt(self, mock_transport):
        """Test session interruption."""
        session = VoiceAgentSession(
            session_id="test-123",
            transport=mock_transport,
        )
        session._set_state(SessionState.SPEAKING)

        session.interrupt()

        assert session._interrupted
        mock_transport.clear_output_queue.assert_called_once()

    def test_vad_config(self, mock_transport):
        """Test VAD configuration."""
        vad_config = VADConfig(
            threshold=0.6,
            min_speech_duration_ms=300,
            min_silence_duration_ms=600,
        )
        session = VoiceAgentSession(
            session_id="test-123",
            transport=mock_transport,
            vad_config=vad_config,
        )

        assert session.vad_config.threshold == 0.6
        assert session.vad_config.min_speech_duration_ms == 300

    def test_metrics_initialization(self, mock_transport):
        """Test metrics initialization."""
        session = VoiceAgentSession(
            session_id="test-123",
            transport=mock_transport,
        )

        metrics = session.metrics
        assert metrics.turn_count == 0
        assert metrics.total_audio_duration_ms == 0.0

    def test_metrics_to_dict(self, mock_transport):
        """Test metrics serialization."""
        session = VoiceAgentSession(
            session_id="test-123",
            transport=mock_transport,
        )
        session._metrics.turn_count = 5
        session._metrics.ttfa = 0.5

        metrics_dict = session.metrics.to_dict()
        assert metrics_dict["turn_count"] == 5
        assert metrics_dict["latency"]["ttfa_ms"] == 500


class TestSessionCallbacks:
    """Tests for session callbacks."""

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport."""
        transport = MagicMock()
        transport.event_emitter = MagicMock()
        transport.event_emitter.emit = AsyncMock()
        return transport

    @pytest.mark.asyncio
    async def test_on_speech_start_callback(self, mock_transport):
        """Test speech start callback."""
        session = VoiceAgentSession(
            session_id="test-123",
            transport=mock_transport,
        )

        callback_called = []
        session.on_speech_start(lambda: callback_called.append(True))

        await session._on_speech_started()

        assert len(callback_called) == 1
        assert session._is_speech

    @pytest.mark.asyncio
    async def test_on_speech_end_callback(self, mock_transport):
        """Test speech end callback."""
        session = VoiceAgentSession(
            session_id="test-123",
            transport=mock_transport,
        )

        received_audio = []
        session.on_speech_end(lambda audio: received_audio.append(audio))

        # Simulate speech
        session._is_speech = True
        session._speech_start_time = asyncio.get_event_loop().time() - 1  # 1 second ago
        session._speech_buffer = [b"audio1", b"audio2"]

        await session._on_speech_ended()

        assert len(received_audio) == 1
        assert received_audio[0] == b"audio1audio2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
