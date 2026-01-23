"""WebRTC connection wrapper using aiortc."""

import asyncio
import logging
from typing import Callable, List, Optional

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay

from ..core.config import get_settings
from ..core.session import RealtimeSession
from .datachannel import DataChannelHandler
from .tracks import AudioInputHandler, AudioOutputTrack

logger = logging.getLogger(__name__)


class RealtimeConnection:
    """Wrapper for RTCPeerConnection with integrated session management.

    This class manages the WebRTC connection lifecycle, including:
    - ICE server configuration (STUN/TURN)
    - Audio track handling (bidirectional)
    - DataChannel for event communication
    - Session state synchronization
    """

    def __init__(
        self,
        session: RealtimeSession,
        on_close: Optional[Callable[[], None]] = None,
    ):
        """Initialize the WebRTC connection.

        Args:
            session: The associated RealtimeSession instance.
            on_close: Optional callback when connection closes.
        """
        self.session = session
        self.on_close = on_close
        self._closed = False

        settings = get_settings()

        # Build ICE server configuration
        ice_servers = self._build_ice_servers(settings)

        # Create RTCPeerConnection
        self.pc = RTCPeerConnection(
            configuration=RTCConfiguration(iceServers=ice_servers)
        )

        # Media relay for track management
        self.relay = MediaRelay()

        # Handlers
        self.datachannel_handler: Optional[DataChannelHandler] = None
        self.audio_input_handler: Optional[AudioInputHandler] = None
        self.audio_output_track: Optional[AudioOutputTrack] = None

        # Setup event handlers
        self._setup_event_handlers()

        logger.info(
            "RealtimeConnection created",
            extra={
                "session_id": session.id,
                "ice_servers": len(ice_servers),
            },
        )

    def _build_ice_servers(self, settings) -> List[RTCIceServer]:
        """Build ICE server configuration from settings.

        Args:
            settings: Application settings.

        Returns:
            List of RTCIceServer instances.
        """
        ice_servers = []

        # Add STUN servers
        for stun_url in settings.stun_servers:
            ice_servers.append(RTCIceServer(urls=stun_url))

        # Add TURN server if configured
        if settings.turn_server and settings.turn_username and settings.turn_password:
            ice_servers.append(
                RTCIceServer(
                    urls=settings.turn_server,
                    username=settings.turn_username,
                    credential=settings.turn_password,
                )
            )

        return ice_servers

    def _setup_event_handlers(self) -> None:
        """Setup RTCPeerConnection event handlers."""

        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            state = self.pc.connectionState
            logger.info(
                "Connection state changed",
                extra={
                    "session_id": self.session.id,
                    "state": state,
                },
            )

            if state in ("failed", "closed"):
                await self.close()

        @self.pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            state = self.pc.iceConnectionState
            logger.debug(
                "ICE connection state changed",
                extra={
                    "session_id": self.session.id,
                    "ice_state": state,
                },
            )

            if state == "failed":
                logger.warning(
                    "ICE connection failed",
                    extra={"session_id": self.session.id},
                )

        @self.pc.on("datachannel")
        def on_datachannel(channel):
            logger.info(
                "DataChannel received",
                extra={
                    "session_id": self.session.id,
                    "channel_label": channel.label,
                },
            )

            if channel.label == "oai-events":
                self._setup_datachannel(channel)

        @self.pc.on("track")
        def on_track(track):
            logger.info(
                "Track received",
                extra={
                    "session_id": self.session.id,
                    "kind": track.kind,
                },
            )

            if track.kind == "audio":
                self._setup_audio_input(track)

    def _setup_datachannel(self, channel) -> None:
        """Setup DataChannel for event communication.

        Args:
            channel: The RTCDataChannel instance.
        """
        self.datachannel_handler = DataChannelHandler(
            session=self.session,
            datachannel=channel,
        )

        @channel.on("open")
        async def on_open():
            logger.info(
                "DataChannel opened",
                extra={"session_id": self.session.id},
            )
            # Send session.created event
            await self.datachannel_handler.send_session_created()

        @channel.on("message")
        async def on_message(message):
            await self.datachannel_handler.on_message(message)

        @channel.on("close")
        async def on_close():
            logger.info(
                "DataChannel closed",
                extra={"session_id": self.session.id},
            )

    def _setup_audio_input(self, track) -> None:
        """Setup audio input track handler.

        Args:
            track: The incoming audio MediaStreamTrack.
        """
        self.audio_input_handler = AudioInputHandler(
            session=self.session,
            track=self.relay.subscribe(track),
        )
        # Start processing audio in background
        asyncio.create_task(self.audio_input_handler.start())

    async def handle_offer(self, sdp: str) -> str:
        """Process SDP offer and return SDP answer.

        Args:
            sdp: The SDP offer string from the client.

        Returns:
            The SDP answer string.
        """
        # Parse the offer
        offer = RTCSessionDescription(sdp=sdp, type="offer")
        await self.pc.setRemoteDescription(offer)

        # Check if offer includes audio - only add output track if client sends audio
        has_audio = "m=audio" in sdp
        if has_audio:
            # Create audio output track for sending audio to client
            self.audio_output_track = AudioOutputTrack(session=self.session)
            self.pc.addTrack(self.audio_output_track)
            logger.info(
                "Audio track added to answer",
                extra={"session_id": self.session.id},
            )

        # Create and set local description (answer)
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)

        logger.info(
            "SDP exchange completed",
            extra={
                "session_id": self.session.id,
                "has_audio": has_audio,
            },
        )

        return self.pc.localDescription.sdp

    async def close(self) -> None:
        """Close the WebRTC connection and cleanup resources."""
        if self._closed:
            return

        self._closed = True

        # Stop audio handlers
        if self.audio_input_handler:
            await self.audio_input_handler.stop()

        if self.audio_output_track:
            self.audio_output_track.stop()

        # Close peer connection
        await self.pc.close()

        # Invoke close callback
        if self.on_close:
            self.on_close()

        logger.info(
            "RealtimeConnection closed",
            extra={"session_id": self.session.id},
        )

    @property
    def is_connected(self) -> bool:
        """Check if the connection is established.

        Returns:
            True if connected, False otherwise.
        """
        return (
            not self._closed
            and self.pc.connectionState == "connected"
        )

    @property
    def connection_state(self) -> str:
        """Get the current connection state.

        Returns:
            The connection state string.
        """
        return self.pc.connectionState
