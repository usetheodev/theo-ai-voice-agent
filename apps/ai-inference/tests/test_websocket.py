"""Tests for the WebSocket handler."""

import base64
import json

import pytest
from fastapi.testclient import TestClient

from src.events.types import ClientEventType, ServerEventType


class TestWebSocketEndpoint:
    """Tests for the WebSocket endpoint."""

    def test_websocket_connect_and_session_created(self, client: TestClient):
        """Test WebSocket connection and session.created event."""
        with client.websocket_connect("/v1/realtime") as websocket:
            # Should receive session.created event
            data = websocket.receive_json()
            assert data["type"] == ServerEventType.SESSION_CREATED
            assert "session" in data
            assert data["session"]["id"].startswith("sess_")
            assert data["session"]["object"] == "realtime.session"

            # Should receive conversation.created event
            data = websocket.receive_json()
            assert data["type"] == ServerEventType.CONVERSATION_CREATED
            assert "conversation" in data

    def test_session_update(self, client: TestClient):
        """Test session.update event."""
        with client.websocket_connect("/v1/realtime") as websocket:
            # Skip initial events
            websocket.receive_json()  # session.created
            websocket.receive_json()  # conversation.created

            # Send session.update
            update_event = {
                "type": ClientEventType.SESSION_UPDATE,
                "session": {
                    "instructions": "You are a helpful assistant",
                    "voice": "nova",
                },
            }
            websocket.send_json(update_event)

            # Should receive session.updated
            data = websocket.receive_json()
            assert data["type"] == ServerEventType.SESSION_UPDATED
            assert data["session"]["instructions"] == "You are a helpful assistant"
            assert data["session"]["voice"] == "nova"

    def test_input_audio_buffer_append(self, client: TestClient):
        """Test input_audio_buffer.append event."""
        with client.websocket_connect("/v1/realtime") as websocket:
            # Skip initial events
            websocket.receive_json()
            websocket.receive_json()

            # Send audio append
            audio_data = b"\x00" * 4800  # 100ms of silence
            append_event = {
                "type": ClientEventType.INPUT_AUDIO_BUFFER_APPEND,
                "audio": base64.b64encode(audio_data).decode(),
            }
            websocket.send_json(append_event)

            # No response for append (it's silent)

    def test_input_audio_buffer_commit(self, client: TestClient):
        """Test input_audio_buffer.commit event."""
        with client.websocket_connect("/v1/realtime") as websocket:
            # Skip initial events
            websocket.receive_json()
            websocket.receive_json()

            # Append audio first
            audio_data = b"\x00" * 4800
            append_event = {
                "type": ClientEventType.INPUT_AUDIO_BUFFER_APPEND,
                "audio": base64.b64encode(audio_data).decode(),
            }
            websocket.send_json(append_event)

            # Commit audio
            commit_event = {
                "type": ClientEventType.INPUT_AUDIO_BUFFER_COMMIT,
            }
            websocket.send_json(commit_event)

            # Should receive input_audio_buffer.committed
            data = websocket.receive_json()
            assert data["type"] == ServerEventType.INPUT_AUDIO_BUFFER_COMMITTED
            assert "item_id" in data

    def test_input_audio_buffer_commit_empty(self, client: TestClient):
        """Test committing empty audio buffer returns error."""
        with client.websocket_connect("/v1/realtime") as websocket:
            # Skip initial events
            websocket.receive_json()
            websocket.receive_json()

            # Try to commit empty buffer
            commit_event = {
                "type": ClientEventType.INPUT_AUDIO_BUFFER_COMMIT,
            }
            websocket.send_json(commit_event)

            # Should receive error
            data = websocket.receive_json()
            assert data["type"] == ServerEventType.ERROR
            assert data["error"]["code"] == "empty_buffer"

    def test_input_audio_buffer_clear(self, client: TestClient):
        """Test input_audio_buffer.clear event."""
        with client.websocket_connect("/v1/realtime") as websocket:
            # Skip initial events
            websocket.receive_json()
            websocket.receive_json()

            # Append audio
            audio_data = b"\x00" * 4800
            append_event = {
                "type": ClientEventType.INPUT_AUDIO_BUFFER_APPEND,
                "audio": base64.b64encode(audio_data).decode(),
            }
            websocket.send_json(append_event)

            # Clear audio
            clear_event = {
                "type": ClientEventType.INPUT_AUDIO_BUFFER_CLEAR,
            }
            websocket.send_json(clear_event)

            # Should receive input_audio_buffer.cleared
            data = websocket.receive_json()
            assert data["type"] == ServerEventType.INPUT_AUDIO_BUFFER_CLEARED

    def test_response_create(self, client: TestClient):
        """Test response.create event."""
        with client.websocket_connect("/v1/realtime") as websocket:
            # Skip initial events
            websocket.receive_json()
            websocket.receive_json()

            # Create response
            create_event = {
                "type": ClientEventType.RESPONSE_CREATE,
            }
            websocket.send_json(create_event)

            # Should receive response.created
            data = websocket.receive_json()
            assert data["type"] == ServerEventType.RESPONSE_CREATED
            assert "response" in data
            assert data["response"]["status"] == "in_progress"

            # Should receive response.done (Phase 1 immediately completes)
            data = websocket.receive_json()
            assert data["type"] == ServerEventType.RESPONSE_DONE
            assert data["response"]["status"] == "completed"

    def test_response_cancel(self, client: TestClient):
        """Test response.cancel with no active response."""
        with client.websocket_connect("/v1/realtime") as websocket:
            # Skip initial events
            websocket.receive_json()
            websocket.receive_json()

            # Try to cancel (no active response)
            cancel_event = {
                "type": ClientEventType.RESPONSE_CANCEL,
            }
            websocket.send_json(cancel_event)

            # Should receive error
            data = websocket.receive_json()
            assert data["type"] == ServerEventType.ERROR
            assert data["error"]["code"] == "no_active_response"

    def test_invalid_json(self, client: TestClient):
        """Test invalid JSON handling."""
        with client.websocket_connect("/v1/realtime") as websocket:
            # Skip initial events
            websocket.receive_json()
            websocket.receive_json()

            # Send invalid JSON
            websocket.send_text("not valid json")

            # Should receive error
            data = websocket.receive_json()
            assert data["type"] == ServerEventType.ERROR
            assert data["error"]["code"] == "json_parse_error"

    def test_unknown_event_type(self, client: TestClient):
        """Test unknown event type handling."""
        with client.websocket_connect("/v1/realtime") as websocket:
            # Skip initial events
            websocket.receive_json()
            websocket.receive_json()

            # Send unknown event type
            unknown_event = {
                "type": "unknown.event.type",
            }
            websocket.send_json(unknown_event)

            # Should receive error
            data = websocket.receive_json()
            assert data["type"] == ServerEventType.ERROR
            assert data["error"]["code"] == "invalid_event"

    def test_binary_audio_data(self, client: TestClient):
        """Test sending binary audio data."""
        with client.websocket_connect("/v1/realtime") as websocket:
            # Skip initial events
            websocket.receive_json()
            websocket.receive_json()

            # Send binary audio data
            audio_data = b"\x00" * 4800
            websocket.send_bytes(audio_data)

            # Binary append is silent, verify by committing
            commit_event = {
                "type": ClientEventType.INPUT_AUDIO_BUFFER_COMMIT,
            }
            websocket.send_json(commit_event)

            # Should receive committed (buffer wasn't empty)
            data = websocket.receive_json()
            assert data["type"] == ServerEventType.INPUT_AUDIO_BUFFER_COMMITTED


class TestRESTEndpoints:
    """Tests for REST endpoints."""

    def test_health_check(self, client: TestClient):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert "sessions_active" in data

    def test_metrics(self, client: TestClient):
        """Test metrics endpoint."""
        response = client.get("/metrics")
        assert response.status_code == 200

        data = response.json()
        assert "total_sessions" in data
        assert "max_sessions" in data

    def test_list_sessions_empty(self, client: TestClient):
        """Test listing sessions when empty."""
        response = client.get("/sessions")
        assert response.status_code == 200

        data = response.json()
        assert data["sessions"] == []
        assert data["total"] == 0

    def test_session_not_found(self, client: TestClient):
        """Test getting nonexistent session."""
        response = client.get("/sessions/nonexistent")
        assert response.status_code == 404
