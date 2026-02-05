#!/bin/bash
#===============================================
# Setup Inicial do PABX Docker
# Compatível com Linux e Windows (Git Bash)
#===============================================

set -e

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
# Verifica dependências
#-----------------------------------------------
check_dependencies() {
    local missing=()

    if ! command -v docker &> /dev/null; then
        missing+=("docker")
    fi

    if [ -z "$DOCKER_COMPOSE" ]; then
        missing+=("docker-compose")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Dependencias faltando: ${missing[*]}"
        exit 1
    fi
}

#-----------------------------------------------
# Gera certificados SSL
#-----------------------------------------------
generate_ssl_certs() {
    if [ -f "asterisk/keys/asterisk.crt" ]; then
        log_success "    Certificados ja existem, pulando..."
        return 0
    fi

    # Verifica se openssl existe
    local openssl_cmd="openssl"

    if ! command -v openssl &> /dev/null; then
        if [ "$OS_TYPE" = "windows" ]; then
            local git_openssl="/c/Program Files/Git/usr/bin/openssl.exe"
            if [ -f "$git_openssl" ]; then
                openssl_cmd="$git_openssl"
            else
                log_error "OpenSSL nao encontrado!"
                log_warn "Instale Git for Windows com OpenSSL"
                exit 1
            fi
        else
            log_error "OpenSSL nao encontrado!"
            exit 1
        fi
    fi

    "$openssl_cmd" req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout asterisk/keys/asterisk.key \
        -out asterisk/keys/asterisk.crt \
        -subj "/CN=localhost" \
        2>/dev/null

    log_success "    Certificados gerados com sucesso!"
}

#-----------------------------------------------
# Cria arquivo .env se não existir
#-----------------------------------------------
create_env_files() {
    # AI Agent .env
    if [ ! -f "ai-agent/.env" ]; then
        log_warn "    Criando ai-agent/.env..."
        cat > ai-agent/.env << 'EOF'
# AI Agent Configuration
# ======================

# STT Provider: faster_whisper, whisper, openai
STT_PROVIDER=faster_whisper
WHISPER_MODEL=base

# LLM Provider: anthropic, openai, mock
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-api-key-here

# TTS Provider: kokoro, gtts, openai
TTS_PROVIDER=kokoro

# Logging
LOG_LEVEL=INFO
EOF
        log_success "    ai-agent/.env criado (edite com sua API key)"
    fi

    # Media Server .env
    if [ ! -f "media-server/.env" ]; then
        log_warn "    Criando media-server/.env..."
        cat > media-server/.env << 'EOF'
# Media Server Configuration
# ==========================

# SIP Configuration
SIP_USERNAME=2000
SIP_PASSWORD=7Wslll0Hlc6BCOv4jF51
SIP_DOMAIN=127.0.0.1
SIP_PORT=5160

# WebSocket (AI Agent)
WEBSOCKET_URL=ws://127.0.0.1:8765

# Logging
LOG_LEVEL=INFO
EOF
        log_success "    media-server/.env criado"
    fi
}

#-----------------------------------------------
# Cria arquivo .env do AI Transcribe
#-----------------------------------------------
create_transcribe_env() {
    if [ ! -f "ai-transcribe/.env" ]; then
        log_warn "    Criando ai-transcribe/.env..."
        cat > ai-transcribe/.env << 'EOF'
# AI Transcribe Configuration
# ===========================

# WebSocket Server
WS_HOST=0.0.0.0
WS_PORT=8766

# Elasticsearch
ES_HOSTS=http://elasticsearch:9200
ES_INDEX_PREFIX=voice-transcriptions
ES_BULK_SIZE=50
ES_BULK_INTERVAL_S=5.0

# STT (Speech-to-Text)
STT_MODEL=tiny
STT_LANGUAGE=pt
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8

# Metrics
METRICS_PORT=9093
METRICS_HOST=0.0.0.0

# Logging
LOG_LEVEL=INFO
EOF
        log_success "    ai-transcribe/.env criado"
    else
        log_success "    ai-transcribe/.env ja existe"
    fi
}

#===============================================
# INÍCIO DA EXECUÇÃO
#===============================================

log_info "==================================="
log_info "   PABX Docker - Setup Inicial"
log_info "==================================="
log_info "OS: $OS_TYPE | Compose: $DOCKER_COMPOSE"
echo ""

# Verificar dependências
check_dependencies

# [1/5] Criar diretórios necessários
echo "[1/5] Criando diretorios..."
mkdir -p asterisk/keys
mkdir -p asterisk/sounds
mkdir -p observability/prometheus/rules
mkdir -p observability/grafana/provisioning/datasources
mkdir -p observability/grafana/provisioning/dashboards
mkdir -p observability/grafana/dashboards
mkdir -p ai-transcribe/tests

# [2/5] Gerar certificados SSL
echo "[2/5] Gerando certificados SSL..."
generate_ssl_certs

# [3/5] Criar arquivos .env
echo "[3/5] Configurando variaveis de ambiente..."
create_env_files

# [4/5] Criar .env do AI Transcribe
echo "[4/5] Configurando AI Transcribe..."
create_transcribe_env

# [5/5] Pull/Build das imagens
echo "[5/5] Preparando imagens Docker..."
$DOCKER_COMPOSE pull 2>/dev/null || true
$DOCKER_COMPOSE build

# Resumo
echo ""
log_info "==================================="
log_info "   Setup Completo!"
log_info "==================================="
echo ""
log_success "Proximo passo: Configure sua API key do Anthropic"
echo ""
echo "   1. Edite o arquivo: ai-agent/.env"
echo "   2. Substitua 'your-api-key-here' pela sua API key"
echo ""
log_info "Para iniciar o sistema:"
echo "   ./start.sh"
echo ""
log_info "Para iniciar com transcricao (Elasticsearch):"
echo "   TRANSCRIBE_ENABLED=true ./start.sh"
echo ""
log_info "Ramais disponiveis:"
echo "   1001-1003: SIP (senha: ver pjsip.conf)"
echo "   1004-1005: WebRTC (SoftPhone)"
echo "   2000:      Agente IA"
echo ""
log_info "Codigos uteis:"
echo "   9    : Acessar URA"
echo "   *43  : Teste de eco"
echo "   *60  : Hora certa"
echo "   8000 : Sala de conferencia"
echo ""
log_info "URLs de acesso:"
echo "   Grafana:       http://localhost:3000 (admin/admin)"
echo "   Prometheus:    http://localhost:9092"
echo "   Elasticsearch: http://localhost:9200"
echo "   Kibana:        http://localhost:5601 (--profile debug)"
echo ""
