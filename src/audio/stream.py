"""
Audio Stream Interface

Provides abstract interface for AI Pipeline to consume/produce audio,
hiding RTP/codec complexity.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Optional
import time

from ..common.logging import get_logger
from ..rtp.packet import RTPHeader
from ..rtp.server import RTPSession
from .codec import G711Codec

logger = get_logger('audio.stream')


class AudioStream(ABC):
    """
    Abstract interface for audio streaming

    Provides clean API for AI components to consume/produce audio
    without dealing with RTP/codec details.
    """

    @abstractmethod
    async def receive(self) -> Optional[bytes]:
        """
        Receive PCM audio chunk (typically 20ms frame)

        Returns:
            PCM data (16-bit signed little-endian) or None if closed
        """
        pass

    @abstractmethod
    async def send(self, pcm_data: bytes) -> bool:
        """
        Send PCM audio chunk

        Args:
            pcm_data: PCM data (16-bit signed little-endian)

        Returns:
            True if sent successfully
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close stream gracefully"""
        pass

    @abstractmethod
    def is_active(self) -> bool:
        """Check if stream is active"""
        pass

    @abstractmethod
    def get_stats(self) -> dict:
        """Get stream statistics"""
        pass


class RTPAudioStream(AudioStream):
    """
    AudioStream implementation backed by RTP

    Bridges RTPSession to AudioStream interface, handling:
    - G.711 codec encoding/decoding
    - RTP packet generation
    - Queue management
    """

    def __init__(self, rtp_session: RTPSession, codec: Optional[G711Codec] = None):
        """
        Initialize RTP audio stream

        Args:
            rtp_session: RTP session to bridge
            codec: G.711 codec (default: PCMU/μ-law)
        """
        self.rtp_session = rtp_session
        self.codec = codec or G711Codec(law='ulaw')

        # State
        self.active = True
        self.closed = False

        # Statistics
        self.frames_received = 0
        self.frames_sent = 0
        self.bytes_received = 0
        self.bytes_sent = 0

        # RTP TX state
        self.tx_sequence_number = 0
        self.tx_timestamp = 0
        self.tx_ssrc = 0x12345678  # Our SSRC for outbound stream
        self.sample_rate = 8000  # G.711 sample rate

        logger.info("RTP AudioStream created",
                   session_id=rtp_session.session_id,
                   codec=codec.law)

    async def receive(self) -> Optional[bytes]:
        """
        Receive PCM audio frame from RTP

        Returns:
            PCM data (16-bit signed) or None if closed/timeout
        """
        if self.closed:
            return None

        try:
            # Get RTP packet from queue (with timeout)
            try:
                header, payload = await asyncio.wait_for(
                    self.rtp_session.audio_in_queue.get(),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.debug("Receive timeout (no audio for 5s)")
                return None

            # Decode G.711 → PCM
            pcm_data = self.codec.decode(payload)
            if pcm_data is None:
                logger.warning("Failed to decode RTP payload")
                return None

            # Update statistics
            self.frames_received += 1
            self.bytes_received += len(payload)

            return pcm_data

        except Exception as e:
            logger.error("Error receiving audio", error=str(e))
            return None

    async def send(self, pcm_data: bytes) -> bool:
        """
        Send PCM audio frame via RTP

        Args:
            pcm_data: PCM data (16-bit signed)

        Returns:
            True if sent successfully
        """
        if self.closed:
            return False

        try:
            # Encode PCM → G.711
            g711_data = self.codec.encode(pcm_data)
            if g711_data is None:
                logger.warning("Failed to encode PCM data")
                return False

            # Create RTP header
            header = RTPHeader(
                version=2,
                padding=False,
                extension=False,
                marker=False,
                payload_type=0,  # PCMU
                sequence_number=self.tx_sequence_number & 0xFFFF,
                timestamp=self.tx_timestamp & 0xFFFFFFFF,
                ssrc=self.tx_ssrc
            )

            # Send via RTP session
            await self.rtp_session.send_rtp(header, g711_data)

            # Update TX state
            self.tx_sequence_number += 1
            samples_per_frame = len(pcm_data) // 2  # 16-bit = 2 bytes per sample
            self.tx_timestamp += samples_per_frame

            # Update statistics
            self.frames_sent += 1
            self.bytes_sent += len(g711_data)

            return True

        except Exception as e:
            logger.error("Error sending audio", error=str(e))
            return False

    async def close(self) -> None:
        """Close stream gracefully"""
        if self.closed:
            return

        self.closed = True
        self.active = False

        logger.info("RTP AudioStream closed",
                   frames_rx=self.frames_received,
                   frames_tx=self.frames_sent)

    def is_active(self) -> bool:
        """Check if stream is active"""
        return self.active and not self.closed and self.rtp_session.connection.running

    def get_stats(self) -> dict:
        """Get stream statistics"""
        return {
            'session_id': self.rtp_session.session_id,
            'active': self.active,
            'closed': self.closed,
            'frames_received': self.frames_received,
            'frames_sent': self.frames_sent,
            'bytes_received': self.bytes_received,
            'bytes_sent': self.bytes_sent,
            'codec': self.codec.law,
            'rtp_session': self.rtp_session.get_stats()
        }
