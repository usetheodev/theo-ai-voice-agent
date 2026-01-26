"""
ConversationChain for multi-turn voice conversations.

Extends VoiceChain with conversation management, memory,
and advanced features like barge-in handling.
"""

import asyncio
from typing import AsyncIterator, Callable, Optional

from voice_pipeline.callbacks.context import (
    emit_asr_end,
    emit_asr_start,
    emit_custom_event,
    emit_llm_end,
    emit_llm_start,
    emit_llm_token,
    emit_tts_end,
    emit_tts_start,
)
from voice_pipeline.chains.base_voice_chain import BaseVoiceChain
from voice_pipeline.core.state_machine import ConversationState, ConversationStateMachine
from voice_pipeline.interfaces import (
    ASRInterface,
    AudioChunk,
    LLMChunk,
    LLMInterface,
    TTSInterface,
    VADInterface,
)
from voice_pipeline.memory.base import VoiceMemory
from voice_pipeline.runnable import RunnableConfig, VoiceRunnable, ensure_config


class ConversationChain(BaseVoiceChain):
    """
    Advanced voice chain with conversation management.

    Extends VoiceChain with:
    - Multi-turn conversation memory
    - Configurable memory backends
    - Barge-in support
    - State management
    - Event hooks

    Example:
        >>> chain = ConversationChain(
        ...     asr=whisper_asr,
        ...     llm=ollama_llm,
        ...     tts=piper_tts,
        ...     system_prompt="You are a helpful assistant.",
        ...     memory=ConversationBufferMemory(k=10),
        ...     enable_barge_in=True,
        ... )
        >>>
        >>> # Process multiple turns
        >>> for audio in user_audio_chunks:
        ...     async for response_audio in chain.astream(audio):
        ...         play(response_audio)
    """

    name: str = "ConversationChain"

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
        memory: Optional[VoiceMemory] = None,
        max_history: Optional[int] = None,
        enable_barge_in: bool = True,
        barge_in_threshold_ms: int = 200,
        on_turn_start: Optional[Callable[[], None]] = None,
        on_turn_end: Optional[Callable[[], None]] = None,
        on_state_change: Optional[Callable[[ConversationState], None]] = None,
    ):
        """
        Initialize the conversation chain.

        Args:
            asr: ASR provider.
            llm: LLM provider.
            tts: TTS provider.
            vad: Optional VAD provider.
            system_prompt: System prompt for the LLM.
            language: Language code for ASR.
            tts_voice: Voice identifier for TTS.
            llm_temperature: LLM sampling temperature.
            memory: Memory backend for conversation history.
            max_history: Maximum messages to keep (if no memory backend).
            enable_barge_in: Allow user interruption.
            barge_in_threshold_ms: Time before triggering barge-in.
            on_turn_start: Callback for turn start.
            on_turn_end: Callback for turn end.
            on_state_change: Callback for state changes.
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
            max_messages=max_history or 20,
        )
        self.memory = memory
        self.max_history = max_history
        self.enable_barge_in = enable_barge_in
        self.barge_in_threshold_ms = barge_in_threshold_ms

        # Callbacks
        self.on_turn_start = on_turn_start
        self.on_turn_end = on_turn_end
        self.on_state_change = on_state_change

        # State machine
        self._state_machine = ConversationStateMachine()
        if self.on_state_change:
            self._state_machine.on_state_change(
                lambda old, new: self.on_state_change(new)
            )
        self._turn_count = 0
        self._interrupted = False

        # Cancellation
        self._cancel_event: Optional[asyncio.Event] = None

    @property
    def state(self) -> ConversationState:
        """Current conversation state."""
        return self._state_machine.state

    @property
    def turn_count(self) -> int:
        """Number of completed turns."""
        return self._turn_count

    def reset(self) -> None:
        """Reset conversation state and history."""
        super().reset()
        self._turn_count = 0
        self._interrupted = False
        self._state_machine.reset()

        # Note: memory.clear() is async; schedule if event loop is running
        if self.memory:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.memory.clear())
            except RuntimeError:
                pass

    def interrupt(self) -> None:
        """
        Interrupt the current response (barge-in).

        Call this when you detect the user is trying to speak
        while the assistant is talking.
        """
        if self.enable_barge_in and self._state_machine.is_speaking:
            self._interrupted = True
            self._state_machine.force_transition(ConversationState.INTERRUPTED)

            if self._cancel_event:
                self._cancel_event.set()

    async def astream(
        self,
        input: bytes,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[AudioChunk]:
        """
        Process audio and stream response.

        Handles the full conversation turn:
        1. Transition to LISTENING
        2. ASR transcription
        3. Transition to PROCESSING
        4. LLM generation
        5. Transition to SPEAKING
        6. TTS synthesis
        7. Return to IDLE

        Args:
            input: Audio bytes.
            config: Optional configuration.

        Yields:
            AudioChunk objects.
        """
        config = ensure_config(config)

        # Setup cancellation for barge-in
        self._cancel_event = asyncio.Event()
        self._interrupted = False

        try:
            # Turn start
            self._turn_count += 1
            if self.on_turn_start:
                self.on_turn_start()
            await emit_custom_event("turn_start", {"turn": self._turn_count})

            # LISTENING -> PROCESSING
            self._state_machine.transition_to(ConversationState.LISTENING)

            # ASR
            await emit_asr_start(input)

            asr_config = RunnableConfig(
                configurable={"language": self.language},
            ).merge(config)

            transcription = await self.asr.ainvoke(input, asr_config)
            await emit_asr_end(transcription)

            if not transcription.text.strip():
                self._state_machine.force_transition(ConversationState.IDLE)
                return

            # Add user message
            self._add_message("user", transcription.text)

            # Load memory context if available
            messages = self._messages.copy()
            if self.memory:
                context = await self.memory.load_context(transcription.text)
                if context and context.messages:
                    messages = context.messages

            # PROCESSING
            self._state_machine.transition_to(ConversationState.PROCESSING)

            await emit_llm_start(messages)

            llm_config = RunnableConfig(
                configurable={
                    "system_prompt": self.system_prompt,
                    "temperature": self.llm_temperature,
                },
            ).merge(config)

            # Collect LLM response
            response_text = ""
            async for chunk in self.llm.astream(messages, llm_config):
                if self._interrupted:
                    break

                token = chunk.text if isinstance(chunk, LLMChunk) else str(chunk)
                response_text += token
                await emit_llm_token(token)

            await emit_llm_end(response_text)

            if self._interrupted:
                self._state_machine.force_transition(ConversationState.IDLE)
                await emit_custom_event("barge_in", {"partial_response": response_text})
                return

            # Add assistant message
            self._add_message("assistant", response_text)

            # Save to memory if available
            if self.memory:
                await self.memory.save_context(transcription.text, response_text)

            # SPEAKING
            if response_text.strip():
                self._state_machine.transition_to(ConversationState.SPEAKING)

                await emit_tts_start(response_text)

                tts_config = RunnableConfig(
                    configurable={"voice": self.tts_voice},
                ).merge(config)

                async for audio_chunk in self.tts.astream(response_text, tts_config):
                    if self._interrupted:
                        break
                    yield audio_chunk

                await emit_tts_end()

            # Turn complete
            if self.on_turn_end:
                self.on_turn_end()
            await emit_custom_event("turn_end", {"turn": self._turn_count})

        finally:
            self._state_machine.force_transition(ConversationState.IDLE)
            self._cancel_event = None

    async def process_continuous(
        self,
        audio_stream: AsyncIterator[bytes],
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[AudioChunk]:
        """
        Process a continuous stream of audio chunks.

        This method handles ongoing conversation with automatic
        turn detection using VAD.

        Args:
            audio_stream: Continuous stream of audio chunks.
            config: Optional configuration.

        Yields:
            AudioChunk objects for synthesized responses.
        """
        if self.vad is None:
            raise ValueError("VAD is required for continuous processing")

        # Buffer for collecting speech
        speech_buffer: list[bytes] = []
        in_speech = False

        async for audio_chunk in audio_stream:
            # Check for speech
            vad_result = await self.vad.process(audio_chunk, 16000)

            if vad_result.is_speech:
                if not in_speech:
                    in_speech = True
                    speech_buffer.clear()

                speech_buffer.append(audio_chunk)

                # If we're speaking, this might be barge-in
                if self._state_machine.is_speaking:
                    self.interrupt()

            else:
                if in_speech:
                    # Speech ended, process the collected audio
                    in_speech = False

                    if speech_buffer:
                        combined_audio = b"".join(speech_buffer)
                        async for response_chunk in self.astream(combined_audio, config):
                            yield response_chunk

                        speech_buffer.clear()
