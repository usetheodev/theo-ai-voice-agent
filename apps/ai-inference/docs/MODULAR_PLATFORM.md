# Plataforma Modular de Voice Agents

## Análise de Mercado: Como os Líderes Resolvem o Problema

### 1. Vapi.ai

**Arquitetura:**
- Pipeline modular: STT → LLM → TTS (cada componente é substituível)
- Provider flexibility: pode trocar qualquer provider sem mudar código
- WebSocket bidirectional para áudio
- Latência: 500-800ms end-to-end

**VAD State Machine:**
```
QUIET → STARTING → SPEAKING → STOPPING → QUIET
```
- Transições baseadas em energia do áudio e duração
- `minSecondsOfNoise` para evitar falsos positivos
- `silenceTimeoutMs` para detectar fim de fala

**Interrupção (Barge-in):**
- Detecta quando usuário fala durante resposta do bot
- Para TTS imediatamente
- Cancela geração LLM em andamento
- Reinicia pipeline com novo input

**Diferenciais:**
- SDK em múltiplas linguagens
- Webhook para eventos
- Transcrição em tempo real
- Suporte a múltiplos providers (Deepgram, OpenAI, ElevenLabs, etc.)

---

### 2. Retell AI

**Arquitetura:**
- Latência: ~600ms (estado da arte)
- Modelo proprietário de turn-taking
- WebSocket para streaming de áudio
- Arquitetura distribuída para escalabilidade

**Turn-Taking:**
- Modelo de ML treinado especificamente para conversação
- Prediz quando é a vez de cada participante
- Reduz interrupções acidentais
- Melhora naturalidade da conversa

**Barge-in Detection:**
- Detecção de fala do usuário durante resposta
- Cancelamento graceful da resposta atual
- Contexto preservado para continuidade

**Diferenciais:**
- Foco em call centers e telefonia
- Integração com SIP/PSTN
- Vozes clonadas customizadas
- Analytics de conversação

---

### 3. ElevenLabs Conversational AI

**Arquitetura:**
- WebSocket API primária
- WebRTC para baixa latência
- Multi-Context: 5 contextos concorrentes por conexão
- Áudio: 16kHz mono PCM

**Multi-Context:**
```
Conexão WebSocket
├── Contexto 1 (Conversa A)
├── Contexto 2 (Conversa B)
├── Contexto 3 (Conversa C)
├── Contexto 4 (Conversa D)
└── Contexto 5 (Conversa E)
```
- Reutiliza conexão para múltiplas conversas
- Reduz overhead de handshake
- Ideal para aplicações multi-tenant

**Streaming:**
- Áudio enviado em chunks pequenos
- TTS retorna áudio enquanto gera
- Baixa latência percebida

**Diferenciais:**
- Qualidade de voz excepcional
- Voice cloning avançado
- Monitoramento em tempo real
- SDK robusto

---

## Padrões Comuns Identificados

| Padrão | Vapi | Retell | ElevenLabs | Nossa Plataforma |
|--------|------|--------|------------|------------------|
| Pipeline Modular | ✅ | ✅ | ✅ | ✅ |
| Provider Swappable | ✅ | ❌ | ❌ | ✅ |
| VAD Inteligente | ✅ | ✅ | ✅ | ✅ |
| Barge-in | ✅ | ✅ | ✅ | ✅ |
| WebSocket | ✅ | ✅ | ✅ | ✅ |
| WebRTC | ❌ | ❌ | ✅ | ✅ |
| Multi-Context | ❌ | ❌ | ✅ | ✅ |
| Open Source | ❌ | ❌ | ❌ | ✅ |

---

## Arquitetura Proposta: Voice Agent Platform

### Princípios de Design

1. **Plugin Architecture**: Cada componente é um plugin substituível
2. **Protocol Agnostic**: WebSocket, WebRTC, SIP - mesmo core
3. **Provider Agnostic**: Troque ASR, LLM, TTS sem mudar código
4. **Event-Driven**: Tudo é evento, fácil de debugar e extender
5. **Streaming First**: Nunca espere completar, sempre streame

### Arquitetura de Alto Nível

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Voice Agent Platform                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                      Transport Layer (Plugins)                   │    │
│  ├──────────────┬──────────────┬──────────────┬──────────────────┤    │
│  │   WebRTC     │  WebSocket   │     SIP      │    HTTP/REST     │    │
│  │  (aiortc)    │ (FastAPI WS) │  (pjsip)     │   (polling)      │    │
│  └──────┬───────┴──────┬───────┴──────┬───────┴────────┬─────────┘    │
│         │              │              │                │               │
│         └──────────────┴──────────────┴────────────────┘               │
│                              │                                          │
│                    ┌─────────▼─────────┐                               │
│                    │   Session Manager  │                               │
│                    │  (Multi-Context)   │                               │
│                    └─────────┬─────────┘                               │
│                              │                                          │
│  ┌───────────────────────────▼───────────────────────────────────┐     │
│  │                     Pipeline Orchestrator                      │     │
│  │                                                                │     │
│  │   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐   │     │
│  │   │   VAD   │───►│   ASR   │───►│   LLM   │───►│   TTS   │   │     │
│  │   │ (Plugin)│    │ (Plugin)│    │ (Plugin)│    │ (Plugin)│   │     │
│  │   └─────────┘    └─────────┘    └─────────┘    └─────────┘   │     │
│  │                                                                │     │
│  │   ┌─────────────────────────────────────────────────────────┐ │     │
│  │   │              Interruption Handler (Barge-in)             │ │     │
│  │   └─────────────────────────────────────────────────────────┘ │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                        Provider Registry                         │    │
│  ├─────────────┬─────────────┬─────────────┬─────────────────────┤    │
│  │ ASR Providers│LLM Providers│TTS Providers│   VAD Providers     │    │
│  │ ─────────────│─────────────│─────────────│───────────────────  │    │
│  │ • Whisper    │ • Ollama    │ • Piper     │ • Silero VAD        │    │
│  │ • Deepgram   │ • OpenAI    │ • ElevenLabs│ • WebRTC VAD        │    │
│  │ • Parakeet   │ • Anthropic │ • Azure     │ • Energy-based      │    │
│  │ • Google     │ • Groq      │ • Coqui     │                     │    │
│  └─────────────┴─────────────┴─────────────┴─────────────────────┘    │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                         Event Bus                                │    │
│  │   (Pub/Sub para todos os componentes se comunicarem)            │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Estrutura de Diretórios Proposta

```
apps/ai-inference/src/
├── core/
│   ├── config.py              # Configurações globais
│   ├── session.py             # RealtimeSession
│   ├── session_manager.py     # Gerenciamento multi-sessão
│   └── event_bus.py           # Event Bus (pub/sub)
│
├── transports/                # Transport Layer (Plugins)
│   ├── __init__.py
│   ├── base.py                # TransportBase (interface)
│   ├── webrtc/                # WebRTC transport (existente)
│   │   ├── connection.py
│   │   ├── datachannel.py
│   │   └── tracks.py
│   ├── websocket/             # WebSocket transport
│   │   └── handler.py
│   └── sip/                   # SIP transport (futuro)
│       └── handler.py
│
├── pipeline/                  # Pipeline Orchestrator
│   ├── __init__.py
│   ├── orchestrator.py        # Pipeline principal
│   ├── interruption.py        # Barge-in handler
│   └── state_machine.py       # Estado da conversa
│
├── providers/                 # Provider Registry
│   ├── __init__.py
│   ├── base.py                # Interfaces base
│   ├── registry.py            # Provider registry
│   │
│   ├── asr/                   # ASR Providers
│   │   ├── __init__.py
│   │   ├── base.py            # ASRProvider interface
│   │   ├── whisper.py         # Whisper local
│   │   ├── deepgram.py        # Deepgram API
│   │   └── parakeet.py        # Parakeet local
│   │
│   ├── llm/                   # LLM Providers
│   │   ├── __init__.py
│   │   ├── base.py            # LLMProvider interface
│   │   ├── ollama.py          # Ollama local
│   │   ├── openai.py          # OpenAI API
│   │   └── anthropic.py       # Anthropic API
│   │
│   ├── tts/                   # TTS Providers
│   │   ├── __init__.py
│   │   ├── base.py            # TTSProvider interface
│   │   ├── piper.py           # Piper local
│   │   ├── elevenlabs.py      # ElevenLabs API
│   │   └── coqui.py           # Coqui local
│   │
│   └── vad/                   # VAD Providers
│       ├── __init__.py
│       ├── base.py            # VADProvider interface
│       ├── silero.py          # Silero VAD
│       └── webrtc.py          # WebRTC VAD
│
├── events/                    # Event System (existente)
│   ├── types.py
│   ├── client_events.py
│   └── server_events.py
│
├── models/                    # Data Models (existente)
│   ├── session.py
│   ├── conversation.py
│   └── audio.py
│
└── api/                       # REST API (existente)
    ├── rest.py
    └── signaling.py
```

---

## Interfaces dos Providers

### ASR Provider Interface

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from dataclasses import dataclass

@dataclass
class TranscriptionResult:
    text: str
    is_final: bool
    confidence: float
    language: Optional[str] = None
    words: Optional[list] = None  # Word-level timestamps

class ASRProvider(ABC):
    """Interface para providers de ASR (Speech-to-Text)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome do provider (ex: 'whisper', 'deepgram')."""
        pass

    @property
    @abstractmethod
    def supports_streaming(self) -> bool:
        """Se suporta transcrição em streaming."""
        pass

    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[TranscriptionResult]:
        """Transcreve áudio em streaming."""
        pass

    @abstractmethod
    async def transcribe_batch(
        self,
        audio_data: bytes
    ) -> TranscriptionResult:
        """Transcreve áudio completo de uma vez."""
        pass
```

### LLM Provider Interface

```python
@dataclass
class LLMResponse:
    text: str
    is_complete: bool
    usage: Optional[dict] = None

class LLMProvider(ABC):
    """Interface para providers de LLM."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def supports_streaming(self) -> bool:
        pass

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[LLMResponse]:
        """Gera resposta em streaming."""
        pass

    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """Gera resposta completa."""
        pass
```

### TTS Provider Interface

```python
@dataclass
class AudioChunk:
    data: bytes
    sample_rate: int
    channels: int
    is_final: bool

class TTSProvider(ABC):
    """Interface para providers de TTS (Text-to-Speech)."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def supports_streaming(self) -> bool:
        pass

    @property
    @abstractmethod
    def available_voices(self) -> list[str]:
        pass

    @abstractmethod
    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: str = "default"
    ) -> AsyncIterator[AudioChunk]:
        """Sintetiza texto em streaming."""
        pass

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str = "default"
    ) -> AudioChunk:
        """Sintetiza texto completo."""
        pass
```

### VAD Provider Interface

```python
@dataclass
class VADResult:
    is_speech: bool
    confidence: float
    start_time: Optional[float] = None
    end_time: Optional[float] = None

class VADProvider(ABC):
    """Interface para providers de VAD (Voice Activity Detection)."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int = 16000
    ) -> VADResult:
        """Processa chunk de áudio e retorna se há fala."""
        pass

    @abstractmethod
    def reset(self):
        """Reseta estado interno do VAD."""
        pass
```

---

## Provider Registry

```python
class ProviderRegistry:
    """Registro central de todos os providers."""

    def __init__(self):
        self._asr_providers: dict[str, ASRProvider] = {}
        self._llm_providers: dict[str, LLMProvider] = {}
        self._tts_providers: dict[str, TTSProvider] = {}
        self._vad_providers: dict[str, VADProvider] = {}

    def register_asr(self, provider: ASRProvider):
        self._asr_providers[provider.name] = provider

    def register_llm(self, provider: LLMProvider):
        self._llm_providers[provider.name] = provider

    def register_tts(self, provider: TTSProvider):
        self._tts_providers[provider.name] = provider

    def register_vad(self, provider: VADProvider):
        self._vad_providers[provider.name] = provider

    def get_asr(self, name: str) -> ASRProvider:
        return self._asr_providers[name]

    def get_llm(self, name: str) -> LLMProvider:
        return self._llm_providers[name]

    def get_tts(self, name: str) -> TTSProvider:
        return self._tts_providers[name]

    def get_vad(self, name: str) -> VADProvider:
        return self._vad_providers[name]

# Uso
registry = ProviderRegistry()
registry.register_asr(WhisperProvider())
registry.register_asr(DeepgramProvider(api_key="..."))
registry.register_llm(OllamaProvider(model="llama3"))
registry.register_tts(PiperProvider(model_path="..."))
registry.register_vad(SileroVADProvider())
```

---

## Pipeline Orchestrator

```python
class PipelineOrchestrator:
    """Orquestra o pipeline ASR → LLM → TTS com suporte a interrupção."""

    def __init__(
        self,
        asr: ASRProvider,
        llm: LLMProvider,
        tts: TTSProvider,
        vad: VADProvider,
        event_bus: EventBus,
    ):
        self.asr = asr
        self.llm = llm
        self.tts = tts
        self.vad = vad
        self.event_bus = event_bus

        self._current_task: Optional[asyncio.Task] = None
        self._interrupted = asyncio.Event()

    async def process_audio(
        self,
        audio_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[AudioChunk]:
        """Pipeline completo: áudio in → áudio out."""

        # 1. VAD + ASR
        async for transcription in self.asr.transcribe_stream(audio_stream):
            if transcription.is_final:
                self.event_bus.emit("transcription.final", transcription)

                # 2. LLM
                messages = self._build_messages(transcription.text)
                text_buffer = ""

                async for llm_response in self.llm.generate_stream(messages):
                    if self._interrupted.is_set():
                        self._interrupted.clear()
                        break

                    text_buffer += llm_response.text

                    # 3. TTS (sentence-level streaming)
                    if self._is_sentence_boundary(text_buffer):
                        sentence, text_buffer = self._extract_sentence(text_buffer)

                        async for audio in self.tts.synthesize_stream(
                            self._text_iter(sentence)
                        ):
                            if self._interrupted.is_set():
                                break
                            yield audio

    def interrupt(self):
        """Interrompe pipeline atual (barge-in)."""
        self._interrupted.set()
        self.event_bus.emit("pipeline.interrupted")
```

---

## Interruption Handler (Barge-in)

```python
class InterruptionHandler:
    """Gerencia interrupções quando usuário fala durante resposta."""

    def __init__(
        self,
        vad: VADProvider,
        pipeline: PipelineOrchestrator,
        event_bus: EventBus,
    ):
        self.vad = vad
        self.pipeline = pipeline
        self.event_bus = event_bus

        # Configuração
        self.min_speech_duration_ms = 200  # Evita falsos positivos
        self.speech_start_time: Optional[float] = None

    async def monitor_input(self, audio_stream: AsyncIterator[bytes]):
        """Monitora áudio de entrada para detectar interrupção."""

        async for chunk in audio_stream:
            result = await self.vad.process(chunk)

            if result.is_speech:
                if self.speech_start_time is None:
                    self.speech_start_time = time.time()

                # Verifica se fala durou tempo suficiente
                duration_ms = (time.time() - self.speech_start_time) * 1000

                if duration_ms >= self.min_speech_duration_ms:
                    if self.pipeline.is_generating:
                        self.pipeline.interrupt()
                        self.event_bus.emit("barge_in.detected")
            else:
                self.speech_start_time = None
```

---

## Event Bus

```python
from typing import Callable, Any
import asyncio

class EventBus:
    """Pub/Sub para comunicação entre componentes."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._async_subscribers: dict[str, list[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        """Registra callback para evento."""
        if asyncio.iscoroutinefunction(callback):
            self._async_subscribers.setdefault(event_type, []).append(callback)
        else:
            self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: str, callback: Callable):
        """Remove callback."""
        if callback in self._subscribers.get(event_type, []):
            self._subscribers[event_type].remove(callback)
        if callback in self._async_subscribers.get(event_type, []):
            self._async_subscribers[event_type].remove(callback)

    async def emit(self, event_type: str, data: Any = None):
        """Emite evento para todos os subscribers."""
        # Sync callbacks
        for callback in self._subscribers.get(event_type, []):
            callback(data)

        # Async callbacks
        tasks = [
            callback(data)
            for callback in self._async_subscribers.get(event_type, [])
        ]
        if tasks:
            await asyncio.gather(*tasks)

# Eventos disponíveis
EVENTS = {
    # Audio
    "audio.input.received",
    "audio.output.sent",

    # VAD
    "vad.speech.start",
    "vad.speech.end",

    # ASR
    "transcription.partial",
    "transcription.final",

    # LLM
    "llm.response.start",
    "llm.response.chunk",
    "llm.response.end",

    # TTS
    "tts.synthesis.start",
    "tts.synthesis.chunk",
    "tts.synthesis.end",

    # Pipeline
    "pipeline.started",
    "pipeline.completed",
    "pipeline.interrupted",

    # Barge-in
    "barge_in.detected",
}
```

---

## Configuração por Sessão

```python
@dataclass
class SessionPipelineConfig:
    """Configuração do pipeline por sessão."""

    # Providers
    asr_provider: str = "whisper"
    llm_provider: str = "ollama"
    tts_provider: str = "piper"
    vad_provider: str = "silero"

    # ASR
    asr_language: str = "pt-BR"
    asr_model: str = "large-v3"

    # LLM
    llm_model: str = "llama3"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 150
    system_prompt: str = "Você é um assistente de voz amigável."

    # TTS
    tts_voice: str = "pt_BR-faber-medium"
    tts_speed: float = 1.0

    # VAD
    vad_threshold: float = 0.5
    vad_min_speech_duration_ms: int = 200
    vad_min_silence_duration_ms: int = 500

    # Interrupção
    enable_barge_in: bool = True
    barge_in_threshold_ms: int = 200

# Uso na API
@router.post("/v1/realtime/sessions")
async def create_session(config: SessionPipelineConfig):
    session = await session_manager.create_session(config)
    # Pipeline configurado automaticamente com os providers especificados
    return session
```

---

## Status de Implementação

### Já Implementado

| Componente | Status | Arquivos |
|------------|--------|----------|
| WebRTC Transport | ✅ Completo | `webrtc/connection.py`, `webrtc/tracks.py`, `webrtc/datachannel.py` |
| Session Manager | ✅ Completo | `core/session_manager.py`, `core/session.py` |
| Event System | ✅ Completo | `events/`, compatível OpenAI |
| REST API Signaling | ✅ Completo | `api/signaling.py` |
| Voice Agent Config | ✅ Completo | `models/agent_config.py` |
| Agent CRUD API | ✅ Completo | `api/agents.py` |
| Provider Registry API | ✅ Completo | Endpoints para listar providers |
| Presets | ✅ Completo | local, low-latency, high-quality |
| Cost/Latency Estimates | ✅ Completo | Baseado nos providers selecionados |

### API Endpoints Disponíveis

```
# Voice Agents
POST   /v1/agents                        - Criar agente customizado
GET    /v1/agents                        - Listar agentes
GET    /v1/agents/{id}                   - Obter agente
PATCH  /v1/agents/{id}                   - Atualizar agente
DELETE /v1/agents/{id}                   - Deletar agente

# Presets
GET    /v1/agents/presets                - Listar presets
POST   /v1/agents/from-preset/{preset}   - Criar a partir de preset

# Providers
GET    /v1/agents/providers/llm          - Listar providers LLM
GET    /v1/agents/providers/tts          - Listar providers TTS
GET    /v1/agents/providers/asr          - Listar providers ASR

# WebRTC (existente)
POST   /v1/realtime/sessions             - Criar sessão
POST   /v1/realtime/sessions/{id}/sdp    - SDP exchange
GET    /v1/realtime/sessions/{id}        - Obter sessão
DELETE /v1/realtime/sessions/{id}        - Deletar sessão
```

---

## Roadmap de Implementação

### Fase 1: Core Infrastructure ✅
- [x] WebRTC Transport
- [x] Session Manager
- [x] Event System (OpenAI-compatible)
- [x] Voice Agent Configuration Model
- [x] Agent CRUD API
- [ ] Event Bus (pub/sub interno)

### Fase 2: Provider Interfaces ✅
- [x] ASRProvider interface
- [x] LLMProvider interface
- [x] TTSProvider interface
- [x] VADProvider interface
- [x] ProviderManager (Registry + Factory)

### Fase 3: Cloud Providers (API-based) ✅
- [x] OpenAI Whisper ASR (batch)
- [x] Deepgram ASR (batch + streaming WebSocket)
- [x] OpenAI LLM (streaming)
- [x] Ollama LLM (streaming) - para rodar LLMs localmente via API
- [x] Groq LLM (streaming) - ultra-baixa latência
- [x] OpenAI TTS (streaming)
- [x] ElevenLabs TTS (streaming)
- [x] Silero VAD (local ou API)
- [x] Energy VAD (local, sem dependências)

### Fase 4: Pipeline (Próximo)
- [ ] Pipeline Orchestrator
- [ ] Interruption Handler (barge-in)
- [ ] Sentence-level streaming (PunctuatedBufferStreamer)
- [ ] State Machine

### Fase 5: Transports Adicionais
- [x] WebSocket transport (existente)
- [ ] SIP transport (telefonia)

---

## Métricas de Sucesso

| Métrica | Target | Como Vapi | Como Retell |
|---------|--------|-----------|-------------|
| Latência E2E | < 800ms | 500-800ms | ~600ms |
| TTFT (Time to First Token) | < 300ms | ~300ms | ~250ms |
| Interrupção Detection | < 200ms | ~200ms | ~150ms |
| Uptime | 99.9% | 99.9% | 99.95% |

---

## Diferenciais da Nossa Plataforma

1. **100% Open Source**: Código aberto, auditável
2. **Self-hosted**: Roda em infraestrutura própria
3. **Provider Agnostic**: Troque qualquer componente
4. **Privacy First**: Dados não saem da sua infra
5. **WebRTC + WebSocket**: Flexibilidade de transporte
6. **OpenAI-Compatible**: API familiar, fácil migração
7. **Modular**: Use só o que precisa
8. **Extensível**: Adicione providers próprios
