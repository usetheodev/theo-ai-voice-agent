"""
RTP Server for receiving and sending audio packets - REFACTORED v2.0

Major Changes from v1.0:
- ✅ Per-call sessions (Dict[call_id, CallSession]) - no more global state
- ✅ Echo filtering (SSRC tracking inbound vs outbound)
- ✅ Security hardening (IP whitelist, endpoint locking)
- ✅ Session cleanup (automatic timeout after 5min idle)
- ✅ call_id includes SSRC (prevents collision in NAT scenarios)

Breaking Changes:
- VAD.process_frame() now requires call_id as first argument
- Audio pipeline (buffer, VAD, builder) is per-call, not global
- Multiple simultaneous calls fully supported

Pattern based on:
- Asterisk-AI-Voice-Agent (production-ready multi-call architecture)
- Pipecat AI (voice agent best practices)
- RFC 3550 (RTP specification)
"""

import asyncio
import socket
import logging
import time
import struct
import numpy as np
from typing import Dict, Any, List, Optional
import sys
from pathlib import Path

# Add parent directory to path to import codec module
sys.path.insert(0, str(Path(__file__).parent.parent))

from rtp.session import CallSession
from codec import RTPParser, G711Codec, RTPBuilder
from audio.buffer import AudioBuffer
from audio.vad import VoiceActivityDetector
from audio.resampling import resample_audio
from asr.whisper import WhisperASR
from llm.phi3 import Phi3LLM
from tts.kokoro import KokoroTTS


class RTPServer:
    """
    UDP server for handling RTP audio streams with G.711 decoding.

    Version 2.0 - Multi-call capable with per-session state isolation.

    Features:
    - Multiple simultaneous calls (per-call sessions)
    - Echo filtering (SSRC tracking)
    - Security hardening (IP whitelist)
    - Automatic session cleanup (prevents memory leak)
    - Full-duplex ready (echo prevention via SSRC + VAD muting)

    Architecture:
        sessions: Dict[call_id, CallSession]
            ├── call_id format: "IP:PORT:SSRC"
            └── Each CallSession contains:
                ├── RTP state (socket, SSRCs, sequence, timestamp)
                ├── Audio pipeline (buffer, VAD, RTP builder)
                └── Call control (muting, stats)

    Thread Safety:
        - Single-threaded asyncio event loop (no locking needed)
        - Each session accessed only by its own async task
    """

    def __init__(self,
                 host: str = '0.0.0.0',
                 port: int = 5080,
                 config: Dict[str, Any] = None,
                 allowed_asterisk_ips: Optional[List[str]] = None):
        """
        Initialize RTP server.

        Args:
            host: Host to bind to
            port: Port to bind to
            config: Configuration dictionary
            allowed_asterisk_ips: Whitelist of Asterisk IPs (security)
                                 Default: ['127.0.0.1', '::1', '172.20.0.10']
        """
        self.host = host
        self.port = port
        self.config = config or {}
        self.logger = logging.getLogger("ai-voice-agent.rtp")

        # Security: IP whitelist (from config or default)
        if allowed_asterisk_ips is None:
            # Try to load from config, else use defaults
            rtp_security_config = self.config.get('rtp_security', {})
            allowed_asterisk_ips = rtp_security_config.get('allowed_asterisk_ips',
                                                          ['127.20.0.1', '::1', '172.20.0.10', '172.20.0.30'])
        self.allowed_ips = set(allowed_asterisk_ips)
        self.logger.info(f"🔒 IP Whitelist: {self.allowed_ips}")

        # Main UDP socket (shared across all calls)
        self.sock = None

        # Per-call sessions (NEW - replaces global state)
        self.sessions: Dict[str, CallSession] = {}

        # Shared components (reused across calls)
        self.rtp_parser = RTPParser()
        self.codec = G711Codec(law='alaw')  # Match WebRTC endpoint codec

        # AI models (shared - expensive to initialize per-call)
        self.asr = None
        self.llm = None
        self.tts = None

        # Background tasks
        self._cleanup_task = None
        self._running = False

    async def start(self):
        """Start the RTP server and background tasks."""
        try:
            # Create UDP socket
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # Allow immediate restart after crashes
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Set large buffer size to prevent packet loss (both RX and TX)
            buffer_size = self.config.get('rtp', {}).get('buffer_size', 4 * 1024 * 1024)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_size)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buffer_size)

            # Bind to address
            self.sock.bind((self.host, self.port))
            self.sock.setblocking(False)

            self.logger.info(f"✅ RTP Server started on {self.host}:{self.port}")
            self.logger.info(f"   Buffer size: {buffer_size / 1024 / 1024:.1f}MB")

            # Initialize AI models (shared across calls)
            self._initialize_ai_models()

            # Start background tasks
            self._running = True
            asyncio.create_task(self._receive_loop())
            asyncio.create_task(self._session_cleanup_task())

            self.logger.info("✅ RTP Server fully initialized (multi-call ready)")

        except Exception as e:
            self.logger.error(f"Failed to start RTP server: {e}")
            raise

    async def stop(self):
        """Stop the RTP server and cleanup all sessions."""
        self.logger.info("⏹️  Stopping RTP Server...")
        self._running = False

        # Cleanup all active sessions
        for call_id in list(self.sessions.keys()):
            await self.cleanup_session(call_id)

        # Close main socket
        if self.sock:
            self.sock.close()

        self.logger.info("✅ RTP Server stopped")

    async def _receive_loop(self):
        """Main loop for receiving RTP packets (all calls)."""
        loop = asyncio.get_event_loop()

        self.logger.info("📡 RTP receive loop started")

        while self._running:
            try:
                # Receive packet (non-blocking)
                data, addr = await loop.sock_recvfrom(self.sock, 2048)

                if not data:
                    continue

                # Security: Whitelist check (reject packets from unknown IPs)
                if addr[0] not in self.allowed_ips:
                    self.logger.warning(f"🚨 RTP packet rejected from {addr[0]} (not whitelisted)")
                    continue

                # Parse RTP header to extract SSRC
                if len(data) < 12:
                    continue  # Invalid RTP packet

                version = data[0] >> 6
                if version != 2:
                    continue  # Not RTP v2

                ssrc = struct.unpack("!I", data[8:12])[0]

                # DEBUG: Log every packet source
                self.logger.info(f"🔍 RTP packet from {addr[0]}:{addr[1]} SSRC={ssrc:#010x} len={len(data)}")

                # Generate call_id (unique per source)
                call_id = CallSession.generate_call_id(addr[0], addr[1], ssrc)

                # Get or create session
                session = self.sessions.get(call_id)
                if session is None:
                    session = await self._create_session(call_id, addr, ssrc)
                    if session is None:
                        continue  # Failed to create session

                # Process RTP packet for this session
                await self._process_rtp_packet(session, data, addr)

            except Exception as e:
                self.logger.error(f"Error in receive loop: {e}", exc_info=True)
                await asyncio.sleep(0.1)

    async def _create_session(self, call_id: str, addr: tuple, ssrc: int) -> Optional[CallSession]:
        """
        Create new CallSession for incoming call.

        Args:
            call_id: Unique call identifier (IP:PORT:SSRC)
            addr: Remote (IP, port) tuple
            ssrc: Caller's SSRC (inbound)

        Returns:
            CallSession instance or None on failure
        """
        try:
            self.logger.info(f"📞 New call: {call_id}")

            # CRITICAL FIX: Asterisk allocates a DYNAMIC port from the RTP range (10000-10100)
            # for each ExternalMedia channel. We must send RTP back to the SOURCE PORT
            # of received packets, NOT to a fixed port like 5080.
            #
            # The source port (addr[1]) is the UNICASTRTP_LOCAL_PORT that Asterisk
            # is actually listening on for this specific call.
            symmetric_rtp_addr = (addr[0], addr[1])  # Use source IP and source PORT

            # Create session
            session = CallSession(
                call_id=call_id,
                socket=self.sock,  # Shared socket (all calls use same)
                remote_addr=symmetric_rtp_addr  # Use symmetric RTP address
            )

            # Set inbound SSRC
            session.inbound_ssrc = ssrc

            # Generate outbound SSRC (different for echo filtering)
            session.generate_outbound_ssrc()

            self.logger.info(
                f"   Inbound SSRC:  {session.inbound_ssrc:#010x}"
            )
            self.logger.info(
                f"   Outbound SSRC: {session.outbound_ssrc:#010x} (echo filter)"
            )

            # Initialize per-call audio pipeline
            session.audio_buffer = AudioBuffer(
                sample_rate=8000,
                target_rate=16000,
                channels=1,
                max_duration_seconds=30.0
            )

            # VAD with per-call callbacks - WebRTC ONLY (no energy fallback)
            # FINAL SOLUTION: Use only ML-based WebRTC VAD for server-agnostic speech detection
            # Energy thresholds set extremely high to effectively disable energy-based detection
            vad_config = self.config.get('vad', {})
            session.vad = VoiceActivityDetector(
                sample_rate=8000,
                frame_duration_ms=20,
                energy_threshold_start=vad_config.get('energy_threshold_start', 999999.0),  # Effectively disabled
                energy_threshold_end=vad_config.get('energy_threshold_end', 999999.0),  # Effectively disabled
                silence_duration_ms=vad_config.get('silence_duration_ms', 300),  # Fast response (WebRTC decides)
                min_speech_duration_ms=vad_config.get('min_speech_duration_ms', 150),  # Accept short utterances
                webrtc_aggressiveness=vad_config.get('webrtc_aggressiveness', 3),  # Maximum robustness to noise
                on_speech_start=lambda: self._on_speech_start(call_id),
                on_speech_end=lambda: self._on_speech_end(call_id)
            )

            # RTP builder for sending
            session.rtp_builder = RTPBuilder()

            # ============================================
            # Phase 1: Initialize Audio Quality Components
            # ============================================

            # 1. RNNoise Filter (Noise Reduction)
            audio_pipeline_config = self.config.get('audio_pipeline', {})
            if audio_pipeline_config.get('rnnoise_enabled', True):
                try:
                    from audio.filters import RNNoiseFilter

                    session.noise_filter = RNNoiseFilter(
                        resampler_quality=audio_pipeline_config.get('rnnoise_quality', 'QQ')
                    )
                    await session.noise_filter.start(sample_rate=8000)

                    self.logger.info(f"   ✅ RNNoise filter initialized")

                except Exception as e:
                    self.logger.warning(f"   ⚠️  RNNoise filter failed to initialize: {e}")
                    session.noise_filter = None

            # 2. Silero VAD (ML-based)
            if audio_pipeline_config.get('silero_vad_enabled', True):
                try:
                    from audio.vad_silero import SileroVAD

                    session.silero_vad = SileroVAD(
                        sample_rate=8000,
                        confidence_threshold=audio_pipeline_config.get('silero_confidence', 0.5),
                        start_frames=audio_pipeline_config.get('silero_start_frames', 3),
                        stop_frames=audio_pipeline_config.get('silero_stop_frames', 10),
                        min_speech_frames=audio_pipeline_config.get('silero_min_speech_frames', 5),
                        model_path=audio_pipeline_config.get('silero_model_path'),
                        on_speech_start=lambda: self._on_speech_start_silero(call_id),
                        on_speech_end=lambda: self._on_speech_end_silero(call_id)
                    )

                    self.logger.info(
                        f"   ✅ Silero VAD initialized "
                        f"(threshold={audio_pipeline_config.get('silero_confidence', 0.5):.2f})"
                    )

                except Exception as e:
                    self.logger.warning(f"   ⚠️  Silero VAD failed to initialize: {e}")
                    session.silero_vad = None

            # 3. SOXR Resampler (High-Quality)
            if audio_pipeline_config.get('soxr_enabled', True):
                try:
                    from audio.resamplers import SOXRStreamResampler

                    session.soxr_resampler = SOXRStreamResampler(
                        quality=audio_pipeline_config.get('soxr_quality', 'VHQ')
                    )

                    self.logger.info(
                        f"   ✅ SOXR resampler initialized "
                        f"(quality={audio_pipeline_config.get('soxr_quality', 'VHQ')})"
                    )

                except Exception as e:
                    self.logger.warning(f"   ⚠️  SOXR resampler failed to initialize: {e}")
                    session.soxr_resampler = None

            # Phase 2.1: Initialize Conversational Intelligence Components
            # ============================================================

            # 1. Turn Detection (End-of-Turn Analysis)
            turn_config = self.config.get('turn_detection', {})
            if turn_config.get('enabled', True):
                try:
                    from audio.turn import SimpleTurnAnalyzer

                    session.turn_analyzer = SimpleTurnAnalyzer(
                        sample_rate=8000,
                        pause_duration=turn_config.get('pause_duration', 1.0),
                        min_duration=turn_config.get('min_duration', 0.3)
                    )

                    self.logger.info(
                        f"   ✅ Turn Detection initialized "
                        f"(pause={turn_config.get('pause_duration', 1.0)}s, "
                        f"min={turn_config.get('min_duration', 0.3)}s)"
                    )

                except Exception as e:
                    self.logger.warning(f"   ⚠️  Turn Detection failed to initialize: {e}")
                    session.turn_analyzer = None

            # 2. Smart Barge-in (Interruption Strategy)
            interruption_config = self.config.get('interruption', {})
            if interruption_config.get('enabled', True):
                try:
                    from audio.interruptions import MinDurationInterruptionStrategy

                    session.interruption_strategy = MinDurationInterruptionStrategy(
                        min_duration=interruption_config.get('min_duration', 0.8)
                    )

                    self.logger.info(
                        f"   ✅ Smart Barge-in initialized "
                        f"(min={interruption_config.get('min_duration', 0.8)}s)"
                    )

                except Exception as e:
                    self.logger.warning(f"   ⚠️  Smart Barge-in failed to initialize: {e}")
                    session.interruption_strategy = None

            # Add to sessions dict
            self.sessions[call_id] = session

            self.logger.info(f"✅ Session created: {call_id} (total active: {len(self.sessions)})")

            return session

        except Exception as e:
            self.logger.error(f"Failed to create session {call_id}: {e}", exc_info=True)
            return None

    async def _process_rtp_packet(self, session: CallSession, data: bytes, addr: tuple):
        """
        Process received RTP packet for specific session.

        Args:
            session: CallSession instance
            data: Raw RTP packet bytes
            addr: Source (IP, port) tuple
        """
        try:
            # Update activity timestamp
            session.update_activity()
            session.packets_received += 1
            session.bytes_received += len(data)

            # Parse RTP packet
            rtp_packet = self.rtp_parser.parse(data)
            if not rtp_packet:
                return

            # CRITICAL: Echo filtering
            if session.is_echo_packet(rtp_packet.header.ssrc):
                session.echo_packets_filtered += 1
                if session.echo_packets_filtered <= 5:  # Log first 5 only
                    self.logger.debug(
                        f"🔇 Echo packet filtered [{session.call_id}] "
                        f"(SSRC={rtp_packet.header.ssrc:#010x}, count={session.echo_packets_filtered})"
                    )
                return  # DROP - don't process echo

            # Decode G.711 ulaw to PCM
            pcm_data = self.codec.decode(rtp_packet.payload)
            if not pcm_data:
                return

            # Process through per-call audio pipeline
            await self._process_audio_frame(session, pcm_data)

        except Exception as e:
            self.logger.error(f"Error processing RTP packet [{session.call_id}]: {e}", exc_info=True)

    async def _process_audio_frame(self, session: CallSession, pcm_data: bytes):
        """
        Process audio frame through VAD and buffer (per-call).

        Args:
            session: CallSession instance
            pcm_data: PCM audio data (16-bit signed, 8kHz)
        """
        if not session.vad or not session.audio_buffer:
            return

        # ============================================
        # Phase 1: Apply RNNoise Filter (if enabled)
        # ============================================
        filtered_audio = pcm_data

        if session.noise_filter and session.noise_filter._rnnoise_ready:
            filtered_audio = await session.noise_filter.filter(pcm_data)

            if len(filtered_audio) == 0:
                # Still buffering (RNNoise needs 480 samples @ 48kHz internally)
                return

        # Use filtered audio for downstream processing
        audio_to_process = filtered_audio

        # Full-duplex (Phase 4): VAD always active (no muting)
        # Echo filtering via SSRC tracking prevents agent audio from triggering VAD

        # Run legacy VAD on frame (WebRTC + Energy)
        is_speech_legacy = session.vad.process_frame(audio_to_process)

        # ============================================
        # Phase 1: Run Silero VAD (parallel detection)
        # ============================================
        is_speech_silero = False
        if session.silero_vad and session.silero_vad.model:
            is_speech_silero = session.silero_vad.process_frame(audio_to_process)

        # Combine VAD results (logical OR - either method triggers speech)
        is_speech = is_speech_legacy or is_speech_silero

        # ============================================================
        # Phase 2.1: Turn Detection (End-of-Turn Analysis)
        # ============================================================
        if session.turn_analyzer:
            # Append audio to turn analyzer
            turn_state = session.turn_analyzer.append_audio(audio_to_process, is_speech)

            # If turn complete, could trigger ASR here (future optimization)
            # For now, we keep existing VAD-based buffer logic

        # ============================================================
        # Phase 2.1: Smart Barge-in (Interruption Strategy)
        # ============================================================
        # Barge-in Detection (Phase 4 + 2.1 enhancement):
        # Check if user speaking during TTS playback
        if is_speech and session.current_playback_id is not None:
            # Accumulate user audio for interruption strategy
            if session.interruption_strategy:
                await session.interruption_strategy.append_audio(audio_to_process, sample_rate=8000)

        # When VAD detects silence after speech during TTS playback
        elif not is_speech and session.current_playback_id is not None and session.interruption_strategy:
            # User stopped speaking during agent playback
            # Check if this was a REAL interruption (not cough/um)
            should_interrupt = await session.interruption_strategy.should_interrupt()

            if should_interrupt:
                # Real interruption detected!
                self.logger.info(
                    f"🎙️  Smart Barge-in: Real interruption detected! "
                    f"User interrupted TTS [{session.call_id}] "
                    f"(duration={session.interruption_strategy.get_current_duration():.2f}s)"
                )

                # Increment barge-in counter (metrics)
                session.barge_in_count += 1

                # Stop current TTS playback via ARI
                if self.ari_client:
                    playback_id = session.current_playback_id
                    session.current_playback_id = None  # Clear immediately to prevent duplicate stops

                    # Stop playback asynchronously (fire-and-forget)
                    asyncio.create_task(self._stop_playback_async(playback_id, session.call_id))

                self.logger.info(f"✋ TTS playback stopped (smart barge-in #{session.barge_in_count}) [{session.call_id}]")
            else:
                # False alarm (cough, "um", noise)
                self.logger.debug(
                    f"🚫 Smart Barge-in: False alarm ignored "
                    f"(duration={session.interruption_strategy.get_current_duration():.2f}s < "
                    f"min={session.interruption_strategy._min_duration}s) [{session.call_id}]"
                )

            # Reset strategy for next potential interruption
            await session.interruption_strategy.reset()

        # If speech detected, add to buffer (continue processing user utterance)
        if is_speech:
            success = session.audio_buffer.add_frame(pcm_data)
            if not success:
                self.logger.warning(f"Audio buffer full [{session.call_id}]")

    async def _stop_playback_async(self, playback_id: str, call_id: str):
        """
        Stop TTS playback asynchronously (for barge-in).

        Args:
            playback_id: Playback ID to stop
            call_id: Call ID (for logging)
        """
        try:
            success = await self.ari_client.stop_playback(playback_id)
            if success:
                self.logger.info(f"⏹️  Successfully stopped playback {playback_id} [{call_id}]")
            else:
                self.logger.warning(f"⚠️  Failed to stop playback {playback_id} [{call_id}]")
        except Exception as e:
            self.logger.error(f"Error stopping playback {playback_id}: {e}", exc_info=True)

    async def _send_silence_keepalive(self, session: CallSession):
        """
        Send a single silence RTP packet to keep bridge alive.

        Phase 5: Continuous Audio Stream
        Sends G.711 encoded silence (20ms frame) to prevent Asterisk from
        destroying the bridge during LLM+TTS processing.

        Args:
            session: CallSession instance
        """
        try:
            # Create 20ms silence frame (160 samples @ 8kHz)
            silence_frame = np.zeros(160, dtype=np.int16)

            # Encode to G.711 alaw
            g711_silence = self.codec.encode_from_numpy(silence_frame)
            if g711_silence is None:
                return

            # Build RTP packet
            rtp_packet = session.rtp_builder.build_packet(
                payload=g711_silence,
                payload_type=8,  # PCMA (G.711 alaw)
                marker=False,     # Not a new talk spurt
                timestamp_increment=160  # 20ms @ 8kHz
            )

            # Send packet
            await asyncio.get_event_loop().sock_sendto(
                self.sock,
                rtp_packet,
                session.remote_addr
            )

            session.packets_sent += 1
            session.bytes_sent += len(rtp_packet)

        except Exception as e:
            self.logger.debug(f"Keepalive send error [{session.call_id}]: {e}")

    async def _keepalive_during_processing(self, session: CallSession):
        """
        Send silence packets continuously during LLM+TTS processing.

        Phase 5: Continuous Audio Stream
        Prevents Asterisk bridge disconnect by maintaining audio activity.
        Sends 20ms silence frames every 20ms (50 packets/sec).

        This task runs until:
        - TTS is ready and starts playing (cancelled by _process_utterance)
        - Session ends (cancelled by cleanup)

        Args:
            session: CallSession instance
        """
        self.logger.info(f"🔇 Keepalive started [{session.call_id}]")
        packets_sent = 0

        try:
            while True:
                await self._send_silence_keepalive(session)
                packets_sent += 1

                # Log every 50 packets (1 second)
                if packets_sent % 50 == 0:
                    self.logger.info(f"🔇 Keepalive active [{session.call_id}] - {packets_sent} silence packets sent")

                await asyncio.sleep(0.02)  # 20ms intervals (50 Hz)

        except asyncio.CancelledError:
            self.logger.info(f"🔇 Keepalive stopped [{session.call_id}] - {packets_sent} silence packets sent")
            raise  # Re-raise to properly cancel
        except Exception as e:
            self.logger.error(f"Keepalive error [{session.call_id}]: {e}", exc_info=True)

    def _on_speech_start(self, call_id: str):
        """Callback when speech starts (per-call)."""
        session = self.sessions.get(call_id)
        if not session:
            return

        self.logger.info(f"🎙️  Speech started [{call_id}]")
        session.audio_buffer.clear()

    def _on_speech_end(self, call_id: str):
        """Callback when speech ends (per-call)."""
        session = self.sessions.get(call_id)
        if not session:
            return

        duration = session.audio_buffer.get_duration()
        self.logger.info(f"🤫 Speech ended [{call_id}] - {duration:.2f}s buffered")

        # Process buffered audio
        asyncio.create_task(self._process_utterance(session))

    # Phase 1: Silero VAD Callbacks
    def _on_speech_start_silero(self, call_id: str):
        """Callback when Silero VAD detects speech start."""
        session = self.sessions.get(call_id)
        if not session:
            return

        self.logger.debug(f"🎙️  Speech started [Silero] [{call_id}]")
        # Note: Audio buffer cleared by legacy VAD callback

    def _on_speech_end_silero(self, call_id: str):
        """Callback when Silero VAD detects speech end."""
        session = self.sessions.get(call_id)
        if not session:
            return

        self.logger.debug(f"🤫 Speech ended [Silero] [{call_id}]")
        # Note: Utterance processing triggered by legacy VAD callback

    async def _process_utterance(self, session: CallSession):
        """
        Process complete utterance: ASR → LLM → TTS → Send RTP.

        Args:
            session: CallSession instance
        """
        try:
            if session.audio_buffer.is_empty():
                return

            # Export WAV for Whisper
            wav_bytes = session.audio_buffer.export_wav(resample=True)
            if not wav_bytes:
                return

            self.logger.info(f"📝 Sending to ASR [{session.call_id}]: {len(wav_bytes)} bytes")

            # ASR: Transcribe
            transcription = self.asr.transcribe(wav_bytes)
            if not transcription:
                self.logger.warning(f"⚠️  Transcription failed [{session.call_id}]")
                session.audio_buffer.clear()
                return

            self.logger.info(f"🎯 Transcription [{session.call_id}]: \"{transcription}\"")

            # Phase 5: Start silence keepalive to maintain bridge during LLM+TTS processing
            # This prevents Asterisk from destroying bridge due to inactivity
            session.keepalive_task = asyncio.create_task(
                self._keepalive_during_processing(session)
            )
            self.logger.info(f"🔇 Keepalive task started [{session.call_id}]")

            # LLM: Generate response
            llm_response = self.llm.generate(transcription)
            if not llm_response:
                self.logger.warning(f"⚠️  LLM failed [{session.call_id}]")
                # Cancel keepalive on error
                if session.keepalive_task and not session.keepalive_task.done():
                    session.keepalive_task.cancel()
                session.audio_buffer.clear()
                return

            self.logger.info(f"🤖 LLM Response [{session.call_id}]: \"{llm_response}\"")

            # Full-duplex (Phase 4): No VAD muting
            # User can speak during TTS (barge-in enabled in Phase 5)

            # TTS: Generate speech
            audio_data = self.tts.synthesize(llm_response)
            if audio_data is None:
                self.logger.warning(f"⚠️  TTS failed [{session.call_id}]")
                # Cancel keepalive on error
                if session.keepalive_task and not session.keepalive_task.done():
                    session.keepalive_task.cancel()
                session.audio_buffer.clear()
                return

            self.logger.info(
                f"🔊 TTS Generated [{session.call_id}]: "
                f"{len(audio_data)} samples ({len(audio_data)/24000:.2f}s @ 24kHz)"
            )

            # Phase 5: Stop keepalive before sending TTS (real audio replaces silence)
            if session.keepalive_task and not session.keepalive_task.done():
                session.keepalive_task.cancel()
                try:
                    await session.keepalive_task  # Wait for cancellation
                except asyncio.CancelledError:
                    pass  # Expected
                self.logger.info(f"🔇 Keepalive task cancelled (TTS ready) [{session.call_id}]")

            # Send audio via RTP
            await self._send_audio_via_rtp(session, audio_data)

            # Clear buffer for next utterance
            session.audio_buffer.clear()

        except Exception as e:
            self.logger.error(f"Error processing utterance [{session.call_id}]: {e}", exc_info=True)
            # Cancel keepalive on exception
            if session and session.keepalive_task and not session.keepalive_task.done():
                session.keepalive_task.cancel()
            # Clear buffer on error
            if session:
                session.audio_buffer.clear()

    async def _send_audio_via_rtp(self, session: CallSession, audio_samples: np.ndarray) -> bool:
        """
        Send audio via RTP (complete pipeline: resample → encode → build → send).

        Args:
            session: CallSession instance
            audio_samples: Audio samples from TTS (numpy array, 24kHz)

        Returns:
            True if successful, False otherwise
        """
        try:
            if session.rtp_builder is None:
                self.logger.error(f"RTP builder not initialized [{session.call_id}]")
                return False

            self.logger.info(f"📡 Starting RTP transmission [{session.call_id}]")
            self.logger.info(f"   Destination: {session.remote_addr[0]}:{session.remote_addr[1]}")
            self.logger.info(f"   Outbound SSRC: {session.outbound_ssrc:#010x}")

            # Barge-in Support (Phase 4): Mark TTS playback as active
            # Use timestamp-based playback ID for tracking
            playback_id = f"rtp-tts-{session.call_id}-{int(time.time() * 1000)}"
            session.current_playback_id = playback_id
            self.logger.debug(f"🔊 TTS playback started: {playback_id} [{session.call_id}]")

            # Step 1: Resample from 24kHz (TTS) to 8kHz (G.711 codec)
            audio_8k = resample_audio(audio_samples, from_rate=24000, to_rate=8000, dtype=np.int16)

            # Step 2: Split into 20ms frames (160 samples @ 8kHz)
            frame_size = 160
            num_frames = len(audio_8k) // frame_size

            packets_sent = 0
            tts_start_time = time.time()

            # Step 3: For each frame: encode G.711 → build RTP → send
            for i in range(num_frames):
                start_idx = i * frame_size
                end_idx = start_idx + frame_size
                frame_pcm = audio_8k[start_idx:end_idx]

                # Encode to G.711 ulaw
                g711_data = self.codec.encode_from_numpy(frame_pcm)
                if g711_data is None:
                    continue

                # Build RTP packet (uses session's sequence/timestamp)
                marker = (i == 0)
                rtp_packet = session.rtp_builder.build_packet(
                    payload=g711_data,
                    payload_type=8,  # PCMA (G.711 alaw) - Match WebRTC codec
                    marker=marker,
                    timestamp_increment=160  # 20ms @ 8kHz
                )

                # Send packet
                try:
                    bytes_sent = await asyncio.get_event_loop().sock_sendto(
                        self.sock,
                        rtp_packet,
                        session.remote_addr
                    )

                    # Debug: Log first packet details
                    if packets_sent == 0:
                        self.logger.info(f"📍 First RTP packet sent: to={session.remote_addr}, len={len(rtp_packet)}, bytes_sent={bytes_sent}, socket_bound={self.sock.getsockname()}")
                        self.logger.info(f"   Socket info: fd={self.sock.fileno()}, family={self.sock.family}, type={self.sock.type}")
                except Exception as e:
                    self.logger.error(f"❌ Failed to send RTP packet: {e}", exc_info=True)
                    continue

                packets_sent += 1
                session.packets_sent += 1
                session.bytes_sent += len(rtp_packet)

            duration_s = (num_frames * frame_size) / 8000.0
            self.logger.info(
                f"📤 Sent {packets_sent} RTP packets [{session.call_id}] "
                f"- Duration: {duration_s:.2f}s"
            )

            # Barge-in Support (Phase 4): Clear playback ID after TTS completes
            session.current_playback_id = None
            self.logger.debug(f"✅ TTS playback completed: {playback_id} [{session.call_id}]")

            # Full-duplex (Phase 4): No VAD unmuting needed
            # VAD remains active throughout, echo filtering via SSRC prevents loops

            return True

        except Exception as e:
            self.logger.error(f"Error sending audio [{session.call_id}]: {e}", exc_info=True)
            # Clear playback ID on error
            session.current_playback_id = None
            return False

    async def _session_cleanup_task(self):
        """
        Background task: Cleanup idle sessions every 60s.

        Prevents memory leak from calls that don't hangup gracefully.
        """
        while self._running:
            await asyncio.sleep(60)  # Check every 1 minute

            idle_timeout = 300  # 5 minutes
            now = time.time()

            for call_id in list(self.sessions.keys()):
                session = self.sessions[call_id]
                idle_time = session.get_idle_time()

                if idle_time > idle_timeout:
                    self.logger.info(
                        f"🗑️  Cleaning up idle session {call_id} (idle={idle_time:.0f}s)"
                    )
                    await self.cleanup_session(call_id)

    async def cleanup_session(self, call_id: str):
        """
        Cleanup single session (manual or automatic).

        Args:
            call_id: Session identifier
        """
        session = self.sessions.pop(call_id, None)
        if not session:
            return

        # Cleanup components
        if session.audio_buffer:
            session.audio_buffer.clear()

        # Phase 5: Cancel keepalive task if running
        if session.keepalive_task and not session.keepalive_task.done():
            session.keepalive_task.cancel()
            try:
                await session.keepalive_task
            except asyncio.CancelledError:
                pass  # Expected
            self.logger.debug(f"🔇 Keepalive task cancelled (session cleanup) [{call_id}]")

        # ============================================
        # Phase 1: Cleanup Audio Quality Components
        # ============================================

        # Stop RNNoise filter
        if session.noise_filter:
            try:
                await session.noise_filter.stop()
            except Exception as e:
                self.logger.debug(f"Error stopping RNNoise filter: {e}")

        # Reset Silero VAD
        if session.silero_vad:
            try:
                session.silero_vad.reset()
            except Exception as e:
                self.logger.debug(f"Error resetting Silero VAD: {e}")

        # Reset SOXR resampler
        if session.soxr_resampler:
            try:
                session.soxr_resampler.reset()
            except Exception as e:
                self.logger.debug(f"Error resetting SOXR resampler: {e}")

        # =========================================================
        # Phase 2.1: Cleanup Conversational Intelligence Components
        # =========================================================

        # Cleanup Turn Analyzer
        if session.turn_analyzer:
            try:
                session.turn_analyzer.clear()
                await session.turn_analyzer.cleanup()
            except Exception as e:
                self.logger.debug(f"Error cleaning up Turn Analyzer: {e}")

        # Reset Interruption Strategy
        if session.interruption_strategy:
            try:
                await session.interruption_strategy.reset()
            except Exception as e:
                self.logger.debug(f"Error resetting Interruption Strategy: {e}")

        # Note: socket is shared, don't close it

        self.logger.info(f"✅ Session cleaned up: {call_id} (remaining: {len(self.sessions)})")

    def _initialize_ai_models(self):
        """Initialize AI models (shared across all calls)."""
        # Whisper ASR
        whisper_config = self.config.get('whisper', {})
        self.asr = WhisperASR(
            model_path=whisper_config.get('model_path', '/app/models/whisper/ggml-base.bin'),
            language=whisper_config.get('language', 'pt')
        )

        # Phi-3 LLM
        llm_config = self.config.get('llm', {})
        self.llm = Phi3LLM(
            model_path=llm_config.get('model_path', '/app/models/llm/phi-3-mini.gguf'),
            system_prompt=llm_config.get('system_prompt',
                'Você é um assistente de voz brasileiro. '
                'Responda SEMPRE em português do Brasil. '
                'Seja EXTREMAMENTE conciso: máximo 1 frase curta (até 10 palavras). '
                'Não use markdown, não use **asteriscos**, não liste alternativas. '
                'Responda apenas UMA vez, de forma direta e objetiva. '
                'NUNCA adicione notas, comentários, explicações ou meta-informações sobre suas instruções. '
                'PROIBIDO usar "Note:", "Nota:", "**Note:**", "Observação:", ou qualquer texto explicativo adicional.'),
            n_threads=llm_config.get('n_threads', 6),
            temperature=llm_config.get('temperature', 0.3),
            max_tokens=llm_config.get('max_tokens', 30)
        )

        # Kokoro TTS
        tts_config = self.config.get('tts', {})
        self.tts = KokoroTTS(
            lang_code=tts_config.get('lang_code', 'p'),
            voice=tts_config.get('voice', 'pf_dora'),
            sample_rate=tts_config.get('sample_rate', 24000)
        )

        self.logger.info("✅ AI models initialized (ASR + LLM + TTS)")

    def get_stats(self) -> Dict[str, Any]:
        """Get server statistics."""
        total_stats = {
            'active_sessions': len(self.sessions),
            'total_packets_rx': sum(s.packets_received for s in self.sessions.values()),
            'total_packets_tx': sum(s.packets_sent for s in self.sessions.values()),
            'total_bytes_rx': sum(s.bytes_received for s in self.sessions.values()),
            'total_bytes_tx': sum(s.bytes_sent for s in self.sessions.values()),
            'total_echo_filtered': sum(s.echo_packets_filtered for s in self.sessions.values()),
            'sessions': {}
        }

        # Per-session stats
        for call_id, session in self.sessions.items():
            total_stats['sessions'][call_id] = session.get_stats()

        return total_stats
