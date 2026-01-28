"""Ollama LLM provider.

Ollama is a local LLM runtime for running open-source models.
Supports Llama 3.2, Mistral, Gemma, Qwen, and many other models.

Reference: https://github.com/ollama/ollama/blob/main/docs/api.md
"""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from voice_pipeline.interfaces.llm import LLMChunk, LLMInterface, LLMResponse

logger = logging.getLogger(__name__)
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)
from voice_pipeline.providers.decorators import register_llm
from voice_pipeline.providers.types import LLMCapabilities


@dataclass
class OllamaLLMConfig(ProviderConfig):
    """Configuration for Ollama LLM provider.

    Attributes:
        model: Model to use (llama3.2, mistral, gemma2, qwen2.5, etc.).
        base_url: Ollama server URL. Defaults to http://localhost:11434.
        format: Response format (None or "json").
        keep_alive: How long to keep model loaded (e.g., "5m", "1h", "-1" for forever).
        num_ctx: Context window size (default: 2048).
        num_predict: Max tokens to generate (default: 128).
        temperature: Sampling temperature (0.0 to 2.0).
        top_p: Top-p sampling (0.0 to 1.0).
        top_k: Top-k sampling.
        repeat_penalty: Repetition penalty.
        seed: Random seed for reproducibility.

    Example:
        >>> config = OllamaLLMConfig(
        ...     model="llama3.2",
        ...     base_url="http://localhost:11434",
        ...     temperature=0.7,
        ... )
        >>> llm = OllamaLLMProvider(config=config)
    """

    model: str = "qwen2.5:0.5b"
    """Model to use (qwen2.5:0.5b, llama3.2, mistral, gemma2, etc.)."""

    base_url: str = "http://localhost:11434"
    """Ollama server URL. Defaults to localhost."""

    format: Optional[str] = None
    """Response format: None (default) or 'json' for JSON mode."""

    keep_alive: str = "5m"
    """How long to keep model loaded after request. Use '-1' for forever."""

    # Model options (passed to Ollama)
    num_ctx: int = 2048
    """Context window size in tokens."""

    num_predict: int = 128
    """Maximum number of tokens to generate."""

    temperature: float = 0.7
    """Sampling temperature (0.0 to 2.0). Higher = more creative."""

    top_p: float = 0.9
    """Top-p (nucleus) sampling. Lower = more focused."""

    top_k: int = 40
    """Top-k sampling. Lower = more focused."""

    repeat_penalty: float = 1.1
    """Penalty for repeating tokens. Higher = less repetition."""

    seed: Optional[int] = None
    """Random seed for reproducibility."""

    default_system_prompt: Optional[str] = None
    """Default system prompt to use if none provided."""

    auto_pull: bool = True
    """Automatically download model if not available locally.
    Set to False to prevent automatic downloads in production."""

    def get_model_options(self) -> dict[str, Any]:
        """Get Ollama model options dict.

        Returns:
            Dict with model options for Ollama API.
        """
        options = {
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
        }
        if self.seed is not None:
            options["seed"] = self.seed
        return options


@register_llm(
    name="ollama",
    capabilities=LLMCapabilities(
        streaming=True,
        function_calling=True,
        system_prompt=True,
        context_window=4096,
        max_output_tokens=2048,
    ),
    description="Ollama local LLM provider for running open-source models locally.",
    version="1.0.0",
    aliases=["ollama-llm", "local-llm"],
    tags=["local", "offline", "llama", "mistral", "gemma", "qwen"],
    default_config={
        "model": "qwen2.5:0.5b",
        "base_url": "http://localhost:11434",
    },
)
class OllamaLLMProvider(BaseProvider, LLMInterface):
    """Ollama LLM provider for local model inference.

    Uses Ollama's REST API for text generation.
    Supports streaming for low-latency voice applications.

    Features:
    - Streaming text generation
    - Tool/function calling support (Ollama 0.4+)
    - Multiple models (Llama, Mistral, Gemma, etc.)
    - Configurable parameters (temperature, top_p, etc.)
    - Automatic retry with exponential backoff
    - No API key required (local server)

    Example:
        >>> llm = OllamaLLMProvider(
        ...     model="llama3.2",
        ...     base_url="http://localhost:11434",
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
        provider_name: "ollama-llm"
        name: "OllamaLLM" (for VoiceRunnable)
    """

    provider_name: str = "ollama-llm"
    name: str = "OllamaLLM"

    def __init__(
        self,
        config: Optional[OllamaLLMConfig] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
        keep_alive: Optional[str] = None,
        **kwargs,
    ):
        """Initialize Ollama LLM provider.

        Args:
            config: Full configuration object.
            model: Model to use (shortcut).
            base_url: Ollama server URL (shortcut).
            temperature: Default temperature (shortcut).
            keep_alive: How long to keep model loaded (shortcut).
                        Use "-1" for forever (recommended for voice agents).
            **kwargs: Additional configuration options.
        """
        # Build config from parameters
        if config is None:
            config = OllamaLLMConfig()

        # Apply shortcuts
        if model is not None:
            config.model = model
        if base_url is not None:
            config.base_url = base_url
        if temperature is not None:
            config.temperature = temperature
        if keep_alive is not None:
            config.keep_alive = keep_alive

        # Check for env var override
        env_base_url = os.environ.get("OLLAMA_HOST")
        if env_base_url and base_url is None:
            config.base_url = env_base_url

        super().__init__(config=config, **kwargs)

        self._llm_config: OllamaLLMConfig = config
        self._client = None
        self._async_client = None

    @staticmethod
    def _parse_keep_alive(value: str):
        """Convert keep_alive string to the format Ollama expects.

        Ollama accepts either:
        - Go duration strings: "5m", "1h", "300s"
        - Integers (nanoseconds): -1 (forever), 0 (unload immediately)

        The string "-1" is NOT a valid Go duration (needs a unit suffix).
        This method converts pure numeric strings to integers.

        Returns:
            int if the value is a pure number, otherwise the original string.
        """
        try:
            return int(value)
        except ValueError:
            return value

    async def connect(self) -> None:
        """Initialize HTTP client and ensure model is available.

        This method:
        1. Creates HTTP clients
        2. Checks if Ollama server is running
        3. Checks if model exists locally
        4. Downloads model automatically if not found
        """
        await super().connect()

        try:
            import httpx
        except ImportError:
            raise ImportError(
                "httpx is required for Ollama LLM. "
                "Install with: pip install httpx"
            )

        # Create HTTP clients
        timeout = httpx.Timeout(
            connect=10.0,
            read=self._llm_config.timeout,
            write=10.0,
            pool=5.0,
        )

        self._client = httpx.Client(
            base_url=self._llm_config.base_url,
            timeout=timeout,
        )
        self._async_client = httpx.AsyncClient(
            base_url=self._llm_config.base_url,
            timeout=timeout,
        )

        # Ensure Ollama server is running and model is available
        await self._ensure_model_available()

    async def disconnect(self) -> None:
        """Close HTTP clients."""
        if self._async_client:
            await self._async_client.aclose()
        if self._client:
            self._client.close()
        self._async_client = None
        self._client = None
        await super().disconnect()

    async def _ensure_model_available(self) -> None:
        """Ensure Ollama server is running and model is available.

        Automatically downloads the model if not found locally.

        Raises:
            ConnectionError: If Ollama server is not running.
        """
        # Check if server is running
        try:
            response = await self._async_client.get("/api/tags")
            response.raise_for_status()
        except Exception as e:
            raise ConnectionError(
                f"Ollama server not running at {self._llm_config.base_url}. "
                f"Start with: ollama serve\n"
                f"Error: {e}"
            ) from e

        # Check if model exists
        data = response.json()
        models = [m.get("name", "") for m in data.get("models", [])]

        model_exists = any(
            self._llm_config.model in m or m.startswith(self._llm_config.model)
            for m in models
        )

        if not model_exists:
            if not self._llm_config.auto_pull:
                raise RuntimeError(
                    f"Model '{self._llm_config.model}' not found locally and "
                    f"auto_pull is disabled. Pull it manually: ollama pull {self._llm_config.model}"
                )
            logger.info(f"Model '{self._llm_config.model}' not found. Downloading...")
            await self._pull_model_with_progress()
            logger.info(f"Model '{self._llm_config.model}' ready!")

    async def _pull_model_with_progress(self) -> None:
        """Download model with progress logging."""
        import json

        try:
            async with self._async_client.stream(
                "POST",
                "/api/pull",
                json={"name": self._llm_config.model, "stream": True},
                timeout=None,  # Download can take a long time
            ) as response:
                response.raise_for_status()

                last_status = ""
                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    status = data.get("status", "")

                    # Log progress
                    if status != last_status:
                        if "pulling" in status:
                            total = data.get("total", 0)
                            completed = data.get("completed", 0)
                            if total > 0:
                                pct = (completed / total) * 100
                                size_mb = total / (1024 * 1024)
                                logger.info(
                                    f"Downloading {self._llm_config.model}: "
                                    f"{pct:.1f}% of {size_mb:.1f}MB"
                                )
                        elif status:
                            logger.info(f"Ollama: {status}")
                        last_status = status

        except Exception as e:
            raise RuntimeError(
                f"Failed to download model '{self._llm_config.model}': {e}"
            ) from e

    async def warmup(self) -> float:
        """Warm up the model by sending a minimal prompt.

        This loads the model into memory and eliminates cold start
        latency on the first real request. The response is discarded.

        Returns:
            Warmup time in milliseconds.

        Raises:
            RuntimeError: If client is not connected.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        start_time = time.perf_counter()

        request_body = {
            "model": self._llm_config.model,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "options": {"num_predict": 1},
        }

        if self._llm_config.keep_alive:
            request_body["keep_alive"] = self._parse_keep_alive(self._llm_config.keep_alive)

        try:
            response = await self._async_client.post(
                "/api/chat",
                json=request_body,
            )
            response.raise_for_status()
        except Exception as e:
            logger.warning(f"LLM warmup failed: {e}")
            # Non-fatal: warmup is best-effort

        warmup_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"LLM warmup completed in {warmup_ms:.1f}ms "
            f"(model={self._llm_config.model}, keep_alive={self._llm_config.keep_alive})"
        )
        return warmup_ms

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if Ollama server is accessible and model is available."""
        if self._async_client is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Client not initialized. Call connect() first.",
            )

        try:
            # Check server is running
            response = await self._async_client.get("/api/tags")
            response.raise_for_status()

            # Parse available models
            data = response.json()
            models = [m.get("name", "") for m in data.get("models", [])]

            # Check if our model is available
            model_available = any(
                self._llm_config.model in m for m in models
            )

            if not model_available:
                return HealthCheckResult(
                    status=ProviderHealth.DEGRADED,
                    message=f"Model '{self._llm_config.model}' not found. "
                    f"Available: {models[:5]}. "
                    f"Run: ollama pull {self._llm_config.model}",
                    details={"available_models": models},
                )

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"Ollama server accessible. Model: {self._llm_config.model}",
                details={
                    "model": self._llm_config.model,
                    "available_models": models,
                },
            )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"Ollama server error: {e}. Is Ollama running?",
            )

    async def list_models(self) -> list[str]:
        """List available models on the Ollama server.

        Returns:
            List of model names.

        Raises:
            RuntimeError: If client not connected.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        response = await self._async_client.get("/api/tags")
        response.raise_for_status()
        data = response.json()
        return [m.get("name", "") for m in data.get("models", [])]

    async def pull_model(self, model: Optional[str] = None) -> None:
        """Pull/download a model from Ollama registry.

        Args:
            model: Model name to pull. Defaults to configured model.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        target_model = model or self._llm_config.model

        response = await self._async_client.post(
            "/api/pull",
            json={"name": target_model},
        )
        response.raise_for_status()

    def _build_messages(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> list[dict[str, str]]:
        """Build message list with optional system prompt.

        Args:
            messages: User messages.
            system_prompt: Optional system prompt.

        Returns:
            Complete message list.
        """
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
        return full_messages

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        """Generate streaming response from Ollama.

        Args:
            messages: Conversation history.
            system_prompt: Optional system prompt.
            temperature: Sampling temperature (overrides config).
            max_tokens: Maximum tokens to generate (overrides config).
            **kwargs: Additional Ollama API parameters.

        Yields:
            LLMChunk objects with text tokens.

        Raises:
            RuntimeError: If client is not connected.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Build request
        full_messages = self._build_messages(messages, system_prompt)

        # Build options
        options = self._llm_config.get_model_options()
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if stop:
            options["stop"] = stop

        request_body = {
            "model": self._llm_config.model,
            "messages": full_messages,
            "stream": True,
            "options": options,
        }

        if self._llm_config.format:
            request_body["format"] = self._llm_config.format

        if self._llm_config.keep_alive:
            request_body["keep_alive"] = self._parse_keep_alive(self._llm_config.keep_alive)

        # Add extra kwargs
        request_body.update(kwargs)

        # Track timing
        start_time = time.perf_counter()
        total_text = ""

        try:
            async with self._async_client.stream(
                "POST",
                "/api/chat",
                json=request_body,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        import json
                        chunk_data = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    # Extract message content
                    message = chunk_data.get("message", {})
                    text = message.get("content", "")

                    if text:
                        total_text += text
                        yield LLMChunk(
                            text=text,
                            is_final=False,
                        )

                    # Check if done
                    if chunk_data.get("done", False):
                        break

            # Final chunk with stats
            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            yield LLMChunk(
                text="",
                is_final=True,
                finish_reason="stop",
            )

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    async def generate(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
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

        # Build request
        full_messages = self._build_messages(messages, system_prompt)

        options = self._llm_config.get_model_options()
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if stop:
            options["stop"] = stop

        request_body = {
            "model": self._llm_config.model,
            "messages": full_messages,
            "stream": False,
            "options": options,
        }

        if self._llm_config.format:
            request_body["format"] = self._llm_config.format

        if self._llm_config.keep_alive:
            request_body["keep_alive"] = self._parse_keep_alive(self._llm_config.keep_alive)

        request_body.update(kwargs)

        start_time = time.perf_counter()

        try:
            response = await self._async_client.post(
                "/api/chat",
                json=request_body,
            )
            response.raise_for_status()

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            data = response.json()
            message = data.get("message", {})
            return message.get("content", "")

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
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        """Generate response with tool calling support.

        Ollama supports tool calling since version 0.4.0.

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

        # Build request
        full_messages = self._build_messages(messages, system_prompt)

        options = self._llm_config.get_model_options()
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if kwargs.get("stop"):
            options["stop"] = kwargs.pop("stop")

        request_body = {
            "model": self._llm_config.model,
            "messages": full_messages,
            "stream": False,
            "options": options,
            "tools": tools,
        }

        if self._llm_config.format:
            request_body["format"] = self._llm_config.format

        if self._llm_config.keep_alive:
            request_body["keep_alive"] = self._parse_keep_alive(self._llm_config.keep_alive)

        request_body.update(kwargs)

        start_time = time.perf_counter()

        try:
            response = await self._async_client.post(
                "/api/chat",
                json=request_body,
            )
            response.raise_for_status()

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            data = response.json()
            message = data.get("message", {})

            # Extract tool calls (Ollama format)
            tool_calls = []
            ollama_tool_calls = message.get("tool_calls", [])

            for i, tc in enumerate(ollama_tool_calls):
                func = tc.get("function", {})
                tool_calls.append({
                    "id": f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": func.get("name", ""),
                        "arguments": func.get("arguments", "{}"),
                    },
                })

            return LLMResponse(
                content=message.get("content", ""),
                tool_calls=tool_calls,
                finish_reason="tool_calls" if tool_calls else "stop",
                usage=None,  # Ollama doesn't return usage stats in same format
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
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        """Generate streaming response with tool calling support.

        Uses Ollama's streaming API to yield text tokens as they arrive.
        Tool calls are detected at the end of the stream and yielded together.

        Note: Ollama streams text tokens but tool calls only appear in the
        final chunk. This still provides significant latency improvements
        for text responses compared to non-streaming.

        Args:
            messages: Conversation history (may include tool results).
            tools: List of tool schemas in OpenAI format.
            system_prompt: Optional system prompt.
            tool_choice: Tool selection mode (Ollama ignores this).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters.

        Yields:
            LLMChunk objects with text and/or tool_calls_delta.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Build request
        full_messages = self._build_messages(messages, system_prompt)

        options = self._llm_config.get_model_options()
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if kwargs.get("stop"):
            options["stop"] = kwargs.pop("stop")

        request_body = {
            "model": self._llm_config.model,
            "messages": full_messages,
            "stream": True,  # Enable streaming!
            "options": options,
            "tools": tools,
        }

        if self._llm_config.format:
            request_body["format"] = self._llm_config.format

        if self._llm_config.keep_alive:
            request_body["keep_alive"] = self._parse_keep_alive(self._llm_config.keep_alive)

        request_body.update(kwargs)

        start_time = time.perf_counter()
        collected_text: list[str] = []
        collected_tool_calls: list[dict] = []

        try:
            async with self._async_client.stream(
                "POST",
                "/api/chat",
                json=request_body,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        import json
                        chunk_data = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    message = chunk_data.get("message", {})

                    # Stream text immediately
                    text = message.get("content", "")
                    if text:
                        collected_text.append(text)
                        yield LLMChunk(
                            text=text,
                            is_final=False,
                        )

                    # Check for tool calls (usually in final chunk)
                    ollama_tool_calls = message.get("tool_calls", [])
                    if ollama_tool_calls:
                        for i, tc in enumerate(ollama_tool_calls):
                            func = tc.get("function", {})
                            collected_tool_calls.append({
                                "id": f"call_{i}",
                                "type": "function",
                                "function": {
                                    "name": func.get("name", ""),
                                    "arguments": func.get("arguments", "{}"),
                                },
                            })

                    # Check if done
                    if chunk_data.get("done", False):
                        break

            # Record metrics
            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            # Yield final chunk with tool calls if any
            if collected_tool_calls:
                yield LLMChunk(
                    text="",
                    tool_calls_delta=collected_tool_calls,
                    finish_reason="tool_calls",
                    is_final=True,
                )
            else:
                yield LLMChunk(
                    text="",
                    finish_reason="stop",
                    is_final=True,
                )

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    def supports_tools(self) -> bool:
        """Check if this LLM supports tool calling.

        Returns:
            True - Ollama 0.4+ supports tool calling.
        """
        return True

    def _handle_error(self, error: Exception) -> None:
        """Convert Ollama errors to provider errors.

        Args:
            error: Original exception.

        Raises:
            RetryableError: For transient errors.
            NonRetryableError: For permanent errors.
        """
        error_str = str(error).lower()

        # Retryable errors
        if any(x in error_str for x in [
            "connection",
            "timeout",
            "server error",
            "503",
            "502",
            "500",
            "temporarily unavailable",
            "connection refused",
        ]):
            raise RetryableError(str(error)) from error

        # Non-retryable errors
        if any(x in error_str for x in [
            "model not found",
            "invalid",
            "not found",
            "404",
            "400",
        ]):
            raise NonRetryableError(str(error)) from error

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"OllamaLLMProvider("
            f"model={self._llm_config.model!r}, "
            f"base_url={self._llm_config.base_url!r}, "
            f"connected={self._connected})"
        )
