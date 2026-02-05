#!/bin/sh
set -e

# =============================================================================
# Coturn Docker Entrypoint - External IP for Bridge Networking
# =============================================================================
# Resolves the Docker host IP and passes it as --external-ip to turnserver.
#
# Without external-ip, TURN relay candidates use the container's internal IP
# (172.x.x.x), which browsers on Docker Desktop (Windows/macOS) cannot reach.
#
# Environment:
#   EXTERNAL_TURN_IP - "auto" (default, resolves host.docker.internal)
#                      or a specific IP address
# =============================================================================

resolve_host_ip() {
    ip=$(getent hosts host.docker.internal 2>/dev/null | awk '{print $1}')
    if [ -n "$ip" ]; then echo "$ip"; return 0; fi

    ip=$(ping -c1 -W1 host.docker.internal 2>/dev/null | head -1 | sed 's/.*(\([0-9.]*\)).*/\1/')
    if [ -n "$ip" ]; then echo "$ip"; return 0; fi

    ip=$(nslookup host.docker.internal 2>/dev/null | awk '/^Address: / { print $2 }' | tail -1)
    if [ -n "$ip" ]; then echo "$ip"; return 0; fi

    return 1
}

EXTERNAL_IP="${EXTERNAL_TURN_IP:-auto}"

if [ "$EXTERNAL_IP" = "auto" ]; then
    EXTERNAL_IP=$(resolve_host_ip) || EXTERNAL_IP=""
fi

if [ -n "$EXTERNAL_IP" ]; then
    echo "[coturn-entrypoint] external-ip=$EXTERNAL_IP"
    exec turnserver -c /etc/coturn/turnserver.conf --external-ip="$EXTERNAL_IP"
else
    echo "[coturn-entrypoint] WARNING: Could not resolve host IP. Running without external-ip."
    echo "[coturn-entrypoint] TURN relay candidates will use container internal IP."
    exec turnserver -c /etc/coturn/turnserver.conf
fi
