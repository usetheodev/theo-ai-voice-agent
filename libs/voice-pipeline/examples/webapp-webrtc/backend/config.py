"""Configuration for the WebRTC demo backend."""

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class WebRTCConfig:
    """WebRTC-specific configuration."""

    ice_servers: list[dict] = field(default_factory=lambda: [{"urls": ["stun:stun.l.google.com:19302"]}])
    audio_codec: str = "opus"
    sample_rate: int = 16000
    channels: int = 1


@dataclass
class LLMConfig:
    """LLM provider configuration."""

    provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "ollama"))
    model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "qwen3:0.6b"))
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    base_url: Optional[str] = field(default_factory=lambda: os.getenv("LLM_BASE_URL"))
    temperature: float = 0.7


@dataclass
class TTSConfig:
    """TTS provider configuration."""

    provider: str = field(default_factory=lambda: os.getenv("TTS_PROVIDER", "kokoro"))
    voice: str = field(default_factory=lambda: os.getenv("TTS_VOICE", "pf_dora"))
    sample_rate: int = 24000


@dataclass
class ASRConfig:
    """ASR provider configuration."""

    provider: str = field(default_factory=lambda: os.getenv("ASR_PROVIDER", "parakeet"))
    model: str = field(default_factory=lambda: os.getenv("ASR_MODEL", "nemo-parakeet-tdt-0.6b-v3"))
    language: str = field(default_factory=lambda: os.getenv("ASR_LANGUAGE", "pt"))


@dataclass
class MemoryConfig:
    """Memory configuration."""

    enabled: bool = True
    store_path: str = field(default_factory=lambda: os.getenv("MEMORY_STORE_PATH", "./episodes"))
    max_recall_episodes: int = 5


@dataclass
class AppConfig:
    """Main application configuration."""

    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    debug: bool = field(default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true")
    cors_origins: list[str] = field(default_factory=lambda: os.getenv("CORS_ORIGINS", "*").split(","))

    webrtc: WebRTCConfig = field(default_factory=WebRTCConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)

    system_prompt: str = field(
        default_factory=lambda: os.getenv(
            "SYSTEM_PROMPT",
            """Voce e um assistente de voz prestativo e amigavel.
Responda de forma concisa e natural, como em uma conversa falada.
Sempre responda em portugues brasileiro.""",
        )
    )


def load_config() -> AppConfig:
    """Load application configuration."""
    return AppConfig()
