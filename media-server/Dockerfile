# Dockerfile para Media Server (SIP Bridge)
# ==========================================
# Build: docker build -t media-server .
# Run:   docker run --rm -it --network host media-server

FROM python:3.11-slim

# Instala dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libasound2-dev \
    libssl-dev \
    libopus-dev \
    libspeex-dev \
    libspeexdsp-dev \
    libsamplerate0-dev \
    portaudio19-dev \
    swig \
    pkg-config \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Compila PJSIP
WORKDIR /tmp
RUN git clone --depth 1 --branch 2.14 https://github.com/pjsip/pjproject.git

WORKDIR /tmp/pjproject
RUN ./configure \
    --enable-shared \
    --disable-video \
    --disable-v4l2 \
    --disable-opencore-amr \
    --disable-silk \
    --disable-bcg729 \
    --disable-gsm-codec \
    --disable-ilbc-codec \
    --disable-l16-codec \
    --disable-g722-codec \
    --disable-g7221-codec \
    --with-external-opus \
    --with-external-speex \
    CFLAGS="-fPIC -O2" \
    && make dep \
    && make \
    && make install \
    && ldconfig

# Instala bindings Python
WORKDIR /tmp/pjproject/pjsip-apps/src/swig/python
RUN make && python setup.py install

# Configura ldconfig
RUN echo "/usr/local/lib" > /etc/ld.so.conf.d/pjsip.conf && ldconfig

# Limpa
RUN rm -rf /tmp/pjproject

# Diretório da aplicação
WORKDIR /app

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código
COPY . .

# Variáveis de ambiente padrão (sobrescritas pelo docker-compose)
ENV WEBSOCKET_URL=ws://127.0.0.1:8765
ENV SIP_DOMAIN=127.0.0.1
ENV SIP_PORT=5160
ENV SIP_USERNAME=2000
ENV SIP_PASSWORD=7Wslll0Hlc6BCOv4jF51
ENV LOG_LEVEL=INFO
ENV PJSIP_LOG_LEVEL=3
ENV METRICS_PORT=9091
ENV LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# Comando de entrada
CMD ["python", "media_server.py"]
