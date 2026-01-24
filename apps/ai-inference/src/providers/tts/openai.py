"""OpenAI TTS Provider.

Calls OpenAI Text-to-Speech API.
"""

import logging
from typing import AsyncIterator, Optional

import httpx

from ..base import TTSProvider, AudioChunk
from ..exceptions import (
    ProviderConnectionError,
    ProviderTimeoutError,
    ProviderAuthError,
)

logger = logging.getLogger(__name__)


class OpenAITTS(TTSProvider):
    """OpenAI Text-to-Speech API provider.

    Usage:
        provider = OpenAITTS(
            api_key="sk-...",
        )

        audio = await provider.synthesize(
            "Hello, how are you?",
            voice="nova",
        )
    """

    VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

    def __init__(
        self,
        api_base: str = "https://api.openai.com/v1",
        api_key: Optional[str] = None,
        default_voice: str = "nova",
        model: str = "tts-1",  # tts-1 or tts-1-hd
        timeout: float = 30.0,
        **kwargs,
    ):
        """Initialize OpenAI TTS provider.

        Args:
            api_base: API base URL.
            api_key: OpenAI API key.
            default_voice: Default voice to use.
            model: TTS model (tts-1 for speed, tts-1-hd for quality).
            timeout: Request timeout in seconds.
        """
        super().__init__(api_base, api_key, timeout, **kwargs)
        self.default_voice = default_voice
        self.model = model

    @property
    def name(self) -> str:
        return "openai-tts"

    @property
    def supports_streaming(self) -> bool:
        # OpenAI TTS supports streaming response
        return True

    @property
    def available_voices(self) -> list[str]:
        return self.VOICES

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        **kwargs,
    ) -> AudioChunk:
        """Synthesize text to speech.

        Args:
            text: Text to synthesize.
            voice: Voice ID (alloy, echo, fable, onyx, nova, shimmer).

        Returns:
            Audio data in MP3 format.
        """
        url = f"{self.api_base}/audio/speech"

        voice = voice or self.default_voice
        response_format = kwargs.get("response_format", "mp3")
        speed = kwargs.get("speed", 1.0)

        payload = {
            "model": self.model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
            "speed": speed,
        }

        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code == 401:
                    raise ProviderAuthError("Invalid API key", provider=self.name)

                response.raise_for_status()

                # Determine format and sample rate
                format_info = {
                    "mp3": ("mp3", 24000),
                    "opus": ("opus", 24000),
                    "aac": ("aac", 24000),
                    "flac": ("flac", 24000),
                    "pcm": ("pcm16", 24000),
                }
                audio_format, sample_rate = format_info.get(
                    response_format, ("mp3", 24000)
                )

                return AudioChunk(
                    data=response.content,
                    sample_rate=sample_rate,
                    channels=1,
                    format=audio_format,
                    is_final=True,
                )

        except httpx.ConnectError as e:
            raise ProviderConnectionError(f"Connection failed: {e}", provider=self.name)
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(f"Request timed out: {e}", provider=self.name)
        except httpx.HTTPStatusError as e:
            raise ProviderConnectionError(
                f"API error: {e.response.status_code}",
                provider=self.name,
            )

    async def synthesize_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        """Synthesize text with streaming audio output.

        OpenAI TTS streams the response as it's generated.

        Args:
            text: Text to synthesize.
            voice: Voice ID.

        Yields:
            Audio chunks as they're generated.
        """
        url = f"{self.api_base}/audio/speech"

        voice = voice or self.default_voice
        response_format = kwargs.get("response_format", "mp3")
        speed = kwargs.get("speed", 1.0)

        payload = {
            "model": self.model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
            "speed": speed,
        }

        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    url,
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code == 401:
                        raise ProviderAuthError("Invalid API key", provider=self.name)

                    response.raise_for_status()

                    chunk_size = 4096  # 4KB chunks
                    is_first = True

                    async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                        if chunk:
                            yield AudioChunk(
                                data=chunk,
                                sample_rate=24000,
                                channels=1,
                                format="mp3" if response_format == "mp3" else response_format,
                                is_final=False,
                            )
                            is_first = False

                    # Final empty chunk to signal end
                    yield AudioChunk(
                        data=b"",
                        sample_rate=24000,
                        channels=1,
                        format="mp3",
                        is_final=True,
                    )

        except httpx.ConnectError as e:
            raise ProviderConnectionError(f"Connection failed: {e}", provider=self.name)
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(f"Request timed out: {e}", provider=self.name)
