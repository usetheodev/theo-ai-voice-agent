FROM coturn/coturn:4.6

# Copy configuration
COPY turnserver.conf /etc/turnserver.conf

# Expose ports
# STUN/TURN UDP
EXPOSE 3478/udp
# STUN/TURN TCP
EXPOSE 3478/tcp
# TURN TLS
EXPOSE 5349/tcp
# Relay ports range
EXPOSE 49152-65535/udp

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD turnadmin -l || exit 1

# Run coturn
CMD ["turnserver", "-c", "/etc/turnserver.conf"]
