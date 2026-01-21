"""
Base Interruption Strategy - Smart Barge-in Foundation

Abstract base class for determining when users can interrupt bot/agent speech.

Problem:
    Traditional barge-in: ANY user sound interrupts agent
        - Cough → Agent stops (FALSE POSITIVE ❌)
        - "Um..." → Agent stops (FALSE POSITIVE ❌)
        - Background noise → Agent stops (FALSE POSITIVE ❌)

Solution:
    Smart barge-in: Only INTENTIONAL interruptions allowed
        - Cough (0.1s) → Agent continues (✅)
        - "Um..." (0.3s) → Agent continues (✅)
        - "Actually, no" (1.2s) → Agent stops (✅ REAL INTERRUPT)

Strategies:
    1. MinDurationInterruptionStrategy (this phase):
       - Interrupt only if user speaks ≥ N seconds
       - Simple, no ASR needed
       - Example: min_duration=0.8s

    2. MinWordsInterruptionStrategy (future):
       - Interrupt only if user says ≥ N words
       - Requires real-time ASR
       - Example: min_words=2 ("actually no", "wait stop")

    3. IntentBasedInterruptionStrategy (future):
       - Interrupt only if user intent is "interruption"
       - Requires LLM classification
       - Example: "stop", "wait", "no" → Interrupt

Pattern based on:
- Pipecat AI (pipecat/audio/interruptions/base_interruption_strategy.py)
- Asterisk-AI-Voice-Agent (Phase 2.1 planning)
"""

from abc import ABC, abstractmethod


class BaseInterruptionStrategy(ABC):
    """
    Base class for interruption strategies.

    Responsibilities:
        1. Accumulate user input (audio/text) during agent speech
        2. Decide if user input is "real interruption" vs "noise"
        3. Return True/False for should_interrupt()

    Workflow:
        ```
        Agent speaks: "Let me explain our pricing..."
        User: [cough]  (0.2s)
                ↓
        append_audio(cough_audio)
                ↓
        should_interrupt() → False (too short)
                ↓
        Agent continues: "...we have three tiers..."
        User: "Actually, stop!"  (1.2s)
                ↓
        append_audio(speech_audio)
                ↓
        should_interrupt() → True (long enough)
                ↓
        Agent stops: [interruption triggered]
        ```

    Thread Safety:
        Each CallSession has its own strategy instance.
        No locking needed (single-threaded asyncio event loop).

    Usage:
        ```python
        # Initialize strategy
        strategy = MinDurationInterruptionStrategy(min_duration=0.8)

        # During agent speech, accumulate user audio
        if agent_is_speaking and user_audio_detected:
            await strategy.append_audio(pcm_data, sample_rate=8000)

        # When user stops speaking, check if real interruption
        if vad_silence_detected:
            if await strategy.should_interrupt():
                # Real interruption - stop agent
                await stop_agent_playback()
                await process_user_input()
            else:
                # False alarm (cough, "um", etc.) - continue agent
                pass

            await strategy.reset()  # Clear for next check
        ```
    """

    async def append_audio(self, audio: bytes, sample_rate: int):
        """
        Append audio data to the strategy for analysis.

        Called for each audio frame during agent speech when user is also speaking.

        Args:
            audio: Raw PCM audio data (int16 samples)
                - Format: Raw PCM S16LE (signed 16-bit little-endian)
                - Example: 20ms @ 8kHz = 160 samples = 320 bytes

            sample_rate: Sample rate of the audio data in Hz
                - Example: 8000 (G.711 ulaw telephony)
                - Example: 16000 (Whisper ASR)

        Note:
            Not all strategies handle audio (MinWordsInterruptionStrategy uses text).
            Default implementation does nothing - subclasses override if needed.

        Example:
            # In RTP processing during agent speech
            if agent_is_speaking and vad_detected_speech:
                await strategy.append_audio(pcm_data, sample_rate=8000)
        """
        pass

    async def append_text(self, text: str):
        """
        Append text data to the strategy for analysis.

        Called when real-time ASR transcribes user speech during agent playback.

        Args:
            text: Transcribed text from user (partial or complete)
                - Example: "stop" (complete)
                - Example: "act..." (partial transcription)

        Note:
            Not all strategies handle text (MinDurationInterruptionStrategy uses audio).
            Default implementation does nothing - subclasses override if needed.

        Use Cases:
            - MinWordsInterruptionStrategy: Count words
            - IntentBasedInterruptionStrategy: Classify intent
            - KeywordInterruptionStrategy: Match keywords ("stop", "wait")

        Example:
            # When ASR provides interim transcription
            if agent_is_speaking:
                await strategy.append_text(transcription.text)
        """
        pass

    @abstractmethod
    async def should_interrupt(self) -> bool:
        """
        Determine if the user should interrupt the bot/agent.

        Called when user stops speaking (VAD silence detected) to decide
        whether this was a REAL interruption vs FALSE ALARM.

        Returns:
            True: Real interruption (user wants to speak)
                - Action: Stop agent playback, process user input
                - Example: User said "actually, no" (1.2s)

            False: False alarm (noise, cough, "um", etc.)
                - Action: Continue agent playback, ignore user input
                - Example: User coughed (0.2s)

        Decision Factors:
            - Audio duration (MinDurationInterruptionStrategy)
            - Word count (MinWordsInterruptionStrategy)
            - Intent classification (IntentBasedInterruptionStrategy)
            - Keyword matching (KeywordInterruptionStrategy)

        Example:
            ```python
            # When user stops speaking during agent speech
            if await strategy.should_interrupt():
                logger.info("Real interruption detected - stopping agent")
                await stop_agent_playback()
                await process_user_input()
            else:
                logger.info("False alarm (cough/um) - continuing agent")
            ```

        Pattern:
            Async to support future ML-based strategies (requires inference).
        """
        pass

    @abstractmethod
    async def reset(self):
        """
        Reset the current accumulated audio/text.

        Called after processing an interruption check (whether True or False)
        to clear state for the next potential interruption.

        Responsibilities:
            - Clear accumulated audio buffer
            - Clear accumulated text buffer
            - Reset counters (duration, word count, etc.)
            - Prepare for next interruption check

        Example:
            ```python
            # After checking interruption
            interrupt = await strategy.should_interrupt()
            if interrupt:
                await handle_interruption()
            await strategy.reset()  # Always reset after check
            ```

        Pattern:
            Async for consistency with other methods (though usually synchronous).
        """
        pass


# Export base class
__all__ = [
    'BaseInterruptionStrategy',
]
