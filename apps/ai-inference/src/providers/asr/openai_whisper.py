"""OpenAI Whisper ASR Provider.

Calls OpenAI-compatible Whisper API for transcription.
Works with:
- OpenAI API (api.openai.com)
- faster-whisper-server (local)
- whisper.cpp server (local)
- Any OpenAI-compatible ASR endpoint
"""

import logging
from typing import Optional

import httpx

from ..base import ASRProvider, TranscriptionResult
from ..exceptions import (
    ProviderConnectionError,
    ProviderTimeoutError,
    ProviderAuthError,
)

logger = logging.getLogger(__name__)


class OpenAIWhisperASR(ASRProvider):
    """OpenAI Whisper API provider.

    Usage:
        # With OpenAI API
        provider = OpenAIWhisperASR(
            api_base="https://api.openai.com/v1",
            api_key="sk-...",
        )

        # With local faster-whisper-server
        provider = OpenAIWhisperASR(
            api_base="http://localhost:8000/v1",
        )

        result = await provider.transcribe(audio_bytes, language="pt")
    """

    def __init__(
        self,
        api_base: str = "https://api.openai.com/v1",
        api_key: Optional[str] = None,
        model: str = "whisper-1",
        timeout: float = 30.0,
        **kwargs,
    ):
        """Initialize OpenAI Whisper provider.

        Args:
            api_base: API base URL.
            api_key: OpenAI API key (required for OpenAI, optional for local).
            model: Whisper model to use.
            timeout: Request timeout in seconds.
        """
        super().__init__(api_base, api_key, timeout, **kwargs)
        self.model = model

    @property
    def name(self) -> str:
        return "openai-whisper"

    @property
    def supports_streaming(self) -> bool:
        # OpenAI Whisper API doesn't support streaming
        # For streaming, use Deepgram or local streaming server
        return False

    async def transcribe(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
        **kwargs,
    ) -> TranscriptionResult:
        """Transcribe audio using OpenAI Whisper API.

        Args:
            audio_data: Audio bytes (supports WAV, MP3, M4A, etc.).
            language: Language code (e.g., 'pt', 'en').

        Returns:
            Transcription result.
        """
        url = f"{self.api_base}/audio/transcriptions"

        # Build form data
        files = {
            "file": ("audio.wav", audio_data, "audio/wav"),
        }
        data = {
            "model": self.model,
        }

        if language:
            # Convert pt-BR to pt for OpenAI
            data["language"] = language.split("-")[0]

        # Optional parameters
        if kwargs.get("response_format"):
            data["response_format"] = kwargs["response_format"]
        if kwargs.get("temperature") is not None:
            data["temperature"] = kwargs["temperature"]
        if kwargs.get("prompt"):
            data["prompt"] = kwargs["prompt"]

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    files=files,
                    data=data,
                    headers=headers,
                )

                if response.status_code == 401:
                    raise ProviderAuthError(
                        "Invalid API key",
                        provider=self.name,
                    )

                response.raise_for_status()

                result = response.json()

                return TranscriptionResult(
                    text=result.get("text", "").strip(),
                    is_final=True,
                    confidence=1.0,  # OpenAI doesn't return confidence
                    language=result.get("language", language),
                )

        except httpx.ConnectError as e:
            raise ProviderConnectionError(
                f"Failed to connect to Whisper API: {e}",
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
