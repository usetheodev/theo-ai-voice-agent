# Stage 1: Get Browser-Phone source
FROM alpine/git as browser-phone-source
WORKDIR /app
RUN git clone --depth 1 https://github.com/InnovateAsterisk/Browser-Phone.git . && \
    ls -la Phone/

# Stage 2: Build Asterisk with WebRTC
FROM debian:bullseye-slim

LABEL maintainer="AI Voice Agent Project"
LABEL description="Asterisk PBX for AI Voice Agent integration with WebRTC"

# Install Asterisk and required modules
RUN apt-get update && apt-get install -y \
    asterisk \
    asterisk-modules \
    asterisk-core-sounds-en \
    asterisk-core-sounds-en-gsm \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create asterisk user (if not exists)
RUN if ! id asterisk > /dev/null 2>&1; then \
        useradd -r -s /bin/false asterisk; \
    fi

# Create necessary directories
RUN mkdir -p /var/log/asterisk \
    /var/lib/asterisk \
    /var/spool/asterisk \
    && chown -R asterisk:asterisk /var/log/asterisk \
    && chown -R asterisk:asterisk /var/lib/asterisk \
    && chown -R asterisk:asterisk /var/spool/asterisk

# Copy custom configurations
COPY configs/ /etc/asterisk/

# Copy SSL certificates for WebRTC
COPY certs/ /etc/asterisk/certs/

# Fix permissions
RUN chown -R asterisk:asterisk /etc/asterisk

# Copy Browser-Phone files for WebRTC client
RUN mkdir -p /var/lib/asterisk/static-http
COPY --from=browser-phone-source /app/Phone /var/lib/asterisk/static-http/
RUN chmod -R 755 /var/lib/asterisk/static-http

# Expose ports
# SIP
EXPOSE 5060/udp 5060/tcp
# RTP range
EXPOSE 10000-10100/udp
# ARI HTTP
EXPOSE 8088/tcp
# HTTPS/WSS for WebRTC
EXPOSE 8089/tcp 8080/tcp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD asterisk -rx "core show version" || exit 1

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Run as root (Asterisk will drop privileges internally)
# USER asterisk

ENTRYPOINT ["/entrypoint.sh"]
CMD ["asterisk", "-f", "-vvv", "-U", "asterisk", "-G", "asterisk"]
