"""Tool executor for voice agents.

Manages tool registration and execution for voice-based function calling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, Sequence, Union

from voice_pipeline.tools.base import FunctionTool, ToolResult, VoiceTool

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from voice_pipeline.tools.permissions import ToolPermissionChecker


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

    permission_checker: Optional["ToolPermissionChecker"] = None
    """Optional permission checker for access control."""

    def __init__(
        self,
        tools: Optional[Sequence[VoiceTool]] = None,
        default_timeout: float = 30.0,
        permission_checker: Optional["ToolPermissionChecker"] = None,
    ):
        """Initialize executor.

        Args:
            tools: Initial tools to register.
            default_timeout: Default timeout for execution.
            permission_checker: Optional permission checker for access control.
                If provided, all tool calls are checked before execution.
        """
        self.tools = {}
        self.default_timeout = default_timeout
        self.permission_checker = permission_checker

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
        skip_permission_check: bool = False,
        timeout: Optional[float] = None,
    ) -> ToolResult:
        """Execute a tool by name.

        Args:
            name: Tool name.
            arguments: Tool arguments.
            skip_permission_check: If True, bypasses permission checking.
            timeout: Execution timeout in seconds. Uses default_timeout if None.

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

        # Check permissions if checker is configured
        if self.permission_checker and not skip_permission_check:
            check_result = self.permission_checker.check(
                tool_name=name,
                args=arguments,
                tool_level=tool.permission_level,
            )

            if not check_result.allowed:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Permission denied: {check_result.reason}",
                    metadata={"permission_denied": True},
                )

            if check_result.requires_confirmation:
                # Try to get confirmation
                confirm_result = await self.permission_checker.check_with_confirmation(
                    tool_name=name,
                    args=arguments,
                    tool_level=tool.permission_level,
                )
                if not confirm_result.allowed:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Permission denied: {confirm_result.reason}",
                        metadata={"permission_denied": True},
                    )

            # Record the call for rate limiting
            self.permission_checker.record_call(name)

        # Execute with timeout
        exec_timeout = timeout if timeout is not None else self.default_timeout
        try:
            return await asyncio.wait_for(
                tool.execute(**arguments),
                timeout=exec_timeout,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool '{name}' execution timed out after {exec_timeout}s",
                metadata={"timeout": True},
            )

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
            results = []
            for i, r in enumerate(raw_results):
                if isinstance(r, ToolResult):
                    results.append(r)
                else:
                    # r is an exception - capture full traceback
                    exc_type = type(r).__name__
                    exc_tb = "".join(traceback.format_exception(type(r), r, r.__traceback__))
                    tool_name = calls[i].name if i < len(calls) else "unknown"

                    logger.error(
                        f"Tool '{tool_name}' failed with {exc_type}: {r}\n{exc_tb}"
                    )

                    results.append(ToolResult(
                        success=False,
                        output=None,
                        error=f"Tool execution failed: {r}",
                        metadata={
                            "exception_type": exc_type,
                            "traceback": exc_tb,
                        },
                    ))
            return results
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
                        # Capture full traceback
                        exc_type = type(exc).__name__
                        exc_tb = "".join(
                            traceback.format_exception(type(exc), exc, exc.__traceback__)
                        )
                        tool_name = calls[idx].name if idx < len(calls) else "unknown"

                        logger.error(
                            f"Tool '{tool_name}' failed with {exc_type}: {exc}\n{exc_tb}"
                        )

                        results[idx] = ToolResult(
                            success=False,
                            output=None,
                            error=f"Tool execution failed: {exc}",
                            metadata={
                                "exception_type": exc_type,
                                "traceback": exc_tb,
                            },
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
