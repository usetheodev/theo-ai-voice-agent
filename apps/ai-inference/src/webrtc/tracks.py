"""Audio track handlers for WebRTC communication."""

import asyncio
import logging
from fractions import Fraction
from typing import Optional

import av
from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError

from ..core.session import RealtimeSession

logger = logging.getLogger(__name__)

# Audio configuration constants
SAMPLE_RATE = 24000  # 24kHz as per OpenAI Realtime API
CHANNELS = 1  # Mono audio
SAMPLES_PER_FRAME = 960  # 40ms at 24kHz (960 samples)


class AudioInputHandler:
    """Handles incoming audio from the client.

    Receives audio frames from the WebRTC track, converts them to
    the appropriate format, and passes them to the session for processing.
    """

    def __init__(
        self,
        session: RealtimeSession,
        track: MediaStreamTrack,
    ):
        """Initialize the audio input handler.

        Args:
            session: The associated RealtimeSession instance.
            track: The incoming audio MediaStreamTrack.
        """
        self.session = session
        self.track = track
        self._running = False
        self._task: Optional[asyncio.Task] = None

        logger.info(
            "AudioInputHandler created",
            extra={"session_id": session.id},
        )

    async def start(self) -> None:
        """Start processing incoming audio frames."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._process_loop())

        logger.info(
            "AudioInputHandler started",
            extra={"session_id": self.session.id},
        )

    async def stop(self) -> None:
        """Stop processing and cleanup resources."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info(
            "AudioInputHandler stopped",
            extra={"session_id": self.session.id},
        )

    async def _process_loop(self) -> None:
        """Main processing loop for incoming audio."""
        try:
            while self._running:
                try:
                    # Receive frame from track
                    frame = await self.track.recv()

                    # Convert to PCM16 bytes
                    audio_data = self._frame_to_pcm16(frame)

                    if audio_data:
                        # Append to session audio buffer
                        self.session.append_audio(audio_data)

                        logger.debug(
                            "Audio frame processed",
                            extra={
                                "session_id": self.session.id,
                                "bytes": len(audio_data),
                                "pts": frame.pts,
                            },
                        )

                except MediaStreamError:
                    logger.info(
                        "Audio track ended",
                        extra={"session_id": self.session.id},
                    )
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(
                "Error in audio input processing",
                extra={"session_id": self.session.id},
            )

    def _frame_to_pcm16(self, frame: av.AudioFrame) -> bytes:
        """Convert an AudioFrame to PCM16 bytes.

        Args:
            frame: The av.AudioFrame from aiortc.

        Returns:
            PCM16 audio data as bytes.
        """
        # Resample to target format if needed
        if frame.sample_rate != SAMPLE_RATE or frame.layout.name != "mono":
            resampler = av.AudioResampler(
                format="s16",
                layout="mono",
                rate=SAMPLE_RATE,
            )
            frame = resampler.resample(frame)[0]
        else:
            # Just ensure format is s16
            frame = frame.reformat(format="s16")

        # Convert to bytes
        return bytes(frame.planes[0])


class AudioOutputTrack(MediaStreamTrack):
    """Audio output track for sending audio to the client.

    Generates audio frames from the session's output buffer and
    sends them to the client via WebRTC.
    """

    kind = "audio"

    def __init__(self, session: RealtimeSession):
        """Initialize the audio output track.

        Args:
            session: The associated RealtimeSession instance.
        """
        super().__init__()
        self.session = session
        self._pts = 0
        self._sample_rate = SAMPLE_RATE
        self._channels = CHANNELS

        # Output audio queue
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)

        # Silence frame for when no audio is available
        self._silence_frame = self._create_silence_frame()

        logger.info(
            "AudioOutputTrack created",
            extra={"session_id": session.id},
        )

    def _create_silence_frame(self) -> av.AudioFrame:
        """Create a silence audio frame.

        Returns:
            An AudioFrame containing silence.
        """
        frame = av.AudioFrame(
            format="s16",
            layout="mono",
            samples=SAMPLES_PER_FRAME,
        )
        frame.sample_rate = self._sample_rate
        frame.pts = 0

        # Fill with zeros (silence)
        # For s16 mono, each sample is 2 bytes
        silence_bytes = bytes(SAMPLES_PER_FRAME * 2)
        for plane in frame.planes:
            plane.update(silence_bytes)

        return frame

    async def recv(self) -> av.AudioFrame:
        """Receive the next audio frame to send.

        Returns:
            The next AudioFrame to transmit.
        """
        # Try to get audio from queue
        try:
            audio_data = self._audio_queue.get_nowait()
            frame = self._pcm16_to_frame(audio_data)
        except asyncio.QueueEmpty:
            # Return silence when no audio available
            frame = self._create_silence_frame()

        # Update presentation timestamp
        frame.pts = self._pts
        frame.time_base = Fraction(1, self._sample_rate)
        self._pts += SAMPLES_PER_FRAME

        return frame

    def _pcm16_to_frame(self, audio_data: bytes) -> av.AudioFrame:
        """Convert PCM16 bytes to an AudioFrame.

        Args:
            audio_data: PCM16 audio data.

        Returns:
            An av.AudioFrame.
        """
        # Calculate number of samples
        num_samples = len(audio_data) // 2  # 2 bytes per sample for s16

        frame = av.AudioFrame(
            format="s16",
            layout="mono",
            samples=num_samples,
        )
        frame.sample_rate = self._sample_rate
        frame.planes[0].update(audio_data)

        return frame

    def queue_audio(self, audio_data: bytes) -> bool:
        """Queue audio data for transmission.

        Args:
            audio_data: PCM16 audio data to send.

        Returns:
            True if queued successfully, False if queue is full.
        """
        try:
            self._audio_queue.put_nowait(audio_data)
            return True
        except asyncio.QueueFull:
            logger.warning(
                "Audio output queue full, dropping frame",
                extra={"session_id": self.session.id},
            )
            return False

    def clear_queue(self) -> None:
        """Clear the audio output queue."""
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        logger.debug(
            "Audio output queue cleared",
            extra={"session_id": self.session.id},
        )
