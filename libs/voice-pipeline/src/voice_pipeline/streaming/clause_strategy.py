"""Clause-level streaming strategy.

Emits text at clause boundaries (commas, semicolons, conjunctions)
for a good balance between latency and natural prosody.

TTFA: ~200-400ms (vs ~600-800ms for sentence-level)
Naturalness: Good (clauses are natural speech units)

Clause boundaries detected:
- Punctuation: , ; : — –
- Conjunctions: "e", "mas", "ou", "porém", "contudo" (PT)
                "and", "but", "or", "however", "although" (EN)
"""

import re
from typing import Optional

from voice_pipeline.streaming.strategy import StreamingGranularity, StreamingStrategy


# Clause-breaking conjunctions by language
_CONJUNCTIONS_PT = {
    " e ", " mas ", " ou ", " porém ", " contudo ", " entretanto ",
    " portanto ", " então ", " porque ", " pois ", " enquanto ",
}
_CONJUNCTIONS_EN = {
    " and ", " but ", " or ", " however ", " although ", " because ",
    " since ", " while ", " therefore ", " so ", " yet ",
}

# Punctuation that indicates clause boundaries
_CLAUSE_PUNCTUATION = {",", ";", ":", "—", "–"}

# Sentence-ending punctuation (always emit on these)
_SENTENCE_END = {".", "!", "?", "\n"}


class ClauseStreamingStrategy(StreamingStrategy):
    """Clause-level streaming for balanced latency and naturalness.

    Emits text at clause boundaries, which are natural pause points
    in speech. This provides lower latency than sentence-level
    while maintaining reasonable prosody.

    The strategy detects boundaries from:
    1. Clause punctuation (commas, semicolons, colons)
    2. Conjunctions ("e", "mas", "ou" / "and", "but", "or")
    3. Sentence-ending punctuation (always triggers emission)

    Args:
        min_chars: Minimum characters before emitting a clause.
            Prevents very short chunks like "e, ". Default: 8.
        max_chars: Maximum characters before forcing emission.
            Default: 150.
        language: Language for conjunction detection ("pt" or "en").
            Default: "pt".

    Example:
        >>> strategy = ClauseStreamingStrategy(min_chars=8)
        >>> strategy.process("Eu gosto de café,")
        []
        >>> strategy.process(" mas prefiro")
        ["Eu gosto de café,"]
        >>> strategy.process(" chá.")
        ["mas prefiro chá."]
    """

    def __init__(
        self,
        min_chars: int = 8,
        max_chars: int = 150,
        language: str = "pt",
    ):
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.language = language
        self._buffer = ""

        # Build conjunction set based on language
        if language.startswith("pt"):
            self._conjunctions = _CONJUNCTIONS_PT
        else:
            self._conjunctions = _CONJUNCTIONS_EN

    def process(self, token: str) -> list[str]:
        """Process token and emit at clause boundaries."""
        self._buffer += token
        return self._extract_clauses()

    def _extract_clauses(self) -> list[str]:
        """Extract ready clauses from buffer.

        Uses min_chars as minimum position for boundary search,
        so short initial segments (like "Olá!") don't block
        detection of subsequent boundaries.
        """
        chunks: list[str] = []

        while True:
            # Search for boundaries starting at min_chars position
            # This ensures the resulting chunk is >= min_chars
            pos = self._find_boundary(min_pos=max(0, self.min_chars - 1))

            if pos is not None:
                # Found a valid boundary
                chunk = self._buffer[: pos + 1].strip()
                remainder = self._buffer[pos + 1:]

                if chunk:
                    chunks.append(chunk)
                    self._buffer = remainder
                    continue
                else:
                    break

            # No boundary found — check max_chars
            if len(self._buffer) >= self.max_chars:
                # Force split at last space
                split_pos = self._buffer.rfind(" ", 0, self.max_chars)
                if split_pos > self.min_chars:
                    chunk = self._buffer[:split_pos].strip()
                    if chunk:
                        chunks.append(chunk)
                    self._buffer = self._buffer[split_pos:]
                else:
                    # No good split, emit all
                    chunk = self._buffer.strip()
                    if chunk:
                        chunks.append(chunk)
                    self._buffer = ""

            break

        return chunks

    def _find_boundary(self, min_pos: int = 0) -> Optional[int]:
        """Find the first clause boundary in the buffer.

        Args:
            min_pos: Minimum position to search from. Boundaries
                before this position are ignored. This prevents
                short initial segments from blocking subsequent
                boundary detection.

        Returns position of the boundary character, or None.
        """
        best_pos: Optional[int] = None

        # Check sentence-ending punctuation (highest priority)
        for i, char in enumerate(self._buffer):
            if i < min_pos:
                continue
            if char in _SENTENCE_END:
                return i

        # Check clause punctuation
        for i, char in enumerate(self._buffer):
            if i < min_pos:
                continue
            if char in _CLAUSE_PUNCTUATION:
                # Verify it's not inside a number (e.g., "1,000")
                if char == "," and i > 0 and i < len(self._buffer) - 1:
                    if self._buffer[i - 1].isdigit() and self._buffer[i + 1].isdigit():
                        continue
                if best_pos is None:
                    best_pos = i

        if best_pos is not None:
            return best_pos

        # Check conjunctions (emit before the conjunction)
        buf_lower = self._buffer.lower()
        for conj in self._conjunctions:
            idx = buf_lower.find(conj, min_pos)
            if idx >= min_pos and idx >= self.min_chars:
                # Emit everything before the conjunction
                # Return position just before the conjunction
                if best_pos is None or idx - 1 < best_pos:
                    best_pos = idx - 1

        return best_pos

    def flush(self) -> Optional[str]:
        """Flush remaining buffer."""
        if self._buffer.strip():
            result = self._buffer.strip()
            self._buffer = ""
            return result
        self._buffer = ""
        return None

    def reset(self) -> None:
        """Reset buffer."""
        self._buffer = ""

    @property
    def granularity(self) -> StreamingGranularity:
        return StreamingGranularity.CLAUSE
