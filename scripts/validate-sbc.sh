#!/bin/bash
#===============================================
# Script de Validação - Integração SBC
#
# Uso: ./scripts/validate-sbc.sh [SBC_IP]
#
# Verifica se o sistema está pronto para
# receber chamadas de um SBC externo.
#===============================================

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SBC_IP="${1:-}"

echo "=============================================="
echo "    Validação de Integração SBC"
echo "=============================================="
echo ""

# Função para verificar
check() {
    local description="$1"
    local command="$2"
    local expected="$3"

    printf "%-50s" "$description"

    if eval "$command" &>/dev/null; then
        echo -e "${GREEN}[OK]${NC}"
        return 0
    else
        echo -e "${RED}[FALHA]${NC}"
        return 1
    fi
}

# Função para avisar
warn() {
    local description="$1"
    local message="$2"

    printf "%-50s" "$description"
    echo -e "${YELLOW}[AVISO]${NC}"
    echo "    → $message"
}

# Contador de erros
ERRORS=0

echo "=== 1. Verificando Serviços ==="
echo ""

# Asterisk rodando
if ! check "Asterisk está rodando" "docker exec asterisk-pabx asterisk -rx 'core show version'"; then
    ((ERRORS++))
fi

# Media Server rodando
if ! check "Media Server está rodando" "docker ps | grep -q sip-media-server"; then
    ((ERRORS++))
fi

# AI Agent rodando
if ! check "AI Agent está rodando" "docker ps | grep -q ai-conversation-agent"; then
    ((ERRORS++))
fi

echo ""
echo "=== 2. Verificando Configuração PJSIP ==="
echo ""

# Endpoint SBC existe
if docker exec asterisk-pabx asterisk -rx "pjsip show endpoint sbc-trunk" 2>&1 | grep -q "Endpoint"; then
    echo -e "Endpoint sbc-trunk                                ${GREEN}[OK]${NC}"
else
    echo -e "Endpoint sbc-trunk                                ${YELLOW}[NÃO CONFIGURADO]${NC}"
    echo "    → Adicione o conteúdo de pjsip-sbc.conf.example ao pjsip.conf"
fi

# Identify configurado
if docker exec asterisk-pabx asterisk -rx "pjsip show identifies" 2>&1 | grep -q "sbc"; then
    echo -e "Identify para SBC                                 ${GREEN}[OK]${NC}"
else
    echo -e "Identify para SBC                                 ${YELLOW}[NÃO CONFIGURADO]${NC}"
    echo "    → Configure os IPs do SBC no identify"
fi

# Ramal 2000 registrado
if docker exec asterisk-pabx asterisk -rx "pjsip show aor 2000" 2>&1 | grep -q "Contact:"; then
    echo -e "Ramal 2000 (Media Server) registrado              ${GREEN}[OK]${NC}"
else
    echo -e "Ramal 2000 (Media Server) registrado              ${RED}[FALHA]${NC}"
    ((ERRORS++))
fi

echo ""
echo "=== 3. Verificando Dialplan ==="
echo ""

# Contexto from-sbc existe
if docker exec asterisk-pabx asterisk -rx "dialplan show from-sbc" 2>&1 | grep -q "from-sbc"; then
    echo -e "Contexto from-sbc existe                          ${GREEN}[OK]${NC}"
else
    echo -e "Contexto from-sbc existe                          ${YELLOW}[NÃO CONFIGURADO]${NC}"
    echo "    → Adicione o conteúdo de extensions-sbc.conf.example ao extensions.conf"
fi

echo ""
echo "=== 4. Verificando Portas ==="
echo ""

# Porta SIP 5160
if ss -ulnp | grep -q ":5160"; then
    echo -e "Porta SIP 5160/UDP aberta                         ${GREEN}[OK]${NC}"
else
    echo -e "Porta SIP 5160/UDP aberta                         ${RED}[FALHA]${NC}"
    ((ERRORS++))
fi

# Range RTP
RTP_PORTS=$(ss -ulnp | grep -E ":(2000[0-9]|201[0-9][0-9])" | wc -l)
if [ "$RTP_PORTS" -gt 0 ]; then
    echo -e "Portas RTP 20000-20100/UDP                        ${GREEN}[OK]${NC} ($RTP_PORTS ativas)"
else
    echo -e "Portas RTP 20000-20100/UDP                        ${YELLOW}[NENHUMA ATIVA]${NC}"
    echo "    → Normal se não há chamadas em andamento"
fi

echo ""
echo "=== 5. Verificando Conectividade ==="
echo ""

if [ -n "$SBC_IP" ]; then
    # Ping ao SBC
    if ping -c 1 -W 2 "$SBC_IP" &>/dev/null; then
        echo -e "Ping para SBC ($SBC_IP)                          ${GREEN}[OK]${NC}"
    else
        echo -e "Ping para SBC ($SBC_IP)                          ${RED}[FALHA]${NC}"
        ((ERRORS++))
    fi

    # Porta SIP do SBC
    if nc -z -u -w 2 "$SBC_IP" 5060 &>/dev/null; then
        echo -e "Porta SIP do SBC ($SBC_IP:5060)                  ${GREEN}[OK]${NC}"
    else
        echo -e "Porta SIP do SBC ($SBC_IP:5060)                  ${YELLOW}[NÃO TESTÁVEL]${NC}"
        echo "    → UDP probe pode não funcionar através de firewall"
    fi
else
    warn "Conectividade com SBC" "Passe o IP do SBC como argumento para testar"
fi

echo ""
echo "=== 6. Verificando RTP Config ==="
echo ""

# Verificar strictrtp
STRICTRTP=$(docker exec asterisk-pabx asterisk -rx "rtp show settings" 2>&1 | grep -i "strictrtp" || echo "")
if echo "$STRICTRTP" | grep -qi "no"; then
    echo -e "strictrtp=no (bom para SBC)                       ${GREEN}[OK]${NC}"
elif echo "$STRICTRTP" | grep -qi "yes"; then
    echo -e "strictrtp=yes                                     ${YELLOW}[AVISO]${NC}"
    echo "    → Se SBC faz ancoragem de mídia, mude para strictrtp=no"
else
    echo -e "strictrtp                                         ${YELLOW}[NÃO VERIFICÁVEL]${NC}"
fi

echo ""
echo "=============================================="

if [ $ERRORS -gt 0 ]; then
    echo -e "Resultado: ${RED}$ERRORS ERRO(S) ENCONTRADO(S)${NC}"
    echo ""
    echo "Corrija os erros antes de integrar com o SBC."
    exit 1
else
    echo -e "Resultado: ${GREEN}SISTEMA PRONTO${NC}"
    echo ""
    echo "Próximos passos:"
    echo "1. Configure os IPs do SBC no pjsip.conf (identify)"
    echo "2. Ajuste o dialplan conforme seus DIDs"
    echo "3. Configure o NLB para balancear portas 5160 e 20000-20100"
    echo "4. Teste com: asterisk -rx 'pjsip set logger on'"
    exit 0
fi
