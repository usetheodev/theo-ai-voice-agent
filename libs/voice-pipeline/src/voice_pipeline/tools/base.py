"""Base classes for voice tools.

Tools allow voice agents to perform actions and access external systems.
"""

import asyncio
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, get_type_hints


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

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given arguments.

        Args:
            **kwargs: Tool-specific arguments.

        Returns:
            ToolResult with success status and output.
        """
        pass

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
    ):
        """Initialize function tool.

        Args:
            func: The function to wrap.
            name: Tool name.
            description: Tool description.
            parameters: Parameter definitions (auto-inferred if None).
            return_direct: Whether to return directly.
            timeout_seconds: Execution timeout.
        """
        self._func = func
        self.name = name
        self.description = description
        self.return_direct = return_direct
        self.timeout_seconds = timeout_seconds

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
                # Run sync function in executor
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: self._func(**kwargs)),
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
