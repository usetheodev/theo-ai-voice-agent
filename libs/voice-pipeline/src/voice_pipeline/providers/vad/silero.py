"""Silero VAD provider.

Silero VAD is a fast, accurate voice activity detection model.
It runs in < 1ms on CPU and is MIT licensed.

Reference: https://github.com/snakers4/silero-vad
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

from voice_pipeline.interfaces.vad import SpeechState, VADEvent, VADInterface
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
)


@dataclass
class SileroVADConfig(ProviderConfig):
    """Configuration for Silero VAD provider.

    Attributes:
        threshold: Speech probability threshold (0.0 to 1.0).
        min_speech_duration_ms: Minimum speech duration to trigger speech start.
        min_silence_duration_ms: Minimum silence duration to trigger speech end.
        speech_pad_ms: Padding to add around detected speech.
        model_path: Path to local model (uses torch.hub if None).

    Example:
        >>> config = SileroVADConfig(
        ...     threshold=0.5,
        ...     min_silence_duration_ms=500,
        ... )
        >>> vad = SileroVADProvider(config=config)
    """

    threshold: float = 0.5
    """Speech probability threshold (0.0 to 1.0)."""

    min_speech_duration_ms: float = 50.0
    """Minimum speech duration to trigger speech start (ms)."""

    min_silence_duration_ms: float = 500.0
    """Minimum silence duration to trigger speech end (ms)."""

    speech_pad_ms: float = 30.0
    """Padding to add around detected speech (ms)."""

    model_path: Optional[str] = None
    """Path to local model file. Uses torch.hub if None."""

    window_size_samples: int = 512
    """Number of samples per window (512 for 16kHz, 256 for 8kHz)."""


class SileroVADProvider(BaseProvider, VADInterface):
    """Silero VAD provider.

    Uses the Silero VAD model for voice activity detection.
    The model is fast (< 1ms on CPU) and accurate.

    Features:
    - Speech probability output (0.0 to 1.0)
    - Configurable thresholds
    - State tracking for speech start/end detection
    - Supports 8kHz and 16kHz sample rates

    Example:
        >>> vad = SileroVADProvider()
        >>> await vad.connect()
        >>>
        >>> # Process audio chunk
        >>> event = await vad.process(audio_chunk, sample_rate=16000)
        >>> print(f"Speech: {event.is_speech}, Confidence: {event.confidence}")
        >>>
        >>> # Or use with pipeline
        >>> async for event in vad.process_stream(audio_stream):
        ...     if event.state == SpeechState.SPEECH:
        ...         print("User is speaking")

    Attributes:
        provider_name: "silero-vad"
        name: "SileroVAD" (for VoiceRunnable)
    """

    provider_name: str = "silero-vad"
    name: str = "SileroVAD"

    def __init__(
        self,
        config: Optional[SileroVADConfig] = None,
        threshold: Optional[float] = None,
        min_silence_duration_ms: Optional[float] = None,
        **kwargs,
    ):
        """Initialize Silero VAD provider.

        Args:
            config: Full configuration object.
            threshold: Speech probability threshold (shortcut).
            min_silence_duration_ms: Minimum silence duration (shortcut).
            **kwargs: Additional configuration options.
        """
        # Build config from parameters
        if config is None:
            config = SileroVADConfig()

        # Apply shortcuts
        if threshold is not None:
            config.threshold = threshold
        if min_silence_duration_ms is not None:
            config.min_silence_duration_ms = min_silence_duration_ms

        super().__init__(config=config, **kwargs)

        self._vad_config: SileroVADConfig = config
        self._model = None
        self._model_utils = None

        # State tracking
        self._is_speaking = False
        self._speech_start_time: Optional[float] = None
        self._silence_start_time: Optional[float] = None
        self._current_speech_duration_ms: float = 0.0
        self._current_silence_duration_ms: float = 0.0

    @property
    def frame_size_ms(self) -> int:
        """Preferred frame size in milliseconds."""
        return 32  # 512 samples at 16kHz = 32ms

    async def connect(self) -> None:
        """Load the Silero VAD model.

        Note:
            Uses ``trust_repo=True`` when loading from torch.hub.
            This is required by Silero VAD but means the repository
            code is trusted. For security-sensitive deployments,
            consider using a local model via ``model_path``.
        """
        await super().connect()

        try:
            import torch
        except ImportError:
            raise ImportError(
                "torch is required for Silero VAD. "
                "Install with: pip install torch"
            )

        # Load model from torch.hub or local path
        if self._vad_config.model_path:
            self._model = torch.jit.load(self._vad_config.model_path)
        else:
            self._model, self._model_utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                onnx=False,
                trust_repo=True,
            )

        # Set model to eval mode
        self._model.eval()

    async def disconnect(self) -> None:
        """Unload the model."""
        self._model = None
        self._model_utils = None
        self.reset()
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if model is loaded and working."""
        if self._model is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Model not loaded. Call connect() first.",
            )

        try:
            import torch

            # Test with silence
            test_audio = torch.zeros(512)
            self._model(test_audio, 16000)

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message="Silero VAD model loaded and working.",
            )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"Model test failed: {e}",
            )

    def reset(self) -> None:
        """Reset VAD state."""
        self._is_speaking = False
        self._speech_start_time = None
        self._silence_start_time = None
        self._current_speech_duration_ms = 0.0
        self._current_silence_duration_ms = 0.0

        # Reset model state if available
        if self._model is not None:
            try:
                self._model.reset_states()
            except AttributeError:
                logger.debug("Model does not have reset_states method")

    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int,
    ) -> VADEvent:
        """Process audio chunk for voice activity.

        Args:
            audio_chunk: Audio data (PCM16, mono).
            sample_rate: Sample rate in Hz (8000 or 16000).

        Returns:
            VADEvent with speech detection result.

        Raises:
            ValueError: If sample rate is not supported.
            RuntimeError: If model is not loaded.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call connect() first.")

        if sample_rate not in (8000, 16000):
            raise ValueError(
                f"Unsupported sample rate: {sample_rate}. "
                "Silero VAD supports 8000 or 16000 Hz."
            )

        import torch

        # Convert bytes to numpy array (PCM16)
        audio_np = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32)

        # Normalize to [-1, 1]
        audio_np = audio_np / 32768.0

        # Convert to tensor
        audio_tensor = torch.from_numpy(audio_np)

        # Get speech probability
        start_time = time.perf_counter()
        with torch.no_grad():
            speech_prob = self._model(audio_tensor, sample_rate).item()
        inference_time_ms = (time.perf_counter() - start_time) * 1000

        # Record metrics
        self._metrics.record_success(inference_time_ms)

        # Calculate chunk duration
        chunk_duration_ms = len(audio_np) / sample_rate * 1000

        # Update state based on threshold
        is_speech = speech_prob >= self._vad_config.threshold
        current_time = time.time()

        # Track speech/silence transitions
        if is_speech:
            if not self._is_speaking:
                # Potential speech start
                if self._speech_start_time is None:
                    self._speech_start_time = current_time
                    self._current_speech_duration_ms = chunk_duration_ms
                else:
                    self._current_speech_duration_ms += chunk_duration_ms

                # Check if we've had enough speech to trigger
                if self._current_speech_duration_ms >= self._vad_config.min_speech_duration_ms:
                    self._is_speaking = True
                    self._silence_start_time = None
                    self._current_silence_duration_ms = 0.0
            else:
                # Continuing speech
                self._silence_start_time = None
                self._current_silence_duration_ms = 0.0
        else:
            if self._is_speaking:
                # Potential speech end
                if self._silence_start_time is None:
                    self._silence_start_time = current_time
                    self._current_silence_duration_ms = chunk_duration_ms
                else:
                    self._current_silence_duration_ms += chunk_duration_ms

                # Check if we've had enough silence to end speech
                if self._current_silence_duration_ms >= self._vad_config.min_silence_duration_ms:
                    self._is_speaking = False
                    self._speech_start_time = None
                    self._current_speech_duration_ms = 0.0
            else:
                # Continuing silence
                self._speech_start_time = None
                self._current_speech_duration_ms = 0.0

        # Determine state
        if self._is_speaking:
            state = SpeechState.SPEECH
        elif is_speech:
            state = SpeechState.UNCERTAIN
        else:
            state = SpeechState.SILENCE

        return VADEvent(
            is_speech=self._is_speaking,
            confidence=speech_prob,
            state=state,
            speech_start_ms=self._speech_start_time * 1000 if self._speech_start_time else None,
            speech_end_ms=self._silence_start_time * 1000 if self._silence_start_time and not self._is_speaking else None,
        )

    def get_speech_probability(self, audio_chunk: bytes, sample_rate: int) -> float:
        """Get raw speech probability without state tracking.

        Synchronous method for simple probability checking.

        Args:
            audio_chunk: Audio data (PCM16, mono).
            sample_rate: Sample rate in Hz.

        Returns:
            Speech probability (0.0 to 1.0).
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call connect() first.")

        import torch

        # Convert bytes to tensor
        audio_np = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32)
        audio_np = audio_np / 32768.0
        audio_tensor = torch.from_numpy(audio_np)

        with torch.no_grad():
            return self._model(audio_tensor, sample_rate).item()

    def set_threshold(self, threshold: float) -> None:
        """Update the speech probability threshold.

        Args:
            threshold: New threshold (0.0 to 1.0).
        """
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("Threshold must be between 0.0 and 1.0")
        self._vad_config.threshold = threshold

    def set_min_silence_duration(self, duration_ms: float) -> None:
        """Update the minimum silence duration.

        Args:
            duration_ms: New duration in milliseconds.
        """
        if duration_ms < 0:
            raise ValueError("Duration must be positive")
        self._vad_config.min_silence_duration_ms = duration_ms

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"SileroVADProvider("
            f"threshold={self._vad_config.threshold}, "
            f"min_silence_ms={self._vad_config.min_silence_duration_ms}, "
            f"connected={self._connected})"
        )
