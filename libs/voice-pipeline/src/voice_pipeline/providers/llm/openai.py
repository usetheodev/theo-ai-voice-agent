"""OpenAI LLM provider.

OpenAI's GPT models for text generation and chat completions.
Supports GPT-4, GPT-4 Turbo, GPT-3.5 Turbo, and other models.

Reference: https://platform.openai.com/docs/api-reference/chat
"""

import os
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from voice_pipeline.interfaces.llm import LLMChunk, LLMInterface, LLMResponse
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)


@dataclass
class OpenAILLMConfig(ProviderConfig):
    """Configuration for OpenAI LLM provider.

    Attributes:
        model: Model to use (gpt-4, gpt-4-turbo, gpt-3.5-turbo, etc.).
        api_key: OpenAI API key. Falls back to OPENAI_API_KEY env var.
        api_base: API base URL. Defaults to OpenAI's API.
        organization: OpenAI organization ID (optional).
        default_temperature: Default sampling temperature.
        default_max_tokens: Default max tokens to generate.

    Example:
        >>> config = OpenAILLMConfig(
        ...     model="gpt-4-turbo",
        ...     api_key="sk-...",
        ...     default_temperature=0.7,
        ... )
        >>> llm = OpenAILLMProvider(config=config)
    """

    model: str = "gpt-4o-mini"
    """Model to use (gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo, etc.)."""

    organization: Optional[str] = None
    """OpenAI organization ID (optional)."""

    default_temperature: float = 0.7
    """Default sampling temperature (0.0 to 2.0)."""

    default_max_tokens: Optional[int] = None
    """Default max tokens to generate."""

    default_system_prompt: Optional[str] = None
    """Default system prompt to use."""


class OpenAILLMProvider(BaseProvider, LLMInterface):
    """OpenAI LLM provider.

    Uses OpenAI's Chat Completions API for text generation.
    Supports streaming for low-latency voice applications.

    Features:
    - Streaming text generation
    - Tool/function calling support
    - Multiple models (GPT-4, GPT-3.5, etc.)
    - Configurable temperature, max_tokens
    - Automatic retry with exponential backoff

    Example:
        >>> llm = OpenAILLMProvider(
        ...     model="gpt-4o-mini",
        ...     api_key="sk-...",
        ... )
        >>> await llm.connect()
        >>>
        >>> # Generate streaming response
        >>> async for chunk in llm.generate_stream(
        ...     messages=[{"role": "user", "content": "Hello!"}]
        ... ):
        ...     print(chunk.text, end="")
        >>>
        >>> # Or use with pipeline
        >>> chain = asr | llm | tts
        >>> await chain.ainvoke(audio_bytes)

    Attributes:
        provider_name: "openai-llm"
        name: "OpenAILLM" (for VoiceRunnable)
    """

    provider_name: str = "openai-llm"
    name: str = "OpenAILLM"

    def __init__(
        self,
        config: Optional[OpenAILLMConfig] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: Optional[float] = None,
        **kwargs,
    ):
        """Initialize OpenAI LLM provider.

        Args:
            config: Full configuration object.
            model: Model to use (shortcut).
            api_key: OpenAI API key (shortcut).
            temperature: Default temperature (shortcut).
            **kwargs: Additional configuration options.
        """
        # Build config from parameters
        if config is None:
            config = OpenAILLMConfig()

        # Apply shortcuts
        if model is not None:
            config.model = model
        if api_key is not None:
            config.api_key = api_key
        if temperature is not None:
            config.default_temperature = temperature

        super().__init__(config=config, **kwargs)

        self._llm_config: OpenAILLMConfig = config
        self._client = None
        self._async_client = None

    async def connect(self) -> None:
        """Initialize OpenAI client."""
        await super().connect()

        try:
            from openai import AsyncOpenAI, OpenAI
        except ImportError:
            raise ImportError(
                "openai is required for OpenAI LLM. "
                "Install with: pip install openai"
            )

        # Get API key
        api_key = self._llm_config.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenAI API key is required. "
                "Set OPENAI_API_KEY environment variable or pass api_key parameter."
            )

        # Build client kwargs
        client_kwargs = {"api_key": api_key}

        if self._llm_config.api_base:
            client_kwargs["base_url"] = self._llm_config.api_base

        if self._llm_config.organization:
            client_kwargs["organization"] = self._llm_config.organization

        if self._llm_config.timeout:
            client_kwargs["timeout"] = self._llm_config.timeout

        # Create clients
        self._client = OpenAI(**client_kwargs)
        self._async_client = AsyncOpenAI(**client_kwargs)

    async def disconnect(self) -> None:
        """Close OpenAI client."""
        if self._async_client:
            await self._async_client.close()
        self._async_client = None
        self._client = None
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if OpenAI API is accessible."""
        if self._async_client is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Client not initialized. Call connect() first.",
            )

        try:
            # Make a minimal API call to check connectivity
            response = await self._async_client.chat.completions.create(
                model=self._llm_config.model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=1,
            )

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"OpenAI API accessible. Model: {self._llm_config.model}",
                details={"model": self._llm_config.model},
            )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"OpenAI API error: {e}",
            )

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        """Generate streaming response from OpenAI.

        Args:
            messages: Conversation history.
            system_prompt: Optional system prompt.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional OpenAI API parameters.

        Yields:
            LLMChunk objects with text tokens.

        Raises:
            RuntimeError: If client is not connected.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Build messages with system prompt
        full_messages = []

        # Add system prompt
        effective_system_prompt = (
            system_prompt or self._llm_config.default_system_prompt
        )
        if effective_system_prompt:
            full_messages.append({
                "role": "system",
                "content": effective_system_prompt,
            })

        full_messages.extend(messages)

        # Build request
        request_kwargs = {
            "model": self._llm_config.model,
            "messages": full_messages,
            "temperature": temperature,
            "stream": True,
        }

        if max_tokens or self._llm_config.default_max_tokens:
            request_kwargs["max_tokens"] = (
                max_tokens or self._llm_config.default_max_tokens
            )

        if stop:
            request_kwargs["stop"] = stop

        # Add any extra kwargs
        request_kwargs.update(kwargs)

        # Track timing
        start_time = time.perf_counter()
        total_text = ""
        finish_reason = None

        try:
            stream = await self._async_client.chat.completions.create(
                **request_kwargs
            )

            async for chunk in stream:
                if chunk.choices:
                    choice = chunk.choices[0]

                    # Extract text delta
                    delta = choice.delta
                    text = delta.content or ""

                    if text:
                        total_text += text
                        yield LLMChunk(
                            text=text,
                            is_final=False,
                        )

                    # Check for finish reason
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason

            # Final chunk with stats
            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            yield LLMChunk(
                text="",
                is_final=True,
                finish_reason=finish_reason,
            )

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    async def generate(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        **kwargs,
    ) -> str:
        """Generate complete response.

        Non-streaming version for simpler use cases.

        Args:
            messages: Conversation history.
            system_prompt: Optional system prompt.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters.

        Returns:
            Complete response text.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Build messages with system prompt
        full_messages = []

        effective_system_prompt = (
            system_prompt or self._llm_config.default_system_prompt
        )
        if effective_system_prompt:
            full_messages.append({
                "role": "system",
                "content": effective_system_prompt,
            })

        full_messages.extend(messages)

        # Build request
        request_kwargs = {
            "model": self._llm_config.model,
            "messages": full_messages,
            "temperature": temperature,
        }

        if max_tokens or self._llm_config.default_max_tokens:
            request_kwargs["max_tokens"] = (
                max_tokens or self._llm_config.default_max_tokens
            )

        if stop:
            request_kwargs["stop"] = stop

        request_kwargs.update(kwargs)

        start_time = time.perf_counter()

        try:
            response = await self._async_client.chat.completions.create(
                **request_kwargs
            )

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            return response.choices[0].message.content or ""

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    async def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        """Generate response with tool calling support.

        Args:
            messages: Conversation history (may include tool results).
            tools: List of tool schemas in OpenAI format.
            system_prompt: Optional system prompt.
            tool_choice: Tool selection mode ("auto", "none", "required").
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters.

        Returns:
            LLMResponse with content and/or tool_calls.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Build messages with system prompt
        full_messages = []

        effective_system_prompt = (
            system_prompt or self._llm_config.default_system_prompt
        )
        if effective_system_prompt:
            full_messages.append({
                "role": "system",
                "content": effective_system_prompt,
            })

        full_messages.extend(messages)

        # Build request
        request_kwargs = {
            "model": self._llm_config.model,
            "messages": full_messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": temperature,
        }

        if max_tokens or self._llm_config.default_max_tokens:
            request_kwargs["max_tokens"] = (
                max_tokens or self._llm_config.default_max_tokens
            )

        if kwargs.get("stop"):
            request_kwargs["stop"] = kwargs.pop("stop")

        request_kwargs.update(kwargs)

        start_time = time.perf_counter()

        try:
            response = await self._async_client.chat.completions.create(
                **request_kwargs
            )

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            message = response.choices[0].message
            usage = response.usage

            # Convert tool calls to dict format
            tool_calls = []
            if message.tool_calls:
                for tc in message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    })

            return LLMResponse(
                content=message.content or "",
                tool_calls=tool_calls,
                finish_reason=response.choices[0].finish_reason,
                usage={
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                } if usage else None,
            )

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    def supports_tools(self) -> bool:
        """Check if this LLM supports tool calling.

        Returns:
            True - OpenAI models support function calling.
        """
        return True

    def _handle_error(self, error: Exception) -> None:
        """Convert OpenAI errors to provider errors.

        Args:
            error: Original exception.

        Raises:
            RetryableError: For transient errors.
            NonRetryableError: For permanent errors.
        """
        error_str = str(error).lower()

        # Retryable errors
        if any(x in error_str for x in [
            "rate limit",
            "timeout",
            "connection",
            "server error",
            "503",
            "502",
            "500",
            "overloaded",
        ]):
            raise RetryableError(str(error)) from error

        # Non-retryable errors
        if any(x in error_str for x in [
            "invalid api key",
            "authentication",
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
            f"OpenAILLMProvider("
            f"model={self._llm_config.model!r}, "
            f"connected={self._connected})"
        )
