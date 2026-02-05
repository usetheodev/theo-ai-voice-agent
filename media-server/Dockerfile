# syntax=docker/dockerfile:1.4
# =============================================================================
# Dockerfile Media Server - Usa imagem base voice-base
# =============================================================================
# Build context deve ser a raiz do projeto:
#   docker build -f media-server/Dockerfile -t media-server .
# =============================================================================

ARG BASE_IMAGE=paulohenriquevn/voice-base:latest
FROM ${BASE_IMAGE}

WORKDIR /app

# Copia modulos compartilhados PRIMEIRO (mudam menos frequentemente)
COPY shared/asp_protocol/ ./shared/asp_protocol/
COPY shared/shared_config/ ./shared/shared_config/
COPY shared/ws/ ./shared/ws/

# Copia codigo do media-server
COPY media-server/ .

# =============================================================================
# Variaveis de ambiente padrao (sobrescritas pelo docker-compose)
# =============================================================================

ENV WEBSOCKET_URL=ws://127.0.0.1:8765
ENV TRANSCRIBE_URL=ws://127.0.0.1:8766
ENV TRANSCRIBE_ENABLED=false
ENV SIP_DOMAIN=127.0.0.1
ENV SIP_PORT=5160
ENV SIP_USERNAME=2000
ENV SIP_PASSWORD=7Wslll0Hlc6BCOv4jF51
ENV LOG_LEVEL=INFO
ENV PJSIP_LOG_LEVEL=3
ENV METRICS_PORT=9091

# PJSIP libs
ENV LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# Python path para modulos compartilhados
ENV PYTHONPATH=/app:/app/shared

# Expoe porta de metricas
EXPOSE 9091

# Comando de entrada
CMD ["python", "media_server.py"]
