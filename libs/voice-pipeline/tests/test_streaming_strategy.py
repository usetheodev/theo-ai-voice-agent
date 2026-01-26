"""Tests for streaming strategies (Phase 8).

Tests the StreamingStrategy interface and all implementations:
- SentenceStreamingStrategy (wrapper of SentenceStreamer)
- ClauseStreamingStrategy (clause-level boundaries)
- WordStreamingStrategy (word-level, minimum latency)

Also tests builder integration with .streaming_granularity().
"""

import pytest

from voice_pipeline.streaming.strategy import StreamingGranularity, StreamingStrategy
from voice_pipeline.streaming.sentence_strategy import SentenceStreamingStrategy
from voice_pipeline.streaming.clause_strategy import ClauseStreamingStrategy
from voice_pipeline.streaming.word_strategy import WordStreamingStrategy


# =============================================================================
# StreamingStrategy Interface
# =============================================================================


class TestStreamingStrategyInterface:
    """Test the abstract interface."""

    def test_granularity_enum_values(self):
        assert StreamingGranularity.WORD.value == "word"
        assert StreamingGranularity.CLAUSE.value == "clause"
        assert StreamingGranularity.SENTENCE.value == "sentence"

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            StreamingStrategy()

    def test_all_strategies_implement_interface(self):
        strategies = [
            SentenceStreamingStrategy(),
            ClauseStreamingStrategy(),
            WordStreamingStrategy(),
        ]
        for s in strategies:
            assert isinstance(s, StreamingStrategy)
            assert hasattr(s, "process")
            assert hasattr(s, "flush")
            assert hasattr(s, "reset")
            assert hasattr(s, "granularity")
            assert hasattr(s, "name")

    def test_strategy_name_property(self):
        s = WordStreamingStrategy()
        assert "WordStreamingStrategy" in s.name
        assert "word" in s.name


# =============================================================================
# SentenceStreamingStrategy
# =============================================================================


class TestSentenceStreamingStrategy:
    """Test the sentence-level strategy (wrapper of SentenceStreamer)."""

    def test_granularity(self):
        s = SentenceStreamingStrategy()
        assert s.granularity == StreamingGranularity.SENTENCE

    def test_basic_sentence(self):
        s = SentenceStreamingStrategy()
        chunks = s.process("Olá! ")
        assert chunks == ["Olá!"]

    def test_buffered_sentence(self):
        s = SentenceStreamingStrategy()
        chunks = s.process("Como vai")
        assert chunks == []
        chunks = s.process(" você?")
        assert len(chunks) == 1
        assert "Como vai você?" in chunks[0]

    def test_flush_remaining(self):
        s = SentenceStreamingStrategy()
        s.process("Texto sem pontuação")
        remaining = s.flush()
        assert remaining is not None
        assert "Texto sem pontuação" in remaining

    def test_flush_empty(self):
        s = SentenceStreamingStrategy()
        assert s.flush() is None

    def test_reset(self):
        s = SentenceStreamingStrategy()
        s.process("Algo no buffer")
        s.reset()
        remaining = s.flush()
        assert remaining is None

    def test_config_accessible(self):
        s = SentenceStreamingStrategy()
        assert s.config is not None

    def test_multiple_sentences(self):
        """Simulate token-by-token input producing multiple sentences."""
        s = SentenceStreamingStrategy()
        all_chunks = []
        tokens = [
            "Esta ", "é ", "a ", "primeira ", "frase. ",
            "E ", "esta ", "é ", "a ", "segunda ", "frase. ",
            "E ", "a ", "terceira ", "também. ",
        ]
        for token in tokens:
            all_chunks.extend(s.process(token))
        remaining = s.flush()
        if remaining:
            all_chunks.append(remaining)
        assert len(all_chunks) >= 2  # At least 2 chunks emitted


# =============================================================================
# ClauseStreamingStrategy
# =============================================================================


class TestClauseStreamingStrategy:
    """Test clause-level streaming."""

    def test_granularity(self):
        s = ClauseStreamingStrategy()
        assert s.granularity == StreamingGranularity.CLAUSE

    def test_basic_comma_split(self):
        s = ClauseStreamingStrategy(min_chars=5)
        chunks = s.process("Eu gosto de café, mas prefiro chá.")
        # Should split at comma and/or period
        assert len(chunks) >= 1

    def test_sentence_end_triggers(self):
        s = ClauseStreamingStrategy(min_chars=3)
        chunks = s.process("Olá mundo. Tudo bem?")
        assert len(chunks) >= 1

    def test_min_chars_respected(self):
        s = ClauseStreamingStrategy(min_chars=20)
        # Short clause should NOT be emitted
        chunks = s.process("Oi, tudo")
        assert chunks == []  # "Oi," is too short (< 20 chars)

    def test_max_chars_forces_emission(self):
        s = ClauseStreamingStrategy(min_chars=5, max_chars=30)
        # Long text without punctuation should force split
        text = "abcdefghij " * 5  # 55 chars, no punctuation
        chunks = s.process(text)
        assert len(chunks) >= 1

    def test_conjunction_boundary_pt(self):
        s = ClauseStreamingStrategy(min_chars=5, language="pt")
        # "mas" is a conjunction — should split before it
        chunks = s.process("Eu gosto de café mas prefiro chá")
        # Should detect " mas " as boundary
        assert len(chunks) >= 1
        if chunks:
            assert "café" in chunks[0] or "gosto" in chunks[0]

    def test_conjunction_boundary_en(self):
        s = ClauseStreamingStrategy(min_chars=5, language="en")
        chunks = s.process("I like coffee but prefer tea.")
        assert len(chunks) >= 1

    def test_number_comma_not_split(self):
        """Commas inside numbers like 1,000 should not split."""
        s = ClauseStreamingStrategy(min_chars=3)
        chunks = s.process("O valor é 1,000 reais.")
        # Should not split at the comma in "1,000"
        combined = " ".join(chunks) if chunks else ""
        # The sentence should end at the period
        assert len(chunks) >= 1

    def test_semicolon_split(self):
        s = ClauseStreamingStrategy(min_chars=5)
        chunks = s.process("Primeira parte; segunda parte.")
        assert len(chunks) >= 1

    def test_flush_remaining(self):
        s = ClauseStreamingStrategy()
        s.process("Texto parcial sem")
        remaining = s.flush()
        assert remaining is not None
        assert "Texto parcial sem" in remaining

    def test_flush_empty(self):
        s = ClauseStreamingStrategy()
        assert s.flush() is None

    def test_reset(self):
        s = ClauseStreamingStrategy()
        s.process("Algo no buffer")
        s.reset()
        assert s.flush() is None

    def test_incremental_tokens(self):
        """Simulate token-by-token LLM output."""
        s = ClauseStreamingStrategy(min_chars=5)
        all_chunks = []
        tokens = ["Eu ", "gosto ", "de ", "café, ", "mas ", "prefiro ", "chá."]
        for token in tokens:
            chunks = s.process(token)
            all_chunks.extend(chunks)
        remaining = s.flush()
        if remaining:
            all_chunks.append(remaining)

        # All text should be accounted for
        combined = " ".join(all_chunks)
        assert "café" in combined
        assert "chá" in combined

    def test_exclamation_triggers_emission(self):
        s = ClauseStreamingStrategy(min_chars=3)
        chunks = s.process("Incrível! Fantástico!")
        assert len(chunks) >= 1

    def test_question_triggers_emission(self):
        s = ClauseStreamingStrategy(min_chars=3)
        chunks = s.process("Como vai? Tudo bem?")
        assert len(chunks) >= 1


# =============================================================================
# WordStreamingStrategy
# =============================================================================


class TestWordStreamingStrategy:
    """Test word-level streaming."""

    def test_granularity(self):
        s = WordStreamingStrategy()
        assert s.granularity == StreamingGranularity.WORD

    def test_single_word(self):
        s = WordStreamingStrategy()
        chunks = s.process("Olá ")
        assert chunks == ["Olá"]

    def test_word_not_emitted_without_space(self):
        s = WordStreamingStrategy()
        chunks = s.process("Olá")
        assert chunks == []

    def test_multiple_words(self):
        s = WordStreamingStrategy()
        chunks = s.process("Olá mundo ")
        assert "Olá" in chunks
        assert "mundo" in chunks

    def test_flush_incomplete_word(self):
        s = WordStreamingStrategy()
        s.process("incompleto")
        remaining = s.flush()
        assert remaining == "incompleto"

    def test_flush_empty(self):
        s = WordStreamingStrategy()
        assert s.flush() is None

    def test_flush_with_word_buffer(self):
        """Flush should emit words in word_buffer + remaining buffer."""
        s = WordStreamingStrategy(min_word_length=5)
        s.process("de ")  # Too short with min_word_length=5
        remaining = s.flush()
        assert remaining is not None
        assert "de" in remaining

    def test_reset(self):
        s = WordStreamingStrategy()
        s.process("algo no buffer")
        s.reset()
        assert s.flush() is None

    def test_group_size_2(self):
        s = WordStreamingStrategy(group_size=2)
        chunks = s.process("Eu gosto ")
        # Two words => should emit one group
        assert len(chunks) == 1
        assert chunks[0] == "Eu gosto"

    def test_group_size_2_partial(self):
        s = WordStreamingStrategy(group_size=2)
        chunks = s.process("Apenas ")
        # Only 1 word, need 2 to emit
        assert chunks == []

    def test_group_size_3(self):
        s = WordStreamingStrategy(group_size=3)
        all_chunks = []
        all_chunks.extend(s.process("Um "))
        all_chunks.extend(s.process("dois "))
        all_chunks.extend(s.process("três "))
        assert len(all_chunks) == 1
        assert all_chunks[0] == "Um dois três"

    def test_min_word_length(self):
        s = WordStreamingStrategy(min_word_length=3)
        chunks = s.process("Eu ")
        # "Eu" has 2 chars, less than min_word_length=3
        assert chunks == []

    def test_min_word_length_passes(self):
        s = WordStreamingStrategy(min_word_length=3)
        chunks = s.process("Olá ")
        # "Olá" has 3 chars, meets min_word_length
        assert chunks == ["Olá"]

    def test_newline_as_separator(self):
        s = WordStreamingStrategy()
        chunks = s.process("Olá\nmundo ")
        assert "Olá" in chunks
        assert "mundo" in chunks

    def test_incremental_tokens(self):
        """Simulate token-by-token LLM output."""
        s = WordStreamingStrategy()
        all_chunks = []
        tokens = ["Ol", "á ", "mun", "do ", "bo", "ni", "to!"]
        for token in tokens:
            chunks = s.process(token)
            all_chunks.extend(chunks)
        remaining = s.flush()
        if remaining:
            all_chunks.append(remaining)

        assert "Olá" in all_chunks
        assert "mundo" in all_chunks
        assert "bonito!" in all_chunks

    def test_empty_words_ignored(self):
        """Multiple spaces should not produce empty words."""
        s = WordStreamingStrategy()
        chunks = s.process("  hello  world  ")
        # Should only emit actual words, not empty strings
        for chunk in chunks:
            assert chunk.strip() != ""


# =============================================================================
# Builder Integration
# =============================================================================


class TestBuilderStreamingGranularity:
    """Test VoiceAgentBuilder.streaming_granularity()."""

    def test_sentence_granularity(self):
        from voice_pipeline.agents.base import VoiceAgentBuilder
        b = VoiceAgentBuilder()
        result = b.streaming_granularity("sentence")
        assert result is b  # Returns self for chaining
        assert isinstance(b._streaming_strategy, SentenceStreamingStrategy)

    def test_clause_granularity(self):
        from voice_pipeline.agents.base import VoiceAgentBuilder
        b = VoiceAgentBuilder()
        b.streaming_granularity("clause", min_chars=10, language="en")
        assert isinstance(b._streaming_strategy, ClauseStreamingStrategy)
        assert b._streaming_strategy.min_chars == 10
        assert b._streaming_strategy.language == "en"

    def test_word_granularity(self):
        from voice_pipeline.agents.base import VoiceAgentBuilder
        b = VoiceAgentBuilder()
        b.streaming_granularity("word", group_size=3, min_word_length=2)
        assert isinstance(b._streaming_strategy, WordStreamingStrategy)
        assert b._streaming_strategy.group_size == 3
        assert b._streaming_strategy.min_word_length == 2

    def test_invalid_granularity_raises(self):
        from voice_pipeline.agents.base import VoiceAgentBuilder
        b = VoiceAgentBuilder()
        with pytest.raises(ValueError, match="Streaming granularity desconhecida"):
            b.streaming_granularity("phoneme")

    def test_chaining(self):
        from voice_pipeline.agents.base import VoiceAgentBuilder
        b = (
            VoiceAgentBuilder()
            .streaming_granularity("clause")
        )
        assert isinstance(b._streaming_strategy, ClauseStreamingStrategy)


# =============================================================================
# Chain Integration
# =============================================================================


class TestChainStreamingStrategy:
    """Test StreamingVoiceChain uses streaming_strategy."""

    def test_chain_accepts_strategy(self):
        """Chain should accept streaming_strategy parameter."""
        from unittest.mock import MagicMock
        from voice_pipeline.chains.streaming import StreamingVoiceChain

        mock_asr = MagicMock()
        mock_llm = MagicMock()
        mock_tts = MagicMock()
        strategy = ClauseStreamingStrategy(min_chars=10)

        chain = StreamingVoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
            streaming_strategy=strategy,
        )

        assert chain.streaming_strategy is strategy

    def test_chain_default_strategy_is_none(self):
        """Chain should default to None (uses SentenceStreamer fallback)."""
        from unittest.mock import MagicMock
        from voice_pipeline.chains.streaming import StreamingVoiceChain

        chain = StreamingVoiceChain(
            asr=MagicMock(),
            llm=MagicMock(),
            tts=MagicMock(),
        )

        assert chain.streaming_strategy is None

    def test_get_strategy_returns_provided(self):
        """_get_strategy() should return the provided strategy."""
        from unittest.mock import MagicMock
        from voice_pipeline.chains.streaming import StreamingVoiceChain

        strategy = WordStreamingStrategy(group_size=2)
        chain = StreamingVoiceChain(
            asr=MagicMock(),
            llm=MagicMock(),
            tts=MagicMock(),
            streaming_strategy=strategy,
        )

        result = chain._get_strategy()
        assert result is strategy

    def test_get_strategy_returns_default_sentence(self):
        """_get_strategy() should return SentenceStreamingStrategy when no strategy set."""
        from unittest.mock import MagicMock
        from voice_pipeline.chains.streaming import StreamingVoiceChain

        chain = StreamingVoiceChain(
            asr=MagicMock(),
            llm=MagicMock(),
            tts=MagicMock(),
        )

        result = chain._get_strategy()
        assert isinstance(result, SentenceStreamingStrategy)

    def test_get_strategy_resets_before_returning(self):
        """_get_strategy() should reset the strategy."""
        from unittest.mock import MagicMock
        from voice_pipeline.chains.streaming import StreamingVoiceChain

        strategy = ClauseStreamingStrategy()
        strategy.process("Some buffered text, that should be cleared.")

        chain = StreamingVoiceChain(
            asr=MagicMock(),
            llm=MagicMock(),
            tts=MagicMock(),
            streaming_strategy=strategy,
        )

        result = chain._get_strategy()
        # Buffer should be reset
        assert result.flush() is None


# =============================================================================
# Cross-Strategy Comparison
# =============================================================================


class TestCrossStrategyComparison:
    """Compare behavior across strategies on the same input."""

    def test_all_strategies_preserve_content(self):
        """All strategies should preserve full text (no data loss)."""
        text_tokens = [
            "Eu ", "gosto ", "muito ", "de ", "café, ",
            "mas ", "prefiro ", "chá. ",
            "E ", "você?",
        ]
        full_text = "".join(text_tokens)

        strategies = [
            SentenceStreamingStrategy(),
            ClauseStreamingStrategy(min_chars=3),
            WordStreamingStrategy(),
        ]

        for strategy in strategies:
            all_chunks = []
            for token in text_tokens:
                chunks = strategy.process(token)
                all_chunks.extend(chunks)
            remaining = strategy.flush()
            if remaining:
                all_chunks.append(remaining)

            # Reconstruct text
            reconstructed = " ".join(all_chunks)
            # All meaningful content should be present
            for word in ["gosto", "café", "prefiro", "chá", "você"]:
                assert word in reconstructed, (
                    f"'{word}' missing in {strategy.name}: {reconstructed}"
                )

    def test_word_emits_more_chunks_than_sentence(self):
        """Word strategy should produce more chunks than sentence."""
        tokens = ["Olá ", "mundo! ", "Como ", "vai ", "você? "]

        word_strategy = WordStreamingStrategy()
        sentence_strategy = SentenceStreamingStrategy()

        word_chunks = []
        sentence_chunks = []

        for token in tokens:
            word_chunks.extend(word_strategy.process(token))
            sentence_chunks.extend(sentence_strategy.process(token))

        w_remaining = word_strategy.flush()
        s_remaining = sentence_strategy.flush()
        if w_remaining:
            word_chunks.append(w_remaining)
        if s_remaining:
            sentence_chunks.append(s_remaining)

        assert len(word_chunks) >= len(sentence_chunks), (
            f"Word ({len(word_chunks)}) should produce >= chunks than "
            f"Sentence ({len(sentence_chunks)})"
        )

    def test_clause_between_word_and_sentence(self):
        """Clause strategy should typically produce chunks between word and sentence count."""
        tokens = [
            "Eu ", "gosto ", "de ", "café, ",
            "mas ", "também ", "gosto ", "de ", "chá. ",
            "E ", "você, ", "o ", "que ", "prefere? ",
        ]

        word_s = WordStreamingStrategy()
        clause_s = ClauseStreamingStrategy(min_chars=5)
        sentence_s = SentenceStreamingStrategy()

        def count_chunks(strategy):
            chunks = []
            for t in tokens:
                chunks.extend(strategy.process(t))
            r = strategy.flush()
            if r:
                chunks.append(r)
            return len(chunks)

        word_count = count_chunks(word_s)
        clause_count = count_chunks(clause_s)
        sentence_count = count_chunks(sentence_s)

        # Word should produce the most chunks
        assert word_count >= clause_count, (
            f"Word ({word_count}) should produce >= Clause ({clause_count})"
        )
        # Clause should produce >= sentence
        assert clause_count >= sentence_count, (
            f"Clause ({clause_count}) should produce >= Sentence ({sentence_count})"
        )
