"""
Turn Detection - End-of-Turn Analysis

Intelligent detection of when user finished speaking vs mid-sentence pause.
"""

from .base_turn_analyzer import EndOfTurnState, BaseTurnParams, BaseTurnAnalyzer
from .simple_turn_analyzer import SimpleTurnAnalyzer

__all__ = [
    'EndOfTurnState',
    'BaseTurnParams',
    'BaseTurnAnalyzer',
    'SimpleTurnAnalyzer',
]
