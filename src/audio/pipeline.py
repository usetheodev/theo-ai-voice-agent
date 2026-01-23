"""
Audio Pipeline - Orchestrates audio processing flow

Coordinates: RTP → Codec → VAD → Buffer → AI Components

Full-Duplex Support:
- Hybrid VAD (Energy + WebRTC + Silero)
- Acoustic Echo Cancellation (Speex AEC)
- Barge-in detection during AI speech
"""

import asyncio
from dataclasses import dataclass
from typing import Optional, Callable
import numpy as np

from ..common.logging import get_logger
from ..rtp.server import RTPSession
from .codec import G711Codec
from .buffer import AudioBuffer
from .vad import VoiceActivityDetector
from .stream import RTPAudioStream
from ..ai.vad_hybrid import HybridVAD, VADResult, is_hybrid_vad_available
from ..ai.barge_in import BargeInHandler, BargeInEvent

logger = get_logger('audio.pipeline')


@dataclass
class AudioPipelineConfig:
    """Audio Pipeline Configuration"""
    # Codec
    codec_law: str = 'ulaw'  # 'ulaw' or 'alaw'

    # Legacy VAD (kept for fallback if Hybrid VAD not available)
    vad_energy_threshold_start: float = 500.0
    vad_energy_threshold_end: float = 300.0
    vad_silence_duration_ms: int = 500
    vad_min_speech_duration_ms: int = 300
    vad_webrtc_aggressiveness: int = 1

    # Hybrid VAD (Full-Duplex)
    use_hybrid_vad: bool = True
    vad_enable_aec: bool = True
    vad_enable_silero: bool = True
    vad_energy_threshold_db: float = -40.0
    vad_silero_threshold: float = 0.5
    vad_grace_period_ms: int = 200
    vad_min_silence_duration_ms: int = 100

    # Barge-in
    barge_in_enabled: bool = True
    barge_in_min_confidence: float = 0.7

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

        # Initialize VAD (Hybrid or Legacy)
        self.use_hybrid_vad = config.use_hybrid_vad and is_hybrid_vad_available()

        if self.use_hybrid_vad:
            logger.info("🔊 Initializing Full-Duplex Hybrid VAD")
            self.hybrid_vad = HybridVAD(
                sample_rate=config.buffer_sample_rate,
                enable_aec=config.vad_enable_aec,
                enable_silero=config.vad_enable_silero,
                energy_threshold_db=config.vad_energy_threshold_db,
                silero_threshold=config.vad_silero_threshold,
                webrtc_aggressiveness=config.vad_webrtc_aggressiveness,
                grace_period_ms=config.vad_grace_period_ms,
                min_speech_duration_ms=config.vad_min_speech_duration_ms,
                min_silence_duration_ms=config.vad_min_silence_duration_ms,
            )
            self.vad = None  # Legacy VAD not used

            # Initialize Barge-in Handler
            if config.barge_in_enabled:
                self.barge_in_handler = BargeInHandler(
                    on_barge_in=self._on_barge_in,
                    grace_period_ms=config.vad_grace_period_ms,
                    min_interruption_confidence=config.barge_in_min_confidence,
                )
                logger.info("🔴 Barge-in handler initialized")
            else:
                self.barge_in_handler = None
                logger.info("⚠️ Barge-in disabled")
        else:
            # Fallback to legacy VAD
            logger.warning("⚠️ Hybrid VAD not available - using legacy VAD")
            self.hybrid_vad = None
            self.barge_in_handler = None
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
        self.ai_is_speaking = False
        self.ai_reference_audio: Optional[np.ndarray] = None  # For AEC
        self.speech_active = False  # Track speech state for Hybrid VAD

        # Callbacks (for AI integration)
        self.on_speech_ready: Optional[Callable[[bytes], None]] = None
        self.on_dtmf: Optional[Callable[[str], None]] = None  # Callback for DTMF digits
        self.on_barge_in_detected: Optional[Callable[[BargeInEvent], None]] = None  # Barge-in callback

        logger.info("AudioPipeline initialized",
                   hybrid_vad=self.use_hybrid_vad,
                   barge_in=config.barge_in_enabled if self.use_hybrid_vad else False)

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

        # Start DTMF monitoring task
        dtmf_task = asyncio.create_task(self._monitor_dtmf(rtp_session))

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

                # Process audio through appropriate VAD
                if self.use_hybrid_vad:
                    await self._process_hybrid_vad(pcm_data)
                else:
                    # Legacy VAD path
                    is_speech = self.vad.process_frame(pcm_data)

                    # Accumulate speech frames
                    if is_speech:
                        buffer_added = self.buffer.add_frame(pcm_data)

                        # If buffer is full, force speech end to process accumulated audio
                        if not buffer_added:
                            logger.warning("Buffer full - forcing speech end",
                                          duration_s=self.buffer.get_duration())
                            self.vad.force_speech_end()

        except asyncio.CancelledError:
            logger.info("Audio processing cancelled")
        except Exception as e:
            logger.error("Error in audio processing", error=str(e))
        finally:
            self.running = False

            # Stop DTMF monitoring
            dtmf_task.cancel()
            try:
                await dtmf_task
            except asyncio.CancelledError:
                pass

            if self.stream:
                await self.stream.close()

            logger.info("Audio processing stopped", session_id=rtp_session.session_id)

    async def _process_hybrid_vad(self, pcm_data: bytes):
        """
        Process audio through Hybrid VAD pipeline

        Args:
            pcm_data: PCM audio data from RTP (bytes, 8kHz, 16-bit)
        """
        # Convert bytes → numpy int16 → float32 [-1.0, 1.0]
        audio_int16 = np.frombuffer(pcm_data, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0

        # Process through Hybrid VAD
        try:
            vad_result = await self.hybrid_vad.process(
                user_audio=audio_float32,
                ai_reference_audio=self.ai_reference_audio  # For AEC
            )

            # Handle barge-in detection
            if vad_result.is_barge_in and self.barge_in_handler:
                await self.barge_in_handler.handle_user_speech(
                    confidence=vad_result.confidence,
                    energy_db=vad_result.energy_db
                )

            # State transitions
            if vad_result.is_speech and not self.speech_active:
                # Speech start
                self.speech_active = True
                logger.debug("🎤 Speech started (Hybrid VAD)")
                self.buffer.clear()

            elif not vad_result.is_speech and self.speech_active:
                # Speech end
                self.speech_active = False
                logger.debug("🔇 Speech ended (Hybrid VAD)")
                await self._finalize_speech()

            # Accumulate speech frames
            if vad_result.is_speech:
                buffer_added = self.buffer.add_frame(pcm_data)

                # If buffer is full, force speech end
                if not buffer_added:
                    logger.warning("Buffer full - forcing speech end",
                                  duration_s=self.buffer.get_duration())
                    self.speech_active = False
                    await self._finalize_speech()

        except Exception as e:
            logger.error("Error in Hybrid VAD processing", error=str(e), exc_info=True)

    async def _finalize_speech(self):
        """Finalize speech and send to ASR"""
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

    async def _on_barge_in(self, event: BargeInEvent):
        """
        Handle barge-in event (user interrupted AI)

        Args:
            event: Barge-in event metadata
        """
        logger.warning(
            "🔴 BARGE-IN DETECTED! User interrupted AI (event_id=%d, confidence=%.2f)",
            event.event_id,
            event.user_speech_confidence
        )

        # Notify application layer (will cancel TTS/RTP)
        if self.on_barge_in_detected:
            try:
                self.on_barge_in_detected(event)
            except Exception as e:
                logger.error("Error in barge-in callback", error=str(e))

    def set_ai_speaking(self, is_speaking: bool, audio_duration_ms: float = 0.0):
        """
        Update AI speaking state (for barge-in detection)

        Call this when:
        - AI starts TTS playback: set_ai_speaking(True)
        - AI finishes TTS playback: set_ai_speaking(False, duration_ms)

        Args:
            is_speaking: True if AI is currently speaking
            audio_duration_ms: Duration of AI speech (when stopping)
        """
        self.ai_is_speaking = is_speaking

        if self.barge_in_handler:
            self.barge_in_handler.set_ai_speaking(is_speaking, audio_duration_ms)

    def set_ai_reference_audio(self, audio: Optional[np.ndarray]):
        """
        Set AI reference audio for AEC (Acoustic Echo Cancellation)

        Call this before sending TTS audio to RTP to enable echo cancellation.

        Args:
            audio: AI audio being played (float32, 8kHz) or None to clear
        """
        self.ai_reference_audio = audio

    def _on_speech_start(self):
        """Callback when speech starts (legacy VAD)"""
        logger.debug("Speech started - clearing buffer")
        self.buffer.clear()

    def _on_speech_end(self):
        """Callback when speech ends (legacy VAD)"""
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

    async def _monitor_dtmf(self, rtp_session: RTPSession):
        """
        Monitor DTMF events from RTP session queue

        Args:
            rtp_session: RTP session with DTMF queue
        """
        logger.debug("DTMF monitoring started", session_id=rtp_session.session_id)

        try:
            while self.running:
                try:
                    # Wait for DTMF event
                    dtmf_event = await asyncio.wait_for(
                        rtp_session.dtmf_queue.get(),
                        timeout=1.0
                    )

                    digit = dtmf_event.digit
                    logger.info("📞 DTMF received for AI",
                               session_id=rtp_session.session_id,
                               digit=digit,
                               duration_ms=dtmf_event.duration_ms)

                    # Trigger DTMF callback for AI integration
                    if self.on_dtmf:
                        try:
                            self.on_dtmf(digit)
                        except Exception as e:
                            logger.error("Error in DTMF callback",
                                       error=str(e),
                                       digit=digit)

                except asyncio.TimeoutError:
                    # No DTMF - continue monitoring
                    continue

        except asyncio.CancelledError:
            logger.debug("DTMF monitoring cancelled", session_id=rtp_session.session_id)
        except Exception as e:
            logger.error("Error in DTMF monitoring",
                        error=str(e),
                        session_id=rtp_session.session_id)

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
            'ai_is_speaking': self.ai_is_speaking,
            'speech_active': self.speech_active,
        }

        # VAD stats (Hybrid or Legacy)
        if self.use_hybrid_vad and self.hybrid_vad:
            stats['vad'] = self.hybrid_vad.get_stats()
            stats['vad_type'] = 'hybrid'

            # Barge-in stats
            if self.barge_in_handler:
                stats['barge_in'] = self.barge_in_handler.get_stats()
        elif self.vad:
            stats['vad'] = self.vad.get_stats()
            stats['vad_type'] = 'legacy'

        if self.stream:
            stats['stream'] = self.stream.get_stats()

        return stats
