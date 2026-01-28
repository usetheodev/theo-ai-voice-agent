"""Agent execution loop implementing the ReAct pattern.

ReAct (Reasoning + Acting) is a paradigm that combines reasoning
and action in LLM agents:

1. THINK: LLM reasons about what to do
2. ACT: LLM decides to call tools or respond
3. OBSERVE: Tool results are added to context
4. REPEAT: Back to step 1 until final response
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Optional

from voice_pipeline.agents.events import StateDelta, StreamEvent, StreamEventType
from voice_pipeline.agents.state import AgentState, AgentStatus
from voice_pipeline.agents.tool_node import ToolNode
from voice_pipeline.interfaces.llm import LLMInterface, LLMResponse
from voice_pipeline.tools.base import VoiceTool
from voice_pipeline.tools.executor import ToolCall, ToolExecutor
from voice_pipeline.utils.retry import RetryConfig, with_retry, LLM_RETRY_CONFIG
from voice_pipeline.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
)

if TYPE_CHECKING:
    from voice_pipeline.callbacks.base import CallbackManager, RunContext

logger = logging.getLogger(__name__)


@dataclass
class ToolFeedbackConfig:
    """Configuration for verbal feedback during tool execution.

    In voice AI applications, users shouldn't experience silence
    while tools are executing. This config defines phrases the
    agent speaks while waiting for tools to complete.

    Attributes:
        enabled: Whether to emit feedback phrases.
        phrases: List of phrases to randomly choose from.
        per_tool_phrases: Tool-specific phrases (tool_name -> phrases).
        phrase_selector: Optional custom selector function.

    Example:
        >>> config = ToolFeedbackConfig(
        ...     enabled=True,
        ...     phrases=["Let me check...", "One moment..."],
        ...     per_tool_phrases={
        ...         "web_search": ["Searching the web...", "Looking that up..."],
        ...         "get_weather": ["Checking the forecast..."],
        ...     },
        ... )
        >>> loop = AgentLoop(llm=my_llm, tool_feedback=config)
    """

    enabled: bool = True
    """Whether feedback is enabled."""

    phrases: list[str] = field(default_factory=lambda: [
        "Let me check on that.",
        "One moment please.",
        "Working on it.",
        "Let me look into that.",
    ])
    """Default phrases to use."""

    per_tool_phrases: dict[str, list[str]] = field(default_factory=dict)
    """Tool-specific phrases. Keys are tool names."""

    phrase_selector: Optional[Callable[[str, list[str]], str]] = None
    """Custom function to select a phrase. Args: (tool_name, available_phrases)."""

    def get_phrase(self, tool_name: str) -> str:
        """Get a feedback phrase for a tool.

        Args:
            tool_name: Name of the tool being executed.

        Returns:
            A feedback phrase to speak.
        """
        # Get tool-specific phrases if available
        available = self.per_tool_phrases.get(tool_name, self.phrases)
        if not available:
            available = self.phrases

        # Use custom selector if provided
        if self.phrase_selector:
            return self.phrase_selector(tool_name, available)

        # Default: random selection
        return random.choice(available)


class AgentLoop:
    """Execution loop for voice agents following the ReAct pattern.

    Orchestrates the Think → Act → Observe cycle until the agent
    produces a final response or reaches max iterations.

    Attributes:
        llm: LLM interface for generation.
        executor: Tool executor for running tools.
        tool_node: VoiceRunnable for tool execution.
        system_prompt: System prompt for the agent.
        max_iterations: Maximum loop iterations.
        stop_on_first_response: Stop when LLM responds without tools.

    Example:
        >>> from voice_pipeline.tools import voice_tool
        >>>
        >>> @voice_tool
        ... def get_time() -> str:
        ...     '''Get the current time.'''
        ...     from datetime import datetime
        ...     return datetime.now().strftime("%H:%M")
        >>>
        >>> loop = AgentLoop(
        ...     llm=my_llm,
        ...     tools=[get_time],
        ...     system_prompt="You are a helpful assistant.",
        ... )
        >>>
        >>> result = await loop.run("What time is it?")
        >>> print(result)  # "The current time is 14:30."
    """

    def __init__(
        self,
        llm: LLMInterface,
        tools: Optional[list[VoiceTool]] = None,
        system_prompt: Optional[str] = None,
        max_iterations: int = 10,
        stop_on_first_response: bool = True,
        parallel_tool_execution: bool = True,
        tool_feedback: Optional[ToolFeedbackConfig] = None,
        tool_execution_timeout: float = 30.0,
        callbacks: Optional["CallbackManager"] = None,
        retry_config: Optional[RetryConfig] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        """Initialize the agent loop.

        Args:
            llm: LLM interface for generation.
            tools: List of tools available to the agent.
            system_prompt: System prompt for the agent.
            max_iterations: Maximum iterations before stopping.
            stop_on_first_response: Stop when LLM responds without tools.
            parallel_tool_execution: Execute multiple tools in parallel.
            tool_feedback: Configuration for verbal feedback during tool execution.
                If None, no feedback is emitted. Use ToolFeedbackConfig() for defaults.
            tool_execution_timeout: Timeout in seconds for each tool execution.
            callbacks: Optional callback manager for observability events.
            retry_config: Configuration for LLM call retries. If None, uses defaults
                (3 attempts with exponential backoff).
            circuit_breaker: Optional circuit breaker for LLM calls. When open,
                LLM calls fail fast without attempting the request.
        """
        self.llm = llm
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.stop_on_first_response = stop_on_first_response
        self.tool_feedback = tool_feedback
        self.callbacks = callbacks
        self.retry_config = retry_config or LLM_RETRY_CONFIG
        self.circuit_breaker = circuit_breaker

        # Cancellation support
        self._cancel_event = asyncio.Event()

        # Set up tool execution with timeout
        self.executor = ToolExecutor(
            tools=tools or [],
            default_timeout=tool_execution_timeout,
        )
        self.tool_node = ToolNode(
            executor=self.executor,
            parallel=parallel_tool_execution,
            cancel_event=self._cancel_event,
        )

    def cancel(self) -> None:
        """Request cancellation of the current execution.

        Sets the cancel event which will:
        - Cancel pending tool executions
        - Stop the agent loop at the next iteration check

        The loop will return a partial response or error message.
        Call reset_cancel() before starting a new run.
        """
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        """Reset the cancellation state for a new run.

        Call this before starting a new run if a previous run
        was cancelled.
        """
        self._cancel_event.clear()

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested.

        Returns:
            True if cancel() was called.
        """
        return self._cancel_event.is_set()

    async def run(
        self, input: str, initial_state: Optional[AgentState] = None
    ) -> str:
        """Execute the agent loop and return the final response.

        Args:
            input: User input to process.
            initial_state: Optional pre-built state with context (e.g. memory).
                If provided, used as-is (input should already be in the state).

        Returns:
            Final response from the agent.

        Raises:
            RuntimeError: If max iterations reached without response.
        """
        # Reset cancel state for new run
        self.reset_cancel()
        start_time = time.time()

        # Create callback context if callbacks are configured
        ctx: Optional["RunContext"] = None
        if self.callbacks:
            ctx = self.callbacks.create_context(run_name="agent_run")
            await self.callbacks.on_agent_start(
                ctx, input, self.executor.list_tools()
            )

        if initial_state is not None:
            state = initial_state
        else:
            state = AgentState(max_iterations=self.max_iterations)
            state.add_user_message(input)

        try:
            while state.should_continue():
                # Check for cancellation
                if self.is_cancelled:
                    state.status = AgentStatus.ERROR
                    state.error = "Cancelled"
                    break

                # Emit iteration callback
                if self.callbacks and ctx:
                    await self.callbacks.on_agent_iteration(
                        ctx, state.iteration + 1, self.max_iterations
                    )

                # THINK + ACT: LLM generates response or tool calls
                state = await self._think_and_act(state)

                # Check if we have a final response
                if state.status == AgentStatus.COMPLETED:
                    break

                # OBSERVE: Execute pending tool calls
                if state.pending_tool_calls:
                    state = await self._execute_tools_with_callbacks(state, ctx)

                    # Check for cancellation after tool execution
                    if self.is_cancelled:
                        state.status = AgentStatus.ERROR
                        state.error = "Cancelled"
                        break

            if state.final_response is None:
                if state.error:
                    result = f"Error: {state.error}"
                else:
                    result = "I was unable to complete the request within the allowed iterations."
            else:
                result = state.final_response

            # Emit end callback
            if self.callbacks and ctx:
                duration_ms = (time.time() - start_time) * 1000
                await self.callbacks.on_agent_end(
                    ctx, result, state.iteration, duration_ms
                )

            return result

        except Exception as e:
            if self.callbacks and ctx:
                await self.callbacks.on_agent_error(ctx, e)
            raise

    async def _execute_tools_with_callbacks(
        self, state: AgentState, ctx: Optional["RunContext"]
    ) -> AgentState:
        """Execute pending tool calls with callback events."""
        if not state.pending_tool_calls:
            return state

        for call in state.pending_tool_calls:
            if self.callbacks and ctx:
                await self.callbacks.on_agent_tool_start(
                    ctx, call.name, call.arguments
                )

        tool_start = time.time()
        state = await self.tool_node.ainvoke(state)
        tool_duration_ms = (time.time() - tool_start) * 1000

        # Emit tool end events (simplified - one event for batch)
        if self.callbacks and ctx:
            # Get results from last N messages
            tool_count = len([m for m in state.messages if m.role == "tool"])
            await self.callbacks.on_agent_tool_end(
                ctx,
                "batch",
                f"{tool_count} tools executed",
                True,
                tool_duration_ms,
            )

        return state

    async def run_stream(
        self, input: str, initial_state: Optional[AgentState] = None
    ) -> AsyncIterator[str]:
        """Execute the agent loop with streaming output.

        Yields only response tokens (excludes feedback phrases).
        For full event stream including feedback, use run_stream_events().

        Args:
            input: User input to process.
            initial_state: Optional pre-built state with context (e.g. memory).
                If provided, used as-is (input should already be in the state).

        Yields:
            Tokens from the final response only.
        """
        async for event in self.run_stream_events(input, initial_state):
            if event.is_response_token:
                yield event.data
            elif event.is_error:
                yield event.data
            elif event.is_done and not event.data:
                # Final response was empty
                pass

    async def run_stream_events(
        self, input: str, initial_state: Optional[AgentState] = None
    ) -> AsyncIterator[StreamEvent]:
        """Execute the agent loop with typed streaming events.

        Yields StreamEvent objects for all events during execution,
        including tokens, feedback phrases, tool events, and errors.
        This allows callers to handle different event types appropriately.

        Args:
            input: User input to process.
            initial_state: Optional pre-built state with context (e.g. memory).
                If provided, input should already be in the state.
                If input is not found in state, a warning is logged.

        Yields:
            StreamEvent objects for each event.

        Example:
            >>> async for event in loop.run_stream_events("Hello"):
            ...     if event.is_response_token:
            ...         print(event.data, end="")
            ...     elif event.type == StreamEventType.FEEDBACK:
            ...         play_feedback_audio(event.data)
            ...     elif event.type == StreamEventType.TOOL_START:
            ...         show_tool_indicator(event.metadata["tool_name"])
        """
        # Reset cancel state for new run
        self.reset_cancel()

        # Initialize state
        if initial_state is not None:
            state = initial_state
            # TASK-1.3: Validate input is in state
            if not any(
                m.content == input and m.role == "user"
                for m in state.messages
            ):
                logger.warning(
                    "Input not found in initial_state messages. "
                    "Caller should add input to state before passing it."
                )
        else:
            state = AgentState(max_iterations=self.max_iterations)
            state.add_user_message(input)

        while state.should_continue():
            # Check for cancellation
            if self.is_cancelled:
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    data="Cancelled",
                    metadata={"cancelled": True},
                )
                return
            # Emit iteration start
            yield StreamEvent(
                type=StreamEventType.ITERATION,
                data=str(state.iteration + 1),
                metadata={"iteration": state.iteration + 1, "max": state.max_iterations},
            )

            # THINK + ACT with streaming
            yield StreamEvent(type=StreamEventType.THINKING)

            async for event, delta in self._think_and_act_stream_v2(state):
                yield event
                if delta:
                    delta.apply_to(state)

            if state.status == AgentStatus.COMPLETED:
                break

            # OBSERVE: Execute pending tool calls
            if state.pending_tool_calls:
                # Emit feedback as FEEDBACK event (not TOKEN)
                if self.tool_feedback and self.tool_feedback.enabled:
                    tool_name = state.pending_tool_calls[0].name
                    feedback = self.tool_feedback.get_phrase(tool_name)
                    yield StreamEvent(
                        type=StreamEventType.FEEDBACK,
                        data=feedback,
                        metadata={"tool_name": tool_name},
                    )

                # Emit tool start events
                for call in state.pending_tool_calls:
                    yield StreamEvent(
                        type=StreamEventType.TOOL_START,
                        data=call.name,
                        metadata={"tool_name": call.name, "arguments": call.arguments},
                    )

                # Execute tools
                state = await self.tool_node.ainvoke(state)

                # Check for cancellation after tool execution
                if self.is_cancelled:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        data="Cancelled",
                        metadata={"cancelled": True},
                    )
                    return

                # Emit tool end events
                # Note: Results are in the last N messages where N = len(pending calls)
                yield StreamEvent(
                    type=StreamEventType.TOOL_END,
                    data="",
                    metadata={"tool_count": len(state.pending_tool_calls) if state.pending_tool_calls else 0},
                )

        # Emit final event
        if state.final_response is not None:
            yield StreamEvent(
                type=StreamEventType.DONE,
                data=state.final_response,
            )
        elif state.error:
            yield StreamEvent(
                type=StreamEventType.ERROR,
                data=f"Error: {state.error}",
            )
        else:
            yield StreamEvent(
                type=StreamEventType.ERROR,
                data="I was unable to complete the request within the allowed iterations.",
            )

    async def run_with_state(
        self, input: str, initial_state: Optional[AgentState] = None
    ) -> AgentState:
        """Execute the loop and return the full state.

        Useful for debugging or when you need access to
        the full conversation history.

        Args:
            input: User input to process.
            initial_state: Optional pre-built state with context (e.g. memory).
                If provided, used as-is (input should already be in the state).

        Returns:
            Final AgentState with all messages.
        """
        if initial_state is not None:
            state = initial_state
        else:
            state = AgentState(max_iterations=self.max_iterations)
            state.add_user_message(input)

        while state.should_continue():
            state = await self._think_and_act(state)

            if state.status == AgentStatus.COMPLETED:
                break

            if state.pending_tool_calls:
                state = await self.tool_node.ainvoke(state)

        return state

    async def _think_and_act(self, state: AgentState) -> AgentState:
        """Execute the think and act phase.

        Calls the LLM with tools and updates state based on response.
        LLM calls are automatically retried on transient failures.

        Args:
            state: Current agent state.

        Returns:
            Updated state with new message and/or pending tool calls.
        """
        state.status = AgentStatus.THINKING

        # Prepare messages for LLM
        messages = state.to_messages()
        tools = self.executor.to_openai_tools()

        try:
            # Call LLM with retry support
            response = await self._call_llm_with_retry(messages, tools)

            # Process response
            state = self._process_response(state, response)

        except Exception as e:
            state.status = AgentStatus.ERROR
            state.error = str(e)
            logger.exception(f"LLM call failed after retries: {e}")

        state.iteration += 1
        return state

    async def _call_llm_with_retry(
        self, messages: list, tools: list
    ) -> LLMResponse:
        """Call LLM with automatic retry and circuit breaker protection.

        Args:
            messages: Message history.
            tools: Available tools.

        Returns:
            LLM response.

        Raises:
            CircuitBreakerError: If circuit breaker is open.
        """

        @with_retry(config=self.retry_config)
        async def _call() -> LLMResponse:
            if tools and self.llm.supports_tools():
                return await self.llm.generate_with_tools(
                    messages=messages,
                    tools=tools,
                    system_prompt=self.system_prompt,
                )
            else:
                content = await self.llm.generate(
                    messages=messages,
                    system_prompt=self.system_prompt,
                )
                return LLMResponse(content=content)

        # Use circuit breaker if configured
        if self.circuit_breaker:
            return await self.circuit_breaker.call(_call)
        else:
            return await _call()

    async def _think_and_act_stream(
        self, state: AgentState
    ) -> AsyncIterator[tuple[str, bool]]:
        """Execute think/act with streaming for final response.

        Yields (token, is_final) tuples. If is_final is False,
        it means tool calls were detected and tokens should not
        be shown to user.

        Args:
            state: Current agent state.

        Yields:
            Tuples of (token, is_final_response).
        """
        state.status = AgentStatus.THINKING

        messages = state.to_messages()
        tools = self.executor.to_openai_tools()

        try:
            if tools and self.llm.supports_tools():
                collected_text: list[str] = []
                collected_tool_calls: list[dict] = []

                async for chunk in self.llm.generate_stream_with_tools(
                    messages=messages,
                    tools=tools,
                    system_prompt=self.system_prompt,
                ):
                    # Stream text immediately
                    if chunk.text:
                        collected_text.append(chunk.text)
                        yield (chunk.text, True)

                    # Accumulate tool call deltas
                    if chunk.tool_calls_delta:
                        collected_tool_calls.extend(chunk.tool_calls_delta)

                full_content = "".join(collected_text)

                if collected_tool_calls:
                    # Tool calls — process silently
                    response = LLMResponse(
                        content=full_content,
                        tool_calls=collected_tool_calls,
                    )
                    state = self._process_response(state, response)
                    state.iteration += 1
                else:
                    # Final text response
                    state.add_assistant_message(content=full_content)
                    state.final_response = full_content
                    state.status = AgentStatus.COMPLETED
                    state.iteration += 1
            else:
                # No tools, stream directly
                collected: list[str] = []
                async for chunk in self.llm.astream(messages):
                    collected.append(chunk.text)
                    yield (chunk.text, True)

                full_content = "".join(collected)
                state.add_assistant_message(content=full_content)
                state.final_response = full_content
                state.status = AgentStatus.COMPLETED
                state.iteration += 1

        except Exception as e:
            state.status = AgentStatus.ERROR
            state.error = str(e)
            state.iteration += 1

    async def _think_and_act_stream_v2(
        self, state: AgentState
    ) -> AsyncIterator[tuple[StreamEvent, Optional[StateDelta]]]:
        """Execute think/act with streaming, returning typed events and state deltas.

        This version properly propagates state changes back to the caller
        via StateDelta objects, fixing the state propagation bug in the
        original _think_and_act_stream.

        Args:
            state: Current agent state (read-only, changes returned via deltas).

        Yields:
            Tuples of (StreamEvent, Optional[StateDelta]).
            Apply deltas to state after receiving them.
        """
        messages = state.to_messages()
        tools = self.executor.to_openai_tools()

        try:
            if tools and hasattr(self.llm, 'supports_tools') and self.llm.supports_tools():
                collected_text: list[str] = []
                collected_tool_calls: list[dict] = []

                async for chunk in self.llm.generate_stream_with_tools(
                    messages=messages,
                    tools=tools,
                    system_prompt=self.system_prompt,
                ):
                    # Stream text as TOKEN events
                    if chunk.text:
                        collected_text.append(chunk.text)
                        yield (
                            StreamEvent(type=StreamEventType.TOKEN, data=chunk.text),
                            None,  # No state change yet
                        )

                    # Accumulate tool call deltas
                    if chunk.tool_calls_delta:
                        collected_tool_calls.extend(chunk.tool_calls_delta)

                full_content = "".join(collected_text)

                if collected_tool_calls:
                    # Tool calls detected - emit state delta
                    tool_calls_parsed = [
                        ToolCall.from_openai(tc) for tc in collected_tool_calls
                    ]
                    yield (
                        StreamEvent(
                            type=StreamEventType.TOKEN,
                            data="",
                            metadata={"has_tool_calls": True},
                        ),
                        StateDelta(
                            status=AgentStatus.ACTING,
                            iteration_increment=True,
                            pending_tool_calls=tool_calls_parsed,
                            add_message={
                                "role": "assistant",
                                "content": full_content,
                                "tool_calls": collected_tool_calls,
                            },
                        ),
                    )
                else:
                    # Final text response - emit completion delta
                    yield (
                        StreamEvent(type=StreamEventType.DONE, data=full_content),
                        StateDelta(
                            status=AgentStatus.COMPLETED,
                            iteration_increment=True,
                            final_response=full_content,
                            add_message={
                                "role": "assistant",
                                "content": full_content,
                            },
                        ),
                    )
            else:
                # No tools, stream directly
                collected: list[str] = []

                if hasattr(self.llm, 'astream'):
                    async for chunk in self.llm.astream(messages):
                        text = chunk.text if hasattr(chunk, 'text') else str(chunk)
                        collected.append(text)
                        yield (
                            StreamEvent(type=StreamEventType.TOKEN, data=text),
                            None,
                        )
                else:
                    # Fallback: generate full response
                    content = await self.llm.generate(
                        messages=messages,
                        system_prompt=self.system_prompt,
                    )
                    collected.append(content)
                    yield (
                        StreamEvent(type=StreamEventType.TOKEN, data=content),
                        None,
                    )

                full_content = "".join(collected)
                yield (
                    StreamEvent(type=StreamEventType.DONE, data=full_content),
                    StateDelta(
                        status=AgentStatus.COMPLETED,
                        iteration_increment=True,
                        final_response=full_content,
                        add_message={
                            "role": "assistant",
                            "content": full_content,
                        },
                    ),
                )

        except Exception as e:
            logger.exception("Error during think_and_act_stream")
            yield (
                StreamEvent(
                    type=StreamEventType.ERROR,
                    data=str(e),
                    metadata={"exception_type": type(e).__name__},
                ),
                StateDelta(
                    status=AgentStatus.ERROR,
                    iteration_increment=True,
                    error=str(e),
                ),
            )

    def _process_response(
        self,
        state: AgentState,
        response: LLMResponse,
    ) -> AgentState:
        """Process LLM response and update state.

        Args:
            state: Current agent state.
            response: LLM response to process.

        Returns:
            Updated state.
        """
        if response.has_tool_calls:
            # LLM wants to use tools
            state.pending_tool_calls = [
                ToolCall.from_openai(tc) for tc in response.tool_calls
            ]
            state.add_assistant_message(
                content=response.content or "",
                tool_calls=response.tool_calls,
            )
            state.status = AgentStatus.ACTING
        else:
            # LLM generated final response
            state.final_response = response.content
            state.add_assistant_message(content=response.content)
            state.status = AgentStatus.COMPLETED

        return state

    def add_tool(self, tool: VoiceTool, overwrite: bool = False) -> None:
        """Add a tool to the executor.

        Args:
            tool: Tool to add.
            overwrite: If True, allows overwriting an existing tool.

        Raises:
            ValueError: If a tool with the same name is already registered
                and overwrite is False.
        """
        self.executor.register(tool, overwrite=overwrite)

    def remove_tool(self, name: str) -> None:
        """Remove a tool from the executor.

        Args:
            name: Name of tool to remove.
        """
        self.executor.unregister(name)

    def list_tools(self) -> list[str]:
        """List available tool names.

        Returns:
            List of tool names.
        """
        return self.executor.list_tools()
