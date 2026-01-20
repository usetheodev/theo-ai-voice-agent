# ===== STAGE 1: Browser Phone (WebRTC Client) =====
FROM node:18-alpine AS browser-phone-source

WORKDIR /app

# Clone Browser Phone from InnovateAsterisk
RUN apk add --no-cache git && \
    git clone https://github.com/InnovateAsterisk/Browser-Phone.git && \
    mv Browser-Phone/Phone ./Phone && \
    rm -rf Browser-Phone

# Verify files exist
RUN ls -la Phone/ && \
    test -f Phone/index.html || (echo "ERROR: Browser-Phone files not found!" && exit 1)

# ===== STAGE 2: Asterisk =====
FROM ubuntu:22.04

# Metadata
LABEL maintainer="Voice Engineering Team"
LABEL description="Asterisk for AI Voice Agent E2E Testing with WebRTC"

# Evitar interação durante instalação
ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y \
    # Build tools
    build-essential \
    wget \
    curl \
    git \
    pkg-config \
    # Asterisk dependencies
    libncurses5-dev \
    libssl-dev \
    libxml2-dev \
    libsqlite3-dev \
    uuid-dev \
    libjansson-dev \
    libedit-dev \
    # Audio codecs
    libspeex-dev \
    libspeexdsp-dev \
    libopus-dev \
    # Utilities
    tcpdump \
    net-tools \
    vim \
    && rm -rf /var/lib/apt/lists/*

# Download and compile Asterisk
WORKDIR /tmp
RUN wget http://downloads.asterisk.org/pub/telephony/asterisk/asterisk-20-current.tar.gz && \
    tar -xzf asterisk-20-current.tar.gz && \
    cd asterisk-20.* && \
    ./configure --with-jansson-bundled && \
    make menuselect.makeopts && \
    # Disable unnecessary modules to speed up build
    menuselect/menuselect --disable BUILD_NATIVE \
                          --enable cdr_csv \
                          --enable res_http_websocket \
                          --enable res_ari \
                          --enable res_pjsip \
                          menuselect.makeopts && \
    make -j$(nproc) && \
    make install && \
    make samples && \
    make config && \
    ldconfig && \
    # Cleanup
    cd / && rm -rf /tmp/asterisk-*

# Create directories
RUN mkdir -p /var/log/asterisk \
             /var/lib/asterisk \
             /var/spool/asterisk \
             /etc/asterisk \
             /etc/asterisk/keys

# Copy custom configurations
COPY config/* /etc/asterisk/

# ===== Browser Phone files for WebRTC client =====
# Asterisk expects static files in /usr/share/asterisk/static-http/
RUN mkdir -p /usr/share/asterisk/static-http
COPY --from=browser-phone-source /app/Phone /usr/share/asterisk/static-http/
RUN chmod -R 755 /usr/share/asterisk/static-http

# Create asterisk user
RUN useradd -m asterisk && \
    chown -R asterisk:asterisk /var/log/asterisk \
                               /var/lib/asterisk \
                               /var/spool/asterisk \
                               /etc/asterisk \
                               /usr/share/asterisk/static-http

# Expose ports
# SIP signaling
EXPOSE 5060/udp 5060/tcp

# RTP media
EXPOSE 10000-10100/udp

# ARI (REST interface)
EXPOSE 8088/tcp

# HTTP/HTTPS for WebRTC
EXPOSE 8080/tcp 8089/tcp

# Copy entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Set working directory
WORKDIR /etc/asterisk

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
    CMD asterisk -rx "core show version" || exit 1

# Use entrypoint script
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
