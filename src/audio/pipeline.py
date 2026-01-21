"""
Audio Pipeline - Orchestrates audio processing flow

Coordinates: RTP → Codec → VAD → Buffer → AI Components
"""

import asyncio
from dataclasses import dataclass
from typing import Optional, Callable

from ..common.logging import get_logger
from ..rtp.server import RTPSession
from .codec import G711Codec
from .buffer import AudioBuffer
from .vad import VoiceActivityDetector
from .stream import RTPAudioStream

logger = get_logger('audio.pipeline')


@dataclass
class AudioPipelineConfig:
    """Audio Pipeline Configuration"""
    # Codec
    codec_law: str = 'ulaw'  # 'ulaw' or 'alaw'

    # VAD
    vad_energy_threshold_start: float = 500.0
    vad_energy_threshold_end: float = 300.0
    vad_silence_duration_ms: int = 500
    vad_min_speech_duration_ms: int = 300
    vad_webrtc_aggressiveness: int = 1

    # Buffer
    buffer_sample_rate: int = 8000
    buffer_target_rate: int = 16000
    buffer_max_duration_seconds: float = 30.0


class AudioPipeline:
    """
    Audio processing pipeline orchestrator

    Flow:
    RTP → Decode → VAD → Buffer → [AI Pipeline]
    [AI Pipeline] → Encode → RTP

    Usage:
        config = AudioPipelineConfig()
        pipeline = AudioPipeline(config)

        # Process a call
        await pipeline.process_call(rtp_session)
    """

    def __init__(self, config: AudioPipelineConfig):
        """
        Initialize audio pipeline

        Args:
            config: Pipeline configuration
        """
        self.config = config

        # Components
        self.codec = G711Codec(law=config.codec_law)
        self.buffer = AudioBuffer(
            sample_rate=config.buffer_sample_rate,
            target_rate=config.buffer_target_rate,
            max_duration_seconds=config.buffer_max_duration_seconds
        )
        self.vad = VoiceActivityDetector(
            sample_rate=config.buffer_sample_rate,
            energy_threshold_start=config.vad_energy_threshold_start,
            energy_threshold_end=config.vad_energy_threshold_end,
            silence_duration_ms=config.vad_silence_duration_ms,
            min_speech_duration_ms=config.vad_min_speech_duration_ms,
            webrtc_aggressiveness=config.vad_webrtc_aggressiveness,
            on_speech_start=self._on_speech_start,
            on_speech_end=self._on_speech_end
        )

        # Stream
        self.stream: Optional[RTPAudioStream] = None

        # State
        self.running = False

        # Callbacks (for AI integration)
        self.on_speech_ready: Optional[Callable[[bytes], None]] = None

        logger.info("AudioPipeline initialized", config=config)

    async def process_call(self, rtp_session: RTPSession):
        """
        Main loop for processing one call

        Args:
            rtp_session: RTP session to process
        """
        self.running = True

        # Create audio stream
        self.stream = RTPAudioStream(rtp_session, self.codec)

        logger.info("Starting audio processing", session_id=rtp_session.session_id)

        try:
            while self.running and rtp_session.connection.running:
                try:
                    # Get RTP packet from queue
                    header, payload = await asyncio.wait_for(
                        rtp_session.audio_in_queue.get(),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    logger.debug("No audio for 5s, checking connection...")
                    if not rtp_session.connection.running:
                        break
                    continue

                # Decode G.711 → PCM
                pcm_data = self.codec.decode(payload)
                if pcm_data is None:
                    continue

                # VAD detection
                is_speech = self.vad.process_frame(pcm_data)

                # Accumulate speech frames
                if is_speech:
                    self.buffer.add_frame(pcm_data)

        except asyncio.CancelledError:
            logger.info("Audio processing cancelled")
        except Exception as e:
            logger.error("Error in audio processing", error=str(e))
        finally:
            self.running = False
            if self.stream:
                await self.stream.close()

            logger.info("Audio processing stopped", session_id=rtp_session.session_id)

    def _on_speech_start(self):
        """Callback when speech starts"""
        logger.debug("Speech started - clearing buffer")
        self.buffer.clear()

    def _on_speech_end(self):
        """Callback when speech ends"""
        logger.debug("Speech ended - processing buffer")

        # Get audio from buffer
        audio_data = self.buffer.get_audio(resample=True)
        if audio_data is None or len(audio_data) == 0:
            logger.warning("No audio in buffer after speech ended")
            return

        duration = self.buffer.get_duration()
        logger.info("Speech ready for processing",
                   duration_s=f"{duration:.2f}",
                   samples=len(audio_data))

        # Trigger AI processing callback
        if self.on_speech_ready:
            try:
                # Convert numpy array to bytes
                audio_bytes = audio_data.tobytes()
                self.on_speech_ready(audio_bytes)
            except Exception as e:
                logger.error("Error in speech_ready callback", error=str(e))

        # Clear buffer for next speech segment
        self.buffer.clear()

    async def stop(self):
        """Stop audio processing"""
        self.running = False

        if self.stream:
            await self.stream.close()

        logger.info("AudioPipeline stopped")

    def get_stats(self) -> dict:
        """Get pipeline statistics"""
        stats = {
            'running': self.running,
            'codec': self.codec.get_stats(),
            'buffer': self.buffer.get_stats(),
            'vad': self.vad.get_stats(),
        }

        if self.stream:
            stats['stream'] = self.stream.get_stats()

        return stats
