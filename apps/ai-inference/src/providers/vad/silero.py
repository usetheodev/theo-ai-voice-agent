"""Silero VAD Provider.

Silero VAD is lightweight (~1MB) and can run locally.
Also supports API-based usage for consistency.
"""

import logging
import struct
from typing import Optional

from ..base import VADProvider, VADResult
from ..exceptions import ProviderConnectionError

logger = logging.getLogger(__name__)


class SileroVAD(VADProvider):
    """Silero Voice Activity Detection provider.

    Can run locally (model is ~1MB) or via API.

    Usage:
        # Local mode (default)
        provider = SileroVAD()

        # API mode
        provider = SileroVAD(api_base="http://localhost:8000/vad")

        result = await provider.process(audio_chunk)
        if result.is_speech:
            print("Speech detected!")
    """

    def __init__(
        self,
        api_base: str = "",  # Empty = local mode
        threshold: float = 0.5,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 100,
        **kwargs,
    ):
        """Initialize Silero VAD provider.

        Args:
            api_base: API URL (empty for local mode).
            threshold: Speech detection threshold (0-1).
            min_speech_duration_ms: Minimum speech duration.
            min_silence_duration_ms: Minimum silence duration.
        """
        super().__init__(
            api_base=api_base,
            threshold=threshold,
            min_speech_duration_ms=min_speech_duration_ms,
            min_silence_duration_ms=min_silence_duration_ms,
            **kwargs,
        )

        self._model = None
        self._local_mode = not api_base

        # State for tracking speech
        self._speech_start: Optional[float] = None
        self._last_speech_time: float = 0.0
        self._sample_count: int = 0

    @property
    def name(self) -> str:
        return "silero"

    def _load_model(self):
        """Load Silero VAD model locally."""
        if self._model is not None:
            return

        try:
            import torch

            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                trust_repo=True,
            )

            self._model = model
            self._get_speech_timestamps = utils[0]

            logger.info("Loaded Silero VAD model locally")

        except ImportError:
            logger.warning(
                "torch not installed. Silero VAD requires: pip install torch"
            )
            raise ProviderConnectionError(
                "torch not installed for local Silero VAD",
                provider=self.name,
            )
        except Exception as e:
            logger.error(f"Failed to load Silero VAD: {e}")
            raise ProviderConnectionError(
                f"Failed to load model: {e}",
                provider=self.name,
            )

    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int = 16000,
    ) -> VADResult:
        """Process audio chunk and detect voice activity.

        Args:
            audio_chunk: Raw PCM16 audio bytes.
            sample_rate: Audio sample rate (16000 recommended).

        Returns:
            VAD result with speech detection.
        """
        if self._local_mode:
            return await self._process_local(audio_chunk, sample_rate)
        else:
            return await self._process_api(audio_chunk, sample_rate)

    async def _process_local(
        self,
        audio_chunk: bytes,
        sample_rate: int,
    ) -> VADResult:
        """Process audio locally with Silero model."""
        self._load_model()

        import torch

        # Convert bytes to float tensor
        # Audio is PCM16 (signed 16-bit little-endian)
        num_samples = len(audio_chunk) // 2
        samples = struct.unpack(f"<{num_samples}h", audio_chunk)

        # Normalize to [-1, 1]
        audio_tensor = torch.tensor(samples, dtype=torch.float32) / 32768.0

        # Resample if needed (Silero works best at 16000)
        if sample_rate != 16000:
            # Simple resampling - for production use torchaudio
            ratio = 16000 / sample_rate
            new_length = int(len(audio_tensor) * ratio)
            indices = torch.linspace(0, len(audio_tensor) - 1, new_length).long()
            audio_tensor = audio_tensor[indices]

        # Run VAD
        try:
            speech_prob = self._model(audio_tensor, 16000).item()
        except Exception as e:
            logger.warning(f"VAD inference error: {e}")
            speech_prob = 0.0

        is_speech = speech_prob >= self.threshold

        # Track timing
        chunk_duration = num_samples / sample_rate
        current_time = self._sample_count / sample_rate
        self._sample_count += num_samples

        if is_speech:
            if self._speech_start is None:
                self._speech_start = current_time
            self._last_speech_time = current_time
        else:
            # Check if silence duration exceeded
            if self._speech_start is not None:
                silence_duration = (current_time - self._last_speech_time) * 1000
                if silence_duration >= self.min_silence_duration_ms:
                    self._speech_start = None

        return VADResult(
            is_speech=is_speech,
            confidence=speech_prob,
            start_time=self._speech_start,
            end_time=current_time if is_speech else None,
        )

    async def _process_api(
        self,
        audio_chunk: bytes,
        sample_rate: int,
    ) -> VADResult:
        """Process audio via API."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.api_base}/process",
                    content=audio_chunk,
                    params={"sample_rate": sample_rate},
                    headers={"Content-Type": "audio/pcm"},
                )

                response.raise_for_status()
                data = response.json()

                return VADResult(
                    is_speech=data.get("is_speech", False),
                    confidence=data.get("confidence", 0.0),
                    start_time=data.get("start_time"),
                    end_time=data.get("end_time"),
                )

        except Exception as e:
            raise ProviderConnectionError(
                f"VAD API error: {e}",
                provider=self.name,
            )

    def reset(self) -> None:
        """Reset VAD state for new utterance."""
        self._speech_start = None
        self._last_speech_time = 0.0
        self._sample_count = 0

        # Reset model state if loaded
        if self._model is not None:
            try:
                self._model.reset_states()
            except Exception:
                pass
