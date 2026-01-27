"""Token estimation for conversation memory.

Provides accurate token counting when tiktoken is available,
with a heuristic fallback (len(text) // 4) otherwise.
"""

from typing import Callable, Optional


class TokenEstimator:
    """Estimates token count for text strings.

    Uses tiktoken when available for accurate counting,
    falls back to a heuristic (len // 4) otherwise.
    Supports custom token counting functions.

    Args:
        encoding_name: tiktoken encoding name (default: "cl100k_base").
        custom_fn: Optional custom function that takes text and returns int.

    Example:
        >>> estimator = TokenEstimator()
        >>> estimator.estimate("Hello, world!")
        4  # with tiktoken
        3  # without tiktoken (13 // 4)
    """

    def __init__(
        self,
        encoding_name: str = "cl100k_base",
        custom_fn: Optional[Callable[[str], int]] = None,
    ):
        self._custom_fn = custom_fn
        self._encoding = None
        self._encoding_name = encoding_name

        if custom_fn is None:
            try:
                import tiktoken
                self._encoding = tiktoken.get_encoding(encoding_name)
            except (ImportError, Exception):
                pass

    @property
    def is_accurate(self) -> bool:
        """Whether this estimator uses a real tokenizer (not heuristic)."""
        return self._encoding is not None or self._custom_fn is not None

    def estimate(self, text: str) -> int:
        """Estimate token count for the given text.

        Args:
            text: Text to estimate tokens for.

        Returns:
            Estimated token count.
        """
        if not text:
            return 0

        if self._custom_fn is not None:
            return self._custom_fn(text)

        if self._encoding is not None:
            return len(self._encoding.encode(text))

        # Heuristic fallback: ~4 chars per token
        return len(text) // 4
