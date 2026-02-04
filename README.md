# PABX Docker - Asterisk + AI Voice Agent

Sistema de PABX com Asterisk, SoftPhone WebRTC em React e Agente de Conversação com IA.

## Arquitetura

```
┌──────────────────────┐    WebSocket     ┌──────────────────────┐
│    Media Server      │◄────────────────►│      AI Agent        │
│    (SIP Bridge)      │  Audio + Control │  (Conversation)      │
├──────────────────────┤                  ├──────────────────────┤
│ • PJSUA2 SIP/RTP     │                  │ • STT (Whisper)      │
│ • Call control       │                  │ • LLM (Claude)       │
│ • Audio capture      │                  │ • TTS (gTTS)         │
│ • Audio playback     │                  │ • VAD                │
│ • WS Client          │                  │ • Session Manager    │
└──────────────────────┘                  └──────────────────────┘
         ▲
         │ SIP/RTP
         ▼
   ┌───────────┐         ┌───────────────┐
   │ Asterisk  │◄───────►│  SoftPhone    │
   │  (PABX)   │         │  (WebRTC)     │
   └───────────┘         └───────────────┘
```

## Estrutura de Diretórios

```
pabx-docker/
├── docker-compose.yml
├── asterisk/
│   ├── config/
│   │   ├── pjsip.conf      # Configuração SIP/WebRTC
│   │   ├── extensions.conf # Dialplan com URA
│   │   ├── http.conf       # WebSocket para WebRTC
│   │   ├── rtp.conf        # Configuração RTP
│   │   └── modules.conf    # Módulos do Asterisk
│   └── sounds/             # Áudios customizados da URA
├── media-server/           # Bridge SIP ↔ WebSocket
│   ├── sip/                # PJSUA2 SIP handling
│   └── ws/                 # WebSocket client
├── ai-agent/               # Servidor de Conversação IA
│   ├── server/             # WebSocket server
│   ├── pipeline/           # STT → LLM → TTS
│   └── providers/          # Whisper, Claude, gTTS
└── softphone/              # SoftPhone React WebRTC
```

## Ramais Configurados

| Ramal | Senha                | Transporte        | Descrição           |
|-------|----------------------|-------------------|---------------------|
| 1001  | FRGQib50A3gZQSl1NSen | UDP :5160         | Ramal SIP padrão    |
| 1002  | jaFViIPZkzejvgHczIFE | UDP :5160         | Ramal SIP padrão    |
| 1003  | axkCUAmMk2FyI1NJpLSF | UDP :5160         | Ramal SIP padrão    |
| 1004  | xe9JDXRiUeK2848Uvoz1 | WSS :8189 (WebRTC)| SoftPhone React     |
| 1005  | d9nHiKsFcKXmj9tS0NXd | WSS :8189 (WebRTC)| SoftPhone React     |
| 2000  | 7Wslll0Hlc6BCOv4jF51 | UDP :5160         | Agente IA           |

### Configuração por Tipo de Cliente

**WebRTC (Browser/SoftPhone React):**
- URL WebSocket: `wss://SEU_IP:8189/ws`
- Use ramal **1004** ou **1005**

**SIP Tradicional (Zoiper, Linphone, etc.):**
- Servidor: `SEU_IP:5160`
- Use ramal **1001**, **1002** ou **1003**

**Agente IA:**
- Ramal **2000** - atendimento automático com IA

## Códigos de Acesso

| Código | Função                    |
|--------|---------------------------|
| 9      | Acessar URA               |
| *43    | Teste de eco              |
| *60    | Hora certa                |
| 8000   | Sala de conferência       |

## URA - Menu

- **1** - Falar com Operador (ramal 1001)
- **2** - Falar com Suporte (ramal 1002)
- **3** - Discar ramal diretamente
- **0** - Repetir menu

## Início Rápido

### 1. Configurar variáveis de ambiente

```bash
# Copiar arquivo de exemplo
cp ai-agent/.env.example ai-agent/.env

# Editar com sua chave da Anthropic
nano ai-agent/.env
```

Variáveis necessárias no `ai-agent/.env`:
```bash
ANTHROPIC_API_KEY=sk-ant-...  # Obrigatório
STT_PROVIDER=whisper_local
STT_MODEL=base
TTS_PROVIDER=gtts
TTS_LANG=pt
```

### 2. Iniciar todos os serviços

```bash
docker compose up -d
```

Isso inicia:
- **asterisk** - PABX SIP
- **coturn** - TURN server para WebRTC
- **ai-agent** - Servidor de conversação IA
- **media-server** - Bridge SIP ↔ WebSocket

### 3. Verificar se está rodando

```bash
# Ver logs de todos os serviços
docker compose logs -f

# Ver logs específicos
docker logs -f ai-conversation-agent
docker logs -f sip-media-server

# Acessar CLI do Asterisk
docker exec -it asterisk-pabx asterisk -rvvv

# Verificar ramais registrados
docker exec -it asterisk-pabx asterisk -rx "pjsip show endpoints"
```

### 4. Iniciar o SoftPhone React (opcional)

```bash
cd softphone
npm install
npm run dev
```

Acesse: https://localhost:3000

**Nota:** Use HTTPS para WebRTC funcionar. O navegador pode alertar sobre certificado autoassinado.

### 5. Testar o Agente IA

1. Registre um softphone (ramal 1001-1003) ou use o SoftPhone React (1004-1005)
2. Ligue para o ramal **2000**
3. O agente IA irá atender e você pode conversar com ele

## Testar com SoftPhone Tradicional

Use qualquer softphone SIP (Zoiper, Linphone, MicroSIP):

- **Servidor:** IP da sua máquina
- **Porta:** 5160 (UDP)
- **Usuário:** 1001
- **Senha:** FRGQib50A3gZQSl1NSen

Para testar o Agente IA, ligue para o ramal **2000**.

## Portas Utilizadas

| Porta       | Protocolo | Serviço                     |
|-------------|-----------|------------------------------|
| 5160        | UDP       | SIP (Asterisk)               |
| 8189        | TCP       | WSS (WebRTC via Odin/SRTP)   |
| 8765        | TCP       | WebSocket (AI Agent interno) |
| 9090        | TCP       | Prometheus Metrics           |
| 9091        | TCP       | Media Server Metrics         |
| 10000-10100 | UDP       | RTP (áudio)                  |
| 40000-40100 | UDP       | RTP (Media Server)           |

## Adicionar Novos Ramais

Edite `asterisk/config/pjsip.conf` e adicione:

```ini
;-- Ramal 1006 --
[1006](endpoint-base)  ; Use webrtc-base para WebRTC
auth=1006-auth
aors=1006-aor
callerid="Ramal 1006" <1006>

[1006-auth](auth-base)
username=1006
password=suasenha123

[1006-aor](aor-base)
```

Depois recarregue:

```bash
docker exec -it asterisk-pabx asterisk -rx "pjsip reload"
```

## Adicionar Áudios da URA

1. Coloque os arquivos `.wav` ou `.gsm` em `asterisk/sounds/`
2. Os áudios devem estar no formato:
   - WAV: 8kHz, 16-bit, mono
   - GSM: 8kHz, mono

Converter com ffmpeg:
```bash
ffmpeg -i audio.mp3 -ar 8000 -ac 1 -acodec pcm_s16le asterisk/sounds/audio.wav
```

3. Reinicie o Asterisk:
```bash
docker-compose restart asterisk
```

## Integração com SBC (Session Border Controller)

O sistema suporta receber chamadas de um SBC externo via NLB.

**Fluxo:**
```
PSTN → SBC (externo) → NLB → Asterisk → Media Server → AI Agent
```

### Documentação

Consulte [docs/SBC-INTEGRATION.md](docs/SBC-INTEGRATION.md) para:
- Configuração completa do trunk SBC
- Ajustes no dialplan
- Configuração do NLB
- Troubleshooting

### Arquivos de Exemplo

| Arquivo | Descrição |
|---------|-----------|
| `asterisk/config/pjsip-sbc.conf.example` | Configuração do trunk SBC |
| `asterisk/config/extensions-sbc.conf.example` | Dialplan para chamadas do SBC |
| `asterisk/config/rtp-sbc.conf.example` | RTP otimizado para SBC |

### Validação

```bash
# Verificar se o sistema está pronto para SBC
./scripts/validate-sbc.sh [IP_DO_SBC]
```

---

## Troubleshooting

### WebRTC não conecta

1. Verifique se está usando HTTPS
2. Aceite o certificado autoassinado no navegador
3. Verifique se as portas estão abertas no firewall

### Sem áudio

1. Verifique se as portas RTP (10000-10100) estão abertas
2. Verifique permissões do microfone no navegador
3. Use `network_mode: host` no docker-compose (já configurado)

### Ramal não registra

```bash
# Ver logs de registro
docker exec -it asterisk-pabx asterisk -rx "pjsip set logger on"
docker exec -it asterisk-pabx asterisk -rx "pjsip show registrations"
```
