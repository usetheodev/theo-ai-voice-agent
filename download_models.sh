#!/bin/bash
# =============================================================================
# Download de Modelos ML - Voice Agent
# =============================================================================
# Baixa todos os modelos necessarios para o pipeline de voz:
#   - Whisper (STT)     -> faster-whisper via HuggingFace
#   - Kokoro (TTS)      -> kokoro via HuggingFace
#   - E5 (Embeddings)   -> sentence-transformers via HuggingFace
#
# Uso:
#   ./download_models.sh                     # Todos os modelos (whisper tiny)
#   ./download_models.sh --whisper-model small
#   ./download_models.sh --only stt          # Apenas Whisper
#   ./download_models.sh --only tts          # Apenas Kokoro
#   ./download_models.sh --only embeddings   # Apenas E5
#   ./download_models.sh --cache-dir /path   # Cache customizado
#   ./download_models.sh --dry-run           # Mostra o que faria
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Configuracao
# -----------------------------------------------------------------------------

WHISPER_MODEL="${WHISPER_MODEL:-tiny}"
CACHE_DIR="${HF_HOME:-${HOME}/.cache/huggingface}"
ONLY=""
DRY_RUN=""

# Cores (desabilita se nao for terminal)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    GREEN='' YELLOW='' RED='' BLUE='' NC=''
fi

# -----------------------------------------------------------------------------
# Parse de argumentos
# -----------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case $1 in
        --whisper-model)
            WHISPER_MODEL="$2"
            shift 2
            ;;
        --only)
            ONLY="$2"
            shift 2
            ;;
        --cache-dir)
            CACHE_DIR="$2"
            export HF_HOME="$CACHE_DIR"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="1"
            shift
            ;;
        -h|--help)
            sed -n '2,18p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo -e "${RED}Argumento desconhecido: $1${NC}"
            echo "Use --help para ver opcoes"
            exit 1
            ;;
    esac
done

# Valida --only
if [[ -n "$ONLY" && ! "$ONLY" =~ ^(stt|tts|embeddings)$ ]]; then
    echo -e "${RED}--only invalido: '$ONLY'. Use: stt, tts, embeddings${NC}"
    exit 1
fi

# Valida modelo whisper
VALID_MODELS="tiny tiny.en base base.en small small.en medium medium.en large-v1 large-v2 large-v3"
if [[ -n "$WHISPER_MODEL" && ! " $VALID_MODELS " =~ " $WHISPER_MODEL " ]]; then
    echo -e "${RED}Modelo whisper invalido: '$WHISPER_MODEL'${NC}"
    echo "Modelos validos: $VALID_MODELS"
    exit 1
fi

# -----------------------------------------------------------------------------
# Funcoes
# -----------------------------------------------------------------------------

log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_python() {
    if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
        log_error "Python 3 nao encontrado"
        exit 1
    fi
    PYTHON=$(command -v python3 || command -v python)
}

should_download() {
    [[ -z "$ONLY" || "$ONLY" == "$1" ]]
}

# -----------------------------------------------------------------------------
# Header
# -----------------------------------------------------------------------------

echo ""
echo "=============================================="
echo " Download de Modelos ML - Voice Agent"
echo "=============================================="
echo " Whisper Model:  ${WHISPER_MODEL}"
echo " Cache Dir:      ${CACHE_DIR}"
echo " Filtro:         ${ONLY:-todos}"
[[ -n "$DRY_RUN" ]] && echo " Modo:           DRY RUN (nada sera baixado)"
echo "=============================================="
echo ""

check_python
log_info "Python: $($PYTHON --version 2>&1)"

if [[ -n "$DRY_RUN" ]]; then
    should_download stt && log_info "[DRY] Baixaria: faster-whisper model '${WHISPER_MODEL}'"
    should_download tts && log_info "[DRY] Baixaria: kokoro TTS model"
    should_download embeddings && log_info "[DRY] Baixaria: intfloat/multilingual-e5-small"
    echo ""
    log_ok "Dry run concluido. Nenhum modelo baixado."
    exit 0
fi

FAILED=0

# -----------------------------------------------------------------------------
# 1. Whisper (STT)
# -----------------------------------------------------------------------------

if should_download stt; then
    echo ""
    log_info "Baixando modelo Whisper: ${WHISPER_MODEL} ..."

    if $PYTHON -c "
from faster_whisper import WhisperModel
model = WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8')
print('Modelo carregado com sucesso')
" 2>&1; then
        log_ok "Whisper '${WHISPER_MODEL}' baixado"
    else
        log_error "Falha ao baixar Whisper '${WHISPER_MODEL}'"
        FAILED=$((FAILED + 1))
    fi
fi

# -----------------------------------------------------------------------------
# 2. Kokoro (TTS)
# -----------------------------------------------------------------------------

if should_download tts; then
    echo ""
    log_info "Baixando modelo Kokoro TTS ..."

    if $PYTHON -c "
import kokoro
pipeline = kokoro.KPipeline(lang_code='a')
print('Modelo carregado com sucesso')
" 2>&1; then
        log_ok "Kokoro TTS baixado"
    else
        log_error "Falha ao baixar Kokoro TTS"
        FAILED=$((FAILED + 1))
    fi
fi

# -----------------------------------------------------------------------------
# 3. E5 Embeddings
# -----------------------------------------------------------------------------

if should_download embeddings; then
    echo ""
    log_info "Baixando modelo E5 multilingual (embeddings) ..."

    if $PYTHON -c "
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('intfloat/multilingual-e5-small')
print('Modelo carregado com sucesso')
" 2>&1; then
        log_ok "E5 multilingual-e5-small baixado"
    else
        log_error "Falha ao baixar E5 embeddings"
        FAILED=$((FAILED + 1))
    fi
fi

# -----------------------------------------------------------------------------
# Resultado
# -----------------------------------------------------------------------------

echo ""
echo "=============================================="

if [[ $FAILED -eq 0 ]]; then
    log_ok "Todos os modelos baixados com sucesso"
else
    log_error "${FAILED} modelo(s) falharam"
fi

echo ""
echo "Cache em: ${CACHE_DIR}"

# Mostra tamanho do cache se du disponivel
if command -v du &>/dev/null; then
    CACHE_SIZE=$(du -sh "${CACHE_DIR}" 2>/dev/null | cut -f1 || echo "N/A")
    echo "Tamanho total: ${CACHE_SIZE}"
fi

echo "=============================================="
echo ""

exit $FAILED
