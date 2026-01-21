#!/bin/bash
#
# Script de Teste - Autenticação Digest
# Testa autenticação do AI Voice Agent via Asterisk
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🔐 Teste de Autenticação Digest${NC}"
echo -e "${BLUE}   AI Voice Agent + Asterisk${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Verificar se Asterisk está rodando
check_asterisk() {
    echo -e "${YELLOW}Verificando Asterisk...${NC}"

    if command -v asterisk &> /dev/null; then
        # Asterisk local
        if asterisk -rx "core show version" &> /dev/null; then
            echo -e "${GREEN}✅ Asterisk rodando (local)${NC}"
            ASTERISK_CMD="asterisk -rx"
            return 0
        fi
    fi

    # Tentar Docker
    if docker ps | grep -q asterisk; then
        echo -e "${GREEN}✅ Asterisk rodando (Docker)${NC}"
        ASTERISK_CMD="docker exec asterisk asterisk -rx"
        return 0
    fi

    echo -e "${RED}❌ Asterisk não encontrado${NC}"
    echo "   Inicie o Asterisk antes de executar os testes"
    exit 1
}

# Verificar se AI Voice Agent está rodando
check_ai_agent() {
    echo -e "${YELLOW}Verificando AI Voice Agent...${NC}"

    if netstat -tulpn 2>/dev/null | grep -q ":5061"; then
        echo -e "${GREEN}✅ AI Voice Agent rodando (porta 5061)${NC}"
        return 0
    fi

    if ss -tulpn 2>/dev/null | grep -q ":5061"; then
        echo -e "${GREEN}✅ AI Voice Agent rodando (porta 5061)${NC}"
        return 0
    fi

    echo -e "${RED}❌ AI Voice Agent não está rodando na porta 5061${NC}"
    echo "   Inicie com: python3 src/main.py --config config/default.yaml"
    exit 1
}

# Verificar configuração do trunk
check_trunk_config() {
    echo -e "${YELLOW}Verificando configuração do trunk...${NC}"

    output=$($ASTERISK_CMD "pjsip show endpoint ai-agent-trunk" 2>&1)

    if echo "$output" | grep -q "ai-agent-trunk"; then
        echo -e "${GREEN}✅ Trunk ai-agent-trunk configurado${NC}"

        if echo "$output" | grep -q "carrier_demo"; then
            echo -e "${GREEN}✅ Autenticação configurada (carrier_demo)${NC}"
        else
            echo -e "${YELLOW}⚠️  Autenticação não encontrada${NC}"
        fi
        return 0
    else
        echo -e "${RED}❌ Trunk ai-agent-trunk não encontrado${NC}"
        echo "   Execute: $ASTERISK_CMD 'pjsip reload'"
        exit 1
    fi
}

# Teste 1: Autenticação bem-sucedida
test_valid_auth() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Teste 1: Autenticação Válida${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo "Credenciais: carrier_demo / demo123"
    echo "Algoritmo esperado: SHA-256"
    echo ""
    echo -e "${YELLOW}Iniciando chamada de teste...${NC}"

    # Fazer chamada
    $ASTERISK_CMD "channel originate PJSIP/agent@ai-agent-trunk application Milliwatt" &

    sleep 3

    # Verificar se canal foi criado
    channels=$($ASTERISK_CMD "pjsip show channels")

    if echo "$channels" | grep -q "ai-agent-trunk"; then
        echo -e "${GREEN}✅ PASSOU: Chamada conectada com autenticação${NC}"
        echo ""
        echo "Canais ativos:"
        echo "$channels"

        # Desligar chamada
        sleep 2
        $ASTERISK_CMD "channel request hangup all" &> /dev/null || true

        return 0
    else
        echo -e "${RED}❌ FALHOU: Chamada não conectou${NC}"
        echo "Verifique os logs do AI Voice Agent"
        return 1
    fi
}

# Mostrar logs do AI Voice Agent (últimas linhas)
show_agent_logs() {
    echo ""
    echo -e "${BLUE}Últimos logs do AI Voice Agent:${NC}"
    echo -e "${BLUE}(procure por 'Authentication')${NC}"
    echo ""

    # Tentar encontrar logs
    if [ -f "logs/aiagent.log" ]; then
        tail -20 logs/aiagent.log | grep -i "auth\|401\|403\|invite" || true
    else
        echo -e "${YELLOW}⚠️  Arquivo de log não encontrado${NC}"
        echo "   Os logs devem aparecer no console onde o AI Agent está rodando"
    fi
}

# Instruções para testes manuais
show_manual_tests() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Testes Manuais Adicionais${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo "Execute os seguintes comandos no CLI do Asterisk:"
    echo ""
    echo "1. Conectar ao CLI:"
    echo -e "${GREEN}   $ASTERISK_CMD${NC}"
    echo ""
    echo "2. Teste de chamada básica (extensão 7000):"
    echo -e "${GREEN}   channel originate Local/7000@default application Milliwatt${NC}"
    echo ""
    echo "3. Verificar canais ativos:"
    echo -e "${GREEN}   pjsip show channels${NC}"
    echo ""
    echo "4. Verificar endpoint:"
    echo -e "${GREEN}   pjsip show endpoint ai-agent-trunk${NC}"
    echo ""
    echo "5. Desligar todas as chamadas:"
    echo -e "${GREEN}   channel request hangup all${NC}"
    echo ""
}

# Menu principal
main() {
    check_asterisk
    check_ai_agent
    check_trunk_config

    echo ""
    echo -e "${YELLOW}Deseja executar teste automático de chamada?${NC}"
    echo -e "${YELLOW}(Isso fará uma chamada de teste via Asterisk)${NC}"
    read -p "Continuar? (s/n): " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Ss]$ ]]; then
        test_valid_auth
        show_agent_logs
    fi

    show_manual_tests

    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${GREEN}✅ Script concluído!${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo "Para mais detalhes, consulte:"
    echo "  docs/TESTE_AUTENTICACAO_ASTERISK.md"
    echo ""
}

# Executar
main
