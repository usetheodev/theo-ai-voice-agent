#!/bin/bash
#===============================================
# Script para iniciar com AI Transcribe habilitado
# Inicia Elasticsearch, AI-Transcribe e Media Server
#===============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Cores
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

log_info()    { echo -e "${BLUE}$1${NC}"; }
log_success() { echo -e "${GREEN}$1${NC}"; }
log_warn()    { echo -e "${YELLOW}$1${NC}"; }

log_info "================================================"
log_info "   PABX Docker - Iniciando com AI Transcribe    "
log_info "================================================"
echo ""

# Exporta variável para habilitar transcribe
export TRANSCRIBE_ENABLED=true

log_warn "TRANSCRIBE_ENABLED=true"
echo ""

# Executa start.sh normal
exec ./start.sh
