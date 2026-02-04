"""
Configuração do AI Agent (Conversation Server)

Todas as configurações são carregadas de variáveis de ambiente.
Veja .env.example para documentação detalhada de cada variável.
"""

import os
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()


def _parse_bool(value: str, default: bool = False) -> bool:
    """Parse boolean de string"""
    if not value:
        return default
    return value.lower() in ("true", "1", "yes", "on")


def _parse_list(value: str, default: List[str]) -> List[str]:
    """Parse lista separada por vírgula"""
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


# =============================================================================
# WEBSOCKET SERVER
# =============================================================================

WS_CONFIG = {
    # Host para bind do servidor WebSocket
    "host": os.getenv("WS_HOST", "0.0.0.0"),

    # Porta do servidor WebSocket
    "port": int(os.getenv("WS_PORT", "8765")),

    # Número máximo de conexões simultâneas
    "max_connections": int(os.getenv("WS_MAX_CONNECTIONS", "100")),

    # Intervalo de ping para manter conexão viva (segundos)
    "ping_interval": int(os.getenv("WS_PING_INTERVAL", "30")),

    # Timeout do ping (segundos)
    "ping_timeout": int(os.getenv("WS_PING_TIMEOUT", "10")),

    # Timeout para fechar conexão WebSocket (segundos)
    "close_timeout": int(os.getenv("WS_CLOSE_TIMEOUT", "5")),
}


# =============================================================================
# CONFIGURAÇÕES DE ÁUDIO
# =============================================================================

AUDIO_CONFIG = {
    # Taxa de amostragem para telefonia (Hz)
    "sample_rate": int(os.getenv("AUDIO_SAMPLE_RATE", "8000")),

    # Número de canais (1 = mono)
    "channels": int(os.getenv("AUDIO_CHANNELS", "1")),

    # Largura da amostra em bytes (2 = 16-bit)
    "sample_width": int(os.getenv("AUDIO_SAMPLE_WIDTH", "2")),

    # Duração do frame RTP em milissegundos
    "frame_duration_ms": int(os.getenv("AUDIO_FRAME_DURATION_MS", "20")),

    # Agressividade do VAD (0-3)
    "vad_aggressiveness": int(os.getenv("VAD_AGGRESSIVENESS", "2")),

    # Threshold de silêncio para fim de fala (ms)
    "silence_threshold_ms": int(os.getenv("SILENCE_THRESHOLD_MS", "500")),

    # Duração mínima de fala para ser considerada válida (ms)
    "min_speech_ms": int(os.getenv("VAD_MIN_SPEECH_MS", "250")),

    # Threshold de energia RMS para fallback VAD
    "energy_threshold": int(os.getenv("VAD_ENERGY_THRESHOLD", "500")),

    # Tamanho máximo do buffer de áudio em segundos
    "max_buffer_seconds": int(os.getenv("AUDIO_MAX_BUFFER_SECONDS", "60")),

    # Tamanho do ring buffer do VAD em frames
    "vad_ring_buffer_size": int(os.getenv("VAD_RING_BUFFER_SIZE", "5")),

    # Taxa mínima de frames com fala para considerar que há fala (0.0 - 1.0)
    "vad_speech_ratio_threshold": float(os.getenv("VAD_SPEECH_RATIO_THRESHOLD", "0.4")),
}


# =============================================================================
# LOGGING
# =============================================================================

LOG_CONFIG = {
    # Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    "level": os.getenv("LOG_LEVEL", "INFO"),
}


# =============================================================================
# MÉTRICAS PROMETHEUS
# =============================================================================

METRICS_CONFIG = {
    # Porta do servidor HTTP para métricas Prometheus
    "port": int(os.getenv("METRICS_PORT", "9090")),

    # Habilitar servidor de métricas
    "enabled": _parse_bool(os.getenv("METRICS_ENABLED", "true"), True),
}


# =============================================================================
# ASR/STT (Automatic Speech Recognition)
# =============================================================================

STT_CONFIG = {
    # Provider: faster-whisper (recomendado), whisper, openai
    "provider": os.getenv("ASR_PROVIDER", os.getenv("STT_PROVIDER", "faster-whisper")),

    # Modelo: tiny, base, small, medium, large-v3
    "model": os.getenv("ASR_MODEL", os.getenv("STT_MODEL", "tiny")),

    # Idioma (ISO-639-1): pt, en, es, etc.
    "language": os.getenv("ASR_LANGUAGE", os.getenv("STT_LANGUAGE", "pt")),

    # Tipo de computação: int8 (CPU), float16 (GPU), float32
    "compute_type": os.getenv("ASR_COMPUTE_TYPE", "int8"),

    # Device: cpu, cuda, auto
    "device": os.getenv("ASR_DEVICE", "cpu"),

    # Beam size para transcrição (1 = greedy, mais rápido)
    "beam_size": int(os.getenv("ASR_BEAM_SIZE", "1")),

    # Habilitar filtro VAD no Whisper
    "vad_filter": _parse_bool(os.getenv("ASR_VAD_FILTER", "false"), False),

    # Gerar timestamps de palavras
    "word_timestamps": _parse_bool(os.getenv("ASR_WORD_TIMESTAMPS", "false"), False),

    # Número de threads CPU (0 = auto)
    "cpu_threads": int(os.getenv("ASR_CPU_THREADS", "0")),

    # Número de workers paralelos
    "num_workers": int(os.getenv("ASR_NUM_WORKERS", "1")),

    # Número de workers no ThreadPoolExecutor
    "executor_workers": int(os.getenv("ASR_EXECUTOR_WORKERS", "2")),

    # Para compatibilidade com código antigo
    "whisper_model": os.getenv("STT_MODEL", "base"),
    "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
}


# =============================================================================
# LLM (Large Language Model)
# =============================================================================

LLM_CONFIG = {
    # Provider: anthropic, openai, mock
    "provider": os.getenv("LLM_PROVIDER", "anthropic"),

    # API Keys
    "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
    "openai_api_key": os.getenv("OPENAI_API_KEY", ""),

    # Modelo Anthropic
    "model": os.getenv("LLM_MODEL", "claude-3-haiku-20240307"),

    # Modelo OpenAI
    "openai_model": os.getenv("OPENAI_LLM_MODEL", "gpt-3.5-turbo"),

    # Número máximo de tokens na resposta
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "256")),

    # Temperatura (0.0 - 1.0)
    "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),

    # Timeout da requisição (segundos)
    "timeout": float(os.getenv("LLM_TIMEOUT", "15.0")),

    # System prompt customizado
    "system_prompt": os.getenv("LLM_SYSTEM_PROMPT", """Você é um assistente virtual de atendimento telefônico.
Seja conciso e direto nas respostas, pois está em uma ligação telefônica.
Responda sempre em português brasileiro.
Limite suas respostas a 2-3 frases curtas."""),
}


# =============================================================================
# TTS (Text-to-Speech)
# =============================================================================

TTS_CONFIG = {
    # Provider: kokoro (recomendado), gtts, openai, mock
    "provider": os.getenv("TTS_PROVIDER", "kokoro"),

    # Idioma para gTTS
    "language": os.getenv("TTS_LANG", "pt"),

    # Voz para Kokoro: pf_dora (português), af_bella, am_adam, etc.
    "voice": os.getenv("TTS_VOICE", "pf_dora"),

    # Sample rate nativo do TTS (antes do downsampling)
    "sample_rate": int(os.getenv("TTS_SAMPLE_RATE", "24000")),

    # Sample rate de saída para telefonia
    "output_sample_rate": int(os.getenv("TTS_OUTPUT_SAMPLE_RATE", "8000")),

    # Velocidade da fala (0.5 - 2.0)
    "speed": float(os.getenv("TTS_SPEED", "1.0")),

    # Número de workers no ThreadPoolExecutor
    "executor_workers": int(os.getenv("TTS_EXECUTOR_WORKERS", "2")),

    # OpenAI TTS config
    "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
    "openai_tts_model": os.getenv("OPENAI_TTS_MODEL", "tts-1"),
    "openai_tts_voice": os.getenv("OPENAI_TTS_VOICE", "alloy"),
}


# =============================================================================
# PIPELINE DE CONVERSAÇÃO
# =============================================================================

PIPELINE_CONFIG = {
    # Tamanho da fila de frases para streaming LLM → TTS
    "sentence_queue_size": int(os.getenv("PIPELINE_SENTENCE_QUEUE_SIZE", "3")),

    # Timeout para transcrição STT (segundos)
    "stt_timeout": float(os.getenv("PIPELINE_STT_TIMEOUT", "30.0")),

    # Timeout para síntese TTS (segundos)
    "tts_timeout": float(os.getenv("PIPELINE_TTS_TIMEOUT", "60.0")),
}


# =============================================================================
# SESSÕES
# =============================================================================

SESSION_CONFIG = {
    # Tempo máximo de inatividade antes de limpar sessão (segundos)
    "max_idle_seconds": int(os.getenv("SESSION_MAX_IDLE_SECONDS", "300")),

    # Intervalo de limpeza de sessões inativas (segundos)
    "cleanup_interval": int(os.getenv("SESSION_CLEANUP_INTERVAL", "60")),
}


# =============================================================================
# MENSAGENS DO AGENTE
# =============================================================================

AGENT_MESSAGES = {
    # Saudação inicial
    "greeting": os.getenv("AGENT_GREETING", "Olá! Bem-vindo ao atendimento. Como posso ajudá-lo?"),

    # Mensagem de erro
    "error": os.getenv("AGENT_ERROR", "Desculpe, tive um problema ao processar sua mensagem."),

    # Despedida
    "goodbye": os.getenv("AGENT_GOODBYE", "Até logo! Tenha um bom dia!"),
}
