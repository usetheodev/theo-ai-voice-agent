"""Tests for Ollama LLM provider."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from voice_pipeline.interfaces.llm import LLMChunk, LLMResponse
from voice_pipeline.providers.base import (
    HealthCheckResult,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)
from voice_pipeline.providers.llm import OllamaLLMProvider, OllamaLLMConfig


class TestOllamaLLMConfig:
    """Tests for OllamaLLMConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = OllamaLLMConfig()

        assert config.model == "qwen2.5:0.5b"
        assert config.base_url == "http://localhost:11434"
        assert config.format is None
        assert config.keep_alive == "5m"
        assert config.num_ctx == 2048
        assert config.num_predict == 128
        assert config.temperature == 0.7
        assert config.top_p == 0.9
        assert config.top_k == 40
        assert config.repeat_penalty == 1.1
        assert config.seed is None
        assert config.default_system_prompt is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = OllamaLLMConfig(
            model="mistral",
            base_url="http://remote-ollama:11434",
            format="json",
            keep_alive="1h",
            num_ctx=4096,
            num_predict=256,
            temperature=0.5,
            top_p=0.8,
            top_k=50,
            repeat_penalty=1.2,
            seed=42,
            default_system_prompt="You are a helpful assistant.",
        )

        assert config.model == "mistral"
        assert config.base_url == "http://remote-ollama:11434"
        assert config.format == "json"
        assert config.keep_alive == "1h"
        assert config.num_ctx == 4096
        assert config.num_predict == 256
        assert config.temperature == 0.5
        assert config.top_p == 0.8
        assert config.top_k == 50
        assert config.repeat_penalty == 1.2
        assert config.seed == 42
        assert config.default_system_prompt == "You are a helpful assistant."

    def test_get_model_options(self):
        """Test model options generation."""
        config = OllamaLLMConfig(
            temperature=0.8,
            top_p=0.95,
            top_k=30,
            seed=123,
        )

        options = config.get_model_options()

        assert options["temperature"] == 0.8
        assert options["top_p"] == 0.95
        assert options["top_k"] == 30
        assert options["seed"] == 123
        assert "num_ctx" in options
        assert "num_predict" in options
        assert "repeat_penalty" in options

    def test_get_model_options_without_seed(self):
        """Test model options without seed."""
        config = OllamaLLMConfig()

        options = config.get_model_options()

        assert "seed" not in options


class TestOllamaLLMProviderInit:
    """Tests for OllamaLLMProvider initialization."""

    def test_default_initialization(self):
        """Test provider with default config."""
        provider = OllamaLLMProvider()

        assert provider.provider_name == "ollama-llm"
        assert provider.name == "OllamaLLM"
        assert provider._llm_config.model == "qwen2.5:0.5b"
        assert provider._llm_config.base_url == "http://localhost:11434"
        assert provider.is_connected is False

    def test_initialization_with_config(self):
        """Test provider with custom config."""
        config = OllamaLLMConfig(
            model="mistral",
            base_url="http://custom:11434",
        )
        provider = OllamaLLMProvider(config=config)

        assert provider._llm_config.model == "mistral"
        assert provider._llm_config.base_url == "http://custom:11434"

    def test_initialization_with_shortcuts(self):
        """Test provider with shortcut parameters."""
        provider = OllamaLLMProvider(
            model="gemma2",
            base_url="http://remote:11434",
            temperature=0.3,
        )

        assert provider._llm_config.model == "gemma2"
        assert provider._llm_config.base_url == "http://remote:11434"
        assert provider._llm_config.temperature == 0.3

    def test_shortcuts_override_config(self):
        """Test that shortcuts override config values."""
        config = OllamaLLMConfig(model="llama3.2", base_url="http://config:11434")
        provider = OllamaLLMProvider(
            config=config,
            model="mistral",
            base_url="http://shortcut:11434",
        )

        assert provider._llm_config.model == "mistral"
        assert provider._llm_config.base_url == "http://shortcut:11434"

    def test_env_var_override(self, monkeypatch):
        """Test OLLAMA_HOST environment variable override."""
        monkeypatch.setenv("OLLAMA_HOST", "http://env-ollama:11434")
        provider = OllamaLLMProvider()

        assert provider._llm_config.base_url == "http://env-ollama:11434"

    def test_explicit_url_overrides_env(self, monkeypatch):
        """Test that explicit base_url overrides env var."""
        monkeypatch.setenv("OLLAMA_HOST", "http://env-ollama:11434")
        provider = OllamaLLMProvider(base_url="http://explicit:11434")

        assert provider._llm_config.base_url == "http://explicit:11434"

    def test_repr(self):
        """Test string representation."""
        provider = OllamaLLMProvider(model="mistral")
        repr_str = repr(provider)

        assert "OllamaLLMProvider" in repr_str
        assert "mistral" in repr_str
        assert "localhost:11434" in repr_str
        assert "connected=False" in repr_str


class TestOllamaLLMProviderLifecycle:
    """Tests for provider lifecycle (connect/disconnect)."""

    @pytest.mark.asyncio
    async def test_connect_creates_clients(self):
        """Test that connect creates HTTP clients."""
        provider = OllamaLLMProvider()

        with patch("httpx.Client") as mock_sync:
            with patch("httpx.AsyncClient") as mock_async:
                mock_sync_instance = MagicMock()
                mock_async_instance = MagicMock()

                # Mock the async get method for _ensure_model_available
                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "models": [{"name": "qwen2.5:0.5b"}]
                }
                mock_response.raise_for_status = MagicMock()
                mock_async_instance.get = AsyncMock(return_value=mock_response)

                mock_sync.return_value = mock_sync_instance
                mock_async.return_value = mock_async_instance

                await provider.connect()

                mock_sync.assert_called_once()
                mock_async.assert_called_once()
                assert provider.is_connected is True
                assert provider._client is mock_sync_instance
                assert provider._async_client is mock_async_instance

    @pytest.mark.asyncio
    async def test_connect_with_custom_url(self):
        """Test connect with custom base URL."""
        provider = OllamaLLMProvider(base_url="http://custom:11434")

        with patch("httpx.Client") as mock_sync:
            with patch("httpx.AsyncClient") as mock_async:
                # Mock async client for _ensure_model_available
                mock_async_instance = MagicMock()
                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "models": [{"name": "qwen2.5:0.5b"}]
                }
                mock_response.raise_for_status = MagicMock()
                mock_async_instance.get = AsyncMock(return_value=mock_response)
                mock_async.return_value = mock_async_instance

                await provider.connect()

                # Check that custom URL was passed
                call_kwargs = mock_async.call_args[1]
                assert call_kwargs["base_url"] == "http://custom:11434"

    @pytest.mark.asyncio
    async def test_connect_raises_without_httpx(self):
        """Test that connect raises ImportError without httpx package."""
        provider = OllamaLLMProvider()

        with patch.dict("sys.modules", {"httpx": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("No module named 'httpx'"),
            ):
                with pytest.raises(ImportError, match="httpx is required"):
                    await provider.connect()

    @pytest.mark.asyncio
    async def test_disconnect_closes_clients(self):
        """Test that disconnect closes the clients."""
        provider = OllamaLLMProvider()

        mock_async_client = AsyncMock()
        mock_sync_client = MagicMock()
        provider._async_client = mock_async_client
        provider._client = mock_sync_client
        provider._connected = True

        await provider.disconnect()

        mock_async_client.aclose.assert_called_once()
        mock_sync_client.close.assert_called_once()
        assert provider._async_client is None
        assert provider._client is None
        assert provider.is_connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        provider = OllamaLLMProvider()

        with patch("httpx.Client"):
            with patch("httpx.AsyncClient") as mock_async:
                mock_client = AsyncMock()
                # Mock the async get method for _ensure_model_available
                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "models": [{"name": "qwen2.5:0.5b"}]
                }
                mock_response.raise_for_status = MagicMock()
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_async.return_value = mock_client

                async with provider as p:
                    assert p.is_connected is True

                assert provider.is_connected is False


class TestOllamaLLMProviderHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_when_not_connected(self):
        """Test health check returns unhealthy when not connected."""
        provider = OllamaLLMProvider()

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "not initialized" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_when_model_available(self):
        """Test health check returns healthy when model is available."""
        provider = OllamaLLMProvider(model="llama3.2")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3.2:latest"},
                {"name": "mistral:latest"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.health_check()

        assert result.status == ProviderHealth.HEALTHY
        assert "llama3.2" in result.message
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_health_check_degraded_when_model_not_found(self):
        """Test health check returns degraded when model not found."""
        provider = OllamaLLMProvider(model="nonexistent-model")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3.2:latest"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.health_check()

        assert result.status == ProviderHealth.DEGRADED
        assert "not found" in result.message.lower()
        assert "ollama pull" in result.message

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_connection_error(self):
        """Test health check returns unhealthy on connection error."""
        provider = OllamaLLMProvider()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        provider._async_client = mock_client

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "ollama running" in result.message.lower()


class TestOllamaLLMProviderListModels:
    """Tests for list_models functionality."""

    @pytest.mark.asyncio
    async def test_list_models_raises_without_client(self):
        """Test list_models raises error when not connected."""
        provider = OllamaLLMProvider()

        with pytest.raises(RuntimeError, match="not connected"):
            await provider.list_models()

    @pytest.mark.asyncio
    async def test_list_models_returns_model_names(self):
        """Test list_models returns available model names."""
        provider = OllamaLLMProvider()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3.2:latest"},
                {"name": "mistral:7b"},
                {"name": "gemma2:2b"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        models = await provider.list_models()

        assert "llama3.2:latest" in models
        assert "mistral:7b" in models
        assert "gemma2:2b" in models
        assert len(models) == 3


class TestOllamaLLMProviderGenerateStream:
    """Tests for streaming text generation."""

    @pytest.mark.asyncio
    async def test_generate_stream_raises_without_client(self):
        """Test generate_stream raises error when not connected."""
        provider = OllamaLLMProvider()

        with pytest.raises(RuntimeError, match="not connected"):
            async for _ in provider.generate_stream(
                messages=[{"role": "user", "content": "Hello"}]
            ):
                pass

    @pytest.mark.asyncio
    async def test_generate_stream_basic(self):
        """Test basic streaming generation."""
        provider = OllamaLLMProvider()

        # Create mock streaming response
        async def mock_aiter_lines():
            yield json.dumps({"message": {"content": "Hello"}, "done": False})
            yield json.dumps({"message": {"content": " World"}, "done": False})
            yield json.dumps({"message": {"content": "!"}, "done": True})

        mock_response = AsyncMock()
        mock_response.aiter_lines = mock_aiter_lines
        mock_response.raise_for_status = MagicMock()

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_context.__aexit__.return_value = None

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_context)
        provider._async_client = mock_client

        chunks = []
        async for chunk in provider.generate_stream(
            messages=[{"role": "user", "content": "Hi"}]
        ):
            chunks.append(chunk)

        # Should have 4 chunks: "Hello", " World", "!", and final
        assert len(chunks) == 4
        assert chunks[0].text == "Hello"
        assert chunks[1].text == " World"
        assert chunks[2].text == "!"
        assert chunks[3].is_final is True
        assert chunks[3].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_generate_stream_with_system_prompt(self):
        """Test streaming with system prompt."""
        provider = OllamaLLMProvider()

        async def mock_aiter_lines():
            yield json.dumps({"message": {"content": "Arrr!"}, "done": True})

        mock_response = AsyncMock()
        mock_response.aiter_lines = mock_aiter_lines
        mock_response.raise_for_status = MagicMock()

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_context.__aexit__.return_value = None

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_context)
        provider._async_client = mock_client

        chunks = []
        async for chunk in provider.generate_stream(
            messages=[{"role": "user", "content": "Hi"}],
            system_prompt="You are a pirate.",
        ):
            chunks.append(chunk)

        # Check that system prompt was included in request
        call_kwargs = mock_client.stream.call_args[1]
        request_body = call_kwargs["json"]
        messages = request_body["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a pirate."

    @pytest.mark.asyncio
    async def test_generate_stream_uses_default_system_prompt(self):
        """Test streaming uses default system prompt from config."""
        config = OllamaLLMConfig(default_system_prompt="Default system prompt")
        provider = OllamaLLMProvider(config=config)

        async def mock_aiter_lines():
            yield json.dumps({"message": {"content": "Hi"}, "done": True})

        mock_response = AsyncMock()
        mock_response.aiter_lines = mock_aiter_lines
        mock_response.raise_for_status = MagicMock()

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_context.__aexit__.return_value = None

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_context)
        provider._async_client = mock_client

        chunks = []
        async for chunk in provider.generate_stream(
            messages=[{"role": "user", "content": "Hi"}]
        ):
            chunks.append(chunk)

        call_kwargs = mock_client.stream.call_args[1]
        request_body = call_kwargs["json"]
        messages = request_body["messages"]
        assert messages[0]["content"] == "Default system prompt"

    @pytest.mark.asyncio
    async def test_generate_stream_with_options(self):
        """Test streaming with custom options."""
        provider = OllamaLLMProvider()

        async def mock_aiter_lines():
            yield json.dumps({"message": {"content": "Hi"}, "done": True})

        mock_response = AsyncMock()
        mock_response.aiter_lines = mock_aiter_lines
        mock_response.raise_for_status = MagicMock()

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_context.__aexit__.return_value = None

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_context)
        provider._async_client = mock_client

        chunks = []
        async for chunk in provider.generate_stream(
            messages=[{"role": "user", "content": "Hi"}],
            temperature=0.5,
            max_tokens=200,
        ):
            chunks.append(chunk)

        call_kwargs = mock_client.stream.call_args[1]
        request_body = call_kwargs["json"]
        options = request_body["options"]
        assert options["temperature"] == 0.5
        assert options["num_predict"] == 200

    @pytest.mark.asyncio
    async def test_generate_stream_records_metrics(self):
        """Test that streaming records metrics."""
        provider = OllamaLLMProvider()

        async def mock_aiter_lines():
            yield json.dumps({"message": {"content": "Hi"}, "done": True})

        mock_response = AsyncMock()
        mock_response.aiter_lines = mock_aiter_lines
        mock_response.raise_for_status = MagicMock()

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_context.__aexit__.return_value = None

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_context)
        provider._async_client = mock_client

        async for _ in provider.generate_stream(
            messages=[{"role": "user", "content": "Hi"}]
        ):
            pass

        assert provider.metrics.successful_requests == 1
        assert provider.metrics.total_requests == 1


class TestOllamaLLMProviderGenerate:
    """Tests for non-streaming text generation."""

    @pytest.mark.asyncio
    async def test_generate_raises_without_client(self):
        """Test generate raises error when not connected."""
        provider = OllamaLLMProvider()

        with pytest.raises(RuntimeError, match="not connected"):
            await provider.generate(
                messages=[{"role": "user", "content": "Hello"}]
            )

    @pytest.mark.asyncio
    async def test_generate_basic(self):
        """Test basic non-streaming generation."""
        provider = OllamaLLMProvider()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Hello, how can I help?"}
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.generate(
            messages=[{"role": "user", "content": "Hi"}]
        )

        assert result == "Hello, how can I help?"

    @pytest.mark.asyncio
    async def test_generate_with_options(self):
        """Test generation with custom options."""
        provider = OllamaLLMProvider()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Response"}
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        await provider.generate(
            messages=[{"role": "user", "content": "Hi"}],
            temperature=0.3,
            max_tokens=100,
        )

        call_kwargs = mock_client.post.call_args[1]
        request_body = call_kwargs["json"]
        assert request_body["options"]["temperature"] == 0.3
        assert request_body["options"]["num_predict"] == 100
        assert request_body["stream"] is False


class TestOllamaLLMProviderToolCalling:
    """Tests for tool calling functionality."""

    def test_supports_tools(self):
        """Test that Ollama LLM supports tools."""
        provider = OllamaLLMProvider()
        assert provider.supports_tools() is True

    @pytest.mark.asyncio
    async def test_generate_with_tools_raises_without_client(self):
        """Test generate_with_tools raises error when not connected."""
        provider = OllamaLLMProvider()

        with pytest.raises(RuntimeError, match="not connected"):
            await provider.generate_with_tools(
                messages=[{"role": "user", "content": "What's the weather?"}],
                tools=[],
            )

    @pytest.mark.asyncio
    async def test_generate_with_tools_basic(self):
        """Test tool calling with tools."""
        provider = OllamaLLMProvider()

        # Mock response with tool call (Ollama format)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "Boston"}',
                        }
                    }
                ],
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"}
                        },
                        "required": ["location"],
                    },
                },
            }
        ]

        result = await provider.generate_with_tools(
            messages=[{"role": "user", "content": "What's the weather in Boston?"}],
            tools=tools,
        )

        assert isinstance(result, LLMResponse)
        assert result.has_tool_calls is True
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["function"]["name"] == "get_weather"
        assert result.finish_reason == "tool_calls"

    @pytest.mark.asyncio
    async def test_generate_with_tools_dict_arguments(self):
        """Test tool calling with arguments as dict (some Ollama versions)."""
        provider = OllamaLLMProvider()

        # Some Ollama versions return arguments as dict, not JSON string
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "calculate",
                            "arguments": {"expression": "2+2", "precision": 2},  # Dict, not string
                        }
                    }
                ],
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "Calculate an expression",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string"},
                            "precision": {"type": "integer"},
                        },
                        "required": ["expression"],
                    },
                },
            }
        ]

        result = await provider.generate_with_tools(
            messages=[{"role": "user", "content": "Calculate 2+2"}],
            tools=tools,
        )

        assert isinstance(result, LLMResponse)
        assert result.has_tool_calls is True
        assert len(result.tool_calls) == 1
        # Verify arguments are correctly parsed as dict
        args = result.tool_calls[0]["function"]["arguments"]
        assert args["expression"] == "2+2"
        assert args["precision"] == 2

    @pytest.mark.asyncio
    async def test_generate_with_tools_no_tool_call(self):
        """Test tool calling when LLM responds directly."""
        provider = OllamaLLMProvider()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {
                "content": "I don't have access to weather data.",
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.generate_with_tools(
            messages=[{"role": "user", "content": "Tell me a joke"}],
            tools=[],
        )

        assert result.has_tool_calls is False
        assert result.content == "I don't have access to weather data."
        assert result.finish_reason == "stop"


class TestOllamaLLMProviderErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_retryable_error_connection_refused(self):
        """Test connection refused error is retryable."""
        provider = OllamaLLMProvider()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
        provider._async_client = mock_client

        with pytest.raises(RetryableError):
            await provider.generate(
                messages=[{"role": "user", "content": "Hi"}]
            )

    @pytest.mark.asyncio
    async def test_retryable_error_timeout(self):
        """Test timeout error is retryable."""
        provider = OllamaLLMProvider()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection timeout"))
        provider._async_client = mock_client

        with pytest.raises(RetryableError):
            await provider.generate(
                messages=[{"role": "user", "content": "Hi"}]
            )

    @pytest.mark.asyncio
    async def test_non_retryable_error_model_not_found(self):
        """Test model not found error is non-retryable."""
        provider = OllamaLLMProvider()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("model not found"))
        provider._async_client = mock_client

        with pytest.raises(NonRetryableError):
            await provider.generate(
                messages=[{"role": "user", "content": "Hi"}]
            )

    @pytest.mark.asyncio
    async def test_non_retryable_error_invalid_request(self):
        """Test invalid request error is non-retryable."""
        provider = OllamaLLMProvider()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("400 invalid request"))
        provider._async_client = mock_client

        with pytest.raises(NonRetryableError):
            await provider.generate(
                messages=[{"role": "user", "content": "Hi"}]
            )

    @pytest.mark.asyncio
    async def test_error_records_metrics(self):
        """Test that errors are recorded in metrics."""
        provider = OllamaLLMProvider()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Some error"))
        provider._async_client = mock_client

        try:
            await provider.generate(
                messages=[{"role": "user", "content": "Hi"}]
            )
        except Exception:
            pass

        assert provider.metrics.failed_requests == 1
        assert provider.metrics.last_error is not None


class TestOllamaLLMProviderVoiceRunnable:
    """Tests for VoiceRunnable interface."""

    @pytest.mark.asyncio
    async def test_ainvoke_with_string(self):
        """Test ainvoke with string input."""
        provider = OllamaLLMProvider()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Hello!"}
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.ainvoke("Hi there")

        assert result == "Hello!"

        # Check that string was converted to message
        call_kwargs = mock_client.post.call_args[1]
        request_body = call_kwargs["json"]
        messages = request_body["messages"]
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Hi there"

    @pytest.mark.asyncio
    async def test_ainvoke_with_messages(self):
        """Test ainvoke with message list."""
        provider = OllamaLLMProvider()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Response"}
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "How are you?"},
        ]

        result = await provider.ainvoke(messages)

        assert result == "Response"

    @pytest.mark.asyncio
    async def test_ainvoke_with_transcription_result(self):
        """Test ainvoke with TranscriptionResult-like object."""
        provider = OllamaLLMProvider()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Response"}
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        # Object with .text attribute
        class FakeTranscriptionResult:
            text = "Transcribed text"

        result = await provider.ainvoke(FakeTranscriptionResult())

        assert result == "Response"

        call_kwargs = mock_client.post.call_args[1]
        request_body = call_kwargs["json"]
        messages = request_body["messages"]
        assert messages[-1]["content"] == "Transcribed text"

    @pytest.mark.asyncio
    async def test_astream(self):
        """Test astream method."""
        provider = OllamaLLMProvider()

        async def mock_aiter_lines():
            yield json.dumps({"message": {"content": "Hello"}, "done": False})
            yield json.dumps({"message": {"content": " World"}, "done": True})

        mock_response = AsyncMock()
        mock_response.aiter_lines = mock_aiter_lines
        mock_response.raise_for_status = MagicMock()

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_context.__aexit__.return_value = None

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_context)
        provider._async_client = mock_client

        chunks = []
        async for chunk in provider.astream("Hi"):
            chunks.append(chunk)

        assert len(chunks) == 3  # "Hello", " World", final
        assert chunks[0].text == "Hello"


def _get_first_ollama_model():
    """Get the first available model from Ollama server."""
    try:
        import httpx

        response = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if response.status_code != 200:
            return None

        data = response.json()
        models = data.get("models", [])
        if models:
            return models[0].get("name")
        return None

    except Exception:
        return None


def _check_ollama_available():
    """Check if Ollama server is accessible and functional."""
    return _get_first_ollama_model() is not None


@pytest.mark.skipif(
    not _check_ollama_available(),
    reason="Ollama server not available or no models installed"
)
class TestOllamaLLMProviderIntegration:
    """Integration tests (requires running Ollama server with models).

    These tests are skipped automatically if Ollama is not running or
    no models are installed.

    To run these tests:
    1. Start Ollama: ollama serve
    2. Pull a model: ollama pull llama3.2
    3. Run: pytest tests/test_provider_llm_ollama.py -v
    """

    @pytest.fixture
    async def ollama_provider(self):
        """Create and connect an Ollama provider using first available model."""
        model_name = _get_first_ollama_model()
        if not model_name:
            pytest.skip("No Ollama models available")

        provider = OllamaLLMProvider(model=model_name)
        await provider.connect()

        # Check if model is available
        health = await provider.health_check()
        if health.status != ProviderHealth.HEALTHY:
            await provider.disconnect()
            pytest.skip(f"Ollama model not ready: {health.message}")

        yield provider

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_real_generation(self, ollama_provider):
        """Test real generation with Ollama server."""
        provider = ollama_provider

        # Generate response
        result = await provider.generate(
            messages=[{"role": "user", "content": "Say 'Hello' in one word."}],
            max_tokens=10,
        )

        assert len(result) > 0
        assert "hello" in result.lower() or "hi" in result.lower()

    @pytest.mark.asyncio
    async def test_real_streaming(self, ollama_provider):
        """Test real streaming with Ollama server."""
        provider = ollama_provider

        chunks = []
        async for chunk in provider.generate_stream(
            messages=[{"role": "user", "content": "Count to 3."}],
            max_tokens=20,
        ):
            chunks.append(chunk)

        # Should have multiple chunks
        assert len(chunks) >= 2
        # Last chunk should be final
        assert chunks[-1].is_final
