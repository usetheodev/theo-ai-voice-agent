# ✅ Asterisk Configuration Summary

**Data:** 2026-01-20
**Status:** ✅ CONFIGURAÇÃO COMPLETA - Pronto para testar com softphone

---

## 🎯 O Que Foi Configurado

### 1. PJSIP Endpoints (Softphone Users)

**Arquivo:** `docker/asterisk/config/pjsip.conf`

| Usuário | Username | Password | Extension | Status |
|---------|----------|----------|-----------|--------|
| Test User | `testuser` | `test123` | `1000` | ✅ Configurado |
| Alice | `alice` | `alice123` | `1001` | ✅ Configurado |
| Bob | `bob` | `bob123` | `1002` | ✅ Configurado |

**AI Voice Agent Trunk:**
- Endpoint: `voiceagent-endpoint`
- Contact: `sip:voiceagent:5060`
- IP: `172.20.0.20` (Docker network)
- Codecs: ulaw, alaw, opus

---

### 2. Dialplan (Call Routing)

**Arquivo:** `docker/asterisk/config/extensions.conf`

| Extensão | Destino | Descrição |
|----------|---------|-----------|
| `100` | AI Voice Agent | **Rota principal de teste** |
| `101` | Echo Test | Testa áudio bidirecional (sem AI) |
| `102` | Playback Test | Testa áudio Asterisk → Softphone |
| `103` | Milliwatt Test | Tom de 1000Hz (teste de sinal) |
| `1000-1002` | Outros usuários | Chamadas peer-to-peer |

**Fluxo da Extensão 100:**
```
User disca 100
→ Asterisk Answer()
→ Asterisk Dial(PJSIP/voiceagent-endpoint/sip:agent@voiceagent:5060)
→ AI Voice Agent recebe SIP INVITE
→ Se responder: Áudio bidirecional via RTP
→ Se não responder: Playback "currently unavailable"
```

---

### 3. Módulos Asterisk

**Arquivo:** `docker/asterisk/config/modules.conf`

**Habilitados:**
- ✅ `chan_pjsip.so` - PJSIP channel driver (moderno)
- ✅ `res_pjsip*.so` - PJSIP resources (13 módulos)
- ✅ `codec_ulaw.so, codec_alaw.so, codec_opus.so` - Codecs G.711 e Opus
- ✅ `res_ari.so` - ARI (Asterisk REST Interface)
- ✅ `res_rtp_asterisk.so` - RTP support

**Desabilitados:**
- ❌ `chan_sip.so` - Legacy SIP (evitar conflito com PJSIP)
- ❌ `chan_dahdi.so, chan_iax2.so` - Hardware não usado

---

### 4. Rede Docker

**Arquivo:** `docker-compose.yml`

```
Network: voip-net (172.20.0.0/16)

┌────────────────────┬──────────────┬─────────────────┐
│ Service            │ IP           │ Ports           │
├────────────────────┼──────────────┼─────────────────┤
│ asterisk           │ 172.20.0.10  │ 5060 (SIP)      │
│                    │              │ 10000-10100 RTP │
│                    │              │ 8088 (ARI)      │
├────────────────────┼──────────────┼─────────────────┤
│ voiceagent         │ 172.20.0.20  │ 5060 (SIP)      │
│ (AI Voice Agent)   │              │ 10200-10300 RTP │
│                    │              │ 8000 (Metrics)  │
└────────────────────┴──────────────┴─────────────────┘
```

**Port Mapping (Host → Container):**
- `5060:5060/udp` - Asterisk SIP (softphone conecta aqui)
- `5080:5060/udp` - AI Agent SIP (evita conflito)
- `10000-10100:10000-10100/udp` - Asterisk RTP
- `10200-10300:10200-10300/udp` - AI Agent RTP

---

## 🧪 Script de Teste

**Arquivo:** `scripts/test_asterisk_setup.sh`

**O que o script valida:**
1. ✅ Container Asterisk está rodando
2. ✅ Asterisk process ativo
3. ✅ PJSIP module carregado
4. ✅ PJSIP endpoints configurados (1000, 1001, 1002, voiceagent)
5. ✅ Dialplan carregado (extensões 100-103)
6. ✅ RTP ports configurados (10000-10100)
7. ✅ Network connectivity (Asterisk → voiceagent)
8. ✅ SIP port listening (5060/udp)
9. ✅ Host pode alcançar Asterisk (localhost:5060)
10. ✅ Config files existem

**Uso:**
```bash
chmod +x ./scripts/test_asterisk_setup.sh
./scripts/test_asterisk_setup.sh
```

---

## 📱 Como Conectar Softphone

### Quick Setup (Zoiper/Linphone)

**SIP Account:**
```
Server: <SEU_IP>:5060
Username: testuser
Password: test123
Display Name: Test User
Transport: UDP
```

**Descobrir seu IP:**
```bash
hostname -I | awk '{print $1}'
# Ou
ip addr show | grep "inet " | grep -v "127.0.0.1"
```

### Primeira Chamada de Teste

**Passo 1:** Registre o softphone (deve aparecer ícone verde)

**Passo 2:** Disque `101` (Echo Test)
- ✅ Esperado: Ouvir sua própria voz (eco)
- ✅ Valida: RTP bidirecional funciona

**Passo 3:** Disque `102` (Playback Test)
- ✅ Esperado: Ouvir mensagens gravadas
- ✅ Valida: Asterisk → Softphone funciona

**Passo 4:** Disque `100` (AI Voice Agent)
- ⚠️ Esperado (se AI não implementado): "Currently unavailable"
- ✅ Valida: Roteamento Asterisk → AI está funcionando

---

## 📊 Status de Implementação

### ✅ Asterisk (COMPLETO)

- [x] Dockerfile configurado
- [x] PJSIP endpoints criados
- [x] Dialplan implementado
- [x] Módulos configurados
- [x] Docker network configurado
- [x] Script de teste criado
- [x] Documentação completa

### ⏳ AI Voice Agent (PENDENTE)

- [ ] SIP Server implementado
- [ ] RTP Server implementado
- [ ] AI Pipeline implementado
- [ ] Integração completa

---

## 🔍 Troubleshooting

### Asterisk não inicia

```bash
# Ver logs
docker logs asterisk

# Possíveis causas:
# - Porta 5060 já em uso
# - Erro de sintaxe nos configs
# - Falta de recursos (RAM/CPU)

# Solução: Verificar logs e corrigir
docker-compose down
docker-compose up -d asterisk
```

### Softphone não registra

```bash
# Verificar se Asterisk está rodando
docker ps | grep asterisk

# Verificar logs em tempo real
docker logs -f asterisk

# Verificar endpoints
docker exec asterisk asterisk -rx "pjsip show endpoints"

# Deve mostrar:
# 1000  testuser  Not in use  0 of inf
```

### Chamada conecta mas sem áudio

```bash
# Verificar RTP ports abertas
sudo ufw allow 10000:10100/udp

# Verificar codecs negociados
docker exec asterisk asterisk -rx "pjsip show endpoint 1000"

# Capturar RTP para debug
sudo tcpdump -i any -n 'udp portrange 10000-10100'
```

### Extensão 100 não conecta ao AI Agent

**Esperado se AI Agent não implementado ainda:**
```
DIALSTATUS = CHANUNAVAIL
ou
DIALSTATUS = NOANSWER
```

**Quando AI implementado, deve ser:**
```
DIALSTATUS = ANSWER
```

**Verificar conectividade:**
```bash
docker exec asterisk ping voiceagent
# Deve responder com "64 bytes from voiceagent..."
```

---

## 📚 Arquivos Criados/Modificados

```
ai-voice-agent/
├── docker/asterisk/config/
│   ├── pjsip.conf           ✅ CRIADO (PJSIP endpoints)
│   ├── extensions.conf      ✅ ATUALIZADO (dialplan com ext 100-103)
│   ├── modules.conf         ✅ CRIADO (PJSIP habilitado, chan_sip desabilitado)
│   ├── rtp.conf             ✅ EXISTENTE (10000-10100)
│   ├── logger.conf          ✅ EXISTENTE
│   ├── ari.conf             ✅ EXISTENTE
│   ├── http.conf            ✅ EXISTENTE
│   └── sip.conf             ✅ EXISTENTE (legacy, não usado)
│
├── scripts/
│   └── test_asterisk_setup.sh  ✅ CRIADO (10 automated tests)
│
├── SOFTPHONE_SETUP.md          ✅ CRIADO (guia completo softphone)
├── TESTING_STRATEGY.md         ✅ CRIADO (estratégia de testes)
├── ASTERISK_CONFIG_SUMMARY.md  ✅ CRIADO (este arquivo)
└── docker/asterisk/README.md   ✅ ATUALIZADO (quick start)
```

---

## 🚀 Próximos Passos

### 1. Testar Asterisk AGORA

```bash
# Passo 1: Subir Asterisk
cd /home/paulo/Projetos/pesquisas/ai-voice-agent
docker-compose up -d asterisk

# Passo 2: Aguardar inicializar (~30s)
docker logs -f asterisk

# Passo 3: Rodar testes
./scripts/test_asterisk_setup.sh

# Passo 4: Configurar softphone
# Ver SOFTPHONE_SETUP.md

# Passo 5: Testar extensão 101 (echo)
# Deve funcionar perfeitamente!
```

### 2. Implementar AI Voice Agent

**Ordem recomendada:**
1. Common Module (config, logging, metrics, errors)
2. Orchestrator (EventBus, CallOrchestrator)
3. RTP Server (AudioStream, codec, jitter buffer)
4. SIP Server (PJSUA2 wrapper, session, auth, SDP)
5. AI Pipeline (VAD, ASR, LLM, TTS)

### 3. Testar E2E

Quando AI Agent estiver implementado:
```bash
# Subir tudo
docker-compose up -d

# Discar extensão 100
# Esperado: AI atende e responde!
```

---

## 📞 Credenciais Rápidas (Copiar/Colar)

**Softphone Configuration:**
```
SIP Server: <YOUR_IP>:5060
Username: testuser
Password: test123
```

**Test Extensions:**
```
101 → Echo test
102 → Playback test
100 → AI Voice Agent
```

**Docker Commands:**
```bash
# Start
docker-compose up -d asterisk

# Logs
docker logs -f asterisk

# CLI
docker exec -it asterisk asterisk -rvvv

# Test
./scripts/test_asterisk_setup.sh
```

---

## ✅ Checklist Final

- [x] PJSIP configurado com 3 usuários (1000, 1001, 1002)
- [x] Trunk para AI Voice Agent configurado
- [x] Dialplan com 5 extensões de teste (100-103, 1000-1002)
- [x] Módulos Asterisk otimizados (PJSIP on, chan_sip off)
- [x] Docker network configurado (172.20.0.0/16)
- [x] Script de teste automatizado criado
- [x] Documentação completa (3 arquivos: SOFTPHONE_SETUP, TESTING_STRATEGY, este)
- [x] Pronto para testar com softphone real

---

**🎉 Asterisk está 100% configurado e pronto para uso!**

**Próximo passo:** Configure seu softphone e teste a extensão `101` (echo).
**Depois:** Implemente o AI Voice Agent para fazer a extensão `100` funcionar!

---

**Documentação relacionada:**
- [SOFTPHONE_SETUP.md](SOFTPHONE_SETUP.md) - Setup detalhado do softphone
- [TESTING_STRATEGY.md](TESTING_STRATEGY.md) - Estratégia completa de testes
- [docker/asterisk/README.md](docker/asterisk/README.md) - README do container Asterisk
