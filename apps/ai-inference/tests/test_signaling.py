"""Tests for WebRTC signaling endpoints."""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from src.api.signaling import _generate_client_secret, _verify_client_secret
from src.core.config import get_settings, reset_settings


@pytest.fixture(autouse=True)
def reset_config():
    """Reset config before each test."""
    reset_settings()
    yield
    reset_settings()


class TestClientSecret:
    """Tests for ephemeral token generation and verification."""

    def test_generate_client_secret(self):
        """Test client secret generation."""
        session_id = "sess_test123"
        secret = _generate_client_secret(session_id)

        assert secret.value is not None
        assert len(secret.value) > 0
        assert secret.expires_at > time.time()

    def test_verify_valid_client_secret(self):
        """Test verification of a valid client secret."""
        session_id = "sess_test123"
        secret = _generate_client_secret(session_id)

        is_valid = _verify_client_secret(secret.value, session_id)
        assert is_valid is True

    def test_verify_invalid_session_id(self):
        """Test verification fails with wrong session ID."""
        session_id = "sess_test123"
        secret = _generate_client_secret(session_id)

        is_valid = _verify_client_secret(secret.value, "sess_different")
        assert is_valid is False

    def test_verify_expired_token(self):
        """Test verification fails with expired token."""
        settings = get_settings()
        session_id = "sess_test123"

        # Create expired token
        payload = {
            "session_id": session_id,
            "exp": int(time.time()) - 10,  # Expired 10 seconds ago
            "iat": int(time.time()) - 130,
        }
        token = jwt.encode(payload, settings.token_secret, algorithm="HS256")

        is_valid = _verify_client_secret(token, session_id)
        assert is_valid is False

    def test_verify_invalid_token(self):
        """Test verification fails with invalid token."""
        is_valid = _verify_client_secret("invalid.token.here", "sess_test")
        assert is_valid is False


class TestSessionEndpoints:
    """Tests for session management endpoints."""

    def test_create_session(self, client: TestClient):
        """Test creating a session."""
        response = client.post("/v1/realtime/sessions")

        assert response.status_code == 200
        data = response.json()

        assert "id" in data
        assert data["id"].startswith("sess_")
        assert data["object"] == "realtime.session"
        assert "client_secret" in data
        assert "value" in data["client_secret"]
        assert "expires_at" in data["client_secret"]

    def test_create_session_with_config(self, client: TestClient):
        """Test creating a session with configuration."""
        response = client.post(
            "/v1/realtime/sessions",
            json={
                "instructions": "You are a helpful assistant.",
                "voice": "alloy",
                "temperature": 0.8,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert "id" in data
        assert data["id"].startswith("sess_")

    def test_get_session(self, client: TestClient):
        """Test getting session info."""
        # First create a session
        create_response = client.post("/v1/realtime/sessions")
        session_id = create_response.json()["id"]

        # Get session info
        response = client.get(f"/v1/realtime/sessions/{session_id}")

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == session_id
        assert data["object"] == "realtime.session"
        assert "state" in data
        assert "connection" in data
        assert "config" in data

    def test_get_nonexistent_session(self, client: TestClient):
        """Test getting a non-existent session."""
        response = client.get("/v1/realtime/sessions/sess_nonexistent")

        assert response.status_code == 404

    def test_close_session(self, client: TestClient):
        """Test closing a session."""
        # First create a session
        create_response = client.post("/v1/realtime/sessions")
        session_id = create_response.json()["id"]

        # Close session
        response = client.delete(f"/v1/realtime/sessions/{session_id}")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "closed"
        assert data["session_id"] == session_id

        # Verify session is gone
        get_response = client.get(f"/v1/realtime/sessions/{session_id}")
        assert get_response.status_code == 404

    def test_close_nonexistent_session(self, client: TestClient):
        """Test closing a non-existent session."""
        response = client.delete("/v1/realtime/sessions/sess_nonexistent")

        assert response.status_code == 404


class TestSDPEndpoint:
    """Tests for SDP exchange endpoint."""

    def test_sdp_exchange_no_auth(self, client: TestClient):
        """Test SDP exchange without authorization."""
        # Create session first
        create_response = client.post("/v1/realtime/sessions")
        session_id = create_response.json()["id"]

        # Try SDP exchange without auth
        response = client.post(
            f"/v1/realtime/sessions/{session_id}/sdp",
            content="fake sdp offer",
            headers={"Content-Type": "application/sdp"},
        )

        assert response.status_code == 401

    def test_sdp_exchange_invalid_auth(self, client: TestClient):
        """Test SDP exchange with invalid authorization."""
        # Create session first
        create_response = client.post("/v1/realtime/sessions")
        session_id = create_response.json()["id"]

        # Try SDP exchange with invalid auth
        response = client.post(
            f"/v1/realtime/sessions/{session_id}/sdp",
            content="fake sdp offer",
            headers={
                "Content-Type": "application/sdp",
                "Authorization": "Bearer invalid_token",
            },
        )

        assert response.status_code == 401

    def test_sdp_exchange_nonexistent_session(self, client: TestClient):
        """Test SDP exchange for non-existent session."""
        # Generate a valid token for a fake session
        settings = get_settings()
        fake_session_id = "sess_fake123"
        payload = {
            "session_id": fake_session_id,
            "exp": int(time.time()) + 120,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, settings.token_secret, algorithm="HS256")

        response = client.post(
            f"/v1/realtime/sessions/{fake_session_id}/sdp",
            content="fake sdp offer",
            headers={
                "Content-Type": "application/sdp",
                "Authorization": f"Bearer {token}",
            },
        )

        assert response.status_code == 404
