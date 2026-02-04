"""
Configuração do Media Server (SIP Bridge)
"""
import os
from dotenv import load_dotenv

load_dotenv(override=False)  # Não sobrescreve variáveis de ambiente do Docker

# Configurações do AI Agent (WebSocket)
AI_AGENT_CONFIG = {
    "url": os.getenv("WEBSOCKET_URL", "ws://ai-agent:8765"),
    "reconnect_interval": int(os.getenv("WS_RECONNECT_INTERVAL", "5")),
    "max_reconnect_attempts": int(os.getenv("WS_MAX_RECONNECT_ATTEMPTS", "10")),
    "ping_interval": int(os.getenv("WS_PING_INTERVAL", "30")),
}

# Configurações do Asterisk/SIP
SIP_CONFIG = {
    "domain": os.getenv("SIP_DOMAIN", "127.0.0.1"),
    "port": int(os.getenv("SIP_PORT", "5160")),
    "transport": os.getenv("SIP_TRANSPORT", "udp"),
    "username": os.getenv("SIP_USERNAME", "2000"),
    "password": os.getenv("SIP_PASSWORD", "ramal2000"),
    "display_name": os.getenv("SIP_DISPLAY_NAME", "Agente IA"),
    "codecs": ["PCMU", "PCMA"],  # ulaw, alaw
    "rtp_port_start": int(os.getenv("RTP_PORT_START", "40000")),
    "rtp_port_end": int(os.getenv("RTP_PORT_END", "40100")),
}

# Configurações de áudio
AUDIO_CONFIG = {
    "sample_rate": 8000,      # 8kHz para telefonia
    "channels": 1,            # Mono
    "sample_width": 2,        # 16-bit
    "frame_duration_ms": 20,  # 20ms por frame RTP
    "silence_threshold_ms": int(os.getenv("SILENCE_THRESHOLD_MS", "500")),  # Pausas naturais são 300-500ms
    "vad_aggressiveness": int(os.getenv("VAD_AGGRESSIVENESS", "2")),
}

# Configurações de log
LOG_CONFIG = {
    "level": os.getenv("LOG_LEVEL", "INFO"),
    "pjsip_log_level": int(os.getenv("PJSIP_LOG_LEVEL", "3")),
}

# Configurações do SBC (Session Border Controller)
SBC_CONFIG = {
    "enabled": os.getenv("SBC_ENABLED", "false").lower() == "true",
    "host": os.getenv("SBC_HOST", ""),
    "port": int(os.getenv("SBC_PORT", "5060")),
    "transport": os.getenv("SBC_TRANSPORT", "udp").lower(),
    "outbound_proxy": os.getenv("SBC_OUTBOUND_PROXY", ""),
    "realm": os.getenv("SBC_REALM", "*"),
    "register": os.getenv("SBC_REGISTER", "true").lower() == "true",
    "public_ip": os.getenv("SBC_PUBLIC_IP", ""),
    "keep_alive_interval": int(os.getenv("SBC_KEEP_ALIVE", "30")),
    "register_timeout": int(os.getenv("SBC_REGISTER_TIMEOUT", "300")),
}
