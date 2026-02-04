#!/bin/bash
#===============================================
# Script de Inicialização do PABX Docker
# Inicia Asterisk + Agente Python
#===============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}       PABX Docker - Iniciando Sistema          ${NC}"
echo -e "${BLUE}================================================${NC}"

# Verifica se Docker está rodando
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker não está rodando!${NC}"
    echo "   Execute: sudo systemctl start docker"
    exit 1
fi

# Gera certificados SSL se não existirem
if [ ! -f "asterisk/keys/asterisk.crt" ]; then
    echo -e "${YELLOW}🔐 Gerando certificados SSL...${NC}"
    mkdir -p asterisk/keys
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout asterisk/keys/asterisk.key \
        -out asterisk/keys/asterisk.crt \
        -subj "/CN=localhost/O=PABX/C=BR" \
        2>/dev/null
    echo -e "${GREEN}   ✅ Certificados gerados${NC}"
fi

# Para containers existentes
echo -e "${YELLOW}🛑 Parando containers existentes...${NC}"
docker-compose down 2>/dev/null || true
cd agent && docker-compose down 2>/dev/null || true
cd "$SCRIPT_DIR"

# Inicia Asterisk
echo -e "${YELLOW}🚀 Iniciando Asterisk...${NC}"
docker-compose up -d

# Aguarda Asterisk estar pronto
echo -e "${YELLOW}⏳ Aguardando Asterisk inicializar...${NC}"
sleep 5

# Verifica se Asterisk está rodando
if docker ps | grep -q asterisk-pabx; then
    echo -e "${GREEN}   ✅ Asterisk rodando${NC}"
else
    echo -e "${RED}   ❌ Falha ao iniciar Asterisk${NC}"
    docker-compose logs
    exit 1
fi

# Verifica registro de endpoints
echo -e "${YELLOW}📋 Verificando configuração do Asterisk...${NC}"
docker exec asterisk-pabx asterisk -rx "pjsip show endpoints" 2>/dev/null | head -20 || true

# Inicia Agente Python
echo -e "${YELLOW}🤖 Iniciando Agente Python...${NC}"
cd agent

# Build do agente (primeira vez pode demorar)
echo -e "${YELLOW}   📦 Construindo imagem Docker do Agente...${NC}"
echo -e "${YELLOW}   (primeira execução pode demorar ~5 minutos)${NC}"
docker-compose build

# Inicia o agente
docker-compose up -d

cd "$SCRIPT_DIR"

# Aguarda agente inicializar
echo -e "${YELLOW}⏳ Aguardando Agente registrar...${NC}"
sleep 10

# Verifica se agente está rodando
if docker ps | grep -q sip-agent; then
    echo -e "${GREEN}   ✅ Agente rodando${NC}"
else
    echo -e "${RED}   ❌ Falha ao iniciar Agente${NC}"
    cd agent && docker-compose logs
    exit 1
fi

# Resumo final
echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}       ✅ SISTEMA INICIADO COM SUCESSO!         ${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${BLUE}📞 Portas:${NC}"
echo "   SIP:  5160/UDP"
echo "   HTTP: 8188/TCP"
echo "   WSS:  8189/TCP"
echo "   RTP:  20000-20100/UDP"
echo ""
echo -e "${BLUE}📱 Ramais:${NC}"
echo "   1001-1003: SIP tradicional"
echo "   1004-1005: WebRTC (SoftPhone)"
echo "   2000:      Agente Python (atende automaticamente)"
echo ""
echo -e "${BLUE}🧪 Para testar:${NC}"
echo "   1. Abra o SoftPhone: cd softphone && npm run dev"
echo "   2. Conecte com ramal 1004, senha: ramal1004"
echo "   3. Servidor: ws://localhost:8188/ws"
echo "   4. Ligue para 2000"
echo ""
echo -e "${BLUE}📋 Comandos úteis:${NC}"
echo "   Ver logs Asterisk: docker logs -f asterisk-pabx"
echo "   Ver logs Agente:   docker logs -f sip-agent"
echo "   CLI Asterisk:      docker exec -it asterisk-pabx asterisk -rvvv"
echo "   Parar tudo:        ./stop.sh"
echo ""
