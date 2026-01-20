#!/bin/bash
# Fix Asterisk Dialplan - Add Extension 1000
# Version: 2.0.1-hotfix3

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}DIALPLAN FIX - Adicionar Ramal 1000${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

echo -e "${YELLOW}⚠️  Problema identificado:${NC}"
echo "  - Você ligou para ramal 1000"
echo "  - Asterisk tocou demo (demo-congrats, demo-instruct)"
echo "  - AI Agent NUNCA foi conectado"
echo ""
echo -e "${YELLOW}Causa:${NC}"
echo "  - Ramal 1000 NÃO estava configurado no dialplan"
echo "  - Apenas ramal 9999 estava configurado"
echo ""
echo -e "${GREEN}✅ Correção aplicada:${NC}"
echo "  - Ramal 1000 agora conecta com AI Agent"
echo "  - Ramal 9999 continua funcionando (alias)"
echo ""

read -p "Reiniciar Asterisk para aplicar? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelado."
    echo ""
    echo -e "${YELLOW}Para aplicar manualmente:${NC}"
    echo "  docker-compose restart asterisk"
    exit 0
fi

echo ""
echo -e "${BLUE}[1/2] Reiniciando Asterisk...${NC}"
docker-compose restart asterisk

echo ""
echo -e "${BLUE}[2/2] Aguardando Asterisk inicializar (~10s)...${NC}"
sleep 10

echo ""
echo -e "${GREEN}✅ Dialplan atualizado!${NC}"
echo ""
echo -e "${YELLOW}📋 Próximos passos:${NC}"
echo "  1. Abrir: http://localhost:8090/"
echo "  2. Registrar (qualquer username/password)"
echo "  3. Discar: 1000  ⬅️ AGORA FUNCIONA!"
echo "  4. Falar: 'Oi, como vai?'"
echo "  5. Aguardar 2s em silêncio"
echo ""
echo -e "${YELLOW}🔍 Validar nos logs:${NC}"
echo "  ./scripts/logs.sh"
echo ""
echo "  Esperado:"
echo "  ✅ === AI Voice Agent Call ==="
echo "  ✅ 📞 New call: 172.20.0.10:..."
echo "  ✅ 🎙️ Speech started"
echo "  ✅ 🤫 Speech ended"
echo "  ✅ 📝 Transcription: ..."
echo ""
echo -e "${GREEN}Ramal 1000 agora está configurado!${NC}"
