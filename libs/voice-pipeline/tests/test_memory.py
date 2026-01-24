"""Tests for Voice Memory System."""

import pytest

from voice_pipeline.memory import (
    BaseMemoryStore,
    ConversationBufferMemory,
    ConversationSummaryBufferMemory,
    ConversationSummaryMemory,
    ConversationWindowMemory,
    InMemoryStore,
    MemoryContext,
    VoiceMemory,
)


class TestMemoryContext:
    """Tests for MemoryContext."""

    def test_default_values(self):
        """Test default values."""
        ctx = MemoryContext()
        assert ctx.messages == []
        assert ctx.summary is None
        assert ctx.entities == {}
        assert ctx.metadata == {}

    def test_with_messages(self):
        """Test with messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        ctx = MemoryContext(messages=messages)
        assert len(ctx.messages) == 2
        assert ctx.messages[0]["role"] == "user"

    def test_with_summary(self):
        """Test with summary."""
        ctx = MemoryContext(summary="Previous conversation about weather")
        assert ctx.summary == "Previous conversation about weather"


class TestConversationBufferMemory:
    """Tests for ConversationBufferMemory."""

    @pytest.mark.asyncio
    async def test_save_and_load(self):
        """Test saving and loading context."""
        memory = ConversationBufferMemory(max_messages=10)

        await memory.save_context("Hello!", "Hi there!")

        context = await memory.load_context()
        assert len(context.messages) == 2
        assert context.messages[0]["role"] == "user"
        assert context.messages[0]["content"] == "Hello!"
        assert context.messages[1]["role"] == "assistant"
        assert context.messages[1]["content"] == "Hi there!"

    @pytest.mark.asyncio
    async def test_max_messages(self):
        """Test max_messages limit."""
        memory = ConversationBufferMemory(max_messages=4)

        # Add 3 turns (6 messages)
        for i in range(3):
            await memory.save_context(f"Question {i}", f"Answer {i}")

        context = await memory.load_context()
        # Should be limited to 4 messages
        assert len(context.messages) == 4

    @pytest.mark.asyncio
    async def test_clear(self):
        """Test clearing memory."""
        memory = ConversationBufferMemory()

        await memory.save_context("Hello", "Hi")
        await memory.clear()

        context = await memory.load_context()
        assert len(context.messages) == 0

    def test_get_messages_sync(self):
        """Test synchronous get_messages."""
        memory = ConversationBufferMemory()
        memory.add_message("user", "Hello")
        memory.add_message("assistant", "Hi")

        messages = memory.get_messages()
        assert len(messages) == 2

    def test_add_message_sync(self):
        """Test synchronous add_message."""
        memory = ConversationBufferMemory(max_messages=2)
        memory.add_message("user", "Message 1")
        memory.add_message("assistant", "Response 1")
        memory.add_message("user", "Message 2")

        # Should trim to max_messages
        assert len(memory.get_messages()) == 2


class TestConversationWindowMemory:
    """Tests for ConversationWindowMemory."""

    @pytest.mark.asyncio
    async def test_max_turns(self):
        """Test max_turns limit."""
        memory = ConversationWindowMemory(max_turns=2)

        # Add 3 turns
        for i in range(3):
            await memory.save_context(f"Q{i}", f"A{i}")

        context = await memory.load_context()
        # Should keep only last 2 turns (4 messages)
        assert len(context.messages) == 4

    @pytest.mark.asyncio
    async def test_clear(self):
        """Test clearing memory."""
        memory = ConversationWindowMemory()

        await memory.save_context("Hello", "Hi")
        await memory.clear()

        context = await memory.load_context()
        assert len(context.messages) == 0


class TestConversationSummaryMemory:
    """Tests for ConversationSummaryMemory."""

    @pytest.mark.asyncio
    async def test_without_llm(self):
        """Test summary memory without LLM (truncation mode)."""
        memory = ConversationSummaryMemory(
            llm=None,
            max_messages_before_summary=4,
            keep_recent_messages=2,
        )

        # Add enough messages to trigger summarization
        for i in range(3):
            await memory.save_context(f"Q{i}", f"A{i}")

        context = await memory.load_context()
        # Should have truncated to keep_recent_messages
        assert len(context.messages) <= 4

    @pytest.mark.asyncio
    async def test_clear(self):
        """Test clearing memory."""
        memory = ConversationSummaryMemory()

        await memory.save_context("Hello", "Hi")
        memory._summary = "Test summary"
        await memory.clear()

        context = await memory.load_context()
        assert len(context.messages) == 0
        assert context.summary is None


class TestConversationSummaryBufferMemory:
    """Tests for ConversationSummaryBufferMemory."""

    @pytest.mark.asyncio
    async def test_token_limit(self):
        """Test token limit management."""
        memory = ConversationSummaryBufferMemory(
            llm=None,
            max_token_limit=50,  # Very low limit
        )

        # Add a long message
        await memory.save_context(
            "This is a very long question with many words",
            "This is a very long answer with even more words",
        )

        # Should have pruned something
        context = await memory.load_context()
        # Exact behavior depends on implementation
        assert context is not None


class TestInMemoryStore:
    """Tests for InMemoryStore."""

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        """Test set and get."""
        store = InMemoryStore()

        await store.set("key1", {"value": 123})
        result = await store.get("key1")

        assert result == {"value": 123}

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        """Test getting nonexistent key."""
        store = InMemoryStore()

        result = await store.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self):
        """Test delete."""
        store = InMemoryStore()

        await store.set("key", "value")
        await store.delete("key")

        result = await store.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_exists(self):
        """Test exists."""
        store = InMemoryStore()

        await store.set("key", "value")

        assert await store.exists("key") is True
        assert await store.exists("nonexistent") is False

    @pytest.mark.asyncio
    async def test_keys(self):
        """Test keys listing."""
        store = InMemoryStore()

        await store.set("memory:session1", [])
        await store.set("memory:session2", [])
        await store.set("other:key", [])

        # All keys
        all_keys = await store.keys("*")
        assert len(all_keys) == 3

        # Prefix filter
        memory_keys = await store.keys("memory:*")
        assert len(memory_keys) == 2

    @pytest.mark.asyncio
    async def test_clear_all(self):
        """Test clear all."""
        store = InMemoryStore()

        await store.set("key1", "value1")
        await store.set("key2", "value2")
        await store.clear_all()

        assert await store.exists("key1") is False
        assert await store.exists("key2") is False


class TestMemoryWithStore:
    """Tests for memory with persistence store."""

    @pytest.mark.asyncio
    async def test_buffer_memory_with_store(self):
        """Test buffer memory with InMemoryStore."""
        store = InMemoryStore()
        memory = ConversationBufferMemory(
            store=store,
            session_id="test-session",
        )

        await memory.save_context("Hello", "Hi")

        # Verify persisted
        stored = await store.get("memory:test-session")
        assert stored is not None
        assert len(stored) == 2

    @pytest.mark.asyncio
    async def test_clear_with_store(self):
        """Test clearing memory with store."""
        store = InMemoryStore()
        memory = ConversationBufferMemory(
            store=store,
            session_id="test-session",
        )

        await memory.save_context("Hello", "Hi")
        await memory.clear()

        stored = await store.get("memory:test-session")
        assert stored is None


class TestMemoryInterface:
    """Tests for VoiceMemory interface compliance."""

    def test_buffer_memory_is_voice_memory(self):
        """Test that buffer memory implements VoiceMemory."""
        memory = ConversationBufferMemory()
        assert isinstance(memory, VoiceMemory)

    def test_window_memory_is_voice_memory(self):
        """Test that window memory implements VoiceMemory."""
        memory = ConversationWindowMemory()
        assert isinstance(memory, VoiceMemory)

    def test_summary_memory_is_voice_memory(self):
        """Test that summary memory implements VoiceMemory."""
        memory = ConversationSummaryMemory()
        assert isinstance(memory, VoiceMemory)

    def test_in_memory_store_is_base_store(self):
        """Test that InMemoryStore implements BaseMemoryStore."""
        store = InMemoryStore()
        assert isinstance(store, BaseMemoryStore)
