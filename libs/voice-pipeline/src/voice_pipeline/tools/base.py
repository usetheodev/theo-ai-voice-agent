"""Base classes for voice tools.

Tools allow voice agents to perform actions and access external systems.
"""

from __future__ import annotations

import asyncio
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Optional, get_type_hints

if TYPE_CHECKING:
    from voice_pipeline.tools.permissions import PermissionLevel


@dataclass
class ToolParameter:
    """Description of a tool parameter.

    Used for generating function calling schemas.
    """

    name: str
    """Parameter name."""

    type: str
    """Parameter type (string, number, boolean, etc.)."""

    description: str = ""
    """Description of the parameter."""

    required: bool = True
    """Whether the parameter is required."""

    default: Any = None
    """Default value if not required."""

    enum: Optional[list[str]] = None
    """Allowed values for enum types."""


@dataclass
class ToolResultChunk:
    """A chunk of streaming tool output.

    Used for tools that produce incremental results, allowing
    the voice agent to start speaking before the tool finishes.

    Example:
        >>> async def search_stream(**kwargs) -> AsyncIterator[ToolResultChunk]:
        ...     yield ToolResultChunk(text="Searching...")
        ...     results = await do_search()
        ...     yield ToolResultChunk(text=f"Found {len(results)} results.")
        ...     yield ToolResultChunk(text=results[0], is_final=True)
    """

    text: str = ""
    """Partial text output."""

    is_final: bool = False
    """Whether this is the final chunk."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional chunk metadata."""


@dataclass
class ToolResult:
    """Result from tool execution."""

    success: bool
    """Whether the tool executed successfully."""

    output: Any
    """Tool output (for LLM consumption)."""

    error: Optional[str] = None
    """Error message if failed."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional result metadata."""

    def __str__(self) -> str:
        """String representation for LLM."""
        if self.success:
            return str(self.output)
        return f"Error: {self.error}"


@dataclass
class VoiceTool(ABC):
    """Base class for voice agent tools.

    Tools are actions that voice agents can take, such as:
    - Getting the current time
    - Scheduling a meeting
    - Searching for information
    - Controlling smart home devices

    Tools are designed to work with LLM function calling:
    1. Tool definitions are sent to the LLM
    2. LLM decides to call a tool with arguments
    3. Tool executes and returns result
    4. Result is fed back to LLM

    Example:
        >>> class GetWeatherTool(VoiceTool):
        ...     name = "get_weather"
        ...     description = "Get current weather for a location"
        ...
        ...     async def execute(self, location: str) -> ToolResult:
        ...         weather = await fetch_weather(location)
        ...         return ToolResult(success=True, output=weather)
        >>>
        >>> tool = GetWeatherTool()
        >>> schema = tool.to_openai_schema()
        >>> result = await tool.execute(location="New York")
    """

    name: str = ""
    """Unique tool name (used in function calling)."""

    description: str = ""
    """Description of what the tool does."""

    parameters: list[ToolParameter] = field(default_factory=list)
    """Tool parameters."""

    return_direct: bool = False
    """If True, return tool output directly without LLM processing."""

    timeout_seconds: float = 30.0
    """Maximum execution time in seconds."""

    permission_level: Optional["PermissionLevel"] = None
    """Permission level for this tool. Used by ToolPermissionChecker."""

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given arguments.

        Args:
            **kwargs: Tool-specific arguments.

        Returns:
            ToolResult with success status and output.
        """
        pass

    async def execute_stream(self, **kwargs) -> AsyncIterator[ToolResultChunk]:
        """Execute the tool with streaming output.

        Override this method to provide incremental results for long-running
        tools. The default implementation calls execute() and yields the
        result as a single final chunk.

        This is useful for voice AI where the agent can start speaking
        partial results while the tool continues executing.

        Args:
            **kwargs: Tool-specific arguments.

        Yields:
            ToolResultChunk with partial or final output.

        Example:
            >>> class WebSearchTool(VoiceTool):
            ...     async def execute_stream(self, query: str):
            ...         yield ToolResultChunk(text="Searching the web...")
            ...         results = await self._search(query)
            ...         yield ToolResultChunk(
            ...             text=f"Found: {results}",
            ...             is_final=True,
            ...         )
        """
        # Default: call execute() and yield as single chunk
        result = await self.execute(**kwargs)
        if result.success:
            yield ToolResultChunk(
                text=str(result.output),
                is_final=True,
                metadata=result.metadata,
            )
        else:
            yield ToolResultChunk(
                text=f"Error: {result.error}",
                is_final=True,
                metadata={"error": True, **result.metadata},
            )

    def supports_streaming(self) -> bool:
        """Check if this tool supports streaming output.

        Returns True if execute_stream() is overridden.

        Returns:
            True if streaming is supported.
        """
        # Check if execute_stream is overridden
        return type(self).execute_stream is not VoiceTool.execute_stream

    async def __call__(self, **kwargs) -> ToolResult:
        """Convenience method to execute tool."""
        return await self.execute(**kwargs)

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert tool to OpenAI function calling schema.

        Returns:
            Dictionary compatible with OpenAI function calling.
        """
        properties = {}
        required = []

        for param in self.parameters:
            prop = {"type": param.type, "description": param.description}
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_anthropic_schema(self) -> dict[str, Any]:
        """Convert tool to Anthropic tool use schema.

        Returns:
            Dictionary compatible with Anthropic tool use.
        """
        properties = {}
        required = []

        for param in self.parameters:
            prop = {"type": param.type, "description": param.description}
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


class FunctionTool(VoiceTool):
    """Tool wrapper for regular Python functions.

    Wraps sync or async functions as VoiceTool instances.
    Parameters are inferred from function signature.

    Example:
        >>> def get_time() -> str:
        ...     return datetime.now().strftime("%H:%M")
        >>>
        >>> tool = FunctionTool.from_function(
        ...     get_time,
        ...     name="get_time",
        ...     description="Get current time",
        ... )
    """

    def __init__(
        self,
        func: Callable,
        name: str,
        description: str,
        parameters: Optional[list[ToolParameter]] = None,
        return_direct: bool = False,
        timeout_seconds: float = 30.0,
        permission_level: Optional["PermissionLevel"] = None,
    ):
        """Initialize function tool.

        Args:
            func: The function to wrap.
            name: Tool name.
            description: Tool description.
            parameters: Parameter definitions (auto-inferred if None).
            return_direct: Whether to return directly.
            timeout_seconds: Execution timeout.
            permission_level: Permission level for this tool.
        """
        self._func = func
        self.name = name
        self.description = description
        self.return_direct = return_direct
        self.timeout_seconds = timeout_seconds
        self.permission_level = permission_level

        if parameters is not None:
            self.parameters = parameters
        else:
            self.parameters = self._infer_parameters()

    def _infer_parameters(self) -> list[ToolParameter]:
        """Infer parameters from function signature."""
        sig = inspect.signature(self._func)
        hints = get_type_hints(self._func) if hasattr(self._func, "__annotations__") else {}
        params = []

        for name, param in sig.parameters.items():
            if name in ("self", "cls"):
                continue

            # Determine type
            type_hint = hints.get(name, str)
            param_type = self._python_type_to_json(type_hint)

            # Determine if required
            has_default = param.default is not inspect.Parameter.empty

            params.append(
                ToolParameter(
                    name=name,
                    type=param_type,
                    description=f"Parameter {name}",
                    required=not has_default,
                    default=param.default if has_default else None,
                )
            )

        return params

    @staticmethod
    def _python_type_to_json(python_type) -> str:
        """Convert Python type to JSON schema type."""
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }

        # Handle Optional and other typing constructs
        origin = getattr(python_type, "__origin__", None)
        if origin is not None:
            # Handle Union types (including Optional)
            if hasattr(python_type, "__args__"):
                # Get the first non-None type
                for arg in python_type.__args__:
                    if arg is not type(None):
                        return FunctionTool._python_type_to_json(arg)

        return type_map.get(python_type, "string")

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the wrapped function.

        Args:
            **kwargs: Function arguments.

        Returns:
            ToolResult with function output.
        """
        try:
            # Apply timeout
            if asyncio.iscoroutinefunction(self._func):
                result = await asyncio.wait_for(
                    self._func(**kwargs),
                    timeout=self.timeout_seconds,
                )
            else:
                # Run sync function in thread
                result = await asyncio.wait_for(
                    asyncio.to_thread(self._func, **kwargs),
                    timeout=self.timeout_seconds,
                )

            return ToolResult(success=True, output=result)

        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool {self.name} timed out after {self.timeout_seconds}s",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=str(e),
            )

    async def execute_stream(self, **kwargs) -> AsyncIterator[ToolResultChunk]:
        """Execute the wrapped function with streaming support.

        If the wrapped function is an async generator, yields chunks
        from it. Otherwise, falls back to execute().

        Args:
            **kwargs: Function arguments.

        Yields:
            ToolResultChunk with partial or final output.
        """
        try:
            if inspect.isasyncgenfunction(self._func):
                # Function is an async generator - stream its output
                collected: list[str] = []
                async for chunk in self._func(**kwargs):
                    if isinstance(chunk, ToolResultChunk):
                        yield chunk
                    else:
                        # Convert raw output to chunk
                        text = str(chunk)
                        collected.append(text)
                        yield ToolResultChunk(text=text)

                # Yield final chunk
                yield ToolResultChunk(
                    text="",
                    is_final=True,
                    metadata={"full_output": "".join(collected)},
                )
            else:
                # Not a generator - use default behavior
                async for chunk in super().execute_stream(**kwargs):
                    yield chunk

        except asyncio.TimeoutError:
            yield ToolResultChunk(
                text=f"Error: Tool {self.name} timed out after {self.timeout_seconds}s",
                is_final=True,
                metadata={"error": True},
            )
        except Exception as e:
            yield ToolResultChunk(
                text=f"Error: {str(e)}",
                is_final=True,
                metadata={"error": True},
            )

    def supports_streaming(self) -> bool:
        """Check if this tool supports streaming output.

        Returns True if the wrapped function is an async generator.
        """
        return inspect.isasyncgenfunction(self._func)

    @classmethod
    def from_function(
        cls,
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs,
    ) -> "FunctionTool":
        """Create FunctionTool from a callable.

        Args:
            func: Function to wrap.
            name: Tool name (defaults to function name).
            description: Tool description (defaults to docstring).
            **kwargs: Additional arguments.

        Returns:
            FunctionTool instance.
        """
        tool_name = name or func.__name__
        tool_desc = description or func.__doc__ or f"Execute {tool_name}"

        return cls(func=func, name=tool_name, description=tool_desc, **kwargs)
