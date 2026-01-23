FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    wget \
    curl \
    libsndfile1 \
    ffmpeg \
    # PJSIP build dependencies
    libasound2-dev \
    libssl-dev \
    libopus-dev \
    libspeex-dev \
    libsrtp2-dev \
    libv4l-dev \
    swig \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy installation scripts
COPY scripts/install_pjsip.sh scripts/install_kokoro.sh ./scripts/

# Install PJSIP with Python bindings (pjsua2)
RUN bash ./scripts/install_pjsip.sh

# Copy requirements and install Python dependencies
COPY requirements-docker.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-docker.txt

# Install Kokoro TTS (optional, from GitHub)
RUN bash ./scripts/install_kokoro.sh || echo "Warning: Kokoro TTS installation failed, continuing without it"

# CRITICAL FIX: Kokoro-ONNX installs numpy>=2.0.2, which breaks scipy 1.11.4
# Reinstall correct numpy version after Kokoro installation
RUN pip install --no-cache-dir "numpy>=1.21.6,<1.28.0" --force-reinstall

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create directories
RUN mkdir -p /app/logs /app/models

# Expose ports
# SIP signaling
EXPOSE 5060/udp
EXPOSE 5060/tcp

# RTP media
EXPOSE 10000-20000/udp

# Metrics API (Prometheus format)
EXPOSE 8001/tcp

# Run application
CMD ["python", "src/main.py", "--config", "config/default.yaml"]
