FROM python:3.11-slim-bookworm

LABEL maintainer="AI Voice Agent Project"
LABEL description="AI Voice Agent with Whisper + LLM + TTS"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    cmake \
    wget \
    curl \
    ffmpeg \
    portaudio19-dev \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY ./requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Whisper.cpp
RUN git clone https://github.com/ggerganov/whisper.cpp.git /tmp/whisper.cpp && \
    cd /tmp/whisper.cpp && \
    make && \
    cp build/bin/main /usr/local/bin/whisper-cpp && \
    cp build/libwhisper.so /usr/local/lib/ 2>/dev/null || \
    cp libwhisper.so /usr/local/lib/ || true && \
    ldconfig && \
    rm -rf /tmp/whisper.cpp

# Install llama.cpp (for LLM)
RUN git clone https://github.com/ggerganov/llama.cpp.git /tmp/llama.cpp && \
    cd /tmp/llama.cpp && \
    make && \
    cp build/bin/llama-cli /usr/local/bin/llama-cpp 2>/dev/null || \
    cp llama-cli /usr/local/bin/llama-cpp || \
    cp main /usr/local/bin/llama-cpp || true && \
    rm -rf /tmp/llama.cpp

# Install Piper TTS
RUN wget -qO- https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz | \
    tar -xvz -C /usr/local/bin/

# Create directories for models and logs
RUN mkdir -p /app/models/{whisper,llm,tts} /app/logs

# Copy application code
# Note: Build context is project root (see docker-compose.yml)
COPY ./src /app/src
COPY ./config.yaml /app/

# Expose ports
# RTP
EXPOSE 5080/udp
# Prometheus metrics (optional)
EXPOSE 9090/tcp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD nc -z -u 127.0.0.1 5080 || exit 1

# Copy entrypoint
COPY ./docker/ai-agent/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-u", "src/main.py"]
