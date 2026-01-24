"""ElevenLabs TTS Provider.

Calls ElevenLabs API for high-quality text-to-speech synthesis.
Supports streaming for low latency.
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


class ElevenLabsTTS(TTSProvider):
    """ElevenLabs Text-to-Speech API provider.

    Usage:
        provider = ElevenLabsTTS(
            api_key="your-elevenlabs-api-key",
        )

        # Non-streaming
        audio = await provider.synthesize("Hello!", voice="rachel")

        # Streaming
        async for chunk in provider.synthesize_stream("Hello!"):
            play_audio(chunk.data)
    """

    # Default voices (can be fetched dynamically)
    DEFAULT_VOICES = [
        "rachel",
        "drew",
        "clyde",
        "paul",
        "domi",
        "dave",
        "fin",
        "sarah",
        "antoni",
        "thomas",
    ]

    def __init__(
        self,
        api_base: str = "https://api.elevenlabs.io/v1",
        api_key: Optional[str] = None,
        default_voice: str = "rachel",
        model_id: str = "eleven_multilingual_v2",
        timeout: float = 30.0,
        **kwargs,
    ):
        """Initialize ElevenLabs TTS provider.

        Args:
            api_base: API base URL.
            api_key: ElevenLabs API key.
            default_voice: Default voice ID.
            model_id: TTS model (eleven_multilingual_v2, eleven_turbo_v2, etc.).
            timeout: Request timeout in seconds.
        """
        super().__init__(api_base, api_key, timeout, **kwargs)
        self.default_voice = default_voice
        self.model_id = model_id
        self._voice_cache: dict[str, str] = {}  # name -> id mapping

    @property
    def name(self) -> str:
        return "elevenlabs"

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def available_voices(self) -> list[str]:
        return self.DEFAULT_VOICES

    def _get_headers(self) -> dict[str, str]:
        """Get headers for ElevenLabs API."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        if self.api_key:
            headers["xi-api-key"] = self.api_key
        return headers

    async def _resolve_voice_id(self, voice: str) -> str:
        """Resolve voice name to voice ID.

        Args:
            voice: Voice name or ID.

        Returns:
            Voice ID.
        """
        # If already looks like an ID (alphanumeric, no spaces), return as-is
        if voice and not " " in voice and len(voice) > 10:
            return voice

        # Check cache
        if voice in self._voice_cache:
            return self._voice_cache[voice]

        # Fetch voices and find match
        try:
            voices = await self.list_voices()
            for v in voices:
                if v.get("name", "").lower() == voice.lower():
                    voice_id = v.get("voice_id", voice)
                    self._voice_cache[voice] = voice_id
                    return voice_id
        except Exception as e:
            logger.warning(f"Failed to fetch voices: {e}")

        # Return as-is if not found
        return voice

    async def list_voices(self) -> list[dict]:
        """Fetch available voices from ElevenLabs.

        Returns:
            List of voice objects with id, name, etc.
        """
        url = f"{self.api_base}/voices"

        headers = {"xi-api-key": self.api_key} if self.api_key else {}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()

                data = response.json()
                return data.get("voices", [])

        except Exception as e:
            logger.warning(f"Failed to list voices: {e}")
            return []

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        **kwargs,
    ) -> AudioChunk:
        """Synthesize text to speech.

        Args:
            text: Text to synthesize.
            voice: Voice name or ID.

        Returns:
            Audio data in MP3 format.
        """
        voice = voice or self.default_voice
        voice_id = await self._resolve_voice_id(voice)

        url = f"{self.api_base}/text-to-speech/{voice_id}"

        payload = {
            "text": text,
            "model_id": kwargs.get("model_id", self.model_id),
            "voice_settings": {
                "stability": kwargs.get("stability", 0.5),
                "similarity_boost": kwargs.get("similarity_boost", 0.75),
                "style": kwargs.get("style", 0.0),
                "use_speaker_boost": kwargs.get("use_speaker_boost", True),
            },
        }

        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code == 401:
                    raise ProviderAuthError("Invalid API key", provider=self.name)

                response.raise_for_status()

                return AudioChunk(
                    data=response.content,
                    sample_rate=24000,  # ElevenLabs default
                    channels=1,
                    format="mp3",
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

        Args:
            text: Text to synthesize.
            voice: Voice name or ID.

        Yields:
            Audio chunks as they're generated.
        """
        voice = voice or self.default_voice
        voice_id = await self._resolve_voice_id(voice)

        # Use streaming endpoint
        url = f"{self.api_base}/text-to-speech/{voice_id}/stream"

        payload = {
            "text": text,
            "model_id": kwargs.get("model_id", self.model_id),
            "voice_settings": {
                "stability": kwargs.get("stability", 0.5),
                "similarity_boost": kwargs.get("similarity_boost", 0.75),
            },
        }

        # Query params for streaming
        params = {
            "output_format": kwargs.get("output_format", "mp3_44100_128"),
        }

        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    url,
                    json=payload,
                    params=params,
                    headers=headers,
                ) as response:
                    if response.status_code == 401:
                        raise ProviderAuthError("Invalid API key", provider=self.name)

                    response.raise_for_status()

                    chunk_size = 4096

                    async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                        if chunk:
                            yield AudioChunk(
                                data=chunk,
                                sample_rate=44100,  # Based on output_format
                                channels=1,
                                format="mp3",
                                is_final=False,
                            )

                    # Final chunk
                    yield AudioChunk(
                        data=b"",
                        sample_rate=44100,
                        channels=1,
                        format="mp3",
                        is_final=True,
                    )

        except httpx.ConnectError as e:
            raise ProviderConnectionError(f"Connection failed: {e}", provider=self.name)
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(f"Request timed out: {e}", provider=self.name)
