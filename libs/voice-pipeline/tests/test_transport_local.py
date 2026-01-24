"""Tests for LocalAudioTransport."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from voice_pipeline.transport.local import (
    LocalAudioTransport,
    LocalAudioConfig,
    _get_sounddevice,
)
from voice_pipeline.interfaces.transport import (
    AudioFrame,
    TransportState,
)
from voice_pipeline.providers.base import HealthCheckResult, ProviderHealth


# ==================== Test Configuration ====================


class TestLocalAudioConfig:
    """Tests for LocalAudioConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = LocalAudioConfig()

        assert config.input_device is None
        assert config.output_device is None
        assert config.input_sample_rate == 16000
        assert config.output_sample_rate == 24000
        assert config.input_channels == 1
        assert config.output_channels == 1
        assert config.buffer_size_ms == 20
        assert config.latency == "low"
        assert config.enable_echo_cancellation is False
        assert config.enable_noise_suppression is False
        assert config.enable_auto_gain_control is False
        assert config.monitor_levels is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = LocalAudioConfig(
            input_device=1,
            output_device=2,
            input_sample_rate=44100,
            output_sample_rate=48000,
            input_channels=2,
            output_channels=2,
            buffer_size_ms=40,
            latency="high",
            enable_echo_cancellation=True,
            enable_noise_suppression=True,
            enable_auto_gain_control=True,
            monitor_levels=False,
        )

        assert config.input_device == 1
        assert config.output_device == 2
        assert config.input_sample_rate == 44100
        assert config.output_sample_rate == 48000
        assert config.input_channels == 2
        assert config.output_channels == 2
        assert config.buffer_size_ms == 40
        assert config.latency == "high"
        assert config.enable_echo_cancellation is True
        assert config.enable_noise_suppression is True
        assert config.enable_auto_gain_control is True
        assert config.monitor_levels is False


# ==================== Test Initialization ====================


class TestLocalAudioTransportInit:
    """Tests for LocalAudioTransport initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        transport = LocalAudioTransport()

        assert transport.name == "LocalAudioTransport"
        assert transport.state == TransportState.IDLE
        assert not transport.is_running

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        transport = LocalAudioTransport(
            input_device=1,
            output_device=2,
            input_sample_rate=44100,
            output_sample_rate=48000,
            buffer_size_ms=40,
        )

        assert transport._config_obj.input_device == 1
        assert transport._config_obj.output_device == 2
        assert transport._config_obj.input_sample_rate == 44100
        assert transport._config_obj.output_sample_rate == 48000
        assert transport._config_obj.buffer_size_ms == 40

    def test_transport_config(self):
        """Test transport configuration is set correctly."""
        transport = LocalAudioTransport(
            input_sample_rate=44100,
            output_sample_rate=48000,
            input_channels=2,
            output_channels=2,
        )

        config = transport.config
        assert config.input_config.sample_rate == 44100
        assert config.output_config.sample_rate == 48000
        assert config.input_config.channels == 2
        assert config.output_config.channels == 2


# ==================== Test Sounddevice Import ====================


class TestSounddeviceImport:
    """Tests for sounddevice lazy import."""

    def test_import_error_when_missing(self):
        """Test that ImportError is raised when sounddevice is missing."""
        with patch.dict("sys.modules", {"sounddevice": None}):
            # Reset the cached module
            import voice_pipeline.transport.local as local_module
            local_module._sounddevice = None

            with patch("builtins.__import__", side_effect=ImportError("No module")):
                with pytest.raises(ImportError, match="sounddevice is required"):
                    _get_sounddevice()


# ==================== Test Start/Stop with Mocked Sounddevice ====================


class TestLocalAudioTransportStartStop:
    """Tests for start/stop with mocked sounddevice."""

    @pytest.fixture
    def mock_sounddevice(self):
        """Create a mock sounddevice module."""
        mock_sd = MagicMock()

        # Mock stream classes
        mock_input_stream = MagicMock()
        mock_output_stream = MagicMock()
        mock_sd.InputStream.return_value = mock_input_stream
        mock_sd.OutputStream.return_value = mock_output_stream

        # Mock query_devices
        mock_sd.query_devices.return_value = [
            {
                "name": "Test Input",
                "max_input_channels": 2,
                "max_output_channels": 0,
                "default_samplerate": 44100.0,
            },
            {
                "name": "Test Output",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": 44100.0,
            },
        ]

        # Mock default device
        mock_sd.default.device = (0, 1)

        return mock_sd

    @pytest.fixture
    def transport_with_mock(self, mock_sounddevice):
        """Create transport with mocked sounddevice."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice
        return LocalAudioTransport()

    @pytest.mark.asyncio
    async def test_start_opens_streams(self, transport_with_mock, mock_sounddevice):
        """Test that start opens input and output streams."""
        await transport_with_mock.start()

        # Verify streams were created
        mock_sounddevice.InputStream.assert_called_once()
        mock_sounddevice.OutputStream.assert_called_once()

        # Verify streams were started
        mock_sounddevice.InputStream.return_value.start.assert_called_once()
        mock_sounddevice.OutputStream.return_value.start.assert_called_once()

        assert transport_with_mock.is_running
        assert transport_with_mock.state == TransportState.RUNNING

        await transport_with_mock.stop()

    @pytest.mark.asyncio
    async def test_start_with_custom_device(self, mock_sounddevice):
        """Test that start uses custom devices."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice

        transport = LocalAudioTransport(input_device=1, output_device=2)
        await transport.start()

        # Verify device was passed to InputStream
        call_kwargs = mock_sounddevice.InputStream.call_args[1]
        assert call_kwargs["device"] == 1

        # Verify device was passed to OutputStream
        call_kwargs = mock_sounddevice.OutputStream.call_args[1]
        assert call_kwargs["device"] == 2

        await transport.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_streams(self, transport_with_mock, mock_sounddevice):
        """Test that stop closes streams."""
        await transport_with_mock.start()
        await transport_with_mock.stop()

        # Verify streams were stopped and closed
        input_stream = mock_sounddevice.InputStream.return_value
        output_stream = mock_sounddevice.OutputStream.return_value

        input_stream.stop.assert_called_once()
        input_stream.close.assert_called_once()
        output_stream.stop.assert_called_once()
        output_stream.close.assert_called_once()

        assert not transport_with_mock.is_running
        assert transport_with_mock.state == TransportState.STOPPED

    @pytest.mark.asyncio
    async def test_double_start_warning(self, transport_with_mock):
        """Test that double start logs warning."""
        await transport_with_mock.start()
        await transport_with_mock.start()  # Should not raise

        assert transport_with_mock.is_running
        await transport_with_mock.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self, transport_with_mock):
        """Test that stop without start is safe."""
        await transport_with_mock.stop()  # Should not raise
        assert not transport_with_mock.is_running

    @pytest.mark.asyncio
    async def test_context_manager(self, transport_with_mock):
        """Test async context manager."""
        async with transport_with_mock as transport:
            assert transport.is_running
            assert transport.state == TransportState.RUNNING

        assert not transport.is_running
        assert transport.state == TransportState.STOPPED


# ==================== Test Read/Write ====================


class TestLocalAudioTransportReadWrite:
    """Tests for read/write operations."""

    @pytest.fixture
    def mock_sounddevice(self):
        """Create a mock sounddevice module."""
        mock_sd = MagicMock()
        mock_sd.InputStream.return_value = MagicMock()
        mock_sd.OutputStream.return_value = MagicMock()
        mock_sd.query_devices.return_value = []
        mock_sd.default.device = (0, 1)
        return mock_sd

    @pytest.fixture
    def transport_with_mock(self, mock_sounddevice):
        """Create transport with mocked sounddevice."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice
        return LocalAudioTransport()

    @pytest.mark.asyncio
    async def test_write_bytes_queues_data(self, transport_with_mock):
        """Test that write_bytes queues data."""
        await transport_with_mock.start()

        audio = b"\x00" * 1600  # 50ms of 16kHz mono audio
        await transport_with_mock.write_bytes(audio)

        # Data should be in output queue
        assert not transport_with_mock._output_queue.empty()

        await transport_with_mock.stop()

    @pytest.mark.asyncio
    async def test_write_frame_queues_data(self, transport_with_mock):
        """Test that write_frame queues data."""
        await transport_with_mock.start()

        frame = AudioFrame(
            data=b"\x00" * 1600,
            sample_rate=16000,
            channels=1,
            sample_width=2,
        )
        await transport_with_mock.write_frame(frame)

        # Data should be in output queue
        assert not transport_with_mock._output_queue.empty()

        await transport_with_mock.stop()

    @pytest.mark.asyncio
    async def test_write_without_start_raises(self, transport_with_mock):
        """Test that writing without start raises error."""
        with pytest.raises(RuntimeError, match="not running"):
            await transport_with_mock.write_bytes(b"test")

    @pytest.mark.asyncio
    async def test_read_frames_yields_from_queue(self, transport_with_mock):
        """Test that read_frames yields frames from queue."""
        await transport_with_mock.start()

        # Put a frame in the input queue
        frame = AudioFrame(
            data=b"\x00" * 640,
            sample_rate=16000,
            channels=1,
            sample_width=2,
        )
        await transport_with_mock._input_queue.put(frame)

        # Stop immediately to end the loop
        transport_with_mock._running = False

        # Should yield the queued frame
        frames = []
        async for f in transport_with_mock.read_frames():
            frames.append(f)

        assert len(frames) == 1
        assert frames[0] == frame


# ==================== Test Pause/Resume ====================


class TestLocalAudioTransportPauseResume:
    """Tests for pause/resume functionality."""

    @pytest.fixture
    def mock_sounddevice(self):
        """Create a mock sounddevice module."""
        mock_sd = MagicMock()
        mock_sd.InputStream.return_value = MagicMock()
        mock_sd.OutputStream.return_value = MagicMock()
        return mock_sd

    @pytest.fixture
    def transport_with_mock(self, mock_sounddevice):
        """Create transport with mocked sounddevice."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice
        return LocalAudioTransport()

    @pytest.mark.asyncio
    async def test_pause_changes_state(self, transport_with_mock):
        """Test that pause changes state."""
        await transport_with_mock.start()

        await transport_with_mock.pause()
        assert transport_with_mock.state == TransportState.PAUSED
        assert transport_with_mock._paused is True

        await transport_with_mock.stop()

    @pytest.mark.asyncio
    async def test_resume_changes_state(self, transport_with_mock):
        """Test that resume changes state."""
        await transport_with_mock.start()

        await transport_with_mock.pause()
        await transport_with_mock.resume()

        assert transport_with_mock.state == TransportState.RUNNING
        assert transport_with_mock._paused is False

        await transport_with_mock.stop()

    @pytest.mark.asyncio
    async def test_pause_without_start_raises(self, transport_with_mock):
        """Test that pause without start raises."""
        with pytest.raises(RuntimeError, match="not running"):
            await transport_with_mock.pause()

    @pytest.mark.asyncio
    async def test_resume_without_start_raises(self, transport_with_mock):
        """Test that resume without start raises."""
        with pytest.raises(RuntimeError, match="not running"):
            await transport_with_mock.resume()


# ==================== Test Mute ====================


class TestLocalAudioTransportMute:
    """Tests for mute functionality."""

    @pytest.fixture
    def mock_sounddevice(self):
        """Create a mock sounddevice module."""
        mock_sd = MagicMock()
        mock_sd.InputStream.return_value = MagicMock()
        mock_sd.OutputStream.return_value = MagicMock()
        return mock_sd

    @pytest.fixture
    def transport_with_mock(self, mock_sounddevice):
        """Create transport with mocked sounddevice."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice
        return LocalAudioTransport()

    @pytest.mark.asyncio
    async def test_set_input_muted(self, transport_with_mock):
        """Test muting input."""
        await transport_with_mock.set_input_muted(True)
        assert transport_with_mock._input_muted is True

        await transport_with_mock.set_input_muted(False)
        assert transport_with_mock._input_muted is False

    @pytest.mark.asyncio
    async def test_set_output_muted(self, transport_with_mock):
        """Test muting output."""
        await transport_with_mock.set_output_muted(True)
        assert transport_with_mock._output_muted is True

        await transport_with_mock.set_output_muted(False)
        assert transport_with_mock._output_muted is False


# ==================== Test Level Monitoring ====================


class TestLocalAudioTransportLevels:
    """Tests for level monitoring."""

    @pytest.fixture
    def mock_sounddevice(self):
        """Create a mock sounddevice module."""
        mock_sd = MagicMock()
        mock_sd.InputStream.return_value = MagicMock()
        mock_sd.OutputStream.return_value = MagicMock()
        return mock_sd

    @pytest.fixture
    def transport_with_mock(self, mock_sounddevice):
        """Create transport with mocked sounddevice."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice
        return LocalAudioTransport()

    @pytest.mark.asyncio
    async def test_get_input_level(self, transport_with_mock):
        """Test getting input level."""
        transport_with_mock._input_level = 0.5
        level = await transport_with_mock.get_input_level()
        assert level == 0.5

    @pytest.mark.asyncio
    async def test_get_output_level(self, transport_with_mock):
        """Test getting output level."""
        transport_with_mock._output_level = 0.3
        level = await transport_with_mock.get_output_level()
        assert level == 0.3


# ==================== Test Device Management ====================


class TestLocalAudioTransportDevices:
    """Tests for device management."""

    @pytest.fixture
    def mock_sounddevice(self):
        """Create a mock sounddevice module."""
        mock_sd = MagicMock()
        mock_sd.query_devices.return_value = [
            {
                "name": "Built-in Microphone",
                "max_input_channels": 2,
                "max_output_channels": 0,
                "default_samplerate": 44100.0,
            },
            {
                "name": "Built-in Speaker",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": 44100.0,
            },
            {
                "name": "USB Audio",
                "max_input_channels": 2,
                "max_output_channels": 2,
                "default_samplerate": 48000.0,
            },
        ]
        mock_sd.default.device = (0, 1)
        return mock_sd

    def test_list_devices(self, mock_sounddevice):
        """Test listing audio devices."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice

        devices = LocalAudioTransport.list_devices()

        assert len(devices) == 3
        assert devices[0]["name"] == "Built-in Microphone"
        assert devices[0]["is_input"] is True
        assert devices[0]["is_output"] is False
        assert devices[1]["name"] == "Built-in Speaker"
        assert devices[1]["is_input"] is False
        assert devices[1]["is_output"] is True
        assert devices[2]["is_input"] is True
        assert devices[2]["is_output"] is True

    def test_get_default_input_device(self, mock_sounddevice):
        """Test getting default input device."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice

        device = LocalAudioTransport.get_default_input_device()
        assert device == 0

    def test_get_default_output_device(self, mock_sounddevice):
        """Test getting default output device."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice

        device = LocalAudioTransport.get_default_output_device()
        assert device == 1


# ==================== Test Health Check ====================


class TestLocalAudioTransportHealthCheck:
    """Tests for health check."""

    @pytest.fixture
    def mock_sounddevice(self):
        """Create a mock sounddevice module."""
        mock_sd = MagicMock()
        mock_sd.query_devices.return_value = [
            {"name": "Input", "max_input_channels": 2, "max_output_channels": 0},
            {"name": "Output", "max_input_channels": 0, "max_output_channels": 2},
        ]
        return mock_sd

    @pytest.mark.asyncio
    async def test_health_check_with_sounddevice(self, mock_sounddevice):
        """Test health check when sounddevice is available."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice

        transport = LocalAudioTransport()
        health = await transport._do_health_check()

        assert isinstance(health, HealthCheckResult)
        assert health.status == ProviderHealth.HEALTHY
        assert health.details["sounddevice_available"] is True
        assert health.details["input_device_available"] is True
        assert health.details["output_device_available"] is True
        assert health.details["state"] == "idle"
        assert health.details["is_running"] is False

    @pytest.mark.asyncio
    async def test_health_check_without_sounddevice(self):
        """Test health check when sounddevice is not available."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = None

        transport = LocalAudioTransport()

        with patch.object(
            local_module,
            "_get_sounddevice",
            side_effect=ImportError("Not installed"),
        ):
            health = await transport._do_health_check()

        assert isinstance(health, HealthCheckResult)
        assert health.status == ProviderHealth.UNHEALTHY
        assert health.details["sounddevice_available"] is False


# ==================== Test Callbacks ====================


class TestLocalAudioTransportCallbacks:
    """Tests for callback registration."""

    @pytest.fixture
    def mock_sounddevice(self):
        """Create a mock sounddevice module."""
        mock_sd = MagicMock()
        mock_sd.InputStream.return_value = MagicMock()
        mock_sd.OutputStream.return_value = MagicMock()
        return mock_sd

    @pytest.fixture
    def transport_with_mock(self, mock_sounddevice):
        """Create transport with mocked sounddevice."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice
        return LocalAudioTransport()

    @pytest.mark.asyncio
    async def test_state_callback_is_called(self, transport_with_mock):
        """Test that state callback is called."""
        states = []
        transport_with_mock.on_state_change(lambda s: states.append(s))

        await transport_with_mock.start()
        await transport_with_mock.stop()

        assert TransportState.STARTING in states
        assert TransportState.RUNNING in states
        assert TransportState.STOPPING in states
        assert TransportState.STOPPED in states

    @pytest.mark.asyncio
    async def test_error_callback_on_stream_error(self, transport_with_mock, mock_sounddevice):
        """Test that error callback is called on stream error."""
        mock_sounddevice.InputStream.side_effect = Exception("Stream error")

        errors = []
        transport_with_mock.on_error(lambda e: errors.append(e))

        with pytest.raises(Exception, match="Stream error"):
            await transport_with_mock.start()

        assert len(errors) == 1
        assert str(errors[0]) == "Stream error"


# ==================== Test Input Callback ====================


class TestLocalAudioTransportInputCallback:
    """Tests for the internal input callback."""

    @pytest.fixture
    def mock_sounddevice(self):
        """Create a mock sounddevice module."""
        mock_sd = MagicMock()
        mock_sd.InputStream.return_value = MagicMock()
        mock_sd.OutputStream.return_value = MagicMock()
        return mock_sd

    @pytest.fixture
    def transport_with_mock(self, mock_sounddevice):
        """Create transport with mocked sounddevice."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice
        transport = LocalAudioTransport()
        transport._running = True
        transport._start_time = 0
        return transport

    def test_input_callback_creates_frame(self, transport_with_mock):
        """Test that input callback creates frames."""
        import numpy as np

        # Simulate audio input
        indata = np.zeros((320, 1), dtype=np.float32)  # 20ms of audio
        indata[:, 0] = np.sin(np.linspace(0, 2 * np.pi, 320)) * 0.5

        transport_with_mock._input_callback_fn(
            indata=indata,
            frames=320,
            time_info={},
            status=0,
        )

        # Check that frame was queued
        assert not transport_with_mock._input_queue.empty()

        frame = transport_with_mock._input_queue.get_nowait()
        assert isinstance(frame, AudioFrame)
        assert frame.sample_rate == 16000
        assert frame.sequence_number == 0

    def test_input_callback_skips_when_muted(self, transport_with_mock):
        """Test that input callback skips when muted."""
        import numpy as np

        transport_with_mock._input_muted = True

        indata = np.zeros((320, 1), dtype=np.float32)
        transport_with_mock._input_callback_fn(
            indata=indata,
            frames=320,
            time_info={},
            status=0,
        )

        # Queue should be empty
        assert transport_with_mock._input_queue.empty()

    def test_input_callback_skips_when_paused(self, transport_with_mock):
        """Test that input callback skips when paused."""
        import numpy as np

        transport_with_mock._paused = True

        indata = np.zeros((320, 1), dtype=np.float32)
        transport_with_mock._input_callback_fn(
            indata=indata,
            frames=320,
            time_info={},
            status=0,
        )

        # Queue should be empty
        assert transport_with_mock._input_queue.empty()


# ==================== Test Output Callback ====================


class TestLocalAudioTransportOutputCallback:
    """Tests for the internal output callback."""

    @pytest.fixture
    def mock_sounddevice(self):
        """Create a mock sounddevice module."""
        mock_sd = MagicMock()
        mock_sd.InputStream.return_value = MagicMock()
        mock_sd.OutputStream.return_value = MagicMock()
        return mock_sd

    @pytest.fixture
    def transport_with_mock(self, mock_sounddevice):
        """Create transport with mocked sounddevice."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice
        transport = LocalAudioTransport()
        transport._running = True
        return transport

    def test_output_callback_reads_from_queue(self, transport_with_mock):
        """Test that output callback reads from queue."""
        import numpy as np

        # Put audio data in queue
        audio = b"\x00\x10" * 480  # 480 samples
        transport_with_mock._output_queue.put_nowait(audio)

        outdata = np.zeros((480, 1), dtype=np.float32)
        transport_with_mock._output_callback_fn(
            outdata=outdata,
            frames=480,
            time_info={},
            status=0,
        )

        # outdata should have been filled
        assert not np.all(outdata == 0)

    def test_output_callback_outputs_silence_when_empty(self, transport_with_mock):
        """Test that output callback outputs silence when queue is empty."""
        import numpy as np

        outdata = np.ones((480, 1), dtype=np.float32)
        transport_with_mock._output_callback_fn(
            outdata=outdata,
            frames=480,
            time_info={},
            status=0,
        )

        # outdata should be all zeros (silence)
        assert np.all(outdata == 0)

    def test_output_callback_outputs_silence_when_muted(self, transport_with_mock):
        """Test that output callback outputs silence when muted."""
        import numpy as np

        transport_with_mock._output_muted = True

        audio = b"\x00\x10" * 480
        transport_with_mock._output_queue.put_nowait(audio)

        outdata = np.ones((480, 1), dtype=np.float32)
        transport_with_mock._output_callback_fn(
            outdata=outdata,
            frames=480,
            time_info={},
            status=0,
        )

        # outdata should be all zeros (silence)
        assert np.all(outdata == 0)


# ==================== Test VoiceRunnable Implementation ====================


class TestLocalAudioTransportVoiceRunnable:
    """Tests for VoiceRunnable implementation."""

    @pytest.fixture
    def mock_sounddevice(self):
        """Create a mock sounddevice module."""
        mock_sd = MagicMock()
        mock_sd.InputStream.return_value = MagicMock()
        mock_sd.OutputStream.return_value = MagicMock()
        return mock_sd

    @pytest.fixture
    def transport_with_mock(self, mock_sounddevice):
        """Create transport with mocked sounddevice."""
        import voice_pipeline.transport.local as local_module
        local_module._sounddevice = mock_sounddevice
        return LocalAudioTransport()

    @pytest.mark.asyncio
    async def test_ainvoke_writes_and_reads(self, transport_with_mock):
        """Test ainvoke writes input and returns frame."""
        await transport_with_mock.start()

        # Pre-populate input queue with a frame
        frame = AudioFrame(
            data=b"\x00" * 640,
            sample_rate=16000,
            channels=1,
            sample_width=2,
        )
        await transport_with_mock._input_queue.put(frame)

        input_audio = b"\x00" * 640
        result = await transport_with_mock.ainvoke(input_audio)

        assert isinstance(result, AudioFrame)
        assert result == frame

        await transport_with_mock.stop()

    @pytest.mark.asyncio
    async def test_astream_writes_and_yields(self, transport_with_mock):
        """Test astream writes input and yields frames."""
        await transport_with_mock.start()

        # Pre-populate input queue
        for i in range(3):
            frame = AudioFrame(
                data=b"\x00" * 640,
                sample_rate=16000,
                channels=1,
                sample_width=2,
                sequence_number=i,
            )
            await transport_with_mock._input_queue.put(frame)

        # Stop after a short time
        async def stop_later():
            await asyncio.sleep(0.01)
            transport_with_mock._running = False

        asyncio.create_task(stop_later())

        input_audio = b"\x00" * 640
        frames = []
        async for f in transport_with_mock.astream(input_audio):
            frames.append(f)

        assert len(frames) == 3
        assert all(isinstance(f, AudioFrame) for f in frames)
