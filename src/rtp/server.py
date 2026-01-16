"""
RTP Server for receiving and sending audio packets
"""

import asyncio
import socket
import logging
import time
from typing import Dict, Any
import sys
from pathlib import Path

# Add parent directory to path to import codec module
sys.path.insert(0, str(Path(__file__).parent.parent))

from codec import RTPParser, G711Codec


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

        # RTP parser and codec
        self.rtp_parser = RTPParser()
        self.codec = G711Codec(law='ulaw')  # Changed from alaw to ulaw

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
                        self.logger.info(f"🎤 First RTP packet received from {addr}")

                    # Parse RTP packet
                    rtp_packet = self.rtp_parser.parse(data)

                    if rtp_packet:
                        # Decode G.711 ulaw to PCM
                        pcm_data = self.codec.decode(rtp_packet.payload)

                        if pcm_data:
                            self.audio_frames_decoded += 1
                            self.pcm_bytes_decoded += len(pcm_data)

                            # TODO: Send PCM to audio buffer
                            # TODO: VAD (Voice Activity Detection)
                            # TODO: Send to ASR pipeline when voice detected

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

    def get_stats(self) -> Dict[str, int]:
        """Get server statistics"""
        return {
            'packets_received': self.packets_received,
            'packets_sent': self.packets_sent,
            'bytes_received': self.bytes_received,
            'bytes_sent': self.bytes_sent,
        }
