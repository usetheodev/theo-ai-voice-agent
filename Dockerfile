FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    libsndfile1 \
    ffmpeg \
    # PJSIP dependencies
    libasound2-dev \
    libssl-dev \
    libopus-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for caching)
COPY pyproject.toml ./
COPY README.md ./

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create directories
RUN mkdir -p /app/logs /app/models

# Expose ports
# SIP signaling
EXPOSE 5060/udp

# RTP media
EXPOSE 10000-20000/udp

# Metrics
EXPOSE 8000

# Run application
CMD ["python", "src/main.py", "--config", "config/default.yaml"]
