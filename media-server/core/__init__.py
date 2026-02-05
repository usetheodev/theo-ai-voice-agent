"""
Core components for Media Forking architecture.

This module provides the infrastructure for isolating the critical media path
from non-critical AI processing, ensuring voice calls never depend on AI availability.

Architecture:
    RTP Callback (critical path)
         |
         v
    MediaForkManager.fork_audio()  <-- NEVER BLOCKS
         |
         v
    RingBuffer (lock-free, drop oldest)
         |
         v
    ForkConsumer (async worker, best-effort)
         |
         v
    AI Agent (non-critical consumer)
"""

from .ring_buffer import RingBuffer, AudioFrame, BufferMetrics
from .fork_consumer import ForkConsumer, ConsumerState, ConsumerMetrics
from .media_fork_manager import MediaForkManager, SessionFork

__all__ = [
    # Ring Buffer
    "RingBuffer",
    "AudioFrame",
    "BufferMetrics",
    # Fork Consumer
    "ForkConsumer",
    "ConsumerState",
    "ConsumerMetrics",
    # Media Fork Manager
    "MediaForkManager",
    "SessionFork",
]
