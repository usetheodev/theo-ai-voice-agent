# 🎯 Roadmap de Correção de GAPs - Voice Pipeline

> **Autor**: Staff Engineer (especialista em Agent AI)
> **Data**: 2025-01-24
> **Baseado em**: Análise do estado atual vs ROADMAP.md original

---

## 📊 Estado Atual vs Gaps

### ✅ Já Implementado (Completo)
| Componente | Arquivo | Status |
|------------|---------|--------|
| Provider Base Infrastructure | `providers/base.py` | ✅ Completo |
| OpenAI LLM Provider | `providers/llm/openai.py` | ✅ Completo |
| OpenAI TTS Provider | `providers/tts/openai.py` | ✅ Completo |
| OpenAI ASR Provider | `providers/asr/openai.py` | ✅ Completo |
| Silero VAD Provider | `providers/vad/silero.py` | ✅ Completo |
| Provider Registry | `providers/registry.py` | ✅ Completo |

### ❌ GAPs Identificados (Faltando)
| Gap | Prioridade | Impacto |
|-----|------------|---------|
| **Ollama LLM Provider** | 🔴 Alta | Permite uso offline/local |
| **Ollama TTS Provider** | 🟡 Média | Síntese local |
| **whisper.cpp ASR** | 🟡 Média | ASR local ultra-rápido |
| **WebRTC VAD** | 🟢 Baixa | Alternativa leve ao Silero |
| **OpenAI Realtime API** | 🔴 Alta | Ultra-baixa latência (<300ms) |
| **Audio Transport Layer** | 🔴 Alta | Captura/playback real |
| **Testes E2E com Fixtures** | 🔴 Alta | Confiança em produção |

---

## 🚀 SPRINT 1: Providers Locais (Ollama)
> **Duração Estimada**: 1-2 sprints
> **Objetivo**: Permitir uso 100% offline

### 1.1 Ollama LLM Provider
**Arquivo**: `src/voice_pipeline/providers/llm/ollama.py`

```
Escopo:
├── OllamaLLMConfig (dataclass)
│   ├── base_url: str = "http://localhost:11434"
│   ├── model: str = "llama3.2"
│   ├── timeout: float = 30.0
│   └── format: Optional[str] = None
│
├── OllamaLLMProvider (BaseProvider, LLMInterface)
│   ├── __init__(config: OllamaLLMConfig)
│   ├── connect() → None
│   ├── disconnect() → None
│   ├── health_check() → HealthCheckResult
│   ├── ainvoke(messages: list[dict]) → LLMResponse
│   ├── astream(messages: list[dict]) → AsyncIterator[LLMChunk]
│   └── _handle_tool_calls() → list[ToolCall]
│
└── Testes
    ├── test_ollama_llm_config.py
    ├── test_ollama_llm_invoke.py (mock)
    ├── test_ollama_llm_stream.py (mock)
    └── test_ollama_llm_integration.py (skip se Ollama não disponível)
```

**Definition of Done**:
- [ ] Implementa `LLMInterface` completamente
- [ ] Streaming funciona com tokens incrementais
- [ ] Suporte a tool/function calling
- [ ] Auto-discovery de modelos disponíveis
- [ ] Health check verifica conexão com Ollama
- [ ] Fallback graceful se Ollama offline
- [ ] Testes unitários com mocks
- [ ] Testes de integração (marcados como `@pytest.mark.integration`)

### 1.2 Ollama TTS Provider (via Kokoro/Piper)
**Arquivo**: `src/voice_pipeline/providers/tts/ollama.py`

> **Nota**: Ollama não tem TTS nativo. Implementar wrapper para Kokoro TTS local.

```
Escopo:
├── LocalTTSConfig (dataclass)
│   ├── backend: Literal["kokoro", "piper"] = "kokoro"
│   ├── voice: str = "af_bella"
│   ├── speed: float = 1.0
│   └── sample_rate: int = 24000
│
├── LocalTTSProvider (BaseProvider, TTSInterface)
│   ├── __init__(config: LocalTTSConfig)
│   ├── ainvoke(text: str) → bytes
│   ├── astream(text: str) → AsyncIterator[AudioChunk]
│   └── list_voices() → list[str]
│
└── Testes
    ├── test_local_tts_config.py
    ├── test_local_tts_kokoro.py
    └── test_local_tts_piper.py
```

**Definition of Done**:
- [ ] Implementa `TTSInterface`
- [ ] Streaming por sentenças
- [ ] Múltiplas vozes disponíveis
- [ ] Latência < 200ms TTFB local
- [ ] Testes com áudio gerado (verificar formato)

---

## 🚀 SPRINT 2: whisper.cpp ASR
> **Duração Estimada**: 1 sprint
> **Objetivo**: ASR local ultra-rápido

### 2.1 whisper.cpp Provider
**Arquivo**: `src/voice_pipeline/providers/asr/whisper_cpp.py`

```
Escopo:
├── WhisperCppConfig (dataclass)
│   ├── model_path: Optional[str] = None  # Auto-download se None
│   ├── model_size: Literal["tiny", "base", "small", "medium", "large"] = "base"
│   ├── language: str = "pt"
│   ├── use_gpu: bool = True
│   ├── n_threads: int = 4
│   └── beam_size: int = 5
│
├── WhisperCppProvider (BaseProvider, ASRInterface)
│   ├── __init__(config: WhisperCppConfig)
│   ├── _download_model() → Path
│   ├── _detect_hardware() → Literal["cpu", "cuda", "metal"]
│   ├── ainvoke(audio: bytes) → TranscriptionResult
│   ├── astream(audio_stream) → AsyncIterator[TranscriptionResult]
│   └── transcribe_file(path: Path) → TranscriptionResult
│
└── Testes
    ├── test_whisper_cpp_config.py
    ├── test_whisper_cpp_invoke.py (com fixture de áudio)
    ├── test_whisper_cpp_stream.py
    └── test_whisper_cpp_models.py (download/cache)
```

**Opções de Binding**:
1. **pywhispercpp** - Binding Python puro
2. **faster-whisper** - CTranslate2 backend (recomendado)
3. **whisper.cpp subprocess** - Menos overhead

**Definition of Done**:
- [ ] Implementa `ASRInterface`
- [ ] Auto-download de modelos
- [ ] GPU detection (CUDA/Metal)
- [ ] Latência < 100ms para chunks de 1s
- [ ] Suporte a PT-BR
- [ ] Testes com fixtures WAV

---

## 🚀 SPRINT 3: OpenAI Realtime API
> **Duração Estimada**: 2 sprints
> **Objetivo**: Audio-to-audio com latência < 300ms

### 3.1 OpenAI Realtime Provider
**Arquivo**: `src/voice_pipeline/providers/realtime/openai.py`

```
Escopo:
├── OpenAIRealtimeConfig (dataclass)
│   ├── api_key: str
│   ├── model: str = "gpt-4o-realtime-preview"
│   ├── voice: str = "alloy"
│   ├── modalities: list[str] = ["text", "audio"]
│   ├── input_audio_format: str = "pcm16"
│   ├── output_audio_format: str = "pcm16"
│   ├── turn_detection: TurnDetectionConfig
│   └── tools: list[ToolDefinition]
│
├── TurnDetectionConfig (dataclass)
│   ├── type: Literal["server_vad", "none"] = "server_vad"
│   ├── threshold: float = 0.5
│   ├── prefix_padding_ms: int = 300
│   └── silence_duration_ms: int = 500
│
├── OpenAIRealtimeProvider
│   ├── __init__(config: OpenAIRealtimeConfig)
│   ├── connect() → None  # WebSocket connection
│   ├── disconnect() → None
│   ├── send_audio(chunk: bytes) → None
│   ├── receive() → AsyncIterator[RealtimeEvent]
│   ├── interrupt() → None  # Cancel response
│   ├── update_session(config: dict) → None
│   └── call_function(name: str, args: dict) → None
│
├── RealtimeEvent (Union type)
│   ├── SessionCreated
│   ├── SessionUpdated
│   ├── InputAudioBufferSpeechStarted
│   ├── InputAudioBufferSpeechStopped
│   ├── ConversationItemCreated
│   ├── ResponseAudioDelta
│   ├── ResponseAudioDone
│   ├── ResponseFunctionCallArguments
│   └── Error
│
└── Testes
    ├── test_realtime_config.py
    ├── test_realtime_websocket.py (mock server)
    ├── test_realtime_audio_flow.py
    ├── test_realtime_interruption.py
    └── test_realtime_tools.py
```

**Definition of Done**:
- [ ] WebSocket bidirectional funcionando
- [ ] Send audio → Receive audio streaming
- [ ] Interrupção (barge-in) via `response.cancel`
- [ ] Turn detection server-side
- [ ] Function calling
- [ ] Eventos tipados
- [ ] Reconnection com backoff
- [ ] Latência E2E < 300ms (medido)

### 3.2 Integração com Pipeline
**Arquivo**: `src/voice_pipeline/core/realtime_pipeline.py`

```
RealtimePipeline
├── Usa OpenAIRealtimeProvider diretamente
├── Bypass ASR/LLM/TTS separados
├── Mantém compatibilidade com EventEmitter
├── Suporta tools/functions
└── Fallback para pipeline tradicional se Realtime falhar
```

---

## 🚀 SPRINT 4: Audio Transport Layer
> **Duração Estimada**: 2 sprints
> **Objetivo**: Captura e playback de áudio real

### 4.1 Audio Transport Interface
**Arquivo**: `src/voice_pipeline/transport/base.py`

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator

class AudioTransport(ABC):
    """Interface para transporte de áudio."""

    @abstractmethod
    async def start(self) -> None:
        """Inicia captura/playback."""

    @abstractmethod
    async def stop(self) -> None:
        """Para captura/playback."""

    @abstractmethod
    async def read(self) -> AsyncIterator[bytes]:
        """Lê chunks de áudio do input."""

    @abstractmethod
    async def write(self, chunk: bytes) -> None:
        """Escreve chunk de áudio para output."""

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Sample rate do áudio."""

    @property
    @abstractmethod
    def channels(self) -> int:
        """Número de canais."""
```

### 4.2 Local Audio Transport
**Arquivo**: `src/voice_pipeline/transport/local.py`

```
LocalAudioTransport
├── Backend: sounddevice ou pyaudio
├── Device selection (input/output)
├── Echo cancellation flag
├── Resampling automático
└── Buffer management
```

### 4.3 WebSocket Transport
**Arquivo**: `src/voice_pipeline/transport/websocket.py`

```
WebSocketTransport
├── Cliente ou servidor
├── Binary frames (PCM16)
├── Reconnection logic
├── Heartbeat/ping
└── Compression opcional
```

### 4.4 WebRTC Transport (Futuro)
**Arquivo**: `src/voice_pipeline/transport/webrtc.py`

```
WebRTCTransport
├── aiortc integration
├── ICE/STUN/TURN
├── DTLS/SRTP
├── Signaling via WebSocket
└── Browser compatibility
```

**Definition of Done**:
- [ ] Interface `AudioTransport` abstrata
- [ ] `LocalAudioTransport` funciona com microfone/speaker
- [ ] `WebSocketTransport` bidirecional
- [ ] Testes com mock devices
- [ ] Exemplo funcional de captura → pipeline → playback

---

## 🚀 SPRINT 5: Testes E2E com Fixtures
> **Duração Estimada**: 1-2 sprints
> **Objetivo**: Confiança total em produção

### 5.1 Audio Fixtures
**Diretório**: `tests/fixtures/audio/`

```
fixtures/audio/
├── speech/
│   ├── pt-br-hello.wav          # "Olá, tudo bem?"
│   ├── pt-br-question.wav       # "Qual é a previsão do tempo?"
│   ├── pt-br-long.wav           # Frase longa (10s)
│   ├── en-us-hello.wav          # "Hello, how are you?"
│   └── multi-speaker.wav        # Múltiplas vozes
├── noise/
│   ├── silence.wav              # Silêncio puro
│   ├── white-noise.wav          # Ruído branco
│   ├── office-noise.wav         # Ruído de escritório
│   └── music-background.wav     # Música de fundo
├── edge-cases/
│   ├── very-quiet.wav           # Volume muito baixo
│   ├── very-loud.wav            # Volume alto (clipping)
│   ├── short-utterance.wav      # < 500ms
│   └── interruption.wav         # Fala interrompida
└── README.md                    # Documentação das fixtures
```

### 5.2 Mock Servers
**Diretório**: `tests/mocks/`

```python
# tests/mocks/openai_server.py
class MockOpenAIServer:
    """Mock server para testes de integração."""

    async def whisper_transcribe(self, audio: bytes) -> dict:
        """Simula resposta do Whisper."""
        return {"text": "Olá, tudo bem?", "language": "pt"}

    async def chat_completion(self, messages: list) -> AsyncIterator[dict]:
        """Simula streaming do GPT."""
        for token in ["Olá", "!", " Como", " posso", " ajudar", "?"]:
            yield {"choices": [{"delta": {"content": token}}]}

    async def tts_speech(self, text: str) -> bytes:
        """Retorna áudio fixture."""
        return load_fixture("speech/pt-br-hello.wav")
```

### 5.3 Integration Tests
**Arquivo**: `tests/integration/test_pipeline_e2e.py`

```python
@pytest.mark.integration
@pytest.mark.slow
class TestPipelineE2E:
    """Testes end-to-end do pipeline."""

    async def test_audio_to_audio_flow(self):
        """Testa fluxo completo: audio → ASR → LLM → TTS → audio."""

    async def test_barge_in_interruption(self):
        """Testa interrupção durante TTS."""

    async def test_provider_fallback(self):
        """Testa fallback quando provider falha."""

    async def test_latency_under_threshold(self):
        """Verifica latência < 1000ms P95."""
```

### 5.4 Performance Benchmarks
**Arquivo**: `tests/benchmarks/test_latency.py`

```python
@pytest.mark.benchmark
class TestLatencyBenchmarks:
    """Benchmarks de latência."""

    async def test_asr_latency(self, benchmark):
        """ASR deve processar em < 500ms."""

    async def test_llm_ttft(self, benchmark):
        """TTFT do LLM deve ser < 300ms."""

    async def test_tts_ttfa(self, benchmark):
        """TTFA do TTS deve ser < 200ms."""

    async def test_e2e_latency(self, benchmark):
        """E2E deve ser < 1000ms P95."""
```

**Definition of Done**:
- [ ] 10+ fixtures de áudio (PT-BR e EN-US)
- [ ] Mock servers para todos os providers
- [ ] Testes E2E cobrindo fluxo principal
- [ ] Testes de barge-in
- [ ] Benchmarks de latência com thresholds
- [ ] CI rodando testes de integração
- [ ] Coverage > 85%

---

## 📋 Resumo de Prioridades

### 🔴 Prioridade Alta (V1 Must-Have)
| Sprint | Entrega | Desbloqueio |
|--------|---------|-------------|
| **Sprint 1.1** | Ollama LLM | Uso offline |
| **Sprint 3** | OpenAI Realtime | Ultra-baixa latência |
| **Sprint 4.1-4.2** | Audio Transport | Demo funcional |
| **Sprint 5** | Testes E2E | Confiança produção |

### 🟡 Prioridade Média (V1 Should-Have)
| Sprint | Entrega | Desbloqueio |
|--------|---------|-------------|
| **Sprint 1.2** | Local TTS | Síntese offline |
| **Sprint 2** | whisper.cpp | ASR local |

### 🟢 Prioridade Baixa (V1.1)
| Sprint | Entrega | Desbloqueio |
|--------|---------|-------------|
| **Sprint 4.4** | WebRTC Transport | Browser nativo |
| - | WebRTC VAD | Alternativa leve |

---

## 📅 Timeline Proposta

```
Semana 1-2:  Sprint 1.1 - Ollama LLM Provider
             ████████████████████████████████

Semana 3:    Sprint 1.2 - Local TTS (Kokoro/Piper)
             ████████████████

Semana 4:    Sprint 2 - whisper.cpp ASR
             ████████████████

Semana 5-6:  Sprint 3 - OpenAI Realtime API
             ████████████████████████████████

Semana 7-8:  Sprint 4 - Audio Transport Layer
             ████████████████████████████████

Semana 9:    Sprint 5 - Testes E2E
             ████████████████

─────────────────────────────────────────────
Total: ~9 semanas para V1 completo
```

---

## 🎯 Critérios de Sucesso (V1)

| Métrica | Target | Stretch |
|---------|--------|---------|
| **Providers Implementados** | 7 (OpenAI x3, Ollama x2, Silero, whisper.cpp) | 9+ |
| **Latência E2E (P95)** | < 1000ms | < 500ms |
| **Latência Realtime** | < 300ms | < 200ms |
| **Test Coverage** | > 85% | > 90% |
| **Fixtures de Áudio** | 10+ | 20+ |
| **Documentação** | README + Exemplos | API Docs completa |

---

## 🔗 Dependências Entre Sprints

```
Sprint 1.1 (Ollama LLM)
    │
    └──► Sprint 1.2 (Local TTS) ──► [Stack Local Completo]
            │
            └──► Sprint 2 (whisper.cpp)

Sprint 3 (OpenAI Realtime) ──► [Standalone - Ultra Low Latency]

Sprint 4 (Audio Transport)
    │
    └──► Sprint 5 (Testes E2E) ──► [Production Ready]
```

---

## 📝 Próximos Passos Imediatos

1. **AGORA**: Escolher Sprint 1.1 ou Sprint 3 para iniciar
2. **Validar**: Confirmar se Ollama já está instalado localmente
3. **Definir**: Qual modelo Ollama usar (llama3.2, mistral, etc.)
4. **Criar**: Issue/task para cada sub-item do sprint escolhido

---

> **Pergunta**: Qual sprint você quer iniciar primeiro?
> - **Sprint 1.1**: Ollama LLM (uso offline)
> - **Sprint 3**: OpenAI Realtime (ultra-baixa latência)
> - **Sprint 4**: Audio Transport (demo funcional)
