#!/bin/bash
#===============================================
# Script para Ver Logs do PABX Docker
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
    BLUE='\033[0;34m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
else
    BLUE=''
    YELLOW=''
    NC=''
fi

log_info() { echo -e "${BLUE}$1${NC}"; }
log_warn() { echo -e "${YELLOW}$1${NC}"; }

#-----------------------------------------------
# Verifica se container existe
#-----------------------------------------------
container_exists() {
    local container_name="$1"
    docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${container_name}$"
}

#-----------------------------------------------
# Mostra uso
#-----------------------------------------------
show_usage() {
    echo "Uso: $0 [servico] [opcoes]"
    echo ""
    echo "Servicos:"
    echo "   asterisk, ast    - Logs do Asterisk"
    echo "   agent, ai        - Logs do AI Agent"
    echo "   media            - Logs do Media Server"
    echo "   transcribe, tr   - Logs do AI Transcribe"
    echo "   elasticsearch,es - Logs do Elasticsearch"
    echo "   prometheus       - Logs do Prometheus"
    echo "   grafana          - Logs do Grafana"
    echo "   coturn           - Logs do CoTURN"
    echo "   all              - Logs de todos (padrao)"
    echo ""
    echo "Opcoes:"
    echo "   -n, --no-follow  - Mostra logs sem acompanhar"
    echo "   -t, --tail N     - Mostra ultimas N linhas (padrao: 100)"
    echo "   -h, --help       - Mostra esta ajuda"
    echo ""
    echo "Exemplos:"
    echo "   $0               - Mostra todos os logs (acompanhando)"
    echo "   $0 asterisk      - Mostra logs do Asterisk"
    echo "   $0 transcribe    - Mostra logs do AI Transcribe"
    echo "   $0 agent -n      - Mostra logs do Agent sem acompanhar"
    echo "   $0 -t 50         - Ultimas 50 linhas de todos"
}

#===============================================
# INÍCIO DA EXECUÇÃO
#===============================================

SERVICE="${1:-all}"
FOLLOW="true"
TAIL_LINES="100"

# Parse argumentos
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--no-follow)
            FOLLOW="false"
            shift
            ;;
        -t|--tail)
            TAIL_LINES="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        asterisk|ast|agent|ai|media|transcribe|tr|elasticsearch|es|prometheus|grafana|coturn|all)
            SERVICE="$1"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# Verifica Docker
if ! docker info > /dev/null 2>&1; then
    log_warn "Docker nao esta rodando!"
    exit 1
fi

# Mapeia serviço para container
get_container_name() {
    case "$1" in
        asterisk|ast) echo "asterisk-pabx" ;;
        agent|ai) echo "ai-conversation-agent" ;;
        media) echo "sip-media-server" ;;
        transcribe|tr) echo "ai-transcribe" ;;
        elasticsearch|es) echo "elasticsearch" ;;
        prometheus) echo "prometheus" ;;
        grafana) echo "grafana" ;;
        coturn) echo "coturn-turn" ;;
        *) echo "" ;;
    esac
}

# Mostra logs de um serviço específico
show_service_logs() {
    local container="$1"

    if ! container_exists "$container"; then
        log_warn "Container '$container' nao existe"
        return 1
    fi

    if [ "$FOLLOW" = "true" ]; then
        docker logs -f --tail "$TAIL_LINES" "$container"
    else
        docker logs --tail "$TAIL_LINES" "$container"
    fi
}

case "$SERVICE" in
    asterisk|ast|agent|ai|media|transcribe|tr|elasticsearch|es|prometheus|grafana|coturn)
        container=$(get_container_name "$SERVICE")
        log_info "Logs de $SERVICE ($container):"
        show_service_logs "$container"
        ;;
    all|*)
        log_info "Logs de todos os servicos:"
        log_info "(Ctrl+C para sair)"
        echo ""

        if [ "$FOLLOW" = "true" ]; then
            # Usa docker-compose logs para todos
            $DOCKER_COMPOSE logs -f --tail "$TAIL_LINES"
        else
            $DOCKER_COMPOSE logs --tail "$TAIL_LINES"
        fi
        ;;
esac
