"""Filler sound injection for reducing perceived latency.

Fills the gap between end-of-turn detection and first TTS audio by
pre-synthesizing short filler sounds ("hmm", "um momento") and
injecting them immediately.

This reduces perceived latency by 200-800ms since the user hears
audio feedback within ~50ms of end-of-turn detection.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from voice_pipeline.interfaces import AudioChunk, TTSInterface

logger = logging.getLogger(__name__)

_DEFAULT_FILLERS = {
    "pt": ["hmm", "um momento"],
    "en": ["hmm", "one moment"],
}


@dataclass
class FillerConfig:
    """Configuration for filler sound injection.

    Attributes:
        enabled: Whether filler injection is active.
        language: Language for default filler texts.
        custom_fillers: Custom filler texts (overrides defaults).
        filler_voice: Voice to use for fillers (None = same as main TTS).
        max_filler_duration_ms: Maximum duration of a filler sound.
        fade_out_ms: Fade-out duration at the end of filler.
    """

    enabled: bool = True
    language: str = "en"
    custom_fillers: Optional[list[str]] = None
    filler_voice: Optional[str] = None
    max_filler_duration_ms: float = 800.0
    fade_out_ms: float = 50.0


class FillerInjector:
    """Pre-synthesizes and injects filler sounds before TTS response.

    Warmup pre-synthesizes all filler texts. During streaming, get_filler()
    returns the next filler in round-robin order.

    Example:
        >>> injector = FillerInjector(FillerConfig(language="pt"))
        >>> await injector.warmup(tts_provider)
        >>> if injector.is_ready:
        ...     filler = injector.get_filler()
        ...     if filler:
        ...         yield filler  # Play before main response
    """

    def __init__(self, config: FillerConfig | None = None):
        self._config = config or FillerConfig()
        self._fillers: list[AudioChunk] = []
        self._index: int = 0
        self._ready = False

    async def warmup(self, tts: TTSInterface) -> float:
        """Pre-synthesize filler sounds using the TTS provider.

        Args:
            tts: TTS provider to synthesize fillers.

        Returns:
            Time taken to synthesize fillers in milliseconds.
        """
        if not self._config.enabled:
            return 0.0

        import time
        start = time.perf_counter()

        texts = self._config.custom_fillers
        if not texts:
            lang_key = "pt" if self._config.language.startswith("pt") else "en"
            texts = _DEFAULT_FILLERS.get(lang_key, _DEFAULT_FILLERS["en"])

        from voice_pipeline.runnable import RunnableConfig
        tts_config = RunnableConfig(
            configurable={"voice": self._config.filler_voice},
        )

        for text in texts:
            try:
                chunks: list[AudioChunk] = []
                total_samples = 0

                async for chunk in tts.astream(text, tts_config):
                    chunks.append(chunk)
                    total_samples += len(chunk.data) // 2  # PCM16

                    # Check max duration
                    duration_ms = (total_samples / chunk.sample_rate) * 1000
                    if duration_ms >= self._config.max_filler_duration_ms:
                        break

                if chunks:
                    # Merge chunks into single AudioChunk
                    merged = self._merge_and_trim(chunks)
                    if merged:
                        self._fillers.append(merged)

            except Exception as e:
                logger.warning(f"Failed to synthesize filler '{text}': {e}")

        self._ready = len(self._fillers) > 0
        elapsed_ms = (time.perf_counter() - start) * 1000

        if self._ready:
            logger.info(
                f"Warmed up {len(self._fillers)} fillers in {elapsed_ms:.1f}ms"
            )

        return elapsed_ms

    def _merge_and_trim(self, chunks: list[AudioChunk]) -> Optional[AudioChunk]:
        """Merge audio chunks and apply max duration + fade-out."""
        if not chunks:
            return None

        import numpy as np

        all_data = b"".join(c.data for c in chunks)
        sample_rate = chunks[0].sample_rate

        samples = np.frombuffer(all_data, dtype=np.int16).astype(np.float32)

        # Trim to max duration
        max_samples = int(self._config.max_filler_duration_ms / 1000 * sample_rate)
        if len(samples) > max_samples:
            samples = samples[:max_samples]

        # Apply fade-out
        fade_samples = int(self._config.fade_out_ms / 1000 * sample_rate)
        if fade_samples > 0 and len(samples) > fade_samples:
            fade = np.linspace(1.0, 0.0, fade_samples)
            samples[-fade_samples:] *= fade

        result_bytes = samples.astype(np.int16).tobytes()
        return AudioChunk(
            data=result_bytes,
            sample_rate=sample_rate,
        )

    def get_filler(self) -> Optional[AudioChunk]:
        """Get the next filler sound in round-robin order.

        Returns:
            AudioChunk of the filler, or None if not ready/disabled.
        """
        if not self._ready or not self._fillers:
            return None

        filler = self._fillers[self._index % len(self._fillers)]
        self._index += 1
        return filler

    @property
    def is_ready(self) -> bool:
        """Whether fillers are pre-synthesized and ready."""
        return self._ready

    @property
    def enabled(self) -> bool:
        """Whether filler injection is enabled."""
        return self._config.enabled
