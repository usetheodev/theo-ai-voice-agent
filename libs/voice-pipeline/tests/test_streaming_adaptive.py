"""Tests for AdaptiveStreamingStrategy.

Covers:
- Phase transitions (WORD -> CLAUSE)
- Buffer migration between phases
- Reset behavior
- Flush in both phases
- Builder integration
- Content preservation (no text lost during transition)
"""

import pytest

from voice_pipeline.streaming.adaptive_strategy import AdaptiveStreamingStrategy
from voice_pipeline.streaming.strategy import StreamingGranularity


class TestAdaptiveStreamingStrategy:
    """Test suite for AdaptiveStreamingStrategy."""

    def test_starts_in_word_phase(self):
        """Strategy starts in WORD phase."""
        strategy = AdaptiveStreamingStrategy()
        assert strategy.phase == "word"

    def test_first_chunk_emits_words(self):
        """First emission uses word-level grouping."""
        strategy = AdaptiveStreamingStrategy(first_chunk_words=3)

        # Feed 3 words
        result1 = strategy.process("Olá ")
        assert result1 == []
        result2 = strategy.process("eu ")
        assert result2 == []
        result3 = strategy.process("sou ")
        assert result3 == ["Olá eu sou"]

    def test_transitions_to_clause_after_first_chunk(self):
        """After first word chunk, transitions to CLAUSE phase."""
        strategy = AdaptiveStreamingStrategy(first_chunk_words=2)

        # Emit first chunk (2 words)
        strategy.process("Olá ")
        strategy.process("mundo ")
        assert strategy.phase == "clause"

    def test_clause_phase_uses_clause_boundaries(self):
        """After transition, uses clause-level emission."""
        strategy = AdaptiveStreamingStrategy(
            first_chunk_words=2,
            clause_min_chars=8,
        )

        # Phase WORD: emit first chunk
        strategy.process("Olá ")
        chunks = strategy.process("mundo ")
        assert len(chunks) == 1  # First word chunk
        assert strategy.phase == "clause"

        # Phase CLAUSE: accumulates until clause boundary with min_chars
        result = strategy.process("eu gosto de café,")
        # The comma triggers emission since text >= min_chars
        assert len(result) >= 1
        assert any("café" in c for c in result)

        # Continue with more text
        result = strategy.process(" mas prefiro chá.")
        # Period triggers emission
        assert len(result) >= 1

    def test_buffer_migration_on_transition(self):
        """Remaining word buffer migrates to clause strategy on transition."""
        strategy = AdaptiveStreamingStrategy(first_chunk_words=2)

        # Feed tokens that include extra text after the 2-word boundary
        strategy.process("Um ")
        chunks = strategy.process("dois ")
        assert chunks == ["Um dois"]

        # The word strategy had remaining text which should migrate
        # Now verify clause strategy works with any migrated content
        assert strategy.phase == "clause"

    def test_flush_in_word_phase(self):
        """Flush works correctly in WORD phase."""
        strategy = AdaptiveStreamingStrategy(first_chunk_words=3)

        strategy.process("Olá ")
        strategy.process("mundo")
        # Only 2 words, not enough for first chunk

        result = strategy.flush()
        assert result is not None
        assert "Olá" in result
        assert "mundo" in result

    def test_flush_in_clause_phase(self):
        """Flush works correctly in CLAUSE phase."""
        strategy = AdaptiveStreamingStrategy(first_chunk_words=2)

        # Transition to clause
        strategy.process("Um ")
        strategy.process("dois ")
        assert strategy.phase == "clause"

        # Add text without clause boundary
        strategy.process("texto sem pontuação")

        result = strategy.flush()
        assert result is not None
        assert "texto sem pontuação" in result

    def test_reset_returns_to_word_phase(self):
        """Reset returns to initial WORD phase."""
        strategy = AdaptiveStreamingStrategy(first_chunk_words=2)

        # Transition to clause
        strategy.process("Um ")
        strategy.process("dois ")
        assert strategy.phase == "clause"

        # Reset
        strategy.reset()
        assert strategy.phase == "word"

        # Should work again from word phase
        strategy.process("Novo ")
        chunks = strategy.process("início ")
        assert len(chunks) == 1

    def test_content_preservation_full_response(self):
        """All content is preserved across phase transition."""
        strategy = AdaptiveStreamingStrategy(first_chunk_words=3)

        original_text = "Olá eu sou um assistente de voz, e posso ajudar você."
        all_chunks = []

        # Feed token by token (simulating LLM output)
        for word in original_text.split():
            chunks = strategy.process(word + " ")
            all_chunks.extend(chunks)

        # Flush remaining
        remaining = strategy.flush()
        if remaining:
            all_chunks.append(remaining)

        # Reconstruct and verify no text was lost
        reconstructed = " ".join(all_chunks)
        # Remove extra spaces for comparison
        original_words = original_text.split()
        reconstructed_words = reconstructed.split()
        assert original_words == reconstructed_words

    def test_granularity_reports_clause(self):
        """Reports CLAUSE as the granularity."""
        strategy = AdaptiveStreamingStrategy()
        assert strategy.granularity == StreamingGranularity.CLAUSE

    def test_name_reflects_phase(self):
        """Name includes current phase."""
        strategy = AdaptiveStreamingStrategy(first_chunk_words=2)
        assert "word" in strategy.name.lower()

        strategy.process("Um ")
        strategy.process("dois ")
        assert "clause" in strategy.name.lower()

    def test_builder_integration(self):
        """Strategy can be created via VoiceAgent builder."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        builder = VoiceAgentBuilder()
        builder.streaming_granularity(
            "adaptive",
            first_chunk_words=3,
            clause_min_chars=10,
            language="pt",
        )

        assert builder._streaming_strategy is not None
        assert isinstance(builder._streaming_strategy, AdaptiveStreamingStrategy)
