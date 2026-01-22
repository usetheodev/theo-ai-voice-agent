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
from src.ai import WhisperASR, QwenLLM, ConversationManager
from src.ai.kokoro import KokoroTTS
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

        # Initialize Audio Pipeline Config
        audio_config = AudioPipelineConfig(
            codec_law='ulaw',
            vad_energy_threshold_start=self.config.ai.vad_threshold * 1000,  # Convert to RMS
            vad_energy_threshold_end=self.config.ai.vad_threshold * 600,
            vad_silence_duration_ms=500,
            vad_min_speech_duration_ms=self.config.ai.vad_min_speech_duration_ms,
            buffer_sample_rate=8000,
            buffer_target_rate=16000
        )

        # Initialize Whisper ASR
        try:
            whisper_asr = WhisperASR(
                model_path=self.config.ai.asr_model_path,
                language=self.config.ai.asr_language,
                n_threads=self.config.ai.asr_threads
            )
            logger.info('Whisper ASR initialized',
                       model=self.config.ai.asr_model,
                       language=self.config.ai.asr_language,
                       threads=self.config.ai.asr_threads)
        except FileNotFoundError:
            logger.error('Whisper model file not found', path=self.config.ai.asr_model_path)
            logger.error('Download: wget https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin -O models/whisper/ggml-base.bin')
            sys.exit(1)
        except Exception as e:
            logger.error('Failed to initialize Whisper ASR', error=str(e), exc_info=True)
            sys.exit(1)

        # Initialize Qwen LLM
        try:
            logger.info('Initializing Qwen LLM (this may take 30-120 seconds)...')
            qwen_llm = QwenLLM(config=self.config)
            await qwen_llm.initialize()
            logger.info('Qwen LLM initialized',
                       model=self.config.ai.llm_model,
                       max_tokens=self.config.ai.llm_max_tokens)
        except Exception as e:
            logger.error('Failed to initialize Qwen LLM', error=str(e), exc_info=True)
            sys.exit(1)

        # Initialize Conversation Manager
        conversation_manager = ConversationManager(max_history_turns=10)
        logger.info('Conversation Manager initialized')

        # Initialize Kokoro TTS
        try:
            logger.info('Initializing Kokoro TTS...')
            kokoro_tts = KokoroTTS(
                lang_code='p',  # Brazilian Portuguese
                voice=self.config.ai.tts_voice,
                sample_rate=24000  # Kokoro native rate
            )
            logger.info('Kokoro TTS initialized',
                       voice=self.config.ai.tts_voice,
                       sample_rate=24000)
        except Exception as e:
            logger.error('Failed to initialize Kokoro TTS', error=str(e), exc_info=True)
            sys.exit(1)

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

                    # Run Whisper in thread pool (non-blocking) with timeout
                    text = await asyncio.wait_for(
                        asyncio.to_thread(
                            whisper_asr.transcribe_array,
                            audio_float32
                        ),
                        timeout=10.0
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
                            response_text = await qwen_llm.generate_response(
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

        # Function to send TTS audio via RTP
        async def send_tts_audio(session_id: str, tts_audio: np.ndarray, rtp_session):
            """
            Process TTS audio and send via RTP

            Args:
                session_id: Session ID
                tts_audio: Audio from TTS (float32, 24kHz, range [-1, 1])
                rtp_session: RTP session object
            """
            try:
                from src.rtp.packet import RTPHeader
                import time
                import audioop

                # Step 1: Resample 24kHz → 8kHz (telephony rate)
                logger.debug('Resampling TTS audio: 24kHz → 8kHz', session_id=session_id)

                # Convert float32 [-1, 1] → int16
                tts_int16 = (tts_audio * 32767).astype(np.int16)

                # Resample using audioop (simple but effective)
                # audioop.ratecv(fragment, width, nchannels, inrate, outrate, state)
                tts_8khz_bytes, _ = audioop.ratecv(
                    tts_int16.tobytes(),
                    2,  # 2 bytes per sample (16-bit)
                    1,  # mono
                    24000,  # input rate
                    8000,   # output rate
                    None    # no state
                )

                # Step 2: Encode PCM → G.711 μ-law
                logger.debug('Encoding PCM → G.711 μ-law', session_id=session_id)
                g711_data = audioop.lin2ulaw(tts_8khz_bytes, 2)

                # Step 3: Split into RTP packets (160 bytes = 20ms @ 8kHz)
                PACKET_SIZE = 160  # 20ms of audio
                num_packets = (len(g711_data) + PACKET_SIZE - 1) // PACKET_SIZE

                logger.info('Sending TTS audio via RTP',
                           session_id=session_id,
                           duration_s=f"{len(g711_data) / 8000:.2f}",
                           packets=num_packets)

                # Get initial RTP state
                base_timestamp = int(time.time() * 8000) & 0xFFFFFFFF
                sequence_start = rtp_session.packets_sent & 0xFFFF

                # Send packets with proper timing
                for i in range(num_packets):
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

                    # Pace packets (20ms per packet = 50 packets/sec)
                    # This prevents network congestion
                    await asyncio.sleep(0.020)  # 20ms

                logger.info('TTS audio sent successfully',
                           session_id=session_id,
                           packets_sent=num_packets)

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

                            # Set callback with session_id
                            pipeline.on_speech_ready = lambda audio_bytes, sid=session_id: on_speech_ready(sid, audio_bytes)

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
