# AI Inference Service - Arquitetura Técnica

> Documento técnico para implementação de um Voice Agent de baixa latência compatível com OpenAI Realtime API.

---

## 1. Visão Geral do Sistema

O AI Inference Service é um servidor de inferência de voz em tempo real que recebe áudio, processa com ASR/LLM/TTS, e retorna áudio sintetizado. O sistema é compatível com a OpenAI Realtime API e suporta dois transportes: **WebSocket** e **WebRTC**.

### 1.1 Objetivo de Latência

| Métrica | Target | Descrição |
|---------|--------|-----------|
| **Total Time** | < 1.0s | Tempo total do pipeline |
| **TTFA** | < 0.7s | Time-to-First-Audio |
| **RTF** | < 1.0 | Real-Time Factor (processamento mais rápido que tempo real) |

### 1.2 Diagrama de Alto Nível

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AI INFERENCE SERVICE                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐                                       │
│  │   WebSocket  │    │    WebRTC    │                                       │
│  │   /v1/realtime   │    /v1/realtime/sessions                              │
│  └───────┬──────┘    └───────┬──────┘                                       │
│          │                   │                                               │
│          └─────────┬─────────┘                                               │
│                    ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      SESSION MANAGER                                 │   │
│  │  - Gerencia múltiplas sessões simultâneas                           │   │
│  │  - Timeout e cleanup automático                                      │   │
│  │  - Máximo: 100 sessões (configurável)                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                    │                                                         │
│                    ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      REALTIME SESSION                                │   │
│  │  - Máquina de estados (CREATED→ACTIVE→LISTENING→PROCESSING→...)    │   │
│  │  - Buffer de áudio de entrada                                        │   │
│  │  - Histórico de conversa                                             │   │
│  │  - Configuração (voice, instructions, etc.)                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                    │                                                         │
│                    ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      INFERENCE PIPELINE                              │   │
│  │                                                                      │   │
│  │   Audio In ──▶ ASR ──▶ LLM ──▶ TTS ──▶ Audio Out                   │   │
│  │                        ▲                                             │   │
│  │                        │                                             │   │
│  │                   [RAG Context]                                      │   │
│  │                   (opcional)                                         │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Estrutura de Diretórios

```
apps/ai-inference/
├── src/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app entry point
│   │
│   ├── api/                       # Endpoints HTTP/WebSocket/WebRTC
│   │   ├── __init__.py
│   │   ├── rest.py                # GET /health, /metrics, /sessions
│   │   ├── websocket.py           # WS /v1/realtime
│   │   ├── signaling.py           # POST /v1/realtime/sessions, /sdp
│   │   └── dependencies.py        # Injeção de dependências
│   │
│   ├── core/                      # Núcleo do sistema
│   │   ├── __init__.py
│   │   ├── config.py              # Settings (Pydantic)
│   │   ├── session.py             # RealtimeSession (state machine)
│   │   └── session_manager.py     # Gerenciamento multi-sessão
│   │
│   ├── models/                    # Modelos de dados (Pydantic)
│   │   ├── __init__.py
│   │   ├── audio.py               # AudioChunk, AudioBuffer
│   │   ├── session.py             # SessionConfig, TurnDetection
│   │   └── conversation.py        # ConversationItem, Response
│   │
│   ├── events/                    # Protocolo de eventos (OpenAI-compatible)
│   │   ├── __init__.py
│   │   ├── types.py               # ClientEventType, ServerEventType
│   │   ├── client_events.py       # Eventos do cliente
│   │   └── server_events.py       # Eventos do servidor
│   │
│   ├── webrtc/                    # Módulo WebRTC (aiortc)
│   │   ├── __init__.py
│   │   ├── connection.py          # RTCPeerConnection wrapper
│   │   ├── datachannel.py         # Handler de eventos via DataChannel
│   │   └── tracks.py              # AudioInputHandler, AudioOutputTrack
│   │
│   └── pipeline/                  # Pipeline de inferência (A IMPLEMENTAR)
│       ├── __init__.py
│       ├── orchestrator.py        # Coordena ASR → LLM → TTS
│       ├── asr/                   # Automatic Speech Recognition
│       │   ├── __init__.py
│       │   ├── base.py            # Interface base
│       │   └── sherpa.py          # Implementação Sherpa-ONNX
│       ├── llm/                   # Large Language Model
│       │   ├── __init__.py
│       │   ├── base.py            # Interface base
│       │   └── ollama.py          # Implementação Ollama
│       ├── tts/                   # Text-to-Speech
│       │   ├── __init__.py
│       │   ├── base.py            # Interface base
│       │   └── piper.py           # Implementação Piper
│       └── streaming/             # Streaming utilities
│           ├── __init__.py
│           ├── sentence_buffer.py # PunctuatedBufferStreamer
│           └── audio_queue.py     # Thread-safe audio queue
│
├── tests/
│   ├── conftest.py
│   ├── test_session.py
│   ├── test_websocket.py
│   ├── test_signaling.py
│   └── test_webrtc.py
│
├── scripts/
│   ├── run_e2e_test.sh
│   ├── test_e2e_webrtc.py
│   └── test_webrtc_browser.html
│
├── docs/
│   └── ARCHITECTURE.md            # Este documento
│
├── pyproject.toml
├── Dockerfile
└── README.md
```

---

## 3. Componentes Implementados (Fase 1)

### 3.1 Transporte WebSocket (`api/websocket.py`)

Implementa o protocolo OpenAI Realtime API sobre WebSocket.

```python
# Endpoint
WS /v1/realtime

# Fluxo de conexão
1. Cliente conecta via WebSocket
2. Servidor cria RealtimeSession
3. Servidor envia: session.created, conversation.created
4. Cliente/servidor trocam eventos JSON
5. Cliente pode enviar áudio como binary frames
```

**Eventos suportados (cliente → servidor):**
- `session.update` - Atualiza configuração
- `input_audio_buffer.append` - Adiciona áudio (base64)
- `input_audio_buffer.commit` - Confirma buffer de áudio
- `input_audio_buffer.clear` - Limpa buffer
- `conversation.item.create` - Cria item de conversa
- `response.create` - Solicita resposta do assistente
- `response.cancel` - Cancela resposta em andamento

**Eventos suportados (servidor → cliente):**
- `session.created`, `session.updated`
- `conversation.created`, `conversation.item.created`
- `input_audio_buffer.committed`, `input_audio_buffer.cleared`
- `response.created`, `response.done`
- `response.audio.delta`, `response.audio.done`
- `error`

### 3.2 Transporte WebRTC (`api/signaling.py`, `webrtc/`)

Implementa signaling REST + conexão WebRTC com aiortc.

```python
# Endpoints REST
POST /v1/realtime/sessions           # Cria sessão, retorna client_secret
POST /v1/realtime/sessions/{id}/sdp  # SDP exchange (offer → answer)
GET  /v1/realtime/sessions/{id}      # Info da sessão
DELETE /v1/realtime/sessions/{id}    # Fecha sessão

# Fluxo de conexão
1. Cliente: POST /v1/realtime/sessions → {id, client_secret}
2. Cliente: Cria RTCPeerConnection + DataChannel("oai-events")
3. Cliente: POST /v1/realtime/sessions/{id}/sdp com SDP offer
4. Servidor: Retorna SDP answer
5. Conexão WebRTC estabelecida
6. Eventos trocados via DataChannel (mesmo formato do WebSocket)
7. Áudio trocado via MediaTrack (RTP/SRTP + Opus)
```

**Componentes WebRTC:**
- `RealtimeConnection` - Wrapper para RTCPeerConnection
- `DataChannelHandler` - Processa eventos JSON (mesmo código do WebSocket)
- `AudioInputHandler` - Recebe áudio do cliente, envia para sessão
- `AudioOutputTrack` - Envia áudio sintetizado para cliente

### 3.3 Session Manager (`core/session_manager.py`)

Gerencia múltiplas sessões simultâneas.

```python
class SessionManager:
    async def create_session(config=None) -> RealtimeSession
    async def get_session(session_id) -> Optional[RealtimeSession]
    async def delete_session(session_id) -> bool
    async def list_sessions() -> List[str]
    async def cleanup_expired() -> int  # Remove sessões expiradas
```

**Configurações:**
- `max_sessions`: 100 (padrão)
- `session_timeout_seconds`: 3600 (1 hora)
- Cleanup task automática a cada 60s

### 3.4 Realtime Session (`core/session.py`)

Máquina de estados para cada sessão.

```python
class SessionState(Enum):
    CREATED = "created"       # Recém criada
    ACTIVE = "active"         # Aguardando ação
    LISTENING = "listening"   # Recebendo áudio
    PROCESSING = "processing" # Processando (ASR/LLM)
    RESPONDING = "responding" # Gerando resposta (TTS)
    CLOSED = "closed"         # Encerrada

class RealtimeSession:
    id: str                           # "sess_xxx"
    config: SessionConfig             # Configuração (voice, instructions, etc)
    state: SessionState               # Estado atual
    conversation: Conversation        # Histórico
    input_audio_buffer: AudioBuffer   # Buffer de áudio de entrada
    current_response: Response        # Resposta em andamento

    def update_config(new_config)     # Atualiza configuração
    def append_audio(data: bytes)     # Adiciona áudio ao buffer
    def commit_audio() -> str         # Confirma buffer, retorna item_id
    def create_response(config) -> Response
    def cancel_response() -> Response
```

---

## 4. Pipeline de Inferência (A IMPLEMENTAR)

### 4.1 Arquitetura do Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INFERENCE PIPELINE                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐                                                           │
│  │ Audio Input  │  PCM16 24kHz mono                                         │
│  │ (from WebRTC │                                                           │
│  │  or WS)      │                                                           │
│  └──────┬───────┘                                                           │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         ASR MODULE                                    │  │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │  │
│  │  │ VAD         │───▶│ Streaming   │───▶│ Transcript  │              │  │
│  │  │ (Silero)    │    │ ASR         │    │ Buffer      │              │  │
│  │  │             │    │ (Sherpa)    │    │             │              │  │
│  │  └─────────────┘    └─────────────┘    └──────┬──────┘              │  │
│  │                                               │                      │  │
│  │  Eventos emitidos:                            │                      │  │
│  │  - input_audio_buffer.speech_started          │                      │  │
│  │  - input_audio_buffer.speech_stopped          │                      │  │
│  │  - conversation.item.input_audio_transcription.completed            │  │
│  └───────────────────────────────────────────────┼──────────────────────┘  │
│                                                  │                          │
│                                                  ▼                          │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         LLM MODULE                                    │  │
│  │                                                                       │  │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐  │  │
│  │  │ Prompt      │───▶│ LLM         │───▶│ Punctuated              │  │  │
│  │  │ Builder     │    │ (Ollama)    │    │ Buffer Streamer         │  │  │
│  │  │             │    │ streaming   │    │                         │  │  │
│  │  └─────────────┘    └─────────────┘    └───────────┬─────────────┘  │  │
│  │                                                    │                 │  │
│  │  Streaming: Token por token                        │ Sentenças       │  │
│  │  Output: Sentenças completas                       │ completas       │  │
│  │                                                    │                 │  │
│  │  Eventos emitidos:                                 │                 │  │
│  │  - response.output_item.added                      │                 │  │
│  │  - response.text.delta                             │                 │  │
│  │  - response.text.done                              │                 │  │
│  └────────────────────────────────────────────────────┼─────────────────┘  │
│                                                       │                     │
│                                                       ▼                     │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         TTS MODULE                                    │  │
│  │                                                                       │  │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐  │  │
│  │  │ Sentence    │───▶│ TTS         │───▶│ Audio                   │  │  │
│  │  │ Queue       │    │ (Piper)     │    │ Output Queue            │  │  │
│  │  │             │    │             │    │                         │  │  │
│  │  └─────────────┘    └─────────────┘    └───────────┬─────────────┘  │  │
│  │                                                    │                 │  │
│  │  Síntese: Por sentença (não espera LLM terminar)   │                 │  │
│  │  Output: Chunks de áudio PCM16                     │                 │  │
│  │                                                    │                 │  │
│  │  Eventos emitidos:                                 │                 │  │
│  │  - response.audio.delta (base64)                   │                 │  │
│  │  - response.audio.done                             │                 │  │
│  │  - response.audio_transcript.delta                 │                 │  │
│  └────────────────────────────────────────────────────┼─────────────────┘  │
│                                                       │                     │
│                                                       ▼                     │
│  ┌──────────────┐                                                          │
│  │ Audio Output │  PCM16 24kHz mono                                        │
│  │ (to WebRTC   │  ou Opus encoded                                         │
│  │  or WS)      │                                                          │
│  └──────────────┘                                                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Padrão Producer-Consumer com Threading

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      THREADING MODEL                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Main Thread (asyncio event loop)                                           │
│  ├── Gerencia conexões WebSocket/WebRTC                                     │
│  ├── Recebe eventos do cliente                                              │
│  └── Envia eventos para o cliente                                           │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     PARA CADA SESSÃO ATIVA                           │   │
│  │                                                                      │   │
│  │  ┌────────────────┐      ┌──────────────┐      ┌────────────────┐  │   │
│  │  │  ASR Thread    │      │ Transcript   │      │  LLM Thread    │  │   │
│  │  │  (Producer)    │─────▶│ Queue        │─────▶│  (Consumer/    │  │   │
│  │  │                │      │              │      │   Producer)    │  │   │
│  │  │ - Recebe áudio │      │ Thread-safe  │      │                │  │   │
│  │  │ - Executa VAD  │      │ maxsize=10   │      │ - Gera texto   │  │   │
│  │  │ - Transcreve   │      │              │      │ - Streaming    │  │   │
│  │  └────────────────┘      └──────────────┘      └───────┬────────┘  │   │
│  │                                                        │            │   │
│  │                                                        ▼            │   │
│  │                                               ┌──────────────┐     │   │
│  │                                               │ Sentence     │     │   │
│  │                                               │ Queue        │     │   │
│  │                                               │              │     │   │
│  │                                               │ Thread-safe  │     │   │
│  │                                               │ maxsize=20   │     │   │
│  │                                               └───────┬──────┘     │   │
│  │                                                       │            │   │
│  │                                                       ▼            │   │
│  │  ┌────────────────┐      ┌──────────────┐      ┌────────────────┐  │   │
│  │  │  Audio Output  │      │ Audio        │      │  TTS Thread    │  │   │
│  │  │  (to client)   │◀─────│ Queue        │◀─────│  (Consumer)    │  │   │
│  │  │                │      │              │      │                │  │   │
│  │  │ - PCM16 chunks │      │ Thread-safe  │      │ - Sintetiza    │  │   │
│  │  │ - Ou Opus      │      │ maxsize=100  │      │ - Por sentença │  │   │
│  │  └────────────────┘      └──────────────┘      └────────────────┘  │   │
│  │                                                                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 PunctuatedBufferStreamer

Componente crítico que permite o TTS começar antes do LLM terminar.

```python
class PunctuatedBufferStreamer:
    """
    Detecta sentenças completas no stream de tokens do LLM
    e envia para a fila do TTS.

    Funcionamento:
    1. LLM gera tokens um a um
    2. Tokens são acumulados em buffer
    3. Quando detecta pontuação final (.!?), envia sentença para queue
    4. TTS consome sentenças e sintetiza em paralelo

    Benefício: TTS começa ~0.5s antes do LLM terminar
    """

    def __init__(self, sentence_queue: Queue):
        self.buffer = ""
        self.sentence_queue = sentence_queue
        self.sentence_pattern = re.compile(r'[.!?]\s*')
        self.first_token_time = None  # Para métricas TTFT

    def on_token(self, token: str):
        """Chamado para cada token gerado pelo LLM."""
        if self.first_token_time is None:
            self.first_token_time = time.time()

        self.buffer += token
        self._flush_complete_sentences()

    def _flush_complete_sentences(self):
        """Envia sentenças completas para a fila."""
        parts = self.sentence_pattern.split(self.buffer)

        # Enviar todas as sentenças completas
        for i in range(0, len(parts) - 1, 2):
            sentence = parts[i].strip()
            punctuation = parts[i + 1] if i + 1 < len(parts) else ""
            if sentence:
                full_sentence = sentence + punctuation
                self.sentence_queue.put(full_sentence)

        # Manter texto incompleto no buffer
        self.buffer = parts[-1] if parts else ""

    def finish(self):
        """Chamado quando LLM termina. Envia resto do buffer."""
        if self.buffer.strip():
            self.sentence_queue.put(self.buffer.strip())
        self.sentence_queue.put(None)  # Sinaliza fim
```

### 4.4 Interfaces dos Módulos

```python
# === ASR Interface ===
class ASREngine(ABC):
    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[TranscriptionResult]:
        """Transcreve stream de áudio em tempo real."""
        pass

@dataclass
class TranscriptionResult:
    text: str
    is_final: bool
    confidence: float
    timestamp_ms: int


# === LLM Interface ===
class LLMEngine(ABC):
    @abstractmethod
    async def generate_stream(
        self,
        messages: List[Message],
        config: GenerationConfig
    ) -> AsyncIterator[str]:
        """Gera resposta em streaming (token por token)."""
        pass

@dataclass
class GenerationConfig:
    temperature: float = 0.7
    max_tokens: int = 256
    stop_sequences: List[str] = None


# === TTS Interface ===
class TTSEngine(ABC):
    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str = "default"
    ) -> bytes:
        """Sintetiza texto em áudio PCM16."""
        pass

    @abstractmethod
    async def warmup(self):
        """Pré-carrega componentes para reduzir latência inicial."""
        pass
```

---

## 5. Protocolo de Eventos

### 5.1 Formato dos Eventos

Todos os eventos seguem o mesmo formato JSON, compatível com OpenAI Realtime API:

```json
{
    "event_id": "event_xxx",
    "type": "event.type.name",
    ...campos específicos do evento
}
```

### 5.2 Fluxo Típico de Conversa

```
Cliente                              Servidor
   │                                    │
   │◀───────── session.created ─────────│  (após conexão)
   │◀────── conversation.created ───────│
   │                                    │
   │── input_audio_buffer.append ──────▶│  (áudio em chunks)
   │── input_audio_buffer.append ──────▶│
   │── input_audio_buffer.append ──────▶│
   │                                    │
   │◀─── input_audio_buffer.speech_started ──│  (VAD detectou fala)
   │                                    │
   │── input_audio_buffer.commit ──────▶│  (usuário parou de falar)
   │◀─ input_audio_buffer.committed ────│
   │                                    │
   │◀─ conversation.item.created ───────│  (item de áudio criado)
   │◀─ input_audio_transcription.completed ─│  (transcrição pronta)
   │                                    │
   │── response.create ────────────────▶│  (solicita resposta)
   │◀───── response.created ────────────│
   │◀─ response.output_item.added ──────│
   │                                    │
   │◀──── response.text.delta ──────────│  (texto em streaming)
   │◀──── response.text.delta ──────────│
   │◀──── response.audio.delta ─────────│  (áudio em streaming)
   │◀──── response.audio.delta ─────────│
   │◀──── response.text.done ───────────│
   │◀──── response.audio.done ──────────│
   │◀─ response.output_item.done ───────│
   │◀───── response.done ───────────────│
   │                                    │
```

### 5.3 Eventos de Áudio

Para WebSocket, áudio é enviado como base64 nos eventos:

```json
{
    "type": "response.audio.delta",
    "response_id": "resp_xxx",
    "item_id": "item_xxx",
    "content_index": 0,
    "delta": "base64_encoded_pcm16_audio..."
}
```

Para WebRTC, áudio é enviado via MediaTrack (mais eficiente):
- Codec: Opus
- Sample rate: 24kHz ou 48kHz
- Channels: 1 (mono)
- Eventos via DataChannel são apenas metadados (sem áudio inline)

---

## 6. Configuração

### 6.1 Variáveis de Ambiente

```bash
# Servidor
AI_INFERENCE_HOST=0.0.0.0
AI_INFERENCE_PORT=8080
AI_INFERENCE_DEBUG=false

# Sessões
AI_INFERENCE_MAX_SESSIONS=100
AI_INFERENCE_SESSION_TIMEOUT_SECONDS=3600

# ASR
AI_INFERENCE_ASR_ENGINE=sherpa        # sherpa, whisper, etc
AI_INFERENCE_ASR_MODEL=...
AI_INFERENCE_ASR_ENDPOINT=...

# LLM
AI_INFERENCE_LLM_ENGINE=ollama
AI_INFERENCE_LLM_MODEL=llama3.2:3b
AI_INFERENCE_LLM_ENDPOINT=http://localhost:11434

# TTS
AI_INFERENCE_TTS_ENGINE=piper
AI_INFERENCE_TTS_MODEL=...
AI_INFERENCE_TTS_ENDPOINT=...

# WebRTC
AI_INFERENCE_STUN_SERVERS=["stun:stun.l.google.com:19302"]
AI_INFERENCE_TURN_SERVER=turn:localhost:3478
AI_INFERENCE_TURN_USERNAME=...
AI_INFERENCE_TURN_PASSWORD=...

# Tokens
AI_INFERENCE_TOKEN_SECRET=change-me-in-production
AI_INFERENCE_TOKEN_EXPIRY_SECONDS=120
```

### 6.2 Configuração de Sessão

```json
{
    "modalities": ["text", "audio"],
    "instructions": "You are a helpful assistant.",
    "voice": "alloy",
    "input_audio_format": "pcm16",
    "output_audio_format": "pcm16",
    "turn_detection": {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 500,
        "create_response": true
    },
    "temperature": 0.7,
    "max_response_output_tokens": 256
}
```

---

## 7. Métricas e Monitoramento

### 7.1 Métricas Coletadas

```python
@dataclass
class PipelineMetrics:
    # Latências (segundos)
    asr_time: float          # Tempo de transcrição
    llm_time: float          # Tempo de geração
    tts_time: float          # Tempo de síntese
    total_time: float        # Tempo total do pipeline

    # Time-to-First
    ttft: float              # Time-to-First-Token (LLM)
    ttfa: float              # Time-to-First-Audio (TTS)

    # Throughput
    asr_words_per_sec: float
    llm_tokens_per_sec: float

    # Real-Time Factor
    asr_rtf: float           # < 1.0 = faster than realtime
    tts_rtf: float
```

### 7.2 Endpoints de Monitoramento

```
GET /health
{
    "status": "healthy",
    "sessions_active": 5
}

GET /metrics
{
    "total_sessions": 5,
    "max_sessions": 100,
    "sessions_by_state": {
        "active": 3,
        "processing": 2
    }
}
```

---

## 8. Testes

### 8.1 Testes Unitários

```bash
# Rodar todos os testes
python3 -m pytest tests/ -v

# Testes específicos
python3 -m pytest tests/test_session.py -v
python3 -m pytest tests/test_signaling.py -v
python3 -m pytest tests/test_webrtc.py -v
```

### 8.2 Testes E2E

```bash
# Iniciar servidor + abrir teste no browser
./scripts/run_e2e_test.sh

# Só rodar teste Python
python3 scripts/test_e2e_webrtc.py
```

### 8.3 Teste Manual com cURL

```bash
# Health check
curl http://localhost:8080/health

# Criar sessão
curl -X POST http://localhost:8080/v1/realtime/sessions \
  -H "Content-Type: application/json" \
  -d '{"instructions": "You are helpful."}'

# Obter info da sessão
curl http://localhost:8080/v1/realtime/sessions/{session_id}
```

---

## 9. Dependências

```toml
[project]
dependencies = [
    # Web framework
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",

    # Data validation
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",

    # WebSocket
    "websockets>=12.0",

    # WebRTC
    "aiortc>=1.9.0",
    "aioice>=0.9.0",
    "av>=12.0.0",

    # Auth
    "PyJWT>=2.8.0",

    # Logging
    "structlog>=24.0.0",
]
```

---

## 10. Próximos Passos

1. **Implementar `pipeline/orchestrator.py`**
   - Coordena ASR → LLM → TTS
   - Gerencia threads e queues

2. **Implementar `pipeline/asr/sherpa.py`**
   - Integrar Sherpa-ONNX para streaming ASR
   - Adicionar VAD (Silero)

3. **Implementar `pipeline/llm/ollama.py`**
   - Integrar Ollama para geração
   - Implementar PunctuatedBufferStreamer

4. **Implementar `pipeline/tts/piper.py`**
   - Integrar Piper para síntese
   - Implementar warmup

5. **Conectar pipeline com transporte**
   - WebSocket: enviar eventos de áudio como base64
   - WebRTC: enviar áudio via AudioOutputTrack

---

*Documento atualizado em: 2026-01-23*
