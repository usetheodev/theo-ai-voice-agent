# Voice Pipeline WebRTC Demo

Uma aplicacao web profissional que demonstra todas as funcionalidades do voice-pipeline framework usando WebRTC para comunicacao de audio em tempo real.

## Funcionalidades

- **Audio bidirecional via WebRTC** - Comunicacao de audio em tempo real entre browser e servidor
- **Streaming de tokens em tempo real** - Visualizacao dos tokens do LLM conforme sao gerados
- **Memoria episodica** - Persistencia de contexto entre conversas
- **Execucao de ferramentas com feedback** - Ferramentas executam com feedback verbal
- **Sistema de permissoes** - Controle de acesso para ferramentas sensiveis
- **Cliente MCP** - Integracao com servidores MCP para ferramentas externas
- **Visualizacao de audio** - Waveform em tempo real
- **Metricas de latencia** - TTFA, TTFT, E2E exibidos no dashboard

## Arquitetura

```
Frontend (React + TypeScript)          Backend (FastAPI + aiortc)
┌─────────────────────────────┐       ┌─────────────────────────────┐
│  Dashboard                   │       │  WebRTC Transport Layer     │
│  ┌────────┐ ┌────────┐     │       │                             │
│  │ Audio  │ │ Chat   │     │       │  Audio → VAD → ASR → LLM → │
│  │ Viz    │ │ Panel  │     │       │  AgentLoop → TTS → Audio    │
│  └────────┘ └────────┘     │       │                             │
│  ┌────────┐ ┌────────┐     │       │  ┌─────────┐ ┌─────────┐   │
│  │ Tool   │ │Memory  │     │       │  │ Tools   │ │ Memory  │   │
│  │ Panel  │ │ Panel  │     │       │  └─────────┘ └─────────┘   │
│  └────────┘ └────────┘     │       │                             │
│                             │       │                             │
│  WebRTC + DataChannel       │◄─────►│  WebRTC + DataChannel       │
└─────────────────────────────┘       └─────────────────────────────┘
```

## Requisitos

- Python 3.10+
- Node.js 18+
- Navegador com suporte a WebRTC (Chrome, Firefox, Safari, Edge)

## Instalacao Rapida

```bash
# Clone o repositorio (se ainda nao tiver)
cd libs/voice-pipeline/examples/webapp-webrtc

# Execute o script de inicializacao
./run.sh
```

O script ira:
1. Criar um ambiente virtual Python
2. Instalar dependencias do backend
3. Instalar dependencias do frontend
4. Iniciar ambos os servidores

Acesse http://localhost:5173 no navegador.

## Instalacao Manual

### Backend

```bash
cd backend

# Criar ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

# Instalar dependencias
pip install -r ../requirements.txt

# Instalar voice-pipeline (do diretorio pai)
pip install -e ../../..

# Executar servidor
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend

# Instalar dependencias
npm install

# Executar servidor de desenvolvimento
npm run dev
```

## Configuracao

Crie um arquivo `.env` no diretorio raiz:

```env
# LLM Provider
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=your-api-key

# Ou use Ollama
# LLM_PROVIDER=ollama
# LLM_MODEL=llama2

# TTS
TTS_PROVIDER=kokoro
TTS_VOICE=af_bella

# ASR
ASR_PROVIDER=faster-whisper
ASR_MODEL=base
ASR_LANGUAGE=pt

# Memory
MEMORY_ENABLED=true
MEMORY_STORE_PATH=./episodes

# Server
HOST=0.0.0.0
PORT=8000
DEBUG=false
```

## Endpoints da API

### REST

| Endpoint | Metodo | Descricao |
|----------|--------|-----------|
| `/api/health` | GET | Health check |
| `/api/config` | GET | Configuracao publica |
| `/api/sessions` | GET | Lista sessoes ativas |
| `/api/sessions/{id}` | GET | Detalhes da sessao |
| `/api/sessions/{id}` | DELETE | Encerra sessao |
| `/api/sessions/{id}/interrupt` | POST | Interrompe resposta |
| `/api/tools` | GET | Lista ferramentas |
| `/api/mcp/connect` | POST | Conecta servidor MCP |
| `/api/mcp/servers` | GET | Lista servidores MCP |

### WebSocket

| Endpoint | Descricao |
|----------|-----------|
| `/ws/signaling` | WebRTC signaling |

## Eventos do DataChannel

Eventos enviados do backend para o frontend via DataChannel (msgpack):

| Evento | Dados | Descricao |
|--------|-------|-----------|
| `connected` | `{state}` | Conexao estabelecida |
| `vad_start` | `{timestamp}` | Inicio da fala detectado |
| `vad_end` | `{timestamp, duration_ms}` | Fim da fala |
| `asr_final` | `{text}` | Transcricao final |
| `llm_token` | `{token}` | Token do LLM |
| `tts_start` | `{timestamp}` | Inicio da sintese |
| `tool_call` | `{name, args}` | Ferramenta chamada |
| `tool_result` | `{name, result}` | Resultado da ferramenta |
| `tool_feedback` | `{tool, phrase}` | Feedback verbal |
| `memory_recall` | `{query, episodes}` | Episodios recuperados |
| `metrics` | `{turn_count, latency}` | Metricas de latencia |

## Ferramentas Demo

O backend inclui ferramentas de demonstracao:

- `get_current_time` - Obter hora atual
- `get_weather` - Clima de uma cidade (simulado)
- `web_search` - Busca na web (simulado)
- `calculate` - Calculadora matematica
- `set_reminder` - Definir lembrete (simulado)
- `translate` - Traducao (simulado)
- `get_news` - Noticias (simulado)

## Testes

```bash
# Backend
cd backend
pytest ../tests/ -v

# Frontend
cd frontend
npm run lint
```

## Estrutura de Arquivos

```
webapp-webrtc/
├── README.md
├── requirements.txt
├── run.sh
├── backend/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Configuracao
│   ├── webrtc/
│   │   ├── transport.py     # WebRTCTransport
│   │   ├── signaling.py     # WebSocket signaling
│   │   ├── tracks.py        # Audio tracks
│   │   └── events.py        # DataChannel events
│   ├── agent/
│   │   ├── session.py       # VoiceAgentSession
│   │   └── integration.py   # AgentLoop integration
│   └── features/
│       ├── demo_tools.py    # Demo tools
│       └── mcp_wrapper.py   # MCP integration
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── AudioVisualizer.tsx
│   │   │   ├── ChatPanel.tsx
│   │   │   ├── ToolPanel.tsx
│   │   │   ├── MemoryPanel.tsx
│   │   │   └── ...
│   │   └── hooks/
│   │       ├── useWebRTC.ts
│   │       └── useAgentState.ts
│   └── ...
└── tests/
    ├── test_webrtc_transport.py
    └── test_integration.py
```

## Troubleshooting

### Erro de CORS
Se encontrar erros de CORS, verifique se o backend esta rodando na porta 8000 e o frontend na 5173.

### Microfone nao detectado
- Verifique as permissoes do navegador
- Certifique-se de estar usando HTTPS ou localhost

### Conexao WebRTC falha
- Verifique se nao ha firewall bloqueando
- Tente usar apenas servidores STUN publicos

### Audio nao reproduz
- Verifique se o volume nao esta mudo
- Alguns navegadores requerem interacao do usuario antes de reproduzir audio

## Licenca

MIT
