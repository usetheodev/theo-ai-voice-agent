# syntax=docker/dockerfile:1.4
# Dockerfile otimizado para AI Agent
# ===================================
# Usa BuildKit cache para acelerar rebuilds
# NOTA: Build context deve ser a raiz do projeto (não ./ai-agent)

FROM python:3.11-slim AS base

WORKDIR /app

# Instala dependências de sistema (raramente muda)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    curl \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# ===================================
# Stage: Dependências pesadas (cache)
# ===================================
FROM base AS deps-heavy

# Instala dependências pesadas primeiro (torch/faster-whisper/kokoro) - raramente mudam
# Usa cache mount para não baixar toda vez
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir \
    numpy>=1.24.0 \
    torch>=2.0.0 \
    faster-whisper>=1.0.0 \
    kokoro>=0.3.0 \
    soundfile>=0.12.0

# ===================================
# Stage: Dependências leves
# ===================================
FROM deps-heavy AS deps

# Copia requirements e instala o resto
# NOTA: Path relativo à raiz do projeto (build context)
COPY ai-agent/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# ===================================
# Stage: Final
# ===================================
FROM deps AS final

# Copia módulos compartilhados PRIMEIRO
# (mudam menos frequentemente que o código principal)
COPY shared/asp_protocol/ ./shared/asp_protocol/
COPY shared/ws/ ./shared/ws/

# Copia código do ai-agent por ÚLTIMO (muda frequentemente)
# Assim não invalida cache das dependências
COPY ai-agent/config.py .
COPY ai-agent/ai_agent.py .
COPY ai-agent/metrics/ ./metrics/
COPY ai-agent/ws/ ./ws/
COPY ai-agent/server/ ./server/
COPY ai-agent/pipeline/ ./pipeline/
COPY ai-agent/providers/ ./providers/

# =============================================================================
# Variáveis de ambiente padrão
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

# Métricas
ENV METRICS_PORT=9090

# Expõe portas
EXPOSE 8765 9090

# Comando de entrada
CMD ["python", "ai_agent.py"]
