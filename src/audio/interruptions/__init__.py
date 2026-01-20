"""
Interruption Strategies - Smart Barge-in Control

Intelligent strategies to prevent false barge-ins during agent speech.

Why This Matters:
    Without smart barge-in, ANY user sound interrupts the agent:
    - Cough → Agent stops mid-sentence (BAD)
    - "Um..." → Agent stops (BAD)
    - "Yes, continue" → Agent stops (GOOD)

Smart Barge-in ensures only INTENTIONAL interruptions work.
"""

from .base_interruption_strategy import BaseInterruptionStrategy
from .min_duration_interruption_strategy import MinDurationInterruptionStrategy

__all__ = [
    'BaseInterruptionStrategy',
    'MinDurationInterruptionStrategy',
]
