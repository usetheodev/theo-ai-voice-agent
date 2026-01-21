"""
Configuration Management

Loads YAML config and provides typed access
"""

import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class SIPConfig:
    """SIP Server Configuration"""
    host: str = "0.0.0.0"
    port: int = 5060
    realm: str = "voiceagent"
    external_ip: Optional[str] = None
    codecs: List[str] = field(default_factory=lambda: ["PCMU", "PCMA", "opus"])
    max_concurrent_calls: int = 100
    ringing_timeout: int = 60
    trunks: List[Dict[str, Any]] = field(default_factory=list)
    ip_whitelist: List[str] = field(default_factory=list)


@dataclass
class RTPConfig:
    """RTP Server Configuration"""
    port_start: int = 10000
    port_end: int = 20000
    codec_priority: List[str] = field(default_factory=lambda: ["PCMU", "PCMA"])
    jitter_buffer_ms: int = 60
    jitter_buffer_max_ms: int = 200
    dtmf_detection: bool = True
    dtmf_min_duration_ms: int = 40
    rtp_timeout_ms: int = 5000


@dataclass
class AIConfig:
    """AI Pipeline Configuration"""
    asr_model: str = "openai/whisper-base"
    asr_model_path: str = "models/whisper/ggml-base.bin"
    asr_language: str = "pt"
    asr_threads: int = 4
    llm_model: str = "Qwen/Qwen2.5-7B"
    llm_max_tokens: int = 256
    llm_temperature: float = 0.7
    tts_model: str = "kokoro-tts"
    tts_voice: str = "af_bella"
    tts_speed: float = 1.0
    vad_threshold: float = 0.5
    vad_min_speech_duration_ms: int = 300
    system_prompt: str = ""


@dataclass
class AppConfig:
    """Main Application Configuration"""
    sip: SIPConfig
    rtp: RTPConfig
    ai: AIConfig
    log_level: str = "INFO"
    metrics_port: int = 8000

    @classmethod
    def from_yaml(cls, path: str) -> 'AppConfig':
        """Load configuration from YAML file"""
        config_path = Path(path)

        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        # Parse nested configs
        sip_config = SIPConfig(**data.get('sip', {}))
        rtp_config = RTPConfig(**data.get('rtp', {}))
        ai_config = AIConfig(**data.get('ai', {}))

        return cls(
            sip=sip_config,
            rtp=rtp_config,
            ai=ai_config,
            log_level=data.get('log_level', 'INFO'),
            metrics_port=data.get('metrics_port', 8000)
        )

    def validate(self) -> List[str]:
        """
        Validate configuration

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # SIP validation
        if self.sip.port < 1024 or self.sip.port > 65535:
            errors.append(f"Invalid SIP port: {self.sip.port}")

        # RTP validation
        if self.rtp.port_start >= self.rtp.port_end:
            errors.append(f"Invalid RTP port range: {self.rtp.port_start}-{self.rtp.port_end}")

        if self.rtp.port_end - self.rtp.port_start < 100:
            errors.append("RTP port range too small (need at least 100 ports)")

        # Log level validation
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR']
        if self.log_level.upper() not in valid_levels:
            errors.append(f"Invalid log level: {self.log_level}")

        return errors
