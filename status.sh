#!/bin/bash
#===============================================
# Script para Ver Status do PABX Docker
# Compatível com Linux e Windows (Git Bash)
#===============================================

#-----------------------------------------------
# Detecta diretório do script
#-----------------------------------------------
get_script_dir() {
    local source="${BASH_SOURCE[0]}"
    while [ -h "$source" ]; do
        local dir="$(cd -P "$(dirname "$source")" && pwd)"
        source="$(readlink "$source")"
        [[ $source != /* ]] && source="$dir/$source"
    done
    cd -P "$(dirname "$source")" && pwd
}

SCRIPT_DIR="$(get_script_dir)"
cd "$SCRIPT_DIR"

#-----------------------------------------------
# Cores
#-----------------------------------------------
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

log_info()    { echo -e "${BLUE}$1${NC}"; }
log_success() { echo -e "${GREEN}$1${NC}"; }
log_warn()    { echo -e "${YELLOW}$1${NC}"; }
log_error()   { echo -e "${RED}$1${NC}"; }

#-----------------------------------------------
# Verifica status de um container
#-----------------------------------------------
check_container() {
    local container_name="$1"
    local display_name="$2"

    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${container_name}$"; then
        local health=$(docker inspect --format='{{.State.Health.Status}}' "$container_name" 2>/dev/null || echo "running")
        if [ "$health" = "healthy" ]; then
            printf "   %-20s ${GREEN}Rodando (healthy)${NC}\n" "$display_name:"
        else
            printf "   %-20s ${GREEN}Rodando${NC}\n" "$display_name:"
        fi
        return 0
    else
        printf "   %-20s ${RED}Parado${NC}\n" "$display_name:"
        return 1
    fi
}

#===============================================
# INÍCIO DA EXECUÇÃO
#===============================================

log_info "================================================"
log_info "          PABX Docker - Status                  "
log_info "================================================"
echo ""

# Verifica se Docker está rodando
if ! docker info > /dev/null 2>&1; then
    log_error "Docker nao esta rodando!"
    exit 1
fi

# Status dos containers
log_info "Containers:"
echo ""

check_container "asterisk-pabx" "Asterisk"
check_container "ai-conversation-agent" "AI Agent"
check_container "sip-media-server" "Media Server"
check_container "elasticsearch" "Elasticsearch"
check_container "ai-transcribe" "AI Transcribe"
check_container "coturn-turn" "CoTURN"
check_container "prometheus" "Prometheus"
check_container "grafana" "Grafana"

echo ""

# Endpoints registrados
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^asterisk-pabx$"; then
    log_info "Endpoints PJSIP:"
    echo ""
    docker exec asterisk-pabx asterisk -rx "pjsip show endpoints" 2>/dev/null | grep -E "Endpoint:|Contact:" | head -20 || echo "   Nenhum endpoint"
    echo ""

    log_info "Ramais Online:"
    echo ""
    docker exec asterisk-pabx asterisk -rx "pjsip show contacts" 2>/dev/null | grep -E "Contact|sip:" | head -20 || echo "   Nenhum ramal online"
fi

echo ""
log_info "URLs de Acesso:"
echo "   Elasticsearch: http://localhost:9200"
echo "   Kibana:        http://localhost:5601 (--profile debug)"
echo "   Prometheus:    http://localhost:9092"
echo "   Grafana:       http://localhost:3000 (admin/admin)"
echo ""
log_info "================================================"
