"""
RTP Server for receiving and sending audio packets
"""

import asyncio
import socket
import logging
import time
import numpy as np
from typing import Dict, Any
import sys
from pathlib import Path

# Add parent directory to path to import codec module
sys.path.insert(0, str(Path(__file__).parent.parent))

from codec import RTPParser, G711Codec, RTPBuilder
from audio.buffer import AudioBuffer
from audio.vad import VoiceActivityDetector
from audio.resampling import resample_audio
from asr.whisper import WhisperASR
from llm.phi3 import Phi3LLM
from tts.kokoro import KokoroTTS


class RTPServer:
    """
    UDP server for handling RTP audio streams with G.711 decoding
    """

    def __init__(self, host: str = '0.0.0.0', port: int = 5080, config: Dict[str, Any] = None):
        """
        Initialize RTP server

        Args:
            host: Host to bind to
            port: Port to bind to
            config: Configuration dictionary
        """
        self.host = host
        self.port = port
        self.config = config or {}
        self.logger = logging.getLogger("ai-voice-agent.rtp")

        # Socket
        self.sock = None

        # RTP parser, codec, and builder
        self.rtp_parser = RTPParser()
        self.codec = G711Codec(law='ulaw')  # Changed from alaw to ulaw
        self.rtp_builder = None  # Will be initialized when first call is received

        # Statistics
        self.packets_received = 0
        self.packets_sent = 0
        self.bytes_received = 0
        self.bytes_sent = 0

        # Real-time stats tracking
        self.stats_start_time = None
        self.last_stats_log_time = None
        self.stats_interval = 2.0  # Log stats every 2 seconds

        # Audio processing stats
        self.audio_frames_decoded = 0
        self.pcm_bytes_decoded = 0

        # Audio pipeline components
        self.audio_buffer = None
        self.vad = None
        self.asr = None
        self.llm = None
        self.tts = None
        self.current_call_id = None
        self.current_remote_addr = None  # Track remote address for sending RTP

        # Half-duplex control (mute VAD during TTS playback to prevent echo)
        self.vad_muted = False
        self.tts_playback_start_time = None

    async def start(self):
        """Start the RTP server"""
        try:
            # Create UDP socket
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # Set large buffer size to prevent packet loss
            buffer_size = self.config.get('rtp_buffer_size', 4 * 1024 * 1024)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_size)

            # Bind to address
            self.sock.bind((self.host, self.port))
            self.sock.setblocking(False)

            self.logger.info(f"✅ RTP Server started on {self.host}:{self.port}")
            self.logger.info(f"   Buffer size: {buffer_size / 1024 / 1024:.1f}MB")

            # Initialize audio pipeline
            self._initialize_audio_pipeline()

            # Start receiving loop
            asyncio.create_task(self._receive_loop())

        except Exception as e:
            self.logger.error(f"Failed to start RTP server: {e}")
            raise

    async def _receive_loop(self):
        """Main loop for receiving RTP packets"""
        loop = asyncio.get_event_loop()

        self.logger.info("📡 RTP receive loop started")

        while True:
            try:
                # Receive packet (non-blocking)
                data, addr = await loop.sock_recvfrom(self.sock, 2048)

                if data:
                    current_time = time.time()

                    self.packets_received += 1
                    self.bytes_received += len(data)

                    # Initialize timing on first packet
                    if self.packets_received == 1:
                        self.stats_start_time = current_time
                        self.last_stats_log_time = current_time
                        self.current_remote_addr = addr  # Save remote address for sending RTP
                        self.logger.info(f"🎤 First RTP packet received from {addr}")

                        # Reset RTP parser statistics for this call
                        self.rtp_parser.reset_stats()

                        # Initialize RTP builder for sending
                        self.rtp_builder = RTPBuilder()
                        self.logger.info(f"✅ RTP Builder initialized for sending responses")

                    # Parse RTP packet
                    rtp_packet = self.rtp_parser.parse(data)

                    if rtp_packet:
                        # Decode G.711 ulaw to PCM
                        pcm_data = self.codec.decode(rtp_packet.payload)

                        if pcm_data:
                            self.audio_frames_decoded += 1
                            self.pcm_bytes_decoded += len(pcm_data)

                            # Process through VAD + Buffer pipeline
                            self._process_audio_frame(pcm_data)

                    # Log real-time statistics every N seconds
                    if self.last_stats_log_time and (current_time - self.last_stats_log_time) >= self.stats_interval:
                        elapsed_total = current_time - self.stats_start_time
                        elapsed_interval = current_time - self.last_stats_log_time

                        # Calculate rates
                        packets_per_sec = self.packets_received / elapsed_total if elapsed_total > 0 else 0
                        kb_total = self.bytes_received / 1024
                        pcm_kb = self.pcm_bytes_decoded / 1024

                        # Get parser stats
                        parser_stats = self.rtp_parser.get_stats()

                        self.logger.info(
                            f"📊 RTP Stats: {self.packets_received} packets ({kb_total:.1f}KB) "
                            f"in {elapsed_total:.1f}s - {packets_per_sec:.0f} pkt/s"
                        )
                        self.logger.info(
                            f"🎵 Audio: {self.audio_frames_decoded} frames decoded "
                            f"({pcm_kb:.1f}KB PCM) - Loss: {parser_stats['loss_rate']*100:.2f}%"
                        )

                        self.last_stats_log_time = current_time

            except Exception as e:
                self.logger.error(f"Error in receive loop: {e}", exc_info=True)
                await asyncio.sleep(0.1)

    async def send_rtp(self, payload: bytes, dest_addr: tuple):
        """
        Send RTP packet

        Args:
            payload: RTP payload (encoded audio)
            dest_addr: Destination (host, port) tuple
        """
        try:
            self.sock.sendto(payload, dest_addr)
            self.packets_sent += 1
            self.bytes_sent += len(payload)

        except Exception as e:
            self.logger.error(f"Failed to send RTP packet: {e}")

    def _initialize_audio_pipeline(self):
        """Initialize audio buffer, VAD, and ASR"""
        # Create audio buffer (8kHz input, 16kHz output for Whisper)
        self.audio_buffer = AudioBuffer(
            sample_rate=8000,
            target_rate=16000,
            channels=1,
            max_duration_seconds=30.0
        )

        # Create VAD with callbacks
        # Thresholds based on real-world voice agent projects (Asterisk-AI-Voice-Agent, Pipecat)
        self.vad = VoiceActivityDetector(
            sample_rate=8000,
            frame_duration_ms=20,
            energy_threshold_start=1200.0,  # RMS 1000-3000 range (evidence: Asterisk-AI-Voice-Agent)
                                             # Using 1200 (lower end) for better detection on clean lines
            energy_threshold_end=700.0,     # Allow faster termination (evidence: real-world projects use 700-900)
            silence_duration_ms=700,        # Wait 700ms of silence to confirm speech end
            min_speech_duration_ms=500,     # Minimum 250-600ms (evidence: barge_in.min_ms in real projects)
            on_speech_start=self._on_speech_start,
            on_speech_end=self._on_speech_end
        )

        # Create Whisper ASR
        whisper_config = self.config.get('whisper', {})
        self.asr = WhisperASR(
            model_path=whisper_config.get('model_path', '/app/models/whisper/ggml-base.bin'),
            language=whisper_config.get('language', 'pt')
        )

        # Create Phi-3 LLM
        # Configuration based on real-world voice agent best practices (LiveKit, Pipecat)
        llm_config = self.config.get('llm', {})
        self.llm = Phi3LLM(
            model_path=llm_config.get('model_path', '/app/models/llm/phi-3-mini.gguf'),
            system_prompt=llm_config.get('system_prompt',
                'Você é um assistente de voz brasileiro. '
                'Responda SEMPRE em português do Brasil. '
                'Seja EXTREMAMENTE conciso: máximo 1 frase curta (até 10 palavras). '
                'Não use markdown, não use **asteriscos**, não liste alternativas. '
                'Responda apenas UMA vez, de forma direta e objetiva.'),
            n_threads=llm_config.get('n_threads', 6),
            temperature=llm_config.get('temperature', 0.3),  # 0.2-0.3 for fact-based QA (evidence: real projects)
            max_tokens=llm_config.get('max_tokens', 30)      # 30-50 for voice assistants (evidence: LiveKit, Pipecat)
        )

        # Create Kokoro TTS
        tts_config = self.config.get('tts', {})
        self.tts = KokoroTTS(
            lang_code=tts_config.get('lang_code', 'p'),  # Brazilian Portuguese
            voice=tts_config.get('voice', 'pf_dora'),     # Female voice
            sample_rate=tts_config.get('sample_rate', 24000)
        )

        self.logger.info("✅ Audio pipeline initialized (Buffer + VAD + ASR + LLM + TTS)")

    def _process_audio_frame(self, pcm_data: bytes):
        """
        Process audio frame through VAD and buffer

        Args:
            pcm_data: PCM audio data (16-bit signed, 8kHz)
        """
        if not self.vad or not self.audio_buffer:
            return

        # Half-duplex: Skip VAD processing if muted during TTS playback
        # Pattern from Pipecat AI: block VAD frames when bot is speaking
        if self.vad_muted:
            return

        # Run VAD on frame
        is_speech = self.vad.process_frame(pcm_data)

        # If speech detected, add to buffer
        if is_speech:
            success = self.audio_buffer.add_frame(pcm_data)
            if not success:
                self.logger.warning("Audio buffer full, frame rejected")

    def _on_speech_start(self):
        """Callback when speech starts"""
        self.logger.info("🎙️  Speech started - buffering audio")
        # Clear buffer to start fresh
        self.audio_buffer.clear()

    def _on_speech_end(self):
        """Callback when speech ends"""
        duration = self.audio_buffer.get_duration()
        self.logger.info(f"🤫 Speech ended - {duration:.2f}s buffered")

        # Get buffered audio
        if not self.audio_buffer.is_empty():
            # Export as WAV for Whisper
            wav_bytes = self.audio_buffer.export_wav(resample=True)

            if wav_bytes:
                self.logger.info(f"📝 Sending to ASR: {len(wav_bytes)} bytes WAV @ 16kHz")

                # Transcribe with Whisper
                transcription = self.asr.transcribe(wav_bytes)

                if transcription:
                    self.logger.info(f"🎯 Transcription: \"{transcription}\"")

                    # Generate LLM response
                    if self.llm:
                        llm_response = self.llm.generate(transcription)
                        if llm_response:
                            self.logger.info(f"🤖 LLM Response: \"{llm_response}\"")

                            # PREVENTIVE MUTE: Mute VAD BEFORE TTS generation
                            # Pattern from Asterisk-AI-Voice-Agent: initial_protection_ms (200-600ms)
                            # This prevents VAD from detecting noise/silence before TTS starts
                            self.vad_muted = True
                            self.tts_playback_start_time = time.time()
                            self.logger.info("🔇 VAD muted - preparing TTS response")

                            # Generate speech with TTS
                            if self.tts:
                                audio_data = self.tts.synthesize(llm_response)
                                if audio_data is not None:
                                    self.logger.info(f"🔊 TTS Generated: {len(audio_data)} samples ({len(audio_data)/24000:.2f}s @ 24kHz)")

                                    # Send audio via RTP (async)
                                    # VAD is already muted, so no echo will be detected
                                    asyncio.create_task(self._send_audio_via_rtp(audio_data))
                                else:
                                    self.logger.warning("⚠️  TTS synthesis failed")
                                    # Unmute VAD on TTS failure
                                    self.vad_muted = False
                            else:
                                self.logger.warning("⚠️  TTS not initialized")
                                # Unmute VAD if TTS not available
                                self.vad_muted = False
                        else:
                            self.logger.warning("⚠️  LLM generation failed or empty")
                    else:
                        self.logger.warning("⚠️  LLM not initialized")
                else:
                    self.logger.warning("⚠️  Transcription failed or empty")

            # Clear buffer for next utterance
            self.audio_buffer.clear()

    async def _send_audio_via_rtp(self, audio_samples: np.ndarray) -> bool:
        """
        Send audio via RTP (complete pipeline: resample → encode → build → send)

        Implements half-duplex pattern: VAD is already muted before calling this method.
        Based on real-world patterns:
        - Asterisk-AI-Voice-Agent: initial_protection_ms (200-600ms) - preventive mute
        - Pipecat AI: AlwaysUserMuteStrategy (mute during bot speech)

        Args:
            audio_samples: Audio samples from TTS (numpy array, 24kHz)

        Returns:
            True if successful, False otherwise
        """
        try:
            if self.rtp_builder is None or self.current_remote_addr is None:
                self.logger.error("RTP builder or remote address not initialized")
                return False

            # VAD is already muted (set in _on_speech_end before TTS generation)
            # This ensures zero echo detection from the moment we start preparing the response
            self.logger.info("📡 Starting RTP transmission (VAD already muted)")

            # Step 1: Resample from 24kHz (TTS) to 8kHz (G.711 codec)
            self.logger.debug(f"Step 1: Resampling {len(audio_samples)} samples from 24kHz to 8kHz")
            audio_8k = resample_audio(audio_samples, from_rate=24000, to_rate=8000, dtype=np.int16)
            self.logger.debug(f"  ✓ Resampled to {len(audio_8k)} samples @ 8kHz")

            # Step 2: Split into 20ms frames (160 samples @ 8kHz)
            frame_size = 160  # 20ms @ 8kHz = 160 samples
            num_frames = len(audio_8k) // frame_size
            self.logger.debug(f"Step 2: Splitting into {num_frames} frames of {frame_size} samples (20ms)")

            packets_sent = 0

            # Step 3: For each frame: encode G.711 → build RTP → send
            for i in range(num_frames):
                # Extract frame
                start_idx = i * frame_size
                end_idx = start_idx + frame_size
                frame_pcm = audio_8k[start_idx:end_idx]

                # Encode to G.711 ulaw
                g711_data = self.codec.encode_from_numpy(frame_pcm)
                if g711_data is None:
                    self.logger.error(f"Failed to encode frame {i}")
                    continue

                # Build RTP packet
                # Set marker bit on first packet
                marker = (i == 0)
                rtp_packet = self.rtp_builder.build_packet(
                    payload=g711_data,
                    payload_type=0,  # 0 = PCMU (G.711 ulaw)
                    marker=marker,
                    timestamp_increment=160  # 20ms @ 8kHz
                )

                # Send packet
                await asyncio.get_event_loop().sock_sendto(
                    self.sock,
                    rtp_packet,
                    self.current_remote_addr
                )

                packets_sent += 1
                self.packets_sent += 1
                self.bytes_sent += len(rtp_packet)

            duration_s = (num_frames * frame_size) / 8000.0
            self.logger.info(
                f"📤 Sent {packets_sent} RTP packets ({self.bytes_sent/1024:.1f}KB total) "
                f"- Duration: {duration_s:.2f}s"
            )

            # UNMUTE VAD after TTS playback + protection window
            # Pattern from Asterisk-AI-Voice-Agent: post_tts_end_protection_ms (250-500ms)
            # Wait for audio to finish playing + 300ms guard time
            protection_window_ms = 300
            total_wait = duration_s + (protection_window_ms / 1000.0)

            await asyncio.sleep(total_wait)

            # Pattern: BotStoppedSpeakingFrame equivalent
            self.vad_muted = False
            playback_duration = time.time() - self.tts_playback_start_time
            self.logger.info(f"🔊 VAD unmuted - TTS playback ended (total: {playback_duration:.2f}s)")

            return True

        except Exception as e:
            self.logger.error(f"Error sending audio via RTP: {e}", exc_info=True)
            # Ensure VAD is unmuted even on error
            self.vad_muted = False
            return False

    def get_stats(self) -> Dict[str, int]:
        """Get server statistics"""
        stats = {
            'packets_received': self.packets_received,
            'packets_sent': self.packets_sent,
            'bytes_received': self.bytes_received,
            'bytes_sent': self.bytes_sent,
        }

        # Add VAD stats if available
        if self.vad:
            stats['vad'] = self.vad.get_stats()

        # Add buffer stats if available
        if self.audio_buffer:
            stats['buffer'] = self.audio_buffer.get_stats()

        # Add ASR stats if available
        if self.asr:
            stats['asr'] = self.asr.get_stats()

        # Add TTS stats if available
        if self.tts:
            stats['tts'] = self.tts.get_stats()

        return stats
