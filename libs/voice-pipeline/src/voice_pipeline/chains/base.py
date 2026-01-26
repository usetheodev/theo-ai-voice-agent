"""
Base VoiceChain class for composing voice pipelines.

VoiceChain provides a high-level abstraction for building
complete voice AI pipelines from ASR, LLM, and TTS components.
"""

from typing import Any, AsyncIterator, Optional

from voice_pipeline.callbacks import run_with_callbacks
from voice_pipeline.callbacks.base import VoiceCallbackHandler
from voice_pipeline.callbacks.context import (
    emit_asr_end,
    emit_asr_start,
    emit_llm_end,
    emit_llm_start,
    emit_llm_token,
    emit_tts_end,
    emit_tts_start,
    get_callback_manager,
    get_run_context,
)
from voice_pipeline.interfaces import (
    ASRInterface,
    AudioChunk,
    LLMChunk,
    LLMInterface,
    TranscriptionResult,
    TTSInterface,
    VADInterface,
)
from voice_pipeline.chains.base_voice_chain import BaseVoiceChain
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable, ensure_config


class VoiceChain(BaseVoiceChain):
    """
    A complete voice-to-voice chain: Audio → ASR → LLM → TTS → Audio.

    VoiceChain orchestrates the flow between components with support for:
    - Full streaming end-to-end
    - Callbacks for observability
    - Configurable system prompts and conversation history
    - Barge-in handling

    Example:
        >>> chain = VoiceChain(
        ...     asr=whisper_asr,
        ...     llm=ollama_llm,
        ...     tts=piper_tts,
        ...     system_prompt="You are a helpful assistant.",
        ... )
        >>>
        >>> # Non-streaming
        >>> result = await chain.ainvoke(audio_bytes)
        >>>
        >>> # Streaming
        >>> async for audio in chain.astream(audio_bytes):
        ...     play(audio)
    """

    name: str = "VoiceChain"

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
        llm_max_tokens: Optional[int] = None,
    ):
        """
        Initialize the voice chain.

        Args:
            asr: ASR provider for speech-to-text.
            llm: LLM provider for response generation.
            tts: TTS provider for text-to-speech.
            vad: Optional VAD provider for voice activity detection.
            system_prompt: System prompt for the LLM.
            language: Language code for ASR (e.g., "pt-BR").
            tts_voice: Voice identifier for TTS.
            llm_temperature: LLM sampling temperature.
            llm_max_tokens: Maximum tokens for LLM response.
        """
        super().__init__(
            asr=asr,
            llm=llm,
            tts=tts,
            vad=vad,
            system_prompt=system_prompt,
            language=language,
            tts_voice=tts_voice,
            llm_temperature=llm_temperature,
        )
        self.llm_max_tokens = llm_max_tokens

    def add_message(self, role: str, content: str) -> None:
        """Add a message to conversation history (public API)."""
        self._add_message(role, content)

    async def astream(
        self,
        input: bytes,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[AudioChunk]:
        """
        Process audio input and stream synthesized response.

        This method provides end-to-end streaming:
        1. Transcribe audio with ASR
        2. Stream LLM response tokens
        3. Stream TTS audio as sentences complete

        Args:
            input: Audio bytes (PCM16).
            config: Optional configuration.

        Yields:
            AudioChunk objects with synthesized audio.
        """
        config = ensure_config(config)

        # Step 1: ASR
        await emit_asr_start(input)

        asr_config = RunnableConfig(
            configurable={"language": self.language},
        ).merge(config)

        transcription = await self.asr.ainvoke(input, asr_config)

        await emit_asr_end(transcription)

        if not transcription.text.strip():
            return

        # Add user message to history
        self.add_message("user", transcription.text)

        # Step 2: LLM
        await emit_llm_start(self._messages)

        llm_config = RunnableConfig(
            configurable={
                "system_prompt": self.system_prompt,
                "temperature": self.llm_temperature,
                "max_tokens": self.llm_max_tokens,
            },
        ).merge(config)

        # Collect response and stream to TTS
        response_text = ""

        async for chunk in self.llm.astream(self._messages, llm_config):
            if isinstance(chunk, LLMChunk):
                token = chunk.text
            else:
                token = str(chunk)

            response_text += token
            await emit_llm_token(token)

        await emit_llm_end(response_text)

        # Add assistant message to history
        self.add_message("assistant", response_text)

        # Step 3: TTS
        if response_text.strip():
            await emit_tts_start(response_text)

            tts_config = RunnableConfig(
                configurable={
                    "voice": self.tts_voice,
                },
            ).merge(config)

            async for audio_chunk in self.tts.astream(response_text, tts_config):
                yield audio_chunk

            await emit_tts_end()

    async def process_with_callbacks(
        self,
        input: bytes,
        callbacks: list[VoiceCallbackHandler],
        run_name: Optional[str] = None,
    ) -> AudioChunk:
        """
        Process audio with callback handlers.

        Convenience method that wraps ainvoke with callbacks.

        Args:
            input: Audio bytes.
            callbacks: List of callback handlers.
            run_name: Optional name for this run.

        Returns:
            AudioChunk with synthesized response.
        """
        async with run_with_callbacks(callbacks, run_name=run_name):
            return await self.ainvoke(input)

    async def stream_with_callbacks(
        self,
        input: bytes,
        callbacks: list[VoiceCallbackHandler],
        run_name: Optional[str] = None,
    ) -> AsyncIterator[AudioChunk]:
        """
        Stream audio with callback handlers.

        Convenience method that wraps astream with callbacks.

        Args:
            input: Audio bytes.
            callbacks: List of callback handlers.
            run_name: Optional name for this run.

        Yields:
            AudioChunk objects with synthesized audio.
        """
        async with run_with_callbacks(callbacks, run_name=run_name):
            async for chunk in self.astream(input):
                yield chunk

    def __repr__(self) -> str:
        return (
            f"VoiceChain("
            f"asr={self.asr.__class__.__name__}, "
            f"llm={self.llm.__class__.__name__}, "
            f"tts={self.tts.__class__.__name__}"
            f")"
        )


class SimpleVoiceChain(VoiceRunnable[str, AudioChunk]):
    """
    Simplified chain: Text → LLM → TTS → Audio.

    Useful when you already have text input (from external ASR
    or direct text input).

    Example:
        >>> chain = SimpleVoiceChain(llm=ollama_llm, tts=piper_tts)
        >>> audio = await chain.ainvoke("Hello, how are you?")
    """

    name: str = "SimpleVoiceChain"

    def __init__(
        self,
        llm: LLMInterface,
        tts: TTSInterface,
        system_prompt: Optional[str] = None,
        tts_voice: Optional[str] = None,
        llm_temperature: float = 0.7,
    ):
        """
        Initialize the simple chain.

        Args:
            llm: LLM provider.
            tts: TTS provider.
            system_prompt: System prompt for the LLM.
            tts_voice: Voice identifier for TTS.
            llm_temperature: LLM sampling temperature.
        """
        self.llm = llm
        self.tts = tts
        self.system_prompt = system_prompt
        self.tts_voice = tts_voice
        self.llm_temperature = llm_temperature
        self._messages: list[dict[str, str]] = []

    def reset(self) -> None:
        """Reset conversation history."""
        self._messages.clear()

    async def ainvoke(
        self,
        input: str,
        config: Optional[RunnableConfig] = None,
    ) -> AudioChunk:
        """Process text and return audio."""
        chunks: list[bytes] = []
        async for chunk in self.astream(input, config):
            chunks.append(chunk.data)

        return AudioChunk(
            data=b"".join(chunks),
            sample_rate=24000,
        )

    async def astream(
        self,
        input: str,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[AudioChunk]:
        """Process text and stream audio."""
        config = ensure_config(config)

        # Add user message
        self._messages.append({"role": "user", "content": input})

        # LLM
        await emit_llm_start(self._messages)

        llm_config = RunnableConfig(
            configurable={
                "system_prompt": self.system_prompt,
                "temperature": self.llm_temperature,
            },
        ).merge(config)

        response_text = ""
        async for chunk in self.llm.astream(self._messages, llm_config):
            token = chunk.text if isinstance(chunk, LLMChunk) else str(chunk)
            response_text += token
            await emit_llm_token(token)

        await emit_llm_end(response_text)
        self._messages.append({"role": "assistant", "content": response_text})

        # TTS
        if response_text.strip():
            await emit_tts_start(response_text)

            tts_config = RunnableConfig(
                configurable={"voice": self.tts_voice},
            ).merge(config)

            async for audio_chunk in self.tts.astream(response_text, tts_config):
                yield audio_chunk

            await emit_tts_end()
