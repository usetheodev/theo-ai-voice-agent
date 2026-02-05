#!/bin/bash
#===============================================
# Setup do LLM Local (Docker Model Runner)
# Configura modelos de linguagem locais para
# reduzir latencia e custo
#===============================================

set -e

#-----------------------------------------------
# Cores para output
#-----------------------------------------------
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    CYAN=''
    NC=''
fi

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()    { echo -e "${CYAN}[STEP]${NC} $1"; }

#-----------------------------------------------
# Modelos disponiveis
#-----------------------------------------------
declare -A MODELS
MODELS=(
    ["smollm3"]="ai/smollm3|3.1B params|Chat eficiente, RECOMENDADO"
    ["functiongemma"]="ai/functiongemma|270M params|Function-calling, mais rapido"
    ["phi4"]="ai/phi4|~3B params|Raciocinio compacto"
    ["qwen3"]="ai/qwen3|4-72B params|Alta qualidade, mais lento"
    ["mistral"]="ai/mistral|7B params|Modelo eficiente"
    ["gemma3"]="ai/gemma3|varios|Google Gemma 3"
)

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
# Verifica requisitos
#-----------------------------------------------
check_requirements() {
    log_step "Verificando requisitos..."

    # Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker nao encontrado!"
        exit 1
    fi
    log_success "Docker instalado"

    # Docker rodando
    if ! docker info > /dev/null 2>&1; then
        log_error "Docker nao esta rodando!"
        exit 1
    fi
    log_success "Docker rodando"

    # Versao do Docker Desktop (precisa 4.40+)
    local docker_version=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
    log_info "Versao Docker: $docker_version"
}

#-----------------------------------------------
# Verifica se Model Runner esta disponivel
#-----------------------------------------------
check_model_runner() {
    log_step "Verificando Docker Model Runner..."

    # Tenta o comando docker model
    if docker model ls &>/dev/null 2>&1; then
        log_success "Docker Model Runner disponivel"
        return 0
    fi

    # Nao disponivel
    log_warn "Docker Model Runner NAO disponivel"
    echo ""
    log_info "Para habilitar o Docker Model Runner:"
    echo ""

    case "$OS_TYPE" in
        linux)
            echo "   1. Instale o plugin:"
            echo "      sudo apt-get update && sudo apt-get install docker-model-plugin"
            echo ""
            echo "   2. Habilite com TCP:"
            echo "      docker model enable --tcp 12434"
            ;;
        macos|windows)
            echo "   1. Atualize Docker Desktop para versao 4.40+"
            echo ""
            echo "   2. Habilite em Settings > Features in development > Docker Model Runner"
            echo "      Ou execute:"
            echo "      docker desktop enable model-runner --tcp 12434"
            ;;
        *)
            echo "   Consulte: https://docs.docker.com/ai/model-runner/"
            ;;
    esac

    echo ""
    return 1
}

#-----------------------------------------------
# Habilita Model Runner
#-----------------------------------------------
enable_model_runner() {
    log_step "Habilitando Docker Model Runner..."

    case "$OS_TYPE" in
        linux)
            log_info "Habilitando Model Runner..."
            docker model enable --tcp 12434 2>/dev/null || true
            ;;
        macos|windows)
            log_info "Tentando habilitar via docker desktop..."
            docker desktop enable model-runner --tcp 12434 2>/dev/null || {
                log_warn "Nao foi possivel habilitar automaticamente."
                log_info "Habilite manualmente em Docker Desktop > Settings > Features"
                return 1
            }
            ;;
    esac

    # Aguarda inicializar
    log_info "Aguardando Model Runner inicializar..."
    sleep 5

    # Verifica novamente
    if docker model ls &>/dev/null 2>&1; then
        log_success "Docker Model Runner habilitado!"
        return 0
    else
        log_error "Falha ao habilitar Model Runner"
        return 1
    fi
}

#-----------------------------------------------
# Lista modelos disponiveis
#-----------------------------------------------
list_available_models() {
    echo ""
    log_info "Modelos disponiveis para download:"
    echo ""
    printf "   %-15s %-20s %s\n" "NOME" "MODELO" "DESCRICAO"
    printf "   %-15s %-20s %s\n" "----" "------" "---------"

    for key in "${!MODELS[@]}"; do
        IFS='|' read -r model_name params desc <<< "${MODELS[$key]}"
        printf "   %-15s %-20s %s (%s)\n" "$key" "$model_name" "$desc" "$params"
    done
    echo ""
}

#-----------------------------------------------
# Baixa modelo
#-----------------------------------------------
download_model() {
    local model_key="${1:-smollm3}"

    if [[ -z "${MODELS[$model_key]}" ]]; then
        log_error "Modelo '$model_key' nao reconhecido!"
        list_available_models
        exit 1
    fi

    IFS='|' read -r model_name params desc <<< "${MODELS[$model_key]}"

    log_step "Baixando modelo: $model_name ($params)"
    log_info "$desc"
    echo ""

    docker model pull "$model_name"

    if [ $? -eq 0 ]; then
        log_success "Modelo $model_name baixado com sucesso!"
    else
        log_error "Falha ao baixar modelo!"
        exit 1
    fi
}

#-----------------------------------------------
# Lista modelos instalados
#-----------------------------------------------
list_installed_models() {
    log_step "Modelos instalados:"
    echo ""
    docker model ls 2>/dev/null || {
        log_warn "Nenhum modelo instalado ou Model Runner nao disponivel"
        return 1
    }
}

#-----------------------------------------------
# Testa modelo
#-----------------------------------------------
test_model() {
    local model="${1:-ai/smollm3}"

    log_step "Testando modelo: $model"
    echo ""

    local response=$(curl -s http://localhost:12434/engines/llama.cpp/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"$model\",
            \"messages\": [{\"role\": \"user\", \"content\": \"Ola! Responda em portugues com uma frase curta.\"}],
            \"max_tokens\": 50
        }" 2>/dev/null)

    if [ $? -eq 0 ] && [ -n "$response" ]; then
        local content=$(echo "$response" | grep -o '"content":"[^"]*"' | head -1 | sed 's/"content":"//;s/"$//')

        if [ -n "$content" ]; then
            log_success "Modelo funcionando!"
            echo ""
            echo "   Resposta: $content"
            echo ""
            return 0
        fi
    fi

    log_error "Falha ao testar modelo!"
    log_info "Resposta raw: $response"
    return 1
}

#-----------------------------------------------
# Configura .env
#-----------------------------------------------
configure_env() {
    local model="${1:-ai/smollm3}"
    local env_file="./ai-agent/.env"

    log_step "Configurando .env para usar LLM local..."

    if [ ! -f "$env_file" ]; then
        if [ -f "./ai-agent/.env.example" ]; then
            cp ./ai-agent/.env.example "$env_file"
            log_info "Criado .env a partir de .env.example"
        else
            log_error "Arquivo .env.example nao encontrado!"
            return 1
        fi
    fi

    # Faz backup
    cp "$env_file" "${env_file}.backup"

    # Atualiza configuracoes
    if grep -q "^LLM_PROVIDER=" "$env_file"; then
        sed -i "s/^LLM_PROVIDER=.*/LLM_PROVIDER=local/" "$env_file"
    else
        echo "LLM_PROVIDER=local" >> "$env_file"
    fi

    if grep -q "^LOCAL_LLM_MODEL=" "$env_file"; then
        sed -i "s|^LOCAL_LLM_MODEL=.*|LOCAL_LLM_MODEL=$model|" "$env_file"
    else
        echo "LOCAL_LLM_MODEL=$model" >> "$env_file"
    fi

    if grep -q "^LOCAL_LLM_BASE_URL=" "$env_file"; then
        sed -i "s|^LOCAL_LLM_BASE_URL=.*|LOCAL_LLM_BASE_URL=http://localhost:12434/engines/llama.cpp/v1|" "$env_file"
    else
        echo "LOCAL_LLM_BASE_URL=http://localhost:12434/engines/llama.cpp/v1" >> "$env_file"
    fi

    log_success "Configuracao atualizada!"
    echo ""
    echo "   LLM_PROVIDER=local"
    echo "   LOCAL_LLM_MODEL=$model"
    echo "   LOCAL_LLM_BASE_URL=http://localhost:12434/engines/llama.cpp/v1"
    echo ""
}

#-----------------------------------------------
# Mostra uso
#-----------------------------------------------
show_usage() {
    echo ""
    echo "Uso: $0 [comando] [opcoes]"
    echo ""
    echo "Comandos:"
    echo "   setup [modelo]    Setup completo (default: smollm3)"
    echo "   check             Verifica se Model Runner esta disponivel"
    echo "   enable            Habilita Model Runner"
    echo "   download [modelo] Baixa um modelo"
    echo "   list              Lista modelos instalados"
    echo "   models            Lista modelos disponiveis"
    echo "   test [modelo]     Testa um modelo"
    echo "   configure [modelo] Configura .env para usar modelo local"
    echo ""
    echo "Modelos disponiveis:"
    for key in "${!MODELS[@]}"; do
        IFS='|' read -r model_name params desc <<< "${MODELS[$key]}"
        echo "   $key - $desc ($params)"
    done
    echo ""
    echo "Exemplos:"
    echo "   $0 setup              # Setup completo com smollm3"
    echo "   $0 setup phi4         # Setup com phi4"
    echo "   $0 download qwen3     # Baixa apenas o qwen3"
    echo "   $0 test ai/smollm3    # Testa modelo especifico"
    echo ""
}

#===============================================
# MAIN
#===============================================

echo ""
log_info "================================================"
log_info "     Setup LLM Local (Docker Model Runner)      "
log_info "================================================"
echo ""

# Parse comando
COMMAND="${1:-setup}"
MODEL="${2:-smollm3}"

case "$COMMAND" in
    setup)
        check_requirements

        if ! check_model_runner; then
            echo ""
            read -p "Deseja tentar habilitar o Model Runner? [y/N] " -n 1 -r
            echo ""
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                enable_model_runner || exit 1
            else
                exit 1
            fi
        fi

        download_model "$MODEL"
        test_model "${MODELS[$MODEL]%%|*}"
        configure_env "${MODELS[$MODEL]%%|*}"

        echo ""
        log_success "================================================"
        log_success "           SETUP CONCLUIDO COM SUCESSO!         "
        log_success "================================================"
        echo ""
        log_info "Proximo passo: Reinicie o AI Agent"
        echo "   ./start.sh"
        echo ""
        ;;

    check)
        check_requirements
        check_model_runner
        ;;

    enable)
        enable_model_runner
        ;;

    download)
        check_requirements
        check_model_runner || exit 1
        download_model "$MODEL"
        ;;

    list)
        check_model_runner || exit 1
        list_installed_models
        ;;

    models)
        list_available_models
        ;;

    test)
        check_model_runner || exit 1
        # Se passou nome completo (ai/xxx), usa direto
        if [[ "$MODEL" == ai/* ]]; then
            test_model "$MODEL"
        else
            # Senao, busca no array
            if [[ -n "${MODELS[$MODEL]}" ]]; then
                test_model "${MODELS[$MODEL]%%|*}"
            else
                test_model "ai/$MODEL"
            fi
        fi
        ;;

    configure)
        if [[ -n "${MODELS[$MODEL]}" ]]; then
            configure_env "${MODELS[$MODEL]%%|*}"
        else
            configure_env "$MODEL"
        fi
        ;;

    help|--help|-h)
        show_usage
        ;;

    *)
        log_error "Comando desconhecido: $COMMAND"
        show_usage
        exit 1
        ;;
esac
