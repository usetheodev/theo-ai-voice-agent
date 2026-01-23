"""Pytest configuration and fixtures for AI Inference tests."""

import asyncio
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from src.core.config import Settings, reset_settings
from src.core.session_manager import SessionManager
from src.main import create_app

# Import for resetting global session manager
import src.core.session_manager as session_manager_module


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    reset_settings()
    return Settings(
        max_sessions=10,
        session_timeout_seconds=60,
        debug=True,
        log_level="DEBUG",
    )


@pytest.fixture
def session_manager(settings: Settings) -> SessionManager:
    """Create a session manager for testing."""
    return SessionManager(settings=settings)


@pytest.fixture(autouse=True)
def reset_global_session_manager():
    """Reset global session manager before each test."""
    session_manager_module._session_manager = None
    yield
    session_manager_module._session_manager = None


@pytest.fixture
def app():
    """Create a FastAPI app for testing."""
    reset_settings()
    return create_app()


@pytest.fixture
def client(app) -> TestClient:
    """Create a test client."""
    return TestClient(app)


@pytest_asyncio.fixture
async def async_client(app) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
