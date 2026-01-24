"""Audio Transport interface.

Interface for audio I/O (microphone input, speaker output, WebRTC, etc.).
"""

from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Callable, Optional, Union

from voice_pipeline.runnable import RunnableConfig, VoiceRunnable


class TransportState(Enum):
    """State of the audio transport."""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class AudioConfig:
    """Configuration for audio format."""

    sample_rate: int = 16000
    """Sample rate in Hz."""

    channels: int = 1
    """Number of audio channels (1=mono, 2=stereo)."""

    sample_width: int = 2
    """Sample width in bytes (1=8-bit, 2=16-bit, 4=32-bit)."""

    format: str = "pcm16"
    """Audio format (pcm16, pcm32, float32)."""

    @property
    def bytes_per_second(self) -> int:
        """Calculate bytes per second."""
        return self.sample_rate * self.channels * self.sample_width

    @property
    def frame_size(self) -> int:
        """Calculate frame size in bytes for given duration."""
        return self.sample_width * self.channels


@dataclass
class TransportConfig:
    """Configuration for audio transport."""

    input_config: AudioConfig = field(default_factory=AudioConfig)
    """Configuration for input audio."""

    output_config: AudioConfig = field(default_factory=AudioConfig)
    """Configuration for output audio."""

    buffer_size_ms: int = 20
    """Buffer size in milliseconds."""

    enable_echo_cancellation: bool = False
    """Enable acoustic echo cancellation."""

    enable_noise_suppression: bool = False
    """Enable noise suppression."""

    enable_auto_gain_control: bool = False
    """Enable automatic gain control."""

    @property
    def input_buffer_size(self) -> int:
        """Calculate input buffer size in bytes."""
        samples = int(self.input_config.sample_rate * self.buffer_size_ms / 1000)
        return samples * self.input_config.frame_size

    @property
    def output_buffer_size(self) -> int:
        """Calculate output buffer size in bytes."""
        samples = int(self.output_config.sample_rate * self.buffer_size_ms / 1000)
        return samples * self.output_config.frame_size


@dataclass
class AudioFrame:
    """A frame of audio data."""

    data: bytes
    """Raw audio data."""

    sample_rate: int
    """Sample rate of the audio."""

    channels: int = 1
    """Number of channels."""

    sample_width: int = 2
    """Sample width in bytes."""

    timestamp: Optional[float] = None
    """Timestamp in seconds (optional)."""

    sequence_number: Optional[int] = None
    """Sequence number (optional, for ordering)."""

    @property
    def duration_ms(self) -> float:
        """Duration of the frame in milliseconds."""
        samples = len(self.data) // (self.channels * self.sample_width)
        return samples * 1000 / self.sample_rate


# Input type for transport: audio bytes or AudioFrame
TransportInput = Union[bytes, AudioFrame]


class AudioTransportInterface(VoiceRunnable[TransportInput, AudioFrame]):
    """Interface for Audio Transport.

    Implementations provide bidirectional audio I/O capabilities:
    - Capture audio from input devices (microphone)
    - Play audio to output devices (speaker)
    - Support for remote audio transport (WebRTC, WebSocket)

    Example implementation:
        class LocalAudioTransport(AudioTransportInterface):
            async def start(self):
                self.input_stream = self.audio.open(input=True, ...)
                self.output_stream = self.audio.open(output=True, ...)

            async def read_frames(self):
                while self.running:
                    data = self.input_stream.read(...)
                    yield AudioFrame(data=data, sample_rate=16000)

            async def write_frame(self, frame):
                self.output_stream.write(frame.data)
    """

    name: str = "AudioTransport"

    @abstractmethod
    async def start(self) -> None:
        """Start the audio transport.

        Opens audio streams and prepares for I/O.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the audio transport.

        Closes audio streams and releases resources.
        """
        pass

    @abstractmethod
    def read_frames(self) -> AsyncIterator[AudioFrame]:
        """Read audio frames from input.

        Yields:
            AudioFrame objects as they are captured.
        """
        pass

    @abstractmethod
    async def write_frame(self, frame: AudioFrame) -> None:
        """Write an audio frame to output.

        Args:
            frame: Audio frame to play/send.
        """
        pass

    @abstractmethod
    async def write_bytes(self, data: bytes) -> None:
        """Write raw audio bytes to output.

        Convenience method that creates an AudioFrame internally.

        Args:
            data: Raw audio bytes.
        """
        pass

    @property
    @abstractmethod
    def state(self) -> TransportState:
        """Current transport state."""
        pass

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the transport is running."""
        pass

    @property
    @abstractmethod
    def config(self) -> TransportConfig:
        """Get transport configuration."""
        pass

    # Optional methods for advanced features

    async def pause(self) -> None:
        """Pause the transport (optional).

        Implementations may not support pause.
        """
        raise NotImplementedError("Pause not supported by this transport")

    async def resume(self) -> None:
        """Resume the transport (optional).

        Implementations may not support resume.
        """
        raise NotImplementedError("Resume not supported by this transport")

    async def set_input_muted(self, muted: bool) -> None:
        """Mute/unmute input (optional).

        Args:
            muted: Whether to mute input.
        """
        raise NotImplementedError("Input mute not supported by this transport")

    async def set_output_muted(self, muted: bool) -> None:
        """Mute/unmute output (optional).

        Args:
            muted: Whether to mute output.
        """
        raise NotImplementedError("Output mute not supported by this transport")

    async def get_input_level(self) -> float:
        """Get current input audio level (optional).

        Returns:
            Audio level from 0.0 to 1.0.
        """
        raise NotImplementedError("Input level not supported by this transport")

    async def get_output_level(self) -> float:
        """Get current output audio level (optional).

        Returns:
            Audio level from 0.0 to 1.0.
        """
        raise NotImplementedError("Output level not supported by this transport")

    # Event handlers (optional, for convenience)
    def on_input_frame(self, callback: Callable[[AudioFrame], None]) -> None:
        """Register callback for input frames.

        Args:
            callback: Function to call with each input frame.
        """
        self._input_callback = callback

    def on_state_change(self, callback: Callable[[TransportState], None]) -> None:
        """Register callback for state changes.

        Args:
            callback: Function to call on state change.
        """
        self._state_callback = callback

    def on_error(self, callback: Callable[[Exception], None]) -> None:
        """Register callback for errors.

        Args:
            callback: Function to call on error.
        """
        self._error_callback = callback

    # ==================== VoiceRunnable Implementation ====================

    async def ainvoke(
        self,
        input: TransportInput,
        config: Optional[RunnableConfig] = None,
    ) -> AudioFrame:
        """Write input and return next captured frame.

        Args:
            input: Audio bytes or AudioFrame to play.
            config: Optional configuration.

        Returns:
            Next captured AudioFrame.
        """
        if isinstance(input, bytes):
            await self.write_bytes(input)
        else:
            await self.write_frame(input)

        # Return next captured frame
        async for frame in self.read_frames():
            return frame

        raise RuntimeError("No input frame available")

    async def astream(
        self,
        input: TransportInput,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[AudioFrame]:
        """Write input and stream captured frames.

        Args:
            input: Audio bytes or AudioFrame to play.
            config: Optional configuration.

        Yields:
            AudioFrame objects as they are captured.
        """
        if isinstance(input, bytes):
            await self.write_bytes(input)
        else:
            await self.write_frame(input)

        async for frame in self.read_frames():
            yield frame
