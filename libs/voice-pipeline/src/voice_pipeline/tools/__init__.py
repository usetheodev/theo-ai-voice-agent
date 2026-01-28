"""Voice Tools for function calling.

Tools allow voice agents to perform actions and access external systems.

Quick Start:
    >>> from voice_pipeline.tools import voice_tool, ToolExecutor
    >>>
    >>> @voice_tool(description="Get current time")
    ... def get_time() -> str:
    ...     from datetime import datetime
    ...     return datetime.now().strftime("%H:%M")
    >>>
    >>> executor = ToolExecutor(tools=[get_time])
    >>>
    >>> # Execute tool
    >>> result = await executor.execute("get_time", {})
    >>> print(result.output)  # "14:30"

Using with LLM Function Calling:
    >>> # Get tools in OpenAI format
    >>> tools = executor.to_openai_tools()
    >>>
    >>> # Send to LLM for function calling
    >>> response = await llm.chat(messages, tools=tools)
    >>>
    >>> # Execute any tool calls
    >>> for call in response.tool_calls:
    ...     tool_call = ToolCall.from_openai(call)
    ...     result = await executor.execute_call(tool_call)

Builtin Tools:
    >>> from voice_pipeline.tools.builtin import DATETIME_TOOLS
    >>> executor = ToolExecutor(tools=DATETIME_TOOLS)
"""

from voice_pipeline.tools.base import (
    FunctionTool,
    ToolParameter,
    ToolResult,
    ToolResultChunk,
    VoiceTool,
)
from voice_pipeline.tools.decorator import tool, voice_tool
from voice_pipeline.tools.executor import (
    ToolCall,
    ToolExecutor,
    create_executor,
)
from voice_pipeline.tools.permissions import (
    PermissionCheckResult,
    PermissionLevel,
    PermissionPolicy,
    ToolPermission,
    ToolPermissionChecker,
    create_moderate_policy,
    create_permissive_policy,
    create_safe_policy,
)

__all__ = [
    # Base
    "VoiceTool",
    "FunctionTool",
    "ToolParameter",
    "ToolResult",
    "ToolResultChunk",
    # Decorator
    "voice_tool",
    "tool",
    # Executor
    "ToolExecutor",
    "ToolCall",
    "create_executor",
    # Permissions
    "PermissionLevel",
    "PermissionPolicy",
    "ToolPermission",
    "PermissionCheckResult",
    "ToolPermissionChecker",
    "create_safe_policy",
    "create_moderate_policy",
    "create_permissive_policy",
]
