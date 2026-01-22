"""
SimulStreaming ASR Integration

SimulStreaming is the successor to WhisperStreaming, offering:
- ~100ms streaming latency (vs ~200ms for WhisperStreaming)
- Partial results for progressive transcription
- Based on faster-whisper backend
- Self-adaptive latency using local agreement policy

References:
- GitHub: https://github.com/ufal/whisper_streaming
- Paper: SimulStreaming (2025) by Dominik Macháček
"""

import logging
import numpy as np
import asyncio
from typing import Optional, AsyncIterator, Dict, Any
from dataclasses import dataclass

# Import will be conditional based on installation
try:
    from whisper_online import FasterWhisperASR, OnlineASRProcessor
    SIMULSTREAMING_AVAILABLE = True
except ImportError:
    SIMULSTREAMING_AVAILABLE = False
    FasterWhisperASR = None
    OnlineASRProcessor = None


@dataclass
class ASRResult:
    """ASR transcription result"""
    text: str
    is_partial: bool = False
    confidence: float = 1.0
    timestamp: float = 0.0


class SimulStreamingASR:
    """
    SimulStreaming ASR wrapper compatible with WhisperASR interface

    Features:
    - Streaming transcription with partial results
    - ~100ms latency (lower than batch Whisper)
    - Compatible interface with WhisperASR for easy swapping
    - Support for async streaming via transcribe_stream()

    Usage:
        # Initialize
        asr = SimulStreamingASR(
            model="base",
            language="pt",
            min_chunk_size=1.0
        )

        # Batch transcription (compatible with WhisperASR)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        text = asr.transcribe_array(audio_float32)

        # Streaming transcription (new feature)
        async for result in asr.transcribe_stream(audio_iterator):
            if result.is_partial:
                print(f"Partial: {result.text}")
            else:
                print(f"Final: {result.text}")
    """

    def __init__(self,
                 model: str = "base",
                 language: str = "pt",
                 min_chunk_size: float = 1.0,
                 buffer_trimming: str = "segment",
                 n_threads: int = 4):
        """
        Initialize SimulStreaming ASR

        Args:
            model: Whisper model size (tiny, base, small, medium, large-v3)
            language: Language code (pt, en, es, etc.)
            min_chunk_size: Minimum audio chunk size in seconds before processing
            buffer_trimming: Buffer management strategy ('segment' or 'sentence')
            n_threads: Number of CPU threads to use
        """
        if not SIMULSTREAMING_AVAILABLE:
            raise ImportError(
                "whisper-streaming is not installed. "
                "Install it with: pip install whisper-streaming"
            )

        self.model_name = model
        self.language = language
        self.min_chunk_size = min_chunk_size
        self.buffer_trimming = buffer_trimming
        self.n_threads = n_threads

        self.logger = logging.getLogger("ai-voice-agent.asr.simulstreaming")

        # Initialize the model
        try:
            # Initialize FasterWhisper backend
            self.asr_backend = FasterWhisperASR(lan=language, modelsize=model)

            # Initialize online processor
            self.model = OnlineASRProcessor(self.asr_backend)

            self.logger.info(
                f"SimulStreaming ASR initialized: model={model}, "
                f"language={language}, min_chunk_size={min_chunk_size}s"
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize SimulStreaming model: {e}")
            raise

        # Statistics
        self.transcriptions_count = 0
        self.partial_results_count = 0
        self.total_duration = 0.0

    def transcribe_array(self, audio_data: np.ndarray) -> Optional[str]:
        """
        Transcribe audio from numpy array (batch mode - compatible with WhisperASR)

        This method provides compatibility with WhisperASR interface.
        For streaming, use transcribe_stream() instead.

        Args:
            audio_data: Audio samples as numpy array
                       - dtype: float32
                       - range: [-1.0, 1.0]
                       - sample rate: 16000 Hz
                       - shape: (n_samples,)

        Returns:
            Transcribed text or None on error
        """
        try:
            # Validate input
            if audio_data.dtype != np.float32:
                self.logger.warning(f"Converting audio from {audio_data.dtype} to float32")
                audio_data = audio_data.astype(np.float32)

            # Ensure audio is in [-1.0, 1.0] range
            if audio_data.max() > 1.0 or audio_data.min() < -1.0:
                self.logger.warning(f"Audio range: [{audio_data.min():.3f}, {audio_data.max():.3f}] - normalizing")
                audio_data = np.clip(audio_data, -1.0, 1.0)

            # Process audio through streaming model
            # Note: This is batch mode - for true streaming use transcribe_stream()
            self.model.init()  # Reset state

            # Feed audio to model
            self.model.insert_audio_chunk(audio_data)

            # Process and get result
            output = self.model.process_iter()

            # Finalize
            final_output = self.model.finish()

            # Extract text from output
            # Output format: (beg_timestamp, end_timestamp, text)
            if final_output and len(final_output) >= 3:
                text = final_output[2].strip() if final_output[2] else ""

                if text:
                    self.transcriptions_count += 1
                    self.logger.info(f"✅ Transcription #{self.transcriptions_count}: {text}")
                    return text

            self.logger.warning("Transcription returned empty result")
            return None

        except Exception as e:
            self.logger.error(f"Transcription error: {e}", exc_info=True)
            return None

    async def transcribe_stream(self,
                                audio_iterator: AsyncIterator[np.ndarray]
                                ) -> AsyncIterator[ASRResult]:
        """
        Transcribe audio stream with partial results

        This is the main streaming method that provides low-latency transcription.
        It yields both partial and final results as audio is processed.

        Args:
            audio_iterator: Async iterator of audio chunks (numpy arrays)
                           Each chunk should be float32, 16kHz, mono

        Yields:
            ASRResult objects with partial or final transcriptions
        """
        try:
            self.model.init()  # Reset state

            async for audio_chunk in audio_iterator:
                # Validate and normalize audio
                if audio_chunk.dtype != np.float32:
                    audio_chunk = audio_chunk.astype(np.float32)

                if audio_chunk.max() > 1.0 or audio_chunk.min() < -1.0:
                    audio_chunk = np.clip(audio_chunk, -1.0, 1.0)

                # Insert audio chunk
                await asyncio.to_thread(
                    self.model.insert_audio_chunk,
                    audio_chunk
                )

                # Process and get partial result
                output = await asyncio.to_thread(self.model.process_iter)

                if output:
                    # Output format: (beg_timestamp, end_timestamp, text)
                    # Empty output means no confirmed words yet
                    if len(output) >= 3 and output[2]:
                        text = output[2].strip()

                        if text:
                            # This is a partial result (confirmed words so far)
                            self.partial_results_count += 1
                            self.logger.debug(f"⏳ Partial #{self.partial_results_count}: {text}")

                            yield ASRResult(
                                text=text,
                                is_partial=True,
                                confidence=1.0,  # whisper-streaming doesn't provide confidence
                                timestamp=output[0] if len(output) > 0 else 0.0
                            )

            # Finalize and get complete result
            final_output = await asyncio.to_thread(self.model.finish)

            if final_output and len(final_output) >= 3 and final_output[2]:
                text = final_output[2].strip()

                if text:
                    self.transcriptions_count += 1
                    self.logger.info(f"✅ Final #{self.transcriptions_count}: {text}")

                    yield ASRResult(
                        text=text,
                        is_partial=False,
                        confidence=1.0,
                        timestamp=final_output[0] if len(final_output) > 0 else 0.0
                    )

        except Exception as e:
            self.logger.error(f"Streaming transcription error: {e}", exc_info=True)

    def transcribe(self, wav_bytes: bytes) -> Optional[str]:
        """
        Transcribe WAV audio bytes (compatible with WhisperASR interface)

        Args:
            wav_bytes: WAV file bytes (must be 16kHz, mono, 16-bit)

        Returns:
            Transcribed text or None on error
        """
        try:
            import wave
            import io

            # Parse WAV file
            with wave.open(io.BytesIO(wav_bytes), 'rb') as wav:
                # Validate format
                if wav.getnchannels() != 1:
                    self.logger.error(f"WAV must be mono, got {wav.getnchannels()} channels")
                    return None

                if wav.getframerate() != 16000:
                    self.logger.error(f"WAV must be 16kHz, got {wav.getframerate()} Hz")
                    return None

                if wav.getsampwidth() != 2:
                    self.logger.error(f"WAV must be 16-bit, got {wav.getsampwidth()} bytes per sample")
                    return None

                # Read PCM data
                frames = wav.readframes(wav.getnframes())
                audio_int16 = np.frombuffer(frames, dtype=np.int16)

            # Convert int16 to float32 in range [-1.0, 1.0]
            audio_float32 = audio_int16.astype(np.float32) / 32768.0

            # Transcribe using array method
            return self.transcribe_array(audio_float32)

        except Exception as e:
            self.logger.error(f"WAV parsing error: {e}", exc_info=True)
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get ASR statistics (compatible with WhisperASR interface)"""
        return {
            'provider': 'simulstreaming',
            'transcriptions_count': self.transcriptions_count,
            'partial_results_count': self.partial_results_count,
            'total_duration': self.total_duration,
            'model': self.model_name,
            'language': self.language,
            'min_chunk_size': self.min_chunk_size,
            'n_threads': self.n_threads
        }

    def reset(self):
        """Reset internal state (useful for new sessions)"""
        self.model.init()
        self.logger.debug("SimulStreaming state reset")


# Capability detection
def is_simulstreaming_available() -> bool:
    """Check if SimulStreaming is available"""
    return SIMULSTREAMING_AVAILABLE


async def test_simulstreaming_asr():
    """Test SimulStreaming ASR with sample audio"""
    if not SIMULSTREAMING_AVAILABLE:
        print("❌ SimulStreaming not available. Install with: pip install whisper-streaming")
        return

    print("✅ SimulStreaming available")

    # Create test audio (1 second 440 Hz tone)
    sample_rate = 16000
    duration = 1.0
    frequency = 440

    t = np.linspace(0, duration, int(sample_rate * duration))
    audio = np.sin(2 * np.pi * frequency * t).astype(np.float32) * 0.5

    # Test ASR
    asr = SimulStreamingASR(
        model="base",
        language="pt",
        min_chunk_size=1.0
    )

    print(f"Testing SimulStreaming ASR with {len(audio)} samples...")

    # Test batch mode (WhisperASR compatible)
    text = asr.transcribe_array(audio)
    print(f"Batch transcription: {text}")

    # Test streaming mode
    async def audio_generator():
        chunk_size = 4000  # ~250ms chunks
        for i in range(0, len(audio), chunk_size):
            yield audio[i:i+chunk_size]
            await asyncio.sleep(0.01)  # Simulate real-time

    print("\nStreaming transcription:")
    async for result in asr.transcribe_stream(audio_generator()):
        prefix = "⏳" if result.is_partial else "✅"
        print(f"{prefix} {result.text} (conf: {result.confidence:.2f})")

    print(f"\nStats: {asr.get_stats()}")


if __name__ == '__main__':
    # Run test
    asyncio.run(test_simulstreaming_asr())
