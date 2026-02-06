# syntax=docker/dockerfile:1.4
# =============================================================================
# Dockerfile AI Agent - Usa imagem base voice-base
# =============================================================================
# Build context deve ser a raiz do projeto:
#   docker build -f ai-agent/Dockerfile -t ai-agent .
# =============================================================================

ARG BASE_IMAGE=paulohenriquevn/voice-base:latest
FROM ${BASE_IMAGE}

WORKDIR /app

# Copia modulos compartilhados PRIMEIRO (mudam menos frequentemente)
COPY shared/asp_protocol/ ./shared/asp_protocol/
COPY shared/shared_config/ ./shared/shared_config/
COPY shared/ws/ ./shared/ws/

# Copia codigo do ai-agent por ULTIMO (muda frequentemente)
COPY ai-agent/config.py .
COPY ai-agent/config_validation.py .
COPY ai-agent/ai_agent.py .
COPY ai-agent/metrics/ ./metrics/
COPY ai-agent/ws/ ./ws/
COPY ai-agent/server/ ./server/
COPY ai-agent/pipeline/ ./pipeline/
COPY ai-agent/providers/ ./providers/
COPY ai-agent/utils/ ./utils/

# =============================================================================
# Variaveis de ambiente padrao
# =============================================================================

# WebSocket
ENV WS_HOST=0.0.0.0
ENV WS_PORT=8765

# Logging
ENV LOG_LEVEL=INFO

# ASR/STT - FasterWhisper (recomendado)
ENV ASR_PROVIDER=faster-whisper
ENV ASR_MODEL=tiny
ENV ASR_LANGUAGE=pt
ENV ASR_COMPUTE_TYPE=int8
ENV ASR_DEVICE=cpu

# LLM
ENV LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY deve ser passada via docker run -e ou docker-compose

# TTS - Kokoro (recomendado)
ENV TTS_PROVIDER=kokoro
ENV TTS_VOICE=pf_dora
ENV TTS_SAMPLE_RATE=24000
ENV TTS_LANG=pt

# VAD
ENV VAD_AGGRESSIVENESS=2
ENV SILENCE_THRESHOLD_MS=500

# Metricas
ENV METRICS_PORT=9090

# Python path para modulos compartilhados
ENV PYTHONPATH=/app:/app/shared

# Expoe portas
EXPOSE 8765 9090

# Comando de entrada
CMD ["python", "ai_agent.py"]
