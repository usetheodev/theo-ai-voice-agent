"""WebRTC signaling endpoints for the Realtime API."""

import logging
import time
from typing import Dict, Optional

import jwt
from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..core.config import get_settings
from ..core.session_manager import get_session_manager
from ..models.session import SessionConfig
from ..webrtc.connection import RealtimeConnection

logger = logging.getLogger(__name__)

router = APIRouter()

# Store for active WebRTC connections
_connections: Dict[str, RealtimeConnection] = {}


class ClientSecret(BaseModel):
    """Ephemeral client secret for WebRTC authentication."""

    value: str = Field(description="JWT token for authentication")
    expires_at: int = Field(description="Unix timestamp when token expires")


class SessionResponse(BaseModel):
    """Response for session creation."""

    id: str = Field(description="Session ID")
    object: str = Field(default="realtime.session", description="Object type")
    client_secret: ClientSecret = Field(description="Ephemeral authentication token")


class SessionCreateRequest(BaseModel):
    """Request body for creating a session."""

    model: Optional[str] = Field(
        default=None,
        description="Model name (ignored, uses local models)"
    )
    instructions: Optional[str] = Field(
        default=None,
        description="System instructions for the assistant"
    )
    voice: Optional[str] = Field(
        default=None,
        description="Voice for audio output"
    )
    input_audio_format: Optional[str] = Field(
        default=None,
        description="Input audio format"
    )
    output_audio_format: Optional[str] = Field(
        default=None,
        description="Output audio format"
    )
    temperature: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature"
    )
    max_response_output_tokens: Optional[int] = Field(
        default=None,
        description="Maximum output tokens"
    )


def _generate_client_secret(session_id: str) -> ClientSecret:
    """Generate an ephemeral client secret for a session.

    Args:
        session_id: The session ID to encode in the token.

    Returns:
        A ClientSecret with JWT token and expiry.
    """
    settings = get_settings()

    expires_at = int(time.time()) + settings.token_expiry_seconds

    payload = {
        "session_id": session_id,
        "exp": expires_at,
        "iat": int(time.time()),
    }

    token = jwt.encode(
        payload,
        settings.token_secret,
        algorithm="HS256",
    )

    return ClientSecret(
        value=token,
        expires_at=expires_at,
    )


def _verify_client_secret(token: str, session_id: str) -> bool:
    """Verify a client secret token.

    Args:
        token: The JWT token to verify.
        session_id: The expected session ID.

    Returns:
        True if valid, False otherwise.
    """
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.token_secret,
            algorithms=["HS256"],
        )
        return payload.get("session_id") == session_id
    except jwt.ExpiredSignatureError:
        logger.warning("Client secret expired")
        return False
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid client secret: {e}")
        return False


@router.post("/v1/realtime/sessions", response_model=SessionResponse)
async def create_session(
    request: Optional[SessionCreateRequest] = None,
) -> SessionResponse:
    """Create a new Realtime session.

    This endpoint creates a new session and returns an ephemeral client
    secret that can be used to authenticate the WebRTC connection.

    The session configuration can be optionally provided in the request body.
    """
    session_manager = get_session_manager()

    # Build session config from request
    config = None
    if request:
        config_dict = {}
        if request.instructions:
            config_dict["instructions"] = request.instructions
        if request.voice:
            config_dict["voice"] = request.voice
        if request.input_audio_format:
            config_dict["input_audio_format"] = request.input_audio_format
        if request.output_audio_format:
            config_dict["output_audio_format"] = request.output_audio_format
        if request.temperature is not None:
            config_dict["temperature"] = request.temperature
        if request.max_response_output_tokens is not None:
            config_dict["max_response_output_tokens"] = request.max_response_output_tokens

        if config_dict:
            config = SessionConfig(**config_dict)

    # Create session
    try:
        session = await session_manager.create_session(config)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Generate client secret
    client_secret = _generate_client_secret(session.id)

    logger.info(
        "Realtime session created",
        extra={
            "session_id": session.id,
            "expires_at": client_secret.expires_at,
        },
    )

    return SessionResponse(
        id=session.id,
        client_secret=client_secret,
    )


@router.post("/v1/realtime/sessions/{session_id}/sdp")
async def sdp_exchange(
    session_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Response:
    """Exchange SDP offer/answer for WebRTC connection.

    This endpoint accepts an SDP offer from the client and returns
    an SDP answer to establish the WebRTC connection.

    The request body should contain the SDP offer as plain text.
    Authentication is required via Bearer token in the Authorization header.
    """
    # Verify authorization
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header required",
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization format",
        )

    token = authorization[7:]  # Remove "Bearer " prefix

    if not _verify_client_secret(token, session_id):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired client secret",
        )

    # Get session
    session_manager = get_session_manager()
    session = await session_manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found",
        )

    # Read SDP offer from request body
    content_type = request.headers.get("content-type", "")

    if "application/sdp" in content_type:
        sdp_offer = (await request.body()).decode("utf-8")
    elif "text/plain" in content_type:
        sdp_offer = (await request.body()).decode("utf-8")
    else:
        # Try to parse as JSON (alternative format)
        try:
            body = await request.json()
            sdp_offer = body.get("sdp")
            if not sdp_offer:
                raise HTTPException(
                    status_code=400,
                    detail="Missing 'sdp' field in JSON body",
                )
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid content type. Expected application/sdp, text/plain, or JSON",
            )

    # Clean up existing connection if any
    if session_id in _connections:
        old_conn = _connections.pop(session_id)
        await old_conn.close()

    # Create WebRTC connection
    def on_close():
        _connections.pop(session_id, None)

    connection = RealtimeConnection(
        session=session,
        on_close=on_close,
    )
    _connections[session_id] = connection

    # Process SDP offer and get answer
    try:
        sdp_answer = await connection.handle_offer(sdp_offer)
    except Exception as e:
        logger.exception(
            "SDP exchange failed",
            extra={"session_id": session_id},
        )
        await connection.close()
        _connections.pop(session_id, None)
        raise HTTPException(
            status_code=400,
            detail=f"SDP exchange failed: {e}",
        )

    logger.info(
        "SDP exchange completed",
        extra={"session_id": session_id},
    )

    return Response(
        content=sdp_answer,
        media_type="application/sdp",
    )


@router.delete("/v1/realtime/sessions/{session_id}")
async def close_session(session_id: str) -> Dict[str, str]:
    """Close a Realtime session.

    This endpoint closes the WebRTC connection and deletes the session.
    """
    # Close WebRTC connection
    if session_id in _connections:
        connection = _connections.pop(session_id)
        await connection.close()

    # Delete session
    session_manager = get_session_manager()
    deleted = await session_manager.delete_session(session_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found",
        )

    logger.info(
        "Realtime session closed",
        extra={"session_id": session_id},
    )

    return {"status": "closed", "session_id": session_id}


@router.get("/v1/realtime/sessions/{session_id}")
async def get_session(session_id: str) -> Dict:
    """Get information about a Realtime session.

    Returns session details including connection status.
    """
    session_manager = get_session_manager()
    session = await session_manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found",
        )

    connection = _connections.get(session_id)

    return {
        "id": session.id,
        "object": "realtime.session",
        "state": session.state.value,
        "created_at": session.created_at.isoformat(),
        "connection": {
            "connected": connection.is_connected if connection else False,
            "state": connection.connection_state if connection else "disconnected",
        },
        "config": session.config.model_dump(exclude_none=True),
    }
