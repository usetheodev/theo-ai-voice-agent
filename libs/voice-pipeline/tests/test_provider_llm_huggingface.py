"""Tests for HuggingFace LLM provider with BitsAndBytes quantization."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio


# =============================================================================
# Skip if dependencies not installed
# =============================================================================


torch = pytest.importorskip("torch", reason="torch not installed")


from voice_pipeline.providers.llm.huggingface import (
    HuggingFaceLLMProvider,
    HuggingFaceLLMConfig,
    QuantizationType,
)
from voice_pipeline.interfaces.llm import LLMChunk


# =============================================================================
# Config Tests
# =============================================================================


class TestHuggingFaceLLMConfig:
    """Tests for HuggingFaceLLMConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = HuggingFaceLLMConfig()

        assert config.model == "microsoft/phi-2"
        assert config.quantization == QuantizationType.INT4
        assert config.device == "auto"
        assert config.max_new_tokens == 128
        assert config.temperature == 0.7
        assert config.top_p == 0.9
        assert config.top_k == 50
        assert config.do_sample is True
        assert config.use_flash_attention is True
        assert config.double_quant is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = HuggingFaceLLMConfig(
            model="meta-llama/Llama-2-7b-chat-hf",
            quantization=QuantizationType.INT8,
            device="cuda",
            max_new_tokens=256,
            temperature=0.5,
        )

        assert config.model == "meta-llama/Llama-2-7b-chat-hf"
        assert config.quantization == QuantizationType.INT8
        assert config.device == "cuda"
        assert config.max_new_tokens == 256
        assert config.temperature == 0.5

    def test_quantization_types(self):
        """Test all quantization types."""
        assert QuantizationType.NONE.value == "none"
        assert QuantizationType.INT8.value == "int8"
        assert QuantizationType.INT4.value == "int4"
        assert QuantizationType.NF4.value == "nf4"
        assert QuantizationType.FP4.value == "fp4"


# =============================================================================
# Provider Initialization Tests
# =============================================================================


class TestHuggingFaceLLMProviderInit:
    """Tests for provider initialization."""

    def test_init_with_config(self):
        """Test initialization with config object."""
        config = HuggingFaceLLMConfig(model="test-model")
        provider = HuggingFaceLLMProvider(config=config)

        assert provider._llm_config.model == "test-model"
        assert provider._model is None
        assert provider._tokenizer is None

    def test_init_with_shortcuts(self):
        """Test initialization with shortcut parameters."""
        provider = HuggingFaceLLMProvider(
            model="custom-model",
            quantization="int8",
            device="cuda",
            temperature=0.3,
            max_new_tokens=64,
        )

        assert provider._llm_config.model == "custom-model"
        assert provider._llm_config.quantization == QuantizationType.INT8
        assert provider._llm_config.device == "cuda"
        assert provider._llm_config.temperature == 0.3
        assert provider._llm_config.max_new_tokens == 64

    def test_default_init(self):
        """Test default initialization."""
        provider = HuggingFaceLLMProvider()

        assert provider._llm_config.model == "microsoft/phi-2"
        assert provider._llm_config.quantization == QuantizationType.INT4

    def test_provider_name(self):
        """Test provider name attributes."""
        provider = HuggingFaceLLMProvider()

        assert provider.provider_name == "huggingface-llm"
        assert provider.name == "HuggingFaceLLM"


# =============================================================================
# Quantization Config Tests
# =============================================================================


def _has_bitsandbytes():
    """Check if bitsandbytes is available."""
    try:
        import bitsandbytes
        return True
    except ImportError:
        return False


class TestQuantizationConfig:
    """Tests for quantization configuration."""

    def test_int8_quantization_config_type(self):
        """Test 8-bit quantization config type is set correctly."""
        provider = HuggingFaceLLMProvider(quantization="int8")

        # Check that the config is properly set
        assert provider._llm_config.quantization == QuantizationType.INT8

    @pytest.mark.skipif(not _has_bitsandbytes(), reason="bitsandbytes not installed")
    def test_int8_quantization_config_creation(self):
        """Test 8-bit quantization config creation."""
        provider = HuggingFaceLLMProvider(quantization="int8")
        config = provider._get_quantization_config()
        assert config is not None

    def test_int4_quantization_config_type(self):
        """Test 4-bit quantization config type is set correctly."""
        provider = HuggingFaceLLMProvider(quantization="int4")

        assert provider._llm_config.quantization == QuantizationType.INT4

    @pytest.mark.skipif(not _has_bitsandbytes(), reason="bitsandbytes not installed")
    def test_int4_quantization_config_creation(self):
        """Test 4-bit quantization config creation."""
        provider = HuggingFaceLLMProvider(quantization="int4")
        config = provider._get_quantization_config()
        assert config is not None

    def test_nf4_quantization_config(self):
        """Test NF4 quantization config."""
        provider = HuggingFaceLLMProvider(quantization="nf4")

        assert provider._llm_config.quantization == QuantizationType.NF4

    def test_no_quantization_config(self):
        """Test no quantization returns None."""
        provider = HuggingFaceLLMProvider(quantization="none")
        config = provider._get_quantization_config()

        assert config is None


# =============================================================================
# Health Check Tests
# =============================================================================


class TestHealthCheck:
    """Tests for health check."""

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self):
        """Test health check when not connected."""
        provider = HuggingFaceLLMProvider()
        result = await provider._do_health_check()

        assert result.status.value == "unhealthy"
        assert "not loaded" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_connected(self):
        """Test health check when connected."""
        provider = HuggingFaceLLMProvider()

        # Mock model and tokenizer
        provider._model = MagicMock()
        provider._model.device = "cuda:0"
        provider._tokenizer = MagicMock()
        provider._tokenizer.return_value = {"input_ids": MagicMock()}

        result = await provider._do_health_check()

        assert result.status.value == "healthy"
        assert "loaded" in result.message.lower()


# =============================================================================
# Prompt Building Tests
# =============================================================================


class TestPromptBuilding:
    """Tests for prompt building."""

    def test_build_prompt_simple(self):
        """Test simple prompt building."""
        provider = HuggingFaceLLMProvider()

        # Mock tokenizer without chat template
        provider._tokenizer = MagicMock()
        provider._tokenizer.chat_template = None

        messages = [{"role": "user", "content": "Hello!"}]
        prompt = provider._build_prompt(messages)

        assert "User: Hello!" in prompt
        assert "Assistant:" in prompt

    def test_build_prompt_with_system(self):
        """Test prompt building with system prompt."""
        provider = HuggingFaceLLMProvider()

        provider._tokenizer = MagicMock()
        provider._tokenizer.chat_template = None

        messages = [{"role": "user", "content": "Hello!"}]
        prompt = provider._build_prompt(messages, system_prompt="You are helpful.")

        assert "System: You are helpful." in prompt
        assert "User: Hello!" in prompt

    def test_build_prompt_with_chat_template(self):
        """Test prompt building with chat template."""
        provider = HuggingFaceLLMProvider()

        provider._tokenizer = MagicMock()
        provider._tokenizer.chat_template = "<|template|>"
        provider._tokenizer.apply_chat_template.return_value = "formatted prompt"

        messages = [{"role": "user", "content": "Hello!"}]
        prompt = provider._build_prompt(messages)

        assert prompt == "formatted prompt"
        provider._tokenizer.apply_chat_template.assert_called_once()


# =============================================================================
# Generation Tests (Mocked)
# =============================================================================


class TestGeneration:
    """Tests for text generation."""

    @pytest.mark.asyncio
    async def test_generate_not_connected(self):
        """Test generation fails when not connected."""
        provider = HuggingFaceLLMProvider()

        with pytest.raises(RuntimeError, match="not loaded"):
            await provider.generate([{"role": "user", "content": "Hello"}])

    @pytest.mark.asyncio
    async def test_generate_stream_not_connected(self):
        """Test streaming generation fails when not connected."""
        provider = HuggingFaceLLMProvider()

        with pytest.raises(RuntimeError, match="not loaded"):
            async for _ in provider.generate_stream([{"role": "user", "content": "Hello"}]):
                pass

    @pytest.mark.asyncio
    async def test_supports_tools(self):
        """Test tool support check."""
        provider = HuggingFaceLLMProvider()

        assert provider.supports_tools() is False


# =============================================================================
# Torch Dtype Tests
# =============================================================================


class TestTorchDtype:
    """Tests for torch dtype handling."""

    def test_get_torch_dtype_auto(self):
        """Test auto dtype."""
        provider = HuggingFaceLLMProvider()
        provider._llm_config.torch_dtype = "auto"

        dtype = provider._get_torch_dtype()
        assert dtype == "auto"

    def test_get_torch_dtype_float16(self):
        """Test float16 dtype."""
        provider = HuggingFaceLLMProvider()
        provider._llm_config.torch_dtype = "float16"

        dtype = provider._get_torch_dtype()
        assert dtype == torch.float16

    def test_get_torch_dtype_bfloat16(self):
        """Test bfloat16 dtype."""
        provider = HuggingFaceLLMProvider()
        provider._llm_config.torch_dtype = "bfloat16"

        dtype = provider._get_torch_dtype()
        assert dtype == torch.bfloat16


# =============================================================================
# Device Info Tests
# =============================================================================


class TestDeviceInfo:
    """Tests for device info."""

    def test_device_info_not_loaded(self):
        """Test device info when model not loaded."""
        provider = HuggingFaceLLMProvider()
        info = provider._get_device_info()

        assert info == "not loaded"

    def test_device_info_with_device(self):
        """Test device info with model device."""
        provider = HuggingFaceLLMProvider()
        provider._model = MagicMock()
        provider._model.device = "cuda:0"

        info = provider._get_device_info()
        assert info == "cuda:0"

    def test_device_info_with_device_map(self):
        """Test device info with device map."""
        provider = HuggingFaceLLMProvider()
        provider._model = MagicMock(spec=[])  # No .device attribute
        provider._model.hf_device_map = {"layer1": 0, "layer2": 0}

        info = provider._get_device_info()
        assert "distributed" in info


# =============================================================================
# Repr Tests
# =============================================================================


class TestRepr:
    """Tests for string representation."""

    def test_repr(self):
        """Test string representation."""
        provider = HuggingFaceLLMProvider(
            model="test-model",
            quantization="int4",
            device="cuda",
        )

        repr_str = repr(provider)

        assert "HuggingFaceLLMProvider" in repr_str
        assert "test-model" in repr_str
        assert "int4" in repr_str
        assert "cuda" in repr_str


# =============================================================================
# Integration Test (Skipped by default)
# =============================================================================


@pytest.mark.skip(reason="Requires GPU and model download")
class TestIntegration:
    """Integration tests (require actual hardware)."""

    @pytest.mark.asyncio
    async def test_full_generation(self):
        """Test full generation flow."""
        provider = HuggingFaceLLMProvider(
            model="microsoft/phi-2",
            quantization="int4",
            device="cuda",
        )

        await provider.connect()

        try:
            response = await provider.generate(
                [{"role": "user", "content": "Say hello in one word."}],
                max_tokens=10,
            )

            assert len(response) > 0
        finally:
            await provider.disconnect()
