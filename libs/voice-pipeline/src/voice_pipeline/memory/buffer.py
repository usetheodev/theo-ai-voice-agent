"""Buffer-based memory implementations.

Simple memory that stores the last N messages.
"""

from dataclasses import dataclass, field
from typing import Optional

from voice_pipeline.memory.base import BaseMemoryStore, MemoryContext, VoiceMemory


@dataclass
class ConversationBufferMemory(VoiceMemory):
    """Simple buffer memory that stores the last K messages.

    This is the most basic memory implementation, keeping
    a rolling window of conversation history.

    Example:
        >>> memory = ConversationBufferMemory(max_messages=10)
        >>>
        >>> # Save turns
        >>> await memory.save_context("Hello!", "Hi there!")
        >>> await memory.save_context("How are you?", "I'm doing great!")
        >>>
        >>> # Load context
        >>> context = await memory.load_context()
        >>> len(context.messages)  # 4 messages (2 turns)
        4

    Attributes:
        max_messages: Maximum messages to keep (default 20).
        store: Optional persistence backend.
        session_id: Optional session identifier for persistence.
    """

    max_messages: int = 20
    """Maximum number of messages to retain."""

    store: Optional[BaseMemoryStore] = None
    """Optional persistence backend."""

    session_id: str = "default"
    """Session identifier for persistence."""

    return_messages: bool = True
    """Whether to return messages in context."""

    _messages: list[dict[str, str]] = field(default_factory=list)
    """Internal message buffer."""

    def __post_init__(self):
        """Initialize internal state."""
        self._messages = []

    async def load_context(
        self,
        query: Optional[str] = None,
    ) -> MemoryContext:
        """Load context with message history.

        Args:
            query: Current user query (not used by buffer memory).

        Returns:
            MemoryContext with message history.
        """
        # Load from store if available
        if self.store:
            stored = await self.store.get(f"memory:{self.session_id}")
            if stored and isinstance(stored, list):
                self._messages = stored

        if self.return_messages:
            return MemoryContext(messages=self._messages.copy())
        else:
            # Convert to string format
            history = "\n".join(
                f"{m['role'].title()}: {m['content']}" for m in self._messages
            )
            return MemoryContext(
                messages=[],
                metadata={"history": history},
            )

    async def save_context(
        self,
        user_input: str,
        assistant_output: str,
    ) -> None:
        """Save a conversation turn.

        Args:
            user_input: User's message.
            assistant_output: Assistant's response.
        """
        self._messages.append({"role": "user", "content": user_input})
        self._messages.append({"role": "assistant", "content": assistant_output})

        # Trim to max_messages
        while len(self._messages) > self.max_messages:
            self._messages.pop(0)

        # Persist if store available
        if self.store:
            await self.store.set(f"memory:{self.session_id}", self._messages)

    async def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()

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

        # Trim if needed
        while len(self._messages) > self.max_messages:
            self._messages.pop(0)


@dataclass
class ConversationWindowMemory(VoiceMemory):
    """Window memory that keeps only the last K turns.

    Similar to BufferMemory but counts turns (user + assistant pairs)
    instead of individual messages.

    Example:
        >>> memory = ConversationWindowMemory(max_turns=5)
        >>>
        >>> for i in range(10):
        ...     await memory.save_context(f"Message {i}", f"Response {i}")
        >>>
        >>> # Only last 5 turns are kept
        >>> context = await memory.load_context()
        >>> len(context.messages) // 2  # 5 turns
        5
    """

    max_turns: int = 5
    """Maximum conversation turns to retain."""

    store: Optional[BaseMemoryStore] = None
    """Optional persistence backend."""

    session_id: str = "default"
    """Session identifier for persistence."""

    _messages: list[dict[str, str]] = field(default_factory=list)
    """Internal message buffer."""

    def __post_init__(self):
        """Initialize internal state."""
        self._messages = []

    async def load_context(
        self,
        query: Optional[str] = None,
    ) -> MemoryContext:
        """Load context with message history.

        Args:
            query: Current user query (not used).

        Returns:
            MemoryContext with message history.
        """
        if self.store:
            stored = await self.store.get(f"memory:{self.session_id}")
            if stored and isinstance(stored, list):
                self._messages = stored

        return MemoryContext(messages=self._messages.copy())

    async def save_context(
        self,
        user_input: str,
        assistant_output: str,
    ) -> None:
        """Save a conversation turn.

        Args:
            user_input: User's message.
            assistant_output: Assistant's response.
        """
        self._messages.append({"role": "user", "content": user_input})
        self._messages.append({"role": "assistant", "content": assistant_output})

        # Trim to max_turns (2 messages per turn)
        max_messages = self.max_turns * 2
        while len(self._messages) > max_messages:
            self._messages.pop(0)

        if self.store:
            await self.store.set(f"memory:{self.session_id}", self._messages)

    async def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()

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
