"""REST API endpoints for the AI Inference service."""

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from .dependencies import SessionManagerDep, SettingsDep

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    sessions_active: int


class MetricsResponse(BaseModel):
    """Metrics response."""

    total_sessions: int
    max_sessions: int
    sessions_by_state: Dict[str, int]


class SessionInfo(BaseModel):
    """Session information."""

    id: str
    state: str
    created_at: str
    last_activity: str
    conversation_items: int
    audio_buffer_duration_ms: int
    has_active_response: bool


class SessionsListResponse(BaseModel):
    """Sessions list response."""

    sessions: List[SessionInfo]
    total: int


@router.get("/health", response_model=HealthResponse)
async def health_check(session_manager: SessionManagerDep) -> HealthResponse:
    """Health check endpoint.

    Returns the service health status and number of active sessions.
    """
    session_count = await session_manager.get_session_count()
    return HealthResponse(status="healthy", sessions_active=session_count)


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(session_manager: SessionManagerDep) -> MetricsResponse:
    """Get service metrics.

    Returns detailed metrics about the service and sessions.
    """
    stats = await session_manager.get_session_stats()
    return MetricsResponse(**stats)


@router.get("/sessions", response_model=SessionsListResponse)
async def list_sessions(session_manager: SessionManagerDep) -> SessionsListResponse:
    """List all active sessions.

    This endpoint is for debugging/monitoring purposes.
    """
    session_ids = await session_manager.list_sessions()
    sessions = []

    for session_id in session_ids:
        session = await session_manager.get_session(session_id)
        if session:
            session_dict = session.to_dict()
            sessions.append(
                SessionInfo(
                    id=session_dict["id"],
                    state=session_dict["state"],
                    created_at=session_dict["created_at"],
                    last_activity=session_dict["last_activity"],
                    conversation_items=session_dict["conversation_items"],
                    audio_buffer_duration_ms=session_dict["audio_buffer_duration_ms"],
                    has_active_response=session_dict["has_active_response"],
                )
            )

    return SessionsListResponse(sessions=sessions, total=len(sessions))


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str, session_manager: SessionManagerDep
) -> Dict[str, Any]:
    """Get details for a specific session.

    Args:
        session_id: The session ID to look up.

    Returns:
        Session details.

    Raises:
        HTTPException: If session not found.
    """
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )
    return session.to_dict()


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str, session_manager: SessionManagerDep
) -> Dict[str, str]:
    """Delete a specific session.

    Args:
        session_id: The session ID to delete.

    Returns:
        Confirmation message.

    Raises:
        HTTPException: If session not found.
    """
    deleted = await session_manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )
    return {"message": f"Session {session_id} deleted"}
