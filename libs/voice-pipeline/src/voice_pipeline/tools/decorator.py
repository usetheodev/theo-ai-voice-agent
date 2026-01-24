"""Decorator for creating voice tools.

The @voice_tool decorator provides a convenient way to create tools
from regular Python functions.
"""

from typing import Callable, Optional, TypeVar, Union, overload

from voice_pipeline.tools.base import FunctionTool, ToolParameter

F = TypeVar("F", bound=Callable)


@overload
def voice_tool(func: F) -> FunctionTool: ...


@overload
def voice_tool(
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    return_direct: bool = False,
    timeout_seconds: float = 30.0,
    parameters: Optional[list[ToolParameter]] = None,
) -> Callable[[F], FunctionTool]: ...


def voice_tool(
    func: Optional[F] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    return_direct: bool = False,
    timeout_seconds: float = 30.0,
    parameters: Optional[list[ToolParameter]] = None,
) -> Union[FunctionTool, Callable[[F], FunctionTool]]:
    """Decorator to create a voice tool from a function.

    Can be used with or without arguments:

    Example (without arguments):
        >>> @voice_tool
        ... def get_time() -> str:
        ...     '''Get the current time.'''
        ...     return datetime.now().strftime("%H:%M")

    Example (with arguments):
        >>> @voice_tool(
        ...     name="get_weather",
        ...     description="Get weather for a location",
        ... )
        ... async def get_weather(location: str) -> str:
        ...     return await fetch_weather(location)

    Args:
        func: Function to wrap (when used without parentheses).
        name: Tool name (defaults to function name).
        description: Tool description (defaults to docstring).
        return_direct: If True, return output without LLM processing.
        timeout_seconds: Maximum execution time.
        parameters: Parameter definitions (auto-inferred if None).

    Returns:
        FunctionTool wrapping the function.
    """

    def decorator(fn: F) -> FunctionTool:
        return FunctionTool.from_function(
            fn,
            name=name,
            description=description,
            return_direct=return_direct,
            timeout_seconds=timeout_seconds,
            parameters=parameters,
        )

    if func is not None:
        # Used without parentheses: @voice_tool
        return decorator(func)
    else:
        # Used with parentheses: @voice_tool(...)
        return decorator


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    return_direct: bool = False,
    timeout_seconds: float = 30.0,
) -> Callable[[F], FunctionTool]:
    """Alias for @voice_tool decorator.

    Example:
        >>> @tool(description="Get current time")
        ... def get_time() -> str:
        ...     return datetime.now().strftime("%H:%M")

    Args:
        name: Tool name (defaults to function name).
        description: Tool description.
        return_direct: If True, return output without LLM processing.
        timeout_seconds: Maximum execution time.

    Returns:
        Decorator that creates a FunctionTool.
    """
    return voice_tool(
        name=name,
        description=description,
        return_direct=return_direct,
        timeout_seconds=timeout_seconds,
    )
