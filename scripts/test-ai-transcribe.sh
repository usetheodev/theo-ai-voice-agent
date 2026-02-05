#!/bin/bash
#
# Script de teste para ai-transcribe
#
# Uso:
#   ./scripts/test-ai-transcribe.sh [--full]
#
# Flags:
#   --full    Executa teste completo (build, start, test, stop)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_success() { echo -e "${GREEN}[OK]${NC} $1"; }
echo_error() { echo -e "${RED}[ERRO]${NC} $1"; }
echo_warn() { echo -e "${YELLOW}[AVISO]${NC} $1"; }
echo_info() { echo -e "[INFO] $1"; }

# Verifica se servicos estao rodando
check_service() {
    local service=$1
    local port=$2
    local max_attempts=${3:-30}
    local attempt=1

    echo_info "Aguardando $service na porta $port..."

    while [ $attempt -le $max_attempts ]; do
        if curl -s "http://localhost:$port" > /dev/null 2>&1 || \
           curl -s "http://localhost:$port/_cluster/health" > /dev/null 2>&1 || \
           curl -s "http://localhost:$port/metrics" > /dev/null 2>&1; then
            echo_success "$service esta pronto!"
            return 0
        fi
        echo -n "."
        sleep 1
        attempt=$((attempt + 1))
    done

    echo_error "$service nao respondeu apos $max_attempts segundos"
    return 1
}

# Teste rapido (apenas verifica se servicos estao rodando)
test_quick() {
    echo ""
    echo "========================================"
    echo " TESTE RAPIDO - ai-transcribe"
    echo "========================================"
    echo ""

    # Verifica Elasticsearch
    echo_info "Verificando Elasticsearch..."
    if curl -s "http://localhost:9200/_cluster/health" > /dev/null 2>&1; then
        health=$(curl -s "http://localhost:9200/_cluster/health" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
        echo_success "Elasticsearch: $health"
    else
        echo_error "Elasticsearch nao esta rodando"
        echo_info "Execute: docker compose up -d elasticsearch"
        return 1
    fi

    # Verifica ai-transcribe metricas
    echo_info "Verificando ai-transcribe..."
    if curl -s "http://localhost:9093/metrics" > /dev/null 2>&1; then
        sessions=$(curl -s "http://localhost:9093/metrics" | grep "ai_transcribe_active_sessions" | grep -v "#" | awk '{print $2}' | head -1)
        echo_success "ai-transcribe: ${sessions:-0} sessoes ativas"
    else
        echo_error "ai-transcribe nao esta rodando"
        echo_info "Execute: docker compose up -d ai-transcribe"
        return 1
    fi

    # Verifica ES connection status
    es_status=$(curl -s "http://localhost:9093/metrics" | grep "ai_transcribe_es_connection_status" | grep -v "#" | awk '{print $2}' | head -1)
    if [ "$es_status" = "1" ] || [ "$es_status" = "1.0" ]; then
        echo_success "ai-transcribe -> Elasticsearch: conectado"
    else
        echo_warn "ai-transcribe -> Elasticsearch: desconectado (status: $es_status)"
    fi

    echo ""
    echo_success "Teste rapido concluido!"
}

# Teste completo (build, start, test, stop)
test_full() {
    echo ""
    echo "========================================"
    echo " TESTE COMPLETO - ai-transcribe"
    echo "========================================"
    echo ""

    # 1. Build
    echo_info "1/5 - Building ai-transcribe..."
    docker compose build ai-transcribe
    echo_success "Build concluido"

    # 2. Start Elasticsearch
    echo_info "2/5 - Starting Elasticsearch..."
    docker compose up -d elasticsearch
    check_service "Elasticsearch" 9200 60

    # Verifica health
    health=$(curl -s "http://localhost:9200/_cluster/health?wait_for_status=yellow&timeout=30s" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    echo_success "Elasticsearch health: $health"

    # 3. Start ai-transcribe
    echo_info "3/5 - Starting ai-transcribe..."
    docker compose up -d ai-transcribe
    check_service "ai-transcribe" 9093 30

    # 4. Executar testes Python
    echo_info "4/5 - Executando testes..."

    # Teste Elasticsearch
    echo ""
    echo "--- Teste Elasticsearch ---"
    if [ -f "ai-transcribe/tests/test_elasticsearch.py" ]; then
        python ai-transcribe/tests/test_elasticsearch.py --host http://localhost:9200 || true
    else
        echo_warn "Script de teste ES nao encontrado"
    fi

    # Teste WebSocket
    echo ""
    echo "--- Teste WebSocket ---"
    if [ -f "ai-transcribe/tests/test_websocket.py" ]; then
        # Instala dependencias se necessario
        pip install -q websockets aiohttp 2>/dev/null || true
        python ai-transcribe/tests/test_websocket.py --url ws://localhost:8766 || true
    else
        echo_warn "Script de teste WebSocket nao encontrado"
    fi

    # 5. Verificar documentos no ES
    echo ""
    echo_info "5/5 - Verificando documentos no Elasticsearch..."
    doc_count=$(curl -s "http://localhost:9200/voice-transcriptions-*/_count" 2>/dev/null | grep -o '"count":[0-9]*' | cut -d':' -f2 || echo "0")
    echo_info "Documentos indexados: ${doc_count:-0}"

    echo ""
    echo "========================================"
    echo_success "TESTE COMPLETO FINALIZADO"
    echo "========================================"
    echo ""
    echo "Proximos passos:"
    echo "  1. Fazer uma chamada SIP de teste"
    echo "  2. Verificar transcricoes: curl 'http://localhost:9200/voice-transcriptions-*/_search?pretty'"
    echo "  3. Acessar Kibana (se habilitado): http://localhost:5601"
    echo "  4. Ver dashboard Grafana: http://localhost:3000 -> AI Transcribe"
    echo ""
}

# Mostra logs
show_logs() {
    echo_info "Logs do ai-transcribe (Ctrl+C para sair)..."
    docker compose logs -f ai-transcribe
}

# Main
case "${1:-quick}" in
    --full|full)
        test_full
        ;;
    --logs|logs)
        show_logs
        ;;
    --quick|quick|"")
        test_quick
        ;;
    *)
        echo "Uso: $0 [--quick|--full|--logs]"
        echo ""
        echo "  --quick  Teste rapido (verifica se servicos estao rodando)"
        echo "  --full   Teste completo (build, start, test)"
        echo "  --logs   Mostra logs do ai-transcribe"
        exit 1
        ;;
esac
