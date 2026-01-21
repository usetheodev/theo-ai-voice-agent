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
FROM debian:bullseye-slim

# Metadata
LABEL maintainer="Voice Engineering Team"
LABEL description="Asterisk for AI Voice Agent E2E Testing with WebRTC"

# Evitar interação durante instalação
ENV DEBIAN_FRONTEND=noninteractive

# Install Asterisk from Debian packages (much faster than compiling)
RUN apt-get update && apt-get install -y \
    asterisk \
    asterisk-modules \
    asterisk-core-sounds-en \
    asterisk-core-sounds-en-gsm \
    curl \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# Create directories
RUN mkdir -p /var/log/asterisk \
             /var/lib/asterisk \
             /var/spool/asterisk \
             /etc/asterisk \
             /etc/asterisk/keys

# Copy custom configurations
COPY config/* /etc/asterisk/

# ===== Browser Phone files for WebRTC client =====
# Asterisk Debian package serves static files from /usr/share/asterisk/static-http/ by default
RUN mkdir -p /usr/share/asterisk/static-http
COPY --from=browser-phone-source /app/Phone /usr/share/asterisk/static-http/
RUN chmod -R 755 /usr/share/asterisk/static-http

# Set permissions (asterisk user already created by debian package)
RUN chown -R asterisk:asterisk /var/log/asterisk \
                               /var/lib/asterisk \
                               /var/spool/asterisk \
                               /etc/asterisk

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
