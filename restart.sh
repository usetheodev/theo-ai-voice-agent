#!/bin/bash
#===============================================
# Script de Restart do PABX Docker
# Compativel com Linux e Windows (Git Bash)
#===============================================
# Uso:
#   ./restart.sh                    # Restart completo
#   ./restart.sh ai-agent           # Restart apenas do ai-agent
#   ./restart.sh media-server       # Restart apenas do media-server
#   ./restart.sh --build            # Restart com rebuild das imagens
#   ./restart.sh --transcribe       # Restart com transcribe habilitado
#   ./restart.sh ai-agent --build   # Restart do ai-agent com rebuild
#===============================================

set -e

#-----------------------------------------------
# Detecta diretorio do script
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
log_warn()    { echo -e "${YELLOW}$1${NC}"; }
log_success() { echo -e "${GREEN}$1${NC}"; }
log_error()   { echo -e "${RED}$1${NC}"; }

#-----------------------------------------------
# Mostra uso
#-----------------------------------------------
show_usage() {
    echo "Uso: $0 [servico] [opcoes]"
    echo ""
    echo "Servicos disponiveis:"
    echo "  ai-agent       Reinicia apenas o AI Agent"
    echo "  media-server   Reinicia apenas o Media Server"
    echo "  ai-transcribe  Reinicia apenas o AI Transcribe"
    echo "  asterisk       Reinicia apenas o Asterisk"
    echo "  elasticsearch  Reinicia apenas o Elasticsearch"
    echo "  prometheus     Reinicia apenas o Prometheus"
    echo "  grafana        Reinicia apenas o Grafana"
    echo ""
    echo "Opcoes:"
    echo "  --build        Rebuild da imagem antes de reiniciar"
    echo "  --transcribe   Habilita transcricao (TRANSCRIBE_ENABLED=true)"
    echo "  --help         Mostra esta ajuda"
    echo ""
    echo "Exemplos:"
    echo "  $0                         # Restart completo"
    echo "  $0 ai-agent                # Restart apenas ai-agent"
    echo "  $0 ai-agent --build        # Restart ai-agent com rebuild"
    echo "  $0 --build --transcribe    # Restart completo com rebuild e transcribe"
}

#-----------------------------------------------
# Parse argumentos
#-----------------------------------------------
SERVICE=""
DO_BUILD=""
TRANSCRIBE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --build)
            DO_BUILD="1"
            shift
            ;;
        --transcribe)
            TRANSCRIBE="1"
            shift
            ;;
        --help|-h)
            show_usage
            exit 0
            ;;
        -*)
            log_error "Opcao desconhecida: $1"
            show_usage
            exit 1
            ;;
        *)
            if [ -z "$SERVICE" ]; then
                SERVICE="$1"
            else
                log_error "Apenas um servico pode ser especificado"
                show_usage
                exit 1
            fi
            shift
            ;;
    esac
done

#-----------------------------------------------
# Valida servico
#-----------------------------------------------
VALID_SERVICES="ai-agent media-server ai-transcribe asterisk elasticsearch prometheus grafana coturn"

if [ -n "$SERVICE" ]; then
    if ! echo "$VALID_SERVICES" | grep -qw "$SERVICE"; then
        log_error "Servico invalido: $SERVICE"
        echo "Servicos validos: $VALID_SERVICES"
        exit 1
    fi
fi

#===============================================
# INICIO DA EXECUCAO
#===============================================

if [ -z "$DOCKER_COMPOSE" ]; then
    log_error "docker-compose ou docker compose nao encontrado!"
    exit 1
fi

# Habilita transcribe se solicitado
if [ -n "$TRANSCRIBE" ]; then
    export TRANSCRIBE_ENABLED=true
    log_warn "TRANSCRIBE_ENABLED=true"
fi

# Mapeia nome do servico para nome do container
get_container_name() {
    case $1 in
        ai-agent)       echo "ai-conversation-agent" ;;
        media-server)   echo "sip-media-server" ;;
        ai-transcribe)  echo "ai-transcribe" ;;
        asterisk)       echo "asterisk-pabx" ;;
        elasticsearch)  echo "elasticsearch" ;;
        prometheus)     echo "prometheus" ;;
        grafana)        echo "grafana" ;;
        coturn)         echo "coturn-turn" ;;
        *)              echo "$1" ;;
    esac
}

#-----------------------------------------------
# Restart de servico especifico
#-----------------------------------------------
restart_service() {
    local service="$1"
    local container=$(get_container_name "$service")

    log_info "================================================"
    log_info "   Reiniciando: $service"
    log_info "================================================"

    # Para o servico
    log_warn "Parando $service..."
    $DOCKER_COMPOSE stop "$service" 2>/dev/null || true
    $DOCKER_COMPOSE rm -f "$service" 2>/dev/null || true

    # Rebuild se solicitado
    if [ -n "$DO_BUILD" ]; then
        log_warn "Reconstruindo imagem..."
        # Garante builder default para acesso a imagens locais
        docker buildx use default 2>/dev/null || true
        $DOCKER_COMPOSE build "$service"
    fi

    # Inicia o servico
    log_warn "Iniciando $service..."
    $DOCKER_COMPOSE up -d "$service"

    # Aguarda ficar pronto
    log_warn "Aguardando $service ficar pronto..."
    local timeout=60
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${container}$"; then
            local status=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "unknown")
            local health=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "none")

            if [ "$status" = "running" ]; then
                if [ "$health" = "healthy" ] || [ "$health" = "none" ] || [ "$health" = "" ]; then
                    log_success "   $service: OK"
                    return 0
                fi
            fi
        fi
        sleep 2
        ((elapsed+=2))
        echo -n "."
    done

    echo ""
    log_error "   $service: TIMEOUT"
    $DOCKER_COMPOSE logs --tail=20 "$service"
    return 1
}

#-----------------------------------------------
# Restart completo
#-----------------------------------------------
restart_all() {
    log_info "================================================"
    log_info "       PABX Docker - Restart Completo           "
    log_info "================================================"

    if [ -n "$DO_BUILD" ]; then
        log_warn "Modo: Restart com rebuild"
    else
        log_warn "Modo: Restart rapido (sem rebuild)"
    fi
    echo ""

    # Para tudo
    log_warn "Parando todos os servicos..."
    $DOCKER_COMPOSE down 2>/dev/null || true

    # Rebuild se solicitado
    if [ -n "$DO_BUILD" ]; then
        log_warn "Reconstruindo imagens..."
        # Garante builder default para acesso a imagens locais
        docker buildx use default 2>/dev/null || true
        $DOCKER_COMPOSE build
    fi

    # Inicia tudo
    log_warn "Iniciando todos os servicos..."
    $DOCKER_COMPOSE up -d

    # Aguarda servicos principais
    log_warn "Aguardando servicos inicializarem..."
    sleep 5

    # Verifica status
    local services_ok=0
    local services_fail=0

    for svc in asterisk ai-agent media-server; do
        local container=$(get_container_name "$svc")
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${container}$"; then
            log_success "   $svc: OK"
            ((services_ok++))
        else
            log_error "   $svc: FALHA"
            ((services_fail++))
        fi
    done

    # Servicos opcionais
    for svc in elasticsearch ai-transcribe prometheus grafana; do
        local container=$(get_container_name "$svc")
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${container}$"; then
            log_success "   $svc: OK"
            ((services_ok++))
        fi
    done

    echo ""
    if [ $services_fail -eq 0 ]; then
        log_success "================================================"
        log_success "       RESTART CONCLUIDO COM SUCESSO            "
        log_success "================================================"
    else
        log_error "================================================"
        log_error "   RESTART CONCLUIDO COM $services_fail FALHA(S)"
        log_error "================================================"
        log_warn "Use './logs.sh' para verificar os erros"
        exit 1
    fi
}

#===============================================
# EXECUCAO
#===============================================

if [ -n "$SERVICE" ]; then
    restart_service "$SERVICE"
else
    restart_all
fi
