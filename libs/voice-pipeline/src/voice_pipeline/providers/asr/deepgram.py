"""Deepgram ASR provider.

Real-time streaming ASR using Deepgram's WebSocket API.
Provides true streaming transcription with partial results.

Reference: https://developers.deepgram.com/docs/streaming

Features:
- Real-time streaming ASR via WebSocket
- Partial transcriptions (words as they're spoken)
- Final transcriptions (complete utterances)
- Multiple languages supported
- Speaker diarization (optional)
- Smart formatting (punctuation, capitalization)
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Literal, Optional

from voice_pipeline.interfaces.asr import ASRInterface, TranscriptionResult
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)
from voice_pipeline.providers.decorators import register_asr
from voice_pipeline.providers.types import ASRCapabilities


# Deepgram models
DeepgramModel = Literal[
    "nova-2",           # Best quality, low latency
    "nova-2-general",   # General purpose
    "nova-2-meeting",   # Optimized for meetings
    "nova-2-phonecall", # Optimized for phone calls
    "nova-2-voicemail", # Optimized for voicemail
    "nova",             # Previous generation
    "enhanced",         # Enhanced accuracy
    "base",             # Base model
]


@dataclass
class DeepgramASRConfig(ProviderConfig):
    """Configuration for Deepgram ASR provider.

    Attributes:
        api_key: Deepgram API key. If None, uses DEEPGRAM_API_KEY env var.
        model: Deepgram model to use (default "nova-2").
        language: Language code (default "en-US").
        sample_rate: Audio sample rate (default 16000).
        encoding: Audio encoding (default "linear16" for PCM16).
        channels: Number of audio channels (default 1).
        punctuate: Add punctuation (default True).
        smart_format: Apply smart formatting (default True).
        diarize: Enable speaker diarization (default False).
        utterances: Detect utterance boundaries (default True).
        interim_results: Emit partial transcriptions (default True).
        endpointing: Utterance end detection threshold in ms (default 300).
        vad_events: Enable VAD events (default False).
        keywords: Keywords to boost recognition.
        profanity_filter: Filter profanity (default False).
        redact: Redact sensitive info (default False).
        numerals: Convert numbers to digits (default True).

    Example:
        >>> config = DeepgramASRConfig(
        ...     model="nova-2",
        ...     language="pt-BR",
        ...     smart_format=True,
        ... )
        >>> asr = DeepgramASRProvider(config=config)
    """

    api_key: Optional[str] = None
    """Deepgram API key. Falls back to DEEPGRAM_API_KEY env var."""

    model: str = "nova-2"
    """Deepgram model (nova-2, nova, enhanced, base)."""

    language: str = "en-US"
    """Language code (e.g., 'en-US', 'pt-BR', 'es')."""

    sample_rate: int = 16000
    """Audio sample rate in Hz."""

    encoding: str = "linear16"
    """Audio encoding format."""

    channels: int = 1
    """Number of audio channels."""

    punctuate: bool = True
    """Add punctuation to transcriptions."""

    smart_format: bool = True
    """Apply smart formatting (numbers, dates, etc.)."""

    diarize: bool = False
    """Enable speaker diarization."""

    utterances: bool = True
    """Detect utterance boundaries."""

    interim_results: bool = True
    """Emit partial transcriptions as they're generated."""

    endpointing: int = 300
    """Utterance end detection threshold in milliseconds."""

    vad_events: bool = False
    """Enable VAD (Voice Activity Detection) events."""

    keywords: list[str] = field(default_factory=list)
    """Keywords to boost recognition."""

    profanity_filter: bool = False
    """Filter profane words."""

    redact: bool = False
    """Redact sensitive information (PII, SSN, etc.)."""

    numerals: bool = True
    """Convert spoken numbers to digits."""

    filler_words: bool = False
    """Include filler words (um, uh, etc.)."""


@register_asr(
    name="deepgram",
    capabilities=ASRCapabilities(
        streaming=True,
        languages=["en", "es", "fr", "de", "pt", "it", "nl", "ja", "ko", "zh", "hi", "ru"],
        real_time=True,  # True real-time streaming
        word_timestamps=True,
        speaker_diarization=True,
    ),
    description="Real-time streaming ASR using Deepgram's WebSocket API.",
    version="1.0.0",
    aliases=["deepgram-asr", "dg"],
    tags=["cloud", "streaming", "real-time", "high-accuracy"],
    default_config={
        "model": "nova-2",
        "language": "en-US",
        "interim_results": True,
    },
)
class DeepgramASRProvider(BaseProvider, ASRInterface):
    """Deepgram ASR provider for real-time streaming transcription.

    Uses Deepgram's WebSocket API for true real-time ASR with partial
    results. Audio is streamed continuously and transcriptions are
    returned as they're generated.

    Features:
    - True real-time streaming (words as they're spoken)
    - Partial and final transcriptions
    - Multiple model options (nova-2, nova, enhanced)
    - Speaker diarization
    - Smart formatting (punctuation, numbers)
    - Multiple languages

    Example:
        >>> asr = DeepgramASRProvider(
        ...     model="nova-2",
        ...     language="pt-BR",
        ...     interim_results=True,
        ... )
        >>> await asr.connect()
        >>>
        >>> # Stream audio and get real-time transcriptions
        >>> async for result in asr.transcribe_stream(audio_stream):
        ...     if result.is_final:
        ...         print(f"Final: {result.text}")
        ...     else:
        ...         print(f"Partial: {result.text}")
        >>>
        >>> # Or use with pipeline
        >>> chain = asr | llm | tts
        >>> await chain.ainvoke(audio_stream)

    Attributes:
        provider_name: "deepgram"
        name: "DeepgramASR" (for VoiceRunnable)
    """

    provider_name: str = "deepgram"
    name: str = "DeepgramASR"

    @property
    def supports_streaming_input(self) -> bool:
        return True

    def __init__(
        self,
        config: Optional[DeepgramASRConfig] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        language: Optional[str] = None,
        interim_results: Optional[bool] = None,
        smart_format: Optional[bool] = None,
        diarize: Optional[bool] = None,
        **kwargs,
    ):
        """Initialize Deepgram ASR provider.

        Args:
            config: Full configuration object.
            api_key: API key (shortcut, or uses DEEPGRAM_API_KEY env var).
            model: Model name (shortcut).
            language: Language code (shortcut).
            interim_results: Enable partial results (shortcut).
            smart_format: Enable smart formatting (shortcut).
            diarize: Enable speaker diarization (shortcut).
            **kwargs: Additional configuration options.
        """
        # Build config from parameters
        if config is None:
            config = DeepgramASRConfig()

        # Apply shortcuts
        if api_key is not None:
            config.api_key = api_key
        if model is not None:
            config.model = model
        if language is not None:
            config.language = language
        if interim_results is not None:
            config.interim_results = interim_results
        if smart_format is not None:
            config.smart_format = smart_format
        if diarize is not None:
            config.diarize = diarize

        super().__init__(config=config, **kwargs)

        self._asr_config: DeepgramASRConfig = config
        self._client = None
        self._api_key: Optional[str] = None

    @property
    def sample_rate(self) -> int:
        """Expected input sample rate."""
        return self._asr_config.sample_rate

    def _get_api_key(self) -> str:
        """Get API key from config or environment."""
        api_key = self._asr_config.api_key or os.environ.get("DEEPGRAM_API_KEY")
        if not api_key:
            raise ValueError(
                "Deepgram API key not found. Set DEEPGRAM_API_KEY environment "
                "variable or pass api_key to constructor."
            )
        return api_key

    def _build_websocket_url(self) -> str:
        """Build WebSocket URL with query parameters."""
        base_url = "wss://api.deepgram.com/v1/listen"

        params = [
            f"model={self._asr_config.model}",
            f"language={self._asr_config.language}",
            f"encoding={self._asr_config.encoding}",
            f"sample_rate={self._asr_config.sample_rate}",
            f"channels={self._asr_config.channels}",
        ]

        if self._asr_config.punctuate:
            params.append("punctuate=true")
        if self._asr_config.smart_format:
            params.append("smart_format=true")
        if self._asr_config.diarize:
            params.append("diarize=true")
        if self._asr_config.utterances:
            params.append("utterances=true")
        if self._asr_config.interim_results:
            params.append("interim_results=true")
        if self._asr_config.endpointing:
            params.append(f"endpointing={self._asr_config.endpointing}")
        if self._asr_config.vad_events:
            params.append("vad_events=true")
        if self._asr_config.numerals:
            params.append("numerals=true")
        if self._asr_config.profanity_filter:
            params.append("profanity_filter=true")
        if self._asr_config.redact:
            params.append("redact=pci")
        if self._asr_config.filler_words:
            params.append("filler_words=true")
        if self._asr_config.keywords:
            for kw in self._asr_config.keywords:
                params.append(f"keywords={kw}")

        return f"{base_url}?{'&'.join(params)}"

    async def connect(self) -> None:
        """Initialize Deepgram client."""
        await super().connect()

        try:
            import websockets
        except ImportError:
            raise ImportError(
                "websockets is required for Deepgram streaming. "
                "Install with: pip install websockets"
            )

        # Validate API key
        self._api_key = self._get_api_key()

    async def disconnect(self) -> None:
        """Close Deepgram client."""
        self._api_key = None
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if Deepgram API is accessible."""
        try:
            import websockets

            # Try to connect briefly
            url = self._build_websocket_url()
            headers = {"Authorization": f"Token {self._api_key}"}

            async with websockets.connect(
                url,
                extra_headers=headers,
                close_timeout=5,
            ) as ws:
                # Send close message
                await ws.close()

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"Deepgram ready. Model: {self._asr_config.model}",
                details={
                    "model": self._asr_config.model,
                    "language": self._asr_config.language,
                },
            )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"Deepgram error: {e}",
            )

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        """Transcribe audio stream with real-time partial results.

        Connects to Deepgram WebSocket API and streams audio,
        yielding transcription results as they arrive.

        Args:
            audio_stream: Async iterator of audio chunks (PCM16, mono).
            language: Optional language code (overrides default).

        Yields:
            TranscriptionResult objects (partial and final).
        """
        if self._api_key is None:
            raise RuntimeError("Not connected. Call connect() first.")

        try:
            import websockets
        except ImportError:
            raise ImportError(
                "websockets is required for Deepgram streaming. "
                "Install with: pip install websockets"
            )

        # Build URL (with optional language override)
        if language:
            original_lang = self._asr_config.language
            self._asr_config.language = language

        url = self._build_websocket_url()

        if language:
            self._asr_config.language = original_lang

        headers = {"Authorization": f"Token {self._api_key}"}

        start_time = time.perf_counter()
        results_queue: asyncio.Queue = asyncio.Queue()
        send_done = asyncio.Event()
        receive_done = asyncio.Event()

        async def send_audio(ws):
            """Send audio chunks to WebSocket."""
            try:
                async for chunk in audio_stream:
                    if chunk:
                        await ws.send(chunk)
                # Signal end of audio
                await ws.send(json.dumps({"type": "CloseStream"}))
            except Exception as e:
                await results_queue.put(("error", e))
            finally:
                send_done.set()

        async def receive_results(ws):
            """Receive transcription results from WebSocket."""
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    except asyncio.TimeoutError:
                        if send_done.is_set():
                            break
                        continue

                    try:
                        data = json.loads(msg)
                    except json.JSONDecodeError:
                        continue

                    # Check message type
                    msg_type = data.get("type", "")

                    if msg_type == "Results":
                        # Extract transcription
                        channel = data.get("channel", {})
                        alternatives = channel.get("alternatives", [])

                        if alternatives:
                            alt = alternatives[0]
                            text = alt.get("transcript", "")
                            confidence = alt.get("confidence", 1.0)

                            is_final = data.get("is_final", False)

                            # Word timestamps
                            words = alt.get("words", [])
                            start_ts = None
                            end_ts = None
                            if words:
                                start_ts = words[0].get("start")
                                end_ts = words[-1].get("end")

                            if text:  # Only emit non-empty results
                                result = TranscriptionResult(
                                    text=text,
                                    is_final=is_final,
                                    confidence=confidence,
                                    language=self._asr_config.language,
                                    start_time=start_ts,
                                    end_time=end_ts,
                                )
                                await results_queue.put(("result", result))

                    elif msg_type == "Metadata":
                        # Connection metadata, ignore
                        pass

                    elif msg_type == "SpeechStarted":
                        # VAD detected speech start
                        pass

                    elif msg_type == "UtteranceEnd":
                        # Utterance boundary
                        pass

                    elif "error" in data:
                        error_msg = data.get("error", "Unknown error")
                        await results_queue.put(("error", Exception(error_msg)))
                        break

            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as e:
                await results_queue.put(("error", e))
            finally:
                receive_done.set()
                await results_queue.put(("done", None))

        try:
            async with websockets.connect(
                url,
                extra_headers=headers,
                ping_interval=20,
                ping_timeout=20,
            ) as ws:
                # Start send and receive tasks
                send_task = asyncio.create_task(send_audio(ws))
                receive_task = asyncio.create_task(receive_results(ws))

                try:
                    # Yield results as they arrive
                    while True:
                        item = await results_queue.get()
                        msg_type, payload = item

                        if msg_type == "result":
                            latency_ms = (time.perf_counter() - start_time) * 1000
                            self._metrics.record_success(latency_ms)
                            yield payload

                        elif msg_type == "error":
                            self._metrics.record_failure(str(payload))
                            raise payload

                        elif msg_type == "done":
                            break

                finally:
                    # Cancel tasks
                    send_task.cancel()
                    receive_task.cancel()
                    try:
                        await send_task
                    except asyncio.CancelledError:
                        pass
                    try:
                        await receive_task
                    except asyncio.CancelledError:
                        pass

        except Exception as e:
            self._handle_error(e)
            raise

    async def transcribe(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe complete audio data.

        Sends audio via WebSocket and collects final result.

        Args:
            audio_data: Complete audio data (PCM16, mono).
            language: Optional language code.

        Returns:
            Final transcription result.
        """
        async def audio_generator():
            # Send in chunks (for large audio)
            chunk_size = 8192  # 8KB chunks
            for i in range(0, len(audio_data), chunk_size):
                yield audio_data[i:i + chunk_size]

        final_result = TranscriptionResult(text="", is_final=True)
        full_text_parts = []

        async for result in self.transcribe_stream(audio_generator(), language):
            if result.is_final:
                full_text_parts.append(result.text)
                final_result = result

        # Combine all final results
        if full_text_parts:
            final_result = TranscriptionResult(
                text=" ".join(full_text_parts).strip(),
                is_final=True,
                confidence=final_result.confidence,
                language=final_result.language,
            )

        return final_result

    def _handle_error(self, error: Exception) -> None:
        """Convert Deepgram errors to provider errors.

        Args:
            error: Original exception.

        Raises:
            RetryableError: For transient errors.
            NonRetryableError: For permanent errors.
        """
        error_str = str(error).lower()

        # Retryable errors
        if any(x in error_str for x in [
            "timeout",
            "connection",
            "network",
            "rate limit",
            "429",
            "503",
            "502",
            "504",
        ]):
            raise RetryableError(str(error)) from error

        # Non-retryable errors
        if any(x in error_str for x in [
            "invalid api key",
            "unauthorized",
            "401",
            "403",
            "invalid",
            "not found",
            "404",
        ]):
            raise NonRetryableError(str(error)) from error

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"DeepgramASRProvider("
            f"model={self._asr_config.model!r}, "
            f"language={self._asr_config.language!r}, "
            f"interim_results={self._asr_config.interim_results}, "
            f"connected={self._connected})"
        )


# Alias for convenience
DeepgramASR = DeepgramASRProvider
