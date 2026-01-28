"""Anthropic LLM provider.

Claude models for text generation and chat completions.
Supports Claude 3.5 Sonnet, Claude 3 Opus, Haiku, and other models.

Reference: https://docs.anthropic.com/en/api/messages
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
class AnthropicLLMConfig(ProviderConfig):
    """Configuration for Anthropic LLM provider.

    Attributes:
        model: Model to use (claude-3-5-sonnet-20241022, claude-3-opus, etc.).
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
        api_base: API base URL. Defaults to Anthropic's API.
        default_temperature: Default sampling temperature.
        default_max_tokens: Default max tokens to generate.
        default_system_prompt: Default system prompt.

    Example:
        >>> config = AnthropicLLMConfig(
        ...     model="claude-3-5-sonnet-20241022",
        ...     api_key="sk-ant-...",
        ...     default_temperature=0.7,
        ... )
        >>> llm = AnthropicLLMProvider(config=config)
    """

    model: str = "claude-3-5-sonnet-20241022"
    """Model to use (claude-3-5-sonnet-20241022, claude-3-opus-20240229, etc.)."""

    default_temperature: float = 0.7
    """Default sampling temperature (0.0 to 1.0)."""

    default_max_tokens: int = 4096
    """Default max tokens to generate. Required for Anthropic API."""

    default_system_prompt: Optional[str] = None
    """Default system prompt to use."""


class AnthropicLLMProvider(BaseProvider, LLMInterface):
    """Anthropic LLM provider.

    Uses Anthropic's Messages API for text generation.
    Supports streaming for low-latency voice applications.

    Features:
    - Streaming text generation
    - Tool/function calling support
    - Multiple models (Claude 3.5 Sonnet, Opus, Haiku)
    - Configurable temperature, max_tokens
    - Automatic retry with exponential backoff

    Example:
        >>> llm = AnthropicLLMProvider(
        ...     model="claude-3-5-sonnet-20241022",
        ...     api_key="sk-ant-...",
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
        provider_name: "anthropic-llm"
        name: "AnthropicLLM" (for VoiceRunnable)
    """

    provider_name: str = "anthropic-llm"
    name: str = "AnthropicLLM"

    def __init__(
        self,
        config: Optional[AnthropicLLMConfig] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ):
        """Initialize Anthropic LLM provider.

        Args:
            config: Full configuration object.
            model: Model to use (shortcut).
            api_key: Anthropic API key (shortcut).
            temperature: Default temperature (shortcut).
            max_tokens: Default max tokens (shortcut).
            **kwargs: Additional configuration options.
        """
        # Build config from parameters
        if config is None:
            config = AnthropicLLMConfig()

        # Apply shortcuts
        if model is not None:
            config.model = model
        if api_key is not None:
            config.api_key = api_key
        if temperature is not None:
            config.default_temperature = temperature
        if max_tokens is not None:
            config.default_max_tokens = max_tokens

        super().__init__(config=config, **kwargs)

        self._llm_config: AnthropicLLMConfig = config
        self._client = None
        self._async_client = None

    async def connect(self) -> None:
        """Initialize Anthropic client."""
        await super().connect()

        try:
            from anthropic import Anthropic, AsyncAnthropic
        except ImportError:
            raise ImportError(
                "anthropic is required for Anthropic LLM. "
                "Install with: pip install anthropic"
            )

        # Get API key
        api_key = self._llm_config.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "Anthropic API key is required. "
                "Set ANTHROPIC_API_KEY environment variable or pass api_key parameter."
            )

        # Build client kwargs
        client_kwargs = {"api_key": api_key}

        if self._llm_config.api_base:
            client_kwargs["base_url"] = self._llm_config.api_base

        if self._llm_config.timeout:
            client_kwargs["timeout"] = self._llm_config.timeout

        # Create clients
        self._client = Anthropic(**client_kwargs)
        self._async_client = AsyncAnthropic(**client_kwargs)

    async def disconnect(self) -> None:
        """Close Anthropic client."""
        if self._async_client:
            await self._async_client.close()
        self._async_client = None
        self._client = None
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if Anthropic API is accessible."""
        if self._async_client is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Client not initialized. Call connect() first.",
            )

        try:
            # Make a minimal API call to check connectivity
            response = await self._async_client.messages.create(
                model=self._llm_config.model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=1,
            )

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"Anthropic API accessible. Model: {self._llm_config.model}",
                details={"model": self._llm_config.model},
            )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"Anthropic API error: {e}",
            )

    def _convert_messages_to_anthropic(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert messages to Anthropic format.

        Anthropic uses a slightly different format:
        - No 'system' role in messages (separate parameter)
        - Tool results use 'tool_result' content blocks

        Args:
            messages: Messages in OpenAI format.

        Returns:
            Messages in Anthropic format.
        """
        result = []
        for msg in messages:
            role = msg.get("role", "user")

            if role == "system":
                # Skip system messages (handled separately)
                continue

            if role == "tool":
                # Convert tool result to Anthropic format
                result.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id", ""),
                            "content": msg.get("content", ""),
                        }
                    ],
                })
            elif role == "assistant" and msg.get("tool_calls"):
                # Assistant message with tool calls
                content = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    func = tc.get("function", tc)
                    import json
                    args = func.get("arguments", "{}")
                    if isinstance(args, str):
                        args = json.loads(args)
                    content.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "input": args,
                    })
                result.append({"role": "assistant", "content": content})
            else:
                # Regular message
                result.append({
                    "role": role,
                    "content": msg.get("content", ""),
                })

        return result

    def _convert_tools_to_anthropic(
        self,
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert tools from OpenAI format to Anthropic format.

        Args:
            tools: Tools in OpenAI format.

        Returns:
            Tools in Anthropic format.
        """
        result = []
        for tool in tools:
            func = tool.get("function", tool)
            result.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object"}),
            })
        return result

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        """Generate streaming response from Anthropic.

        Args:
            messages: Conversation history.
            system_prompt: Optional system prompt.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate.
            stop: Optional list of stop sequences.
            **kwargs: Additional Anthropic API parameters.

        Yields:
            LLMChunk objects with text tokens.

        Raises:
            RuntimeError: If client is not connected.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Convert messages
        anthropic_messages = self._convert_messages_to_anthropic(messages)

        # Build request
        request_kwargs: dict[str, Any] = {
            "model": self._llm_config.model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or self._llm_config.default_max_tokens,
        }

        # Add system prompt
        effective_system_prompt = (
            system_prompt or self._llm_config.default_system_prompt
        )
        if effective_system_prompt:
            request_kwargs["system"] = effective_system_prompt

        if stop:
            request_kwargs["stop_sequences"] = stop

        # Add any extra kwargs
        request_kwargs.update(kwargs)

        # Track timing
        start_time = time.perf_counter()
        finish_reason = None

        try:
            async with self._async_client.messages.stream(
                **request_kwargs
            ) as stream:
                async for text in stream.text_stream:
                    yield LLMChunk(text=text, is_final=False)

                # Get final message for stats
                message = await stream.get_final_message()
                finish_reason = message.stop_reason

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
            stop: Optional list of stop sequences.
            **kwargs: Additional parameters.

        Returns:
            Complete response text.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Convert messages
        anthropic_messages = self._convert_messages_to_anthropic(messages)

        # Build request
        request_kwargs: dict[str, Any] = {
            "model": self._llm_config.model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or self._llm_config.default_max_tokens,
        }

        # Add system prompt
        effective_system_prompt = (
            system_prompt or self._llm_config.default_system_prompt
        )
        if effective_system_prompt:
            request_kwargs["system"] = effective_system_prompt

        if stop:
            request_kwargs["stop_sequences"] = stop

        request_kwargs.update(kwargs)

        start_time = time.perf_counter()

        try:
            response = await self._async_client.messages.create(**request_kwargs)

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            # Extract text content
            text_blocks = [
                block.text
                for block in response.content
                if block.type == "text"
            ]
            return "".join(text_blocks)

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
            tool_choice: Tool selection mode ("auto", "none", "any").
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters.

        Returns:
            LLMResponse with content and/or tool_calls.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Convert messages and tools
        anthropic_messages = self._convert_messages_to_anthropic(messages)
        anthropic_tools = self._convert_tools_to_anthropic(tools)

        # Build request
        request_kwargs: dict[str, Any] = {
            "model": self._llm_config.model,
            "messages": anthropic_messages,
            "tools": anthropic_tools,
            "temperature": temperature,
            "max_tokens": max_tokens or self._llm_config.default_max_tokens,
        }

        # Add system prompt
        effective_system_prompt = (
            system_prompt or self._llm_config.default_system_prompt
        )
        if effective_system_prompt:
            request_kwargs["system"] = effective_system_prompt

        # Map tool_choice to Anthropic format
        if tool_choice == "none":
            # Don't pass tools at all
            del request_kwargs["tools"]
        elif tool_choice == "required":
            request_kwargs["tool_choice"] = {"type": "any"}
        # "auto" is the default

        if kwargs.get("stop"):
            request_kwargs["stop_sequences"] = kwargs.pop("stop")

        request_kwargs.update(kwargs)

        start_time = time.perf_counter()

        try:
            response = await self._async_client.messages.create(**request_kwargs)

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            # Extract content and tool calls
            text_content = ""
            tool_calls = []

            for block in response.content:
                if block.type == "text":
                    text_content += block.text
                elif block.type == "tool_use":
                    # Convert to OpenAI format
                    import json
                    tool_calls.append({
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": json.dumps(block.input),
                        },
                    })

            # Map stop_reason to finish_reason
            finish_reason = response.stop_reason
            if finish_reason == "tool_use":
                finish_reason = "tool_calls"
            elif finish_reason == "end_turn":
                finish_reason = "stop"

            return LLMResponse(
                content=text_content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage={
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                } if response.usage else None,
            )

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    async def generate_stream_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        """Generate streaming response with tool calling support.

        Uses Anthropic's streaming API to yield text tokens as they arrive.
        Tool calls are accumulated and yielded at the end.

        Args:
            messages: Conversation history.
            tools: List of tool schemas in OpenAI format.
            system_prompt: Optional system prompt.
            tool_choice: Tool selection mode.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters.

        Yields:
            LLMChunk objects with text and/or tool_calls_delta.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Convert messages and tools
        anthropic_messages = self._convert_messages_to_anthropic(messages)
        anthropic_tools = self._convert_tools_to_anthropic(tools)

        # Build request
        request_kwargs: dict[str, Any] = {
            "model": self._llm_config.model,
            "messages": anthropic_messages,
            "tools": anthropic_tools,
            "temperature": temperature,
            "max_tokens": max_tokens or self._llm_config.default_max_tokens,
        }

        # Add system prompt
        effective_system_prompt = (
            system_prompt or self._llm_config.default_system_prompt
        )
        if effective_system_prompt:
            request_kwargs["system"] = effective_system_prompt

        # Map tool_choice to Anthropic format
        if tool_choice == "none":
            del request_kwargs["tools"]
        elif tool_choice == "required":
            request_kwargs["tool_choice"] = {"type": "any"}

        if kwargs.get("stop"):
            request_kwargs["stop_sequences"] = kwargs.pop("stop")

        request_kwargs.update(kwargs)

        start_time = time.perf_counter()
        finish_reason = None

        # Track tool calls being built
        current_tool_calls: dict[int, dict[str, Any]] = {}
        current_tool_index = -1

        try:
            async with self._async_client.messages.stream(
                **request_kwargs
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            current_tool_index += 1
                            current_tool_calls[current_tool_index] = {
                                "id": block.id,
                                "type": "function",
                                "function": {
                                    "name": block.name,
                                    "arguments": "",
                                },
                            }
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield LLMChunk(text=delta.text)
                        elif delta.type == "input_json_delta":
                            # Accumulate JSON for tool arguments
                            if current_tool_index >= 0:
                                current_tool_calls[current_tool_index]["function"]["arguments"] += delta.partial_json
                    elif event.type == "message_stop":
                        pass

                # Get final message
                message = await stream.get_final_message()
                finish_reason = message.stop_reason

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            # If there were tool calls, yield them as final chunk
            if current_tool_calls:
                sorted_calls = [
                    current_tool_calls[i]
                    for i in sorted(current_tool_calls.keys())
                ]
                yield LLMChunk(
                    text="",
                    tool_calls_delta=sorted_calls,
                    finish_reason="tool_calls",
                    is_final=True,
                )
            else:
                yield LLMChunk(
                    text="",
                    is_final=True,
                    finish_reason="stop" if finish_reason == "end_turn" else finish_reason,
                )

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    def supports_tools(self) -> bool:
        """Check if this LLM supports tool calling.

        Returns:
            True - Anthropic Claude models support tool calling.
        """
        return True

    def _handle_error(self, error: Exception) -> None:
        """Convert Anthropic errors to provider errors.

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
            "overloaded",
            "timeout",
            "connection",
            "server error",
            "503",
            "502",
            "500",
            "529",  # Anthropic overloaded
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
            f"AnthropicLLMProvider("
            f"model={self._llm_config.model!r}, "
            f"connected={self._connected})"
        )
