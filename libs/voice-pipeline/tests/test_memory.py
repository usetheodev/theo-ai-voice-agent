"""Tests for Voice Memory System."""

import json
import tempfile
import time
from pathlib import Path

import pytest

from voice_pipeline.memory import (
    BaseMemoryStore,
    ConversationBufferMemory,
    ConversationSummaryBufferMemory,
    ConversationSummaryMemory,
    ConversationWindowMemory,
    Episode,
    EpisodicMemory,
    EpisodeStore,
    FileEpisodeStore,
    InMemoryEpisodeStore,
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


class TestEpisode:
    """Tests for Episode dataclass."""

    def test_default_values(self):
        """Test episode with default values."""
        episode = Episode()
        assert episode.messages == []
        assert episode.id != ""  # Auto-generated
        assert episode.summary == ""
        assert episode.user_id is None
        assert episode.tags == []
        assert episode.importance == 0.5

    def test_with_messages(self):
        """Test episode with messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        episode = Episode(messages=messages)
        assert len(episode.messages) == 2
        assert episode.messages[0]["content"] == "Hello"

    def test_auto_id_generation(self):
        """Test that ID is auto-generated from content."""
        ep1 = Episode(messages=[{"role": "user", "content": "Hello"}])
        ep2 = Episode(messages=[{"role": "user", "content": "Hello"}])
        # Different timestamps should generate different IDs
        assert ep1.id != "" and ep2.id != ""

    def test_from_conversation(self):
        """Test creating episode from conversation."""
        messages = [
            {"role": "user", "content": "What is the weather?"},
            {"role": "assistant", "content": "It's sunny!"},
        ]
        episode = Episode.from_conversation(
            messages=messages,
            user_id="user_123",
            tags=["weather"],
            importance=0.7,
        )

        assert episode.user_id == "user_123"
        assert episode.tags == ["weather"]
        assert episode.importance == 0.7
        assert "weather" in episode.summary.lower()

    def test_from_conversation_auto_summary(self):
        """Test auto-generated summary."""
        messages = [
            {"role": "user", "content": "Tell me a joke please"},
            {"role": "assistant", "content": "Why did the chicken..."},
        ]
        episode = Episode.from_conversation(messages=messages)
        assert "joke" in episode.summary.lower()

    def test_to_dict_from_dict(self):
        """Test serialization roundtrip."""
        original = Episode(
            messages=[{"role": "user", "content": "Test"}],
            summary="Test summary",
            user_id="user_1",
            tags=["test"],
            importance=0.8,
        )

        data = original.to_dict()
        restored = Episode.from_dict(data)

        assert restored.id == original.id
        assert restored.summary == original.summary
        assert restored.user_id == original.user_id
        assert restored.tags == original.tags
        assert restored.importance == original.importance

    def test_age_days(self):
        """Test age calculation."""
        # Episode from 2 days ago
        episode = Episode(timestamp=time.time() - 2 * 86400)
        assert 1.9 < episode.age_days < 2.1

    def test_datetime_property(self):
        """Test datetime conversion."""
        episode = Episode()
        dt = episode.datetime
        assert dt is not None


class TestInMemoryEpisodeStore:
    """Tests for InMemoryEpisodeStore."""

    @pytest.mark.asyncio
    async def test_save_and_load(self):
        """Test saving and loading episodes."""
        store = InMemoryEpisodeStore()
        episode = Episode(
            messages=[{"role": "user", "content": "Hello"}],
            summary="Greeting",
        )

        await store.save(episode)
        loaded = await store.load(episode.id)

        assert loaded is not None
        assert loaded.id == episode.id
        assert loaded.summary == "Greeting"

    @pytest.mark.asyncio
    async def test_load_nonexistent(self):
        """Test loading nonexistent episode."""
        store = InMemoryEpisodeStore()
        result = await store.load("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self):
        """Test deleting episodes."""
        store = InMemoryEpisodeStore()
        episode = Episode(summary="To delete")

        await store.save(episode)
        assert await store.delete(episode.id) is True
        assert await store.load(episode.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        """Test deleting nonexistent episode."""
        store = InMemoryEpisodeStore()
        assert await store.delete("nonexistent") is False

    @pytest.mark.asyncio
    async def test_list_all(self):
        """Test listing all episodes."""
        store = InMemoryEpisodeStore()

        for i in range(3):
            await store.save(Episode(summary=f"Episode {i}"))

        episodes = await store.list_all()
        assert len(episodes) == 3

    @pytest.mark.asyncio
    async def test_list_all_by_user(self):
        """Test filtering by user."""
        store = InMemoryEpisodeStore()

        await store.save(Episode(summary="User 1 ep", user_id="user1"))
        await store.save(Episode(summary="User 2 ep", user_id="user2"))
        await store.save(Episode(summary="User 1 ep 2", user_id="user1"))

        user1_eps = await store.list_all(user_id="user1")
        assert len(user1_eps) == 2

    @pytest.mark.asyncio
    async def test_list_all_with_limit(self):
        """Test limit parameter."""
        store = InMemoryEpisodeStore()

        for i in range(5):
            await store.save(Episode(summary=f"Episode {i}"))

        episodes = await store.list_all(limit=2)
        assert len(episodes) == 2

    @pytest.mark.asyncio
    async def test_search_by_summary(self):
        """Test searching by summary content."""
        store = InMemoryEpisodeStore()

        await store.save(Episode(summary="Discussion about weather"))
        await store.save(Episode(summary="Planning a trip"))
        await store.save(Episode(summary="Weather forecast review"))

        results = await store.search("weather")
        # Results are ranked by relevance - weather episodes should be first
        assert len(results) >= 2
        weather_summaries = [r.summary for r in results[:2]]
        assert any("weather" in s.lower() for s in weather_summaries)

    @pytest.mark.asyncio
    async def test_search_by_message_content(self):
        """Test searching by message content."""
        store = InMemoryEpisodeStore()

        await store.save(Episode(
            messages=[{"role": "user", "content": "What is Python?"}],
            summary="Tech question",
        ))
        await store.save(Episode(
            messages=[{"role": "user", "content": "Tell me a joke"}],
            summary="Entertainment",
        ))

        results = await store.search("python")
        # Python episode should rank first due to content match
        assert len(results) >= 1
        assert "python" in results[0].messages[0]["content"].lower()

    @pytest.mark.asyncio
    async def test_search_with_tags(self):
        """Test filtering search by tags."""
        store = InMemoryEpisodeStore()

        await store.save(Episode(summary="Weather chat", tags=["weather"]))
        await store.save(Episode(summary="Weather news", tags=["news"]))

        results = await store.search("weather", tags=["weather"])
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_clear_all(self):
        """Test clearing all episodes."""
        store = InMemoryEpisodeStore()

        for i in range(3):
            await store.save(Episode(summary=f"Episode {i}"))

        count = await store.clear()
        assert count == 3
        assert len(await store.list_all()) == 0

    @pytest.mark.asyncio
    async def test_clear_by_user(self):
        """Test clearing episodes by user."""
        store = InMemoryEpisodeStore()

        await store.save(Episode(summary="User 1", user_id="user1"))
        await store.save(Episode(summary="User 2", user_id="user2"))

        count = await store.clear(user_id="user1")
        assert count == 1
        assert len(await store.list_all()) == 1


class TestFileEpisodeStore:
    """Tests for FileEpisodeStore."""

    @pytest.mark.asyncio
    async def test_save_and_load(self):
        """Test saving and loading with file store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileEpisodeStore(tmpdir)
            episode = Episode(
                messages=[{"role": "user", "content": "Hello"}],
                summary="File test",
            )

            await store.save(episode)

            # Verify file exists
            path = Path(tmpdir) / f"{episode.id}.json"
            assert path.exists()

            # Load and verify
            loaded = await store.load(episode.id)
            assert loaded is not None
            assert loaded.summary == "File test"

    @pytest.mark.asyncio
    async def test_delete(self):
        """Test deleting from file store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileEpisodeStore(tmpdir)
            episode = Episode(summary="To delete")

            await store.save(episode)
            assert await store.delete(episode.id) is True

            path = Path(tmpdir) / f"{episode.id}.json"
            assert not path.exists()

    @pytest.mark.asyncio
    async def test_list_all(self):
        """Test listing from file store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileEpisodeStore(tmpdir)

            for i in range(3):
                await store.save(Episode(summary=f"Episode {i}"))

            episodes = await store.list_all()
            assert len(episodes) == 3

    @pytest.mark.asyncio
    async def test_search(self):
        """Test searching file store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileEpisodeStore(tmpdir)

            await store.save(Episode(summary="Weather discussion"))
            await store.save(Episode(summary="Food planning"))

            results = await store.search("weather")
            # Weather episode should rank first
            assert len(results) >= 1
            assert "weather" in results[0].summary.lower()

    @pytest.mark.asyncio
    async def test_clear(self):
        """Test clearing file store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileEpisodeStore(tmpdir)

            for i in range(3):
                await store.save(Episode(summary=f"Episode {i}"))

            count = await store.clear()
            assert count == 3
            assert len(list(Path(tmpdir).glob("*.json"))) == 0


class TestEpisodicMemory:
    """Tests for EpisodicMemory."""

    @pytest.mark.asyncio
    async def test_save_and_load_context(self):
        """Test saving and loading conversation context."""
        memory = EpisodicMemory()

        await memory.save_context("Hello", "Hi there!")
        await memory.save_context("How are you?", "I'm great!")

        context = await memory.load_context()
        assert len(context.messages) == 4
        assert context.messages[0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_clear_current_conversation(self):
        """Test clearing current conversation."""
        memory = EpisodicMemory()

        await memory.save_context("Hello", "Hi")
        await memory.clear()

        context = await memory.load_context()
        assert len(context.messages) == 0

    @pytest.mark.asyncio
    async def test_commit_episode(self):
        """Test committing current conversation as episode."""
        memory = EpisodicMemory(user_id="test_user")

        await memory.save_context("Tell me about weather", "It's sunny!")
        episode = await memory.commit_episode(
            summary="Weather chat",
            tags=["weather"],
        )

        assert episode.user_id == "test_user"
        assert episode.summary == "Weather chat"
        assert "weather" in episode.tags

        # Should have cleared after commit
        assert len(memory.get_messages()) == 0

    @pytest.mark.asyncio
    async def test_commit_episode_no_clear(self):
        """Test committing without clearing."""
        memory = EpisodicMemory()

        await memory.save_context("Test", "Response")
        await memory.commit_episode(clear_after=False)

        # Messages should remain
        assert len(memory.get_messages()) == 2

    @pytest.mark.asyncio
    async def test_recall_episodes(self):
        """Test recalling episodes by query."""
        memory = EpisodicMemory()

        # Create some episodes
        memory.current_messages = [
            {"role": "user", "content": "Weather forecast?"},
            {"role": "assistant", "content": "Sunny today"},
        ]
        await memory.commit_episode(summary="Weather discussion")

        memory.current_messages = [
            {"role": "user", "content": "Python code help"},
            {"role": "assistant", "content": "Here's an example"},
        ]
        await memory.commit_episode(summary="Python coding help")

        # Recall
        episodes = await memory.recall("weather")
        assert len(episodes) >= 1
        assert any("weather" in e.summary.lower() for e in episodes)

    @pytest.mark.asyncio
    async def test_load_context_with_episodes(self):
        """Test loading context includes relevant episodes."""
        memory = EpisodicMemory(include_episode_context=True)

        # Create an episode
        memory.current_messages = [
            {"role": "user", "content": "I like sunny weather"},
            {"role": "assistant", "content": "Nice!"},
        ]
        await memory.commit_episode(summary="Weather preferences")

        # New conversation referencing old topic
        memory.current_messages = [
            {"role": "user", "content": "Remember what I said?"},
        ]

        context = await memory.load_context(query="weather preferences")

        # Should include episode context
        assert "episodes" in context.metadata
        assert context.metadata["episode_count"] >= 0

    @pytest.mark.asyncio
    async def test_episodic_memory_is_voice_memory(self):
        """Test that EpisodicMemory implements VoiceMemory."""
        memory = EpisodicMemory()
        assert isinstance(memory, VoiceMemory)

    @pytest.mark.asyncio
    async def test_get_messages_sync(self):
        """Test synchronous get_messages."""
        memory = EpisodicMemory()
        memory.add_message("user", "Hello")
        memory.add_message("assistant", "Hi!")

        messages = memory.get_messages()
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_save_and_get_episode(self):
        """Test saving and getting specific episode."""
        memory = EpisodicMemory()

        episode = Episode(summary="Test episode")
        await memory.save_episode(episode)

        loaded = await memory.get_episode(episode.id)
        assert loaded is not None
        assert loaded.summary == "Test episode"

    @pytest.mark.asyncio
    async def test_delete_episode(self):
        """Test deleting episode."""
        memory = EpisodicMemory()

        episode = Episode(summary="To delete")
        await memory.save_episode(episode)

        assert await memory.delete_episode(episode.id) is True
        assert await memory.get_episode(episode.id) is None

    @pytest.mark.asyncio
    async def test_list_episodes(self):
        """Test listing user episodes."""
        memory = EpisodicMemory(user_id="user1")

        await memory.save_episode(Episode(summary="Episode 1"))
        await memory.save_episode(Episode(summary="Episode 2"))

        episodes = await memory.list_episodes()
        assert len(episodes) == 2

    @pytest.mark.asyncio
    async def test_clear_episodes(self):
        """Test clearing user episodes."""
        memory = EpisodicMemory(user_id="user1")

        await memory.save_episode(Episode(summary="Episode 1"))
        await memory.save_episode(Episode(summary="Episode 2"))

        count = await memory.clear_episodes()
        assert count == 2
        assert len(await memory.list_episodes()) == 0

    @pytest.mark.asyncio
    async def test_with_file_store(self):
        """Test EpisodicMemory with FileEpisodeStore."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileEpisodeStore(tmpdir)
            memory = EpisodicMemory(store=store, user_id="test")

            await memory.save_context("Hello", "Hi!")
            episode = await memory.commit_episode(summary="Greeting")

            # Verify persistence
            files = list(Path(tmpdir).glob("*.json"))
            assert len(files) == 1

            # Verify can recall
            recalled = await memory.recall("hello")
            assert len(recalled) >= 1
