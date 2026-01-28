"""LLM (Large Language Model) providers.

Available providers:
- OpenAILLMProvider: OpenAI GPT models (GPT-4, GPT-3.5, etc.)
- AnthropicLLMProvider: Anthropic Claude models (Claude 3.5 Sonnet, Opus, Haiku)
- OllamaLLMProvider: Ollama local models (Llama, Mistral, Gemma, etc.)
- HuggingFaceLLMProvider: HuggingFace Transformers with BitsAndBytes quantization
"""

from voice_pipeline.providers.llm.openai import (
    OpenAILLMProvider,
    OpenAILLMConfig,
)
from voice_pipeline.providers.llm.anthropic import (
    AnthropicLLMProvider,
    AnthropicLLMConfig,
)
from voice_pipeline.providers.llm.ollama import (
    OllamaLLMProvider,
    OllamaLLMConfig,
)
from voice_pipeline.providers.llm.huggingface import (
    HuggingFaceLLMProvider,
    HuggingFaceLLMConfig,
    QuantizationType,
)

__all__ = [
    "OpenAILLMProvider",
    "OpenAILLMConfig",
    "AnthropicLLMProvider",
    "AnthropicLLMConfig",
    "OllamaLLMProvider",
    "OllamaLLMConfig",
    "HuggingFaceLLMProvider",
    "HuggingFaceLLMConfig",
    "QuantizationType",
]
