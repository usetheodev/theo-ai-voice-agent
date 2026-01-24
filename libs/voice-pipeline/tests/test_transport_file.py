"""Tests for FileAudioTransport."""

import asyncio
import struct
import tempfile
import wave
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_pipeline.transport.file import (
    FileAudioTransport,
    FileAudioConfig,
    create_test_audio,
    create_silence,
)
from voice_pipeline.interfaces.transport import (
    AudioFrame,
    TransportState,
)
from voice_pipeline.providers.base import HealthCheckResult, ProviderHealth


# ==================== Test Utilities ====================


class TestCreateTestAudio:
    """Tests for create_test_audio utility."""

    def test_creates_audio_with_default_params(self):
        """Test creating test audio with defaults."""
        audio = create_test_audio()

        # 1 second at 16kHz = 16000 samples * 2 bytes = 32000 bytes
        assert len(audio) == 32000

    def test_creates_audio_with_custom_duration(self):
        """Test creating audio with custom duration."""
        audio = create_test_audio(duration_seconds=0.5)

        # 0.5 seconds at 16kHz = 8000 samples * 2 bytes = 16000 bytes
        assert len(audio) == 16000

    def test_creates_audio_with_custom_sample_rate(self):
        """Test creating audio with custom sample rate."""
        audio = create_test_audio(duration_seconds=1.0, sample_rate=8000)

        # 1 second at 8kHz = 8000 samples * 2 bytes = 16000 bytes
        assert len(audio) == 16000

    def test_audio_is_not_silent(self):
        """Test that generated audio is not silent."""
        audio = create_test_audio(amplitude=0.5)

        # Unpack samples and check some are non-zero
        samples = struct.unpack(f"<{len(audio)//2}h", audio)
        assert max(abs(s) for s in samples) > 0

    def test_audio_respects_amplitude(self):
        """Test that amplitude affects the audio level."""
        audio_loud = create_test_audio(amplitude=0.9)
        audio_quiet = create_test_audio(amplitude=0.1)

        samples_loud = struct.unpack(f"<{len(audio_loud)//2}h", audio_loud)
        samples_quiet = struct.unpack(f"<{len(audio_quiet)//2}h", audio_quiet)

        max_loud = max(abs(s) for s in samples_loud)
        max_quiet = max(abs(s) for s in samples_quiet)

        assert max_loud > max_quiet


class TestCreateSilence:
    """Tests for create_silence utility."""

    def test_creates_silence_with_default_params(self):
        """Test creating silence with defaults."""
        audio = create_silence()

        # 1 second at 16kHz = 16000 samples * 2 bytes = 32000 bytes
        assert len(audio) == 32000

    def test_silence_is_all_zeros(self):
        """Test that silence is all zeros."""
        audio = create_silence()
        assert audio == b"\x00" * len(audio)

    def test_creates_silence_with_custom_duration(self):
        """Test creating silence with custom duration."""
        audio = create_silence(duration_seconds=0.5)
        assert len(audio) == 16000


# ==================== Test Configuration ====================


class TestFileAudioConfig:
    """Tests for FileAudioConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = FileAudioConfig()

        assert config.input_file is None
        assert config.output_file is None
        assert config.sample_rate == 16000
        assert config.channels == 1
        assert config.chunk_duration_ms == 20
        assert config.loop_input is False
        assert config.real_time is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = FileAudioConfig(
            input_file="input.wav",
            output_file="output.wav",
            sample_rate=44100,
            channels=2,
            chunk_duration_ms=40,
            loop_input=True,
            real_time=False,
        )

        assert config.input_file == "input.wav"
        assert config.output_file == "output.wav"
        assert config.sample_rate == 44100
        assert config.channels == 2
        assert config.chunk_duration_ms == 40
        assert config.loop_input is True
        assert config.real_time is False


# ==================== Test Initialization ====================


class TestFileAudioTransportInit:
    """Tests for FileAudioTransport initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        transport = FileAudioTransport()

        assert transport.name == "FileAudioTransport"
        assert transport.state == TransportState.IDLE
        assert not transport.is_running

    def test_init_with_input_file(self):
        """Test initialization with input file."""
        transport = FileAudioTransport(input_file="test.wav")

        assert transport._config_obj.input_file == "test.wav"

    def test_init_with_output_file(self):
        """Test initialization with output file."""
        transport = FileAudioTransport(output_file="output.wav")

        assert transport._config_obj.output_file == "output.wav"

    def test_init_with_path_object(self):
        """Test initialization with Path object."""
        transport = FileAudioTransport(
            input_file=Path("input.wav"),
            output_file=Path("output.wav"),
        )

        assert transport._config_obj.input_file == "input.wav"
        assert transport._config_obj.output_file == "output.wav"

    def test_transport_config(self):
        """Test transport configuration is set correctly."""
        transport = FileAudioTransport(
            sample_rate=44100,
            channels=2,
            chunk_duration_ms=40,
        )

        config = transport.config
        assert config.input_config.sample_rate == 44100
        assert config.input_config.channels == 2
        assert config.buffer_size_ms == 40


# ==================== Test Start/Stop ====================


class TestFileAudioTransportStartStop:
    """Tests for start/stop functionality."""

    @pytest.mark.asyncio
    async def test_start_with_no_files(self):
        """Test starting transport with no files."""
        transport = FileAudioTransport()
        await transport.start()

        assert transport.is_running
        assert transport.state == TransportState.RUNNING

        await transport.stop()
        assert not transport.is_running

    @pytest.mark.asyncio
    async def test_start_with_nonexistent_input_file(self):
        """Test starting with non-existent input file raises error."""
        transport = FileAudioTransport(input_file="nonexistent.wav")

        with pytest.raises(FileNotFoundError):
            await transport.start()

        assert transport.state == TransportState.ERROR

    @pytest.mark.asyncio
    async def test_start_creates_output_directory(self):
        """Test that start creates output directory if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "subdir" / "output.wav"
            transport = FileAudioTransport(output_file=str(output_path))

            await transport.start()
            assert output_path.parent.exists()

            await transport.stop()

    @pytest.mark.asyncio
    async def test_double_start_warning(self):
        """Test that double start logs warning."""
        transport = FileAudioTransport()
        await transport.start()
        await transport.start()  # Should not raise

        assert transport.is_running
        await transport.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """Test that stop without start is safe."""
        transport = FileAudioTransport()
        await transport.stop()  # Should not raise

        assert not transport.is_running

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        async with FileAudioTransport() as transport:
            assert transport.is_running
            assert transport.state == TransportState.RUNNING

        assert not transport.is_running
        assert transport.state == TransportState.STOPPED


# ==================== Test Input Data ====================


class TestFileAudioTransportInputData:
    """Tests for direct input data."""

    @pytest.mark.asyncio
    async def test_set_input_data(self):
        """Test setting input data directly."""
        transport = FileAudioTransport(real_time=False)
        audio = create_test_audio(duration_seconds=0.1)

        transport.set_input_data(audio)
        await transport.start()

        frames = []
        async for frame in transport.read_frames():
            frames.append(frame)

        await transport.stop()

        # Should have received some frames
        assert len(frames) > 0

        # Total data should match input
        total_data = b"".join(f.data for f in frames)
        assert len(total_data) == len(audio)

    @pytest.mark.asyncio
    async def test_input_data_loop(self):
        """Test looping input data."""
        transport = FileAudioTransport(
            real_time=False,
            loop_input=True,
            chunk_duration_ms=100,
        )

        # Create short audio
        audio = create_test_audio(duration_seconds=0.1)
        transport.set_input_data(audio)

        await transport.start()

        # Read more than the input length
        frames = []
        for _ in range(5):
            async for frame in transport.read_frames():
                frames.append(frame)
                if len(frames) >= 5:
                    break
            if len(frames) >= 5:
                break

        await transport.stop()

        # Should have looped
        assert len(frames) >= 5

    @pytest.mark.asyncio
    async def test_input_data_no_loop_ends(self):
        """Test that input data ends without loop."""
        transport = FileAudioTransport(
            real_time=False,
            loop_input=False,
            chunk_duration_ms=50,
        )

        audio = create_test_audio(duration_seconds=0.1)
        transport.set_input_data(audio)

        await transport.start()

        frames = []
        async for frame in transport.read_frames():
            frames.append(frame)

        await transport.stop()

        # Should have ended after processing all input
        assert len(frames) >= 1


# ==================== Test Input File ====================


class TestFileAudioTransportInputFile:
    """Tests for input file reading."""

    @pytest.fixture
    def test_wav_file(self):
        """Create a test WAV file."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            # Create WAV file
            with wave.open(f.name, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                audio = create_test_audio(duration_seconds=0.5)
                wav.writeframes(audio)

            yield f.name

            # Cleanup
            Path(f.name).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_read_from_wav_file(self, test_wav_file):
        """Test reading from WAV file."""
        transport = FileAudioTransport(
            input_file=test_wav_file,
            real_time=False,
        )

        await transport.start()

        frames = []
        async for frame in transport.read_frames():
            frames.append(frame)

        await transport.stop()

        assert len(frames) > 0
        assert all(isinstance(f, AudioFrame) for f in frames)

    @pytest.mark.asyncio
    async def test_get_input_duration(self, test_wav_file):
        """Test getting input duration."""
        transport = FileAudioTransport(
            input_file=test_wav_file,
            real_time=False,
        )

        await transport.start()
        duration = transport.get_input_duration()
        await transport.stop()

        # Should be approximately 0.5 seconds
        assert 0.4 <= duration <= 0.6


# ==================== Test Output ====================


class TestFileAudioTransportOutput:
    """Tests for output writing."""

    @pytest.mark.asyncio
    async def test_write_bytes(self):
        """Test writing bytes."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            transport = FileAudioTransport(output_file=f.name)

            await transport.start()

            audio = create_test_audio(duration_seconds=0.1)
            await transport.write_bytes(audio)

            await transport.stop()

            # Verify output file
            with wave.open(f.name, "rb") as wav:
                data = wav.readframes(wav.getnframes())
                assert len(data) == len(audio)

            Path(f.name).unlink()

    @pytest.mark.asyncio
    async def test_write_frame(self):
        """Test writing frame."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            transport = FileAudioTransport(output_file=f.name)

            await transport.start()

            audio = create_test_audio(duration_seconds=0.1)
            frame = AudioFrame(
                data=audio,
                sample_rate=16000,
                channels=1,
                sample_width=2,
            )
            await transport.write_frame(frame)

            await transport.stop()

            # Verify output file
            with wave.open(f.name, "rb") as wav:
                data = wav.readframes(wav.getnframes())
                assert len(data) == len(audio)

            Path(f.name).unlink()

    @pytest.mark.asyncio
    async def test_write_without_start_raises(self):
        """Test that writing without start raises error."""
        transport = FileAudioTransport()

        with pytest.raises(RuntimeError, match="not running"):
            await transport.write_bytes(b"test")

    @pytest.mark.asyncio
    async def test_get_output_data(self):
        """Test getting output data buffer."""
        transport = FileAudioTransport()
        await transport.start()

        audio1 = create_test_audio(duration_seconds=0.05)
        audio2 = create_test_audio(duration_seconds=0.05)

        await transport.write_bytes(audio1)
        await transport.write_bytes(audio2)

        # Get buffered data (when no file is specified)
        output = transport.get_output_data()
        assert output == audio1 + audio2

        await transport.stop()


# ==================== Test Frame Properties ====================


class TestFileAudioTransportFrameProperties:
    """Tests for frame properties."""

    @pytest.mark.asyncio
    async def test_frame_has_timestamp(self):
        """Test that frames have timestamps."""
        transport = FileAudioTransport(real_time=False)
        transport.set_input_data(create_test_audio(duration_seconds=0.1))

        await transport.start()

        async for frame in transport.read_frames():
            assert frame.timestamp is not None
            assert frame.timestamp >= 0
            break

        await transport.stop()

    @pytest.mark.asyncio
    async def test_frame_has_sequence_number(self):
        """Test that frames have sequence numbers."""
        transport = FileAudioTransport(real_time=False)
        transport.set_input_data(create_test_audio(duration_seconds=0.1))

        await transport.start()

        sequence_numbers = []
        async for frame in transport.read_frames():
            sequence_numbers.append(frame.sequence_number)
            if len(sequence_numbers) >= 3:
                break

        await transport.stop()

        # Should be sequential
        assert sequence_numbers == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_frame_duration_calculation(self):
        """Test frame duration calculation."""
        transport = FileAudioTransport(
            real_time=False,
            chunk_duration_ms=20,
        )
        transport.set_input_data(create_test_audio(duration_seconds=0.1))

        await transport.start()

        async for frame in transport.read_frames():
            # Duration should be approximately 20ms
            duration = frame.duration_ms
            assert 15 <= duration <= 25
            break

        await transport.stop()


# ==================== Test Pause/Resume ====================


class TestFileAudioTransportPauseResume:
    """Tests for pause/resume functionality."""

    @pytest.mark.asyncio
    async def test_pause_changes_state(self):
        """Test that pause changes state."""
        transport = FileAudioTransport()
        await transport.start()

        await transport.pause()
        assert transport.state == TransportState.PAUSED

        await transport.stop()

    @pytest.mark.asyncio
    async def test_resume_changes_state(self):
        """Test that resume changes state."""
        transport = FileAudioTransport()
        await transport.start()

        await transport.pause()
        await transport.resume()
        assert transport.state == TransportState.RUNNING

        await transport.stop()


# ==================== Test Level Monitoring ====================


class TestFileAudioTransportLevels:
    """Tests for level monitoring."""

    @pytest.mark.asyncio
    async def test_input_level_updates(self):
        """Test that input level is updated."""
        transport = FileAudioTransport(real_time=False)
        transport.set_input_data(create_test_audio(duration_seconds=0.1, amplitude=0.8))

        await transport.start()

        # Read a frame to update level
        async for frame in transport.read_frames():
            break

        level = await transport.get_input_level()
        assert level > 0

        await transport.stop()

    @pytest.mark.asyncio
    async def test_output_level_updates(self):
        """Test that output level is updated."""
        transport = FileAudioTransport()
        await transport.start()

        await transport.write_bytes(create_test_audio(duration_seconds=0.1, amplitude=0.8))

        level = await transport.get_output_level()
        assert level > 0

        await transport.stop()


# ==================== Test Health Check ====================


class TestFileAudioTransportHealthCheck:
    """Tests for health check."""

    @pytest.mark.asyncio
    async def test_health_check_idle(self):
        """Test health check when idle."""
        transport = FileAudioTransport()
        health = await transport._do_health_check()

        assert isinstance(health, HealthCheckResult)
        assert health.status == ProviderHealth.HEALTHY
        assert health.details["state"] == "idle"
        assert health.details["is_running"] is False
        assert health.details["has_input"] is False
        assert health.details["has_output"] is False

    @pytest.mark.asyncio
    async def test_health_check_running(self):
        """Test health check when running."""
        transport = FileAudioTransport()
        transport.set_input_data(create_test_audio())

        await transport.start()
        health = await transport._do_health_check()

        assert isinstance(health, HealthCheckResult)
        assert health.status == ProviderHealth.HEALTHY
        assert health.details["state"] == "running"
        assert health.details["is_running"] is True
        assert health.details["has_input"] is True

        await transport.stop()


# ==================== Test Callbacks ====================


class TestFileAudioTransportCallbacks:
    """Tests for callback registration."""

    @pytest.mark.asyncio
    async def test_input_callback_is_called(self):
        """Test that input callback is called."""
        transport = FileAudioTransport(real_time=False)
        transport.set_input_data(create_test_audio(duration_seconds=0.1))

        received_frames = []
        transport.on_input_frame(lambda f: received_frames.append(f))

        await transport.start()

        async for frame in transport.read_frames():
            if len(received_frames) >= 2:
                break

        await transport.stop()

        assert len(received_frames) >= 2

    @pytest.mark.asyncio
    async def test_state_callback_is_called(self):
        """Test that state callback is called."""
        transport = FileAudioTransport()

        states = []
        transport.on_state_change(lambda s: states.append(s))

        await transport.start()
        await transport.stop()

        assert TransportState.STARTING in states
        assert TransportState.RUNNING in states
        assert TransportState.STOPPING in states
        assert TransportState.STOPPED in states

    @pytest.mark.asyncio
    async def test_error_callback_is_called(self):
        """Test that error callback is called on error."""
        transport = FileAudioTransport(input_file="nonexistent.wav")

        errors = []
        transport.on_error(lambda e: errors.append(e))

        with pytest.raises(FileNotFoundError):
            await transport.start()

        assert len(errors) == 1
        assert isinstance(errors[0], FileNotFoundError)


# ==================== Test VoiceRunnable Implementation ====================


class TestFileAudioTransportVoiceRunnable:
    """Tests for VoiceRunnable implementation."""

    @pytest.mark.asyncio
    async def test_ainvoke(self):
        """Test ainvoke writes input and returns frame."""
        transport = FileAudioTransport(real_time=False)
        transport.set_input_data(create_test_audio(duration_seconds=0.1))

        await transport.start()

        input_audio = create_test_audio(duration_seconds=0.05)
        result = await transport.ainvoke(input_audio)

        assert isinstance(result, AudioFrame)
        assert len(result.data) > 0

        await transport.stop()

    @pytest.mark.asyncio
    async def test_astream(self):
        """Test astream writes input and yields frames."""
        transport = FileAudioTransport(real_time=False)
        transport.set_input_data(create_test_audio(duration_seconds=0.1))

        await transport.start()

        input_audio = create_test_audio(duration_seconds=0.05)
        frames = []

        async for frame in transport.astream(input_audio):
            frames.append(frame)
            if len(frames) >= 2:
                break

        await transport.stop()

        assert len(frames) >= 2
        assert all(isinstance(f, AudioFrame) for f in frames)
