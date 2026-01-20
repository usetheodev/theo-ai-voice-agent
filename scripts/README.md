# 🛠️ Scripts - AI Voice Agent

Coleção de scripts utilitários para gerenciar o AI Voice Agent.

---

## 📜 Scripts Disponíveis

### 1. `start-asterisk.sh` ⭐ **Principal**

**Descrição:** Start completo do Asterisk com health checks

**Uso:**
```bash
./scripts/start-asterisk.sh [options]
```

**Opções:**
- `--rebuild` - Force rebuild do Docker image
- `--clean` - Limpa containers e volumes antes de iniciar
- `--logs` - Segue os logs após o start
- `--help` - Mostra ajuda

**O que faz:**
1. ✅ Verifica/gera certificados SSL
2. ✅ Build da imagem Docker (se necessário)
3. ✅ Para containers existentes
4. ✅ Inicia Asterisk
5. ✅ Aguarda inicialização (até 60s)
6. ✅ Roda 8 health checks
7. ✅ Exibe informações de acesso
8. ✅ Mostra comandos úteis

**Exemplos:**
```bash
# Start normal
./scripts/start-asterisk.sh

# Start com rebuild completo
./scripts/start-asterisk.sh --rebuild

# Start limpo (remove tudo antes)
./scripts/start-asterisk.sh --clean

# Start e seguir logs
./scripts/start-asterisk.sh --logs

# Rebuild + Clean + Logs
./scripts/start-asterisk.sh --rebuild --clean --logs
```

---

### 2. `start_browser_phone.sh`

**Descrição:** Setup rápido do Browser-Phone (WebRTC)

**Uso:**
```bash
./scripts/start_browser_phone.sh
```

**O que faz:**
1. Verifica/gera certificados SSL
2. Build do Asterisk com Browser-Phone
3. Start do container
4. Exibe instruções de acesso
5. Mostra como instalar CA certificate

**Quando usar:**
- Primeiro uso do Browser-Phone
- Quer instruções passo-a-passo
- Precisa de ajuda com certificados

---

### 3. `test_asterisk_setup.sh`

**Descrição:** Testes automatizados da configuração do Asterisk

**Uso:**
```bash
./scripts/test_asterisk_setup.sh
```

**O que testa (10 testes):**
1. ✅ Container Asterisk rodando
2. ✅ Processo Asterisk ativo
3. ✅ PJSIP module carregado
4. ✅ PJSIP endpoints configurados (100, 1000, 1001, 1002, voiceagent)
5. ✅ Dialplan carregado (extensões 100-103)
6. ✅ RTP ports configurados (10000-10100)
7. ✅ Conectividade de rede (Asterisk → voiceagent)
8. ✅ SIP port listening (5060/udp)
9. ✅ Host pode alcançar Asterisk (localhost:5060)
10. ✅ Config files existem

**Output:**
- Mostra testes PASSED/FAILED
- Exibe credenciais do softphone
- Lista extensões de teste
- Sugere próximos passos

**Quando usar:**
- Depois de iniciar Asterisk
- Para troubleshooting
- Para validar configuração
- Antes de fazer chamadas de teste

---

## 🔄 Fluxo Recomendado

### Primeira Vez (Setup Completo)

```bash
# 1. Start com setup completo
./scripts/start-asterisk.sh --rebuild --clean

# 2. Validar configuração
./scripts/test_asterisk_setup.sh

# 3. Instalar CA certificate no navegador
#    Arquivo: asterisk/certs/ca.crt

# 4. Acessar Browser-Phone
#    https://localhost:8089/
```

---

### Uso Diário

```bash
# Start rápido
./scripts/start-asterisk.sh

# Ver logs em tempo real
./scripts/start-asterisk.sh --logs

# Ou seguir logs depois
docker logs -f asterisk
```

---

### Troubleshooting

```bash
# Rebuild completo (se algo quebrou)
./scripts/start-asterisk.sh --rebuild --clean

# Validar configuração
./scripts/test_asterisk_setup.sh

# Ver logs detalhados
docker logs asterisk --tail 100

# Entrar no CLI do Asterisk
docker exec -it asterisk asterisk -rvvv
```

---

## 📊 Comparação dos Scripts

| Script | Propósito | Quando Usar | Tempo |
|--------|-----------|-------------|-------|
| `start-asterisk.sh` | **Start completo** | **Uso geral** | ~30s |
| `start_browser_phone.sh` | Setup WebRTC | Primeira vez | ~45s |
| `test_asterisk_setup.sh` | Validação | Troubleshooting | ~10s |

---

## 🎯 Casos de Uso

### Caso 1: Primeira instalação

```bash
# Setup completo do zero
./scripts/start-asterisk.sh --rebuild --clean
./scripts/test_asterisk_setup.sh

# Seguir instruções para instalar certificado
# Testar no navegador
```

### Caso 2: Desenvolvimento diário

```bash
# Start rápido
./scripts/start-asterisk.sh

# Fazer mudanças no código...

# Restart para aplicar
docker-compose restart asterisk
```

### Caso 3: Algo quebrou

```bash
# Rebuild completo
./scripts/start-asterisk.sh --rebuild --clean

# Validar
./scripts/test_asterisk_setup.sh

# Se ainda falhar, ver logs
docker logs asterisk
```

### Caso 4: Demonstração/Apresentação

```bash
# Start com logs
./scripts/start-asterisk.sh --logs

# Em outra janela:
./scripts/test_asterisk_setup.sh

# Mostrar Browser-Phone:
# https://localhost:8089/
```

---

## 🔧 Comandos Úteis (Complementares)

### Docker Compose

```bash
# Start serviços
docker-compose up -d

# Start apenas Asterisk
docker-compose up -d asterisk

# Stop tudo
docker-compose down

# Stop com remoção de volumes
docker-compose down -v

# Ver logs
docker-compose logs -f asterisk

# Restart
docker-compose restart asterisk

# Rebuild
docker-compose build asterisk
```

### Docker (Direto)

```bash
# Ver containers rodando
docker ps

# Ver todos containers
docker ps -a

# Ver logs
docker logs asterisk
docker logs asterisk --tail 50
docker logs -f asterisk

# Exec comando
docker exec asterisk asterisk -rx "core show version"

# Entrar no container
docker exec -it asterisk bash

# Entrar no CLI Asterisk
docker exec -it asterisk asterisk -rvvv
```

### Asterisk CLI (Dentro do container)

```bash
# Conectar ao CLI
docker exec -it asterisk asterisk -rvvv

# Comandos úteis no CLI:
pjsip show endpoints          # Ver endpoints
pjsip show transports         # Ver transports
core show channels            # Ver chamadas ativas
dialplan show default         # Ver dialplan
rtp show stats                # Ver estatísticas RTP
core reload                   # Reload configs
core restart now              # Restart Asterisk
exit                          # Sair do CLI
```

---

## 📖 Documentação Relacionada

- **BROWSER_PHONE_SETUP.md** - Guia completo do Browser-Phone
- **SOFTPHONE_SETUP.md** - Guia completo do Softphone
- **TESTING_STRATEGY.md** - Estratégia de testes
- **ASTERISK_CONFIG_SUMMARY.md** - Resumo da configuração
- **docker/asterisk/README.md** - Documentação do container

---

## 🐛 Troubleshooting Scripts

### Script não executa

```bash
# Verificar permissões
ls -la scripts/

# Se não for executável:
chmod +x scripts/*.sh

# Executar novamente
./scripts/start-asterisk.sh
```

### Erro "command not found"

```bash
# Usar caminho absoluto
/home/paulo/Projetos/pesquisas/ai-voice-agent/scripts/start-asterisk.sh

# Ou navegar até o diretório
cd /home/paulo/Projetos/pesquisas/ai-voice-agent
./scripts/start-asterisk.sh
```

### Timeout durante health checks

```bash
# Aumentar tempo de espera (editar script)
# Ou ver logs para debug
docker logs asterisk

# Verificar se Asterisk está realmente rodando
docker ps | grep asterisk
docker exec asterisk ps aux | grep asterisk
```

---

## ✅ Quick Reference

**Start Asterisk:**
```bash
./scripts/start-asterisk.sh
```

**Test Configuration:**
```bash
./scripts/test_asterisk_setup.sh
```

**View Logs:**
```bash
docker logs -f asterisk
```

**Asterisk CLI:**
```bash
docker exec -it asterisk asterisk -rvvv
```

**Restart:**
```bash
docker-compose restart asterisk
```

**Stop:**
```bash
docker-compose stop asterisk
```

**Clean Rebuild:**
```bash
./scripts/start-asterisk.sh --rebuild --clean
```

---

**Criado:** 2026-01-20
**Autor:** Claude Code
**Versão:** 1.0
