"""Memory stores for persistence.

Available stores:
- InMemoryStore: No persistence (default)
- RedisStore: Redis-based (requires redis package)
- SQLiteStore: SQLite database (requires aiosqlite package)
"""

from voice_pipeline.memory.stores.in_memory import InMemoryStore

__all__ = [
    "InMemoryStore",
]

# Optional: Redis store (requires redis package)
try:
    from voice_pipeline.memory.stores.redis import RedisStore

    __all__.append("RedisStore")
except ImportError:
    pass

# Optional: SQLite store (requires aiosqlite package)
try:
    from voice_pipeline.memory.stores.sqlite import SQLiteStore

    __all__.append("SQLiteStore")
except ImportError:
    pass
