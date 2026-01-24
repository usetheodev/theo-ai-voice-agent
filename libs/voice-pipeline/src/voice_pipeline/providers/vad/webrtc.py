"""WebRTC VAD provider.

WebRTC VAD is a lightweight, fast voice activity detection library
based on Google's WebRTC implementation.

Reference: https://github.com/wiseman/py-webrtcvad
"""

import time
from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np

from voice_pipeline.interfaces.vad import SpeechState, VADEvent, VADInterface
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
)
from voice_pipeline.providers.decorators import register_vad
from voice_pipeline.providers.types import VADCapabilities


# WebRTC VAD aggressiveness modes
WebRTCVADMode = Literal[0, 1, 2, 3]
# 0 = Least aggressive (allows more speech)
# 1 = Normal
# 2 = Aggressive
# 3 = Most aggressive (filters more non-speech)

# Supported sample rates
WebRTCSampleRate = Literal[8000, 16000, 32000, 48000]

# Supported frame durations in milliseconds
WebRTCFrameDuration = Literal[10, 20, 30]


@dataclass
class WebRTCVADConfig(ProviderConfig):
    """Configuration for WebRTC VAD provider.

    Attributes:
        mode: Aggressiveness mode (0-3). Higher = more aggressive filtering.
        frame_duration_ms: Frame duration in ms (10, 20, or 30).
        min_speech_frames: Minimum consecutive speech frames to trigger speech start.
        min_silence_frames: Minimum consecutive silence frames to trigger speech end.
        sample_rate: Expected sample rate (8000, 16000, 32000, or 48000 Hz).

    Example:
        >>> config = WebRTCVADConfig(
        ...     mode=2,
        ...     frame_duration_ms=30,
        ...     min_silence_frames=10,
        ... )
        >>> vad = WebRTCVADProvider(config=config)
    """

    mode: WebRTCVADMode = 2
    """Aggressiveness mode (0=least, 3=most aggressive)."""

    frame_duration_ms: WebRTCFrameDuration = 30
    """Frame duration in milliseconds (10, 20, or 30)."""

    min_speech_frames: int = 2
    """Minimum consecutive speech frames to trigger speech start."""

    min_silence_frames: int = 15
    """Minimum consecutive silence frames to trigger speech end."""

    sample_rate: WebRTCSampleRate = 16000
    """Expected sample rate in Hz (8000, 16000, 32000, or 48000)."""


@register_vad(
    name="webrtc",
    capabilities=VADCapabilities(
        frame_size_ms=30,
        sample_rates=[8000, 16000, 32000, 48000],
        confidence_scores=False,  # WebRTC VAD gives binary output only
        speech_timestamps=True,
    ),
    description="Lightweight WebRTC-based voice activity detection.",
    version="1.0.0",
    aliases=["webrtc-vad", "google-vad"],
    tags=["local", "lightweight", "cpu", "realtime"],
    default_config={
        "mode": 2,
        "frame_duration_ms": 30,
        "min_speech_frames": 2,
        "min_silence_frames": 15,
    },
)
class WebRTCVADProvider(BaseProvider, VADInterface):
    """WebRTC VAD provider for lightweight voice activity detection.

    Uses Google's WebRTC VAD algorithm via py-webrtcvad.
    Very fast (< 0.1ms) and requires no GPU.

    Features:
    - Binary speech detection (no probability output)
    - Configurable aggressiveness (0-3)
    - Multiple sample rate support
    - State tracking for speech segments

    Aggressiveness modes:
    - 0: Least aggressive, allows more audio through (good for noisy environments)
    - 1: Normal
    - 2: Aggressive (default, good balance)
    - 3: Most aggressive, filters out more non-speech

    Supported configurations:
    - Sample rates: 8000, 16000, 32000, 48000 Hz
    - Frame durations: 10, 20, 30 ms

    Example:
        >>> vad = WebRTCVADProvider(mode=2)
        >>> await vad.connect()
        >>>
        >>> # Process audio chunk
        >>> event = await vad.process(audio_chunk, sample_rate=16000)
        >>> print(f"Speech: {event.is_speech}")
        >>>
        >>> # Or use with pipeline
        >>> async for event in vad.process_stream(audio_stream):
        ...     if event.state == SpeechState.SPEECH:
        ...         print("User is speaking")

    Attributes:
        provider_name: "webrtc-vad"
        name: "WebRTCVAD" (for VoiceRunnable)
    """

    provider_name: str = "webrtc-vad"
    name: str = "WebRTCVAD"

    def __init__(
        self,
        config: Optional[WebRTCVADConfig] = None,
        mode: Optional[int] = None,
        frame_duration_ms: Optional[int] = None,
        min_speech_frames: Optional[int] = None,
        min_silence_frames: Optional[int] = None,
        sample_rate: Optional[int] = None,
        **kwargs,
    ):
        """Initialize WebRTC VAD provider.

        Args:
            config: Full configuration object.
            mode: Aggressiveness mode 0-3 (shortcut).
            frame_duration_ms: Frame duration in ms (shortcut).
            min_speech_frames: Minimum speech frames (shortcut).
            min_silence_frames: Minimum silence frames (shortcut).
            sample_rate: Expected sample rate (shortcut).
            **kwargs: Additional configuration options.
        """
        # Build config from parameters
        if config is None:
            config = WebRTCVADConfig()

        # Apply shortcuts
        if mode is not None:
            config.mode = mode
        if frame_duration_ms is not None:
            config.frame_duration_ms = frame_duration_ms
        if min_speech_frames is not None:
            config.min_speech_frames = min_speech_frames
        if min_silence_frames is not None:
            config.min_silence_frames = min_silence_frames
        if sample_rate is not None:
            config.sample_rate = sample_rate

        super().__init__(config=config, **kwargs)

        self._vad_config: WebRTCVADConfig = config
        self._vad = None

        # State tracking
        self._is_speaking = False
        self._speech_start_time: Optional[float] = None
        self._speech_frame_count = 0
        self._silence_frame_count = 0

    @property
    def frame_size_ms(self) -> int:
        """Preferred frame size in milliseconds."""
        return self._vad_config.frame_duration_ms

    def _calculate_frame_size(self, sample_rate: int) -> int:
        """Calculate frame size in samples for given sample rate.

        Args:
            sample_rate: Sample rate in Hz.

        Returns:
            Number of samples per frame.
        """
        return int(sample_rate * self._vad_config.frame_duration_ms / 1000)

    async def connect(self) -> None:
        """Initialize the WebRTC VAD."""
        await super().connect()

        try:
            import webrtcvad
        except ImportError:
            raise ImportError(
                "webrtcvad is required for WebRTC VAD. "
                "Install with: pip install webrtcvad"
            )

        # Create VAD instance
        self._vad = webrtcvad.Vad(self._vad_config.mode)

    async def disconnect(self) -> None:
        """Release VAD resources."""
        self._vad = None
        self.reset()
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if VAD is initialized and working."""
        if self._vad is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="VAD not initialized. Call connect() first.",
            )

        try:
            # Test with silence
            frame_size = self._calculate_frame_size(self._vad_config.sample_rate)
            test_audio = bytes(frame_size * 2)  # PCM16 = 2 bytes per sample
            self._vad.is_speech(test_audio, self._vad_config.sample_rate)

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"WebRTC VAD ready. Mode: {self._vad_config.mode}",
                details={
                    "mode": self._vad_config.mode,
                    "frame_duration_ms": self._vad_config.frame_duration_ms,
                },
            )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"VAD test failed: {e}",
            )

    def reset(self) -> None:
        """Reset VAD state."""
        self._is_speaking = False
        self._speech_start_time = None
        self._speech_frame_count = 0
        self._silence_frame_count = 0

    def set_mode(self, mode: int) -> None:
        """Update the aggressiveness mode.

        Args:
            mode: New mode (0-3).

        Raises:
            ValueError: If mode is not in valid range.
        """
        if mode not in (0, 1, 2, 3):
            raise ValueError("Mode must be 0, 1, 2, or 3")

        self._vad_config.mode = mode
        if self._vad is not None:
            self._vad.set_mode(mode)

    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int,
    ) -> VADEvent:
        """Process audio chunk for voice activity.

        Args:
            audio_chunk: Audio data (PCM16, mono).
            sample_rate: Sample rate in Hz (8000, 16000, 32000, or 48000).

        Returns:
            VADEvent with speech detection result.

        Raises:
            ValueError: If sample rate or frame size is not supported.
            RuntimeError: If VAD is not initialized.
        """
        if self._vad is None:
            raise RuntimeError("VAD not initialized. Call connect() first.")

        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError(
                f"Unsupported sample rate: {sample_rate}. "
                "WebRTC VAD supports 8000, 16000, 32000, or 48000 Hz."
            )

        # Validate frame size
        expected_frame_size = self._calculate_frame_size(sample_rate)
        actual_samples = len(audio_chunk) // 2  # PCM16 = 2 bytes per sample

        if actual_samples != expected_frame_size:
            raise ValueError(
                f"Invalid frame size: expected {expected_frame_size} samples "
                f"({self._vad_config.frame_duration_ms}ms at {sample_rate}Hz), "
                f"got {actual_samples} samples."
            )

        # Process with WebRTC VAD
        start_time = time.perf_counter()
        is_speech_frame = self._vad.is_speech(audio_chunk, sample_rate)
        inference_time_ms = (time.perf_counter() - start_time) * 1000

        # Record metrics
        self._metrics.record_success(inference_time_ms)

        # Track speech/silence transitions
        current_time = time.time()

        if is_speech_frame:
            self._speech_frame_count += 1
            self._silence_frame_count = 0

            if not self._is_speaking:
                # Check if we've had enough consecutive speech frames
                if self._speech_frame_count >= self._vad_config.min_speech_frames:
                    self._is_speaking = True
                    self._speech_start_time = current_time
        else:
            self._silence_frame_count += 1
            self._speech_frame_count = 0

            if self._is_speaking:
                # Check if we've had enough consecutive silence frames
                if self._silence_frame_count >= self._vad_config.min_silence_frames:
                    speech_end_time = current_time
                    self._is_speaking = False

                    return VADEvent(
                        is_speech=False,
                        confidence=0.0,  # WebRTC gives binary output
                        state=SpeechState.SILENCE,
                        speech_start_ms=self._speech_start_time * 1000 if self._speech_start_time else None,
                        speech_end_ms=speech_end_time * 1000,
                    )

        # Determine state
        if self._is_speaking:
            state = SpeechState.SPEECH
            confidence = 1.0
        elif is_speech_frame:
            state = SpeechState.UNCERTAIN
            confidence = 0.5
        else:
            state = SpeechState.SILENCE
            confidence = 0.0

        return VADEvent(
            is_speech=self._is_speaking,
            confidence=confidence,
            state=state,
            speech_start_ms=self._speech_start_time * 1000 if self._speech_start_time else None,
            speech_end_ms=None,
        )

    def is_speech(self, audio_chunk: bytes, sample_rate: int) -> bool:
        """Get raw speech detection without state tracking.

        Synchronous method for simple speech checking.

        Args:
            audio_chunk: Audio data (PCM16, mono).
            sample_rate: Sample rate in Hz.

        Returns:
            True if speech detected in this frame.
        """
        if self._vad is None:
            raise RuntimeError("VAD not initialized. Call connect() first.")

        return self._vad.is_speech(audio_chunk, sample_rate)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"WebRTCVADProvider("
            f"mode={self._vad_config.mode}, "
            f"frame_duration_ms={self._vad_config.frame_duration_ms}, "
            f"connected={self._connected})"
        )
