# Asterisk Docker Container

**Propósito:** Gateway SIP para testes E2E do AI Voice Agent

**✅ CONFIGURADO COM PJSIP (Moderno)** - Pronto para usar com softphones!

---

## 🎯 Quick Start

```bash
# Build and start Asterisk
docker-compose up -d asterisk

# Check status
docker logs -f asterisk

# Test configuration
./scripts/test_asterisk_setup.sh
```

## 📱 Softphone Credentials

**Test User (Primary):**
- **Server:** `<YOUR_IP>:5060`
- **Username:** `testuser`
- **Password:** `test123`
- **Extension:** `1000`

**Additional Users:**
- **alice** / `alice123` → Extension `1001`
- **bob** / `bob123` → Extension `1002`

## 🧪 Test Extensions

| Extension | Description |
|-----------|-------------|
| `100` | Call AI Voice Agent (main test) |
| `101` | Echo test (verify audio) |
| `102` | Playback test (Asterisk sounds) |
| `103` | Milliwatt test (1000Hz tone) |
| `1000-1002` | Call other softphones |

## 📖 Full Documentation

See [SOFTPHONE_SETUP.md](../../SOFTPHONE_SETUP.md) for complete softphone configuration guide.

---

## 🏗️ Architecture

```
User (Softphone) → Asterisk (PJSIP) → AI Voice Agent
      :5060         172.20.0.10          172.20.0.20:5060
                    RTP: 10000-10100     RTP: 10200-10300
```

---

## 🏗️ Estrutura

```
docker/asterisk/
├── Dockerfile              # Build do Asterisk
├── README.md              # Este arquivo
└── config/                # Configurações Asterisk
    ├── sip.conf           # Configuração SIP
    ├── extensions.conf    # Dialplan
    ├── ari.conf           # ARI (REST API)
    └── logger.conf        # Logs
```

---

## 📞 Extensões Configuradas

### Extensão 100: Chamar Voice Agent

```
User liga: sip:100@<server_ip>:5060
→ Asterisk recebe
→ Asterisk encaminha para VoiceAgent
→ VoiceAgent processa áudio (ASR → LLM → TTS)
```

**Dialplan:**
```ini
[default]
exten => 100,1,NoOp(=== Calling AI Voice Agent ===)
 same => n,Dial(SIP/voiceagent/agent,60,tr)
 same => n,Hangup()
```

---

### Extensão 101: Echo Test

Testa áudio bidirecional sem AI.

```
User liga: sip:101@<server_ip>:5060
→ Tudo que você falar volta como eco
```

---

### Extensão 102: Playback Test

Testa se Asterisk está funcionando.

```
User liga: sip:102@<server_ip>:5060
→ Ouve "Hello World" + mensagem de demo
```

---

## 🔑 Credenciais de Teste

### SIP User (Softphone)

```
Username: testuser
Password: test123
Domain: <server_ip>:5060
```

### ARI (REST API)

```
URL: http://<server_ip>:8088/ari
Username: asterisk
Password: asterisk
```

---

## 🚀 Build e Run

### Build Manual

```bash
cd /home/paulo/Projetos/pesquisas/ai-voice-agent/sip

# Build
docker build -t ai-voice-agent/asterisk:latest ./docker/asterisk

# Run standalone
docker run -d \
  --name asterisk \
  --network voip-net \
  --ip 172.20.0.10 \
  -p 5060:5060/udp \
  -p 10000-10100:10000-10100/udp \
  -p 8088:8088 \
  ai-voice-agent/asterisk:latest
```

### Via Docker Compose (Recomendado)

```bash
# Subir tudo
docker-compose up -d

# Ver logs
docker-compose logs -f asterisk
```

---

## 🧪 Testes

### Teste 1: Asterisk está rodando?

```bash
# Verificar status
docker exec asterisk asterisk -rx "core show version"

# Output esperado:
# Asterisk 20.x.x built by root @ ...
```

---

### Teste 2: SIP trunk para VoiceAgent está up?

```bash
# Verificar peers
docker exec asterisk asterisk -rx "sip show peers"

# Output esperado:
# Name/username    Host            Dyn Forcerport ACL Port     Status
# voiceagent       voiceagent           N      N      A  5060     OK (...)
```

---

### Teste 3: Fazer chamada de teste

**Opção A: Via Softphone (Zoiper, Linphone)**

```
1. Configurar softphone:
   - Server: <server_ip>:5060
   - Username: testuser
   - Password: test123

2. Ligar para: 100
   → Deve conectar com VoiceAgent

3. Ligar para: 101
   → Deve ouvir eco (sem VoiceAgent)
```

**Opção B: Via ARI (REST API)**

```bash
# Originar chamada para extensão 100
curl -X POST http://localhost:8088/ari/channels \
  -u asterisk:asterisk \
  -d "endpoint=SIP/voiceagent" \
  -d "extension=100" \
  -d "context=default"
```

---

## 🔍 Debug

### Ver logs em tempo real

```bash
# Console do Asterisk
docker exec -it asterisk asterisk -rvvv

# Comandos úteis:
asterisk*CLI> core show channels
asterisk*CLI> sip show peers
asterisk*CLI> sip show channelstats
asterisk*CLI> dialplan show default
```

---

### Habilitar debug SIP

```bash
# Via CLI
docker exec asterisk asterisk -rx "sip set debug on"

# Via arquivo (editar logger.conf)
# Descomentar linha:
# sip_debug => debug,verbose

# Restart
docker-compose restart asterisk
```

---

### Capturar pacotes SIP/RTP

```bash
# Capturar SIP (porta 5060)
docker exec asterisk tcpdump -i eth0 -n -s 0 -A port 5060

# Capturar RTP (portas 10000-10100)
docker exec asterisk tcpdump -i eth0 -n udp portrange 10000-10100

# Salvar em arquivo (analisar com Wireshark)
docker exec asterisk tcpdump -i eth0 -w /tmp/capture.pcap port 5060
docker cp asterisk:/tmp/capture.pcap ./asterisk_capture.pcap
wireshark asterisk_capture.pcap
```

---

## 🐛 Troubleshooting

### Problema: Asterisk não inicia

**Verificar logs:**
```bash
docker logs asterisk

# Ou via docker-compose
docker-compose logs asterisk
```

**Soluções comuns:**
- Erro de sintaxe em config files (sip.conf, extensions.conf)
- Porta 5060 já em uso no host
- Falta de memória

---

### Problema: SIP peer "voiceagent" está UNREACHABLE

**Debug:**
```bash
# Verificar conectividade
docker exec asterisk ping voiceagent

# Verificar se VoiceAgent está ouvindo
docker exec ai-voice-agent netstat -tulpn | grep 5060
```

**Soluções:**
- VoiceAgent não iniciou ainda (aguardar healthcheck)
- VoiceAgent não está na mesma rede Docker
- Firewall bloqueando (improvável em Docker)

---

### Problema: Chamada conecta mas não há áudio

**Debug:**
```bash
# Verificar SDP negociado
docker exec asterisk asterisk -rx "sip show channels"

# Verificar se RTP está fluindo
docker exec asterisk tcpdump -i eth0 -n udp portrange 10000-10100
```

**Soluções:**
- Codec mismatch (verificar allow/disallow em sip.conf)
- NAT issues (verificar externip/localnet)
- Firewall bloqueando RTP
- VoiceAgent não enviando RTP de volta

---

### Problema: Echo test (101) não funciona

**Se echo test não funciona, o problema está no Asterisk, não no VoiceAgent!**

**Debug:**
```bash
# Verificar se Asterisk aceita chamada
docker exec asterisk asterisk -rx "core show channels"

# Ver logs
docker logs asterisk | grep "Echo"
```

**Soluções:**
- Verificar se softphone está configurado corretamente
- Verificar codecs (deve usar ulaw ou alaw)
- Verificar NAT settings em sip.conf

---

## 📊 Monitoramento

### Métricas via CLI

```bash
# Chamadas ativas
docker exec asterisk asterisk -rx "core show channels"

# Estatísticas SIP
docker exec asterisk asterisk -rx "sip show channelstats"

# Uptime
docker exec asterisk asterisk -rx "core show uptime"

# Threads
docker exec asterisk asterisk -rx "core show threads"
```

---

## 🔧 Customização

### Adicionar novos usuários SIP

Editar `config/sip.conf`:

```ini
[newuser]
type=friend
context=default
secret=password123
host=dynamic
disallow=all
allow=ulaw
allow=alaw
dtmfmode=rfc2833
nat=force_rport,comedia
```

Restart:
```bash
docker-compose restart asterisk
```

---

### Adicionar novas extensões

Editar `config/extensions.conf`:

```ini
[default]
exten => 200,1,NoOp(New Extension)
 same => n,Answer()
 same => n,Playback(custom-message)
 same => n,Hangup()
```

Reload dialplan:
```bash
docker exec asterisk asterisk -rx "dialplan reload"
```

---

## 📚 Referências

- **Asterisk Docs**: https://docs.asterisk.org/
- **SIP Protocol (RFC 3261)**: https://www.rfc-editor.org/rfc/rfc3261
- **Asterisk ARI**: https://docs.asterisk.org/Asterisk_20_Documentation/API_Documentation/Asterisk_REST_Interface/

---

**Criado:** 2026-01-20
**Autor:** Claude Code
**Versão Asterisk:** 20.x
