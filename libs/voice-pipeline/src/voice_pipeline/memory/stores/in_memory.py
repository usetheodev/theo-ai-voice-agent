"""In-memory store implementation.

Simple store that keeps data in memory (no persistence).
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from voice_pipeline.memory.base import BaseMemoryStore


@dataclass
class InMemoryStore(BaseMemoryStore):
    """In-memory storage backend.

    Stores data in a dictionary. Data is lost when the
    process ends. Useful for testing and development.

    Example:
        >>> store = InMemoryStore()
        >>> await store.set("key", {"data": "value"})
        >>> result = await store.get("key")
        >>> result
        {'data': 'value'}

    Attributes:
        data: Internal storage dictionary.
    """

    _data: dict[str, Any] = field(default_factory=dict)
    """Internal storage."""

    _ttl: dict[str, float] = field(default_factory=dict)
    """TTL expiration times."""

    def __post_init__(self):
        """Initialize internal state."""
        self._data = {}
        self._ttl = {}

    def _is_expired(self, key: str) -> bool:
        """Check if a key has expired."""
        if key not in self._ttl:
            return False
        return time.time() > self._ttl[key]

    def _cleanup_expired(self) -> None:
        """Remove expired keys."""
        now = time.time()
        expired = [k for k, v in self._ttl.items() if now > v]
        for key in expired:
            self._data.pop(key, None)
            self._ttl.pop(key, None)

    async def get(self, key: str) -> Optional[Any]:
        """Get value by key.

        Args:
            key: Storage key.

        Returns:
            Stored value or None if not found or expired.
        """
        if self._is_expired(key):
            self._data.pop(key, None)
            self._ttl.pop(key, None)
            return None
        return self._data.get(key)

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value by key.

        Args:
            key: Storage key.
            value: Value to store.
            ttl: Optional time-to-live in seconds.
        """
        self._data[key] = value
        if ttl:
            self._ttl[key] = time.time() + ttl
        elif key in self._ttl:
            del self._ttl[key]

    async def delete(self, key: str) -> None:
        """Delete value by key.

        Args:
            key: Storage key.
        """
        self._data.pop(key, None)
        self._ttl.pop(key, None)

    async def exists(self, key: str) -> bool:
        """Check if key exists.

        Args:
            key: Storage key.

        Returns:
            True if key exists and not expired.
        """
        if self._is_expired(key):
            self._data.pop(key, None)
            self._ttl.pop(key, None)
            return False
        return key in self._data

    async def keys(self, pattern: str = "*") -> list[str]:
        """List keys matching pattern.

        Args:
            pattern: Glob pattern (simple implementation).

        Returns:
            List of matching keys.
        """
        self._cleanup_expired()

        if pattern == "*":
            return list(self._data.keys())

        # Simple prefix matching
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in self._data.keys() if k.startswith(prefix)]

        return [k for k in self._data.keys() if k == pattern]

    async def clear_all(self) -> None:
        """Clear all stored data."""
        self._data.clear()
        self._ttl.clear()
