#!/bin/bash
#===============================================
# Script de Inicialização do PABX Docker
# Compatível com Linux e Windows (Git Bash)
#===============================================

set -e

#-----------------------------------------------
# Parsing de argumentos
#-----------------------------------------------
DEBUG_MODE=false
PROFILE_ARGS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --debug)
            DEBUG_MODE=true
            PROFILE_ARGS="--profile debug"
            shift
            ;;
        --help|-h)
            echo "Uso: $0 [opcoes]"
            echo ""
            echo "Opcoes:"
            echo "  --debug    Inicia com Kibana e ferramentas de debug"
            echo "  --help     Mostra esta ajuda"
            exit 0
            ;;
        *)
            echo "Opcao desconhecida: $1"
            echo "Use --help para ver opcoes disponiveis"
            exit 1
            ;;
    esac
done

#-----------------------------------------------
# Detecta diretório do script (cross-platform)
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
# Detecta SO
#-----------------------------------------------
detect_os() {
    case "$(uname -s)" in
        Linux*)     echo "linux";;
        Darwin*)    echo "macos";;
        CYGWIN*|MINGW*|MSYS*) echo "windows";;
        *)          echo "unknown";;
    esac
}

OS_TYPE="$(detect_os)"

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
# Cores para output (compatível com Git Bash)
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

#-----------------------------------------------
# Funções de output
#-----------------------------------------------
log_info()    { echo -e "${BLUE}$1${NC}"; }
log_success() { echo -e "${GREEN}$1${NC}"; }
log_warn()    { echo -e "${YELLOW}$1${NC}"; }
log_error()   { echo -e "${RED}$1${NC}"; }

#-----------------------------------------------
# Verifica dependências
#-----------------------------------------------
check_dependencies() {
    local missing=()

    if ! command -v docker &> /dev/null; then
        missing+=("docker")
    fi

    if [ -z "$DOCKER_COMPOSE" ]; then
        missing+=("docker-compose ou docker compose")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Dependencias faltando: ${missing[*]}"
        exit 1
    fi
}

#-----------------------------------------------
# Verifica se Docker está rodando
#-----------------------------------------------
check_docker_running() {
    if ! docker info > /dev/null 2>&1; then
        log_error "Docker nao esta rodando!"

        case "$OS_TYPE" in
            linux)
                echo "   Execute: sudo systemctl start docker"
                echo "   Ou:      sudo service docker start"
                ;;
            macos)
                echo "   Inicie o Docker Desktop no menu de aplicativos"
                ;;
            windows)
                echo "   Inicie o Docker Desktop pelo menu Iniciar"
                echo "   Aguarde o icone do Docker ficar verde na bandeja"
                ;;
            *)
                echo "   Inicie o servico Docker manualmente"
                ;;
        esac
        exit 1
    fi
}

#-----------------------------------------------
# Gera certificados SSL
#-----------------------------------------------
generate_ssl_certs() {
    if [ -f "asterisk/keys/asterisk.crt" ]; then
        return 0
    fi

    log_warn "Gerando certificados SSL..."
    mkdir -p asterisk/keys

    # Verifica se openssl existe
    if ! command -v openssl &> /dev/null; then
        log_warn "OpenSSL nao encontrado. Tentando alternativas..."

        # No Windows, tenta usar openssl do Git
        if [ "$OS_TYPE" = "windows" ]; then
            local git_openssl="/c/Program Files/Git/usr/bin/openssl.exe"
            if [ -f "$git_openssl" ]; then
                "$git_openssl" req -x509 -nodes -days 365 -newkey rsa:2048 \
                    -keyout asterisk/keys/asterisk.key \
                    -out asterisk/keys/asterisk.crt \
                    -subj "/CN=localhost/O=PABX/C=BR" \
                    2>/dev/null
                log_success "   Certificados gerados (via Git OpenSSL)"
                return 0
            fi
        fi

        log_error "OpenSSL nao disponivel. Instale manualmente:"
        case "$OS_TYPE" in
            linux)  echo "   sudo apt install openssl" ;;
            macos)  echo "   brew install openssl" ;;
            windows) echo "   Instale Git for Windows com OpenSSL" ;;
        esac
        exit 1
    fi

    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout asterisk/keys/asterisk.key \
        -out asterisk/keys/asterisk.crt \
        -subj "/CN=localhost/O=PABX/C=BR" \
        2>/dev/null

    log_success "   Certificados gerados"
}

#-----------------------------------------------
# Verifica se container está rodando
#-----------------------------------------------
is_container_running() {
    local container_name="$1"
    docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${container_name}$"
}

#-----------------------------------------------
# Aguarda container ficar healthy
#-----------------------------------------------
wait_for_container() {
    local container_name="$1"
    local timeout="${2:-60}"
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        if is_container_running "$container_name"; then
            local health=$(docker inspect --format='{{.State.Health.Status}}' "$container_name" 2>/dev/null || echo "none")
            if [ "$health" = "healthy" ] || [ "$health" = "none" ]; then
                return 0
            fi
        fi
        sleep 2
        ((elapsed+=2))
    done
    return 1
}

#===============================================
# INÍCIO DA EXECUÇÃO
#===============================================

log_info "================================================"
log_info "       PABX Docker - Iniciando Sistema          "
log_info "================================================"
log_info "OS detectado: $OS_TYPE"
log_info "Docker Compose: $DOCKER_COMPOSE"
echo ""

# Verifica dependências
check_dependencies
check_docker_running

# Gera certificados
generate_ssl_certs

# Verifica e obtem imagem base se necessario
check_base_image() {
    local base_image="${BASE_IMAGE:-paulohenriquevn/voice-base:latest}"

    if ! docker image inspect "$base_image" &>/dev/null; then
        log_warn "Imagem base '$base_image' nao encontrada localmente."
        log_warn "Tentando baixar do Docker Hub..."

        # Tenta pull do Docker Hub primeiro
        if docker pull "$base_image" 2>/dev/null; then
            log_success "   Imagem baixada do Docker Hub com sucesso"
        else
            # Se falhar o pull, tenta construir localmente
            log_warn "   Pull falhou. Construindo imagem localmente (pode demorar)..."

            if [ -x "./docker/build-base.sh" ]; then
                ./docker/build-base.sh
                if [ $? -ne 0 ]; then
                    log_error "Falha ao construir imagem base!"
                    exit 1
                fi
                log_success "   Imagem base construida localmente com sucesso"
            else
                log_error "Script docker/build-base.sh nao encontrado ou sem permissao de execucao!"
                log_error "Execute: chmod +x docker/build-base.sh && ./docker/build-base.sh"
                exit 1
            fi
        fi
    else
        log_success "   Imagem base '$base_image': OK"
    fi
}

check_base_image

# Usa builder default para docker-compose (evita isolamento do buildx container)
# O builder voice-builder (docker-container) nao enxerga imagens locais
ensure_default_builder() {
    local current_builder=$(docker buildx inspect --bootstrap 2>/dev/null | grep -m1 "^Name:" | awk '{print $2}')
    if [ "$current_builder" != "default" ]; then
        log_warn "Alternando para builder 'default' (acesso a imagens locais)..."
        docker buildx use default 2>/dev/null || true
    fi
}

ensure_default_builder

# Para containers existentes (se necessário)
log_warn "Parando containers existentes..."
$DOCKER_COMPOSE $PROFILE_ARGS down 2>/dev/null || true

# Build das imagens (primeira vez pode demorar)
log_warn "Construindo imagens Docker..."
log_warn "(primeira execucao pode demorar alguns minutos)"
$DOCKER_COMPOSE $PROFILE_ARGS build

# Inicia todos os serviços
if [ "$DEBUG_MODE" = true ]; then
    log_warn "Iniciando todos os servicos (modo DEBUG com Kibana)..."
else
    log_warn "Iniciando todos os servicos..."
fi
$DOCKER_COMPOSE $PROFILE_ARGS up -d

# Aguarda serviços principais
log_warn "Aguardando servicos inicializarem..."

# Verifica Asterisk
if wait_for_container "asterisk-pabx" 60; then
    log_success "   Asterisk: OK"
else
    log_error "   Asterisk: FALHA"
    $DOCKER_COMPOSE logs asterisk
    exit 1
fi

# Verifica AI Agent
if wait_for_container "ai-conversation-agent" 90; then
    log_success "   AI Agent: OK"
else
    log_error "   AI Agent: FALHA"
    $DOCKER_COMPOSE logs ai-agent
    exit 1
fi

# Verifica Media Server
if is_container_running "sip-media-server"; then
    log_success "   Media Server: OK"
else
    log_error "   Media Server: FALHA"
    $DOCKER_COMPOSE logs media-server
    exit 1
fi

# Verifica Elasticsearch (se habilitado)
if is_container_running "elasticsearch"; then
    log_success "   Elasticsearch: OK"
fi

# Verifica AI Transcribe (se habilitado)
if is_container_running "ai-transcribe"; then
    log_success "   AI Transcribe: OK"
fi

# Verifica Prometheus e Grafana (opcionais)
if is_container_running "prometheus"; then
    log_success "   Prometheus: OK"
fi

if is_container_running "grafana"; then
    log_success "   Grafana: OK"
fi

# Verifica Kibana
if wait_for_container "kibana" 90; then
    log_success "   Kibana: OK"

    # Aguarda kibana-setup importar dashboards
    log_warn "   Aguardando importacao dos dashboards do Kibana..."
    sleep 5

    # Verifica se kibana-setup executou
    setup_status=$(docker inspect --format='{{.State.ExitCode}}' kibana-setup 2>/dev/null || echo "unknown")
    if [ "$setup_status" = "0" ]; then
        log_success "   Kibana Setup: OK (dashboards importados)"
    elif [ "$setup_status" = "unknown" ]; then
        log_warn "   Kibana Setup: ainda executando..."
    else
        log_warn "   Kibana Setup: falhou (exit code: $setup_status)"
        log_warn "   Execute manualmente: docker compose up kibana-setup"
    fi
else
    log_error "   Kibana: FALHA"
    $DOCKER_COMPOSE logs kibana
fi

# Verifica endpoints do Asterisk
echo ""
log_warn "Verificando configuracao do Asterisk..."
docker exec asterisk-pabx asterisk -rx "pjsip show endpoints" 2>/dev/null | head -20 || true

# Resumo final
echo ""
log_success "================================================"
log_success "       SISTEMA INICIADO COM SUCESSO!            "
log_success "================================================"
echo ""
log_info "Servicos:"
echo "   Asterisk:      porta 5160 (SIP), 8189 (WSS)"
echo "   AI Agent:      porta 8765 (WebSocket)"
echo "   Media Server:  portas 40000-40100 (RTP)"
echo "   AI Transcribe: porta 8766 (WebSocket), 9093 (metrics)"
echo "   Elasticsearch: http://localhost:9200"
echo "   Prometheus:    http://localhost:9092"
echo "   Grafana:       http://localhost:3000 (admin/admin)"
echo "   Kibana:        http://localhost:5601 (dashboards pre-carregados)"
echo ""
log_info "Ramais:"
echo "   1001-1003: SIP tradicional"
echo "   1004-1005: WebRTC (SoftPhone)"
echo "   2000:      Agente IA (Media Server)"
echo ""
log_info "Para testar:"
echo "   1. Abra o SoftPhone: cd softphone && npm run dev"
echo "   2. Conecte com ramal 1004"
echo "   3. Ligue para 2000 (Agente IA)"
echo ""
log_info "Comandos uteis:"
echo "   Ver logs:       ./logs.sh"
echo "   Ver status:     ./status.sh"
echo "   CLI Asterisk:   docker exec -it asterisk-pabx asterisk -rvvv"
echo "   Parar tudo:     ./stop.sh"
echo ""
log_info "Transcricao (Elasticsearch):"
echo "   Iniciar com transcricao:  ./start-with-transcribe.sh"
echo "   Ou:  TRANSCRIBE_ENABLED=true ./start.sh"
echo "   Testar:                   ./scripts/test-ai-transcribe.sh"
echo "   Ver transcricoes:         curl 'http://localhost:9200/voice-transcriptions-*/_search?pretty'"
echo ""
log_info "LLM Local (Docker Model Runner):"
echo "   Setup completo:           ./setup-local-llm.sh"
echo "   Modelos disponiveis:      ./setup-local-llm.sh models"
echo "   Testar modelo:            ./setup-local-llm.sh test smollm3"
echo "   Vantagens: Zero latencia de rede, zero custo, 100% privacidade"
echo ""
