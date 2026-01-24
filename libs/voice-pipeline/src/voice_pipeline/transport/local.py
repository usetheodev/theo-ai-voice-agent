"""Local audio transport using sounddevice.

Provides microphone input and speaker output for local audio processing.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

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
from voice_pipeline.utils.audio import calculate_rms

logger = logging.getLogger(__name__)


# Lazy import for sounddevice
_sounddevice = None


def _get_sounddevice():
    """Lazy import sounddevice to avoid import errors."""
    global _sounddevice
    if _sounddevice is None:
        try:
            import sounddevice as sd
            _sounddevice = sd
        except ImportError as e:
            raise ImportError(
                "sounddevice is required for LocalAudioTransport. "
                "Install it with: pip install sounddevice"
            ) from e
    return _sounddevice


@dataclass
class LocalAudioConfig(ProviderConfig):
    """Configuration for local audio transport."""

    # Input configuration
    input_device: Optional[int] = None
    """Input device index (None = default device)."""

    input_sample_rate: int = 16000
    """Input sample rate in Hz."""

    input_channels: int = 1
    """Number of input channels."""

    # Output configuration
    output_device: Optional[int] = None
    """Output device index (None = default device)."""

    output_sample_rate: int = 24000
    """Output sample rate in Hz."""

    output_channels: int = 1
    """Number of output channels."""

    # Buffer settings
    buffer_size_ms: int = 20
    """Buffer size in milliseconds."""

    latency: str = "low"
    """Latency mode: 'low', 'high', or float seconds."""

    # Audio processing
    enable_echo_cancellation: bool = False
    """Enable acoustic echo cancellation (requires additional library)."""

    enable_noise_suppression: bool = False
    """Enable noise suppression (requires additional library)."""

    enable_auto_gain_control: bool = False
    """Enable automatic gain control."""

    # Level monitoring
    monitor_levels: bool = True
    """Enable input/output level monitoring."""


class LocalAudioTransport(AudioTransportInterface, BaseProvider):
    """Local audio transport using sounddevice.

    Provides microphone input capture and speaker output playback
    for local voice applications.

    Example:
        >>> transport = LocalAudioTransport(
        ...     input_sample_rate=16000,
        ...     output_sample_rate=24000,
        ... )
        >>> await transport.start()
        >>> async for frame in transport.read_frames():
        ...     # Process audio frame
        ...     await process(frame)
        >>> await transport.stop()

    Note:
        Requires sounddevice library: pip install sounddevice
    """

    name = "LocalAudioTransport"

    def __init__(
        self,
        input_device: Optional[int] = None,
        output_device: Optional[int] = None,
        input_sample_rate: int = 16000,
        output_sample_rate: int = 24000,
        input_channels: int = 1,
        output_channels: int = 1,
        buffer_size_ms: int = 20,
        latency: str = "low",
        enable_echo_cancellation: bool = False,
        enable_noise_suppression: bool = False,
        enable_auto_gain_control: bool = False,
        monitor_levels: bool = True,
        **kwargs: Any,
    ):
        """Initialize local audio transport.

        Args:
            input_device: Input device index (None = default).
            output_device: Output device index (None = default).
            input_sample_rate: Input sample rate in Hz.
            output_sample_rate: Output sample rate in Hz.
            input_channels: Number of input channels.
            output_channels: Number of output channels.
            buffer_size_ms: Buffer size in milliseconds.
            latency: Latency mode ('low', 'high', or float).
            enable_echo_cancellation: Enable AEC.
            enable_noise_suppression: Enable noise suppression.
            enable_auto_gain_control: Enable AGC.
            monitor_levels: Enable level monitoring.
            **kwargs: Additional configuration.
        """
        self._config_obj = LocalAudioConfig(
            input_device=input_device,
            output_device=output_device,
            input_sample_rate=input_sample_rate,
            output_sample_rate=output_sample_rate,
            input_channels=input_channels,
            output_channels=output_channels,
            buffer_size_ms=buffer_size_ms,
            latency=latency,
            enable_echo_cancellation=enable_echo_cancellation,
            enable_noise_suppression=enable_noise_suppression,
            enable_auto_gain_control=enable_auto_gain_control,
            monitor_levels=monitor_levels,
        )

        self._transport_config = TransportConfig(
            input_config=AudioConfig(
                sample_rate=input_sample_rate,
                channels=input_channels,
                sample_width=2,  # PCM16
                format="pcm16",
            ),
            output_config=AudioConfig(
                sample_rate=output_sample_rate,
                channels=output_channels,
                sample_width=2,  # PCM16
                format="pcm16",
            ),
            buffer_size_ms=buffer_size_ms,
            enable_echo_cancellation=enable_echo_cancellation,
            enable_noise_suppression=enable_noise_suppression,
            enable_auto_gain_control=enable_auto_gain_control,
        )

        # State management
        self._state = TransportState.IDLE
        self._running = False
        self._paused = False
        self._input_muted = False
        self._output_muted = False

        # Streams
        self._input_stream: Optional[Any] = None
        self._output_stream: Optional[Any] = None

        # Buffers and queues
        self._input_queue: asyncio.Queue[AudioFrame] = asyncio.Queue(maxsize=100)
        self._output_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)

        # Level monitoring
        self._input_level: float = 0.0
        self._output_level: float = 0.0

        # Sequence numbering
        self._sequence_number: int = 0
        self._start_time: Optional[float] = None

        # Callbacks
        self._input_callback: Optional[Any] = None
        self._state_callback: Optional[Any] = None
        self._error_callback: Optional[Any] = None

        # Output task
        self._output_task: Optional[asyncio.Task] = None

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

    def _input_callback_fn(
        self, indata: "numpy.ndarray", frames: int, time_info: dict, status: int
    ) -> None:
        """Callback for input stream (called from audio thread)."""
        if status:
            logger.warning(f"Input status: {status}")

        if self._input_muted or self._paused:
            return

        try:
            # Convert to bytes (int16)
            import numpy as np
            audio_data = (indata * 32767).astype(np.int16).tobytes()

            # Calculate level if monitoring
            if self._config_obj.monitor_levels:
                self._input_level = calculate_rms(audio_data)

            # Create frame
            timestamp = None
            if self._start_time:
                timestamp = time.time() - self._start_time

            frame = AudioFrame(
                data=audio_data,
                sample_rate=self._config_obj.input_sample_rate,
                channels=self._config_obj.input_channels,
                sample_width=2,
                timestamp=timestamp,
                sequence_number=self._sequence_number,
            )
            self._sequence_number += 1

            # Put in queue (non-blocking)
            try:
                self._input_queue.put_nowait(frame)
            except asyncio.QueueFull:
                logger.warning("Input queue full, dropping frame")

            # Call input callback if registered
            if self._input_callback:
                try:
                    self._input_callback(frame)
                except Exception as e:
                    logger.warning(f"Input callback error: {e}")

        except Exception as e:
            logger.error(f"Input callback error: {e}")

    def _output_callback_fn(
        self, outdata: "numpy.ndarray", frames: int, time_info: dict, status: int
    ) -> None:
        """Callback for output stream (called from audio thread)."""
        if status:
            logger.warning(f"Output status: {status}")

        import numpy as np

        if self._output_muted or self._paused:
            outdata[:] = 0
            return

        try:
            # Get data from queue (non-blocking)
            data = self._output_queue.get_nowait()

            # Convert to float
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32767

            # Ensure correct shape
            if len(samples) >= frames:
                samples = samples[:frames]
            else:
                # Pad with zeros if not enough data
                samples = np.pad(samples, (0, frames - len(samples)))

            outdata[:, 0] = samples

            # Calculate level if monitoring
            if self._config_obj.monitor_levels:
                self._output_level = calculate_rms(data)

        except asyncio.QueueEmpty:
            # No data available, output silence
            outdata[:] = 0
        except Exception as e:
            logger.error(f"Output callback error: {e}")
            outdata[:] = 0

    async def start(self) -> None:
        """Start the audio transport."""
        if self._running:
            logger.warning("Transport already running")
            return

        self._set_state(TransportState.STARTING)

        try:
            sd = _get_sounddevice()

            # Calculate buffer size in samples
            input_buffer_samples = int(
                self._config_obj.input_sample_rate * self._config_obj.buffer_size_ms / 1000
            )
            output_buffer_samples = int(
                self._config_obj.output_sample_rate * self._config_obj.buffer_size_ms / 1000
            )

            # Open input stream
            self._input_stream = sd.InputStream(
                device=self._config_obj.input_device,
                samplerate=self._config_obj.input_sample_rate,
                channels=self._config_obj.input_channels,
                dtype="float32",
                blocksize=input_buffer_samples,
                latency=self._config_obj.latency,
                callback=self._input_callback_fn,
            )

            # Open output stream
            self._output_stream = sd.OutputStream(
                device=self._config_obj.output_device,
                samplerate=self._config_obj.output_sample_rate,
                channels=self._config_obj.output_channels,
                dtype="float32",
                blocksize=output_buffer_samples,
                latency=self._config_obj.latency,
                callback=self._output_callback_fn,
            )

            # Start streams
            self._input_stream.start()
            self._output_stream.start()

            self._running = True
            self._start_time = time.time()
            self._sequence_number = 0
            self._set_state(TransportState.RUNNING)

            logger.info(
                f"Local audio transport started (input: {self._config_obj.input_sample_rate}Hz, "
                f"output: {self._config_obj.output_sample_rate}Hz)"
            )

        except Exception as e:
            self._handle_error(e)
            raise

    async def stop(self) -> None:
        """Stop the audio transport."""
        if not self._running:
            return

        self._set_state(TransportState.STOPPING)
        self._running = False

        try:
            # Stop streams
            if self._input_stream:
                self._input_stream.stop()
                self._input_stream.close()
                self._input_stream = None

            if self._output_stream:
                self._output_stream.stop()
                self._output_stream.close()
                self._output_stream = None

            # Clear queues
            while not self._input_queue.empty():
                try:
                    self._input_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            while not self._output_queue.empty():
                try:
                    self._output_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            self._set_state(TransportState.STOPPED)
            logger.info("Local audio transport stopped")

        except Exception as e:
            self._handle_error(e)
            raise

    async def read_frames(self) -> AsyncIterator[AudioFrame]:
        """Read audio frames from microphone.

        Yields:
            AudioFrame objects as they are captured.
        """
        while self._running or not self._input_queue.empty():
            try:
                frame = await asyncio.wait_for(
                    self._input_queue.get(),
                    timeout=0.1,
                )
                yield frame
            except asyncio.TimeoutError:
                # Continue if still running
                if not self._running:
                    break

    async def write_frame(self, frame: AudioFrame) -> None:
        """Write an audio frame to speaker.

        Args:
            frame: Audio frame to play.
        """
        if not self._running:
            raise RuntimeError("Transport not running")

        await self._output_queue.put(frame.data)

    async def write_bytes(self, data: bytes) -> None:
        """Write raw audio bytes to speaker.

        Args:
            data: Raw audio bytes (PCM16).
        """
        if not self._running:
            raise RuntimeError("Transport not running")

        await self._output_queue.put(data)

    async def pause(self) -> None:
        """Pause audio capture and playback."""
        if not self._running:
            raise RuntimeError("Transport not running")

        self._paused = True
        self._set_state(TransportState.PAUSED)
        logger.debug("Transport paused")

    async def resume(self) -> None:
        """Resume audio capture and playback."""
        if not self._running:
            raise RuntimeError("Transport not running")

        self._paused = False
        self._set_state(TransportState.RUNNING)
        logger.debug("Transport resumed")

    async def set_input_muted(self, muted: bool) -> None:
        """Mute/unmute microphone input.

        Args:
            muted: Whether to mute input.
        """
        self._input_muted = muted
        logger.debug(f"Input muted: {muted}")

    async def set_output_muted(self, muted: bool) -> None:
        """Mute/unmute speaker output.

        Args:
            muted: Whether to mute output.
        """
        self._output_muted = muted
        logger.debug(f"Output muted: {muted}")

    async def get_input_level(self) -> float:
        """Get current microphone input level.

        Returns:
            Audio level from 0.0 to 1.0.
        """
        return self._input_level

    async def get_output_level(self) -> float:
        """Get current speaker output level.

        Returns:
            Audio level from 0.0 to 1.0.
        """
        return self._output_level

    # ==================== Device Management ====================

    @staticmethod
    def list_devices() -> list[dict]:
        """List available audio devices.

        Returns:
            List of device info dictionaries.
        """
        sd = _get_sounddevice()
        devices = sd.query_devices()

        result = []
        for i, device in enumerate(devices):
            result.append({
                "index": i,
                "name": device["name"],
                "max_input_channels": device["max_input_channels"],
                "max_output_channels": device["max_output_channels"],
                "default_samplerate": device["default_samplerate"],
                "is_input": device["max_input_channels"] > 0,
                "is_output": device["max_output_channels"] > 0,
            })
        return result

    @staticmethod
    def get_default_input_device() -> Optional[int]:
        """Get default input device index.

        Returns:
            Device index or None if no input device.
        """
        sd = _get_sounddevice()
        try:
            return sd.default.device[0]
        except Exception:
            return None

    @staticmethod
    def get_default_output_device() -> Optional[int]:
        """Get default output device index.

        Returns:
            Device index or None if no output device.
        """
        sd = _get_sounddevice()
        try:
            return sd.default.device[1]
        except Exception:
            return None

    # ==================== BaseProvider Implementation ====================

    async def _do_health_check(self) -> HealthCheckResult:
        """Perform health check.

        Returns:
            Health check results.
        """
        try:
            sd = _get_sounddevice()

            # Check for available devices
            devices = sd.query_devices()
            has_input = any(d["max_input_channels"] > 0 for d in devices)
            has_output = any(d["max_output_channels"] > 0 for d in devices)

            if has_input and has_output:
                return HealthCheckResult(
                    status=ProviderHealth.HEALTHY,
                    message="Audio devices available",
                    details={
                        "sounddevice_available": True,
                        "input_device_available": has_input,
                        "output_device_available": has_output,
                        "state": self._state.value,
                        "is_running": self._running,
                    },
                )
            else:
                return HealthCheckResult(
                    status=ProviderHealth.DEGRADED,
                    message="Some audio devices missing",
                    details={
                        "sounddevice_available": True,
                        "input_device_available": has_input,
                        "output_device_available": has_output,
                    },
                )
        except ImportError:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="sounddevice not installed",
                details={"sounddevice_available": False},
            )
        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=str(e),
                details={"sounddevice_available": True, "error": str(e)},
            )

    # ==================== Context Manager ====================

    async def __aenter__(self) -> "LocalAudioTransport":
        """Enter async context."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context."""
        await self.stop()
