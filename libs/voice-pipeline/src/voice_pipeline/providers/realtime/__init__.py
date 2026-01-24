"""Realtime (Speech-to-Speech) providers.

Available providers:
- OpenAIRealtimeProvider: OpenAI Realtime API (gpt-4o-realtime-preview)
"""

from voice_pipeline.providers.realtime.openai import (
    OpenAIRealtimeProvider,
    OpenAIRealtimeConfig,
)

__all__ = [
    "OpenAIRealtimeProvider",
    "OpenAIRealtimeConfig",
]
