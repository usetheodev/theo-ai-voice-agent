"""API endpoints for the AI Inference service."""

from .rest import router as rest_router
from .signaling import router as signaling_router
from .websocket import router as websocket_router
from .agents import router as agents_router

__all__ = ["rest_router", "signaling_router", "websocket_router", "agents_router"]
