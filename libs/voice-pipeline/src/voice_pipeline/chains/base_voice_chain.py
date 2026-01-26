"""Base class for all voice chains.

Provides shared behavior for VoiceChain, ConversationChain,
StreamingVoiceChain, and ParallelStreamingChain.
"""

from typing import AsyncIterator, Optional

from voice_pipeline.interfaces import (
    ASRInterface,
    AudioChunk,
    LLMInterface,
    TTSInterface,
    VADInterface,
)
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable


class BaseVoiceChain(VoiceRunnable[bytes, AudioChunk]):
    """Base class for all voice chains (ASR -> LLM -> TTS).

    Provides shared functionality:
    - Conversation history management with optional trimming
    - Config creation helpers for ASR, LLM, TTS
    - Default ainvoke() collecting from astream()
    - reset() to clear conversation history
    """

    name: str = "BaseVoiceChain"

    def __init__(
        self,
        asr: ASRInterface,
        llm: LLMInterface,
        tts: TTSInterface,
        vad: Optional[VADInterface] = None,
        system_prompt: Optional[str] = None,
        language: Optional[str] = None,
        tts_voice: Optional[str] = None,
        llm_temperature: float = 0.7,
        max_messages: int = 20,
    ):
        self.asr = asr
        self.llm = llm
        self.tts = tts
        self.vad = vad
        self.system_prompt = system_prompt
        self.language = language
        self.tts_voice = tts_voice
        self.llm_temperature = llm_temperature

        self._messages: list[dict[str, str]] = []
        self._max_messages: int = max_messages

    def _add_message(self, role: str, content: str) -> None:
        """Add a message to history, trimming if over the limit."""
        self._messages.append({"role": role, "content": content})
        if self._max_messages > 0:
            while len(self._messages) > self._max_messages:
                self._messages.pop(0)

    @property
    def messages(self) -> list[dict[str, str]]:
        """Copy of conversation history."""
        return self._messages.copy()

    def _create_asr_config(self, config: Optional[RunnableConfig] = None) -> RunnableConfig:
        """Create ASR config from chain settings."""
        asr_config = RunnableConfig(
            configurable={"language": self.language},
        )
        if config:
            asr_config = asr_config.merge(config)
        return asr_config

    def _create_llm_config(self, config: Optional[RunnableConfig] = None) -> RunnableConfig:
        """Create LLM config from chain settings."""
        llm_config = RunnableConfig(
            configurable={
                "system_prompt": self.system_prompt,
                "temperature": self.llm_temperature,
            },
        )
        if config:
            llm_config = llm_config.merge(config)
        return llm_config

    def _create_tts_config(self, config: Optional[RunnableConfig] = None) -> RunnableConfig:
        """Create TTS config from chain settings."""
        tts_config = RunnableConfig(
            configurable={"voice": self.tts_voice},
        )
        if config:
            tts_config = tts_config.merge(config)
        return tts_config

    async def ainvoke(
        self,
        input: bytes,
        config: Optional[RunnableConfig] = None,
    ) -> AudioChunk:
        """Collect all chunks from astream."""
        chunks: list[bytes] = []
        async for chunk in self.astream(input, config):
            chunks.append(chunk.data)
        return AudioChunk(
            data=b"".join(chunks),
            sample_rate=24000,
        )

    def reset(self) -> None:
        """Clear conversation history."""
        self._messages.clear()
