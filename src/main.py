#!/usr/bin/env python3
"""
AI Voice Agent - Main Entry Point
"""

import asyncio
import signal
import sys
from pathlib import Path

import click
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.config import AppConfig
from src.common.logging import get_logger, configure_logging
from src.common.metrics import start_metrics_server
from src.ai import QwenLLM, ConversationManager
from src.ai.llm_ollama import OllamaLLM
from src.ai import (
    WhisperASR,
    DistilWhisperASR,
    is_distilwhisper_available,
    ParakeetASR,
    is_parakeet_available,
)
from src.ai.asr_sherpa import SherpaONNXASR, SHERPA_ONNX_AVAILABLE
from src.ai.kokoro import KokoroTTS
from src.ai.tts_piper import PiperTTS, is_piper_available
from src.api.metrics_api import MetricsAPIServer

# Logger will be configured after loading config
logger = None


class Application:
    """Main application orchestrator"""

    def __init__(self, config: AppConfig):
        self.config = config
        self.orchestrator = None
        self.sip_server = None
        self.rtp_server = None
        self.event_bus = None
        self.metrics_api_server = None
        self.shutdown_event = asyncio.Event()

    async def start(self):
        """Start the application"""
        global logger

        # Configure logging
        configure_logging(self.config.log_level)
        logger = get_logger('main')

        logger.info('🚀 Starting AI Voice Agent...')

        # Validate config
        errors = self.config.validate()
        if errors:
            for error in errors:
                logger.error('Configuration error', error=error)
            sys.exit(1)

        logger.info('Configuration valid', config=str(self.config))

        # Start metrics server
        start_metrics_server(port=self.config.metrics_port)
        logger.info('Metrics server started', port=self.config.metrics_port)

        # Import modules
        from src.sip import SIPServer, SIPServerConfig
        from src.rtp import RTPServer, RTPServerConfig
        from src.orchestrator.events import EventBus
        from src.audio import AudioPipeline, AudioPipelineConfig

        # Initialize EventBus
        event_bus = EventBus()

        # Initialize RTP Server
        rtp_config = RTPServerConfig(
            port_start=self.config.rtp.port_start,
            port_end=self.config.rtp.port_end,
            listen_addr="0.0.0.0",
            media_timeout=self.config.rtp.rtp_timeout_ms / 1000.0,
            ip_validation_enabled=getattr(self.config.rtp, 'ip_validation_enabled', True),
            jitter_buffer_initial_ms=getattr(self.config.rtp, 'jitter_buffer_initial_ms', 60),
            jitter_buffer_min_ms=getattr(self.config.rtp, 'jitter_buffer_min_ms', 20),
            jitter_buffer_max_ms=getattr(self.config.rtp, 'jitter_buffer_max_ms', 300),
            jitter_buffer_adaptation_rate=getattr(self.config.rtp, 'jitter_buffer_adaptation_rate', 0.1)
        )
        rtp_server = RTPServer(config=rtp_config, event_bus=event_bus)
        await rtp_server.start()

        # Start Metrics API Server
        metrics_api_server = MetricsAPIServer(rtp_server=rtp_server, host='0.0.0.0', port=8001)
        await metrics_api_server.start()
        self.metrics_api_server = metrics_api_server

        # Initialize Audio Pipeline Config (with Full-Duplex Hybrid VAD)
        import os
        audio_config = AudioPipelineConfig(
            codec_law='ulaw',
            # Legacy VAD (fallback)
            vad_energy_threshold_start=self.config.ai.vad_threshold * 1000,
            vad_energy_threshold_end=self.config.ai.vad_threshold * 600,
            vad_silence_duration_ms=500,
            vad_min_speech_duration_ms=self.config.ai.vad_min_speech_duration_ms,
            vad_webrtc_aggressiveness=int(os.getenv('VAD_WEBRTC_AGGRESSIVENESS', '2')),
            # Hybrid VAD (Full-Duplex)
            use_hybrid_vad=os.getenv('VAD_ENABLED', 'true').lower() == 'true',
            vad_enable_aec=os.getenv('VAD_ENABLE_AEC', 'true').lower() == 'true',
            vad_enable_silero=os.getenv('VAD_ENABLE_SILERO', 'true').lower() == 'true',
            vad_energy_threshold_db=float(os.getenv('VAD_ENERGY_THRESHOLD_DB', '-40.0')),
            vad_silero_threshold=float(os.getenv('VAD_SILERO_THRESHOLD', '0.5')),
            vad_grace_period_ms=int(os.getenv('VAD_GRACE_PERIOD_MS', '200')),
            vad_min_silence_duration_ms=int(os.getenv('VAD_MIN_SILENCE_DURATION_MS', '100')),
            # Barge-in
            barge_in_enabled=os.getenv('BARGE_IN_ENABLED', 'true').lower() == 'true',
            barge_in_min_confidence=float(os.getenv('BARGE_IN_MIN_CONFIDENCE', '0.7')),
            # Buffer
            buffer_sample_rate=8000,
            buffer_target_rate=16000
        )

        # Initialize ASR (based on ASR_PROVIDER env var)
        import os
        asr_provider = os.getenv('ASR_PROVIDER', 'distil-whisper').lower()

        try:
            if asr_provider == 'distil-whisper':
                if not is_distilwhisper_available():
                    raise RuntimeError("Distil-Whisper selected but faster-whisper not installed. Install with: pip install faster-whisper")

                whisper_asr = DistilWhisperASR(
                    model=os.getenv('DISTIL_WHISPER_MODEL', 'distil-large-v3'),
                    language=os.getenv('DISTIL_WHISPER_LANGUAGE', 'pt'),
                    device=os.getenv('DISTIL_WHISPER_DEVICE', 'cpu'),
                    compute_type=os.getenv('DISTIL_WHISPER_COMPUTE_TYPE', 'int8'),
                )
                logger.info('✅ Distil-Whisper ASR initialized (6x faster than Whisper)',
                           model=os.getenv('DISTIL_WHISPER_MODEL'),
                           language=os.getenv('DISTIL_WHISPER_LANGUAGE'))

            elif asr_provider == 'parakeet':
                if not is_parakeet_available():
                    raise RuntimeError("Parakeet selected but nemo_toolkit not installed. Install with: pip install nemo_toolkit[asr]")

                whisper_asr = ParakeetASR(
                    model=os.getenv('PARAKEET_MODEL', 'nvidia/parakeet-tdt-0.6b-v3'),
                    device=os.getenv('PARAKEET_DEVICE', 'auto'),
                )
                logger.info('✅ Parakeet TDT ASR initialized (sub-25ms GPU, 6.32% WER)',
                           model=os.getenv('PARAKEET_MODEL'))

            elif asr_provider == 'sherpa-onnx':
                if not SHERPA_ONNX_AVAILABLE:
                    raise RuntimeError("Sherpa-ONNX selected but sherpa-onnx not installed. Install with: pip install sherpa-onnx")

                whisper_asr = SherpaONNXASR(
                    model_dir=os.getenv('SHERPA_ONNX_MODEL_DIR', 'models/sherpa-onnx/sherpa-onnx-whisper-large-v3'),
                    language=os.getenv('SHERPA_ONNX_LANGUAGE', 'pt'),
                    num_threads=int(os.getenv('SHERPA_ONNX_NUM_THREADS', '4')),
                )
                logger.info('✅ Sherpa-ONNX ASR initialized (10x faster, RTF < 0.3)',
                           model_dir=os.getenv('SHERPA_ONNX_MODEL_DIR', 'models/sherpa-onnx/sherpa-onnx-whisper-large-v3'),
                           language=os.getenv('SHERPA_ONNX_LANGUAGE'))

            elif asr_provider == 'whisper':
                whisper_asr = WhisperASR(
                    model_path=self.config.ai.asr_model_path,
                    language=self.config.ai.asr_language,
                    n_threads=self.config.ai.asr_threads
                )
                logger.info('Whisper ASR initialized (legacy)',
                           model=self.config.ai.asr_model,
                           language=self.config.ai.asr_language)

            else:
                logger.error(f'Unknown ASR_PROVIDER: {asr_provider}')
                logger.error('Valid options: sherpa-onnx, whisper, distil-whisper, parakeet')
                sys.exit(1)

        except FileNotFoundError:
            logger.error('Whisper model file not found', path=self.config.ai.asr_model_path)
            logger.error('Download: wget https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin -O models/whisper/ggml-base.bin')
            sys.exit(1)
        except Exception as e:
            logger.error('Failed to initialize ASR', provider=asr_provider, error=str(e), exc_info=True)
            sys.exit(1)

        # Initialize LLM (Ollama or Qwen based on LLM_PROVIDER)
        llm_provider = os.getenv('LLM_PROVIDER', 'qwen').lower()

        try:
            if llm_provider == 'ollama':
                logger.info('Initializing Ollama LLM (fast startup <10s)...')
                llm = OllamaLLM(config=self.config)
                await llm.initialize()
                logger.info('✅ Ollama LLM initialized',
                           host=os.getenv('OLLAMA_HOST', 'http://ollama:11434'),
                           model=os.getenv('OLLAMA_MODEL', 'llama3.2:1b'),
                           max_tokens=self.config.ai.llm_max_tokens)
            else:
                # Fallback to QwenLLM (legacy TinyLlama)
                logger.info('Initializing Qwen LLM (this may take 30-120 seconds)...')
                llm = QwenLLM(config=self.config)
                await llm.initialize()
                logger.info('Qwen LLM initialized',
                           model=self.config.ai.llm_model,
                           max_tokens=self.config.ai.llm_max_tokens)
        except Exception as e:
            logger.error('Failed to initialize LLM', provider=llm_provider, error=str(e), exc_info=True)
            sys.exit(1)

        # Initialize Conversation Manager
        conversation_manager = ConversationManager(max_history_turns=10)
        logger.info('Conversation Manager initialized')

        # Initialize TTS (Piper or Kokoro)
        tts_provider = os.getenv('TTS_PROVIDER', 'kokoro').lower()

        if tts_provider == 'piper':
            if not is_piper_available():
                logger.error('Piper TTS selected but not installed. Install: pip install piper-tts')
                sys.exit(1)

            try:
                logger.info('Initializing Piper TTS (5x faster, CPU-only)...')
                piper_model = os.getenv('PIPER_MODEL', 'pt_BR-faber-medium')
                piper_quality = os.getenv('PIPER_QUALITY', 'medium')
                piper_length_scale = float(os.getenv('PIPER_LENGTH_SCALE', '1.0'))

                tts_engine = PiperTTS(
                    model=piper_model,
                    sample_rate=22050,  # Piper native rate
                    quality=piper_quality,
                )
                tts_sample_rate = 22050
                logger.info('✅ Piper TTS initialized',
                           model=piper_model,
                           quality=piper_quality,
                           sample_rate=22050)
            except Exception as e:
                logger.error('Failed to initialize Piper TTS', error=str(e), exc_info=True)
                sys.exit(1)

        else:  # kokoro (default)
            try:
                logger.info('Initializing Kokoro TTS...')
                tts_engine = KokoroTTS(
                    lang_code='p',  # Brazilian Portuguese
                    voice=self.config.ai.tts_voice,
                    sample_rate=24000  # Kokoro native rate
                )
                tts_sample_rate = 24000
                logger.info('✅ Kokoro TTS initialized',
                           voice=self.config.ai.tts_voice,
                           sample_rate=24000)
            except Exception as e:
                logger.error('Failed to initialize Kokoro TTS', error=str(e), exc_info=True)
                sys.exit(1)

        # Store TTS engine and config
        kokoro_tts = tts_engine  # Keep variable name for compatibility
        self.tts_sample_rate = tts_sample_rate

        # Store audio pipelines (one per call)
        self.audio_pipelines = {}

        # Semaphore for rate limiting transcriptions
        MAX_CONCURRENT_TRANSCRIPTIONS = 10
        transcription_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TRANSCRIPTIONS)

        # Async transcription function
        async def transcribe_audio(session_id: str, audio_bytes: bytes):
            """Async wrapper for Whisper transcription"""
            async with transcription_semaphore:
                try:
                    # Convert bytes → numpy int16 → float32 [-1.0, 1.0]
                    audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
                    audio_float32 = audio_int16.astype(np.float32) / 32768.0

                    # Run ASR in thread pool (non-blocking) with adaptive timeout
                    # Timeout = 3x audio duration or 20s minimum (for first model load)
                    audio_duration = len(audio_float32) / 16000  # seconds
                    timeout_seconds = max(20.0, audio_duration * 3)

                    text = await asyncio.wait_for(
                        asyncio.to_thread(
                            whisper_asr.transcribe_array,
                            audio_float32
                        ),
                        timeout=timeout_seconds
                    )

                    if text:
                        logger.info('Transcription complete',
                                   session_id=session_id,
                                   text=text)

                        # Phase 3: Send to LLM for response generation
                        try:
                            # Add user message to conversation history
                            conversation_manager.add_user_message(session_id, text)

                            # Get conversation history (excluding current message for context)
                            history = conversation_manager.get_history(session_id)
                            # Remove last message (current user text) to pass as separate parameter
                            history_for_llm = history[:-1] if len(history) > 0 else []

                            # Generate LLM response
                            logger.info('Generating LLM response', session_id=session_id)
                            response_text = await llm.generate_response(
                                user_text=text,
                                conversation_history=history_for_llm
                            )

                            logger.info('LLM response generated',
                                       session_id=session_id,
                                       response=response_text)

                            # Add assistant response to history
                            conversation_manager.add_assistant_message(session_id, response_text)

                            # Phase 4: TTS - Convert response to speech and send via RTP
                            try:
                                logger.info('Generating TTS audio', session_id=session_id)

                                # Generate audio (24kHz, float32)
                                tts_audio = await asyncio.to_thread(
                                    kokoro_tts.synthesize,
                                    response_text
                                )

                                if tts_audio is not None:
                                    # Get RTP session
                                    if session_id in rtp_server.sessions:
                                        rtp_session = rtp_server.sessions[session_id]

                                        # Process and send TTS audio
                                        await send_tts_audio(session_id, tts_audio, rtp_session)
                                    else:
                                        logger.warning('RTP session not found for TTS',
                                                     session_id=session_id)
                                else:
                                    logger.warning('TTS returned no audio', session_id=session_id)

                            except Exception as e:
                                logger.error('TTS generation failed',
                                           session_id=session_id,
                                           error=str(e),
                                           exc_info=True)

                        except Exception as e:
                            logger.error('LLM generation failed',
                                        session_id=session_id,
                                        error=str(e),
                                        exc_info=True)
                    else:
                        logger.warning('Transcription returned empty',
                                      session_id=session_id)

                except asyncio.TimeoutError:
                    duration = len(audio_bytes) / 2 / 16000
                    logger.error('Transcription timeout',
                                session_id=session_id,
                                duration_s=f"{duration:.2f}")
                except Exception as e:
                    logger.error('Transcription error',
                                session_id=session_id,
                                error=str(e),
                                exc_info=True)

        # TTS cancellation flags (per session)
        tts_cancellation_flags = {}

        # Function to send TTS audio via RTP (with barge-in support)
        async def send_tts_audio(session_id: str, tts_audio: np.ndarray, rtp_session):
            """
            Process TTS audio and send via RTP (with barge-in cancellation)

            Args:
                session_id: Session ID
                tts_audio: Audio from TTS (float32, 24kHz, range [-1, 1])
                rtp_session: RTP session object
            """
            try:
                from src.rtp.packet import RTPHeader
                import time
                import audioop

                # Reset cancellation flag for this session
                tts_cancellation_flags[session_id] = False

                # Step 1: Resample TTS_RATE → 8kHz (telephony rate)
                logger.debug(f'Resampling TTS audio: {self.tts_sample_rate}Hz → 8kHz', session_id=session_id)

                # Convert float32 [-1, 1] → int16
                tts_int16 = (tts_audio * 32767).astype(np.int16)

                # Resample using audioop
                tts_8khz_bytes, _ = audioop.ratecv(
                    tts_int16.tobytes(),
                    2,  # 2 bytes per sample (16-bit)
                    1,  # mono
                    self.tts_sample_rate,  # input rate (22050 for Piper, 24000 for Kokoro)
                    8000,   # output rate
                    None    # no state
                )

                # Convert to numpy for AEC reference
                tts_8khz_int16 = np.frombuffer(tts_8khz_bytes, dtype=np.int16)
                tts_8khz_float32 = tts_8khz_int16.astype(np.float32) / 32768.0

                # Set AI reference audio for AEC (Acoustic Echo Cancellation)
                if session_id in self.audio_pipelines:
                    pipeline = self.audio_pipelines[session_id]
                    pipeline.set_ai_reference_audio(tts_8khz_float32)
                    pipeline.set_ai_speaking(True)

                # Step 2: Encode PCM → G.711 μ-law
                logger.debug('Encoding PCM → G.711 μ-law', session_id=session_id)
                g711_data = audioop.lin2ulaw(tts_8khz_bytes, 2)

                # Step 3: Split into RTP packets (160 bytes = 20ms @ 8kHz)
                PACKET_SIZE = 160  # 20ms of audio
                num_packets = (len(g711_data) + PACKET_SIZE - 1) // PACKET_SIZE
                audio_duration_ms = (len(g711_data) / 8000) * 1000

                logger.info('Sending TTS audio via RTP',
                           session_id=session_id,
                           duration_s=f"{len(g711_data) / 8000:.2f}",
                           packets=num_packets)

                # Get initial RTP state
                base_timestamp = int(time.time() * 8000) & 0xFFFFFFFF
                sequence_start = rtp_session.packets_sent & 0xFFFF

                # Send packets with proper timing (supports barge-in cancellation)
                packets_sent = 0
                for i in range(num_packets):
                    # Check for barge-in cancellation
                    if tts_cancellation_flags.get(session_id, False):
                        logger.warning('🔴 TTS cancelled due to barge-in',
                                     session_id=session_id,
                                     packets_sent=packets_sent,
                                     packets_cancelled=num_packets - packets_sent)
                        break

                    start_idx = i * PACKET_SIZE
                    end_idx = min(start_idx + PACKET_SIZE, len(g711_data))
                    payload = g711_data[start_idx:end_idx]

                    # Pad last packet if needed
                    if len(payload) < PACKET_SIZE:
                        payload = payload + bytes([0xFF] * (PACKET_SIZE - len(payload)))

                    # Create RTP header
                    header = RTPHeader(
                        version=2,
                        padding=False,
                        extension=False,
                        marker=(i == 0),  # Mark first packet
                        payload_type=0,  # PCMU
                        sequence_number=(sequence_start + i) & 0xFFFF,
                        timestamp=(base_timestamp + i * 160) & 0xFFFFFFFF,
                        ssrc=0x12345678  # Our SSRC
                    )

                    # Send RTP packet
                    await rtp_session.send_rtp(header, payload)
                    packets_sent += 1

                    # Pace packets (20ms per packet = 50 packets/sec)
                    await asyncio.sleep(0.020)

                # Mark AI as stopped speaking
                if session_id in self.audio_pipelines:
                    pipeline = self.audio_pipelines[session_id]
                    pipeline.set_ai_speaking(False, audio_duration_ms)
                    pipeline.set_ai_reference_audio(None)  # Clear reference

                if packets_sent == num_packets:
                    logger.info('TTS audio sent successfully',
                               session_id=session_id,
                               packets_sent=packets_sent)
                else:
                    logger.info('TTS audio partially sent (barge-in)',
                               session_id=session_id,
                               packets_sent=packets_sent,
                               total_packets=num_packets)

            except Exception as e:
                logger.error('Failed to send TTS audio',
                           session_id=session_id,
                           error=str(e),
                           exc_info=True)

        # Callback when speech is detected
        def on_speech_ready(session_id: str, audio_bytes: bytes):
            duration = len(audio_bytes) / 2 / 16000  # 16-bit samples at 16kHz
            logger.info('Speech ready for transcription',
                       session_id=session_id,
                       size_bytes=len(audio_bytes),
                       duration_s=f"{duration:.2f}")

            # Schedule async transcription (non-blocking)
            asyncio.create_task(transcribe_audio(session_id, audio_bytes))

        # Barge-in callback (cancel TTS when user interrupts)
        def on_barge_in_detected(event, session_id: str):
            """Handle barge-in event (user interrupted AI)"""
            logger.warning(
                "🔴 Barge-in detected - cancelling TTS for session %s (event_id=%d)",
                session_id,
                event.event_id
            )
            # Set cancellation flag to stop TTS transmission
            tts_cancellation_flags[session_id] = True

        # Monitor RTP sessions and start audio pipelines
        async def monitor_rtp_sessions():
            """Monitor RTP sessions and start audio pipelines automatically"""
            while True:
                try:
                    await asyncio.sleep(2)  # Check every 2 seconds

                    # Check for new sessions
                    for session_id, rtp_session in list(rtp_server.sessions.items()):
                        # Start audio pipeline if not already running
                        if session_id not in self.audio_pipelines:
                            logger.info('🚀 Starting audio pipeline for session', session_id=session_id)

                            # Create pipeline for this session
                            pipeline = AudioPipeline(config=audio_config)

                            # Set callbacks with session_id
                            pipeline.on_speech_ready = lambda audio_bytes, sid=session_id: on_speech_ready(sid, audio_bytes)

                            # Set barge-in callback (with closure to capture session_id)
                            pipeline.on_barge_in_detected = lambda event, sid=session_id: on_barge_in_detected(event, sid)

                            # Store pipeline
                            self.audio_pipelines[session_id] = pipeline

                            # Start processing in background
                            asyncio.create_task(pipeline.process_call(rtp_session))

                    # Clean up ended sessions
                    for session_id in list(self.audio_pipelines.keys()):
                        if session_id not in rtp_server.sessions:
                            logger.info('🛑 Stopping audio pipeline for ended session', session_id=session_id)
                            pipeline = self.audio_pipelines.pop(session_id)
                            await pipeline.stop()

                            # Clear conversation history for ended session
                            conversation_manager.clear_session(session_id)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error('Error in RTP session monitor', error=str(e))

        # Start session monitor
        self.session_monitor = asyncio.create_task(monitor_rtp_sessions())

        # Initialize SIP Server
        sip_config = SIPServerConfig(
            host=self.config.sip.host,
            port=self.config.sip.port,
            realm=self.config.sip.realm,
            external_ip=getattr(self.config.sip, 'external_ip', None),
            codecs=getattr(self.config.sip, 'codecs', ['PCMU', 'PCMA', 'opus']),
            rtp_port_start=self.config.rtp.port_start,
            rtp_port_end=self.config.rtp.port_end,
            max_concurrent_calls=getattr(self.config.sip, 'max_concurrent_calls', 100),
            auth_enabled=getattr(self.config.sip, 'auth_enabled', True),
            trunks=getattr(self.config.sip, 'trunks', []),
            ip_whitelist=getattr(self.config.sip, 'ip_whitelist', []),
            ip_blacklist=getattr(self.config.sip, 'ip_blacklist', []),
            rate_limit=getattr(self.config.sip, 'rate_limit', None)
        )

        sip_server = SIPServer(config=sip_config, event_bus=event_bus, rtp_server=rtp_server)
        await sip_server.start()

        # Store references for cleanup
        self.sip_server = sip_server
        self.rtp_server = rtp_server
        self.event_bus = event_bus
        self.llm = llm  # Store LLM for cleanup

        # TODO: Initialize RTP Server and AI Pipeline when ready
        # rtp_server = RTPServer(config=self.config.rtp, event_bus=event_bus)
        # ai_pipeline = Voice2VoicePipeline(config=self.config.ai, event_bus=event_bus)

        # self.orchestrator = CallOrchestrator(
        #     sip_server=sip_server,
        #     rtp_server=rtp_server,
        #     ai_pipeline=ai_pipeline,
        #     event_bus=event_bus
        # )

        # await self.orchestrator.start()

        logger.info('✅ AI Voice Agent running')
        logger.info('SIP listening', host=self.config.sip.host, port=self.config.sip.port)
        logger.info('Metrics available', url=f'http://localhost:{self.config.metrics_port}/metrics')

        # Wait for shutdown signal
        await self.shutdown_event.wait()

    async def stop(self):
        """Stop the application gracefully"""
        global logger
        if logger:
            logger.info('🛑 Shutting down AI Voice Agent...')

        # Stop session monitor
        if hasattr(self, 'session_monitor'):
            self.session_monitor.cancel()
            try:
                await self.session_monitor
            except asyncio.CancelledError:
                pass

        # Stop all audio pipelines
        if hasattr(self, 'audio_pipelines'):
            for session_id, pipeline in list(self.audio_pipelines.items()):
                logger.info('Stopping audio pipeline', session_id=session_id)
                await pipeline.stop()
            self.audio_pipelines.clear()

        # Cleanup LLM
        if hasattr(self, 'llm') and self.llm:
            logger.info('Shutting down LLM')
            await self.llm.shutdown()

        if self.sip_server:
            await self.sip_server.stop()

        if self.rtp_server:
            await self.rtp_server.stop()

        if self.metrics_api_server:
            await self.metrics_api_server.stop()

        if self.orchestrator:
            await self.orchestrator.stop()

        if logger:
            logger.info('✅ Shutdown complete')

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals (SIGINT, SIGTERM)"""
        logger.info('Shutdown signal received', signal=signum)
        self.shutdown_event.set()


@click.command()
@click.option(
    '--config',
    '-c',
    type=click.Path(exists=True),
    default='config/default.yaml',
    help='Path to configuration file'
)
@click.option(
    '--log-level',
    '-l',
    type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR']),
    default=None,
    help='Override log level from config'
)
def cli(config: str, log_level: str):
    """
    AI Voice Agent - Modular SIP/RTP voice system with AI

    Examples:

        # Use default config
        python src/main.py

        # Use custom config
        python src/main.py --config config/production.yaml

        # Override log level
        python src/main.py --log-level DEBUG
    """
    # Load configuration
    app_config = AppConfig.from_yaml(config)

    # Override log level if provided
    if log_level:
        app_config.log_level = log_level

    # Create application
    app = Application(app_config)

    # Setup signal handlers
    signal.signal(signal.SIGINT, app.handle_shutdown)
    signal.signal(signal.SIGTERM, app.handle_shutdown)

    # Run
    try:
        asyncio.run(app.start())
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(app.stop())


if __name__ == '__main__':
    cli()
