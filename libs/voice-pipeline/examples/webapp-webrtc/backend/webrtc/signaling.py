"""WebSocket signaling server for WebRTC connection establishment."""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class SignalingMessageType(str, Enum):
    """Types of signaling messages."""

    # Client -> Server
    OFFER = "offer"
    ANSWER = "answer"
    ICE_CANDIDATE = "ice_candidate"
    HANGUP = "hangup"

    # Server -> Client
    SESSION_CREATED = "session_created"
    OFFER_RESPONSE = "offer_response"
    ERROR = "error"

    # Config
    CONFIG = "config"


@dataclass
class SignalingMessage:
    """A signaling message for WebRTC negotiation."""

    type: SignalingMessageType
    data: dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(
            {
                "type": self.type.value,
                "data": self.data,
                "session_id": self.session_id,
            }
        )

    @classmethod
    def from_json(cls, json_str: str) -> "SignalingMessage":
        """Deserialize from JSON string."""
        obj = json.loads(json_str)
        return cls(
            type=SignalingMessageType(obj["type"]),
            data=obj.get("data", {}),
            session_id=obj.get("session_id"),
        )


# Callback types
OnOfferCallback = Callable[[str, dict], Any]  # (session_id, sdp) -> answer_sdp
OnIceCandidateCallback = Callable[[str, dict], Any]  # (session_id, candidate) -> None
OnHangupCallback = Callable[[str], Any]  # (session_id) -> None


class SignalingSession:
    """A signaling session for a single WebRTC connection."""

    def __init__(self, session_id: str, websocket: WebSocket):
        """Initialize a signaling session.

        Args:
            session_id: Unique session identifier.
            websocket: WebSocket connection for this session.
        """
        self.session_id = session_id
        self.websocket = websocket
        self.ice_candidates: list[dict] = []
        self.local_description: Optional[dict] = None
        self.remote_description: Optional[dict] = None
        self.is_connected = False

    async def send(self, message: SignalingMessage) -> None:
        """Send a signaling message.

        Args:
            message: Message to send.
        """
        message.session_id = self.session_id
        await self.websocket.send_text(message.to_json())


class SignalingServer:
    """WebSocket-based signaling server for WebRTC connections."""

    def __init__(self):
        """Initialize the signaling server."""
        self._sessions: dict[str, SignalingSession] = {}
        self._on_offer: Optional[OnOfferCallback] = None
        self._on_ice_candidate: Optional[OnIceCandidateCallback] = None
        self._on_hangup: Optional[OnHangupCallback] = None
        self._ice_servers: list[dict] = [{"urls": ["stun:stun.l.google.com:19302"]}]

    def set_ice_servers(self, ice_servers: list[dict]) -> None:
        """Set the ICE servers configuration.

        Args:
            ice_servers: List of ICE server configurations.
        """
        self._ice_servers = ice_servers

    def on_offer(self, callback: OnOfferCallback) -> None:
        """Register callback for when an offer is received.

        Args:
            callback: Async function (session_id, sdp) -> answer_sdp.
        """
        self._on_offer = callback

    def on_ice_candidate(self, callback: OnIceCandidateCallback) -> None:
        """Register callback for when an ICE candidate is received.

        Args:
            callback: Async function (session_id, candidate) -> None.
        """
        self._on_ice_candidate = callback

    def on_hangup(self, callback: OnHangupCallback) -> None:
        """Register callback for when a hangup is received.

        Args:
            callback: Async function (session_id) -> None.
        """
        self._on_hangup = callback

    def get_session(self, session_id: str) -> Optional[SignalingSession]:
        """Get a session by ID.

        Args:
            session_id: Session ID to look up.

        Returns:
            The session or None if not found.
        """
        return self._sessions.get(session_id)

    async def handle_websocket(self, websocket: WebSocket) -> str:
        """Handle a new WebSocket connection.

        Args:
            websocket: The WebSocket connection.

        Returns:
            The session ID for this connection.
        """
        await websocket.accept()

        # Create session
        session_id = str(uuid.uuid4())
        session = SignalingSession(session_id, websocket)
        self._sessions[session_id] = session

        logger.info(f"New signaling session: {session_id}")

        # Send session created message with config
        await session.send(
            SignalingMessage(
                type=SignalingMessageType.SESSION_CREATED,
                data={
                    "session_id": session_id,
                    "ice_servers": self._ice_servers,
                },
            )
        )

        try:
            # Message handling loop
            while True:
                try:
                    data = await websocket.receive_text()
                    message = SignalingMessage.from_json(data)
                    await self._handle_message(session, message)
                except WebSocketDisconnect:
                    logger.info(f"Session {session_id} disconnected")
                    break
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from session {session_id}: {e}")
                    await session.send(
                        SignalingMessage(
                            type=SignalingMessageType.ERROR,
                            data={"error": "Invalid JSON"},
                        )
                    )
                except Exception as e:
                    logger.error(f"Error in session {session_id}: {e}")
                    await session.send(
                        SignalingMessage(
                            type=SignalingMessageType.ERROR,
                            data={"error": str(e)},
                        )
                    )

        finally:
            # Cleanup
            if session_id in self._sessions:
                del self._sessions[session_id]
            if self._on_hangup:
                try:
                    result = self._on_hangup(session_id)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.error(f"Error in hangup callback: {e}")

        return session_id

    async def _handle_message(self, session: SignalingSession, message: SignalingMessage) -> None:
        """Handle an incoming signaling message.

        Args:
            session: The session that sent the message.
            message: The message to handle.
        """
        logger.debug(f"Received {message.type.value} from {session.session_id}")

        if message.type == SignalingMessageType.OFFER:
            await self._handle_offer(session, message.data)

        elif message.type == SignalingMessageType.ICE_CANDIDATE:
            await self._handle_ice_candidate(session, message.data)

        elif message.type == SignalingMessageType.HANGUP:
            await self._handle_hangup(session)

        else:
            logger.warning(f"Unknown message type: {message.type}")

    async def _handle_offer(self, session: SignalingSession, sdp: dict) -> None:
        """Handle an SDP offer from the client.

        Args:
            session: The session that sent the offer.
            sdp: The SDP offer data.
        """
        session.remote_description = sdp

        if self._on_offer:
            try:
                # Get answer from callback
                result = self._on_offer(session.session_id, sdp)
                if asyncio.iscoroutine(result):
                    answer_sdp = await result
                else:
                    answer_sdp = result

                session.local_description = answer_sdp
                session.is_connected = True

                # Send answer back
                await session.send(
                    SignalingMessage(
                        type=SignalingMessageType.OFFER_RESPONSE,
                        data=answer_sdp,
                    )
                )

            except Exception as e:
                logger.error(f"Error handling offer: {e}")
                await session.send(
                    SignalingMessage(
                        type=SignalingMessageType.ERROR,
                        data={"error": f"Failed to create answer: {str(e)}"},
                    )
                )
        else:
            logger.error("No offer handler registered")
            await session.send(
                SignalingMessage(
                    type=SignalingMessageType.ERROR,
                    data={"error": "Server not configured to handle offers"},
                )
            )

    async def _handle_ice_candidate(self, session: SignalingSession, candidate: dict) -> None:
        """Handle an ICE candidate from the client.

        Args:
            session: The session that sent the candidate.
            candidate: The ICE candidate data.
        """
        session.ice_candidates.append(candidate)

        if self._on_ice_candidate:
            try:
                result = self._on_ice_candidate(session.session_id, candidate)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Error handling ICE candidate: {e}")

    async def _handle_hangup(self, session: SignalingSession) -> None:
        """Handle a hangup from the client.

        Args:
            session: The session that sent the hangup.
        """
        session.is_connected = False

        if self._on_hangup:
            try:
                result = self._on_hangup(session.session_id)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Error handling hangup: {e}")

    async def send_ice_candidate(self, session_id: str, candidate: dict) -> None:
        """Send an ICE candidate to the client.

        Args:
            session_id: Session to send to.
            candidate: ICE candidate data.
        """
        session = self._sessions.get(session_id)
        if session:
            await session.send(
                SignalingMessage(
                    type=SignalingMessageType.ICE_CANDIDATE,
                    data=candidate,
                )
            )

    async def close_session(self, session_id: str) -> None:
        """Close a signaling session.

        Args:
            session_id: Session to close.
        """
        session = self._sessions.get(session_id)
        if session:
            try:
                await session.send(
                    SignalingMessage(
                        type=SignalingMessageType.HANGUP,
                        data={},
                    )
                )
                await session.websocket.close()
            except Exception:
                pass
            finally:
                if session_id in self._sessions:
                    del self._sessions[session_id]

    @property
    def active_sessions(self) -> list[str]:
        """Get list of active session IDs."""
        return list(self._sessions.keys())

    @property
    def session_count(self) -> int:
        """Get number of active sessions."""
        return len(self._sessions)
