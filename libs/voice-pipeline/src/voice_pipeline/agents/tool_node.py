"""Tool execution node for agent pipelines.

Provides a VoiceRunnable-compatible node for executing tools,
similar to LangGraph's ToolNode.
"""

import asyncio
from typing import Optional

from voice_pipeline.agents.state import AgentState, AgentStatus
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable
from voice_pipeline.tools.base import ToolResult
from voice_pipeline.tools.executor import ToolCall, ToolExecutor


class ToolNode(VoiceRunnable[AgentState, AgentState]):
    """Executes pending tool calls in the agent state.

    A VoiceRunnable that processes tool calls from the agent state,
    executes them through the ToolExecutor, and updates the state
    with results.

    Similar to LangGraph's ToolNode - receives state with pending_tool_calls,
    executes tools, and returns updated state with results added to messages.

    Attributes:
        executor: ToolExecutor for running tools.
        parallel: Whether to run tools in parallel.
        handle_errors: Whether to catch and format errors.

    Example:
        >>> from voice_pipeline.tools import ToolExecutor, voice_tool
        >>>
        >>> @voice_tool
        ... def get_time() -> str:
        ...     return "14:30"
        >>>
        >>> executor = ToolExecutor(tools=[get_time])
        >>> tool_node = ToolNode(executor)
        >>>
        >>> # Create state with pending tool call
        >>> state = AgentState()
        >>> state.pending_tool_calls = [
        ...     ToolCall(id="1", name="get_time", arguments={})
        ... ]
        >>>
        >>> # Execute
        >>> new_state = await tool_node.ainvoke(state)
        >>> print(new_state.messages[-1].content)  # "14:30"
    """

    name: str = "ToolNode"

    def __init__(
        self,
        executor: ToolExecutor,
        parallel: bool = True,
        handle_errors: bool = True,
        cancel_event: Optional[asyncio.Event] = None,
    ):
        """Initialize ToolNode.

        Args:
            executor: ToolExecutor with registered tools.
            parallel: Run tools in parallel when possible.
            handle_errors: Catch tool errors and format as results.
            cancel_event: Optional event for cancelling tool execution.
        """
        self.executor = executor
        self.parallel = parallel
        self.handle_errors = handle_errors
        self.cancel_event = cancel_event

    async def ainvoke(
        self,
        state: AgentState,
        config: Optional[RunnableConfig] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AgentState:
        """Execute all pending tool calls in the state.

        Processes each pending tool call, executes it, and adds
        the result as a tool message to the state.

        Args:
            state: Agent state with pending_tool_calls.
            config: Optional runnable configuration.
            cancel_event: Optional event for cancelling execution.
                Overrides the instance-level cancel_event if provided.

        Returns:
            Updated state with tool results in messages.
        """
        if not state.pending_tool_calls:
            return state

        effective_cancel = cancel_event or self.cancel_event

        # Execute tools
        if self.handle_errors:
            results = await self._execute_with_error_handling(
                state.pending_tool_calls,
                cancel_event=effective_cancel,
            )
        else:
            results = await self.executor.execute_many(
                state.pending_tool_calls,
                parallel=self.parallel,
                cancel_event=effective_cancel,
            )

        # Add results to state
        for call, result in zip(state.pending_tool_calls, results):
            state.add_tool_result(
                tool_call_id=call.id,
                name=call.name,
                result=self._format_result(result),
            )

        # Clear pending calls and update status
        state.pending_tool_calls = []
        state.status = AgentStatus.OBSERVING

        return state

    async def _execute_with_error_handling(
        self,
        calls: list[ToolCall],
        cancel_event: Optional[asyncio.Event] = None,
    ) -> list[ToolResult]:
        """Execute tools with error handling.

        Args:
            calls: Tool calls to execute.
            cancel_event: Optional cancellation event.

        Returns:
            List of results (errors formatted as results).
        """
        if cancel_event is not None:
            # Delegate to executor which handles cancel natively
            return await self.executor.execute_many(
                calls,
                parallel=self.parallel,
                cancel_event=cancel_event,
            )

        if self.parallel:
            async def safe_execute(call: ToolCall) -> ToolResult:
                try:
                    return await self.executor.execute_call(call)
                except Exception as e:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Tool execution failed: {str(e)}",
                    )

            return await asyncio.gather(*[safe_execute(call) for call in calls])
        else:
            results = []
            for call in calls:
                try:
                    result = await self.executor.execute_call(call)
                except Exception as e:
                    result = ToolResult(
                        success=False,
                        output=None,
                        error=f"Tool execution failed: {str(e)}",
                    )
                results.append(result)
            return results

    def _format_result(self, result: ToolResult) -> str:
        """Format tool result for LLM consumption.

        Args:
            result: Tool execution result.

        Returns:
            Formatted string for the LLM.
        """
        if result.success:
            return str(result.output)
        return f"Error: {result.error}"


class BatchToolNode(VoiceRunnable[list[AgentState], list[AgentState]]):
    """Batch execution of tool nodes for multiple agent states.

    Useful for parallel processing of multiple agent conversations.

    Example:
        >>> batch_node = BatchToolNode(executor)
        >>> states = [state1, state2, state3]
        >>> updated_states = await batch_node.ainvoke(states)
    """

    name: str = "BatchToolNode"

    def __init__(
        self,
        executor: ToolExecutor,
        parallel: bool = True,
        handle_errors: bool = True,
    ):
        """Initialize BatchToolNode.

        Args:
            executor: ToolExecutor with registered tools.
            parallel: Run tools in parallel.
            handle_errors: Catch and format errors.
        """
        self.tool_node = ToolNode(
            executor=executor,
            parallel=parallel,
            handle_errors=handle_errors,
        )

    async def ainvoke(
        self,
        states: list[AgentState],
        config: Optional[RunnableConfig] = None,
    ) -> list[AgentState]:
        """Execute tool calls for multiple states.

        Args:
            states: List of agent states.
            config: Optional configuration.

        Returns:
            List of updated states.
        """
        import asyncio

        return await asyncio.gather(
            *[self.tool_node.ainvoke(state, config) for state in states]
        )
