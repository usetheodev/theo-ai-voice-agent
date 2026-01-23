"""FastAPI dependencies for the AI Inference service."""

from typing import Annotated

from fastapi import Depends, HTTPException, status

from ..core.config import Settings, get_settings
from ..core.session_manager import SessionManager, get_session_manager


def get_settings_dependency() -> Settings:
    """Dependency for getting application settings."""
    return get_settings()


def get_session_manager_dependency() -> SessionManager:
    """Dependency for getting the session manager."""
    return get_session_manager()


# Type aliases for cleaner dependency injection
SettingsDep = Annotated[Settings, Depends(get_settings_dependency)]
SessionManagerDep = Annotated[SessionManager, Depends(get_session_manager_dependency)]
