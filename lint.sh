#!/bin/bash
#===============================================
# Script de Linting - PABX Docker
# Compatível com Linux e Windows (Git Bash)
#
# Uso:
#   ./lint.sh              # Executa todos os linters
#   ./lint.sh --fix        # Corrige automaticamente
#   ./lint.sh python       # Apenas Python
#   ./lint.sh typescript   # Apenas TypeScript
#   ./lint.sh --check      # Apenas verifica (CI mode)
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
# Cores
#-----------------------------------------------
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    CYAN=''
    BOLD=''
    NC=''
fi

log_info()    { echo -e "${BLUE}$1${NC}"; }
log_success() { echo -e "${GREEN}$1${NC}"; }
log_warn()    { echo -e "${YELLOW}$1${NC}"; }
log_error()   { echo -e "${RED}$1${NC}"; }
log_header()  { echo -e "${BOLD}${CYAN}$1${NC}"; }

#-----------------------------------------------
# Variáveis
#-----------------------------------------------
FIX_MODE=false
CHECK_MODE=false
RUN_PYTHON=true
RUN_TYPESCRIPT=true
RUN_SECURITY=false
ERRORS=0

#-----------------------------------------------
# Parse argumentos
#-----------------------------------------------
show_usage() {
    echo "Uso: $0 [opcoes] [targets]"
    echo ""
    echo "Targets:"
    echo "   python, py      - Lint apenas codigo Python"
    echo "   typescript, ts  - Lint apenas codigo TypeScript"
    echo "   all             - Lint tudo (padrao)"
    echo ""
    echo "Opcoes:"
    echo "   --fix, -f       - Corrige problemas automaticamente"
    echo "   --check, -c     - Apenas verifica (modo CI, sem fix)"
    echo "   --security, -s  - Inclui verificacao de seguranca"
    echo "   --help, -h      - Mostra esta ajuda"
    echo ""
    echo "Exemplos:"
    echo "   $0              - Executa todos os linters"
    echo "   $0 --fix        - Corrige automaticamente"
    echo "   $0 python --fix - Corrige apenas Python"
    echo "   $0 --check      - Modo CI (falha em warnings)"
}

for arg in "$@"; do
    case $arg in
        --fix|-f)
            FIX_MODE=true
            ;;
        --check|-c)
            CHECK_MODE=true
            ;;
        --security|-s)
            RUN_SECURITY=true
            ;;
        --help|-h)
            show_usage
            exit 0
            ;;
        python|py)
            RUN_PYTHON=true
            RUN_TYPESCRIPT=false
            ;;
        typescript|ts)
            RUN_PYTHON=false
            RUN_TYPESCRIPT=true
            ;;
        all)
            RUN_PYTHON=true
            RUN_TYPESCRIPT=true
            ;;
    esac
done

#-----------------------------------------------
# Verifica dependências Python
#-----------------------------------------------
check_python_tools() {
    local missing=()

    if ! command -v ruff &> /dev/null; then
        missing+=("ruff")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_warn "Ferramentas Python faltando: ${missing[*]}"
        log_info "Instalando com: pip install -r requirements-dev.txt"

        if command -v pip &> /dev/null; then
            pip install -r requirements-dev.txt --quiet
        elif command -v pip3 &> /dev/null; then
            pip3 install -r requirements-dev.txt --quiet
        else
            log_error "pip nao encontrado!"
            return 1
        fi
    fi
    return 0
}

#-----------------------------------------------
# Verifica dependências Node
#-----------------------------------------------
check_node_tools() {
    if [ ! -d "softphone/node_modules" ]; then
        log_warn "node_modules nao encontrado no softphone"
        log_info "Instalando dependencias..."

        if command -v npm &> /dev/null; then
            (cd softphone && npm install --silent)
        else
            log_error "npm nao encontrado!"
            return 1
        fi
    fi
    return 0
}

#-----------------------------------------------
# Lint Python com Ruff
#-----------------------------------------------
lint_python() {
    log_header "========================================"
    log_header "  Python Linting (Ruff)"
    log_header "========================================"
    echo ""

    local python_dirs=("ai-agent" "media-server" "shared" "tools")
    local existing_dirs=()

    # Filtra apenas diretórios existentes
    for dir in "${python_dirs[@]}"; do
        if [ -d "$dir" ]; then
            existing_dirs+=("$dir")
        fi
    done

    if [ ${#existing_dirs[@]} -eq 0 ]; then
        log_warn "Nenhum diretorio Python encontrado"
        return 0
    fi

    log_info "Diretorios: ${existing_dirs[*]}"
    echo ""

    # Ruff Check (Linting)
    log_info "[1/3] Verificando codigo..."

    local ruff_args=("check")

    if [ "$FIX_MODE" = true ] && [ "$CHECK_MODE" = false ]; then
        ruff_args+=("--fix")
    fi

    if [ "$CHECK_MODE" = true ]; then
        ruff_args+=("--output-format=grouped")
    fi

    if ruff "${ruff_args[@]}" "${existing_dirs[@]}"; then
        log_success "   Linting OK"
    else
        log_error "   Linting encontrou problemas"
        ((ERRORS++)) || true
    fi

    # Ruff Format (Formatting)
    log_info "[2/3] Verificando formatacao..."

    local format_args=()

    if [ "$FIX_MODE" = true ] && [ "$CHECK_MODE" = false ]; then
        format_args=()  # formato normal (aplica)
    else
        format_args=("--check" "--diff")
    fi

    if ruff format "${format_args[@]}" "${existing_dirs[@]}"; then
        log_success "   Formatacao OK"
    else
        if [ "$FIX_MODE" = true ]; then
            log_warn "   Formatacao aplicada"
        else
            log_error "   Formatacao incorreta (use --fix)"
            ((ERRORS++)) || true
        fi
    fi

    # MyPy (Type Checking) - Opcional
    if command -v mypy &> /dev/null; then
        log_info "[3/3] Verificando tipos..."

        if mypy "${existing_dirs[@]}" --ignore-missing-imports --no-error-summary 2>/dev/null; then
            log_success "   Type checking OK"
        else
            log_warn "   Type checking encontrou avisos (nao bloqueante)"
        fi
    else
        log_info "[3/3] MyPy nao instalado (pulando type check)"
    fi

    echo ""
}

#-----------------------------------------------
# Lint TypeScript com ESLint + Prettier
#-----------------------------------------------
lint_typescript() {
    log_header "========================================"
    log_header "  TypeScript/React Linting (ESLint)"
    log_header "========================================"
    echo ""

    if [ ! -d "softphone/src" ]; then
        log_warn "Diretorio softphone/src nao encontrado"
        return 0
    fi

    cd softphone

    # ESLint
    log_info "[1/3] Verificando codigo (ESLint)..."

    local eslint_args=("src")

    if [ "$FIX_MODE" = true ] && [ "$CHECK_MODE" = false ]; then
        eslint_args+=("--fix")
    fi

    if npx eslint "${eslint_args[@]}" 2>/dev/null; then
        log_success "   ESLint OK"
    else
        log_error "   ESLint encontrou problemas"
        ((ERRORS++)) || true
    fi

    # Prettier
    log_info "[2/3] Verificando formatacao (Prettier)..."

    if [ "$FIX_MODE" = true ] && [ "$CHECK_MODE" = false ]; then
        if npx prettier --write "src/**/*.{ts,tsx,css}" 2>/dev/null; then
            log_success "   Prettier aplicado"
        else
            log_warn "   Prettier encontrou problemas"
        fi
    else
        if npx prettier --check "src/**/*.{ts,tsx,css}" 2>/dev/null; then
            log_success "   Prettier OK"
        else
            log_error "   Formatacao incorreta (use --fix)"
            ((ERRORS++)) || true
        fi
    fi

    # TypeScript Compiler
    log_info "[3/3] Verificando tipos (tsc)..."

    if npx tsc --noEmit 2>/dev/null; then
        log_success "   TypeScript OK"
    else
        log_error "   TypeScript encontrou erros"
        ((ERRORS++)) || true
    fi

    cd "$SCRIPT_DIR"
    echo ""
}

#-----------------------------------------------
# Security Checks
#-----------------------------------------------
lint_security() {
    log_header "========================================"
    log_header "  Security Checks"
    log_header "========================================"
    echo ""

    # Bandit (Python)
    if command -v bandit &> /dev/null; then
        log_info "[1/2] Verificando seguranca Python (Bandit)..."

        local python_dirs=("ai-agent" "media-server")
        local existing_dirs=()

        for dir in "${python_dirs[@]}"; do
            if [ -d "$dir" ]; then
                existing_dirs+=("$dir")
            fi
        done

        if [ ${#existing_dirs[@]} -gt 0 ]; then
            if bandit -r "${existing_dirs[@]}" -ll -q 2>/dev/null; then
                log_success "   Bandit OK"
            else
                log_warn "   Bandit encontrou avisos"
            fi
        fi
    else
        log_info "[1/2] Bandit nao instalado (pulando)"
    fi

    # npm audit
    if [ -d "softphone/node_modules" ]; then
        log_info "[2/2] Verificando vulnerabilidades NPM..."

        cd softphone
        if npm audit --audit-level=high 2>/dev/null; then
            log_success "   NPM Audit OK"
        else
            log_warn "   NPM Audit encontrou vulnerabilidades"
        fi
        cd "$SCRIPT_DIR"
    else
        log_info "[2/2] SoftPhone nao instalado (pulando npm audit)"
    fi

    echo ""
}

#===============================================
# INÍCIO DA EXECUÇÃO
#===============================================

log_header "========================================"
log_header "  PABX Docker - Linting"
log_header "========================================"
log_info "OS: $OS_TYPE"
log_info "Fix mode: $FIX_MODE"
log_info "Check mode: $CHECK_MODE"
echo ""

# Verifica e instala dependências
if [ "$RUN_PYTHON" = true ]; then
    check_python_tools || exit 1
fi

if [ "$RUN_TYPESCRIPT" = true ]; then
    check_node_tools || exit 1
fi

# Executa linters
if [ "$RUN_PYTHON" = true ]; then
    lint_python
fi

if [ "$RUN_TYPESCRIPT" = true ]; then
    lint_typescript
fi

if [ "$RUN_SECURITY" = true ]; then
    lint_security
fi

# Resumo
log_header "========================================"
log_header "  Resumo"
log_header "========================================"

if [ $ERRORS -gt 0 ]; then
    log_error "Encontrados $ERRORS erro(s)"
    echo ""

    if [ "$FIX_MODE" = false ]; then
        log_info "Dica: Execute com --fix para corrigir automaticamente"
    fi

    exit 1
else
    log_success "Todos os checks passaram!"
    exit 0
fi
