"""WebRTC Transport implementing AudioTransportInterface."""

import asyncio
import logging
from typing import Any, AsyncIterator, Callable, Optional

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.sdp import candidate_from_sdp
from aiortc.contrib.media import MediaBlackhole

from voice_pipeline.interfaces.transport import (
    AudioConfig,
    AudioFrame,
    AudioTransportInterface,
    TransportConfig,
    TransportState,
)

from .events import DataChannelEventEmitter, EventType
from .tracks import AudioInputTrack, AudioOutputTrack

logger = logging.getLogger(__name__)


class WebRTCTransport(AudioTransportInterface):
    """WebRTC implementation of AudioTransportInterface.

    Provides bidirectional audio I/O over WebRTC peer connection.
    Uses Opus codec for efficient audio transmission.
    """

    name = "WebRTCTransport"

    def __init__(
        self,
        ice_servers: Optional[list[dict]] = None,
        input_sample_rate: int = 16000,
        output_sample_rate: int = 24000,
    ):
        """Initialize the WebRTC transport.

        Args:
            ice_servers: List of ICE server configurations.
            input_sample_rate: Sample rate for input audio (from browser).
            output_sample_rate: Sample rate for output audio (to browser, TTS).
        """
        self._ice_servers = ice_servers or [{"urls": ["stun:stun.l.google.com:19302"]}]
        self._input_sample_rate = input_sample_rate
        self._output_sample_rate = output_sample_rate

        # State
        self._state = TransportState.IDLE
        self._pc: Optional[RTCPeerConnection] = None
        self._input_track: Optional[AudioInputTrack] = None
        self._output_track: Optional[AudioOutputTrack] = None
        self._datachannel: Optional[Any] = None
        self._event_emitter = DataChannelEventEmitter()

        # Config
        self._config = TransportConfig(
            input_config=AudioConfig(sample_rate=input_sample_rate, channels=1, sample_width=2),
            output_config=AudioConfig(sample_rate=output_sample_rate, channels=1, sample_width=2),
        )

        # Callbacks
        self._input_callback: Optional[Callable[[AudioFrame], None]] = None
        self._state_callback: Optional[Callable[[TransportState], None]] = None
        self._error_callback: Optional[Callable[[Exception], None]] = None

        # Mute state
        self._input_muted = False
        self._output_muted = False

    @property
    def state(self) -> TransportState:
        """Current transport state."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Whether the transport is running."""
        return self._state == TransportState.RUNNING

    @property
    def config(self) -> TransportConfig:
        """Get transport configuration."""
        return self._config

    @property
    def event_emitter(self) -> DataChannelEventEmitter:
        """Get the DataChannel event emitter."""
        return self._event_emitter

    @property
    def peer_connection(self) -> Optional[RTCPeerConnection]:
        """Get the underlying peer connection."""
        return self._pc

    def _set_state(self, state: TransportState) -> None:
        """Update state and notify callback."""
        self._state = state
        if self._state_callback:
            try:
                self._state_callback(state)
            except Exception as e:
                logger.error(f"Error in state callback: {e}")

    async def start(self) -> None:
        """Start the WebRTC transport.

        Creates the peer connection and prepares for audio I/O.
        The actual connection is established via signaling (offer/answer).
        """
        if self._state not in (TransportState.IDLE, TransportState.STOPPED):
            logger.warning(f"Cannot start transport in state {self._state}")
            return

        self._set_state(TransportState.STARTING)

        try:
            # Create peer connection with proper RTCConfiguration
            ice_servers = []
            for server in self._ice_servers:
                urls = server.get("urls", [])
                if isinstance(urls, str):
                    urls = [urls]
                ice_servers.append(RTCIceServer(
                    urls=urls,
                    username=server.get("username"),
                    credential=server.get("credential"),
                ))

            config = RTCConfiguration(iceServers=ice_servers)
            self._pc = RTCPeerConnection(configuration=config)

            # Create output track for sending audio to browser
            self._output_track = AudioOutputTrack(sample_rate=self._output_sample_rate)

            # Add output track to peer connection
            self._pc.addTrack(self._output_track)

            # Set up event handlers
            @self._pc.on("track")
            async def on_track(track):
                logger.info(f"*** RECEIVED TRACK: kind={track.kind}, id={track.id} ***")
                if track.kind == "audio":
                    logger.info("Creating AudioInputTrack...")
                    self._input_track = AudioInputTrack(track)
                    logger.info("Starting AudioInputTrack...")
                    await self._input_track.start()
                    logger.info(f"AudioInputTrack started! Running: {self._input_track._running}")
                    await self._event_emitter.emit(
                        EventType.CONNECTED, {"message": "Audio track connected"}
                    )

            @self._pc.on("datachannel")
            def on_datachannel(channel):
                logger.info(f"DataChannel received: {channel.label}")
                self._datachannel = channel
                self._event_emitter.set_datachannel(channel)

            @self._pc.on("connectionstatechange")
            async def on_connection_state_change():
                state = self._pc.connectionState
                logger.info(f"Connection state: {state}")

                if state == "connected":
                    self._set_state(TransportState.RUNNING)
                    await self._event_emitter.emit(
                        EventType.CONNECTED, {"state": "connected"}
                    )
                elif state == "disconnected":
                    self._set_state(TransportState.PAUSED)
                    await self._event_emitter.emit(
                        EventType.DISCONNECTED, {"state": "disconnected"}
                    )
                elif state == "failed":
                    self._set_state(TransportState.ERROR)
                    await self._event_emitter.emit(
                        EventType.ERROR, {"error": "Connection failed"}
                    )
                elif state == "closed":
                    self._set_state(TransportState.STOPPED)

            @self._pc.on("iceconnectionstatechange")
            async def on_ice_connection_state_change():
                logger.info(f"ICE connection state: {self._pc.iceConnectionState}")

            # Start event emitter
            await self._event_emitter.start()

            logger.info("WebRTC transport started, waiting for connection")

        except Exception as e:
            self._set_state(TransportState.ERROR)
            if self._error_callback:
                self._error_callback(e)
            raise

    async def stop(self) -> None:
        """Stop the WebRTC transport.

        Closes the peer connection and releases resources.
        """
        if self._state == TransportState.STOPPED:
            return

        self._set_state(TransportState.STOPPING)

        try:
            # Stop event emitter
            await self._event_emitter.stop()

            # Stop input track
            if self._input_track:
                await self._input_track.stop()
                self._input_track = None

            # Close peer connection
            if self._pc:
                await self._pc.close()
                self._pc = None

            self._output_track = None
            self._datachannel = None

            self._set_state(TransportState.STOPPED)
            logger.info("WebRTC transport stopped")

        except Exception as e:
            self._set_state(TransportState.ERROR)
            if self._error_callback:
                self._error_callback(e)
            raise

    async def handle_offer(self, sdp: dict) -> dict:
        """Handle an SDP offer from the client.

        Args:
            sdp: SDP offer dictionary with 'type' and 'sdp' keys.

        Returns:
            SDP answer dictionary.
        """
        if not self._pc:
            raise RuntimeError("Transport not started")

        # Set remote description (the offer)
        offer = RTCSessionDescription(sdp=sdp["sdp"], type=sdp["type"])
        await self._pc.setRemoteDescription(offer)

        # Create answer
        answer = await self._pc.createAnswer()
        await self._pc.setLocalDescription(answer)

        return {"type": answer.type, "sdp": answer.sdp}

    async def add_ice_candidate(self, candidate: dict) -> None:
        """Add an ICE candidate from the client.

        Args:
            candidate: ICE candidate dictionary.
        """
        if not self._pc:
            raise RuntimeError("Transport not started")

        if candidate and candidate.get("candidate"):
            candidate_str = candidate["candidate"]
            # Skip empty candidates (end-of-candidates signal)
            if not candidate_str:
                return

            try:
                # Parse the candidate string using aiortc's parser
                ice_candidate = candidate_from_sdp(candidate_str)
                ice_candidate.sdpMid = candidate.get("sdpMid")
                ice_candidate.sdpMLineIndex = candidate.get("sdpMLineIndex")
                await self._pc.addIceCandidate(ice_candidate)
            except Exception as e:
                logger.warning(f"Could not parse ICE candidate: {e}")

    async def read_frames(self) -> AsyncIterator[AudioFrame]:
        """Read audio frames from input (browser microphone).

        Yields:
            AudioFrame objects as they are captured.
        """
        # Wait for input track to be available (with timeout)
        wait_time = 0
        logger.info(f"read_frames called, input_track={self._input_track}, state={self._state}")

        while not self._input_track and wait_time < 30:
            logger.info(f"Waiting for input track... ({wait_time:.1f}s)")
            await asyncio.sleep(0.5)
            wait_time += 0.5

        if not self._input_track:
            logger.error("No input track available after 30 seconds!")
            return

        logger.info(f"Input track available! Track running: {self._input_track._running}")

        async for pcm_bytes in self._input_track.read_frames():
            if self._input_muted:
                continue

            frame = AudioFrame(
                data=pcm_bytes,
                sample_rate=self._input_sample_rate,
                channels=1,
                sample_width=2,
            )

            if self._input_callback:
                try:
                    self._input_callback(frame)
                except Exception as e:
                    logger.error(f"Error in input callback: {e}")

            yield frame

    async def write_frame(self, frame: AudioFrame) -> None:
        """Write an audio frame to output (browser speaker).

        Args:
            frame: Audio frame to send.
        """
        if self._output_muted:
            return

        if self._output_track:
            await self._output_track.write_frame(frame.data)
        else:
            logger.warning("No output track available")

    async def write_bytes(self, data: bytes) -> None:
        """Write raw audio bytes to output.

        Args:
            data: Raw PCM16 audio bytes.
        """
        if self._output_muted:
            logger.debug("Output muted, skipping audio")
            return

        if self._output_track:
            logger.info(f"*** SENDING AUDIO *** {len(data)} bytes to output track")
            await self._output_track.write_bytes(data)
        else:
            logger.warning("No output track available")

    def clear_output_queue(self) -> None:
        """Clear all queued output audio (for barge-in/interruption)."""
        if self._output_track:
            self._output_track.clear_queue()

    async def set_input_muted(self, muted: bool) -> None:
        """Mute/unmute input.

        Args:
            muted: Whether to mute input.
        """
        self._input_muted = muted

    async def set_output_muted(self, muted: bool) -> None:
        """Mute/unmute output.

        Args:
            muted: Whether to mute output.
        """
        self._output_muted = muted

    async def get_input_level(self) -> float:
        """Get current input audio level.

        Returns:
            Audio level from 0.0 to 1.0.
        """
        # Would need to compute from input frames
        return 0.0

    async def get_output_level(self) -> float:
        """Get current output audio level.

        Returns:
            Audio level from 0.0 to 1.0.
        """
        return 0.0

    async def pause(self) -> None:
        """Pause the transport."""
        self._input_muted = True
        self._output_muted = True
        self._set_state(TransportState.PAUSED)

    async def resume(self) -> None:
        """Resume the transport."""
        self._input_muted = False
        self._output_muted = False
        self._set_state(TransportState.RUNNING)
