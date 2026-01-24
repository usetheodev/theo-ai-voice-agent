"""Tests for Voice Agent API endpoints."""

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_agents():
    """Reset agents storage between tests."""
    from src.api import agents
    agents._agents.clear()
    yield
    agents._agents.clear()


class TestPresets:
    """Tests for presets endpoints."""

    def test_list_presets(self, client):
        """Test listing available presets."""
        response = client.get("/v1/agents/presets")
        assert response.status_code == 200

        data = response.json()
        assert "presets" in data
        assert len(data["presets"]) >= 3

        # Check preset structure
        preset = data["presets"][0]
        assert "id" in preset
        assert "name" in preset
        assert "description" in preset
        assert "estimated_cost_per_minute" in preset
        assert "estimated_latency_ms" in preset
        assert "providers" in preset

    def test_create_from_preset_local(self, client):
        """Test creating agent from local preset."""
        response = client.post(
            "/v1/agents/from-preset/local",
            params={
                "name": "Meu Agente Local",
                "system_prompt": "Você é um assistente útil.",
                "first_message": "Olá!",
                "language": "pt-BR",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Meu Agente Local"
        assert data["model"]["provider"] == "ollama"
        assert data["voice"]["provider"] == "piper"
        assert data["transcriber"]["provider"] == "whisper-local"
        assert data["estimated_cost_per_minute"] == 0.0  # Local = free

    def test_create_from_preset_low_latency(self, client):
        """Test creating agent from low-latency preset."""
        response = client.post(
            "/v1/agents/from-preset/low-latency",
            params={"name": "Fast Agent"},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["model"]["provider"] == "groq"
        assert data["transcriber"]["provider"] == "deepgram"
        assert data["estimated_latency_ms"] < 500

    def test_create_from_preset_invalid(self, client):
        """Test creating agent from invalid preset."""
        response = client.post("/v1/agents/from-preset/invalid-preset")
        assert response.status_code == 404


class TestCRUD:
    """Tests for CRUD operations."""

    def test_create_agent(self, client):
        """Test creating a custom agent."""
        response = client.post(
            "/v1/agents",
            json={
                "name": "Atendente Virtual",
                "description": "Agente para atendimento",
                "model": {
                    "provider": "ollama",
                    "model": "llama3:8b",
                    "first_message": "Olá! Como posso ajudar?",
                    "system_prompt": "Você é um atendente virtual.",
                    "max_tokens": 300,
                    "temperature": 0.8,
                },
                "voice": {
                    "provider": "piper",
                    "voice": "pt_BR-faber-medium",
                    "speed": 1.1,
                },
                "transcriber": {
                    "provider": "whisper-local",
                    "model": "large-v3",
                    "language": "pt-BR",
                },
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Atendente Virtual"
        assert data["model"]["provider"] == "ollama"
        assert data["model"]["max_tokens"] == 300
        assert data["model"]["temperature"] == 0.8
        assert data["voice"]["speed"] == 1.1
        assert "id" in data
        assert data["id"].startswith("agent_")

    def test_list_agents_empty(self, client):
        """Test listing agents when empty."""
        response = client.get("/v1/agents")
        assert response.status_code == 200

        data = response.json()
        assert data["agents"] == []
        assert data["total"] == 0

    def test_list_agents(self, client):
        """Test listing agents."""
        # Create agents
        client.post("/v1/agents/from-preset/local", params={"name": "Agent 1"})
        client.post("/v1/agents/from-preset/local", params={"name": "Agent 2"})

        response = client.get("/v1/agents")
        assert response.status_code == 200

        data = response.json()
        assert len(data["agents"]) == 2
        assert data["total"] == 2

    def test_get_agent(self, client):
        """Test getting a specific agent."""
        # Create agent
        create_response = client.post(
            "/v1/agents/from-preset/local",
            params={"name": "Test Agent"},
        )
        agent_id = create_response.json()["id"]

        # Get agent
        response = client.get(f"/v1/agents/{agent_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == agent_id
        assert data["name"] == "Test Agent"

    def test_get_agent_not_found(self, client):
        """Test getting non-existent agent."""
        response = client.get("/v1/agents/agent_notfound")
        assert response.status_code == 404

    def test_update_agent(self, client):
        """Test updating an agent."""
        # Create agent
        create_response = client.post(
            "/v1/agents/from-preset/local",
            params={"name": "Original Name"},
        )
        agent_id = create_response.json()["id"]

        # Update agent
        response = client.patch(
            f"/v1/agents/{agent_id}",
            json={
                "name": "Updated Name",
                "model": {
                    "provider": "groq",
                    "model": "llama3-70b-8192",
                },
                "voice": {
                    "provider": "elevenlabs",
                    "voice": "rachel",
                },
                "transcriber": {
                    "provider": "deepgram",
                    "model": "nova-3",
                    "language": "en-US",
                },
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["model"]["provider"] == "groq"
        assert data["voice"]["provider"] == "elevenlabs"

    def test_delete_agent(self, client):
        """Test deleting an agent."""
        # Create agent
        create_response = client.post(
            "/v1/agents/from-preset/local",
            params={"name": "To Delete"},
        )
        agent_id = create_response.json()["id"]

        # Delete agent
        response = client.delete(f"/v1/agents/{agent_id}")
        assert response.status_code == 200

        # Verify deleted
        get_response = client.get(f"/v1/agents/{agent_id}")
        assert get_response.status_code == 404


class TestProviders:
    """Tests for provider listing endpoints."""

    def test_list_llm_providers(self, client):
        """Test listing LLM providers."""
        response = client.get("/v1/agents/providers/llm")
        assert response.status_code == 200

        data = response.json()
        assert "providers" in data

        # Check for known providers
        provider_ids = [p["id"] for p in data["providers"]]
        assert "ollama" in provider_ids
        assert "openai" in provider_ids
        assert "groq" in provider_ids

        # Check provider structure
        ollama = next(p for p in data["providers"] if p["id"] == "ollama")
        assert "name" in ollama
        assert "models" in ollama
        assert ollama["requires_api_key"] is False

    def test_list_tts_providers(self, client):
        """Test listing TTS providers."""
        response = client.get("/v1/agents/providers/tts")
        assert response.status_code == 200

        data = response.json()
        provider_ids = [p["id"] for p in data["providers"]]
        assert "piper" in provider_ids
        assert "elevenlabs" in provider_ids

    def test_list_asr_providers(self, client):
        """Test listing ASR providers."""
        response = client.get("/v1/agents/providers/asr")
        assert response.status_code == 200

        data = response.json()
        provider_ids = [p["id"] for p in data["providers"]]
        assert "whisper-local" in provider_ids
        assert "deepgram" in provider_ids


class TestEstimates:
    """Tests for cost and latency estimates."""

    def test_local_agent_free(self, client):
        """Test that local agent has zero cost."""
        response = client.post(
            "/v1/agents/from-preset/local",
            params={"name": "Free Agent"},
        )
        data = response.json()
        assert data["estimated_cost_per_minute"] == 0.0

    def test_cloud_agent_has_cost(self, client):
        """Test that cloud agent has cost."""
        response = client.post(
            "/v1/agents",
            json={
                "name": "Cloud Agent",
                "model": {"provider": "openai", "model": "gpt-4o"},
                "voice": {"provider": "elevenlabs", "voice": "rachel"},
                "transcriber": {"provider": "deepgram", "model": "nova-3"},
            },
        )
        data = response.json()
        assert data["estimated_cost_per_minute"] > 0

    def test_latency_estimates(self, client):
        """Test latency estimates vary by provider."""
        # Local agent
        local_response = client.post(
            "/v1/agents/from-preset/local",
            params={"name": "Local"},
        )
        local_latency = local_response.json()["estimated_latency_ms"]

        # Low latency agent
        fast_response = client.post(
            "/v1/agents/from-preset/low-latency",
            params={"name": "Fast"},
        )
        fast_latency = fast_response.json()["estimated_latency_ms"]

        # Low latency should be faster
        assert fast_latency < local_latency
