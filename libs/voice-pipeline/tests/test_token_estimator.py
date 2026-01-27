"""Tests for token estimator."""

from unittest.mock import MagicMock, patch

import pytest

from voice_pipeline.memory.tokenizer import TokenEstimator


class TestTokenEstimator:
    """Tests for TokenEstimator class."""

    def test_empty_string(self):
        estimator = TokenEstimator()
        assert estimator.estimate("") == 0

    def test_heuristic_fallback(self):
        """Without tiktoken, should use len // 4."""
        with patch.dict("sys.modules", {"tiktoken": None}):
            estimator = TokenEstimator.__new__(TokenEstimator)
            estimator._custom_fn = None
            estimator._encoding = None
            estimator._encoding_name = "cl100k_base"

            # 20 chars // 4 = 5
            result = estimator.estimate("a" * 20)
            assert result == 5

    def test_custom_function(self):
        """Custom function should be used when provided."""
        custom_fn = lambda text: len(text.split())
        estimator = TokenEstimator(custom_fn=custom_fn)

        assert estimator.estimate("hello world foo") == 3
        assert estimator.is_accurate is True

    def test_custom_function_overrides_tiktoken(self):
        """Custom function should take precedence over tiktoken."""
        custom_fn = lambda text: 42
        estimator = TokenEstimator(custom_fn=custom_fn)

        assert estimator.estimate("any text") == 42

    def test_is_accurate_without_tiktoken(self):
        """Without tiktoken or custom fn, is_accurate should be False."""
        estimator = TokenEstimator.__new__(TokenEstimator)
        estimator._custom_fn = None
        estimator._encoding = None
        estimator._encoding_name = "cl100k_base"

        assert estimator.is_accurate is False

    def test_is_accurate_with_tiktoken(self):
        """With tiktoken available, is_accurate should be True."""
        try:
            import tiktoken
            estimator = TokenEstimator()
            assert estimator.is_accurate is True
        except ImportError:
            pytest.skip("tiktoken not installed")

    def test_with_mocked_tiktoken(self):
        """Test with mocked tiktoken encoding."""
        mock_encoding = MagicMock()
        mock_encoding.encode.return_value = [1, 2, 3, 4, 5]  # 5 tokens

        estimator = TokenEstimator.__new__(TokenEstimator)
        estimator._custom_fn = None
        estimator._encoding = mock_encoding
        estimator._encoding_name = "cl100k_base"

        result = estimator.estimate("hello world test")
        assert result == 5
        mock_encoding.encode.assert_called_once_with("hello world test")

    def test_heuristic_short_text(self):
        """Short text should still work with heuristic."""
        estimator = TokenEstimator.__new__(TokenEstimator)
        estimator._custom_fn = None
        estimator._encoding = None
        estimator._encoding_name = "cl100k_base"

        assert estimator.estimate("hi") == 0  # 2 // 4 = 0
        assert estimator.estimate("hello") == 1  # 5 // 4 = 1


class TestTokenEstimatorIntegration:
    """Tests for TokenEstimator integration with memory."""

    def test_with_summary_memory(self):
        """Test that TokenEstimator works with ConversationSummaryBufferMemory."""
        from voice_pipeline.memory.summary import ConversationSummaryBufferMemory

        custom_fn = lambda text: len(text.split())
        estimator = TokenEstimator(custom_fn=custom_fn)

        memory = ConversationSummaryBufferMemory(
            max_token_limit=100,
            token_estimator=estimator,
        )

        # _estimate_tokens should delegate to estimator
        assert memory._estimate_tokens("hello world foo bar") == 4

    def test_without_estimator_uses_heuristic(self):
        """Without estimator, memory should use len // 4."""
        from voice_pipeline.memory.summary import ConversationSummaryBufferMemory

        memory = ConversationSummaryBufferMemory(max_token_limit=100)

        # Default heuristic: 20 chars // 4 = 5
        assert memory._estimate_tokens("a" * 20) == 5
