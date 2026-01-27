"""LLM (Large Language Model) interface."""

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, Union

from voice_pipeline.runnable import RunnableConfig, VoiceRunnable


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


@dataclass
class LLMResponse:
    """Complete response from LLM (non-streaming).

    Used when calling generate_with_tools() to get both
    content and tool calls in a single response.

    Attributes:
        content: Text content of the response.
        tool_calls: List of tool calls in OpenAI format.
        finish_reason: Reason for finishing.
        usage: Token usage statistics.

    Example:
        >>> response = await llm.generate_with_tools(messages, tools)
        >>> if response.tool_calls:
        ...     # Execute tools
        ...     for call in response.tool_calls:
        ...         result = await execute(call)
        ... else:
        ...     # Final response
        ...     print(response.content)
    """

    content: str = ""
    """Text content of the response."""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    """Tool calls in OpenAI format (list of {id, type, function})."""

    finish_reason: Optional[str] = None
    """Reason for finishing (stop, tool_calls, length, etc.)."""

    usage: Optional[dict[str, int]] = None
    """Token usage statistics (prompt_tokens, completion_tokens, total_tokens)."""

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls.

        Returns:
            True if there are tool calls to execute.
        """
        return bool(self.tool_calls)


# Tipo de entrada para LLM
# - lista de mensagens
# - string (será convertida para mensagem de usuário)
# - TranscriptionResult (extrai o texto)
# - dict com messages e outras opções
LLMInput = Union[list[dict[str, str]], str, dict[str, Any]]


class LLMInterface(VoiceRunnable[LLMInput, str]):
    """Interface for LLM providers.

    Implementations should generate text responses, supporting
    streaming for low-latency voice applications.

    This interface extends VoiceRunnable, allowing composition with
    the | operator:
        >>> chain = asr | llm | tts
        >>> result = await chain.ainvoke(audio_bytes)

    Example implementation:
        class MyLLM(LLMInterface):
            async def generate_stream(self, messages, system_prompt=None, **kwargs):
                async for token in call_llm_api(messages):
                    yield LLMChunk(text=token)
    """

    name: str = "LLM"

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stop: Optional[list[str]] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        """Generate streaming response.

        Args:
            messages: Conversation history [{"role": "user/assistant", "content": "..."}].
            system_prompt: Optional system prompt.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
            stop: Optional list of stop sequences that will halt generation.
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
        stop: Optional[list[str]] = None,
        **kwargs,
    ) -> str:
        """Generate complete response.

        Default implementation collects stream results.

        Args:
            messages: Conversation history.
            system_prompt: Optional system prompt.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            stop: Optional list of stop sequences that will halt generation.
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
            stop=stop,
            **kwargs,
        ):
            chunks.append(chunk.text)

        return "".join(chunks)

    # ==================== Tool Calling Support ====================

    async def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> "LLMResponse":
        """Generate response with tool calling support.

        This method allows the LLM to decide whether to call tools
        or generate a direct response. Implementations should override
        this method for actual tool calling support.

        Args:
            messages: Conversation history (may include tool results).
            tools: List of tool schemas in OpenAI format.
            system_prompt: Optional system prompt.
            tool_choice: Tool selection mode:
                - "auto": LLM decides whether to use tools.
                - "none": Never use tools.
                - "required": Must use at least one tool.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional provider-specific parameters.

        Returns:
            LLMResponse with content and/or tool_calls.

        Raises:
            NotImplementedError: If the LLM doesn't support tools.

        Example:
            >>> tools = [
            ...     {
            ...         "type": "function",
            ...         "function": {
            ...             "name": "get_weather",
            ...             "description": "Get weather for a location",
            ...             "parameters": {
            ...                 "type": "object",
            ...                 "properties": {
            ...                     "location": {"type": "string"}
            ...                 },
            ...                 "required": ["location"]
            ...             }
            ...         }
            ...     }
            ... ]
            >>>
            >>> response = await llm.generate_with_tools(messages, tools)
            >>> if response.has_tool_calls:
            ...     # Process tool calls
            ...     pass
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support tool calling. "
            "Implement generate_with_tools() to enable tools."
        )

    def supports_tools(self) -> bool:
        """Check if this LLM implementation supports tool calling.

        Subclasses that implement generate_with_tools() should
        override this to return True.

        Returns:
            True if tool calling is supported, False otherwise.
        """
        return False

    # ==================== VoiceRunnable Implementation ====================

    def _normalize_input(
        self, input: LLMInput, config: Optional[RunnableConfig]
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """Normalize various input formats to messages and kwargs.

        Args:
            input: Various input formats.
            config: Optional configuration.

        Returns:
            Tuple of (messages, kwargs).
        """
        kwargs: dict[str, Any] = {}

        # Extrai configurações da config
        if config and config.configurable:
            if "system_prompt" in config.configurable:
                kwargs["system_prompt"] = config.configurable["system_prompt"]
            if "temperature" in config.configurable:
                kwargs["temperature"] = config.configurable["temperature"]
            if "max_tokens" in config.configurable:
                kwargs["max_tokens"] = config.configurable["max_tokens"]
            if "stop" in config.configurable:
                kwargs["stop"] = config.configurable["stop"]

        # Normaliza input para messages
        if isinstance(input, list):
            # Já é lista de mensagens
            messages = input
        elif isinstance(input, str):
            # String simples -> mensagem de usuário
            messages = [{"role": "user", "content": input}]
        elif isinstance(input, dict):
            # Dict pode ter 'messages' ou 'text' ou ser TranscriptionResult-like
            if "messages" in input:
                messages = input["messages"]
                # Extrai kwargs adicionais do dict
                for key in ["system_prompt", "temperature", "max_tokens"]:
                    if key in input:
                        kwargs[key] = input[key]
            elif "text" in input:
                # TranscriptionResult ou similar
                messages = [{"role": "user", "content": input["text"]}]
            elif "content" in input:
                messages = [{"role": "user", "content": input["content"]}]
            else:
                # Tenta converter para string
                messages = [{"role": "user", "content": str(input)}]
        elif hasattr(input, "text"):
            # Objeto com atributo .text (como TranscriptionResult)
            messages = [{"role": "user", "content": input.text}]
        else:
            # Fallback: converte para string
            messages = [{"role": "user", "content": str(input)}]

        return messages, kwargs

    async def ainvoke(
        self,
        input: LLMInput,
        config: Optional[RunnableConfig] = None,
    ) -> str:
        """Execute LLM on input.

        This is the VoiceRunnable interface method that enables
        composition with the | operator.

        Args:
            input: Messages, string, or TranscriptionResult.
            config: Optional configuration with callbacks.

        Returns:
            Generated text response.
        """
        messages, kwargs = self._normalize_input(input, config)
        return await self.generate(messages, **kwargs)

    async def astream(
        self,
        input: LLMInput,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[LLMChunk]:
        """Stream LLM response.

        Args:
            input: Messages, string, or TranscriptionResult.
            config: Optional configuration.

        Yields:
            LLMChunk objects with text tokens.
        """
        messages, kwargs = self._normalize_input(input, config)
        async for chunk in self.generate_stream(messages, **kwargs):
            yield chunk
