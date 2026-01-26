"""
Voice Chains for composing voice pipelines.

This module provides high-level abstractions for building
complete voice AI pipelines with different capabilities.

Quick Start:
    >>> from voice_pipeline.chains import VoiceChain
    >>> chain = VoiceChain(asr=my_asr, llm=my_llm, tts=my_tts)
    >>> async for audio in chain.astream(audio_bytes):
    ...     play(audio)

Using the Builder (deprecated, use VoiceAgent.builder() instead):
    >>> from voice_pipeline.chains import voice_chain
    >>> chain = (
    ...     voice_chain()
    ...     .with_asr("whisper")
    ...     .with_llm("ollama", model="llama3")
    ...     .with_tts("piper")
    ...     .with_system_prompt("You are helpful.")
    ...     .build()
    ... )

Available Chains:
- VoiceChain: Basic audio-to-audio chain
- SimpleVoiceChain: Text-to-audio chain
- ConversationChain: Multi-turn conversation with memory
- StreamingVoiceChain: Optimized for minimal latency
- ParallelStreamingChain: Parallel LLM/TTS processing
"""

from voice_pipeline.chains.base import SimpleVoiceChain, VoiceChain
from voice_pipeline.chains.builder import VoiceChainBuilder, voice_chain
from voice_pipeline.chains.conversation import ConversationChain, ConversationState
from voice_pipeline.chains.streaming import (
    ParallelStreamingChain,
    StreamingVoiceChain,
)

# Add builder method to VoiceChain
VoiceChain.builder = staticmethod(lambda: VoiceChainBuilder())

__all__ = [
    # Base chains
    "VoiceChain",
    "SimpleVoiceChain",
    # Builder
    "VoiceChainBuilder",
    "voice_chain",
    # Conversation
    "ConversationChain",
    "ConversationState",
    # Streaming
    "StreamingVoiceChain",
    "ParallelStreamingChain",
]
