#!/bin/bash
#===============================================
# Script para Parar o PABX Docker
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
# Detecta comando docker-compose
#-----------------------------------------------
get_docker_compose_cmd() {
    if command -v docker-compose &> /dev/null; then
        echo "docker-compose"
    elif docker compose version &> /dev/null 2>&1; then
        echo "docker compose"
    else
        echo ""
    fi
}

DOCKER_COMPOSE="$(get_docker_compose_cmd)"

#-----------------------------------------------
# Cores
#-----------------------------------------------
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    NC=''
fi

log_warn()    { echo -e "${YELLOW}$1${NC}"; }
log_success() { echo -e "${GREEN}$1${NC}"; }
log_error()   { echo -e "${RED}$1${NC}"; }

#===============================================
# INÍCIO DA EXECUÇÃO
#===============================================

if [ -z "$DOCKER_COMPOSE" ]; then
    log_error "docker-compose ou docker compose nao encontrado!"
    exit 1
fi

log_warn "Parando PABX Docker..."
log_warn "   Parando todos os servicos..."

$DOCKER_COMPOSE down 2>/dev/null || true

log_success "Sistema parado"
