# PABX Docker - Asterisk + AI Voice Agent

Sistema de PABX com Asterisk, SoftPhone WebRTC em React e Agente de Conversação com IA.

---

## Visão Macro do Sistema

### Arquitetura Geral

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              INFRAESTRUTURA DE VOZ                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐         ┌─────────────┐         ┌─────────────────────────┐   │
│  │  SoftPhone  │  WebRTC │             │  SIP    │                         │   │
│  │   (React)   │◄───────►│  Asterisk   │◄───────►│     Media Server        │   │
│  │  :3000      │  WSS    │   (PABX)    │  RTP    │     (SIP Bridge)        │   │
│  └─────────────┘  :8189  │   :5160     │ :40000  │                         │   │
│                          └─────────────┘         │  ┌───────────────────┐  │   │
│  ┌─────────────┐                │                │  │ PJSUA2 SIP Stack  │  │   │
│  │  Zoiper /   │     SIP/RTP    │                │  │ VAD (WebRTC)      │  │   │
│  │  Linphone   │◄───────────────┘                │  │ Audio Streaming   │  │   │
│  └─────────────┘                                 │  └───────────────────┘  │   │
│                                                  └───────────┬─────────────┘   │
│                                                              │                 │
│                              WebSocket + ASP Protocol        │                 │
│                              (Audio Session Protocol)        │                 │
│                                                              ▼                 │
│                                                  ┌─────────────────────────┐   │
│                                                  │       AI Agent          │   │
│                                                  │   (Conversation Server) │   │
│                                                  │                         │   │
│                                                  │  ┌───────────────────┐  │   │
│                                                  │  │ Pipeline:         │  │   │
│                                                  │  │  STT → LLM → TTS  │  │   │
│                                                  │  └───────────────────┘  │   │
│                                                  │  ┌───────────────────┐  │   │
│                                                  │  │ Providers:        │  │   │
│                                                  │  │  • Whisper (STT)  │  │   │
│                                                  │  │  • Claude (LLM)   │  │   │
│                                                  │  │  • Kokoro (TTS)   │  │   │
│                                                  │  └───────────────────┘  │   │
│                                                  └─────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### Fluxo de uma Chamada Completa

```
┌────────────┐      ┌──────────┐      ┌──────────────┐      ┌────────────┐
│  Usuário   │      │ Asterisk │      │ Media Server │      │  AI Agent  │
│ (SoftPhone)│      │  (PABX)  │      │ (SIP Bridge) │      │(Conversação)│
└─────┬──────┘      └────┬─────┘      └──────┬───────┘      └─────┬──────┘
      │                  │                   │                    │
      │  1. INVITE       │                   │                    │
      │  (ligar 2000)    │                   │                    │
      │─────────────────►│                   │                    │
      │                  │                   │                    │
      │                  │  2. INVITE        │                    │
      │                  │─────────────────►│                    │
      │                  │                   │                    │
      │                  │  3. 200 OK        │                    │
      │                  │◄─────────────────│                    │
      │                  │                   │                    │
      │  4. 200 OK       │                   │  3a. session.start │
      │◄─────────────────│                   │────────────────────►
      │                  │                   │                    │
      │  5. ACK          │                   │  3b. session.started
      │─────────────────►│                   │◄────────────────────
      │                  │                   │                    │
      │                  │                   │  4. greeting audio │
      │                  │  4a. RTP Audio    │◄────────────────────
      │  4b. RTP Audio   │◄─────────────────│                    │
      │◄─────────────────│                   │                    │
      │                  │                   │                    │
      │ ══════════════ LOOP DE CONVERSAÇÃO ══════════════════════│
      │                  │                   │                    │
      │  5. Fala (RTP)   │                   │                    │
      │─────────────────►│  5a. RTP Audio    │                    │
      │                  │─────────────────►│                    │
      │                  │                   │                    │
      │                  │                   │  5b. audio frames  │
      │                  │                   │  (streaming)       │
      │                  │                   │────────────────────►
      │                  │                   │                    │
      │                  │                   │  5c. VAD detecta   │
      │                  │                   │  fim de fala       │
      │                  │                   │                    │
      │                  │                   │  6. audio.end      │
      │                  │                   │────────────────────►
      │                  │                   │                    │
      │                  │                   │        ┌───────────┤
      │                  │                   │        │ Pipeline: │
      │                  │                   │        │ STT→LLM→TTS
      │                  │                   │        └───────────┤
      │                  │                   │                    │
      │                  │                   │  7. response.start │
      │                  │                   │◄────────────────────
      │                  │                   │                    │
      │                  │                   │  8. audio chunks   │
      │                  │  8a. RTP Audio    │◄────────────────────
      │  8b. RTP Audio   │◄─────────────────│  (streaming)       │
      │◄─────────────────│                   │                    │
      │                  │                   │                    │
      │                  │                   │  9. response.end   │
      │                  │                   │◄────────────────────
      │                  │                   │                    │
      │ ═══════════════ FIM DO LOOP (repete até desligar) ═══════│
      │                  │                   │                    │
      │  10. BYE         │                   │                    │
      │─────────────────►│  10a. BYE         │                    │
      │                  │─────────────────►│  10b. session.end  │
      │                  │                   │────────────────────►
      │                  │                   │                    │
```

---

### Protocolo ASP (Audio Session Protocol)

Protocolo de negociação entre Media Server e AI Agent:

```
┌──────────────┐                              ┌──────────────┐
│ Media Server │                              │   AI Agent   │
│   (Cliente)  │                              │  (Servidor)  │
└──────┬───────┘                              └──────┬───────┘
       │                                             │
       │  1. WebSocket Connect                       │
       │ ───────────────────────────────────────────►│
       │                                             │
       │  2. protocol.capabilities                   │
       │ ◄───────────────────────────────────────────│
       │    {                                        │
       │      version: "1.0.0",                      │
       │      supported_sample_rates: [8000, 16000], │
       │      supported_encodings: ["pcm_s16le"],    │
       │      features: ["barge_in", "streaming_tts"]│
       │    }                                        │
       │                                             │
       │  3. session.start                           │
       │ ───────────────────────────────────────────►│
       │    {                                        │
       │      session_id: "uuid",                    │
       │      audio: { sample_rate: 8000, ... },     │
       │      vad: { silence_threshold_ms: 500, ... }│
       │    }                                        │
       │                                             │
       │  4. session.started                         │
       │ ◄───────────────────────────────────────────│
       │    {                                        │
       │      status: "accepted",                    │
       │      negotiated: { audio: {...}, vad: {...}}│
       │    }                                        │
       │                                             │
       │  ═══════════ SESSÃO ATIVA ══════════════   │
       │                                             │
       │  5. Audio Frames (binário)                  │
       │ ───────────────────────────────────────────►│
       │                                             │
       │  6. audio.end (fim de fala)                 │
       │ ───────────────────────────────────────────►│
       │                                             │
       │  7. response.start                          │
       │ ◄───────────────────────────────────────────│
       │                                             │
       │  8. Audio Frames (resposta)                 │
       │ ◄───────────────────────────────────────────│
       │                                             │
       │  9. response.end                            │
       │ ◄───────────────────────────────────────────│
       │                                             │
       │  10. session.end                            │
       │ ───────────────────────────────────────────►│
       │                                             │
       │  11. session.ended (com estatísticas)       │
       │ ◄───────────────────────────────────────────│
       │                                             │
```

> **Documentação completa:** [docs/ASP_SPECIFICATION.md](docs/ASP_SPECIFICATION.md)

---

### Pipeline de Processamento de Áudio

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           AI AGENT - PIPELINE DE VOZ                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ENTRADA (do Media Server)                                                      │
│  ════════════════════════                                                       │
│                                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                      │
│  │ Audio Frame  │───►│ Audio Buffer │───►│     VAD      │                      │
│  │  (PCM 8kHz)  │    │  (até 60s)   │    │  (WebRTC)    │                      │
│  └──────────────┘    └──────────────┘    └──────┬───────┘                      │
│                                                 │                               │
│                            Detecta fim de fala  │                               │
│                            (audio.end)          ▼                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        PROCESSAMENTO (STT → LLM → TTS)                  │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                         │   │
│  │  ┌────────────────┐     ┌────────────────┐     ┌────────────────┐      │   │
│  │  │      STT       │     │      LLM       │     │      TTS       │      │   │
│  │  │                │     │                │     │                │      │   │
│  │  │ faster-whisper │────►│ Claude/GPT     │────►│ Kokoro/gTTS    │      │   │
│  │  │                │     │                │     │                │      │   │
│  │  │ Audio → Texto  │     │ Texto → Texto  │     │ Texto → Audio  │      │   │
│  │  └────────────────┘     └────────────────┘     └────────┬───────┘      │   │
│  │         │                      │                        │              │   │
│  │         ▼                      ▼                        ▼              │   │
│  │   "Olá, preciso         "Claro! Posso           PCM 8kHz mono        │   │
│  │    de ajuda"             ajudar com..."          (streaming)          │   │
│  │                                                                         │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                 │                               │
│                                                 ▼                               │
│  SAÍDA (para Media Server)                                                      │
│  ═════════════════════════                                                      │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │                       STREAMING DE RESPOSTA                              │  │
│  ├──────────────────────────────────────────────────────────────────────────┤  │
│  │                                                                          │  │
│  │  response.start ──► audio_chunk ──► audio_chunk ──► ... ──► response.end │  │
│  │       │                  │               │                      │        │  │
│  │       ▼                  ▼               ▼                      ▼        │  │
│  │   "Iniciando"      [bytes PCM]     [bytes PCM]            "Completo"     │  │
│  │                                                                          │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐ │
│  │ MÉTRICAS                                                                  │ │
│  │ • TTFB (Time to First Byte): ~300-500ms                                   │ │
│  │ • STT Latency: ~100-300ms (modelo tiny)                                   │ │
│  │ • LLM Latency: ~200-500ms (streaming)                                     │ │
│  │ • TTS Latency: ~100-200ms (primeiro chunk)                                │ │
│  └───────────────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### Barge-In (Interrupção)

O sistema suporta barge-in, permitindo que o usuário interrompa a resposta do agente:

```
┌──────────┐     ┌──────────────┐     ┌────────────┐
│ Usuário  │     │ Media Server │     │  AI Agent  │
└────┬─────┘     └──────┬───────┘     └─────┬──────┘
     │                  │                   │
     │                  │  response.start   │
     │                  │◄──────────────────│
     │                  │                   │
     │  Ouvindo resposta│  audio chunks     │
     │◄─────────────────│◄──────────────────│
     │                  │                   │
     │  INTERROMPE!     │                   │
     │  (começa falar)  │                   │
     │─────────────────►│                   │
     │                  │                   │
     │                  │  VAD detecta fala │
     │                  │  durante playback │
     │                  │                   │
     │                  │  PARA playback    │
     │                  │  imediatamente    │
     │                  │                   │
     │                  │  audio.end        │
     │                  │  (nova fala)      │
     │                  │──────────────────►│
     │                  │                   │
     │                  │  response.start   │
     │                  │  (nova resposta)  │
     │                  │◄──────────────────│
     │                  │                   │
```

---

## Arquitetura Detalhada

```
┌──────────────────────┐    WebSocket     ┌──────────────────────┐
│    Media Server      │◄────────────────►│      AI Agent        │
│    (SIP Bridge)      │  Audio + Control │  (Conversation)      │
├──────────────────────┤                  ├──────────────────────┤
│ • PJSUA2 SIP/RTP     │                  │ • STT (Whisper)      │
│ • Call control       │                  │ • LLM (Claude)       │
│ • Audio capture      │                  │ • TTS (Kokoro)       │
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

## Documentação

| Documento | Descrição |
|-----------|-----------|
| [ASP_SPECIFICATION.md](docs/ASP_SPECIFICATION.md) | Especificação completa do Audio Session Protocol |
| [ASP_PROTOCOL.md](docs/ASP_PROTOCOL.md) | Visão geral e exemplos do protocolo |
| [ASP_INTEGRATION.md](docs/ASP_INTEGRATION.md) | Guia de integração com o ASP |
| [ASP_TROUBLESHOOTING.md](docs/ASP_TROUBLESHOOTING.md) | Diagnóstico de problemas do ASP |
| [SBC-INTEGRATION.md](docs/SBC-INTEGRATION.md) | Integração com Session Border Controller |

### Configuração por Ambiente

| Arquivo | Descrição |
|---------|-----------|
| `ai-agent/.env.example` | Todas as variáveis do AI Agent documentadas |
| `media-server/.env.example` | Todas as variáveis do Media Server documentadas |

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
