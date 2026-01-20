#!/bin/bash
# Apply VAD Hotfix for Noisy Environments
# Version: 2.0.1

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}VAD HOTFIX - Ambientes Ruidosos v2.0.1${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

echo -e "${YELLOW}⚠️  Este script vai:${NC}"
echo "  1. Parar o sistema atual"
echo "  2. Rebuild do container ai-agent"
echo "  3. Reiniciar com novas configurações VAD"
echo ""
echo -e "${YELLOW}Configurações aplicadas:${NC}"
echo "  - webrtc_aggressiveness: 1 → 2 (mais agressivo)"
echo "  - energy_threshold_end: 700 → 400 (detecta silêncio com ruído)"
echo "  - energy_threshold_start: 1200 → 1500 (evita falso positivo)"
echo "  - silence_duration_ms: 700 → 500 (mais responsivo)"
echo "  - min_speech_duration_ms: 500 → 300 (aceita frases curtas)"
echo ""

read -p "Continuar? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelado."
    exit 1
fi

echo ""
echo -e "${BLUE}[1/3] Parando sistema...${NC}"
./scripts/stop.sh

echo ""
echo -e "${BLUE}[2/3] Rebuilding ai-agent container...${NC}"
docker-compose build ai-agent

echo ""
echo -e "${BLUE}[3/3] Iniciando sistema com nova config...${NC}"
./scripts/start.sh

echo ""
echo -e "${GREEN}✅ Hotfix aplicado com sucesso!${NC}"
echo ""
echo -e "${YELLOW}📋 Próximos passos:${NC}"
echo "  1. Abrir: http://localhost:8090/"
echo "  2. Discar: 1000"
echo "  3. Falar: 'Oi, tudo bem?'"
echo "  4. Aguardar 2s em silêncio"
echo "  5. Ver logs: ./scripts/logs.sh"
echo ""
echo -e "${YELLOW}🔍 Validar nos logs:${NC}"
echo "  ✅ '🎙️  Speech started'"
echo "  ✅ '🤫 Speech ended' (deve aparecer em ~2-3s)"
echo "  ✅ '📝 Transcription:' em português"
echo "  ✅ '🤖 LLM Response:' em PT-BR"
echo ""
echo -e "${GREEN}Documentação: HOTFIX_VAD_NOISY_ENV.md${NC}"
