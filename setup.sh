#!/bin/bash
# Setup script para PABX Docker

set -e

echo "==================================="
echo "   PABX Docker - Setup Inicial"
echo "==================================="
echo ""

# Criar diretórios necessários
echo "[1/4] Criando diretórios..."
mkdir -p asterisk/keys
mkdir -p asterisk/sounds

# Gerar certificados SSL
echo "[2/4] Gerando certificados SSL..."
if [ ! -f asterisk/keys/asterisk.crt ]; then
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout asterisk/keys/asterisk.key \
        -out asterisk/keys/asterisk.crt \
        -subj "/CN=localhost" \
        2>/dev/null
    echo "    Certificados gerados com sucesso!"
else
    echo "    Certificados já existem, pulando..."
fi

# Iniciar Asterisk
echo "[3/4] Iniciando Asterisk..."
docker-compose up -d

# Aguardar inicialização
echo "[4/4] Aguardando inicialização..."
sleep 5

# Verificar status
echo ""
echo "==================================="
echo "   Status do Sistema"
echo "==================================="
echo ""

if docker-compose ps | grep -q "Up"; then
    echo "Asterisk: RODANDO"
    echo ""
    echo "Ramais disponíveis:"
    echo "  - 1001 (senha: ramal1001) - SIP"
    echo "  - 1002 (senha: ramal1002) - SIP"
    echo "  - 1003 (senha: ramal1003) - SIP"
    echo "  - 1004 (senha: ramal1004) - WebRTC"
    echo "  - 1005 (senha: ramal1005) - WebRTC"
    echo ""
    echo "Códigos úteis:"
    echo "  - 9    : Acessar URA"
    echo "  - *43  : Teste de eco"
    echo "  - *60  : Hora certa"
    echo "  - 8000 : Sala de conferência"
    echo ""
    echo "Para iniciar o SoftPhone React:"
    echo "  cd softphone && npm install && npm run dev"
    echo ""
    echo "CLI do Asterisk:"
    echo "  docker exec -it asterisk-pabx asterisk -rvvv"
else
    echo "ERRO: Asterisk não iniciou corretamente"
    echo "Verifique os logs: docker-compose logs asterisk"
    exit 1
fi
