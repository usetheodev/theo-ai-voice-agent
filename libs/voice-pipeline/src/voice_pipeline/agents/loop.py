"""Agent execution loop implementing the ReAct pattern.

ReAct (Reasoning + Acting) is a paradigm that combines reasoning
and action in LLM agents:

1. THINK: LLM reasons about what to do
2. ACT: LLM decides to call tools or respond
3. OBSERVE: Tool results are added to context
4. REPEAT: Back to step 1 until final response
"""

from typing import Any, AsyncIterator, Optional

from voice_pipeline.agents.state import AgentState, AgentStatus
from voice_pipeline.agents.tool_node import ToolNode
from voice_pipeline.interfaces.llm import LLMInterface, LLMResponse
from voice_pipeline.tools.base import VoiceTool
from voice_pipeline.tools.executor import ToolCall, ToolExecutor


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
    ):
        """Initialize the agent loop.

        Args:
            llm: LLM interface for generation.
            tools: List of tools available to the agent.
            system_prompt: System prompt for the agent.
            max_iterations: Maximum iterations before stopping.
            stop_on_first_response: Stop when LLM responds without tools.
            parallel_tool_execution: Execute multiple tools in parallel.
        """
        self.llm = llm
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.stop_on_first_response = stop_on_first_response

        # Set up tool execution
        self.executor = ToolExecutor(tools=tools or [])
        self.tool_node = ToolNode(
            executor=self.executor,
            parallel=parallel_tool_execution,
        )

    async def run(self, input: str) -> str:
        """Execute the agent loop and return the final response.

        Args:
            input: User input to process.

        Returns:
            Final response from the agent.

        Raises:
            RuntimeError: If max iterations reached without response.
        """
        state = AgentState(max_iterations=self.max_iterations)
        state.add_user_message(input)

        while state.should_continue():
            # THINK + ACT: LLM generates response or tool calls
            state = await self._think_and_act(state)

            # Check if we have a final response
            if state.status == AgentStatus.COMPLETED:
                break

            # OBSERVE: Execute pending tool calls
            if state.pending_tool_calls:
                state = await self.tool_node.ainvoke(state)

        if state.final_response is None:
            if state.error:
                return f"Error: {state.error}"
            return "I was unable to complete the request within the allowed iterations."

        return state.final_response

    async def run_stream(self, input: str) -> AsyncIterator[str]:
        """Execute the agent loop with streaming output.

        Yields tokens as they're generated during the final response.
        Tool calls are executed silently between yields.

        Args:
            input: User input to process.

        Yields:
            Tokens from the final response.
        """
        # For streaming, we use the non-streaming version and yield the final result
        # This is a simpler approach that still provides streaming output
        result = await self.run(input)
        for char in result:
            yield char

    async def run_with_state(self, input: str) -> AgentState:
        """Execute the loop and return the full state.

        Useful for debugging or when you need access to
        the full conversation history.

        Args:
            input: User input to process.

        Returns:
            Final AgentState with all messages.
        """
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
            # Call LLM with tools
            if tools and self.llm.supports_tools():
                response = await self.llm.generate_with_tools(
                    messages=messages,
                    tools=tools,
                    system_prompt=self.system_prompt,
                )
            else:
                # LLM doesn't support tools, just generate
                content = await self.llm.generate(
                    messages=messages,
                    system_prompt=self.system_prompt,
                )
                response = LLMResponse(content=content)

            # Process response
            state = self._process_response(state, response)

        except Exception as e:
            state.status = AgentStatus.ERROR
            state.error = str(e)

        state.iteration += 1
        return state

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
                # For tool-supporting LLMs, we need non-streaming first
                # to check if it's a tool call or final response
                response = await self.llm.generate_with_tools(
                    messages=messages,
                    tools=tools,
                    system_prompt=self.system_prompt,
                )

                if response.has_tool_calls:
                    # Tool calls - process silently
                    state = self._process_response(state, response)
                    state.iteration += 1
                    yield ("", False)
                else:
                    # Final response - yield content as tokens
                    state.add_assistant_message(content=response.content)
                    state.final_response = response.content
                    state.status = AgentStatus.COMPLETED
                    state.iteration += 1

                    # Yield content (could be chunked if needed)
                    for char in response.content:
                        yield (char, True)
            else:
                # No tools, stream directly
                async for chunk in self.llm.astream(messages):
                    yield (chunk.text, True)

        except Exception as e:
            state.status = AgentStatus.ERROR
            state.error = str(e)
            state.iteration += 1

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

    def add_tool(self, tool: VoiceTool) -> None:
        """Add a tool to the executor.

        Args:
            tool: Tool to add.
        """
        self.executor.register(tool)

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
