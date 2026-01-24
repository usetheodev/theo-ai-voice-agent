"""Tests for OpenAI LLM provider."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from voice_pipeline.interfaces.llm import LLMChunk, LLMResponse
from voice_pipeline.providers.base import (
    HealthCheckResult,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)
from voice_pipeline.providers.llm import OpenAILLMProvider, OpenAILLMConfig


class TestOpenAILLMConfig:
    """Tests for OpenAILLMConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = OpenAILLMConfig()

        assert config.model == "gpt-4o-mini"
        assert config.api_key is None
        assert config.api_base is None
        assert config.organization is None
        assert config.default_temperature == 0.7
        assert config.default_max_tokens is None
        assert config.default_system_prompt is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = OpenAILLMConfig(
            model="gpt-4-turbo",
            api_key="sk-test",
            api_base="https://custom.api.com",
            organization="org-123",
            default_temperature=0.5,
            default_max_tokens=2000,
            default_system_prompt="You are a helpful assistant.",
        )

        assert config.model == "gpt-4-turbo"
        assert config.api_key == "sk-test"
        assert config.api_base == "https://custom.api.com"
        assert config.organization == "org-123"
        assert config.default_temperature == 0.5
        assert config.default_max_tokens == 2000
        assert config.default_system_prompt == "You are a helpful assistant."


class TestOpenAILLMProviderInit:
    """Tests for OpenAILLMProvider initialization."""

    def test_default_initialization(self):
        """Test provider with default config."""
        provider = OpenAILLMProvider()

        assert provider.provider_name == "openai-llm"
        assert provider.name == "OpenAILLM"
        assert provider._llm_config.model == "gpt-4o-mini"
        assert provider.is_connected is False

    def test_initialization_with_config(self):
        """Test provider with custom config."""
        config = OpenAILLMConfig(model="gpt-4", api_key="sk-test")
        provider = OpenAILLMProvider(config=config)

        assert provider._llm_config.model == "gpt-4"
        assert provider._llm_config.api_key == "sk-test"

    def test_initialization_with_shortcuts(self):
        """Test provider with shortcut parameters."""
        provider = OpenAILLMProvider(
            model="gpt-4-turbo",
            api_key="sk-shortcut",
            temperature=0.3,
        )

        assert provider._llm_config.model == "gpt-4-turbo"
        assert provider._llm_config.api_key == "sk-shortcut"
        assert provider._llm_config.default_temperature == 0.3

    def test_shortcuts_override_config(self):
        """Test that shortcuts override config values."""
        config = OpenAILLMConfig(model="gpt-3.5-turbo", api_key="config-key")
        provider = OpenAILLMProvider(
            config=config,
            model="gpt-4",
            api_key="shortcut-key",
        )

        assert provider._llm_config.model == "gpt-4"
        assert provider._llm_config.api_key == "shortcut-key"

    def test_repr(self):
        """Test string representation."""
        provider = OpenAILLMProvider(model="gpt-4-turbo")
        repr_str = repr(provider)

        assert "OpenAILLMProvider" in repr_str
        assert "gpt-4-turbo" in repr_str
        assert "connected=False" in repr_str


class TestOpenAILLMProviderLifecycle:
    """Tests for provider lifecycle (connect/disconnect)."""

    @pytest.mark.asyncio
    async def test_connect_creates_clients(self):
        """Test that connect creates OpenAI clients."""
        provider = OpenAILLMProvider(api_key="sk-test")

        with patch("openai.AsyncOpenAI") as mock_async:
            with patch("openai.OpenAI") as mock_sync:
                mock_async_instance = MagicMock()
                mock_sync_instance = MagicMock()
                mock_async.return_value = mock_async_instance
                mock_sync.return_value = mock_sync_instance

                await provider.connect()

                mock_async.assert_called_once()
                mock_sync.assert_called_once()
                assert provider.is_connected is True
                assert provider._async_client is mock_async_instance
                assert provider._client is mock_sync_instance

    @pytest.mark.asyncio
    async def test_connect_with_organization(self):
        """Test connect with organization parameter."""
        config = OpenAILLMConfig(
            api_key="sk-test",
            organization="org-123",
        )
        provider = OpenAILLMProvider(config=config)

        with patch("openai.AsyncOpenAI") as mock_async:
            with patch("openai.OpenAI") as mock_sync:
                await provider.connect()

                # Check that organization was passed
                call_kwargs = mock_async.call_args[1]
                assert call_kwargs["organization"] == "org-123"

    @pytest.mark.asyncio
    async def test_connect_from_env_var(self, monkeypatch):
        """Test connect with API key from environment."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        provider = OpenAILLMProvider()

        with patch("openai.AsyncOpenAI") as mock_async:
            with patch("openai.OpenAI"):
                await provider.connect()

                call_kwargs = mock_async.call_args[1]
                assert call_kwargs["api_key"] == "sk-from-env"

    @pytest.mark.asyncio
    async def test_connect_raises_without_api_key(self, monkeypatch):
        """Test that connect raises error without API key."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        provider = OpenAILLMProvider()

        with pytest.raises(ValueError, match="API key is required"):
            await provider.connect()

    @pytest.mark.asyncio
    async def test_connect_raises_without_openai(self):
        """Test that connect raises ImportError without openai package."""
        provider = OpenAILLMProvider(api_key="sk-test")

        with patch.dict("sys.modules", {"openai": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("No module named 'openai'"),
            ):
                with pytest.raises(ImportError, match="openai is required"):
                    await provider.connect()

    @pytest.mark.asyncio
    async def test_disconnect_closes_client(self):
        """Test that disconnect closes the client."""
        provider = OpenAILLMProvider(api_key="sk-test")

        mock_async_client = AsyncMock()
        provider._async_client = mock_async_client
        provider._client = MagicMock()
        provider._connected = True

        await provider.disconnect()

        mock_async_client.close.assert_called_once()
        assert provider._async_client is None
        assert provider._client is None
        assert provider.is_connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        provider = OpenAILLMProvider(api_key="sk-test")

        with patch("openai.AsyncOpenAI") as mock_async:
            with patch("openai.OpenAI"):
                mock_client = AsyncMock()
                mock_async.return_value = mock_client

                async with provider as p:
                    assert p.is_connected is True

                assert provider.is_connected is False


class TestOpenAILLMProviderHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_when_not_connected(self):
        """Test health check returns unhealthy when not connected."""
        provider = OpenAILLMProvider(api_key="sk-test")

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "not initialized" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_when_connected(self):
        """Test health check returns healthy when API is accessible."""
        provider = OpenAILLMProvider(api_key="sk-test")

        # Mock client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.health_check()

        assert result.status == ProviderHealth.HEALTHY
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_error(self):
        """Test health check returns unhealthy on API error."""
        provider = OpenAILLMProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )
        provider._async_client = mock_client

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "API error" in result.message


class TestOpenAILLMProviderGenerateStream:
    """Tests for streaming text generation."""

    @pytest.mark.asyncio
    async def test_generate_stream_raises_without_client(self):
        """Test generate_stream raises error when not connected."""
        provider = OpenAILLMProvider(api_key="sk-test")

        with pytest.raises(RuntimeError, match="not connected"):
            async for _ in provider.generate_stream(
                messages=[{"role": "user", "content": "Hello"}]
            ):
                pass

    @pytest.mark.asyncio
    async def test_generate_stream_basic(self):
        """Test basic streaming generation."""
        provider = OpenAILLMProvider(api_key="sk-test")

        # Create mock stream chunks
        mock_chunks = [
            MagicMock(choices=[MagicMock(delta=MagicMock(content="Hello"), finish_reason=None)]),
            MagicMock(choices=[MagicMock(delta=MagicMock(content=" World"), finish_reason=None)]),
            MagicMock(choices=[MagicMock(delta=MagicMock(content="!"), finish_reason="stop")]),
        ]

        async def async_gen():
            for chunk in mock_chunks:
                yield chunk

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=async_gen())
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
        provider = OpenAILLMProvider(api_key="sk-test")

        async def async_gen():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="Response"), finish_reason="stop")])

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=async_gen())
        provider._async_client = mock_client

        chunks = []
        async for chunk in provider.generate_stream(
            messages=[{"role": "user", "content": "Hi"}],
            system_prompt="You are a pirate.",
        ):
            chunks.append(chunk)

        # Check that system prompt was included
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a pirate."

    @pytest.mark.asyncio
    async def test_generate_stream_uses_default_system_prompt(self):
        """Test streaming uses default system prompt from config."""
        config = OpenAILLMConfig(
            api_key="sk-test",
            default_system_prompt="Default system prompt",
        )
        provider = OpenAILLMProvider(config=config)

        async def async_gen():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="Hi"), finish_reason="stop")])

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=async_gen())
        provider._async_client = mock_client

        chunks = []
        async for chunk in provider.generate_stream(
            messages=[{"role": "user", "content": "Hi"}]
        ):
            chunks.append(chunk)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        assert messages[0]["content"] == "Default system prompt"

    @pytest.mark.asyncio
    async def test_generate_stream_records_metrics(self):
        """Test that streaming records metrics."""
        provider = OpenAILLMProvider(api_key="sk-test")

        async def async_gen():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="Hi"), finish_reason="stop")])

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=async_gen())
        provider._async_client = mock_client

        async for _ in provider.generate_stream(
            messages=[{"role": "user", "content": "Hi"}]
        ):
            pass

        assert provider.metrics.successful_requests == 1
        assert provider.metrics.total_requests == 1


class TestOpenAILLMProviderGenerate:
    """Tests for non-streaming text generation."""

    @pytest.mark.asyncio
    async def test_generate_raises_without_client(self):
        """Test generate raises error when not connected."""
        provider = OpenAILLMProvider(api_key="sk-test")

        with pytest.raises(RuntimeError, match="not connected"):
            await provider.generate(
                messages=[{"role": "user", "content": "Hello"}]
            )

    @pytest.mark.asyncio
    async def test_generate_basic(self):
        """Test basic non-streaming generation."""
        provider = OpenAILLMProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="Hello, how can I help?"))
        ]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.generate(
            messages=[{"role": "user", "content": "Hi"}]
        )

        assert result == "Hello, how can I help?"

    @pytest.mark.asyncio
    async def test_generate_with_max_tokens(self):
        """Test generation with max_tokens parameter."""
        provider = OpenAILLMProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Short"))]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        await provider.generate(
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=100,
        )

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 100


class TestOpenAILLMProviderToolCalling:
    """Tests for tool calling functionality."""

    def test_supports_tools(self):
        """Test that OpenAI LLM supports tools."""
        provider = OpenAILLMProvider(api_key="sk-test")
        assert provider.supports_tools() is True

    @pytest.mark.asyncio
    async def test_generate_with_tools_raises_without_client(self):
        """Test generate_with_tools raises error when not connected."""
        provider = OpenAILLMProvider(api_key="sk-test")

        with pytest.raises(RuntimeError, match="not connected"):
            await provider.generate_with_tools(
                messages=[{"role": "user", "content": "What's the weather?"}],
                tools=[],
            )

    @pytest.mark.asyncio
    async def test_generate_with_tools_basic(self):
        """Test tool calling with tools."""
        provider = OpenAILLMProvider(api_key="sk-test")

        # Mock response with tool call
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.type = "function"
        mock_tool_call.function.name = "get_weather"
        mock_tool_call.function.arguments = '{"location": "Boston"}'

        mock_message = MagicMock()
        mock_message.content = None
        mock_message.tool_calls = [mock_tool_call]

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 50
        mock_usage.completion_tokens = 20
        mock_usage.total_tokens = 70

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_message, finish_reason="tool_calls")]
        mock_response.usage = mock_usage

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
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
        assert result.tool_calls[0]["id"] == "call_123"
        assert result.tool_calls[0]["function"]["name"] == "get_weather"
        assert result.finish_reason == "tool_calls"
        assert result.usage["total_tokens"] == 70

    @pytest.mark.asyncio
    async def test_generate_with_tools_no_tool_call(self):
        """Test tool calling when LLM responds directly."""
        provider = OpenAILLMProvider(api_key="sk-test")

        mock_message = MagicMock()
        mock_message.content = "I don't have access to weather data."
        mock_message.tool_calls = None

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_message, finish_reason="stop")]
        mock_response.usage = None

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.generate_with_tools(
            messages=[{"role": "user", "content": "Tell me a joke"}],
            tools=[],
        )

        assert result.has_tool_calls is False
        assert result.content == "I don't have access to weather data."
        assert result.finish_reason == "stop"


class TestOpenAILLMProviderErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_retryable_error_rate_limit(self):
        """Test rate limit error is retryable."""
        provider = OpenAILLMProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Rate limit exceeded")
        )
        provider._async_client = mock_client

        with pytest.raises(RetryableError):
            await provider.generate(
                messages=[{"role": "user", "content": "Hi"}]
            )

    @pytest.mark.asyncio
    async def test_retryable_error_timeout(self):
        """Test timeout error is retryable."""
        provider = OpenAILLMProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Connection timeout")
        )
        provider._async_client = mock_client

        with pytest.raises(RetryableError):
            await provider.generate(
                messages=[{"role": "user", "content": "Hi"}]
            )

    @pytest.mark.asyncio
    async def test_non_retryable_error_invalid_key(self):
        """Test invalid API key error is non-retryable."""
        provider = OpenAILLMProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Invalid API key")
        )
        provider._async_client = mock_client

        with pytest.raises(NonRetryableError):
            await provider.generate(
                messages=[{"role": "user", "content": "Hi"}]
            )

    @pytest.mark.asyncio
    async def test_error_records_metrics(self):
        """Test that errors are recorded in metrics."""
        provider = OpenAILLMProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Some error")
        )
        provider._async_client = mock_client

        try:
            await provider.generate(
                messages=[{"role": "user", "content": "Hi"}]
            )
        except Exception:
            pass

        assert provider.metrics.failed_requests == 1
        assert provider.metrics.last_error is not None


class TestOpenAILLMProviderVoiceRunnable:
    """Tests for VoiceRunnable interface."""

    @pytest.mark.asyncio
    async def test_ainvoke_with_string(self):
        """Test ainvoke with string input."""
        provider = OpenAILLMProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello!"))]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.ainvoke("Hi there")

        assert result == "Hello!"

        # Check that string was converted to message
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Hi there"

    @pytest.mark.asyncio
    async def test_ainvoke_with_messages(self):
        """Test ainvoke with message list."""
        provider = OpenAILLMProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Response"))]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
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
        provider = OpenAILLMProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Response"))]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        # Object with .text attribute
        class FakeTranscriptionResult:
            text = "Transcribed text"

        result = await provider.ainvoke(FakeTranscriptionResult())

        assert result == "Response"

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        assert messages[-1]["content"] == "Transcribed text"

    @pytest.mark.asyncio
    async def test_astream(self):
        """Test astream method."""
        provider = OpenAILLMProvider(api_key="sk-test")

        async def async_gen():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="Hello"), finish_reason=None)])
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=" World"), finish_reason="stop")])

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=async_gen())
        provider._async_client = mock_client

        chunks = []
        async for chunk in provider.astream("Hi"):
            chunks.append(chunk)

        assert len(chunks) == 3  # "Hello", " World", final
        assert chunks[0].text == "Hello"
