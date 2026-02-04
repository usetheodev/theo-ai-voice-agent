"""
Configuração do AI Agent (Conversation Server)
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Configurações do WebSocket Server
WS_CONFIG = {
    "host": os.getenv("WS_HOST", "0.0.0.0"),
    "port": int(os.getenv("WS_PORT", "8765")),
    "max_connections": int(os.getenv("WS_MAX_CONNECTIONS", "100")),
    "ping_interval": int(os.getenv("WS_PING_INTERVAL", "30")),
    "ping_timeout": int(os.getenv("WS_PING_TIMEOUT", "10")),
}

# Configurações de áudio
AUDIO_CONFIG = {
    "sample_rate": 8000,      # 8kHz para telefonia
    "channels": 1,            # Mono
    "sample_width": 2,        # 16-bit
    "frame_duration_ms": 20,  # 20ms por frame RTP
    "vad_aggressiveness": int(os.getenv("VAD_AGGRESSIVENESS", "2")),  # 0-3
    "silence_threshold_ms": int(os.getenv("SILENCE_THRESHOLD_MS", "500")),  # Pausas naturais são 300-500ms
}

# Configurações de log
LOG_CONFIG = {
    "level": os.getenv("LOG_LEVEL", "INFO"),
}

# -----------------------------------------------------------------------------
# ASR (Automatic Speech Recognition) / STT Configuration
# -----------------------------------------------------------------------------
STT_CONFIG = {
    # Provider: faster-whisper (recomendado), whisper, openai
    "provider": os.getenv("ASR_PROVIDER", os.getenv("STT_PROVIDER", "faster-whisper")),

    # Modelo para faster-whisper/whisper: tiny, base, small, medium, large
    # 'tiny' é mais rápido (RTF < 1.0), 'base' é mais preciso mas mais lento
    "model": os.getenv("ASR_MODEL", os.getenv("STT_MODEL", "tiny")),

    # Idioma
    "language": os.getenv("ASR_LANGUAGE", os.getenv("STT_LANGUAGE", "pt")),

    # Tipo de computação para faster-whisper: int8, float16, float32
    "compute_type": os.getenv("ASR_COMPUTE_TYPE", "int8"),

    # Device: cpu, cuda, auto
    "device": os.getenv("ASR_DEVICE", "cpu"),

    # Para compatibilidade com código antigo
    "whisper_model": os.getenv("STT_MODEL", "base"),
    "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
}

# -----------------------------------------------------------------------------
# LLM (Large Language Model) Configuration
# -----------------------------------------------------------------------------
LLM_CONFIG = {
    "provider": os.getenv("LLM_PROVIDER", "anthropic"),  # anthropic, openai, mock
    "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
    "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
    "model": os.getenv("LLM_MODEL", "claude-3-haiku-20240307"),
    "openai_model": os.getenv("OPENAI_LLM_MODEL", "gpt-3.5-turbo"),
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "256")),
    "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
    "timeout": float(os.getenv("LLM_TIMEOUT", "15.0")),
    "system_prompt": os.getenv("LLM_SYSTEM_PROMPT", """Você é um assistente virtual de atendimento telefônico.
Seja conciso e direto nas respostas, pois está em uma ligação telefônica.
Responda sempre em português brasileiro.
Limite suas respostas a 2-3 frases curtas."""),
}

# -----------------------------------------------------------------------------
# TTS (Text-to-Speech) Configuration
# -----------------------------------------------------------------------------
TTS_CONFIG = {
    # Provider: kokoro (local, recomendado), gtts, openai, mock
    "provider": os.getenv("TTS_PROVIDER", "kokoro"),

    # Idioma (para gTTS)
    "language": os.getenv("TTS_LANG", "pt"),

    # Voz para Kokoro: pf_dora (português feminino), af_bella, am_adam, etc.
    "voice": os.getenv("TTS_VOICE", "pf_dora"),

    # Sample rate de saída do TTS (antes do downsampling para 8kHz)
    "sample_rate": int(os.getenv("TTS_SAMPLE_RATE", "24000")),

    # OpenAI TTS config
    "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
    "openai_tts_model": os.getenv("OPENAI_TTS_MODEL", "tts-1"),
    "openai_tts_voice": os.getenv("OPENAI_TTS_VOICE", "alloy"),
}

# Mensagens do agente
AGENT_MESSAGES = {
    "greeting": os.getenv("AGENT_GREETING", "Olá! Bem-vindo ao atendimento. Como posso ajudá-lo?"),
    "error": os.getenv("AGENT_ERROR", "Desculpe, tive um problema ao processar sua mensagem."),
    "goodbye": os.getenv("AGENT_GOODBYE", "Até logo! Tenha um bom dia!"),
}
