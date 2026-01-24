"""MCP-enabled Voice Agent.

Provides VoiceAgent integration with MCP servers.
"""

from typing import Any, AsyncIterator, Optional

from voice_pipeline.agents.base import VoiceAgent
from voice_pipeline.interfaces.llm import LLMInterface
from voice_pipeline.memory.base import VoiceMemory
from voice_pipeline.mcp.client import MCPClient
from voice_pipeline.mcp.tools import MCPToolAdapter, mcp_tools_to_voice_tools
from voice_pipeline.mcp.types import TransportType
from voice_pipeline.prompts.persona import VoicePersona
from voice_pipeline.runnable import RunnableConfig
from voice_pipeline.tools.base import VoiceTool


class MCPEnabledAgent(VoiceAgent):
    """VoiceAgent with MCP server integration.

    Extends VoiceAgent to automatically connect to MCP servers
    and use their tools alongside local tools.

    Example - Single MCP server:
        >>> agent = MCPEnabledAgent(
        ...     llm=my_llm,
        ...     mcp_servers=["http://localhost:8000/mcp"],
        ... )
        >>>
        >>> async with agent:
        ...     result = await agent.ainvoke("Search for AI news")

    Example - Multiple servers:
        >>> agent = MCPEnabledAgent(
        ...     llm=my_llm,
        ...     mcp_servers={
        ...         "search": "http://search-server:8000/mcp",
        ...         "math": "http://math-server:8001/mcp",
        ...     },
        ...     tools=[local_tool],  # Can mix local and MCP tools
        ... )

    Example - With persona and memory:
        >>> agent = MCPEnabledAgent(
        ...     llm=my_llm,
        ...     mcp_servers=["http://localhost:8000/mcp"],
        ...     persona=ASSISTANT_PERSONA,
        ...     memory=ConversationBufferMemory(),
        ... )

    Attributes:
        mcp_servers: MCP server URLs or name->URL mapping.
        mcp_clients: Active MCP client connections.
    """

    name: str = "MCPEnabledAgent"

    def __init__(
        self,
        llm: LLMInterface,
        mcp_servers: Optional[dict[str, str] | list[str]] = None,
        tools: Optional[list[VoiceTool]] = None,
        persona: Optional[VoicePersona] = None,
        memory: Optional[VoiceMemory] = None,
        system_prompt: Optional[str] = None,
        max_iterations: int = 10,
        verbose: bool = False,
        auto_connect: bool = True,
    ):
        """Initialize MCP-enabled agent.

        Args:
            llm: LLM interface.
            mcp_servers: MCP server URLs (list or dict).
            tools: Local tools (in addition to MCP tools).
            persona: Agent persona.
            memory: Conversation memory.
            system_prompt: System prompt.
            max_iterations: Max loop iterations.
            verbose: Enable verbose output.
            auto_connect: Connect to servers automatically.
        """
        # Normalize server config
        if isinstance(mcp_servers, list):
            self._mcp_server_config = {
                f"server_{i}": url for i, url in enumerate(mcp_servers)
            }
        else:
            self._mcp_server_config = mcp_servers or {}

        self._mcp_clients: dict[str, MCPClient] = {}
        self._mcp_tools: list[VoiceTool] = []
        self._local_tools = tools or []
        self._auto_connect = auto_connect
        self._connected = False

        # Initialize base agent with local tools only
        # MCP tools will be added after connection
        super().__init__(
            llm=llm,
            tools=self._local_tools.copy(),
            persona=persona,
            memory=memory,
            system_prompt=system_prompt,
            max_iterations=max_iterations,
            verbose=verbose,
        )

    async def __aenter__(self) -> "MCPEnabledAgent":
        """Connect to MCP servers on context entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Disconnect from MCP servers on context exit."""
        await self.disconnect()

    async def connect(self) -> None:
        """Connect to all configured MCP servers.

        Loads tools from each server and adds them to the agent.
        """
        if self._connected:
            return

        for name, url in self._mcp_server_config.items():
            try:
                client = MCPClient(url)
                await client.connect()
                self._mcp_clients[name] = client

                # Load and convert tools
                mcp_tools = await client.list_tools()
                voice_tools = mcp_tools_to_voice_tools(client, mcp_tools)

                for tool in voice_tools:
                    self._mcp_tools.append(tool)
                    self.add_tool(tool)

            except Exception as e:
                if self.verbose:
                    print(f"Failed to connect to MCP server {name}: {e}")

        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from all MCP servers."""
        for client in self._mcp_clients.values():
            await client.disconnect()

        # Remove MCP tools from agent
        for tool in self._mcp_tools:
            self.remove_tool(tool.name)

        self._mcp_clients.clear()
        self._mcp_tools.clear()
        self._connected = False

    async def ainvoke(
        self,
        input: str,
        config: Optional[RunnableConfig] = None,
    ) -> str:
        """Execute the agent.

        Auto-connects if not connected and auto_connect is True.

        Args:
            input: User input.
            config: Configuration.

        Returns:
            Agent response.
        """
        if self._auto_connect and not self._connected:
            await self.connect()

        return await super().ainvoke(input, config)

    async def astream(
        self,
        input: str,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[str]:
        """Stream agent response.

        Args:
            input: User input.
            config: Configuration.

        Yields:
            Response tokens.
        """
        if self._auto_connect and not self._connected:
            await self.connect()

        async for token in super().astream(input, config):
            yield token

    def add_mcp_server(self, name: str, url: str) -> None:
        """Add an MCP server configuration.

        Call connect() after adding to load tools.

        Args:
            name: Server name.
            url: Server URL.
        """
        self._mcp_server_config[name] = url

    def remove_mcp_server(self, name: str) -> None:
        """Remove an MCP server.

        Args:
            name: Server name.
        """
        self._mcp_server_config.pop(name, None)

    def list_mcp_servers(self) -> list[str]:
        """List configured MCP server names.

        Returns:
            List of server names.
        """
        return list(self._mcp_server_config.keys())

    def list_mcp_tools(self) -> list[str]:
        """List tools from MCP servers.

        Returns:
            List of MCP tool names.
        """
        return [tool.name for tool in self._mcp_tools]

    def get_mcp_client(self, name: str) -> Optional[MCPClient]:
        """Get MCP client by server name.

        Args:
            name: Server name.

        Returns:
            MCPClient or None.
        """
        return self._mcp_clients.get(name)

    def is_connected(self) -> bool:
        """Check if connected to MCP servers.

        Returns:
            True if connected.
        """
        return self._connected


def create_mcp_agent(
    llm: LLMInterface,
    mcp_servers: dict[str, str] | list[str],
    tools: Optional[list[VoiceTool]] = None,
    persona: Optional[VoicePersona] = None,
    memory: Optional[VoiceMemory] = None,
    system_prompt: Optional[str] = None,
    max_iterations: int = 10,
) -> MCPEnabledAgent:
    """Factory function to create an MCP-enabled agent.

    Args:
        llm: LLM interface.
        mcp_servers: MCP server URLs.
        tools: Additional local tools.
        persona: Agent persona.
        memory: Conversation memory.
        system_prompt: System prompt.
        max_iterations: Max iterations.

    Returns:
        Configured MCPEnabledAgent.

    Example:
        >>> agent = create_mcp_agent(
        ...     llm=my_llm,
        ...     mcp_servers={
        ...         "search": "http://localhost:8000/mcp",
        ...     },
        ...     persona=ASSISTANT_PERSONA,
        ... )
        >>>
        >>> async with agent:
        ...     result = await agent.ainvoke("Search for AI news")
    """
    return MCPEnabledAgent(
        llm=llm,
        mcp_servers=mcp_servers,
        tools=tools,
        persona=persona,
        memory=memory,
        system_prompt=system_prompt,
        max_iterations=max_iterations,
    )


async def load_mcp_tools(
    servers: dict[str, str] | list[str],
) -> tuple[list[VoiceTool], list[MCPClient]]:
    """Load tools from MCP servers.

    Utility function to load tools without creating an agent.

    Args:
        servers: MCP server URLs.

    Returns:
        Tuple of (tools, clients).

    Example:
        >>> tools, clients = await load_mcp_tools({
        ...     "search": "http://localhost:8000/mcp",
        ... })
        >>>
        >>> agent = VoiceAgent(llm=llm, tools=tools)
        >>>
        >>> # Remember to close clients when done
        >>> for client in clients:
        ...     await client.disconnect()
    """
    if isinstance(servers, list):
        servers = {f"server_{i}": url for i, url in enumerate(servers)}

    all_tools: list[VoiceTool] = []
    clients: list[MCPClient] = []

    for name, url in servers.items():
        client = MCPClient(url)
        await client.connect()
        clients.append(client)

        mcp_tools = await client.list_tools()
        voice_tools = mcp_tools_to_voice_tools(client, mcp_tools)
        all_tools.extend(voice_tools)

    return all_tools, clients
