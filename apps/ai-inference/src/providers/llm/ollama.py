"""Ollama LLM Provider.

Calls Ollama API for local LLM inference.
Ollama provides OpenAI-compatible API.
"""

import json
import logging
from typing import AsyncIterator, Optional

import httpx

from ..base import LLMProvider, LLMResponse
from ..exceptions import (
    ProviderConnectionError,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)


class OllamaLLM(LLMProvider):
    """Ollama API provider for local LLM inference.

    Usage:
        provider = OllamaLLM(
            api_base="http://localhost:11434",
            model="llama3:8b",
        )

        async for chunk in provider.generate_stream(messages):
            print(chunk.text, end="")
    """

    def __init__(
        self,
        api_base: str = "http://localhost:11434",
        api_key: Optional[str] = None,  # Ollama doesn't require API key
        model: str = "llama3:8b",
        timeout: float = 120.0,  # Local models can be slower
        **kwargs,
    ):
        """Initialize Ollama provider.

        Args:
            api_base: Ollama server URL.
            api_key: Not used (Ollama is local).
            model: Model to use (e.g., llama3:8b, mistral:7b).
            timeout: Request timeout in seconds.
        """
        super().__init__(api_base, api_key, timeout, **kwargs)
        self.model = model

    @property
    def name(self) -> str:
        return "ollama"

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
        """Generate complete response using Ollama.

        Args:
            messages: Conversation history.
            system_prompt: System prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Returns:
            Complete LLM response.
        """
        # Ollama has OpenAI-compatible endpoint
        url = f"{self.api_base}/v1/chat/completions"

        payload = {
            "model": self.model,
            "messages": self._build_messages(messages, system_prompt),
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        if kwargs.get("top_p") is not None:
            payload["options"]["top_p"] = kwargs["top_p"]
        if kwargs.get("top_k") is not None:
            payload["options"]["top_k"] = kwargs["top_k"]

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

                response.raise_for_status()

                data = response.json()
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})

                return LLMResponse(
                    text=message.get("content", ""),
                    is_complete=True,
                    finish_reason=choice.get("finish_reason", "stop"),
                    usage=data.get("usage"),
                )

        except httpx.ConnectError as e:
            raise ProviderConnectionError(
                f"Failed to connect to Ollama at {self.api_base}. "
                f"Make sure Ollama is running: {e}",
                provider=self.name,
            )
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(
                f"Request timed out. Model may be loading: {e}",
                provider=self.name,
            )
        except httpx.HTTPStatusError as e:
            raise ProviderConnectionError(
                f"API error: {e.response.status_code} - {e.response.text}",
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
        """Generate response with streaming using Ollama.

        Args:
            messages: Conversation history.
            system_prompt: System prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Yields:
            Response chunks as they're generated.
        """
        # Use OpenAI-compatible streaming endpoint
        url = f"{self.api_base}/v1/chat/completions"

        payload = {
            "model": self.model,
            "messages": self._build_messages(messages, system_prompt),
            "stream": True,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        if kwargs.get("top_p") is not None:
            payload["options"]["top_p"] = kwargs["top_p"]

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as response:
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
            raise ProviderConnectionError(
                f"Failed to connect to Ollama: {e}",
                provider=self.name,
            )
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(
                f"Request timed out: {e}",
                provider=self.name,
            )

    async def list_models(self) -> list[str]:
        """List available models in Ollama.

        Returns:
            List of model names.
        """
        url = f"{self.api_base}/api/tags"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()

                data = response.json()
                return [model["name"] for model in data.get("models", [])]

        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
            return []

    async def pull_model(self, model_name: str) -> bool:
        """Pull a model from Ollama registry.

        Args:
            model_name: Model to pull (e.g., llama3:8b).

        Returns:
            True if successful.
        """
        url = f"{self.api_base}/api/pull"

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:  # Long timeout for download
                response = await client.post(
                    url,
                    json={"name": model_name},
                )
                response.raise_for_status()
                return True

        except Exception as e:
            logger.error(f"Failed to pull model {model_name}: {e}")
            return False
