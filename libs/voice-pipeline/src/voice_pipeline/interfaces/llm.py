"""LLM (Large Language Model) interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional


@dataclass
class LLMChunk:
    """Chunk from LLM streaming response."""

    text: str
    """Text content of this chunk."""

    is_final: bool = False
    """Whether this is the final chunk."""

    finish_reason: Optional[str] = None
    """Reason for finishing (stop, length, etc.)."""

    usage: Optional[dict] = None
    """Token usage statistics (if available)."""


class LLMInterface(ABC):
    """Interface for LLM providers.

    Implementations should generate text responses, supporting
    streaming for low-latency voice applications.

    Example:
        class MyLLM(LLMInterface):
            async def generate_stream(self, messages, system_prompt=None, **kwargs):
                async for token in call_llm_api(messages):
                    yield LLMChunk(text=token)
    """

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        """Generate streaming response.

        Args:
            messages: Conversation history [{"role": "user/assistant", "content": "..."}].
            system_prompt: Optional system prompt.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional provider-specific parameters.

        Yields:
            LLMChunk objects with text tokens.
        """
        pass

    async def generate(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> str:
        """Generate complete response.

        Default implementation collects stream results.

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
