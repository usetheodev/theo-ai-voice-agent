"""Episodic memory for long-term context persistence.

Episodic memory stores conversations and events across sessions,
allowing the agent to remember past interactions and build
long-term relationships with users.

Example:
    >>> from voice_pipeline.memory import EpisodicMemory, Episode
    >>>
    >>> memory = EpisodicMemory(store_path="~/.voice_agent/memory")
    >>>
    >>> # Save an episode after conversation
    >>> episode = Episode.from_conversation(
    ...     messages=conversation_messages,
    ...     user_id="user_123",
    ...     summary="Discussed weekend plans and weather",
    ...     tags=["casual", "weather"],
    ... )
    >>> await memory.save_episode(episode)
    >>>
    >>> # Later, recall relevant episodes
    >>> episodes = await memory.recall(
    ...     query="What did we talk about last time?",
    ...     user_id="user_123",
    ...     limit=5,
    ... )
"""

import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from voice_pipeline.memory.base import MemoryContext, VoiceMemory


@dataclass
class Episode:
    """A unit of episodic memory - a remembered conversation or event.

    Episodes capture the essence of an interaction for long-term storage.
    They can be recalled based on similarity, recency, or relevance.

    Attributes:
        id: Unique episode identifier.
        timestamp: When the episode occurred.
        messages: Conversation messages in this episode.
        summary: Natural language summary of the episode.
        user_id: Optional user identifier for multi-user systems.
        tags: Categorization tags.
        entities: Named entities mentioned (people, places, etc.).
        importance: Importance score (0-1) for retrieval ranking.
        metadata: Additional episode data.

    Example:
        >>> episode = Episode(
        ...     messages=[
        ...         {"role": "user", "content": "What's the weather?"},
        ...         {"role": "assistant", "content": "It's sunny today!"},
        ...     ],
        ...     summary="User asked about weather, sunny day.",
        ...     tags=["weather", "casual"],
        ...     importance=0.3,
        ... )
    """

    messages: list[dict[str, str]] = field(default_factory=list)
    """Conversation messages in this episode."""

    id: str = ""
    """Unique episode identifier."""

    timestamp: float = field(default_factory=time.time)
    """Unix timestamp when episode was created."""

    summary: str = ""
    """Natural language summary of the episode."""

    user_id: Optional[str] = None
    """User identifier for multi-user systems."""

    tags: list[str] = field(default_factory=list)
    """Categorization tags."""

    entities: dict[str, list[str]] = field(default_factory=dict)
    """Named entities: category -> list of values."""

    importance: float = 0.5
    """Importance score (0-1) for retrieval ranking."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata."""

    def __post_init__(self):
        """Generate ID if not provided."""
        if not self.id:
            # Generate ID from content hash
            content = json.dumps(self.messages, sort_keys=True)
            self.id = hashlib.sha256(
                f"{self.timestamp}:{content}".encode()
            ).hexdigest()[:16]

    @classmethod
    def from_conversation(
        cls,
        messages: list[dict[str, str]],
        user_id: Optional[str] = None,
        summary: Optional[str] = None,
        tags: Optional[list[str]] = None,
        importance: float = 0.5,
        **kwargs,
    ) -> "Episode":
        """Create an episode from a conversation.

        Args:
            messages: Conversation messages.
            user_id: Optional user identifier.
            summary: Optional summary (auto-generated if not provided).
            tags: Optional categorization tags.
            importance: Importance score.
            **kwargs: Additional metadata.

        Returns:
            Episode instance.
        """
        # Auto-generate summary if not provided
        if summary is None and messages:
            # Simple summary from first user message
            user_msgs = [m for m in messages if m.get("role") == "user"]
            if user_msgs:
                first = user_msgs[0].get("content", "")[:100]
                summary = f"Conversation starting with: {first}"
            else:
                summary = "Assistant conversation"

        return cls(
            messages=messages,
            user_id=user_id,
            summary=summary or "",
            tags=tags or [],
            importance=importance,
            metadata=kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "messages": self.messages,
            "summary": self.summary,
            "user_id": self.user_id,
            "tags": self.tags,
            "entities": self.entities,
            "importance": self.importance,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Episode":
        """Create from dictionary."""
        return cls(
            id=data.get("id", ""),
            timestamp=data.get("timestamp", time.time()),
            messages=data.get("messages", []),
            summary=data.get("summary", ""),
            user_id=data.get("user_id"),
            tags=data.get("tags", []),
            entities=data.get("entities", {}),
            importance=data.get("importance", 0.5),
            metadata=data.get("metadata", {}),
        )

    @property
    def age_days(self) -> float:
        """Get age of episode in days."""
        return (time.time() - self.timestamp) / 86400

    @property
    def datetime(self) -> datetime:
        """Get episode datetime."""
        return datetime.fromtimestamp(self.timestamp)


class EpisodeStore(ABC):
    """Abstract base for episode storage backends.

    Implementations handle persistence of episodes to various backends.
    """

    @abstractmethod
    async def save(self, episode: Episode) -> None:
        """Save an episode."""
        pass

    @abstractmethod
    async def load(self, episode_id: str) -> Optional[Episode]:
        """Load an episode by ID."""
        pass

    @abstractmethod
    async def delete(self, episode_id: str) -> bool:
        """Delete an episode. Returns True if deleted."""
        pass

    @abstractmethod
    async def list_all(
        self,
        user_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Episode]:
        """List all episodes, optionally filtered by user."""
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[Episode]:
        """Search episodes by query text."""
        pass

    @abstractmethod
    async def clear(self, user_id: Optional[str] = None) -> int:
        """Clear episodes. Returns count deleted."""
        pass


class InMemoryEpisodeStore(EpisodeStore):
    """In-memory episode store for testing and development.

    Episodes are lost when the process ends.
    """

    def __init__(self):
        self._episodes: dict[str, Episode] = {}

    async def save(self, episode: Episode) -> None:
        """Save episode to memory."""
        self._episodes[episode.id] = episode

    async def load(self, episode_id: str) -> Optional[Episode]:
        """Load episode from memory."""
        return self._episodes.get(episode_id)

    async def delete(self, episode_id: str) -> bool:
        """Delete episode from memory."""
        if episode_id in self._episodes:
            del self._episodes[episode_id]
            return True
        return False

    async def list_all(
        self,
        user_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Episode]:
        """List all episodes."""
        episodes = list(self._episodes.values())

        if user_id is not None:
            episodes = [e for e in episodes if e.user_id == user_id]

        # Sort by timestamp descending (most recent first)
        episodes.sort(key=lambda e: e.timestamp, reverse=True)

        if limit is not None:
            episodes = episodes[:limit]

        return episodes

    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[Episode]:
        """Search episodes by query (simple text matching)."""
        query_lower = query.lower()
        results: list[tuple[float, Episode]] = []

        for episode in self._episodes.values():
            # Filter by user
            if user_id is not None and episode.user_id != user_id:
                continue

            # Filter by tags
            if tags:
                if not any(tag in episode.tags for tag in tags):
                    continue

            # Score by text matching
            score = 0.0

            # Check summary
            if query_lower in episode.summary.lower():
                score += 0.5

            # Check messages
            for msg in episode.messages:
                content = msg.get("content", "").lower()
                if query_lower in content:
                    score += 0.3
                    break

            # Boost by importance and recency
            score += episode.importance * 0.2
            recency_boost = max(0, 1 - episode.age_days / 30) * 0.1
            score += recency_boost

            if score > 0:
                results.append((score, episode))

        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)

        return [episode for _, episode in results[:limit]]

    async def clear(self, user_id: Optional[str] = None) -> int:
        """Clear episodes."""
        if user_id is None:
            count = len(self._episodes)
            self._episodes.clear()
            return count
        else:
            to_delete = [
                eid for eid, ep in self._episodes.items()
                if ep.user_id == user_id
            ]
            for eid in to_delete:
                del self._episodes[eid]
            return len(to_delete)


class FileEpisodeStore(EpisodeStore):
    """File-based episode store using JSON files.

    Each episode is stored as a separate JSON file.
    Suitable for development and small-scale deployments.
    """

    def __init__(self, store_path: str):
        """Initialize file store.

        Args:
            store_path: Directory path for storing episodes.
        """
        self.store_path = Path(store_path).expanduser()
        self.store_path.mkdir(parents=True, exist_ok=True)

    def _episode_path(self, episode_id: str) -> Path:
        """Get path for an episode file."""
        return self.store_path / f"{episode_id}.json"

    async def save(self, episode: Episode) -> None:
        """Save episode to file."""
        path = self._episode_path(episode.id)
        with open(path, "w") as f:
            json.dump(episode.to_dict(), f, indent=2)

    async def load(self, episode_id: str) -> Optional[Episode]:
        """Load episode from file."""
        path = self._episode_path(episode_id)
        if not path.exists():
            return None

        with open(path, "r") as f:
            data = json.load(f)
            return Episode.from_dict(data)

    async def delete(self, episode_id: str) -> bool:
        """Delete episode file."""
        path = self._episode_path(episode_id)
        if path.exists():
            path.unlink()
            return True
        return False

    async def list_all(
        self,
        user_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Episode]:
        """List all episodes from files."""
        episodes: list[Episode] = []

        for path in self.store_path.glob("*.json"):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    episode = Episode.from_dict(data)

                    if user_id is None or episode.user_id == user_id:
                        episodes.append(episode)
            except (json.JSONDecodeError, KeyError):
                continue

        # Sort by timestamp descending
        episodes.sort(key=lambda e: e.timestamp, reverse=True)

        if limit is not None:
            episodes = episodes[:limit]

        return episodes

    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[Episode]:
        """Search episodes (loads all and filters)."""
        all_episodes = await self.list_all(user_id=user_id)

        query_lower = query.lower()
        results: list[tuple[float, Episode]] = []

        for episode in all_episodes:
            # Filter by tags
            if tags:
                if not any(tag in episode.tags for tag in tags):
                    continue

            # Score by text matching
            score = 0.0

            if query_lower in episode.summary.lower():
                score += 0.5

            for msg in episode.messages:
                content = msg.get("content", "").lower()
                if query_lower in content:
                    score += 0.3
                    break

            score += episode.importance * 0.2
            recency_boost = max(0, 1 - episode.age_days / 30) * 0.1
            score += recency_boost

            if score > 0:
                results.append((score, episode))

        results.sort(key=lambda x: x[0], reverse=True)
        return [episode for _, episode in results[:limit]]

    async def clear(self, user_id: Optional[str] = None) -> int:
        """Clear episode files."""
        count = 0

        for path in self.store_path.glob("*.json"):
            try:
                if user_id is None:
                    path.unlink()
                    count += 1
                else:
                    with open(path, "r") as f:
                        data = json.load(f)
                        if data.get("user_id") == user_id:
                            path.unlink()
                            count += 1
            except (json.JSONDecodeError, OSError):
                continue

        return count


class EpisodicMemory(VoiceMemory):
    """Long-term episodic memory for voice agents.

    Combines short-term conversation memory with long-term
    episode storage for persistent context across sessions.

    Attributes:
        store: Episode storage backend.
        user_id: Current user ID.
        current_messages: Messages in current conversation.
        max_recall_episodes: Max episodes to include in context.
        relevance_threshold: Min relevance score for recall.

    Example:
        >>> memory = EpisodicMemory(
        ...     store=FileEpisodeStore("~/.agent/memory"),
        ...     user_id="user_123",
        ... )
        >>>
        >>> # Load context includes relevant past episodes
        >>> context = await memory.load_context("Tell me about last time")
        >>> # context.metadata["episodes"] contains recalled episodes
        >>>
        >>> # After conversation, save as episode
        >>> await memory.commit_episode(
        ...     summary="Discussed project plans",
        ...     tags=["work", "planning"],
        ... )
    """

    def __init__(
        self,
        store: Optional[EpisodeStore] = None,
        user_id: Optional[str] = None,
        max_recall_episodes: int = 3,
        relevance_threshold: float = 0.1,
        include_episode_context: bool = True,
    ):
        """Initialize episodic memory.

        Args:
            store: Episode storage backend. Defaults to InMemoryEpisodeStore.
            user_id: Current user identifier.
            max_recall_episodes: Max past episodes to include in context.
            relevance_threshold: Min score for episode recall.
            include_episode_context: Whether to include past episodes in context.
        """
        self.store = store or InMemoryEpisodeStore()
        self.user_id = user_id
        self.max_recall_episodes = max_recall_episodes
        self.relevance_threshold = relevance_threshold
        self.include_episode_context = include_episode_context

        # Current conversation
        self.current_messages: list[dict[str, str]] = []

    async def load_context(
        self,
        query: Optional[str] = None,
    ) -> MemoryContext:
        """Load context including relevant past episodes.

        Args:
            query: Current query for relevance matching.

        Returns:
            MemoryContext with messages and episode metadata.
        """
        context_messages = list(self.current_messages)
        episodes: list[Episode] = []

        # Recall relevant episodes if enabled
        if self.include_episode_context and query:
            episodes = await self.recall(
                query=query,
                limit=self.max_recall_episodes,
            )

            # Add episode context as system-like messages
            if episodes:
                episode_context = self._format_episodes_for_context(episodes)
                if episode_context:
                    # Insert at beginning
                    context_messages.insert(0, {
                        "role": "system",
                        "content": episode_context,
                    })

        return MemoryContext(
            messages=context_messages,
            metadata={
                "episodes": [e.to_dict() for e in episodes],
                "episode_count": len(episodes),
                "user_id": self.user_id,
            },
        )

    async def save_context(
        self,
        user_input: str,
        assistant_output: str,
    ) -> None:
        """Save a conversation turn.

        Args:
            user_input: User message.
            assistant_output: Assistant response.
        """
        self.current_messages.append({
            "role": "user",
            "content": user_input,
        })
        self.current_messages.append({
            "role": "assistant",
            "content": assistant_output,
        })

    async def clear(self) -> None:
        """Clear current conversation (not episodes)."""
        self.current_messages.clear()

    def get_messages(self) -> list[dict[str, str]]:
        """Get current conversation messages."""
        return list(self.current_messages)

    def add_message(self, role: str, content: str) -> None:
        """Add a message to current conversation."""
        self.current_messages.append({
            "role": role,
            "content": content,
        })

    async def recall(
        self,
        query: str,
        limit: Optional[int] = None,
        tags: Optional[list[str]] = None,
    ) -> list[Episode]:
        """Recall relevant episodes from long-term memory.

        Args:
            query: Query for relevance matching.
            limit: Max episodes to return.
            tags: Optional tag filters.

        Returns:
            List of relevant episodes.
        """
        limit = limit or self.max_recall_episodes

        episodes = await self.store.search(
            query=query,
            user_id=self.user_id,
            tags=tags,
            limit=limit,
        )

        return episodes

    async def save_episode(self, episode: Episode) -> None:
        """Save an episode to long-term memory.

        Args:
            episode: Episode to save.
        """
        # Ensure user_id is set
        if episode.user_id is None:
            episode.user_id = self.user_id

        await self.store.save(episode)

    async def commit_episode(
        self,
        summary: Optional[str] = None,
        tags: Optional[list[str]] = None,
        importance: float = 0.5,
        clear_after: bool = True,
        **metadata,
    ) -> Episode:
        """Commit current conversation as an episode.

        Args:
            summary: Episode summary (auto-generated if None).
            tags: Categorization tags.
            importance: Importance score (0-1).
            clear_after: Whether to clear current messages after commit.
            **metadata: Additional metadata.

        Returns:
            The created Episode.
        """
        episode = Episode.from_conversation(
            messages=list(self.current_messages),
            user_id=self.user_id,
            summary=summary,
            tags=tags,
            importance=importance,
            **metadata,
        )

        await self.save_episode(episode)

        if clear_after:
            self.current_messages.clear()

        return episode

    async def get_episode(self, episode_id: str) -> Optional[Episode]:
        """Get a specific episode by ID.

        Args:
            episode_id: Episode identifier.

        Returns:
            Episode if found, None otherwise.
        """
        return await self.store.load(episode_id)

    async def delete_episode(self, episode_id: str) -> bool:
        """Delete an episode.

        Args:
            episode_id: Episode to delete.

        Returns:
            True if deleted.
        """
        return await self.store.delete(episode_id)

    async def list_episodes(
        self,
        limit: Optional[int] = None,
    ) -> list[Episode]:
        """List all episodes for current user.

        Args:
            limit: Max episodes to return.

        Returns:
            List of episodes, most recent first.
        """
        return await self.store.list_all(
            user_id=self.user_id,
            limit=limit,
        )

    async def clear_episodes(self) -> int:
        """Clear all episodes for current user.

        Returns:
            Number of episodes deleted.
        """
        return await self.store.clear(user_id=self.user_id)

    def _format_episodes_for_context(
        self,
        episodes: list[Episode],
    ) -> str:
        """Format episodes as context string for LLM.

        Args:
            episodes: Episodes to format.

        Returns:
            Formatted context string.
        """
        if not episodes:
            return ""

        lines = ["Here's what I remember from our previous conversations:"]

        for episode in episodes:
            date_str = episode.datetime.strftime("%Y-%m-%d")
            lines.append(f"\n[{date_str}] {episode.summary}")

            # Add key messages (abbreviated)
            user_msgs = [
                m.get("content", "")[:100]
                for m in episode.messages
                if m.get("role") == "user"
            ]
            if user_msgs:
                lines.append(f"  You asked about: {user_msgs[0]}")

        return "\n".join(lines)
