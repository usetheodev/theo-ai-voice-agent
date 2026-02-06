# syntax=docker/dockerfile:1.4
# =============================================================================
# Dockerfile AI Transcribe - Usa imagem base voice-base
# =============================================================================
# Build context deve ser a raiz do projeto:
#   docker build -f ai-transcribe/Dockerfile -t ai-transcribe .
# =============================================================================

ARG BASE_IMAGE=paulohenriquevn/voice-base:latest
FROM ${BASE_IMAGE}

WORKDIR /app

# Copia modulos compartilhados PRIMEIRO
COPY shared/asp_protocol/ ./shared/asp_protocol/
COPY shared/shared_config/ ./shared/shared_config/
COPY shared/ws/ ./shared/ws/

# Copia codigo do ai-transcribe por ULTIMO (muda frequentemente)
COPY ai-transcribe/config.py .
COPY ai-transcribe/ai_transcribe.py .
COPY ai-transcribe/metrics/ ./metrics/
COPY ai-transcribe/server/ ./server/
COPY ai-transcribe/transcriber/ ./transcriber/
COPY ai-transcribe/indexer/ ./indexer/
COPY ai-transcribe/embeddings/ ./embeddings/

# =============================================================================
# Variaveis de ambiente padrao
# =============================================================================

# WebSocket
ENV WS_HOST=0.0.0.0
ENV WS_PORT=8766

# Logging
ENV LOG_LEVEL=INFO

# ASR/STT - FasterWhisper
ENV STT_PROVIDER=faster-whisper
ENV STT_MODEL=tiny
ENV STT_LANGUAGE=pt
ENV STT_COMPUTE_TYPE=int8
ENV STT_DEVICE=cpu

# Elasticsearch
ENV ES_HOSTS=http://elasticsearch:9200
ENV ES_INDEX_PREFIX=voice-transcriptions

# Metricas
ENV METRICS_PORT=9093

# Python path para modulos compartilhados
ENV PYTHONPATH=/app:/app/shared

# Expoe portas
EXPOSE 8766 9093

# Comando de entrada
CMD ["python", "ai_transcribe.py"]
