"""Tests for Anthropic LLM provider."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, AsyncIterator

from voice_pipeline.providers.llm.anthropic import (
    AnthropicLLMProvider,
    AnthropicLLMConfig,
)
from voice_pipeline.interfaces.llm import LLMChunk, LLMResponse


# ==================== Mock Classes ====================


class MockContentBlock:
    """Mock Anthropic content block."""

    def __init__(self, block_type: str, **kwargs):
        self.type = block_type
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockUsage:
    """Mock Anthropic usage."""

    def __init__(self, input_tokens: int = 10, output_tokens: int = 20):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class MockMessage:
    """Mock Anthropic message."""

    def __init__(
        self,
        content: list = None,
        stop_reason: str = "end_turn",
        usage: MockUsage = None,
    ):
        self.content = content or [MockContentBlock("text", text="Hello!")]
        self.stop_reason = stop_reason
        self.usage = usage or MockUsage()


class MockStreamEvent:
    """Mock Anthropic stream event."""

    def __init__(self, event_type: str, **kwargs):
        self.type = event_type
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockStream:
    """Mock Anthropic stream context manager."""

    def __init__(self, events: list = None, final_message: MockMessage = None):
        self.events = events or []
        self._final_message = final_message or MockMessage()
        self._text_chunks = ["Hello", " ", "world!"]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def __aiter__(self):
        for event in self.events:
            yield event

    @property
    async def text_stream(self):
        for chunk in self._text_chunks:
            yield chunk

    async def get_final_message(self):
        return self._final_message


# ==================== Test Config ====================


class TestAnthropicLLMConfig:
    """Tests for AnthropicLLMConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = AnthropicLLMConfig()

        assert config.model == "claude-3-5-sonnet-20241022"
        assert config.default_temperature == 0.7
        assert config.default_max_tokens == 4096

    def test_custom_config(self):
        """Test custom configuration."""
        config = AnthropicLLMConfig(
            model="claude-3-opus-20240229",
            api_key="test-key",
            default_temperature=0.5,
            default_max_tokens=8192,
        )

        assert config.model == "claude-3-opus-20240229"
        assert config.api_key == "test-key"
        assert config.default_temperature == 0.5
        assert config.default_max_tokens == 8192


# ==================== Test Provider ====================


class TestAnthropicLLMProvider:
    """Tests for AnthropicLLMProvider."""

    def test_init_with_config(self):
        """Test initialization with config."""
        config = AnthropicLLMConfig(model="claude-3-haiku-20240307")
        provider = AnthropicLLMProvider(config=config)

        assert provider._llm_config.model == "claude-3-haiku-20240307"

    def test_init_with_shortcuts(self):
        """Test initialization with shortcut parameters."""
        provider = AnthropicLLMProvider(
            model="claude-3-opus-20240229",
            api_key="test-key",
            temperature=0.5,
        )

        assert provider._llm_config.model == "claude-3-opus-20240229"
        assert provider._llm_config.api_key == "test-key"
        assert provider._llm_config.default_temperature == 0.5

    def test_supports_tools(self):
        """Test that provider reports tool support."""
        provider = AnthropicLLMProvider()
        assert provider.supports_tools() is True

    def test_repr(self):
        """Test string representation."""
        provider = AnthropicLLMProvider(model="claude-3-haiku-20240307")
        repr_str = repr(provider)

        assert "AnthropicLLMProvider" in repr_str
        assert "claude-3-haiku" in repr_str


class TestMessageConversion:
    """Tests for message format conversion."""

    def test_convert_simple_messages(self):
        """Test converting simple user/assistant messages."""
        provider = AnthropicLLMProvider()

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        result = provider._convert_messages_to_anthropic(messages)

        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"
        assert result[1]["role"] == "assistant"
        assert result[1]["content"] == "Hi there!"

    def test_convert_skips_system_messages(self):
        """Test that system messages are skipped (handled separately)."""
        provider = AnthropicLLMProvider()

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
        ]

        result = provider._convert_messages_to_anthropic(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_convert_tool_result(self):
        """Test converting tool result messages."""
        provider = AnthropicLLMProvider()

        messages = [
            {
                "role": "tool",
                "content": "Result: 42",
                "tool_call_id": "call_123",
            }
        ]

        result = provider._convert_messages_to_anthropic(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"][0]["type"] == "tool_result"
        assert result[0]["content"][0]["tool_use_id"] == "call_123"
        assert result[0]["content"][0]["content"] == "Result: 42"

    def test_convert_assistant_with_tool_calls(self):
        """Test converting assistant message with tool calls."""
        provider = AnthropicLLMProvider()

        messages = [
            {
                "role": "assistant",
                "content": "Let me check",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "function": {
                            "name": "get_time",
                            "arguments": "{}",
                        },
                    }
                ],
            }
        ]

        result = provider._convert_messages_to_anthropic(messages)

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        # Should have text block + tool_use block
        assert len(result[0]["content"]) == 2
        assert result[0]["content"][0]["type"] == "text"
        assert result[0]["content"][1]["type"] == "tool_use"
        assert result[0]["content"][1]["name"] == "get_time"


class TestToolConversion:
    """Tests for tool format conversion."""

    def test_convert_tools(self):
        """Test converting tools from OpenAI to Anthropic format."""
        provider = AnthropicLLMProvider()

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                        },
                        "required": ["location"],
                    },
                },
            }
        ]

        result = provider._convert_tools_to_anthropic(tools)

        assert len(result) == 1
        assert result[0]["name"] == "get_weather"
        assert result[0]["description"] == "Get weather for a location"
        assert result[0]["input_schema"]["type"] == "object"
        assert "location" in result[0]["input_schema"]["properties"]


# ==================== Test with Mocked Client ====================


class TestAnthropicLLMProviderWithMocks:
    """Tests for AnthropicLLMProvider with mocked Anthropic client."""

    @pytest.mark.asyncio
    async def test_generate_stream(self):
        """Test streaming text generation."""
        provider = AnthropicLLMProvider(api_key="test-key")

        # Create mock client with proper context manager support
        mock_client = MagicMock()
        mock_stream = MockStream()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        provider._async_client = mock_client
        provider._connected = True

        chunks = []
        async for chunk in provider.generate_stream(
            messages=[{"role": "user", "content": "Hello"}]
        ):
            chunks.append(chunk)

        # Should have received text chunks + final chunk
        assert len(chunks) >= 1
        text_chunks = [c for c in chunks if c.text]
        assert len(text_chunks) > 0

    @pytest.mark.asyncio
    async def test_generate(self):
        """Test non-streaming text generation."""
        provider = AnthropicLLMProvider(api_key="test-key")

        # Create mock client
        mock_client = AsyncMock()
        mock_response = MockMessage(
            content=[MockContentBlock("text", text="Hello, how can I help?")],
        )
        mock_client.messages.create.return_value = mock_response

        provider._async_client = mock_client
        provider._connected = True

        result = await provider.generate(
            messages=[{"role": "user", "content": "Hello"}]
        )

        assert result == "Hello, how can I help?"

    @pytest.mark.asyncio
    async def test_generate_with_tools_text_response(self):
        """Test tool calling when LLM responds with text."""
        provider = AnthropicLLMProvider(api_key="test-key")

        mock_client = AsyncMock()
        mock_response = MockMessage(
            content=[MockContentBlock("text", text="The weather is sunny.")],
            stop_reason="end_turn",
        )
        mock_client.messages.create.return_value = mock_response

        provider._async_client = mock_client
        provider._connected = True

        tools = [
            {
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object"},
                }
            }
        ]

        response = await provider.generate_with_tools(
            messages=[{"role": "user", "content": "What's the weather?"}],
            tools=tools,
        )

        assert response.content == "The weather is sunny."
        assert response.tool_calls == []
        assert response.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_generate_with_tools_tool_call(self):
        """Test tool calling when LLM uses a tool."""
        provider = AnthropicLLMProvider(api_key="test-key")

        mock_client = AsyncMock()
        mock_response = MockMessage(
            content=[
                MockContentBlock(
                    "tool_use",
                    id="call_123",
                    name="get_weather",
                    input={"location": "Tokyo"},
                ),
            ],
            stop_reason="tool_use",
        )
        mock_client.messages.create.return_value = mock_response

        provider._async_client = mock_client
        provider._connected = True

        tools = [
            {
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object"},
                }
            }
        ]

        response = await provider.generate_with_tools(
            messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
            tools=tools,
        )

        assert response.has_tool_calls
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0]["function"]["name"] == "get_weather"
        assert response.finish_reason == "tool_calls"


class TestAnthropicLLMProviderErrors:
    """Tests for error handling."""

    def test_handle_error_rate_limit(self):
        """Test that rate limit errors are retryable."""
        from voice_pipeline.providers.base import RetryableError

        provider = AnthropicLLMProvider()

        with pytest.raises(RetryableError):
            provider._handle_error(Exception("rate limit exceeded"))

    def test_handle_error_auth(self):
        """Test that auth errors are not retryable."""
        from voice_pipeline.providers.base import NonRetryableError

        provider = AnthropicLLMProvider()

        with pytest.raises(NonRetryableError):
            provider._handle_error(Exception("invalid api key"))
