"""Base interface for voice memory systems.

Memory provides conversation context for LLM interactions,
allowing multi-turn conversations with history.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MemoryContext:
    """Context loaded from memory for LLM generation.

    This is the output of memory.load_context() that gets
    used to augment the LLM prompt.
    """

    messages: list[dict[str, str]] = field(default_factory=list)
    """Conversation history messages."""

    summary: Optional[str] = None
    """Optional summary of previous conversation."""

    entities: dict[str, Any] = field(default_factory=dict)
    """Extracted entities from conversation."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional context metadata."""


class VoiceMemory(ABC):
    """Abstract base class for voice conversation memory.

    Memory systems store and retrieve conversation history,
    allowing the LLM to maintain context across turns.

    Implementations may:
    - Store raw messages (BufferMemory)
    - Summarize history (SummaryMemory)
    - Extract entities (EntityMemory)
    - Persist to external stores (Redis, SQLite, etc.)

    Example:
        >>> memory = ConversationBufferMemory(max_messages=10)
        >>>
        >>> # Save a turn
        >>> await memory.save_context("What's the weather?", "It's sunny today!")
        >>>
        >>> # Load context for next turn
        >>> context = await memory.load_context("And tomorrow?")
        >>> # context.messages contains the previous turn
    """

    @abstractmethod
    async def load_context(
        self,
        query: Optional[str] = None,
    ) -> MemoryContext:
        """Load context for LLM generation.

        Args:
            query: Current user query (may be used for relevance).

        Returns:
            MemoryContext with messages, summary, entities, etc.
        """
        pass

    @abstractmethod
    async def save_context(
        self,
        user_input: str,
        assistant_output: str,
    ) -> None:
        """Save a conversation turn to memory.

        Args:
            user_input: What the user said.
            assistant_output: What the assistant responded.
        """
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear all memory contents."""
        pass

    def get_messages(self) -> list[dict[str, str]]:
        """Get raw messages from memory (sync convenience method).

        Returns:
            List of message dicts with 'role' and 'content'.
        """
        return []

    def add_message(self, role: str, content: str) -> None:
        """Add a single message (sync convenience method).

        Args:
            role: 'user', 'assistant', or 'system'.
            content: Message content.
        """
        pass


class BaseMemoryStore(ABC):
    """Abstract base for memory persistence backends.

    Stores provide persistence for memory systems,
    allowing conversation history to survive restarts.

    Implementations:
    - InMemoryStore: No persistence (default)
    - RedisStore: Redis-based persistence
    - SQLiteStore: SQLite database persistence
    """

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Get value by key.

        Args:
            key: Storage key.

        Returns:
            Stored value or None.
        """
        pass

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value by key.

        Args:
            key: Storage key.
            value: Value to store.
            ttl: Optional time-to-live in seconds.
        """
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete value by key.

        Args:
            key: Storage key.
        """
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists.

        Args:
            key: Storage key.

        Returns:
            True if key exists.
        """
        pass
