"""HuggingFace LLM provider with BitsAndBytes quantization.

Supports 4-bit and 8-bit quantization for reduced latency and memory usage.
Based on the paper "Toward Low-Latency End-to-End Voice Agents" which reports
~40% latency reduction with 4-bit quantization.

Reference: https://huggingface.co/docs/transformers/quantization
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional

from voice_pipeline.interfaces.llm import LLMChunk, LLMInterface, LLMResponse
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    NonRetryableError,
)
from voice_pipeline.providers.decorators import register_llm
from voice_pipeline.providers.types import LLMCapabilities

logger = logging.getLogger(__name__)


class QuantizationType(str, Enum):
    """Quantization type for model loading."""

    NONE = "none"
    """No quantization (full precision fp16/fp32)."""

    INT8 = "int8"
    """8-bit quantization using BitsAndBytes."""

    INT4 = "int4"
    """4-bit quantization using BitsAndBytes (recommended for low latency)."""

    NF4 = "nf4"
    """4-bit NormalFloat quantization (best quality for 4-bit)."""

    FP4 = "fp4"
    """4-bit floating point quantization."""


@dataclass
class HuggingFaceLLMConfig(ProviderConfig):
    """Configuration for HuggingFace LLM provider with quantization.

    Attributes:
        model: Model identifier from HuggingFace Hub (e.g., "meta-llama/Llama-2-7b-chat-hf").
        quantization: Quantization type (none, int8, int4, nf4, fp4).
        device: Device to use ("cuda", "cpu", "auto").
        max_new_tokens: Maximum tokens to generate.
        temperature: Sampling temperature.
        top_p: Top-p (nucleus) sampling.
        top_k: Top-k sampling.
        do_sample: Whether to use sampling (False = greedy decoding).
        use_flash_attention: Use Flash Attention 2 for faster inference.
        trust_remote_code: Trust remote code from HuggingFace Hub.
        torch_dtype: Data type for model weights ("auto", "float16", "bfloat16").
        double_quant: Use double quantization for 4-bit (saves more memory).
        compute_dtype: Compute dtype for quantized models.
        max_memory: Maximum memory per device (e.g., {"0": "10GB", "cpu": "30GB"}).

    Example:
        >>> config = HuggingFaceLLMConfig(
        ...     model="meta-llama/Llama-2-7b-chat-hf",
        ...     quantization=QuantizationType.INT4,
        ...     device="cuda",
        ...     max_new_tokens=128,
        ... )
        >>> llm = HuggingFaceLLMProvider(config=config)
    """

    model: str = "microsoft/phi-2"
    """Model identifier from HuggingFace Hub."""

    quantization: QuantizationType = QuantizationType.INT4
    """Quantization type: none, int8, int4, nf4, fp4."""

    device: str = "auto"
    """Device to use: 'cuda', 'cpu', 'mps', or 'auto'."""

    max_new_tokens: int = 128
    """Maximum number of tokens to generate."""

    temperature: float = 0.7
    """Sampling temperature (0.0 to 2.0). Higher = more creative."""

    top_p: float = 0.9
    """Top-p (nucleus) sampling. Lower = more focused."""

    top_k: int = 50
    """Top-k sampling. Lower = more focused."""

    do_sample: bool = True
    """Whether to use sampling (False = greedy decoding)."""

    repetition_penalty: float = 1.1
    """Penalty for repeating tokens. Higher = less repetition."""

    # Advanced options
    use_flash_attention: bool = True
    """Use Flash Attention 2 for faster inference (requires compatible GPU)."""

    trust_remote_code: bool = False
    """Trust remote code from HuggingFace Hub (required for some models)."""

    torch_dtype: str = "auto"
    """Data type: 'auto', 'float16', 'bfloat16', 'float32'."""

    # Quantization-specific options
    double_quant: bool = True
    """Use double quantization for 4-bit (saves ~0.4 bits/param)."""

    compute_dtype: str = "float16"
    """Compute dtype for quantized operations."""

    max_memory: Optional[dict[str, str]] = None
    """Maximum memory per device (e.g., {'0': '10GB', 'cpu': '30GB'})."""

    # Chat template
    chat_template: Optional[str] = None
    """Custom chat template (Jinja2 format). None = use model default."""

    default_system_prompt: Optional[str] = None
    """Default system prompt to use if none provided."""


@register_llm(
    name="huggingface",
    capabilities=LLMCapabilities(
        streaming=True,
        function_calling=False,
        system_prompt=True,
        context_window=4096,
        max_output_tokens=2048,
    ),
    description="HuggingFace Transformers with BitsAndBytes 4-bit/8-bit quantization for low-latency inference.",
    version="1.0.0",
    aliases=["hf", "transformers", "bitsandbytes", "bnb"],
    tags=["local", "quantized", "4-bit", "8-bit", "llama", "mistral", "phi"],
    default_config={
        "model": "microsoft/phi-2",
        "quantization": "int4",
        "device": "auto",
    },
)
class HuggingFaceLLMProvider(BaseProvider, LLMInterface):
    """HuggingFace LLM provider with BitsAndBytes quantization.

    Supports 4-bit and 8-bit quantization for reduced latency and memory usage.
    The paper "Toward Low-Latency End-to-End Voice Agents" reports ~40% latency
    reduction with 4-bit quantization.

    Features:
    - 4-bit and 8-bit quantization via BitsAndBytes
    - Streaming text generation with TextIteratorStreamer
    - Support for many models (Llama, Mistral, Phi, Qwen, etc.)
    - Flash Attention 2 for faster inference
    - GPU memory optimization with device_map="auto"

    Requirements:
        pip install transformers accelerate bitsandbytes torch

    Example:
        >>> llm = HuggingFaceLLMProvider(
        ...     model="meta-llama/Llama-2-7b-chat-hf",
        ...     quantization="int4",  # 4-bit quantization
        ...     device="cuda",
        ... )
        >>> await llm.connect()
        >>>
        >>> # Generate streaming response
        >>> async for chunk in llm.generate_stream(
        ...     messages=[{"role": "user", "content": "Hello!"}]
        ... ):
        ...     print(chunk.text, end="")

    Quantization Comparison:
        | Type  | Memory  | Latency | Quality |
        |-------|---------|---------|---------|
        | none  | 100%    | 100%    | Best    |
        | int8  | ~50%    | ~70%    | Good    |
        | int4  | ~25%    | ~60%    | Good    |
        | nf4   | ~25%    | ~60%    | Better  |
    """

    provider_name: str = "huggingface-llm"
    name: str = "HuggingFaceLLM"

    def __init__(
        self,
        config: Optional[HuggingFaceLLMConfig] = None,
        model: Optional[str] = None,
        quantization: Optional[str] = None,
        device: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
        **kwargs,
    ):
        """Initialize HuggingFace LLM provider.

        Args:
            config: Full configuration object.
            model: Model identifier (shortcut).
            quantization: Quantization type (shortcut): "none", "int8", "int4", "nf4", "fp4".
            device: Device to use (shortcut): "cuda", "cpu", "auto".
            temperature: Default temperature (shortcut).
            max_new_tokens: Max tokens to generate (shortcut).
            **kwargs: Additional configuration options.
        """
        if config is None:
            config = HuggingFaceLLMConfig()

        # Apply shortcuts
        if model is not None:
            config.model = model
        if quantization is not None:
            config.quantization = QuantizationType(quantization)
        if device is not None:
            config.device = device
        if temperature is not None:
            config.temperature = temperature
        if max_new_tokens is not None:
            config.max_new_tokens = max_new_tokens

        super().__init__(config=config, **kwargs)

        self._llm_config: HuggingFaceLLMConfig = config
        self._model = None
        self._tokenizer = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._generation_lock = asyncio.Lock()

    async def connect(self) -> None:
        """Load model and tokenizer.

        This may take a while for first load as the model needs to be
        downloaded and loaded into GPU/CPU memory.
        """
        await super().connect()

        # Load in thread to not block event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._load_model)

    def _load_model(self) -> None:
        """Load model and tokenizer synchronously."""
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError:
            raise ImportError(
                "transformers and torch are required for HuggingFace LLM. "
                "Install with: pip install transformers torch accelerate"
            )

        logger.info(f"Loading model: {self._llm_config.model}")
        logger.info(f"Quantization: {self._llm_config.quantization.value}")

        # Determine torch dtype
        torch_dtype = self._get_torch_dtype()

        # Build model kwargs
        model_kwargs = {
            "trust_remote_code": self._llm_config.trust_remote_code,
            "torch_dtype": torch_dtype,
        }

        # Device map for automatic distribution
        if self._llm_config.device == "auto":
            model_kwargs["device_map"] = "auto"
        elif self._llm_config.device == "cuda":
            model_kwargs["device_map"] = "cuda:0"
        elif self._llm_config.device == "mps":
            model_kwargs["device_map"] = "mps"
        # CPU doesn't need device_map

        # Memory limits
        if self._llm_config.max_memory:
            model_kwargs["max_memory"] = self._llm_config.max_memory

        # Flash Attention
        if self._llm_config.use_flash_attention:
            try:
                model_kwargs["attn_implementation"] = "flash_attention_2"
            except Exception:
                logger.warning("Flash Attention 2 not available, using default attention")

        # Quantization config
        if self._llm_config.quantization != QuantizationType.NONE:
            quantization_config = self._get_quantization_config()
            if quantization_config:
                model_kwargs["quantization_config"] = quantization_config

        # Load tokenizer
        logger.info("Loading tokenizer...")
        self._tokenizer = AutoTokenizer.from_pretrained(
            self._llm_config.model,
            trust_remote_code=self._llm_config.trust_remote_code,
        )

        # Ensure pad token is set
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        # Load model
        logger.info("Loading model weights...")
        self._model = AutoModelForCausalLM.from_pretrained(
            self._llm_config.model,
            **model_kwargs,
        )

        # Put in eval mode
        self._model.eval()

        logger.info(f"Model loaded successfully on {self._get_device_info()}")

    def _get_torch_dtype(self):
        """Get torch dtype from config."""
        import torch

        dtype_map = {
            "auto": "auto",
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        return dtype_map.get(self._llm_config.torch_dtype, "auto")

    def _get_quantization_config(self):
        """Get BitsAndBytes quantization config."""
        try:
            from transformers import BitsAndBytesConfig
            import torch
        except ImportError:
            logger.warning(
                "BitsAndBytes not available. "
                "Install with: pip install bitsandbytes"
            )
            return None

        quant_type = self._llm_config.quantization

        # Compute dtype
        compute_dtype_map = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        compute_dtype = compute_dtype_map.get(
            self._llm_config.compute_dtype, torch.float16
        )

        if quant_type == QuantizationType.INT8:
            return BitsAndBytesConfig(
                load_in_8bit=True,
            )

        elif quant_type in (QuantizationType.INT4, QuantizationType.NF4, QuantizationType.FP4):
            # Determine 4-bit type
            bnb_4bit_quant_type = "nf4" if quant_type == QuantizationType.NF4 else "fp4"
            if quant_type == QuantizationType.INT4:
                bnb_4bit_quant_type = "nf4"  # nf4 is the default/best for int4

            return BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type=bnb_4bit_quant_type,
                bnb_4bit_compute_dtype=compute_dtype,
                bnb_4bit_use_double_quant=self._llm_config.double_quant,
            )

        return None

    def _get_device_info(self) -> str:
        """Get device info string."""
        if self._model is None:
            return "not loaded"

        try:
            import torch
            if hasattr(self._model, "device"):
                return str(self._model.device)
            elif hasattr(self._model, "hf_device_map"):
                devices = set(self._model.hf_device_map.values())
                return f"distributed: {devices}"
            elif torch.cuda.is_available():
                return "cuda"
            else:
                return "cpu"
        except Exception:
            return "unknown"

    async def disconnect(self) -> None:
        """Unload model and free memory."""
        if self._model is not None:
            try:
                import torch
                del self._model
                self._model = None
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

        if self._tokenizer is not None:
            del self._tokenizer
            self._tokenizer = None

        self._executor.shutdown(wait=False)
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if model is loaded and ready."""
        if self._model is None or self._tokenizer is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Model not loaded. Call connect() first.",
            )

        try:
            # Quick test generation
            test_input = self._tokenizer("Hello", return_tensors="pt")
            device = self._get_device_info()

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"Model loaded: {self._llm_config.model}",
                details={
                    "model": self._llm_config.model,
                    "quantization": self._llm_config.quantization.value,
                    "device": device,
                },
            )
        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"Model error: {e}",
            )

    def _build_prompt(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> str:
        """Build prompt string from messages using chat template.

        Args:
            messages: Conversation history.
            system_prompt: Optional system prompt.

        Returns:
            Formatted prompt string.
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

        # Use chat template if available
        if self._tokenizer.chat_template or self._llm_config.chat_template:
            try:
                prompt = self._tokenizer.apply_chat_template(
                    full_messages,
                    tokenize=False,
                    add_generation_prompt=True,
                    chat_template=self._llm_config.chat_template,
                )
                return prompt
            except Exception as e:
                logger.warning(f"Chat template failed: {e}, using fallback")

        # Fallback: simple format
        prompt_parts = []
        for msg in full_messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                prompt_parts.append(f"System: {content}")
            elif role == "user":
                prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")

        prompt_parts.append("Assistant:")
        return "\n".join(prompt_parts)

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        """Generate streaming response.

        Args:
            messages: Conversation history.
            system_prompt: Optional system prompt.
            temperature: Sampling temperature (overrides config).
            max_tokens: Maximum tokens to generate (overrides config).
            **kwargs: Additional generation parameters.

        Yields:
            LLMChunk objects with text tokens.
        """
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("Model not loaded. Call connect() first.")

        # Build prompt
        prompt = self._build_prompt(messages, system_prompt)

        # Generation parameters
        gen_kwargs = {
            "max_new_tokens": max_tokens or self._llm_config.max_new_tokens,
            "temperature": temperature or self._llm_config.temperature,
            "top_p": self._llm_config.top_p,
            "top_k": self._llm_config.top_k,
            "do_sample": self._llm_config.do_sample,
            "repetition_penalty": self._llm_config.repetition_penalty,
            "pad_token_id": self._tokenizer.pad_token_id,
            "eos_token_id": self._tokenizer.eos_token_id,
        }

        # Override with kwargs
        gen_kwargs.update(kwargs)

        # Use generation lock to prevent concurrent generation
        async with self._generation_lock:
            start_time = time.perf_counter()

            try:
                # Run generation in thread
                async for text in self._generate_stream_threaded(prompt, gen_kwargs):
                    yield LLMChunk(text=text, is_final=False)

                latency_ms = (time.perf_counter() - start_time) * 1000
                self._metrics.record_success(latency_ms)

                yield LLMChunk(text="", is_final=True, finish_reason="stop")

            except Exception as e:
                self._metrics.record_failure(str(e))
                raise

    async def _generate_stream_threaded(
        self,
        prompt: str,
        gen_kwargs: dict,
    ) -> AsyncIterator[str]:
        """Run streaming generation in thread.

        Uses TextIteratorStreamer to stream tokens from transformers.
        """
        try:
            from transformers import TextIteratorStreamer
            import torch
        except ImportError:
            raise ImportError("transformers is required")

        # Create streamer
        streamer = TextIteratorStreamer(
            self._tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )

        # Tokenize input
        inputs = self._tokenizer(prompt, return_tensors="pt")

        # Move to model device
        if hasattr(self._model, "device"):
            inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

        # Start generation in thread
        generation_kwargs = {
            **inputs,
            **gen_kwargs,
            "streamer": streamer,
        }

        loop = asyncio.get_event_loop()

        def generate():
            with torch.no_grad():
                self._model.generate(**generation_kwargs)

        # Start generation
        future = loop.run_in_executor(self._executor, generate)

        # Stream tokens
        try:
            for text in streamer:
                if text:
                    yield text
                # Allow other tasks to run
                await asyncio.sleep(0)
        finally:
            # Ensure generation completes
            await future

    async def generate(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> str:
        """Generate complete response.

        Args:
            messages: Conversation history.
            system_prompt: Optional system prompt.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters.

        Returns:
            Complete response text.
        """
        chunks = []
        async for chunk in self.generate_stream(
            messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            chunks.append(chunk.text)

        return "".join(chunks)

    def supports_tools(self) -> bool:
        """Check if this LLM supports tool calling.

        Returns:
            False - HuggingFace models generally don't support tool calling natively.
        """
        return False

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"HuggingFaceLLMProvider("
            f"model={self._llm_config.model!r}, "
            f"quantization={self._llm_config.quantization.value!r}, "
            f"device={self._llm_config.device!r}, "
            f"connected={self._connected})"
        )
