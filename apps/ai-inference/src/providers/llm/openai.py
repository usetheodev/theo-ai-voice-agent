"""OpenAI LLM Provider.

Calls OpenAI Chat Completions API.
Works with:
- OpenAI API (api.openai.com)
- Azure OpenAI
- Any OpenAI-compatible endpoint
"""

import json
import logging
from typing import AsyncIterator, Optional

import httpx

from ..base import LLMProvider, LLMResponse
from ..exceptions import (
    ProviderConnectionError,
    ProviderTimeoutError,
    ProviderAuthError,
    ProviderRateLimitError,
)

logger = logging.getLogger(__name__)


class OpenAILLM(LLMProvider):
    """OpenAI Chat Completions API provider.

    Usage:
        provider = OpenAILLM(
            api_key="sk-...",
            model="gpt-4o",
        )

        # Non-streaming
        response = await provider.generate(
            messages=[{"role": "user", "content": "Hello"}],
            system_prompt="You are a helpful assistant.",
        )

        # Streaming
        async for chunk in provider.generate_stream(messages):
            print(chunk.text, end="")
    """

    def __init__(
        self,
        api_base: str = "https://api.openai.com/v1",
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        timeout: float = 60.0,
        **kwargs,
    ):
        """Initialize OpenAI LLM provider.

        Args:
            api_base: API base URL.
            api_key: OpenAI API key.
            model: Model to use.
            timeout: Request timeout in seconds.
        """
        super().__init__(api_base, api_key, timeout, **kwargs)
        self.model = model

    @property
    def name(self) -> str:
        return "openai"

    @property
    def supports_streaming(self) -> bool:
        return True

    def _build_messages(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> list[dict[str, str]]:
        """Build messages list with optional system prompt."""
        result = []

        if system_prompt:
            result.append({"role": "system", "content": system_prompt})

        result.extend(messages)
        return result

    async def generate(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate complete response.

        Args:
            messages: Conversation history.
            system_prompt: System prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Returns:
            Complete LLM response.
        """
        url = f"{self.api_base}/chat/completions"

        payload = {
            "model": self.model,
            "messages": self._build_messages(messages, system_prompt),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        # Optional parameters
        if kwargs.get("top_p") is not None:
            payload["top_p"] = kwargs["top_p"]
        if kwargs.get("frequency_penalty") is not None:
            payload["frequency_penalty"] = kwargs["frequency_penalty"]
        if kwargs.get("presence_penalty") is not None:
            payload["presence_penalty"] = kwargs["presence_penalty"]
        if kwargs.get("stop"):
            payload["stop"] = kwargs["stop"]

        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code == 401:
                    raise ProviderAuthError("Invalid API key", provider=self.name)
                if response.status_code == 429:
                    raise ProviderRateLimitError("Rate limit exceeded", provider=self.name)

                response.raise_for_status()

                data = response.json()
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})

                return LLMResponse(
                    text=message.get("content", ""),
                    is_complete=True,
                    finish_reason=choice.get("finish_reason"),
                    usage=data.get("usage"),
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

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[LLMResponse]:
        """Generate response with streaming.

        Args:
            messages: Conversation history.
            system_prompt: System prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Yields:
            Response chunks as they're generated.
        """
        url = f"{self.api_base}/chat/completions"

        payload = {
            "model": self.model,
            "messages": self._build_messages(messages, system_prompt),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        # Optional parameters
        if kwargs.get("top_p") is not None:
            payload["top_p"] = kwargs["top_p"]
        if kwargs.get("stop"):
            payload["stop"] = kwargs["stop"]

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
                    if response.status_code == 429:
                        raise ProviderRateLimitError("Rate limit exceeded", provider=self.name)

                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line or line == "data: [DONE]":
                            continue

                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                                choice = data.get("choices", [{}])[0]
                                delta = choice.get("delta", {})
                                content = delta.get("content", "")
                                finish_reason = choice.get("finish_reason")

                                if content or finish_reason:
                                    yield LLMResponse(
                                        text=content,
                                        is_complete=finish_reason is not None,
                                        finish_reason=finish_reason,
                                    )

                            except json.JSONDecodeError:
                                continue

        except httpx.ConnectError as e:
            raise ProviderConnectionError(f"Connection failed: {e}", provider=self.name)
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(f"Request timed out: {e}", provider=self.name)
