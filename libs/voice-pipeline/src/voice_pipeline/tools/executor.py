"""Tool executor for voice agents.

Manages tool registration and execution for voice-based function calling.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Union

from voice_pipeline.tools.base import FunctionTool, ToolResult, VoiceTool


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""

    id: str
    """Unique call identifier."""

    name: str
    """Tool name to execute."""

    arguments: dict[str, Any]
    """Tool arguments."""

    @classmethod
    def from_openai(cls, call: dict[str, Any]) -> "ToolCall":
        """Create from OpenAI function call format.

        Args:
            call: OpenAI tool_call object.

        Returns:
            ToolCall instance.
        """
        func = call.get("function", call)
        raw_args = func.get("arguments", "{}")
        if isinstance(raw_args, str):
            arguments = json.loads(raw_args)
        elif isinstance(raw_args, dict):
            arguments = raw_args
        else:
            arguments = {}
        return cls(
            id=call.get("id", ""),
            name=func.get("name", ""),
            arguments=arguments,
        )

    @classmethod
    def from_anthropic(cls, block: dict[str, Any]) -> "ToolCall":
        """Create from Anthropic tool_use block.

        Args:
            block: Anthropic tool_use content block.

        Returns:
            ToolCall instance.
        """
        return cls(
            id=block.get("id", ""),
            name=block.get("name", ""),
            arguments=block.get("input", {}),
        )


@dataclass
class ToolExecutor:
    """Executes tools for voice agents.

    Manages a collection of tools and handles execution
    based on LLM function calling requests.

    Example:
        >>> from voice_pipeline.tools import voice_tool, ToolExecutor
        >>>
        >>> @voice_tool
        ... def get_time() -> str:
        ...     return datetime.now().strftime("%H:%M")
        >>>
        >>> @voice_tool
        ... def calculate(expression: str) -> float:
        ...     return eval(expression)  # Use safely in production!
        >>>
        >>> executor = ToolExecutor(tools=[get_time, calculate])
        >>>
        >>> # Execute a tool call
        >>> result = await executor.execute("get_time", {})
        >>> print(result.output)  # "14:30"

    Attributes:
        tools: Dictionary of registered tools.
        default_timeout: Default timeout for tool execution.
    """

    tools: dict[str, VoiceTool] = field(default_factory=dict)
    """Registered tools by name."""

    default_timeout: float = 30.0
    """Default execution timeout."""

    def __init__(
        self,
        tools: Optional[Sequence[VoiceTool]] = None,
        default_timeout: float = 30.0,
    ):
        """Initialize executor.

        Args:
            tools: Initial tools to register.
            default_timeout: Default timeout for execution.
        """
        self.tools = {}
        self.default_timeout = default_timeout

        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: VoiceTool, overwrite: bool = False) -> None:
        """Register a tool.

        Args:
            tool: Tool to register.
            overwrite: If True, allows overwriting an existing tool.

        Raises:
            ValueError: If a tool with the same name is already registered
                and overwrite is False.
        """
        if tool.name and tool.name in self.tools and not overwrite:
            raise ValueError(
                f"Tool '{tool.name}' is already registered. "
                f"Use overwrite=True to replace it."
            )
        self.tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool.

        Args:
            name: Tool name to remove.
        """
        self.tools.pop(name, None)

    def get(self, name: str) -> Optional[VoiceTool]:
        """Get a tool by name.

        Args:
            name: Tool name.

        Returns:
            Tool instance or None.
        """
        return self.tools.get(name)

    def list_tools(self) -> list[str]:
        """List registered tool names.

        Returns:
            List of tool names.
        """
        return list(self.tools.keys())

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """Execute a tool by name.

        Args:
            name: Tool name.
            arguments: Tool arguments.

        Returns:
            ToolResult from execution.
        """
        tool = self.tools.get(name)

        if tool is None:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool '{name}' not found",
            )

        return await tool.execute(**arguments)

    async def execute_call(self, call: ToolCall) -> ToolResult:
        """Execute a ToolCall.

        Args:
            call: ToolCall to execute.

        Returns:
            ToolResult from execution.
        """
        return await self.execute(call.name, call.arguments)

    async def execute_many(
        self,
        calls: Sequence[ToolCall],
        parallel: bool = True,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> list[ToolResult]:
        """Execute multiple tool calls.

        Args:
            calls: Tool calls to execute.
            parallel: Whether to run in parallel.
            cancel_event: Optional event that, when set, cancels pending
                tool executions. Already-completed results are preserved.

        Returns:
            List of results in same order as calls. Cancelled tools
            return an error ToolResult.
        """
        if not calls:
            return []

        if parallel:
            if cancel_event is not None:
                return await self._execute_parallel_with_cancel(calls, cancel_event)
            # Without cancel_event, use return_exceptions to prevent
            # one failure from killing the others
            tasks = [self.execute_call(call) for call in calls]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)
            return [
                r if isinstance(r, ToolResult) else ToolResult(
                    success=False,
                    output=None,
                    error=f"Tool execution failed: {r}",
                )
                for r in raw_results
            ]
        else:
            results: list[ToolResult] = []
            for call in calls:
                if cancel_event is not None and cancel_event.is_set():
                    results.append(ToolResult(
                        success=False,
                        output=None,
                        error="Cancelled",
                    ))
                    continue
                result = await self.execute_call(call)
                results.append(result)
            return results

    async def _execute_parallel_with_cancel(
        self,
        calls: Sequence[ToolCall],
        cancel_event: asyncio.Event,
    ) -> list[ToolResult]:
        """Execute tool calls in parallel with cancellation support.

        Monitors ``cancel_event`` alongside running tasks.  When the
        event is set, pending tasks are cancelled and receive an error
        result.
        """
        tasks = [
            asyncio.create_task(self.execute_call(call))
            for call in calls
        ]
        cancel_waiter = asyncio.create_task(cancel_event.wait())

        results: list[Optional[ToolResult]] = [None] * len(tasks)
        pending = set(tasks)
        pending.add(cancel_waiter)

        try:
            while pending - {cancel_waiter}:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED,
                )

                if cancel_waiter in done:
                    # Cancel all remaining tool tasks
                    for t in pending:
                        t.cancel()
                    # Wait for cancellations to settle
                    if pending:
                        await asyncio.wait(pending)
                    break

                for t in done:
                    if t is cancel_waiter:
                        continue
                    idx = tasks.index(t)
                    exc = t.exception()
                    if exc is not None:
                        results[idx] = ToolResult(
                            success=False,
                            output=None,
                            error=f"Tool execution failed: {exc}",
                        )
                    else:
                        results[idx] = t.result()
        finally:
            cancel_waiter.cancel()
            try:
                await cancel_waiter
            except asyncio.CancelledError:
                pass

        # Fill in cancelled slots
        for i, r in enumerate(results):
            if r is None:
                results[i] = ToolResult(
                    success=False,
                    output=None,
                    error="Cancelled",
                )

        return results  # type: ignore[return-value]

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Get tools in OpenAI function calling format.

        Returns:
            List of tool schemas for OpenAI API.
        """
        return [tool.to_openai_schema() for tool in self.tools.values()]

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        """Get tools in Anthropic tool use format.

        Returns:
            List of tool schemas for Anthropic API.
        """
        return [tool.to_anthropic_schema() for tool in self.tools.values()]

    def format_result_for_llm(
        self,
        call: ToolCall,
        result: ToolResult,
        format: str = "openai",
    ) -> dict[str, Any]:
        """Format tool result for LLM consumption.

        Args:
            call: The original tool call.
            result: The execution result.
            format: Output format ("openai" or "anthropic").

        Returns:
            Formatted result for LLM.
        """
        if format == "openai":
            return {
                "role": "tool",
                "tool_call_id": call.id,
                "content": str(result),
            }
        else:  # anthropic
            return {
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": str(result),
                "is_error": not result.success,
            }


def create_executor(*tools: VoiceTool) -> ToolExecutor:
    """Create a ToolExecutor with given tools.

    Args:
        *tools: Tools to register.

    Returns:
        Configured ToolExecutor.
    """
    return ToolExecutor(tools=list(tools))
