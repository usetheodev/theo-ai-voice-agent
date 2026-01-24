"""Voice Memory System.

Memory provides conversation context for multi-turn voice interactions.

Quick Start:
    >>> from voice_pipeline.memory import ConversationBufferMemory
    >>>
    >>> # Create a simple buffer memory
    >>> memory = ConversationBufferMemory(max_messages=20)
    >>>
    >>> # Save conversation turns
    >>> await memory.save_context("Hello!", "Hi there!")
    >>> await memory.save_context("How are you?", "I'm great!")
    >>>
    >>> # Load context for next turn
    >>> context = await memory.load_context()
    >>> # context.messages contains conversation history

Using with VoiceChain:
    >>> from voice_pipeline import VoiceChain
    >>> from voice_pipeline.memory import ConversationBufferMemory
    >>>
    >>> chain = VoiceChain(
    ...     asr=my_asr,
    ...     llm=my_llm,
    ...     tts=my_tts,
    ...     memory=ConversationBufferMemory(max_messages=10),
    ... )

Available Memory Types:
- ConversationBufferMemory: Keeps last N messages
- ConversationWindowMemory: Keeps last K turns
- ConversationSummaryMemory: Summarizes older messages
- ConversationSummaryBufferMemory: Hybrid buffer + summary
"""

from voice_pipeline.memory.base import BaseMemoryStore, MemoryContext, VoiceMemory
from voice_pipeline.memory.buffer import (
    ConversationBufferMemory,
    ConversationWindowMemory,
)
from voice_pipeline.memory.stores import InMemoryStore
from voice_pipeline.memory.summary import (
    ConversationSummaryBufferMemory,
    ConversationSummaryMemory,
)

__all__ = [
    # Base
    "VoiceMemory",
    "MemoryContext",
    "BaseMemoryStore",
    # Buffer memories
    "ConversationBufferMemory",
    "ConversationWindowMemory",
    # Summary memories
    "ConversationSummaryMemory",
    "ConversationSummaryBufferMemory",
    # Stores
    "InMemoryStore",
]
