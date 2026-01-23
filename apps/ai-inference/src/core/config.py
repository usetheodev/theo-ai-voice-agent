"""Configuration for the AI Inference service."""

from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Server configuration
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8080, description="Server port")
    debug: bool = Field(default=False, description="Debug mode")

    # WebRTC configuration
    stun_servers: List[str] = Field(
        default=["stun:stun.l.google.com:19302"],
        description="STUN server URLs"
    )
    turn_server: Optional[str] = Field(
        default=None,
        description="TURN server URL (e.g., turn:localhost:3478)"
    )
    turn_username: Optional[str] = Field(
        default=None,
        description="TURN server username"
    )
    turn_password: Optional[str] = Field(
        default=None,
        description="TURN server password"
    )

    # Ephemeral token configuration
    token_secret: str = Field(
        default="change-me-in-production",
        description="Secret key for signing ephemeral tokens"
    )
    token_expiry_seconds: int = Field(
        default=120,
        description="Ephemeral token expiry time in seconds"
    )

    # Session limits
    max_sessions: int = Field(default=100, description="Maximum concurrent sessions")
    session_timeout_seconds: int = Field(
        default=3600, description="Session timeout in seconds"
    )
    max_audio_buffer_bytes: int = Field(
        default=10_000_000, description="Maximum audio buffer size (10MB)"
    )

    # Audio configuration
    default_sample_rate: int = Field(default=24000, description="Default sample rate")
    default_channels: int = Field(default=1, description="Default audio channels")

    # Engine configuration (for future phases)
    asr_engine: str = Field(default="sherpa", description="ASR engine to use")
    llm_engine: str = Field(default="ollama", description="LLM engine to use")
    tts_engine: str = Field(default="piper", description="TTS engine to use")

    # ASR configuration
    asr_model: Optional[str] = Field(default=None, description="ASR model name")
    asr_endpoint: Optional[str] = Field(default=None, description="ASR endpoint URL")

    # LLM configuration
    llm_model: str = Field(default="llama3.2:3b", description="LLM model name")
    llm_endpoint: str = Field(
        default="http://localhost:11434", description="LLM endpoint URL"
    )

    # TTS configuration
    tts_model: Optional[str] = Field(default=None, description="TTS model name")
    tts_endpoint: Optional[str] = Field(default=None, description="TTS endpoint URL")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Logging format (json or text)")

    model_config = {
        "env_prefix": "AI_INFERENCE_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the application settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset settings (useful for testing)."""
    global _settings
    _settings = None
