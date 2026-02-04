#!/bin/bash
#===============================================
# Script de Validação - Integração SBC
# Compatível com Linux e Windows (Git Bash)
#
# Uso: ./scripts/validate-sbc.sh [SBC_IP]
#
# Verifica se o sistema está pronto para
# receber chamadas de um SBC externo.
#===============================================

set -e

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
# Cores para output
#-----------------------------------------------
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    NC=''
fi

SBC_IP="${1:-}"

echo "=============================================="
echo "    Validacao de Integracao SBC"
echo "    OS: $OS_TYPE"
echo "=============================================="
echo ""

#-----------------------------------------------
# Função para verificar
#-----------------------------------------------
check() {
    local description="$1"
    local command="$2"

    printf "%-50s" "$description"

    if eval "$command" &>/dev/null; then
        echo -e "${GREEN}[OK]${NC}"
        return 0
    else
        echo -e "${RED}[FALHA]${NC}"
        return 1
    fi
}

#-----------------------------------------------
# Função para avisar
#-----------------------------------------------
warn() {
    local description="$1"
    local message="$2"

    printf "%-50s" "$description"
    echo -e "${YELLOW}[AVISO]${NC}"
    echo "    -> $message"
}

#-----------------------------------------------
# Verifica se porta está aberta (cross-platform)
#-----------------------------------------------
check_port() {
    local port="$1"
    local proto="${2:-tcp}"

    case "$OS_TYPE" in
        linux)
            if command -v ss &> /dev/null; then
                if [ "$proto" = "udp" ]; then
                    ss -ulnp 2>/dev/null | grep -q ":${port} "
                else
                    ss -tlnp 2>/dev/null | grep -q ":${port} "
                fi
            elif command -v netstat &> /dev/null; then
                netstat -tuln 2>/dev/null | grep -q ":${port} "
            else
                return 0  # Assume OK se não conseguir verificar
            fi
            ;;
        macos)
            netstat -an 2>/dev/null | grep -q "\.${port} "
            ;;
        windows)
            # Git Bash: usa netstat do Windows
            netstat -an 2>/dev/null | grep -qi ":${port} "
            ;;
        *)
            return 0  # Assume OK
            ;;
    esac
}

#-----------------------------------------------
# Ping cross-platform
#-----------------------------------------------
ping_host() {
    local host="$1"

    case "$OS_TYPE" in
        linux|macos)
            ping -c 1 -W 2 "$host" &>/dev/null
            ;;
        windows)
            # Windows ping tem sintaxe diferente
            ping -n 1 -w 2000 "$host" &>/dev/null
            ;;
        *)
            ping -c 1 "$host" &>/dev/null
            ;;
    esac
}

# Contador de erros
ERRORS=0

echo "=== 1. Verificando Servicos ==="
echo ""

# Asterisk rodando
if ! check "Asterisk esta rodando" "docker exec asterisk-pabx asterisk -rx 'core show version'"; then
    ((ERRORS++)) || true
fi

# Media Server rodando
if ! check "Media Server esta rodando" "docker ps --format '{{.Names}}' | grep -q sip-media-server"; then
    ((ERRORS++)) || true
fi

# AI Agent rodando
if ! check "AI Agent esta rodando" "docker ps --format '{{.Names}}' | grep -q ai-conversation-agent"; then
    ((ERRORS++)) || true
fi

echo ""
echo "=== 2. Verificando Configuracao PJSIP ==="
echo ""

# Endpoint SBC existe
if docker exec asterisk-pabx asterisk -rx "pjsip show endpoint sbc-trunk" 2>&1 | grep -q "Endpoint"; then
    echo -e "Endpoint sbc-trunk                                ${GREEN}[OK]${NC}"
else
    echo -e "Endpoint sbc-trunk                                ${YELLOW}[NAO CONFIGURADO]${NC}"
    echo "    -> Adicione o conteudo de pjsip-sbc.conf.example ao pjsip.conf"
fi

# Identify configurado
if docker exec asterisk-pabx asterisk -rx "pjsip show identifies" 2>&1 | grep -q "sbc"; then
    echo -e "Identify para SBC                                 ${GREEN}[OK]${NC}"
else
    echo -e "Identify para SBC                                 ${YELLOW}[NAO CONFIGURADO]${NC}"
    echo "    -> Configure os IPs do SBC no identify"
fi

# Ramal 2000 registrado
if docker exec asterisk-pabx asterisk -rx "pjsip show aor 2000" 2>&1 | grep -q "Contact:"; then
    echo -e "Ramal 2000 (Media Server) registrado              ${GREEN}[OK]${NC}"
else
    echo -e "Ramal 2000 (Media Server) registrado              ${RED}[FALHA]${NC}"
    ((ERRORS++)) || true
fi

echo ""
echo "=== 3. Verificando Dialplan ==="
echo ""

# Contexto from-sbc existe
if docker exec asterisk-pabx asterisk -rx "dialplan show from-sbc" 2>&1 | grep -q "from-sbc"; then
    echo -e "Contexto from-sbc existe                          ${GREEN}[OK]${NC}"
else
    echo -e "Contexto from-sbc existe                          ${YELLOW}[NAO CONFIGURADO]${NC}"
    echo "    -> Adicione o conteudo de extensions-sbc.conf.example ao extensions.conf"
fi

echo ""
echo "=== 4. Verificando Portas ==="
echo ""

# Porta SIP 5160
if check_port 5160 udp; then
    echo -e "Porta SIP 5160/UDP aberta                         ${GREEN}[OK]${NC}"
else
    echo -e "Porta SIP 5160/UDP aberta                         ${YELLOW}[NAO VERIFICAVEL]${NC}"
    echo "    -> Verifique manualmente se o Asterisk esta escutando"
fi

# Verifica dentro do container (mais confiável)
if docker exec asterisk-pabx asterisk -rx "pjsip show transports" 2>&1 | grep -q "5160"; then
    echo -e "Transporte PJSIP porta 5160                       ${GREEN}[OK]${NC}"
else
    echo -e "Transporte PJSIP porta 5160                       ${RED}[FALHA]${NC}"
    ((ERRORS++)) || true
fi

echo ""
echo "=== 5. Verificando Conectividade ==="
echo ""

if [ -n "$SBC_IP" ]; then
    # Ping ao SBC
    if ping_host "$SBC_IP"; then
        echo -e "Ping para SBC ($SBC_IP)                          ${GREEN}[OK]${NC}"
    else
        echo -e "Ping para SBC ($SBC_IP)                          ${RED}[FALHA]${NC}"
        ((ERRORS++)) || true
    fi

    # Aviso sobre teste de porta UDP
    echo -e "Porta SIP do SBC ($SBC_IP:5060)                  ${YELLOW}[NAO TESTAVEL]${NC}"
    echo "    -> UDP probe nao e confiavel. Teste com chamada real."
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
    echo "    -> Se SBC faz ancoragem de midia, mude para strictrtp=no"
else
    echo -e "strictrtp                                         ${YELLOW}[NAO VERIFICAVEL]${NC}"
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
    echo "Proximos passos:"
    echo "1. Configure os IPs do SBC no pjsip.conf (identify)"
    echo "2. Ajuste o dialplan conforme seus DIDs"
    echo "3. Configure o NLB para balancear portas 5160 e 20000-20100"
    echo "4. Teste com: asterisk -rx 'pjsip set logger on'"
    exit 0
fi
