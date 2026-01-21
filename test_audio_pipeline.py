#!/usr/bin/env python3
"""
Test Audio Pipeline Integration with RTP

This script tests the audio pipeline by:
1. Creating a mock RTP session (or using real one)
2. Processing audio through VAD, Buffer, Codec
3. Logging when speech is detected
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.common.logging import configure_logging, get_logger
from src.audio import AudioPipeline, AudioPipelineConfig
from src.rtp import RTPServer, RTPServerConfig
from src.orchestrator.events import EventBus

configure_logging('DEBUG')
logger = get_logger('test')


async def test_audio_pipeline():
    """Test audio pipeline with RTP server"""

    logger.info("🧪 Starting Audio Pipeline Test")

    # Create event bus
    event_bus = EventBus()

    # Create RTP server
    rtp_config = RTPServerConfig(
        port_start=10000,
        port_end=20000,
        listen_addr="0.0.0.0"
    )
    rtp_server = RTPServer(config=rtp_config, event_bus=event_bus)
    await rtp_server.start()

    # Create audio pipeline
    audio_config = AudioPipelineConfig(
        codec_law='ulaw',
        vad_energy_threshold_start=500.0,
        vad_energy_threshold_end=300.0,
        vad_silence_duration_ms=500,
        vad_min_speech_duration_ms=300
    )
    audio_pipeline = AudioPipeline(config=audio_config)

    # Callback when speech is ready
    def on_speech_ready(audio_bytes: bytes):
        duration = len(audio_bytes) / 2 / 16000  # 16-bit samples at 16kHz
        logger.info(f"🎤 SPEECH READY FOR AI PROCESSING!",
                   size_bytes=len(audio_bytes),
                   duration_s=f"{duration:.2f}")

        # Here you would call: whisper.transcribe(audio_bytes)
        logger.info("📝 [Next step: Send to Whisper for transcription]")

    audio_pipeline.on_speech_ready = on_speech_ready

    logger.info("✅ Audio pipeline configured")
    logger.info("📞 Waiting for incoming call...")
    logger.info("💡 Make a call to extension 100 and speak into the phone")

    # Wait for a call to be established
    # In real implementation, this would be triggered by SIP INVITE

    # For now, just wait and monitor RTP sessions
    try:
        while True:
            await asyncio.sleep(5)

            # Check if we have any active sessions
            if rtp_server.sessions:
                for session_id, rtp_session in rtp_server.sessions.items():
                    logger.info("📊 Active RTP session",
                               session_id=session_id,
                               packets_rx=rtp_session.packets_received)

                    # If we have packets but no pipeline running, start it
                    if rtp_session.packets_received > 0 and not audio_pipeline.running:
                        logger.info("🚀 Starting audio processing for session", session_id=session_id)
                        asyncio.create_task(audio_pipeline.process_call(rtp_session))
            else:
                logger.debug("⏳ No active RTP sessions yet")

    except KeyboardInterrupt:
        logger.info("⚠️  Test interrupted by user")
    finally:
        # Cleanup
        await audio_pipeline.stop()
        await rtp_server.stop()
        logger.info("✅ Test completed")


if __name__ == '__main__':
    try:
        asyncio.run(test_audio_pipeline())
    except KeyboardInterrupt:
        pass
