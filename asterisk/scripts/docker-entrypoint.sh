#!/bin/sh
set -e

# =============================================================================
# Asterisk Docker Entrypoint - NAT/Bridge Networking
# =============================================================================
# Resolves the Docker host IP and configures external_media_address
# in pjsip.conf for proper NAT traversal when running in bridge networking.
#
# Without this, WebRTC clients (browsers) cannot reach the container's
# internal IP (172.x.x.x) on Docker Desktop (Windows/macOS).
#
# Environment:
#   EXTERNAL_MEDIA_IP - "auto" (default, resolves host.docker.internal)
#                       or a specific IP address
# =============================================================================

resolve_host_ip() {
    # Method 1: getent (glibc-based systems like Debian)
    ip=$(getent hosts host.docker.internal 2>/dev/null | awk '{print $1}')
    if [ -n "$ip" ]; then echo "$ip"; return 0; fi

    # Method 2: ping (busybox/Alpine)
    ip=$(ping -c1 -W1 host.docker.internal 2>/dev/null | head -1 | sed 's/.*(\([0-9.]*\)).*/\1/')
    if [ -n "$ip" ]; then echo "$ip"; return 0; fi

    # Method 3: nslookup
    ip=$(nslookup host.docker.internal 2>/dev/null | awk '/^Address: / { print $2 }' | tail -1)
    if [ -n "$ip" ]; then echo "$ip"; return 0; fi

    return 1
}

EXTERNAL_IP="${EXTERNAL_MEDIA_IP:-auto}"

if [ "$EXTERNAL_IP" = "auto" ]; then
    EXTERNAL_IP=$(resolve_host_ip) || EXTERNAL_IP=""
fi

PJSIP_TEMPLATE="/etc/asterisk/pjsip.conf.template"
PJSIP_CONF="/etc/asterisk/pjsip.conf"

# Template é montado como :ro (bind mount). Copia para path writável.
if [ -f "$PJSIP_TEMPLATE" ]; then
    cp "$PJSIP_TEMPLATE" "$PJSIP_CONF"
fi

if [ -n "$EXTERNAL_IP" ] && [ -f "$PJSIP_CONF" ]; then
    echo "[asterisk-entrypoint] NAT: external_media_address=$EXTERNAL_IP"
    sed -i "s/__EXTERNAL_IP__/$EXTERNAL_IP/g" "$PJSIP_CONF"
elif [ -f "$PJSIP_CONF" ]; then
    echo "[asterisk-entrypoint] WARNING: Could not resolve host IP."
    echo "[asterisk-entrypoint] Media will rely on TURN relay for NAT traversal."
    sed -i '/__EXTERNAL_IP__/d' "$PJSIP_CONF"
fi

exec "$@"
