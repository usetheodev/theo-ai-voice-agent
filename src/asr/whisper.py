"""
Whisper ASR Integration using Python API

Uses pywhispercpp - Python bindings for whisper.cpp
Native C++ API for fast CPU inference without subprocess overhead.
"""

import logging
import numpy as np
from typing import Optional
from pywhispercpp.model import Model


class WhisperASR:
    """
    Whisper ASR wrapper using native Python API

    Usage:
        asr = WhisperASR(
            model_path="/app/models/whisper/ggml-base.bin",
            language="pt"
        )

        # Option 1: From numpy array (float32, 16kHz)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        text = asr.transcribe_array(audio_float32)

        # Option 2: From WAV bytes
        text = asr.transcribe(wav_bytes)
    """

    def __init__(self,
                 model_path: str,
                 language: str = "pt",
                 n_threads: int = 4):
        """
        Initialize Whisper ASR

        Args:
            model_path: Path to Whisper GGML model file
            language: Language code (pt, en, es, etc.)
            n_threads: Number of CPU threads to use
        """
        self.model_path = model_path
        self.language = language
        self.n_threads = n_threads

        self.logger = logging.getLogger("ai-voice-agent.asr.whisper")

        # Initialize the model
        try:
            self.model = Model(
                model_path,
                n_threads=n_threads,
                print_realtime=False,
                print_progress=False
            )
            self.logger.info(f"Whisper ASR initialized: {model_path} (language: {language}, threads: {n_threads})")
        except Exception as e:
            self.logger.error(f"Failed to initialize Whisper model: {e}")
            raise

        # Statistics
        self.transcriptions_count = 0
        self.total_duration = 0.0

    def transcribe_array(self, audio_data: np.ndarray) -> Optional[str]:
        """
        Transcribe audio from numpy array

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

            # Transcribe using the model
            segments = self.model.transcribe(
                audio_data,
                language=self.language,
                n_threads=self.n_threads,
                no_context=True  # Prevent hallucinations (84.5% reduction - Wang et al. 2025)
            )

            # Extract text from segments
            if segments:
                # segments is a list of segment objects with .text attribute
                text_parts = []
                for segment in segments:
                    if hasattr(segment, 'text'):
                        text_parts.append(segment.text.strip())
                    elif isinstance(segment, dict) and 'text' in segment:
                        text_parts.append(segment['text'].strip())
                    else:
                        # If segment is just a string
                        text_parts.append(str(segment).strip())

                transcription = ' '.join(text_parts).strip()

                if transcription:
                    self.transcriptions_count += 1
                    self.logger.info(f"✅ Transcription #{self.transcriptions_count}: {transcription}")
                    return transcription

            self.logger.warning("Transcription returned empty result")
            return None

        except Exception as e:
            self.logger.error(f"Transcription error: {e}", exc_info=True)
            return None

    def transcribe(self, wav_bytes: bytes) -> Optional[str]:
        """
        Transcribe WAV audio bytes

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

    def get_stats(self) -> dict:
        """Get ASR statistics"""
        return {
            'transcriptions_count': self.transcriptions_count,
            'total_duration': self.total_duration,
            'model': self.model_path,
            'language': self.language,
            'n_threads': self.n_threads
        }


def test_whisper_asr():
    """Test Whisper ASR with sample audio"""
    import numpy as np
    import wave
    import io

    # Create test WAV (1 second 440 Hz tone)
    sample_rate = 16000
    duration = 1.0
    frequency = 440

    t = np.linspace(0, duration, int(sample_rate * duration))
    audio = (np.sin(2 * np.pi * frequency * t) * 32767 * 0.5).astype(np.int16)

    # Create WAV bytes
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio.tobytes())

    wav_bytes = wav_buffer.getvalue()

    # Test ASR
    asr = WhisperASR(
        model_path="/app/models/whisper/ggml-base.bin",
        language="pt"
    )

    print(f"Testing Whisper ASR with {len(wav_bytes)} bytes WAV...")
    text = asr.transcribe(wav_bytes)
    print(f"Transcription: {text}")
    print(f"Stats: {asr.get_stats()}")


if __name__ == '__main__':
    test_whisper_asr()
