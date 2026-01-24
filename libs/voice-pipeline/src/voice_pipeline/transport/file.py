"""File-based audio transport.

Provides audio I/O from/to files for testing and batch processing.
"""

import asyncio
import logging
import struct
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, BinaryIO, Optional, Union

from voice_pipeline.interfaces.transport import (
    AudioConfig,
    AudioFrame,
    AudioTransportInterface,
    TransportConfig,
    TransportState,
)
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
)
from voice_pipeline.utils.audio import calculate_rms, resample_audio

logger = logging.getLogger(__name__)


@dataclass
class FileAudioConfig(ProviderConfig):
    """Configuration for file audio transport."""

    input_file: Optional[str] = None
    """Path to input audio file (WAV format)."""

    output_file: Optional[str] = None
    """Path to output audio file (WAV format)."""

    sample_rate: int = 16000
    """Sample rate for processing."""

    channels: int = 1
    """Number of channels."""

    chunk_duration_ms: int = 20
    """Chunk duration in milliseconds for streaming."""

    loop_input: bool = False
    """Whether to loop input file."""

    real_time: bool = True
    """Simulate real-time streaming (add delays)."""


class FileAudioTransport(AudioTransportInterface, BaseProvider):
    """File-based audio transport.

    Reads audio from input file and writes to output file.
    Useful for testing and batch processing.

    Example:
        >>> transport = FileAudioTransport(
        ...     input_file="input.wav",
        ...     output_file="output.wav",
        ... )
        >>> await transport.start()
        >>> async for frame in transport.read_frames():
        ...     # Process and write back
        ...     await transport.write_frame(frame)
        >>> await transport.stop()
    """

    name = "FileAudioTransport"

    def __init__(
        self,
        input_file: Optional[Union[str, Path]] = None,
        output_file: Optional[Union[str, Path]] = None,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_duration_ms: int = 20,
        loop_input: bool = False,
        real_time: bool = True,
        **kwargs: Any,
    ):
        """Initialize file audio transport.

        Args:
            input_file: Path to input WAV file.
            output_file: Path to output WAV file.
            sample_rate: Sample rate for processing.
            channels: Number of channels.
            chunk_duration_ms: Chunk duration for streaming.
            loop_input: Whether to loop input file.
            real_time: Simulate real-time streaming.
            **kwargs: Additional configuration.
        """
        self._config_obj = FileAudioConfig(
            input_file=str(input_file) if input_file else None,
            output_file=str(output_file) if output_file else None,
            sample_rate=sample_rate,
            channels=channels,
            chunk_duration_ms=chunk_duration_ms,
            loop_input=loop_input,
            real_time=real_time,
        )

        self._transport_config = TransportConfig(
            input_config=AudioConfig(
                sample_rate=sample_rate,
                channels=channels,
                sample_width=2,
                format="pcm16",
            ),
            output_config=AudioConfig(
                sample_rate=sample_rate,
                channels=channels,
                sample_width=2,
                format="pcm16",
            ),
            buffer_size_ms=chunk_duration_ms,
        )

        # State management
        self._state = TransportState.IDLE
        self._running = False
        self._paused = False

        # File handles
        self._input_wav: Optional[wave.Wave_read] = None
        self._output_wav: Optional[wave.Wave_write] = None
        self._output_buffer: list[bytes] = []

        # Streaming state
        self._sequence_number: int = 0
        self._start_time: Optional[float] = None

        # Input data (for memory-based input)
        self._input_data: Optional[bytes] = None
        self._input_position: int = 0

        # Level monitoring
        self._input_level: float = 0.0
        self._output_level: float = 0.0

        # Callbacks
        self._input_callback: Optional[Any] = None
        self._state_callback: Optional[Any] = None
        self._error_callback: Optional[Any] = None

    @property
    def state(self) -> TransportState:
        """Current transport state."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Whether the transport is running."""
        return self._running and self._state == TransportState.RUNNING

    @property
    def config(self) -> TransportConfig:
        """Get transport configuration."""
        return self._transport_config

    def _set_state(self, state: TransportState) -> None:
        """Update state and notify callback."""
        self._state = state
        if self._state_callback:
            try:
                self._state_callback(state)
            except Exception as e:
                logger.warning(f"State callback error: {e}")

    def _handle_error(self, error: Exception) -> None:
        """Handle error and notify callback."""
        logger.error(f"Transport error: {error}")
        self._set_state(TransportState.ERROR)
        if self._error_callback:
            try:
                self._error_callback(error)
            except Exception as e:
                logger.warning(f"Error callback error: {e}")

    def set_input_data(self, data: bytes) -> None:
        """Set input data directly (for testing).

        Args:
            data: PCM16 audio bytes.
        """
        self._input_data = data
        self._input_position = 0

    async def start(self) -> None:
        """Start the file transport."""
        if self._running:
            logger.warning("Transport already running")
            return

        self._set_state(TransportState.STARTING)

        try:
            # Open input file if specified
            if self._config_obj.input_file:
                input_path = Path(self._config_obj.input_file)
                if not input_path.exists():
                    raise FileNotFoundError(f"Input file not found: {input_path}")

                self._input_wav = wave.open(str(input_path), "rb")

                # Check and log input file info
                logger.info(
                    f"Input file: {input_path.name} "
                    f"({self._input_wav.getnchannels()}ch, "
                    f"{self._input_wav.getframerate()}Hz, "
                    f"{self._input_wav.getsampwidth() * 8}bit)"
                )

            # Open output file if specified
            if self._config_obj.output_file:
                output_path = Path(self._config_obj.output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)

                self._output_wav = wave.open(str(output_path), "wb")
                self._output_wav.setnchannels(self._config_obj.channels)
                self._output_wav.setsampwidth(2)  # 16-bit
                self._output_wav.setframerate(self._config_obj.sample_rate)

            self._running = True
            self._start_time = time.time()
            self._sequence_number = 0
            self._input_position = 0
            self._set_state(TransportState.RUNNING)

            logger.info("File audio transport started")

        except Exception as e:
            self._handle_error(e)
            raise

    async def stop(self) -> None:
        """Stop the file transport."""
        if not self._running:
            return

        self._set_state(TransportState.STOPPING)
        self._running = False

        try:
            # Close input file
            if self._input_wav:
                self._input_wav.close()
                self._input_wav = None

            # Write buffered output and close
            if self._output_wav:
                for chunk in self._output_buffer:
                    self._output_wav.writeframes(chunk)
                self._output_wav.close()
                self._output_wav = None
                self._output_buffer.clear()

            self._set_state(TransportState.STOPPED)
            logger.info("File audio transport stopped")

        except Exception as e:
            self._handle_error(e)
            raise

    def _read_chunk_from_file(self) -> Optional[bytes]:
        """Read a chunk from input file.

        Returns:
            Audio bytes or None if EOF.
        """
        if not self._input_wav:
            return None

        # Calculate chunk size
        chunk_samples = int(
            self._input_wav.getframerate() * self._config_obj.chunk_duration_ms / 1000
        )
        chunk_bytes = chunk_samples * self._input_wav.getnchannels() * self._input_wav.getsampwidth()

        # Read data
        data = self._input_wav.readframes(chunk_samples)

        if not data:
            if self._config_obj.loop_input:
                # Rewind and read again
                self._input_wav.rewind()
                data = self._input_wav.readframes(chunk_samples)
            else:
                return None

        if not data:
            return None

        # Resample if needed
        file_rate = self._input_wav.getframerate()
        if file_rate != self._config_obj.sample_rate:
            data = resample_audio(data, file_rate, self._config_obj.sample_rate)

        return data

    def _read_chunk_from_data(self) -> Optional[bytes]:
        """Read a chunk from input data buffer.

        Returns:
            Audio bytes or None if EOF.
        """
        if not self._input_data:
            return None

        # Calculate chunk size
        chunk_samples = int(
            self._config_obj.sample_rate * self._config_obj.chunk_duration_ms / 1000
        )
        chunk_bytes = chunk_samples * self._config_obj.channels * 2  # 16-bit

        # Check if we have data
        if self._input_position >= len(self._input_data):
            if self._config_obj.loop_input:
                self._input_position = 0
            else:
                return None

        # Read chunk
        end_pos = min(self._input_position + chunk_bytes, len(self._input_data))
        data = self._input_data[self._input_position:end_pos]
        self._input_position = end_pos

        return data if data else None

    async def read_frames(self) -> AsyncIterator[AudioFrame]:
        """Read audio frames from input.

        Yields:
            AudioFrame objects from file or buffer.
        """
        while self._running:
            # Skip if paused
            if self._paused:
                await asyncio.sleep(0.01)
                continue

            # Read from file or buffer
            if self._input_data:
                data = self._read_chunk_from_data()
            else:
                data = self._read_chunk_from_file()

            if data is None:
                # End of input
                break

            # Calculate level
            self._input_level = calculate_rms(data)

            # Create frame
            timestamp = None
            if self._start_time:
                timestamp = time.time() - self._start_time

            frame = AudioFrame(
                data=data,
                sample_rate=self._config_obj.sample_rate,
                channels=self._config_obj.channels,
                sample_width=2,
                timestamp=timestamp,
                sequence_number=self._sequence_number,
            )
            self._sequence_number += 1

            # Call input callback if registered
            if self._input_callback:
                try:
                    self._input_callback(frame)
                except Exception as e:
                    logger.warning(f"Input callback error: {e}")

            yield frame

            # Simulate real-time delay
            if self._config_obj.real_time:
                await asyncio.sleep(self._config_obj.chunk_duration_ms / 1000)

    async def write_frame(self, frame: AudioFrame) -> None:
        """Write an audio frame to output.

        Args:
            frame: Audio frame to write.
        """
        await self.write_bytes(frame.data)

    async def write_bytes(self, data: bytes) -> None:
        """Write raw audio bytes to output.

        Args:
            data: Raw audio bytes.
        """
        if not self._running:
            raise RuntimeError("Transport not running")

        # Calculate level
        self._output_level = calculate_rms(data)

        # Buffer for writing
        self._output_buffer.append(data)

        # Write immediately if file is open
        if self._output_wav:
            self._output_wav.writeframes(data)
            self._output_buffer.pop()

    async def pause(self) -> None:
        """Pause the transport."""
        self._paused = True
        self._set_state(TransportState.PAUSED)

    async def resume(self) -> None:
        """Resume the transport."""
        self._paused = False
        self._set_state(TransportState.RUNNING)

    async def get_input_level(self) -> float:
        """Get current input level."""
        return self._input_level

    async def get_output_level(self) -> float:
        """Get current output level."""
        return self._output_level

    # ==================== File Utilities ====================

    def get_output_data(self) -> bytes:
        """Get all output data written so far.

        Returns:
            Combined audio bytes.
        """
        return b"".join(self._output_buffer)

    def get_input_duration(self) -> float:
        """Get input file/data duration in seconds.

        Returns:
            Duration in seconds.
        """
        if self._input_wav:
            frames = self._input_wav.getnframes()
            rate = self._input_wav.getframerate()
            return frames / rate
        elif self._input_data:
            samples = len(self._input_data) // (2 * self._config_obj.channels)
            return samples / self._config_obj.sample_rate
        return 0.0

    # ==================== BaseProvider Implementation ====================

    async def _do_health_check(self) -> HealthCheckResult:
        """Perform health check."""
        has_input = self._input_wav is not None or self._input_data is not None
        has_output = self._output_wav is not None

        return HealthCheckResult(
            status=ProviderHealth.HEALTHY,
            message="File transport ready",
            details={
                "state": self._state.value,
                "is_running": self._running,
                "has_input": has_input,
                "has_output": has_output,
                "input_file": self._config_obj.input_file,
                "output_file": self._config_obj.output_file,
            },
        )

    # ==================== Context Manager ====================

    async def __aenter__(self) -> "FileAudioTransport":
        """Enter async context."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context."""
        await self.stop()


# ==================== Utility Functions ====================


def create_test_audio(
    duration_seconds: float = 1.0,
    sample_rate: int = 16000,
    frequency: float = 440.0,
    amplitude: float = 0.5,
) -> bytes:
    """Create test audio (sine wave).

    Args:
        duration_seconds: Duration in seconds.
        sample_rate: Sample rate in Hz.
        frequency: Frequency in Hz.
        amplitude: Amplitude (0.0 to 1.0).

    Returns:
        PCM16 audio bytes.
    """
    import math

    samples = int(sample_rate * duration_seconds)
    data = bytearray()

    for i in range(samples):
        t = i / sample_rate
        value = amplitude * math.sin(2 * math.pi * frequency * t)
        # Convert to 16-bit signed integer
        sample = int(value * 32767)
        data.extend(struct.pack("<h", sample))

    return bytes(data)


def create_silence(
    duration_seconds: float = 1.0,
    sample_rate: int = 16000,
) -> bytes:
    """Create silence.

    Args:
        duration_seconds: Duration in seconds.
        sample_rate: Sample rate in Hz.

    Returns:
        PCM16 audio bytes (zeros).
    """
    samples = int(sample_rate * duration_seconds)
    return b"\x00\x00" * samples
