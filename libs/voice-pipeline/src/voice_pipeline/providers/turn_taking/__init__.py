"""Turn-taking strategy providers.

Available strategies:
- FixedSilenceTurnTaking: Fixed silence threshold (default, simplest)
- AdaptiveSilenceTurnTaking: Adaptive threshold based on context
- SemanticTurnTaking: ML-based end-of-turn detection

Usage:
    from voice_pipeline.providers.turn_taking import FixedSilenceTurnTaking

    controller = FixedSilenceTurnTaking(silence_threshold_ms=600)
"""

from .fixed import FixedSilenceTurnTaking
from .adaptive import AdaptiveSilenceTurnTaking
from .semantic import SemanticTurnTaking

__all__ = [
    "FixedSilenceTurnTaking",
    "AdaptiveSilenceTurnTaking",
    "SemanticTurnTaking",
]
