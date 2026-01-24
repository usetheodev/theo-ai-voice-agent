"""Deepgram ASR Provider.

Calls Deepgram API for real-time streaming transcription.
Supports both batch and streaming modes.
"""

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

import httpx

from ..base import ASRProvider, TranscriptionResult
from ..exceptions import (
    ProviderConnectionError,
    ProviderTimeoutError,
    ProviderAuthError,
)

logger = logging.getLogger(__name__)


class DeepgramASR(ASRProvider):
    """Deepgram API provider with streaming support.

    Usage:
        provider = DeepgramASR(
            api_key="your-deepgram-api-key",
            model="nova-2",
        )

        # Batch transcription
        result = await provider.transcribe(audio_bytes, language="pt-BR")

        # Streaming transcription
        async for result in provider.transcribe_stream(audio_stream):
            print(result.text, result.is_final)
    """

    def __init__(
        self,
        api_base: str = "https://api.deepgram.com/v1",
        api_key: Optional[str] = None,
        model: str = "nova-2",
        timeout: float = 30.0,
        **kwargs,
    ):
        """Initialize Deepgram provider.

        Args:
            api_base: API base URL.
            api_key: Deepgram API key.
            model: Model to use (nova-2, nova, enhanced, base).
            timeout: Request timeout in seconds.
        """
        super().__init__(api_base, api_key, timeout, **kwargs)
        self.model = model

    @property
    def name(self) -> str:
        return "deepgram"

    @property
    def supports_streaming(self) -> bool:
        return True

    def _build_query_params(
        self,
        language: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Build query parameters for Deepgram API."""
        params = {
            "model": self.model,
            "smart_format": "true",
            "punctuate": "true",
        }

        if language:
            # Deepgram uses BCP-47 codes
            params["language"] = language

        # Additional options
        if kwargs.get("diarize"):
            params["diarize"] = "true"
        if kwargs.get("numerals"):
            params["numerals"] = "true"
        if kwargs.get("keywords"):
            params["keywords"] = ",".join(kwargs["keywords"])

        return params

    async def transcribe(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
        **kwargs,
    ) -> TranscriptionResult:
        """Transcribe audio using Deepgram batch API.

        Args:
            audio_data: Audio bytes.
            language: Language code (e.g., 'pt-BR', 'en-US').

        Returns:
            Transcription result.
        """
        url = f"{self.api_base}/listen"
        params = self._build_query_params(language, **kwargs)

        headers = {
            "Content-Type": "audio/wav",
        }
        if self.api_key:
            headers["Authorization"] = f"Token {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    params=params,
                    content=audio_data,
                    headers=headers,
                )

                if response.status_code == 401:
                    raise ProviderAuthError(
                        "Invalid API key",
                        provider=self.name,
                    )

                response.raise_for_status()

                result = response.json()
                channel = result.get("results", {}).get("channels", [{}])[0]
                alternative = channel.get("alternatives", [{}])[0]

                return TranscriptionResult(
                    text=alternative.get("transcript", "").strip(),
                    is_final=True,
                    confidence=alternative.get("confidence", 1.0),
                    language=result.get("results", {}).get("channels", [{}])[0].get(
                        "detected_language", language
                    ),
                    words=alternative.get("words"),
                )

        except httpx.ConnectError as e:
            raise ProviderConnectionError(
                f"Failed to connect to Deepgram API: {e}",
                provider=self.name,
            )
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(
                f"Request timed out: {e}",
                provider=self.name,
            )
        except httpx.HTTPStatusError as e:
            raise ProviderConnectionError(
                f"API error: {e.response.status_code} - {e.response.text}",
                provider=self.name,
            )

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[TranscriptionResult]:
        """Stream transcription using Deepgram WebSocket API.

        Args:
            audio_stream: Async iterator of audio chunks.
            language: Language code.

        Yields:
            Partial and final transcription results.
        """
        try:
            import websockets
        except ImportError:
            logger.warning("websockets not installed, falling back to batch mode")
            async for result in super().transcribe_stream(audio_stream, language, **kwargs):
                yield result
            return

        # Build WebSocket URL
        params = self._build_query_params(language, **kwargs)
        params["interim_results"] = "true"
        params["endpointing"] = "300"  # 300ms silence detection

        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        ws_url = f"wss://api.deepgram.com/v1/listen?{query_string}"

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Token {self.api_key}"

        try:
            async with websockets.connect(
                ws_url,
                extra_headers=headers,
                ping_interval=5,
                ping_timeout=20,
            ) as websocket:

                # Task to send audio
                async def send_audio():
                    try:
                        async for chunk in audio_stream:
                            await websocket.send(chunk)
                        # Send close signal
                        await websocket.send(json.dumps({"type": "CloseStream"}))
                    except Exception as e:
                        logger.error(f"Error sending audio: {e}")

                # Start sending audio in background
                send_task = asyncio.create_task(send_audio())

                # Receive transcriptions
                try:
                    async for message in websocket:
                        data = json.loads(message)

                        if data.get("type") == "Results":
                            channel = data.get("channel", {})
                            alternatives = channel.get("alternatives", [{}])

                            if alternatives:
                                alt = alternatives[0]
                                transcript = alt.get("transcript", "").strip()

                                if transcript:
                                    yield TranscriptionResult(
                                        text=transcript,
                                        is_final=data.get("is_final", False),
                                        confidence=alt.get("confidence", 1.0),
                                        language=language,
                                        start_time=data.get("start"),
                                        end_time=data.get("start", 0) + data.get("duration", 0),
                                        words=alt.get("words"),
                                    )

                        elif data.get("type") == "Metadata":
                            # Connection metadata
                            logger.debug(f"Deepgram metadata: {data}")

                except websockets.ConnectionClosed:
                    logger.debug("Deepgram WebSocket closed")

                finally:
                    send_task.cancel()
                    try:
                        await send_task
                    except asyncio.CancelledError:
                        pass

        except Exception as e:
            raise ProviderConnectionError(
                f"WebSocket error: {e}",
                provider=self.name,
            )
