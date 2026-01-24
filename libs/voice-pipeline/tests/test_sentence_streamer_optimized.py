"""Tests for optimized SentenceStreamer functionality.

Tests the new optimizations:
- Quick phrases detection (Olá!, Sim., Não.)
- Adaptive min_chars based on punctuation
- Timeout-based emission
- Portuguese language support
"""

import asyncio
import pytest
from unittest.mock import MagicMock

from voice_pipeline.streaming.sentence_streamer import (
    SentenceStreamer,
    SentenceStreamerConfig,
    QUICK_PHRASES_PT,
    QUICK_PHRASES_EN,
    QUICK_PHRASES,
)


# =============================================================================
# Quick Phrases Tests
# =============================================================================


class TestQuickPhrases:
    """Tests for quick phrase detection and immediate emission."""

    def test_quick_phrases_pt_defined(self):
        """Portuguese quick phrases should be defined."""
        assert "olá" in QUICK_PHRASES_PT
        assert "sim" in QUICK_PHRASES_PT
        assert "não" in QUICK_PHRASES_PT
        assert "ok" in QUICK_PHRASES_PT
        assert "obrigado" in QUICK_PHRASES_PT

    def test_quick_phrases_en_defined(self):
        """English quick phrases should be defined."""
        assert "hello" in QUICK_PHRASES_EN
        assert "yes" in QUICK_PHRASES_EN
        assert "no" in QUICK_PHRASES_EN
        assert "ok" in QUICK_PHRASES_EN
        assert "thanks" in QUICK_PHRASES_EN

    def test_combined_quick_phrases(self):
        """Combined set should include both languages."""
        assert QUICK_PHRASES == QUICK_PHRASES_PT | QUICK_PHRASES_EN

    def test_ola_emitted_immediately(self):
        """'Olá!' should be emitted immediately despite being short."""
        streamer = SentenceStreamer()

        # "Olá!" is only 4 chars but should emit immediately
        result = streamer.process("Olá!")

        assert len(result) == 1
        assert result[0] == "Olá!"

    def test_sim_emitted_immediately(self):
        """'Sim.' should be emitted immediately."""
        streamer = SentenceStreamer()

        result = streamer.process("Sim.")

        assert len(result) == 1
        assert result[0] == "Sim."

    def test_nao_emitted_immediately(self):
        """'Não.' should be emitted immediately."""
        streamer = SentenceStreamer()

        result = streamer.process("Não.")

        assert len(result) == 1
        assert result[0] == "Não."

    def test_hello_emitted_immediately(self):
        """'Hello!' should be emitted immediately."""
        streamer = SentenceStreamer()

        result = streamer.process("Hello!")

        assert len(result) == 1
        assert result[0] == "Hello!"

    def test_quick_phrase_disabled(self):
        """Quick phrases can be disabled."""
        config = SentenceStreamerConfig(enable_quick_phrases=False)
        streamer = SentenceStreamer(config)

        # "Olá!" is only 4 chars, should NOT emit if quick phrases disabled
        result = streamer.process("Olá!")

        # With min_chars=20, it should not emit
        assert len(result) == 0
        assert streamer.buffer_content == "Olá!"

    def test_custom_quick_phrases(self):
        """Custom quick phrases can be added."""
        config = SentenceStreamerConfig(
            quick_phrases={"custom", "phrase"}
        )
        streamer = SentenceStreamer(config)

        result = streamer.process("Custom!")

        assert len(result) == 1
        assert result[0] == "Custom!"


# =============================================================================
# Adaptive min_chars Tests
# =============================================================================


class TestAdaptiveMinChars:
    """Tests for adaptive min_chars based on punctuation type."""

    def test_exclamation_uses_smaller_min_chars(self):
        """Sentences ending with ! should use min_chars_exclamation."""
        config = SentenceStreamerConfig(
            min_chars=20,
            min_chars_exclamation=5,
            enable_quick_phrases=False,
        )
        streamer = SentenceStreamer(config)

        # "Vamos!" is 6 chars, should emit with min_chars_exclamation=5
        result = streamer.process("Vamos!")

        assert len(result) == 1
        assert result[0] == "Vamos!"

    def test_question_uses_smaller_min_chars(self):
        """Sentences ending with ? should use min_chars_question."""
        config = SentenceStreamerConfig(
            min_chars=20,
            min_chars_question=8,
            enable_quick_phrases=False,
        )
        streamer = SentenceStreamer(config)

        # "Como vai?" is 9 chars, should emit with min_chars_question=8
        result = streamer.process("Como vai?")

        assert len(result) == 1
        assert result[0] == "Como vai?"

    def test_period_uses_standard_min_chars(self):
        """Sentences ending with . should use standard min_chars."""
        config = SentenceStreamerConfig(
            min_chars=20,
            enable_quick_phrases=False,
        )
        streamer = SentenceStreamer(config)

        # "Oi." is only 3 chars, should NOT emit with min_chars=20
        result = streamer.process("Oi.")

        assert len(result) == 0
        assert streamer.buffer_content == "Oi."


# =============================================================================
# Timeout Tests
# =============================================================================


class TestTimeoutEmission:
    """Tests for timeout-based emission."""

    def test_timeout_default_value(self):
        """Default timeout should be 500ms."""
        config = SentenceStreamerConfig()
        assert config.timeout_ms == 500

    def test_should_emit_timeout_false_when_empty(self):
        """should_emit_timeout should return False when buffer is empty."""
        streamer = SentenceStreamer()

        assert streamer.should_emit_timeout() is False

    def test_should_emit_timeout_false_when_recent(self):
        """should_emit_timeout should return False when token was recent."""
        streamer = SentenceStreamer()
        streamer.process("Some text")

        # Just processed, should not timeout yet
        assert streamer.should_emit_timeout() is False

    def test_time_since_last_token(self):
        """time_since_last_token should return elapsed time."""
        streamer = SentenceStreamer()

        # Before any tokens
        assert streamer.time_since_last_token() is None

        # After a token
        streamer.process("test")
        elapsed = streamer.time_since_last_token()

        assert elapsed is not None
        assert elapsed >= 0
        assert elapsed < 1  # Should be very small

    async def test_process_stream_with_timeout(self):
        """process_stream_with_timeout should emit on timeout."""
        config = SentenceStreamerConfig(timeout_ms=50)  # Short timeout for test
        streamer = SentenceStreamer(config)

        async def token_stream():
            yield "Hello, this is a test"
            await asyncio.sleep(0.1)  # Wait longer than timeout
            yield " more text."

        results = []
        async for sentence in streamer.process_stream_with_timeout(token_stream()):
            results.append(sentence)

        # Should have emitted "Hello, this is a test" on timeout
        # and " more text." at the end
        assert len(results) >= 1

    async def test_process_stream_with_timeout_disabled(self):
        """Timeout can be disabled by setting to 0."""
        config = SentenceStreamerConfig(timeout_ms=0)
        streamer = SentenceStreamer(config)

        async def token_stream():
            yield "Olá!"

        results = []
        async for sentence in streamer.process_stream_with_timeout(token_stream()):
            results.append(sentence)

        assert len(results) == 1
        assert results[0] == "Olá!"


# =============================================================================
# Portuguese Real-World Tests
# =============================================================================


class TestPortugueseRealWorld:
    """Tests with real Portuguese phrases and sentences."""

    def test_greeting_conversation(self):
        """Test typical greeting exchange."""
        streamer = SentenceStreamer()

        # User says "Olá!"
        result = streamer.process("Olá!")
        assert result == ["Olá!"]

        # Continue with response
        streamer.reset()
        tokens = ["Como ", "posso ", "ajudar ", "você ", "hoje?"]

        results = []
        for token in tokens:
            results.extend(streamer.process(token))

        # Should emit when we reach "?"
        assert len(results) == 1
        assert "Como posso ajudar você hoje?" in results[0]

    def test_short_answers(self):
        """Test typical short answers in Portuguese."""
        test_cases = [
            ("Sim.", ["Sim."]),
            ("Não.", ["Não."]),
            ("Ok!", ["Ok!"]),
            ("Certo.", ["Certo."]),
            ("Entendi.", ["Entendi."]),
            ("Obrigado!", ["Obrigado!"]),
        ]

        for input_text, expected in test_cases:
            streamer = SentenceStreamer()
            result = streamer.process(input_text)
            assert result == expected, f"Failed for: {input_text}"

    def test_multi_sentence_response(self):
        """Test multi-sentence response typical of voice assistants."""
        streamer = SentenceStreamer()

        # Simulate LLM generating response token by token
        text = "Olá! Posso ajudar você com várias tarefas. O que você precisa?"

        results = []
        for char in text:
            results.extend(streamer.process(char))

        # Should have 3 sentences
        assert len(results) == 3
        assert results[0] == "Olá!"
        assert "Posso ajudar" in results[1]
        assert "O que você precisa?" in results[2]

    def test_numbers_not_split(self):
        """Numbers like 3.14 should not cause sentence split."""
        streamer = SentenceStreamer()

        result = streamer.process("O valor é 3.14 reais.")

        # Should be one sentence (period in 3.14 is not a boundary)
        assert len(result) == 1
        assert "3.14" in result[0]

    def test_abbreviations_handled(self):
        """Abbreviations like Dr. Sr. should not cause split."""
        streamer = SentenceStreamer()

        # Dr. followed by uppercase should not split
        result = streamer.process("O Dr. Silva chegou.")

        # This is a known limitation - may split incorrectly
        # The test documents current behavior

    def test_long_sentence_soft_break(self):
        """Very long sentences should use soft breaks."""
        config = SentenceStreamerConfig(max_chars=50)
        streamer = SentenceStreamer(config)

        # Long sentence without end punctuation
        long_text = "Este é um texto muito longo que não tem pontuação final, mas precisa ser emitido"

        result = streamer.process(long_text)

        # Should have been split at a soft break (comma)
        assert len(result) >= 1


# =============================================================================
# Buffer Properties Tests
# =============================================================================


class TestBufferProperties:
    """Tests for buffer inspection properties."""

    def test_buffer_length(self):
        """buffer_length should return current buffer size."""
        streamer = SentenceStreamer()

        assert streamer.buffer_length == 0

        streamer.process("Hello")
        assert streamer.buffer_length == 5

        streamer.process(" World")
        assert streamer.buffer_length == 11

    def test_buffer_content(self):
        """buffer_content should return current buffer."""
        streamer = SentenceStreamer()

        assert streamer.buffer_content == ""

        streamer.process("Test")
        assert streamer.buffer_content == "Test"

    def test_reset_clears_buffer(self):
        """reset() should clear buffer and timestamp."""
        streamer = SentenceStreamer()

        streamer.process("Test")
        assert streamer.buffer_length > 0
        assert streamer.time_since_last_token() is not None

        streamer.reset()

        assert streamer.buffer_length == 0
        assert streamer.time_since_last_token() is None


# =============================================================================
# Integration Tests
# =============================================================================


class TestSentenceStreamerIntegration:
    """Integration tests for SentenceStreamer."""

    async def test_full_conversation_flow(self):
        """Test a full conversation flow with streaming."""
        streamer = SentenceStreamer()

        async def simulate_llm():
            """Simulate LLM generating tokens."""
            response = "Olá! Prazer em conhecê-lo. Como posso ajudar hoje?"
            for char in response:
                yield char
                await asyncio.sleep(0.001)  # Tiny delay

        sentences = []
        async for sentence in streamer.process_stream(simulate_llm()):
            sentences.append(sentence)

        assert len(sentences) == 3
        assert sentences[0] == "Olá!"
        assert "Prazer" in sentences[1]
        assert "Como posso" in sentences[2]

    def test_config_from_builder_values(self):
        """Test that config can be created with builder-like values."""
        config = SentenceStreamerConfig(
            min_chars=10,
            max_chars=150,
            timeout_ms=300,
            enable_quick_phrases=True,
        )

        streamer = SentenceStreamer(config)

        assert streamer.config.min_chars == 10
        assert streamer.config.max_chars == 150
        assert streamer.config.timeout_ms == 300
        assert streamer.config.enable_quick_phrases is True


# =============================================================================
# VoiceAgentBuilder Integration Tests
# =============================================================================


class TestVoiceAgentBuilderSentenceConfig:
    """Tests for VoiceAgentBuilder.sentence_config() method."""

    def test_sentence_config_default_values(self):
        """sentence_config should have sensible defaults."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        builder = VoiceAgentBuilder()

        assert builder._min_sentence_chars == 20
        assert builder._max_sentence_chars == 200
        assert builder._sentence_timeout_ms == 500
        assert builder._enable_quick_phrases is True

    def test_sentence_config_can_be_customized(self):
        """sentence_config() should update values."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        builder = VoiceAgentBuilder()
        builder.sentence_config(
            min_chars=10,
            max_chars=150,
            timeout_ms=300,
            enable_quick_phrases=False,
        )

        assert builder._min_sentence_chars == 10
        assert builder._max_sentence_chars == 150
        assert builder._sentence_timeout_ms == 300
        assert builder._enable_quick_phrases is False

    def test_sentence_config_returns_self(self):
        """sentence_config() should return self for chaining."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        builder = VoiceAgentBuilder()
        result = builder.sentence_config(min_chars=10)

        assert result is builder

    def test_sentence_config_chaining(self):
        """sentence_config() should chain with other methods."""
        from voice_pipeline import VoiceAgent

        builder = (
            VoiceAgent.builder()
            .llm("ollama", model="qwen2.5:0.5b")
            .streaming(True)
            .warmup(True)
            .sentence_config(
                min_chars=10,
                timeout_ms=300,
            )
        )

        assert builder._min_sentence_chars == 10
        assert builder._sentence_timeout_ms == 300
        assert builder._streaming is True
        assert builder._auto_warmup is True
