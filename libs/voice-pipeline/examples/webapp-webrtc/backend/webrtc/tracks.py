"""Audio tracks for WebRTC communication."""

import asyncio
import fractions
import logging
import time
from typing import Optional

import numpy as np
from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError
from av import AudioFrame as AVAudioFrame

logger = logging.getLogger(__name__)

# Audio constants
SAMPLE_RATE = 16000  # 16kHz for voice
CHANNELS = 1  # Mono
SAMPLE_WIDTH = 2  # 16-bit PCM
FRAME_DURATION_MS = 20  # 20ms frames (standard for WebRTC)
SAMPLES_PER_FRAME = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 320 samples


class AudioInputTrack(MediaStreamTrack):
    """Track that receives audio from the browser.

    This track decodes incoming Opus audio and provides PCM16 frames
    for processing by the voice pipeline (VAD, ASR, etc.).
    """

    kind = "audio"

    def __init__(self, track: MediaStreamTrack):
        """Initialize the input track.

        Args:
            track: The remote audio track from WebRTC peer connection.
        """
        super().__init__()
        self._track = track
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._sample_rate = SAMPLE_RATE
        self._channels = CHANNELS

    @property
    def sample_rate(self) -> int:
        """Get the sample rate."""
        return self._sample_rate

    @property
    def channels(self) -> int:
        """Get the number of channels."""
        return self._channels

    async def start(self) -> None:
        """Start receiving audio frames."""
        self._running = True
        self._task = asyncio.create_task(self._receive_loop())
        logger.info("AudioInputTrack started")

    async def stop(self) -> None:
        """Stop receiving audio frames."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AudioInputTrack stopped")

    async def _receive_loop(self) -> None:
        """Background task to receive and process frames."""
        logger.info("AudioInputTrack receive loop started")
        frame_count = 0
        while self._running:
            try:
                frame = await self._track.recv()
                frame_count += 1

                if frame_count == 1:
                    logger.info(f"*** FIRST AUDIO FRAME *** rate={frame.sample_rate}, format={frame.format}, samples={frame.samples}, layout={frame.layout}")
                elif frame_count % 50 == 0:
                    logger.info(f"AudioInputTrack: {frame_count} frames, queue={self._queue.qsize()}")

                # Convert AV frame to numpy array
                # aiortc gives us s16 planar or interleaved audio
                audio_array = frame.to_ndarray()

                if frame_count == 1:
                    logger.info(f"AUDIO DEBUG: ndarray shape={audio_array.shape}, dtype={audio_array.dtype}, layout={frame.layout.name}")

                # Handle different audio formats
                # Check if stereo - need to convert to mono properly
                num_channels = len(frame.layout.channels)
                if frame_count == 1:
                    logger.info(f"AUDIO DEBUG: num_channels={num_channels}, samples_per_channel={frame.samples}")

                if num_channels > 1:
                    # Stereo audio - need to convert to mono
                    if audio_array.ndim == 1 or (audio_array.ndim == 2 and audio_array.shape[0] == 1):
                        # Interleaved format: L,R,L,R,L,R...
                        # Flatten if 2D with shape (1, N)
                        if audio_array.ndim == 2:
                            audio_array = audio_array.flatten()
                        if frame_count == 1:
                            logger.info(f"AUDIO DEBUG: Interleaved stereo detected, total_samples={len(audio_array)}")
                        # Separate channels and average
                        left_channel = audio_array[::2]  # Even indices
                        right_channel = audio_array[1::2]  # Odd indices
                        # Average the channels (convert to float first to avoid overflow)
                        audio_array = ((left_channel.astype(np.float32) + right_channel.astype(np.float32)) / 2).astype(np.int16)
                        if frame_count == 1:
                            logger.info(f"AUDIO DEBUG: After stereo->mono, samples={len(audio_array)}")
                    elif audio_array.ndim == 2 and audio_array.shape[0] == num_channels:
                        # Planar format: (channels, samples)
                        if frame_count == 1:
                            logger.info(f"AUDIO DEBUG: Planar stereo detected, shape={audio_array.shape}")
                        audio_array = audio_array.mean(axis=0).astype(np.int16)
                        if frame_count == 1:
                            logger.info(f"AUDIO DEBUG: After planar->mono, samples={len(audio_array)}")

                # Ensure int16 format
                if audio_array.dtype != np.int16:
                    if audio_array.dtype == np.float32 or audio_array.dtype == np.float64:
                        # Convert float [-1, 1] to int16
                        audio_array = (audio_array * 32767).astype(np.int16)
                    else:
                        audio_array = audio_array.astype(np.int16)

                # Resample if needed (WebRTC usually uses 48kHz)
                if frame.sample_rate != SAMPLE_RATE:
                    if frame_count == 1:
                        logger.info(f"Resampling audio from {frame.sample_rate}Hz to {SAMPLE_RATE}Hz, input_samples={len(audio_array)}")
                    audio_array = self._resample(audio_array, frame.sample_rate, SAMPLE_RATE)
                    if frame_count == 1:
                        logger.info(f"AUDIO DEBUG: After resampling, samples={len(audio_array)}")

                # Convert to bytes
                pcm_bytes = audio_array.tobytes()
                if frame_count == 1:
                    logger.info(f"AUDIO DEBUG: Final pcm_bytes size={len(pcm_bytes)}")

                # Put in queue (non-blocking, drop if full)
                try:
                    self._queue.put_nowait(pcm_bytes)
                except asyncio.QueueFull:
                    # Drop oldest frame
                    try:
                        self._queue.get_nowait()
                        self._queue.put_nowait(pcm_bytes)
                    except asyncio.QueueEmpty:
                        pass

            except MediaStreamError:
                logger.info("Media stream ended")
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error receiving audio frame: {e}")
                await asyncio.sleep(0.01)

    def _resample(self, audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Simple linear resampling.

        Args:
            audio: Input audio array.
            from_rate: Source sample rate.
            to_rate: Target sample rate.

        Returns:
            Resampled audio array.
        """
        if from_rate == to_rate:
            return audio

        duration = len(audio) / from_rate
        num_samples = int(duration * to_rate)

        # Linear interpolation
        indices = np.linspace(0, len(audio) - 1, num_samples)
        resampled = np.interp(indices, np.arange(len(audio)), audio.astype(np.float32))
        return resampled.astype(np.int16)

    async def read_frame(self) -> Optional[bytes]:
        """Read a single audio frame.

        Returns:
            PCM16 audio bytes or None if no frame available.
        """
        try:
            frame = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            return frame
        except asyncio.TimeoutError:
            # This is normal - just means no audio in the last 100ms
            return None

    async def read_frames(self):
        """Async generator that yields audio frames.

        Yields:
            PCM16 audio bytes.
        """
        logger.info(f"read_frames generator started, running={self._running}")
        frames_yielded = 0
        while self._running:
            frame = await self.read_frame()
            if frame:
                frames_yielded += 1
                if frames_yielded == 1:
                    logger.info(f"*** FIRST FRAME YIELDED *** size={len(frame)} bytes")
                elif frames_yielded % 50 == 0:
                    logger.info(f"Yielded {frames_yielded} frames")
                yield frame

    async def recv(self) -> AVAudioFrame:
        """Receive method required by MediaStreamTrack interface.

        Returns:
            An AV AudioFrame.
        """
        # This is called by aiortc internally
        return await self._track.recv()


class AudioOutputTrack(MediaStreamTrack):
    """Track that sends audio to the browser.

    This track accepts PCM16 audio bytes and encodes them to Opus
    for transmission over WebRTC.
    """

    kind = "audio"

    def __init__(self, sample_rate: int = 24000):
        """Initialize the output track.

        Args:
            sample_rate: Sample rate of the audio to send (TTS usually uses 24kHz).
        """
        super().__init__()
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self._sample_rate = sample_rate
        self._channels = CHANNELS
        self._pts = 0
        self._time_base = fractions.Fraction(1, sample_rate)
        self._silence = np.zeros(int(sample_rate * FRAME_DURATION_MS / 1000), dtype=np.int16).tobytes()

    @property
    def sample_rate(self) -> int:
        """Get the sample rate."""
        return self._sample_rate

    @property
    def channels(self) -> int:
        """Get the number of channels."""
        return self._channels

    async def write_frame(self, pcm_bytes: bytes) -> None:
        """Write a PCM audio frame to be sent.

        Args:
            pcm_bytes: PCM16 audio bytes.
        """
        try:
            self._queue.put_nowait(pcm_bytes)
        except asyncio.QueueFull:
            # Drop oldest frame
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(pcm_bytes)
            except asyncio.QueueEmpty:
                pass

    async def write_bytes(self, data: bytes) -> None:
        """Write raw audio bytes (alias for write_frame).

        Args:
            data: PCM16 audio bytes.
        """
        await self.write_frame(data)

    def clear_queue(self) -> None:
        """Clear all queued audio (for barge-in/interruption)."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def recv(self) -> AVAudioFrame:
        """Receive method called by aiortc to get the next frame to send.

        Returns:
            An AV AudioFrame ready for encoding and transmission.
        """
        # Calculate samples per frame based on sample rate
        samples_per_frame = int(self._sample_rate * FRAME_DURATION_MS / 1000)
        bytes_per_frame = samples_per_frame * SAMPLE_WIDTH

        # Try to get audio from queue
        try:
            pcm_bytes = await asyncio.wait_for(self._queue.get(), timeout=FRAME_DURATION_MS / 1000)
        except asyncio.TimeoutError:
            # Send silence if no audio available
            pcm_bytes = self._silence

        # Ensure we have the right amount of data
        if len(pcm_bytes) < bytes_per_frame:
            # Pad with silence
            pcm_bytes = pcm_bytes + bytes(bytes_per_frame - len(pcm_bytes))
        elif len(pcm_bytes) > bytes_per_frame:
            # Truncate (and re-queue the rest)
            remainder = pcm_bytes[bytes_per_frame:]
            pcm_bytes = pcm_bytes[:bytes_per_frame]
            try:
                self._queue.put_nowait(remainder)
            except asyncio.QueueFull:
                pass

        # Convert to numpy array
        audio_array = np.frombuffer(pcm_bytes, dtype=np.int16)

        # Create AV frame
        frame = AVAudioFrame(format="s16", layout="mono", samples=len(audio_array))
        frame.sample_rate = self._sample_rate
        frame.pts = self._pts
        frame.time_base = self._time_base

        # Copy audio data to frame
        frame.planes[0].update(audio_array.tobytes())

        # Update PTS for next frame
        self._pts += len(audio_array)

        return frame


class AudioRelayTrack(MediaStreamTrack):
    """Track that relays audio with optional processing.

    Useful for applying effects or monitoring audio levels.
    """

    kind = "audio"

    def __init__(self, source: MediaStreamTrack):
        """Initialize the relay track.

        Args:
            source: Source track to relay from.
        """
        super().__init__()
        self._source = source
        self._level = 0.0

    @property
    def level(self) -> float:
        """Get the current audio level (0.0 to 1.0)."""
        return self._level

    async def recv(self) -> AVAudioFrame:
        """Receive and relay an audio frame.

        Returns:
            The relayed audio frame.
        """
        frame = await self._source.recv()

        # Calculate audio level
        audio_array = frame.to_ndarray()
        if audio_array.size > 0:
            # RMS level normalized to 0-1
            rms = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
            self._level = min(1.0, rms / 32767)

        return frame
