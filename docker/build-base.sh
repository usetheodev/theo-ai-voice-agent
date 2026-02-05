#!/bin/bash
# =============================================================================
# Build da Imagem Base voice-base
# =============================================================================
# Uso:
#   ./docker/build-base.sh                    # Build normal (modelo tiny)
#   ./docker/build-base.sh --model small      # Build com modelo small
#   ./docker/build-base.sh --model medium     # Build com modelo medium
#   ./docker/build-base.sh --no-cache         # Build sem cache
#   ./docker/build-base.sh --push             # Build e push para registry
#
# Volumes Docker usados para cache:
#   - voice-pip-cache     -> cache de pacotes pip
#   - voice-apt-cache     -> cache de pacotes apt
#   - voice-model-cache   -> cache de modelos ML (whisper, kokoro)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Configuracoes
IMAGE_NAME="${BASE_IMAGE_NAME:-paulohenriquevn/voice-base}"
IMAGE_TAG="${BASE_IMAGE_TAG:-latest}"
FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
WHISPER_MODEL="${WHISPER_MODEL:-tiny}"
BUILDER_NAME="voice-builder"

# Volumes para cache
VOL_PIP="voice-pip-cache"
VOL_APT="voice-apt-cache"
VOL_MODELS="voice-model-cache"

# Parse args
NO_CACHE=""
PUSH=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-cache)
            NO_CACHE="1"
            shift
            ;;
        --push)
            PUSH="1"
            shift
            ;;
        --model)
            WHISPER_MODEL="$2"
            shift 2
            ;;
        *)
            echo "Argumento desconhecido: $1"
            exit 1
            ;;
    esac
done

echo "=============================================="
echo " Building Base Image: ${FULL_IMAGE}"
echo "=============================================="
echo " Whisper Model: ${WHISPER_MODEL}"
echo " Cache Volumes: ${VOL_PIP}, ${VOL_APT}, ${VOL_MODELS}"
echo " Cache: $([ -n "$NO_CACHE" ] && echo "DISABLED" || echo "ENABLED")"
echo "=============================================="
echo ""

cd "$PROJECT_ROOT"

# Cria volumes Docker se nao existirem
echo "Verificando volumes de cache..."
for vol in "$VOL_PIP" "$VOL_APT" "$VOL_MODELS"; do
    if ! docker volume inspect "$vol" &>/dev/null; then
        echo "  Criando volume: $vol"
        docker volume create "$vol"
    else
        echo "  Volume existe: $vol"
    fi
done
echo ""

# Garante que o builder existe
if ! docker buildx inspect "${BUILDER_NAME}" &>/dev/null; then
    echo "Criando builder '${BUILDER_NAME}'..."
    docker buildx create --name "${BUILDER_NAME}" --driver docker-container --bootstrap
fi
docker buildx use "${BUILDER_NAME}"

# Monta comando de build
BUILD_CMD="docker buildx build"
BUILD_CMD="${BUILD_CMD} -f docker/Dockerfile.base"
BUILD_CMD="${BUILD_CMD} -t ${FULL_IMAGE}"
BUILD_CMD="${BUILD_CMD} --build-arg BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
BUILD_CMD="${BUILD_CMD} --build-arg VERSION=${IMAGE_TAG}"
BUILD_CMD="${BUILD_CMD} --build-arg WHISPER_MODEL=${WHISPER_MODEL}"

if [ -n "$NO_CACHE" ]; then
    BUILD_CMD="${BUILD_CMD} --no-cache"
fi

BUILD_CMD="${BUILD_CMD} --load"
BUILD_CMD="${BUILD_CMD} ."

echo "Executando build..."
echo "${BUILD_CMD}"
echo ""

eval ${BUILD_CMD}

echo ""
echo "=============================================="
echo " Build concluido: ${FULL_IMAGE}"
echo "=============================================="

# Mostra tamanho da imagem
docker images "${IMAGE_NAME}" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

# Mostra tamanho dos volumes
echo ""
echo "Volumes de cache:"
for vol in "$VOL_PIP" "$VOL_APT" "$VOL_MODELS"; do
    size=$(docker system df -v 2>/dev/null | grep "$vol" | awk '{print $4}' || echo "N/A")
    echo "  $vol: $size"
done

# Push se solicitado
if [ -n "$PUSH" ]; then
    echo ""
    echo "Pushing ${FULL_IMAGE}..."
    docker push "${FULL_IMAGE}"
fi

echo ""
echo "Comandos uteis:"
echo "  Ver volumes:    docker volume ls | grep voice"
echo "  Limpar volumes: docker volume rm ${VOL_PIP} ${VOL_APT} ${VOL_MODELS}"
echo "  Limpar builder: docker buildx prune"
