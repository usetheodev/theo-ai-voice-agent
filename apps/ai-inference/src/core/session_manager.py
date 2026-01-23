"""Session manager for handling multiple realtime sessions."""

import asyncio
import logging
from typing import Dict, List, Optional

from .config import Settings, get_settings
from .session import RealtimeSession, SessionState

from ..models.session import SessionConfig

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages multiple realtime sessions.

    This class is responsible for creating, storing, and managing the lifecycle
    of realtime sessions.
    """

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize the session manager.

        Args:
            settings: Optional settings. Uses global settings if not provided.
        """
        self._settings = settings or get_settings()
        self._sessions: Dict[str, RealtimeSession] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    @property
    def max_sessions(self) -> int:
        """Maximum number of concurrent sessions."""
        return self._settings.max_sessions

    @property
    def session_timeout(self) -> int:
        """Session timeout in seconds."""
        return self._settings.session_timeout_seconds

    async def create_session(
        self,
        config: Optional[SessionConfig] = None,
        session_id: Optional[str] = None,
    ) -> RealtimeSession:
        """Create a new session.

        Args:
            config: Optional session configuration.
            session_id: Optional session ID. Generated if not provided.

        Returns:
            The created session.

        Raises:
            RuntimeError: If maximum sessions limit is reached.
        """
        async with self._lock:
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError(
                    f"Maximum sessions limit reached ({self.max_sessions})"
                )

            session = RealtimeSession(session_id=session_id, config=config)
            self._sessions[session.id] = session

            logger.info(
                "Session created",
                extra={
                    "session_id": session.id,
                    "total_sessions": len(self._sessions),
                },
            )

            return session

    async def get_session(self, session_id: str) -> Optional[RealtimeSession]:
        """Get a session by ID.

        Args:
            session_id: The session ID to look up.

        Returns:
            The session if found, None otherwise.
        """
        return self._sessions.get(session_id)

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: The session ID to delete.

        Returns:
            True if deleted, False if session not found.
        """
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                session.close()
                logger.info(
                    "Session deleted",
                    extra={
                        "session_id": session_id,
                        "total_sessions": len(self._sessions),
                    },
                )
                return True
            return False

    async def list_sessions(self) -> List[str]:
        """List all active session IDs.

        Returns:
            List of session IDs.
        """
        return list(self._sessions.keys())

    async def get_session_count(self) -> int:
        """Get the number of active sessions.

        Returns:
            Number of active sessions.
        """
        return len(self._sessions)

    async def get_session_stats(self) -> Dict:
        """Get statistics about sessions.

        Returns:
            Dictionary with session statistics.
        """
        states: Dict[str, int] = {}
        for session in self._sessions.values():
            state = session.state.value
            states[state] = states.get(state, 0) + 1

        return {
            "total_sessions": len(self._sessions),
            "max_sessions": self.max_sessions,
            "sessions_by_state": states,
        }

    async def cleanup_expired(self) -> int:
        """Remove expired sessions.

        Returns:
            Number of sessions removed.
        """
        async with self._lock:
            expired = [
                sid
                for sid, session in self._sessions.items()
                if session.is_expired(self.session_timeout)
            ]

            for session_id in expired:
                session = self._sessions.pop(session_id)
                session.close()
                logger.info(
                    "Session expired and removed",
                    extra={"session_id": session_id},
                )

            return len(expired)

    async def start_cleanup_task(self, interval_seconds: int = 60) -> None:
        """Start the background cleanup task.

        Args:
            interval_seconds: Interval between cleanup runs.
        """
        if self._cleanup_task is not None:
            return

        async def cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    removed = await self.cleanup_expired()
                    if removed > 0:
                        logger.info(
                            "Cleanup completed",
                            extra={"sessions_removed": removed},
                        )
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")

        self._cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info("Cleanup task started")

    async def stop_cleanup_task(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Cleanup task stopped")

    async def close_all(self) -> None:
        """Close all sessions and stop cleanup task."""
        await self.stop_cleanup_task()

        async with self._lock:
            for session in self._sessions.values():
                session.close()
            count = len(self._sessions)
            self._sessions.clear()

        logger.info("All sessions closed", extra={"sessions_closed": count})


# Global session manager instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get the global session manager instance.

    Returns:
        The session manager singleton.
    """
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


async def init_session_manager() -> SessionManager:
    """Initialize and start the session manager.

    Returns:
        The initialized session manager.
    """
    manager = get_session_manager()
    await manager.start_cleanup_task()
    return manager


async def shutdown_session_manager() -> None:
    """Shutdown the session manager."""
    global _session_manager
    if _session_manager is not None:
        await _session_manager.close_all()
        _session_manager = None
