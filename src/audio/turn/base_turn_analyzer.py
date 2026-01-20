"""
Base Turn Analyzer - End-of-Turn Detection

Abstract base class for analyzing when a user has finished speaking (end-of-turn)
vs when they're just pausing mid-sentence.

This is critical for natural conversation flow:
- Prevents premature interruptions (agent cuts off user mid-sentence)
- Reduces false barge-ins (agent speaks during natural pauses)
- Improves user experience (conversations feel more natural)

Pattern based on:
- Pipecat AI (pipecat/audio/turn/base_turn_analyzer.py)
- Asterisk-AI-Voice-Agent (Phase 2.1 planning)

Architecture:
    BaseTurnAnalyzer (abstract)
        ├── SimpleTurnAnalyzer (rule-based, this phase)
        └── Future: ML-based turn detection (Phase 2.x)
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Tuple


class EndOfTurnState(Enum):
    """
    State enumeration for end-of-turn analysis results.

    States:
        COMPLETE: User has finished their turn (ready to process)
            - Example: "Hello, how are you?" [1s pause] → COMPLETE
            - Action: Send audio to ASR/LLM, prepare agent response

        INCOMPLETE: User is still speaking or may continue
            - Example: "Hello, [0.3s pause]..." → INCOMPLETE
            - Action: Keep accumulating audio, don't interrupt yet

    Why This Matters:
        - COMPLETE too early → Agent cuts off user mid-sentence (BAD UX)
        - COMPLETE too late → User waits unnecessarily (BAD UX)
        - Goal: Detect natural turn boundaries (punctuation + pause)
    """
    COMPLETE = 1      # User finished speaking (end-of-turn detected)
    INCOMPLETE = 2    # User still speaking or may continue


class BaseTurnParams:
    """
    Base class for turn analyzer parameters.

    Subclasses should define specific parameters:
    - SimpleTurnAnalyzer: pause_duration, min_duration
    - Future ML-based: model_path, confidence_threshold, etc.

    Design: Plain class instead of Pydantic to avoid extra dependency
    (Pipecat uses Pydantic, but we keep it minimal)
    """
    pass


class BaseTurnAnalyzer(ABC):
    """
    Abstract base class for analyzing user end-of-turn.

    Responsibilities:
        1. Accumulate audio buffers with speech/silence labels
        2. Detect when user finished speaking (end-of-turn)
        3. Provide COMPLETE/INCOMPLETE state for conversation management

    Workflow:
        ```
        User speaks: "Hello, [pause] how are you?" [pause]
                      ↓        ↓                     ↓
        append_audio(): [speech] [silence] [speech] [silence]
                                                      ↓
        analyze_end_of_turn(): Check pause duration
                              ↓
                        EndOfTurnState.COMPLETE
                              ↓
        Agent responds: "I'm doing well, thanks!"
        ```

    Thread Safety:
        Each CallSession has its own BaseTurnAnalyzer instance.
        No locking needed (single-threaded asyncio event loop).

    Usage:
        ```python
        # In RTP audio processing pipeline
        turn_analyzer = SimpleTurnAnalyzer(sample_rate=8000)

        # For each audio frame from RTP
        state = turn_analyzer.append_audio(pcm_data, is_speech=True)

        if state == EndOfTurnState.COMPLETE:
            # User finished speaking, send to ASR/LLM
            transcription = await asr_engine.transcribe(turn_analyzer.buffer)
            response = await llm_engine.generate(transcription)
            turn_analyzer.clear()  # Reset for next turn
        ```
    """

    def __init__(self, *, sample_rate: Optional[int] = None):
        """
        Initialize the turn analyzer.

        Args:
            sample_rate: Audio sample rate (e.g., 8000 for G.711 ulaw)
                If provided, this will be used as the fixed sample rate.
                If None, must call set_sample_rate() before use.

        Example:
            analyzer = SimpleTurnAnalyzer(sample_rate=8000)
        """
        self._init_sample_rate = sample_rate
        self._sample_rate = sample_rate or 0

    @property
    def sample_rate(self) -> int:
        """
        Returns the current sample rate.

        Returns:
            Sample rate in Hz (e.g., 8000 for telephony, 16000 for Whisper)
        """
        return self._sample_rate

    def set_sample_rate(self, sample_rate: int):
        """
        Sets the sample rate for audio processing.

        If initial sample rate was provided in __init__, it overrides this.
        Otherwise, sets to the provided sample rate.

        Args:
            sample_rate: Sample rate in Hz

        Example:
            analyzer.set_sample_rate(8000)  # G.711 ulaw rate
        """
        if self._init_sample_rate is not None:
            self._sample_rate = self._init_sample_rate
        else:
            self._sample_rate = sample_rate

    @property
    @abstractmethod
    def speech_triggered(self) -> bool:
        """
        Determines if speech has been detected.

        Returns:
            True if speech is currently active or was recently detected,
            False if only silence detected so far.

        Use Case:
            Check if user started speaking before analyzing end-of-turn.
            No point analyzing turn boundaries if user hasn't spoken yet.

        Example:
            if turn_analyzer.speech_triggered:
                state = await turn_analyzer.analyze_end_of_turn()
        """
        pass

    @property
    @abstractmethod
    def params(self) -> BaseTurnParams:
        """
        Get the current turn analyzer parameters.

        Returns:
            Current turn analyzer configuration parameters.

        Example:
            params = analyzer.params
            print(f"Pause duration: {params.pause_duration}s")
        """
        pass

    @abstractmethod
    def append_audio(self, buffer: bytes, is_speech: bool) -> EndOfTurnState:
        """
        Appends audio data for analysis.

        Called for every RTP audio frame (20ms @ 8kHz = 160 samples).
        Accumulates audio and speech/silence state for turn detection.

        Args:
            buffer: Raw PCM audio data (int16 samples)
                - Format: Raw PCM S16LE (signed 16-bit little-endian)
                - Example: 20ms @ 8kHz = 160 samples = 320 bytes

            is_speech: VAD result for this frame
                - True: Speech detected (user speaking)
                - False: Silence detected (pause or no input)

        Returns:
            EndOfTurnState:
                - COMPLETE: User finished speaking (ready to process)
                - INCOMPLETE: User still speaking or may continue

        Example:
            ```python
            # In RTP audio processing
            vad_result = vad.process_frame(pcm_data)  # True/False
            turn_state = turn_analyzer.append_audio(pcm_data, vad_result)

            if turn_state == EndOfTurnState.COMPLETE:
                # Process user's complete utterance
                await process_user_input(turn_analyzer.get_buffer())
            ```

        Pattern:
            This method is synchronous (not async) for performance:
            - Called 50 times/second (20ms frames @ 8kHz)
            - No I/O operations needed (pure state machine)
            - Keeps RTP processing pipeline fast
        """
        pass

    @abstractmethod
    async def analyze_end_of_turn(self) -> Tuple[EndOfTurnState, Optional[dict]]:
        """
        Analyzes if an end-of-turn has occurred based on accumulated audio.

        Called periodically (or on silence detection) to check if user
        finished speaking. More sophisticated than append_audio() return value:
        - Can use ML models (async inference)
        - Can analyze speech patterns (prosody, pauses)
        - Can return confidence scores

        Returns:
            Tuple of:
                - EndOfTurnState: COMPLETE or INCOMPLETE
                - Optional[dict]: Metrics/debug data (can be None)
                    - Example: {"confidence": 0.95, "pause_duration": 1.2}

        Example:
            ```python
            if turn_analyzer.speech_triggered:
                state, metrics = await turn_analyzer.analyze_end_of_turn()

                if state == EndOfTurnState.COMPLETE:
                    logger.info(f"Turn complete: {metrics}")
                    await process_user_input()
            ```

        Pattern:
            - Simple analyzers: Synchronous logic, return (state, None)
            - ML analyzers: Async inference, return (state, metrics)
        """
        pass

    def update_vad_start_secs(self, vad_start_secs: float):
        """
        Update the VAD start trigger time.

        The turn analyzer may adjust its buffer size or analysis strategy
        based on how quickly VAD triggers speech detection.

        Args:
            vad_start_secs: Number of seconds of voice activity before
                triggering the user speaking event.
                - Example: 0.3s (Silero VAD default)
                - Affects how much audio we need before turn analysis

        Use Case:
            If VAD triggers quickly (0.1s), we can use shorter pause durations.
            If VAD triggers slowly (0.5s), we need longer pause durations.

        Example:
            turn_analyzer.update_vad_start_secs(0.3)  # Silero VAD

        Note:
            Optional method - simple analyzers may ignore this.
        """
        pass

    @abstractmethod
    def clear(self):
        """
        Reset the turn analyzer to its initial state.

        Called after processing a complete turn (user utterance) to
        prepare for the next turn.

        Responsibilities:
            - Clear accumulated audio buffer
            - Reset speech_triggered flag
            - Reset silence duration counters
            - Reset any internal state machine

        Example:
            ```python
            # After processing user input
            transcription = await asr_engine.transcribe(turn_analyzer.buffer)
            response = await llm_engine.generate(transcription)

            # Reset for next turn
            turn_analyzer.clear()
            ```

        Pattern:
            Synchronous method (no I/O needed, just state reset)
        """
        pass

    async def cleanup(self):
        """
        Cleanup the turn analyzer (called on session end).

        Called when CallSession is being destroyed (call ended, timeout, etc.)

        Responsibilities:
            - Release any resources (file handles, model memory, etc.)
            - Cancel any background tasks
            - Final state cleanup

        Example:
            ```python
            # In RTP server cleanup
            if session.turn_analyzer:
                await session.turn_analyzer.cleanup()
            ```

        Note:
            Base implementation does nothing - subclasses override if needed.
        """
        pass


# Export all classes/enums
__all__ = [
    'EndOfTurnState',
    'BaseTurnParams',
    'BaseTurnAnalyzer',
]
