"""FastAPI application entry point for the AI Inference service."""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import rest_router, signaling_router, websocket_router
from .core.config import get_settings
from .core.session_manager import init_session_manager, shutdown_session_manager


def setup_logging() -> None:
    """Configure logging based on settings."""
    settings = get_settings()

    log_format = (
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        if settings.log_format == "text"
        else '{"time": "%(asctime)s", "name": "%(name)s", "level": "%(levelname)s", "message": "%(message)s"}'
    )

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format=log_format,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting AI Inference service...")

    # Initialize session manager
    await init_session_manager()
    logger.info("Session manager initialized")

    settings = get_settings()
    logger.info(
        "Service configuration",
        extra={
            "max_sessions": settings.max_sessions,
            "session_timeout": settings.session_timeout_seconds,
            "asr_engine": settings.asr_engine,
            "llm_engine": settings.llm_engine,
            "tts_engine": settings.tts_engine,
        },
    )

    yield

    # Shutdown
    logger.info("Shutting down AI Inference service...")
    await shutdown_session_manager()
    logger.info("Session manager shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application.
    """
    settings = get_settings()

    app = FastAPI(
        title="AI Inference Service",
        description="OpenAI Realtime API compatible inference service",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.debug,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(rest_router, tags=["REST"])
    app.include_router(websocket_router, tags=["WebSocket"])
    app.include_router(signaling_router, tags=["WebRTC"])

    return app


# Create application instance
app = create_app()


def main() -> None:
    """Run the application using uvicorn."""
    settings = get_settings()

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
