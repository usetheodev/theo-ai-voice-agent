"""Summary-based memory implementations.

Memory that summarizes long conversations to stay within context limits.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from voice_pipeline.memory.base import BaseMemoryStore, MemoryContext, VoiceMemory


@dataclass
class ConversationSummaryMemory(VoiceMemory):
    """Memory that summarizes conversation history.

    When the conversation gets long, this memory uses an LLM
    to summarize older messages, keeping context concise while
    preserving important information.

    Example:
        >>> from voice_pipeline.interfaces import LLMInterface
        >>>
        >>> llm = MyLLM()  # Any LLMInterface
        >>> memory = ConversationSummaryMemory(
        ...     llm=llm,
        ...     max_messages_before_summary=10,
        ... )
        >>>
        >>> # After 10+ messages, older ones get summarized
        >>> for i in range(15):
        ...     await memory.save_context(f"Q{i}", f"A{i}")
        >>>
        >>> context = await memory.load_context()
        >>> # context.summary contains summarized older messages
        >>> # context.messages contains recent messages

    Attributes:
        llm: LLM interface for generating summaries.
        max_messages_before_summary: Trigger summarization threshold.
        summary_prompt: Custom prompt for summarization.
    """

    llm: Any = None  # LLMInterface (avoid circular import)
    """LLM for generating summaries."""

    max_messages_before_summary: int = 10
    """Number of messages before triggering summarization."""

    keep_recent_messages: int = 4
    """Number of recent messages to keep after summarization."""

    summary_prompt: str = (
        "Summarize the following conversation concisely, "
        "preserving key information and context:\n\n{conversation}"
    )
    """Prompt template for summarization."""

    store: Optional[BaseMemoryStore] = None
    """Optional persistence backend."""

    session_id: str = "default"
    """Session identifier for persistence."""

    _messages: list[dict[str, str]] = field(default_factory=list)
    """Internal message buffer."""

    _summary: Optional[str] = None
    """Current summary of older messages."""

    def __post_init__(self):
        """Initialize internal state."""
        self._messages = []
        self._summary = None

    async def load_context(
        self,
        query: Optional[str] = None,
    ) -> MemoryContext:
        """Load context with summary and recent messages.

        Args:
            query: Current user query (not used).

        Returns:
            MemoryContext with summary and recent messages.
        """
        if self.store:
            stored = await self.store.get(f"memory:{self.session_id}")
            if stored and isinstance(stored, dict):
                self._messages = stored.get("messages", [])
                self._summary = stored.get("summary")

        return MemoryContext(
            messages=self._messages.copy(),
            summary=self._summary,
        )

    async def save_context(
        self,
        user_input: str,
        assistant_output: str,
    ) -> None:
        """Save a turn and possibly summarize.

        Args:
            user_input: User's message.
            assistant_output: Assistant's response.
        """
        self._messages.append({"role": "user", "content": user_input})
        self._messages.append({"role": "assistant", "content": assistant_output})

        # Check if we need to summarize
        if len(self._messages) > self.max_messages_before_summary:
            await self._summarize()

        # Persist
        if self.store:
            await self.store.set(
                f"memory:{self.session_id}",
                {"messages": self._messages, "summary": self._summary},
            )

    async def _summarize(self) -> None:
        """Summarize older messages and keep recent ones."""
        if not self.llm:
            # No LLM available, just truncate
            self._messages = self._messages[-self.keep_recent_messages :]
            return

        # Get messages to summarize
        to_summarize = self._messages[: -self.keep_recent_messages]
        to_keep = self._messages[-self.keep_recent_messages :]

        # Format conversation for summarization
        conversation = "\n".join(
            f"{m['role'].title()}: {m['content']}" for m in to_summarize
        )

        # Include existing summary
        if self._summary:
            conversation = f"Previous summary: {self._summary}\n\n{conversation}"

        # Generate new summary
        prompt = self.summary_prompt.format(conversation=conversation)
        messages = [{"role": "user", "content": prompt}]

        # Use LLM to generate summary
        if hasattr(self.llm, "generate"):
            self._summary = await self.llm.generate(messages)
        elif hasattr(self.llm, "ainvoke"):
            self._summary = await self.llm.ainvoke(messages)
        else:
            # Fallback: just keep the first line of each message
            self._summary = " ".join(m["content"][:50] for m in to_summarize)

        # Update messages to only recent
        self._messages = to_keep

    async def clear(self) -> None:
        """Clear all messages and summary."""
        self._messages.clear()
        self._summary = None

        if self.store:
            await self.store.delete(f"memory:{self.session_id}")

    def get_messages(self) -> list[dict[str, str]]:
        """Get raw messages.

        Returns:
            List of message dicts.
        """
        return self._messages.copy()

    def add_message(self, role: str, content: str) -> None:
        """Add a single message.

        Args:
            role: 'user', 'assistant', or 'system'.
            content: Message content.
        """
        self._messages.append({"role": role, "content": content})


@dataclass
class ConversationSummaryBufferMemory(VoiceMemory):
    """Hybrid memory with both buffer and summary.

    Keeps recent messages in full detail, while summarizing
    older messages. Best of both worlds for voice applications.

    Example:
        >>> memory = ConversationSummaryBufferMemory(
        ...     llm=llm,
        ...     max_token_limit=1000,
        ... )
        >>>
        >>> # As you add messages, older ones get summarized
        >>> # while recent ones are kept in full

    Attributes:
        llm: LLM for generating summaries.
        max_token_limit: Approximate token limit before summarizing.
    """

    llm: Any = None  # LLMInterface
    """LLM for generating summaries."""

    max_token_limit: int = 1000
    """Approximate token limit for messages."""

    store: Optional[BaseMemoryStore] = None
    """Optional persistence backend."""

    session_id: str = "default"
    """Session identifier for persistence."""

    _messages: list[dict[str, str]] = field(default_factory=list)
    """Internal message buffer."""

    _summary: Optional[str] = None
    """Summary of older messages."""

    def __post_init__(self):
        """Initialize internal state."""
        self._messages = []
        self._summary = None

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (roughly 4 chars per token)."""
        return len(text) // 4

    def _total_tokens(self) -> int:
        """Estimate total tokens in messages."""
        return sum(self._estimate_tokens(m["content"]) for m in self._messages)

    async def load_context(
        self,
        query: Optional[str] = None,
    ) -> MemoryContext:
        """Load context with summary and messages.

        Args:
            query: Current user query (not used).

        Returns:
            MemoryContext with summary and messages.
        """
        if self.store:
            stored = await self.store.get(f"memory:{self.session_id}")
            if stored and isinstance(stored, dict):
                self._messages = stored.get("messages", [])
                self._summary = stored.get("summary")

        return MemoryContext(
            messages=self._messages.copy(),
            summary=self._summary,
        )

    async def save_context(
        self,
        user_input: str,
        assistant_output: str,
    ) -> None:
        """Save a turn and manage token budget.

        Args:
            user_input: User's message.
            assistant_output: Assistant's response.
        """
        self._messages.append({"role": "user", "content": user_input})
        self._messages.append({"role": "assistant", "content": assistant_output})

        # Check token limit
        while self._total_tokens() > self.max_token_limit and len(self._messages) > 2:
            await self._prune_oldest()

        # Persist
        if self.store:
            await self.store.set(
                f"memory:{self.session_id}",
                {"messages": self._messages, "summary": self._summary},
            )

    async def _prune_oldest(self) -> None:
        """Remove and summarize oldest messages."""
        if len(self._messages) <= 2:
            return

        # Take oldest 2 messages (1 turn)
        oldest = self._messages[:2]
        self._messages = self._messages[2:]

        # Add to summary
        turn_text = f"{oldest[0]['content']} -> {oldest[1]['content']}"

        if self._summary:
            if self.llm:
                # Use LLM to merge summaries
                prompt = (
                    f"Combine these into a brief summary:\n"
                    f"Previous: {self._summary}\n"
                    f"New: {turn_text}"
                )
                messages = [{"role": "user", "content": prompt}]
                if hasattr(self.llm, "generate"):
                    self._summary = await self.llm.generate(messages)
                elif hasattr(self.llm, "ainvoke"):
                    self._summary = await self.llm.ainvoke(messages)
            else:
                # No LLM, just append
                self._summary = f"{self._summary}; {turn_text[:100]}"
        else:
            self._summary = turn_text[:200]

    async def clear(self) -> None:
        """Clear all messages and summary."""
        self._messages.clear()
        self._summary = None

        if self.store:
            await self.store.delete(f"memory:{self.session_id}")

    def get_messages(self) -> list[dict[str, str]]:
        """Get raw messages.

        Returns:
            List of message dicts.
        """
        return self._messages.copy()

    def add_message(self, role: str, content: str) -> None:
        """Add a single message.

        Args:
            role: 'user', 'assistant', or 'system'.
            content: Message content.
        """
        self._messages.append({"role": role, "content": content})
