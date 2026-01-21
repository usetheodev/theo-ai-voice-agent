"""
Kokoro TTS Integration

Uses Kokoro-82M - A lightweight, efficient TTS model with 82M parameters.
Best for real-time voice agents with streaming support.

Reference: https://huggingface.co/hexgrad/Kokoro-82M
"""

import logging
import numpy as np
from typing import Optional, Generator
import soundfile as sf
import io


class KokoroTTS:
    """
    Kokoro TTS wrapper for real-time speech synthesis

    Usage:
        tts = KokoroTTS(
            lang_code='p',  # Brazilian Portuguese
            voice='pf_dora'  # Female Brazilian voice
        )

        # Option 1: Generate complete audio
        audio = tts.synthesize("Olá, como posso ajudar?")
        # Returns: numpy array (float32, 24000 Hz)

        # Option 2: Stream audio chunks (for real-time)
        for chunk in tts.synthesize_stream("Olá, como posso ajudar?"):
            # Process chunk in real-time
            pass
    """

    def __init__(self,
                 lang_code: str = 'p',
                 voice: str = 'pf_dora',
                 sample_rate: int = 24000):
        """
        Initialize Kokoro TTS

        Args:
            lang_code: Language code
                'a' => American English
                'b' => British English
                'e' => Spanish
                'f' => French
                'p' => Brazilian Portuguese (pt-br)
                'j' => Japanese
                'z' => Mandarin Chinese
            voice: Voice name (see VOICES.md)
                Brazilian Portuguese:
                - 'pf_dora' (female)
                - 'pm_alex' (male)
                - 'pm_santa' (male)
            sample_rate: Output sample rate (default: 24000 Hz)
        """
        self.lang_code = lang_code
        self.voice = voice
        self.sample_rate = sample_rate

        self.logger = logging.getLogger("ai-voice-agent.tts.kokoro")

        # Initialize Kokoro pipeline
        try:
            from kokoro import KPipeline
            self.pipeline = KPipeline(lang_code=lang_code)
            self.logger.info(f"Kokoro TTS initialized: lang={lang_code}, voice={voice}, rate={sample_rate}Hz")
        except Exception as e:
            self.logger.error(f"Failed to initialize Kokoro TTS: {e}")
            raise

        # Statistics
        self.synthesis_count = 0
        self.total_chars_synthesized = 0

    def synthesize(self, text: str) -> Optional[np.ndarray]:
        """
        Synthesize text to audio (complete generation)

        Args:
            text: Text to synthesize

        Returns:
            Audio as numpy array (float32, sample_rate Hz) or None on error
        """
        try:
            if not text or not text.strip():
                self.logger.warning("Empty text provided for synthesis")
                return None

            self.logger.debug(f"Synthesizing: {text[:50]}...")

            # Generate audio using Kokoro pipeline
            # Pipeline returns generator: (graphemes, phonemes, audio)
            audio_chunks = []
            for i, (gs, ps, audio) in enumerate(self.pipeline(text, voice=self.voice)):
                audio_chunks.append(audio)
                self.logger.debug(f"Generated chunk {i}: {len(audio)} samples")

            # Concatenate all chunks
            if audio_chunks:
                full_audio = np.concatenate(audio_chunks)

                # Update statistics
                self.synthesis_count += 1
                self.total_chars_synthesized += len(text)

                self.logger.info(f"✅ Synthesis #{self.synthesis_count}: {len(text)} chars → {len(full_audio)} samples ({len(full_audio)/self.sample_rate:.2f}s)")
                return full_audio

            self.logger.warning("TTS returned no audio chunks")
            return None

        except Exception as e:
            self.logger.error(f"Synthesis error: {e}", exc_info=True)
            return None

    def synthesize_stream(self, text: str) -> Generator[np.ndarray, None, None]:
        """
        Synthesize text to audio with streaming (real-time chunks)

        Args:
            text: Text to synthesize

        Yields:
            Audio chunks as numpy arrays (float32, sample_rate Hz)
        """
        try:
            if not text or not text.strip():
                self.logger.warning("Empty text provided for streaming synthesis")
                return

            self.logger.debug(f"Streaming synthesis: {text[:50]}...")

            # Generate audio chunks using Kokoro pipeline
            chunk_count = 0
            for i, (gs, ps, audio) in enumerate(self.pipeline(text, voice=self.voice)):
                chunk_count += 1
                self.logger.debug(f"Streaming chunk {i}: {len(audio)} samples")
                yield audio

            # Update statistics after all chunks
            if chunk_count > 0:
                self.synthesis_count += 1
                self.total_chars_synthesized += len(text)
                self.logger.info(f"✅ Streamed synthesis #{self.synthesis_count}: {len(text)} chars in {chunk_count} chunks")

        except Exception as e:
            self.logger.error(f"Streaming synthesis error: {e}", exc_info=True)

    def synthesize_to_wav(self, text: str, output_path: str) -> bool:
        """
        Synthesize text and save to WAV file

        Args:
            text: Text to synthesize
            output_path: Path to save WAV file

        Returns:
            True if successful, False otherwise
        """
        try:
            audio = self.synthesize(text)
            if audio is None:
                return False

            sf.write(output_path, audio, self.sample_rate)
            self.logger.info(f"Audio saved to: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to save WAV: {e}", exc_info=True)
            return False

    def synthesize_to_bytes(self, text: str) -> Optional[bytes]:
        """
        Synthesize text and return WAV bytes

        Args:
            text: Text to synthesize

        Returns:
            WAV file bytes or None on error
        """
        try:
            audio = self.synthesize(text)
            if audio is None:
                return None

            # Convert to WAV bytes
            wav_buffer = io.BytesIO()
            sf.write(wav_buffer, audio, self.sample_rate, format='WAV')
            wav_bytes = wav_buffer.getvalue()

            self.logger.debug(f"Generated {len(wav_bytes)} bytes of WAV data")
            return wav_bytes

        except Exception as e:
            self.logger.error(f"Failed to generate WAV bytes: {e}", exc_info=True)
            return None

    def get_stats(self) -> dict:
        """Get TTS statistics"""
        return {
            'synthesis_count': self.synthesis_count,
            'total_chars_synthesized': self.total_chars_synthesized,
            'lang_code': self.lang_code,
            'voice': self.voice,
            'sample_rate': self.sample_rate
        }


def test_kokoro_tts():
    """Test Kokoro TTS with Brazilian Portuguese"""
    print("Testing Kokoro TTS...")

    # Create TTS instance
    tts = KokoroTTS(
        lang_code='p',  # Brazilian Portuguese
        voice='pf_dora'  # Female voice
    )

    # Test texts
    test_texts = [
        "Olá, tudo bem?",
        "Eu sou um assistente de voz brasileiro.",
        "Como posso ajudar você hoje?"
    ]

    for i, text in enumerate(test_texts):
        print(f"\nTest {i+1}: {text}")

        # Generate audio
        audio = tts.synthesize(text)
        if audio is not None:
            print(f"  ✅ Generated: {len(audio)} samples ({len(audio)/24000:.2f}s)")

            # Save to file
            output_file = f"test_kokoro_{i+1}.wav"
            if tts.synthesize_to_wav(text, output_file):
                print(f"  ✅ Saved to: {output_file}")
        else:
            print(f"  ❌ Failed to generate audio")

    # Print statistics
    print(f"\nStatistics: {tts.get_stats()}")


if __name__ == '__main__':
    test_kokoro_tts()
