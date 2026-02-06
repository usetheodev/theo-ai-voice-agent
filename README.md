# Theo - AI Voice Agent

Agente de voz conversacional com controle de chamadas em tempo real. Integra telefonia SIP/VoIP com pipeline de IA (STT, LLM, TTS) para atendimento automatizado com transferencia assistida.

```
Usuário ──► Asterisk ──► Media Server ──► AI Agent ──► Resposta de voz
           (PABX)    ▲  (SIP Bridge)    (STT→LLM→TTS)
                     │                        │
                     └── AMI Redirect ◄───────┘
                     (Transfer assistida)  (Tool Calling)
```

## Arquitetura

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   ┌──────────┐        ┌──────────┐        ┌─────────────────────────────┐  │
│   │SoftPhone │ WebRTC │          │  SIP   │       Media Server          │  │
│   │ (React)  │◄──────►│ Asterisk │◄──────►│       (SIP Bridge)          │  │
│   └──────────┘  WSS   │  (PABX)  │  RTP   │                             │  │
│                       │          │        │  ┌─────────────────────┐    │  │
│   ┌──────────┐  SIP   │          │◄──AMI──│  │ PJSUA2 + AMI Client│    │  │
│   │ Zoiper / │◄──────►│          │Redirect│  └─────────────────────┘    │  │
│   │ Linphone │  RTP   └──────────┘        └────────────┬────────────────┘  │
│   └──────────┘                                         │                   │
│                                          WebSocket + ASP Protocol          │
│                                                        │                   │
│                            ┌───────────────────────────┼───────────────┐   │
│                            │                           ▼               │   │
│                            │  ┌─────────────────────────────────────┐  │   │
│                            │  │            AI Agent                 │  │   │
│                            │  │                                     │  │   │
│                            │  │   ┌─────┐   ┌─────┐   ┌─────┐      │  │   │
│                            │  │   │ STT │──►│ LLM │──►│ TTS │      │  │   │
│                            │  │   └─────┘   └─────┘   └─────┘      │  │   │
│                            │  │                  │                   │  │   │
│                            │  │  Providers:      │ Tool Calling      │  │   │
│                            │  │  • FasterWhisper  │ • transfer_call   │  │   │
│                            │  │  • Claude / GPT   │ • end_call        │  │   │
│                            │  │  • Kokoro / gTTS  ▼                   │  │   │
│                            │  │              CallActionMessage ──────►│  │   │
│                            │  └─────────────────────────────────────┘  │   │
│                            │                                           │   │
│                            │  ┌─────────────────────────────────────┐  │   │
│                            │  │         AI Transcribe               │  │   │
│                            │  │   (Transcrição → Elasticsearch)     │  │   │
│                            │  └─────────────────────────────────────┘  │   │
│                            │                                           │   │
│                            └───────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Componentes

| Componente | Descrição | Porta |
|------------|-----------|-------|
| **Asterisk** | PABX SIP com WebRTC e AMI | 5160 (SIP), 8189 (WSS), 5038 (AMI) |
| **Media Server** | Bridge SIP↔WebSocket + AMI Client | 40000-40100 (RTP) |
| **AI Agent** | Pipeline STT→LLM→TTS + Tool Calling | 8765 (WS), 9090 (metrics) |
| **AI Transcribe** | Transcrição em tempo real para Elasticsearch | 8766 (WS), 9093 (metrics) |
| **SoftPhone** | Cliente WebRTC em React | 3000 |
| **Elasticsearch** | Armazenamento de transcrições | 9200 |
| **Kibana** | Visualização de transcrições | 5601 |
| **Prometheus** | Coleta de métricas | 9092 |
| **Grafana** | Dashboards de métricas | 3000 |

## Início Rápido

### 1. Configurar ambiente

```bash
# Copiar configuração do AI Agent
cp ai-agent/.env.example ai-agent/.env

# Editar com sua API key (Anthropic ou OpenAI)
nano ai-agent/.env
```

**Configuração mínima** (`ai-agent/.env`):
```bash
# LLM - escolha um:
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Ou use LLM local (sem API key):
# LLM_PROVIDER=local
# LOCAL_LLM_MODEL=ai/smollm3
```

### 2. Iniciar sistema

```bash
./start.sh                    # Sistema básico
./start.sh --transcribe       # Com transcrição (Elasticsearch)
./start.sh --debug            # Com Kibana e debug tools
./start.sh --transcribe --debug  # Tudo habilitado
```

### 3. Testar

1. **SoftPhone WebRTC**: `cd softphone && npm install && npm run dev`
2. Acesse https://localhost:3000
3. Conecte com ramal **1004** (senha: `xe9JDXRiUeK2848Uvoz1`)
4. Ligue para **2000** (Agente IA)

## Scripts

### Resumo

| Script | Descrição |
|--------|-----------|
| `./start.sh` | Iniciar sistema |
| `./stop.sh` | Parar todos os containers |
| `./restart.sh` | Reiniciar serviços |
| `./status.sh` | Ver status dos serviços |
| `./logs.sh` | Ver logs dos serviços |
| `./local-llm.sh` | Configurar LLM local |

---

### start.sh

Inicia o sistema completo.

```bash
# Uso
./start.sh [opções]

# Opções
--transcribe    Habilita transcrição em tempo real (Elasticsearch)
--debug         Inicia com Kibana e ferramentas de debug
--help          Mostra ajuda
```

**Exemplos:**

```bash
# Iniciar sistema básico (Asterisk + Media Server + AI Agent)
./start.sh

# Iniciar com transcrição habilitada
./start.sh --transcribe

# Iniciar com ferramentas de debug (Kibana)
./start.sh --debug

# Iniciar com tudo habilitado
./start.sh --transcribe --debug
```

---

### stop.sh

Para todos os containers.

```bash
# Uso
./stop.sh
```

**Exemplo:**

```bash
# Parar todo o sistema
./stop.sh
```

---

### restart.sh

Reinicia serviços com opções de rebuild.

```bash
# Uso
./restart.sh [serviço] [opções]

# Serviços disponíveis
ai-agent        Reinicia apenas o AI Agent
media-server    Reinicia apenas o Media Server
ai-transcribe   Reinicia apenas o AI Transcribe
asterisk        Reinicia apenas o Asterisk
elasticsearch   Reinicia apenas o Elasticsearch
prometheus      Reinicia apenas o Prometheus
grafana         Reinicia apenas o Grafana

# Opções
--build         Rebuild da imagem antes de reiniciar
--transcribe    Habilita transcrição (TRANSCRIBE_ENABLED=true)
--help          Mostra ajuda
```

**Exemplos:**

```bash
# Restart completo (todos os serviços)
./restart.sh

# Restart apenas do AI Agent
./restart.sh ai-agent

# Restart do AI Agent com rebuild da imagem
./restart.sh ai-agent --build

# Restart completo com rebuild de todas as imagens
./restart.sh --build

# Restart com transcrição habilitada
./restart.sh --transcribe

# Restart do Media Server com rebuild
./restart.sh media-server --build
```

---

### status.sh

Mostra o status de todos os serviços.

```bash
# Uso
./status.sh
```

**Exemplo:**

```bash
# Ver status de todos os containers
./status.sh
```

**Saída esperada:**
```
CONTAINER              STATUS          PORTS
asterisk-pabx          Up 2 hours      5160/udp, 8189/tcp
ai-conversation-agent  Up 2 hours      8765/tcp, 9090/tcp
sip-media-server       Up 2 hours      40000-40100/udp
elasticsearch          Up 2 hours      9200/tcp
```

---

### logs.sh

Visualiza logs dos serviços.

```bash
# Uso
./logs.sh [serviço] [opções]

# Serviços disponíveis
ai-agent        Logs do AI Agent
media-server    Logs do Media Server
ai-transcribe   Logs do AI Transcribe
asterisk        Logs do Asterisk
elasticsearch   Logs do Elasticsearch
all             Todos os serviços (padrão)
```

**Exemplos:**

```bash
# Ver logs de todos os serviços (follow mode)
./logs.sh

# Ver logs apenas do AI Agent
./logs.sh ai-agent

# Ver logs do Media Server
./logs.sh media-server

# Ver logs do Asterisk
./logs.sh asterisk

# Ver logs do AI Transcribe
./logs.sh ai-transcribe
```

---

### local-llm.sh

Configura LLM local usando Docker Model Runner.

```bash
# Uso
./local-llm.sh [comando] [modelo]

# Comandos
setup [modelo]      Setup completo (download + configuração)
check               Verifica se Model Runner está disponível
enable              Habilita Model Runner
download [modelo]   Baixa um modelo
list                Lista modelos instalados
models              Lista modelos disponíveis para download
test [modelo]       Testa um modelo
configure [modelo]  Configura .env para usar modelo local
--help              Mostra ajuda
```

**Exemplos:**

```bash
# Setup completo com modelo padrão (smollm3)
./local-llm.sh setup

# Setup com modelo específico
./local-llm.sh setup phi4

# Ver modelos disponíveis para download
./local-llm.sh models

# Ver modelos já instalados
./local-llm.sh list

# Baixar modelo específico
./local-llm.sh download qwen3

# Testar modelo instalado
./local-llm.sh test ai/smollm3

# Apenas configurar .env (sem baixar)
./local-llm.sh configure ai/phi4

# Verificar se Model Runner está disponível
./local-llm.sh check

# Habilitar Model Runner
./local-llm.sh enable
```

---

### Fluxos Comuns

**Primeira execução:**
```bash
# 1. Configurar ambiente
cp ai-agent/.env.example ai-agent/.env
nano ai-agent/.env  # Adicionar ANTHROPIC_API_KEY

# 2. Iniciar sistema
./start.sh

# 3. Verificar status
./status.sh
```

**Desenvolvimento (com rebuild):**
```bash
# Alterar código e reiniciar com rebuild
./restart.sh ai-agent --build
```

**Debug de problemas:**
```bash
# Ver logs em tempo real
./logs.sh ai-agent

# Iniciar com ferramentas de debug
./stop.sh
./start.sh --debug
```

**Usar LLM local (sem API key):**
```bash
# 1. Setup do LLM local
./local-llm.sh setup

# 2. Reiniciar AI Agent
./restart.sh ai-agent
```

**Habilitar transcrição:**
```bash
# Reiniciar com transcrição
./restart.sh --transcribe

# Ou iniciar do zero
./stop.sh
./start.sh --transcribe
```

---

## Providers Disponíveis

### STT (Speech-to-Text)

| Provider | Descrição | Configuração |
|----------|-----------|--------------|
| **faster-whisper** | Whisper otimizado, roda local (Recomendado) | `ASR_PROVIDER=faster-whisper` |
| whisper | Whisper original | `ASR_PROVIDER=whisper` |
| openai | API OpenAI Whisper | `ASR_PROVIDER=openai` + `OPENAI_API_KEY` |

### LLM (Large Language Model)

| Provider | Descrição | Configuração |
|----------|-----------|--------------|
| **anthropic** | Claude (Recomendado para qualidade) | `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` |
| openai | GPT | `LLM_PROVIDER=openai` + `OPENAI_API_KEY` |
| **local** | Docker Model Runner / vLLM / Ollama (Recomendado para latência) | `LLM_PROVIDER=local` |

### TTS (Text-to-Speech)

| Provider | Descrição | Configuração |
|----------|-----------|--------------|
| **kokoro** | Neural local, alta qualidade (Recomendado) | `TTS_PROVIDER=kokoro` |
| gtts | Google TTS gratuito | `TTS_PROVIDER=gtts` |
| openai | OpenAI TTS | `TTS_PROVIDER=openai` + `OPENAI_API_KEY` |

## LLM Local (Zero Latência de Rede)

Configure um LLM local para eliminar latência de rede e custo de API:

```bash
# Setup completo com modelo recomendado (smollm3)
./local-llm.sh setup

# Ou escolha outro modelo
./local-llm.sh setup phi4

# Ver modelos disponíveis
./local-llm.sh models
```

**Modelos disponíveis:**

| Modelo | Params | Descrição |
|--------|--------|-----------|
| smollm3 | 3.1B | Chat eficiente (Recomendado) |
| functiongemma | 270M | Mais rápido, function-calling |
| phi4 | ~3B | Raciocínio compacto |
| qwen3 | 4-72B | Alta qualidade |

## Ramais

| Ramal | Tipo | Descrição |
|-------|------|-----------|
| 1001-1003 | SIP UDP | Softphones tradicionais (Zoiper, Linphone) |
| 1004-1005 | WebRTC WSS | SoftPhone React |
| **2000** | SIP UDP | **Agente IA** |

## Protocolo ASP (Audio Session Protocol)

Protocolo de comunicação entre Media Server e AI Agent:

```
Media Server                              AI Agent
     │                                        │
     │──────── WebSocket Connect ────────────►│
     │                                        │
     │◄─────── protocol.capabilities ─────────│
     │                                        │
     │──────── session.start ────────────────►│
     │◄─────── session.started ──────────────│
     │                                        │
     │══════════ SESSÃO ATIVA ═══════════════│
     │                                        │
     │──────── audio frames (binary) ────────►│
     │──────── audio.end ────────────────────►│
     │                                        │
     │◄─────── response.start ───────────────│
     │◄─────── audio chunks ─────────────────│
     │◄─────── response.end ─────────────────│
     │◄─────── call.action (transfer/hangup)─│  ← NEW
     │                                        │
     │──────── session.end ──────────────────►│
     │◄─────── session.ended ────────────────│
```

**Documentação completa:** [docs/ASP_SPECIFICATION.md](docs/ASP_SPECIFICATION.md)

## Transferencia Assistida de Chamadas

O agente de voz pode controlar chamadas em tempo real durante a conversa. Quando o LLM decide que o cliente precisa ser transferido, o sistema executa automaticamente via AMI (Asterisk Manager Interface).

### Fluxo

```
1. Caller liga para 2000 (AI Agent)
2. Agente conversa normalmente (pipeline STT → LLM → TTS intacto)
3. LLM decide transferir: diz "Vou transferir para o suporte"
   + tool_call: transfer_call("suporte")
4. AI Agent envia CallActionMessage via ASP Protocol
5. Media Server aguarda playback terminar (caller ouve frase completa)
6. Media Server executa AMI Redirect para contexto [transfer-assistida]
7. Asterisk move caller: MOH → Dial destino → Conecta
8. Se destino nao atende → fallback automatico para AI Agent
```

### Tools disponiveis para o LLM

| Tool | Descricao | Exemplo |
|------|-----------|---------|
| `transfer_call` | Transfere para departamento ou ramal | `transfer_call("suporte")` ou `transfer_call("1001")` |
| `end_call` | Encerra a chamada | `end_call("conversa finalizada")` |

### Departamentos

Configuraveis via variavel de ambiente `DEPARTMENT_MAP` no AI Agent:

```bash
# Formato: "nome:ramal,nome:ramal"
DEPARTMENT_MAP="suporte:1001,vendas:1002,financeiro:1003"
```

O LLM pode usar nomes de departamento (`suporte`) ou ramais diretos (`1001`).

### Separacao de Concerns

```
Camada          | Sabe                         | NAO sabe
----------------|------------------------------|---------------------------
LLM             | transfer_call("suporte")     | channel names, AMI, SIP
AI Agent        | tool call → ASP call.action  | como executar transfer
Media Server    | AMI Redirect + caller_channel| por que a IA decidiu isso
Asterisk        | dialplan + bridge + MOH      | que existe IA no sistema
```

### Fallback automatico

Se o destino da transferencia nao atender (timeout de 30s), o Asterisk redireciona o caller de volta para o AI Agent (ramal 2000), iniciando nova sessao de conversa.

### Decisao Arquitetural

A transferencia usa **AMI** ao inves de ARI para preservar o pipeline existente (Media Fork Manager, streaming ports, barge-in, VAD). Documentacao: [ADR-001](docs/adr/ADR-001-call-control-ami-over-ari.md)

## Estrutura do Projeto

```
theo-ai-voice-agent/
├── ai-agent/                  # Servidor de conversação IA
│   ├── providers/             # STT, LLM, TTS providers
│   │   ├── stt.py            # FasterWhisper, Whisper, OpenAI
│   │   ├── llm.py            # Claude, GPT, Local (+Tool Calling)
│   │   └── tts.py            # Kokoro, gTTS, OpenAI
│   ├── pipeline/              # Pipeline STT→LLM→TTS
│   ├── server/                # WebSocket server
│   ├── tools/                 # LLM tools (transfer_call, end_call)
│   └── config.py              # Configurações
│
├── media-server/              # Bridge SIP ↔ WebSocket
│   ├── sip/                   # PJSUA2 SIP handling
│   ├── ami/                   # AMI client (transfer, hangup)
│   ├── ws/                    # WebSocket client + ASP
│   ├── core/                  # Media fork manager
│   └── adapters/              # AI Agent + Transcribe adapters
│
├── ai-transcribe/             # Transcrição em tempo real
│   ├── transcriber/           # FasterWhisper STT
│   ├── indexer/               # Elasticsearch client
│   └── server/                # WebSocket server
│
├── shared/                    # Código compartilhado
│   ├── asp_protocol/          # Protocolo ASP
│   ├── ws/                    # Protocolo WebSocket
│   └── shared_config/         # Utilitários de config
│
├── asterisk/                  # Configurações Asterisk
│   ├── config/                # pjsip.conf, extensions.conf, manager.conf
│   └── sounds/                # Áudios customizados
│
├── softphone/                 # SoftPhone React WebRTC
│
├── observability/             # Monitoramento
│   ├── prometheus/            # Métricas
│   ├── grafana/               # Dashboards
│   └── kibana/                # Transcrições
│
├── docker-compose.yml         # Orquestração de containers
├── start.sh                   # Script de inicialização
└── local-llm.sh              # Setup de LLM local
```

## Observabilidade

### Métricas (Prometheus + Grafana)

- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9092

Métricas disponíveis:
- Latência STT/LLM/TTS
- Sessões ativas
- Erros por tipo
- Uso de recursos

### Transcrições (Elasticsearch + Kibana)

- **Kibana**: http://localhost:5601
- **Elasticsearch**: http://localhost:9200

```bash
# Ver transcrições recentes
curl 'http://localhost:9200/voice-transcriptions-*/_search?pretty'
```

## Configuração Avançada

### Variáveis de Ambiente

Cada componente tem seu `.env.example` documentado:

- `ai-agent/.env.example` - STT, LLM, TTS, VAD, Pipeline, Tool Calling
- `media-server/.env.example` - SIP, Audio, VAD, ASP, AMI
- `ai-transcribe/.env.example` - STT, Elasticsearch

#### Variaveis AMI (Media Server)

| Variavel | Default | Descricao |
|----------|---------|-----------|
| `AMI_HOST` | `asterisk-pabx` | Host do Asterisk (AMI) |
| `AMI_PORT` | `5038` | Porta AMI |
| `AMI_USERNAME` | `media-server` | Usuario AMI |
| `AMI_SECRET` | *(requerido)* | Senha AMI (definida em manager.conf) |
| `AMI_ENABLED` | `true` | Habilitar AMI (false desabilita transfer) |
| `AMI_TIMEOUT` | `5.0` | Timeout para operacoes AMI (segundos) |

#### Variaveis de Tool Calling (AI Agent)

| Variavel | Default | Descricao |
|----------|---------|-----------|
| `DEPARTMENT_MAP` | `suporte:1001,vendas:1002,financeiro:1003` | Mapeamento departamento:ramal |

### Integração SBC

Para receber chamadas de um Session Border Controller externo:

```bash
./scripts/validate-sbc.sh [IP_DO_SBC]
```

Documentação: [docs/SBC-INTEGRATION.md](docs/SBC-INTEGRATION.md)

## Troubleshooting

### Logs

```bash
./logs.sh              # Todos os serviços
./logs.sh ai-agent     # Apenas AI Agent
./logs.sh media-server # Apenas Media Server
```

### CLI Asterisk

```bash
docker exec -it asterisk-pabx asterisk -rvvv

# Comandos úteis
pjsip show endpoints      # Ver ramais registrados
pjsip show registrations  # Ver registros ativos
core show channels        # Ver chamadas em andamento
```

### Problemas Comuns

| Problema | Solução |
|----------|---------|
| WebRTC não conecta | Verificar HTTPS e aceitar certificado |
| Sem áudio | Verificar portas RTP (40000-40100) no firewall |
| Ramal não registra | `docker exec asterisk-pabx asterisk -rx "pjsip set logger on"` |
| LLM lento | Usar `LLM_PROVIDER=local` com `./local-llm.sh setup` |

## Documentação

| Documento | Descrição |
|-----------|-----------|
| [ADR-001: AMI over ARI](docs/adr/ADR-001-call-control-ami-over-ari.md) | Decisao arquitetural: controle de chamadas via AMI |
| [PLAN-001: Call Transfer](docs/adr/PLAN-001-call-transfer-implementation.md) | Plano de implementacao da transferencia assistida |
| [ASP_SPECIFICATION.md](docs/ASP_SPECIFICATION.md) | Especificação do protocolo ASP |
| [ASP_PROTOCOL.md](docs/ASP_PROTOCOL.md) | Visão geral e exemplos |
| [ASP_INTEGRATION.md](docs/ASP_INTEGRATION.md) | Guia de integração |
| [ASP_TROUBLESHOOTING.md](docs/ASP_TROUBLESHOOTING.md) | Diagnóstico de problemas |
| [SBC-INTEGRATION.md](docs/SBC-INTEGRATION.md) | Integração com SBC |
| [ASTERISK_CONFIG.md](docs/ASTERISK_CONFIG.md) | Configuração do Asterisk |

## Requisitos

- Docker e Docker Compose
- 4GB+ RAM (8GB recomendado para LLM local)
- Portas: 5160 (SIP), 8765 (WS), 40000-40100 (RTP)

## Licença

MIT
