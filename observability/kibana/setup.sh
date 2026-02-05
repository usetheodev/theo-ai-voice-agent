#!/bin/bash
# Kibana Setup Script - Importa dashboards automaticamente
# Usa a Saved Objects API do Kibana

set -e

KIBANA_URL="${KIBANA_URL:-http://kibana:5601}"
DASHBOARDS_DIR="${DASHBOARDS_DIR:-/dashboards}"
MAX_RETRIES="${MAX_RETRIES:-30}"
RETRY_INTERVAL="${RETRY_INTERVAL:-5}"

echo "Kibana Setup - Aguardando Kibana ficar disponivel..."
echo "URL: ${KIBANA_URL}"

# Aguarda Kibana ficar healthy
retry_count=0
until curl -s "${KIBANA_URL}/api/status" | grep -q '"level":"available"'; do
    retry_count=$((retry_count + 1))
    if [ $retry_count -ge $MAX_RETRIES ]; then
        echo "ERRO: Kibana nao ficou disponivel apos ${MAX_RETRIES} tentativas"
        exit 1
    fi
    echo "Aguardando Kibana... (tentativa ${retry_count}/${MAX_RETRIES})"
    sleep $RETRY_INTERVAL
done

echo "Kibana disponivel! Importando dashboards..."

# Importa cada arquivo .ndjson
import_count=0
error_count=0

for ndjson_file in "${DASHBOARDS_DIR}"/*.ndjson; do
    if [ -f "$ndjson_file" ]; then
        filename=$(basename "$ndjson_file")
        echo "Importando: ${filename}"

        response=$(curl -s -w "\n%{http_code}" -X POST \
            "${KIBANA_URL}/api/saved_objects/_import?overwrite=true" \
            -H "kbn-xsrf: true" \
            -F "file=@${ndjson_file}")

        http_code=$(echo "$response" | tail -n1)
        body=$(echo "$response" | sed '$d')

        if [ "$http_code" = "200" ]; then
            success_count=$(echo "$body" | grep -o '"successCount":[0-9]*' | cut -d':' -f2)
            echo "  OK - ${success_count:-0} objetos importados"
            import_count=$((import_count + 1))
        else
            echo "  ERRO (HTTP ${http_code}): ${body}"
            error_count=$((error_count + 1))
        fi
    fi
done

echo ""
echo "=== Setup Concluido ==="
echo "Dashboards importados: ${import_count}"
echo "Erros: ${error_count}"

if [ $error_count -gt 0 ]; then
    exit 1
fi

echo "Kibana pronto para uso!"
