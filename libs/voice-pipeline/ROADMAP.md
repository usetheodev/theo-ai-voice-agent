# Voice-Pipeline Roadmap

## Baseado em Evidências da Indústria

Este roadmap foi construído analisando os principais frameworks de voice AI:

| Framework | Fonte | Principais Aprendizados |
|-----------|-------|-------------------------|
| **Pipecat** | [GitHub](https://github.com/pipecat-ai/pipecat), [Docs](https://docs.pipecat.ai/guides/learn/pipeline) | Frame-based architecture, 40+ providers |
| **LiveKit Agents** | [GitHub](https://github.com/livekit/agents), [Docs](https://docs.livekit.io/agents/build/turns/) | Semantic turn detection, WebRTC native |
| **FastRTC** | [HuggingFace](https://huggingface.co/blog/fastrtc) | Python-first WebRTC, FastAPI integration |
| **Silero VAD** | [GitHub](https://github.com/snakers4/silero-vad) | <1ms inference, MIT license |

### Referências de Latência (Benchmarks da Indústria)

| Métrica | Target | Fonte |
|---------|--------|-------|
| End-to-end response | < 300ms | [Twilio](https://www.twilio.com/en-us/blog/developers/best-practices/guide-core-latency-ai-voice-agents) |
| Turn-taking delay | ~200ms | [Sierra AI](https://sierra.ai/blog/voice-latency) |
| ASR streaming | < 100ms | [AssemblyAI](https://www.assemblyai.com/blog/how-to-build-lowest-latency-voice-agent-vapi) |
| TTS TTFB | < 100ms | [Deepgram](https://deepgram.com/learn/low-latency-voice-ai) |

---

## Estratégia: OpenAI + Ollama + Silero

### Stack de Providers

| Stack | ASR | LLM | TTS | VAD | Uso |
|-------|-----|-----|-----|-----|-----|
| **Cloud** | OpenAI Whisper | OpenAI GPT-4 | OpenAI TTS | Silero | Produção |
| **Local** | whisper.cpp | Ollama | Ollama TTS | Silero | Dev/Testes |
| **Realtime** | OpenAI Realtime | OpenAI Realtime | OpenAI Realtime | Built-in | Ultra-low latency |

### Dependências

```
openai>=1.0.0          # ASR, LLM, TTS, Realtime
ollama                 # Local LLM/TTS
silero-vad             # VAD (torch)
whispercpp (opcional)  # Local ASR
webrtcvad              # VAD alternativo
```

---

## Fase 1: Providers Concretos (CRÍTICO)

> **Objetivo**: Tornar o framework utilizável com providers reais
> **Referência**: [Pipecat Services](https://github.com/pipecat-ai/pipecat/tree/main/src/pipecat/services)

### 1.1 Provider Base Infrastructure

| Task | Descrição | DoD (Definition of Done) |
|------|-----------|--------------------------|
| 1.1.1 | Criar `BaseProvider` abstrato | - Classe base com lifecycle hooks (`connect`, `disconnect`, `health_check`) <br> - Suporte a retry configurável <br> - Métricas integradas (latency, errors) <br> - Testes unitários |
| 1.1.2 | Implementar `ProviderConfig` | - Dataclass com timeout, retry_attempts, api_key <br> - Validação de configuração <br> - Suporte a env vars <br> - Documentação inline |
| 1.1.3 | Criar `ProviderHealth` | - Health check async <br> - Status enum (HEALTHY, DEGRADED, UNHEALTHY) <br> - Métricas de uptime <br> - Testes |

### 1.2 ASR Providers

| Task | Descrição | DoD |
|------|-----------|-----|
| 1.2.1 | **OpenAI Whisper API** | - Implementa `ASRInterface` <br> - Streaming com websocket <br> - Suporte a múltiplos idiomas <br> - Testes com áudio real (fixtures) <br> - Latência < 500ms medida |
| 1.2.2 | **Local Whisper (whisper.cpp)** | - Wrapper para whisper.cpp <br> - CPU/GPU detection <br> - Model download automático <br> - Benchmark de latência |

### 1.3 LLM Providers

| Task | Descrição | DoD |
|------|-----------|-----|
| 1.3.1 | **OpenAI GPT-4** | - Implementa `LLMInterface` <br> - Streaming tokens <br> - Function calling <br> - TTFT (Time to First Token) < 300ms <br> - Testes com mocks e reais |
| 1.3.2 | **Ollama Local** | - Modelos locais <br> - Auto-discovery de modelos <br> - GPU/CPU fallback <br> - Testes offline |
| 1.3.3 | **OpenAI Realtime API** | - WebSocket bidirectional <br> - Audio-to-audio native <br> - Interruption handling <br> - Voice selection |

### 1.4 TTS Providers

| Task | Descrição | DoD |
|------|-----------|-----|
| 1.4.1 | **OpenAI TTS** | - Implementa `TTSInterface` <br> - Streaming <br> - Múltiplas vozes (alloy, echo, fable, onyx, nova, shimmer) <br> - Speed control <br> - Testes |
| 1.4.2 | **Ollama Local TTS** | - Modelos locais <br> - Auto-discovery de modelos <br> - GPU/CPU fallback <br> - Testes offline |

### 1.5 VAD Providers

| Task | Descrição | DoD |
|------|-----------|-----|
| 1.5.1 | **Silero VAD** | - Implementa `VADInterface` <br> - < 1ms inference (CPU) <br> - Configuração de thresholds <br> - Speech probability output <br> - Testes com fixtures de áudio |
| 1.5.2 | **WebRTC VAD** | - Wrapper para py-webrtcvad <br> - Aggressiveness levels (0-3) <br> - Testes |

### Ordem de Implementação (Fase 1)

```
1. Provider Base (1.1) ──────► Desbloqueia todos os providers
2. Silero VAD (1.5.1) ───────► Desbloqueia turn-taking
3. OpenAI LLM (1.3.1) ───────► Core do pipeline
4. OpenAI TTS (1.4.1) ───────► Output de áudio
5. OpenAI ASR (1.2.1) ───────► Input de áudio
6. Ollama LLM (1.3.2) ───────► Testes locais
7. WebRTC VAD (1.5.2) ───────► VAD alternativo
8. whisper.cpp (1.2.2) ──────► ASR local
9. Ollama TTS (1.4.2) ───────► TTS local
10. OpenAI Realtime (1.3.3) ─► Audio-to-audio
```

---

## Fase 2: Integração de Áudio Real (CRÍTICO)

> **Objetivo**: Captura e playback de áudio real
> **Referência**: [FastRTC](https://fastrtc.org/), [LiveKit WebRTC](https://docs.livekit.io/home/)

### 2.1 Audio Transport Layer

| Task | Descrição | DoD |
|------|-----------|-----|
| 2.1.1 | Criar `AudioTransport` interface | - Abstract base class <br> - `start()`, `stop()`, `read()`, `write()` <br> - Sample rate negotiation <br> - Format conversion hooks |
| 2.1.2 | Implementar `LocalAudioTransport` | - PyAudio/sounddevice backend <br> - Device selection <br> - Echo cancellation flag <br> - Testes com mock devices |
| 2.1.3 | Implementar `WebSocketTransport` | - Bidirectional audio streaming <br> - Binary frames <br> - Reconnection logic <br> - Testes de integração |

### 2.2 WebRTC Integration

| Task | Descrição | DoD |
|------|-----------|-----|
| 2.2.1 | **WebRTC Transport** | - aiortc integration <br> - ICE candidate handling <br> - DTLS/SRTP <br> - Testes com browser |
| 2.2.2 | **Signaling Server** | - WebSocket signaling <br> - Room management <br> - SDP exchange <br> - Testes E2E |
| 2.2.3 | **FastRTC Integration** | - Mount on FastAPI <br> - Auto VAD <br> - Turn taking built-in <br> - Exemplo funcional |

### 2.3 Audio Processing

| Task | Descrição | DoD |
|------|-----------|-----|
| 2.3.1 | **Resampler** | - 8kHz ↔ 16kHz ↔ 24kHz ↔ 48kHz <br> - scipy.signal ou librosa <br> - Zero-copy quando possível <br> - Benchmark |
| 2.3.2 | **Echo Cancellation (AEC)** | - WebRTC AEC3 wrapper <br> - Reference signal tracking <br> - Testes com loopback |
| 2.3.3 | **Noise Suppression** | - RNNoise ou similar <br> - Configurable aggressiveness <br> - Testes com ruído |
| 2.3.4 | **Audio Buffer Manager** | - Jitter buffer <br> - Packet loss concealment <br> - Metrics (buffer underrun, overrun) |

---

## Fase 3: Turn-Taking Avançado

> **Objetivo**: Detecção natural de turnos como humanos
> **Referência**: [LiveKit Turn Detection](https://docs.livekit.io/agents/build/turns/), [Pipecat Smart Turn](https://github.com/pipecat-ai/smart-turn)

### 3.1 VAD-based Turn Detection

| Task | Descrição | DoD |
|------|-----------|-----|
| 3.1.1 | **Configuração de Thresholds** | - `min_silence_duration` (default 500ms) <br> - `min_speech_duration` (default 50ms) <br> - `activation_threshold` (0.5) <br> - Hot-reload de config |
| 3.1.2 | **Adaptive Silence Detection** | - Ajuste dinâmico baseado em contexto <br> - Noise floor tracking <br> - Testes |

### 3.2 Semantic Turn Detection

| Task | Descrição | DoD |
|------|-----------|-----|
| 3.2.1 | **End-of-Utterance Model** | - Modelo transformer leve (SmolLM-based) <br> - Inference < 50ms CPU <br> - Fine-tuning pipeline <br> - Integração com VAD |
| 3.2.2 | **STT Endpointing** | - Usar `is_final` do STT <br> - Punctuation-based detection <br> - Fallback para VAD |
| 3.2.3 | **Context-Aware Detection** | - "I understand, but..." não é fim <br> - Detecção de frases incompletas <br> - Testes com edge cases |

### 3.3 Barge-In (Interruptions)

| Task | Descrição | DoD |
|------|-----------|-----|
| 3.3.1 | **Interruption Detection** | - `min_interruption_duration` config <br> - `min_interruption_words` config <br> - Event: `on_user_interrupt` |
| 3.3.2 | **TTS Cancellation** | - Cancelar síntese em andamento <br> - Limpar buffer de saída <br> - Latência < 100ms |
| 3.3.3 | **False Positive Handling** | - `false_interruption_timeout` <br> - Resume speech option <br> - Testes com ruídos breves |
| 3.3.4 | **Graceful Truncation** | - Truncar resposta no ponto de interrupção <br> - Salvar contexto para retomada <br> - Testes |

---

## Fase 4: Resiliência e Observabilidade

> **Objetivo**: Produção-ready com debugging facilitado
> **Referência**: [OpenTelemetry AI Agents](https://opentelemetry.io/blog/2025/ai-agent-observability/), [Hamming AI](https://hamming.ai/)

### 4.1 Circuit Breaker

| Task | Descrição | DoD |
|------|-----------|-----|
| 4.1.1 | **CircuitBreaker Class** | - Estados: CLOSED, OPEN, HALF_OPEN <br> - `failure_threshold` configurável <br> - `recovery_timeout` <br> - Integração com pybreaker ou custom |
| 4.1.2 | **Provider Circuit Breakers** | - Cada provider com seu breaker <br> - Fallback automático <br> - Métricas de estado |
| 4.1.3 | **Health Checks** | - Endpoint `/health` <br> - Provider health aggregation <br> - Liveness/Readiness probes |

### 4.2 Retry e Fallback

| Task | Descrição | DoD |
|------|-----------|-----|
| 4.2.1 | **Retry com Backoff** | - Exponential backoff <br> - Jitter <br> - Max attempts configurável <br> - Exceções retryable vs não-retryable |
| 4.2.2 | **Provider Fallback Chain** | - Lista ordenada de providers <br> - Fallback automático <br> - Métricas de fallback usage |
| 4.2.3 | **Graceful Degradation** | - Modo offline básico <br> - Cache de respostas comuns <br> - Feature flags |

### 4.3 Observabilidade

| Task | Descrição | DoD |
|------|-----------|-----|
| 4.3.1 | **OpenTelemetry Tracing** | - Spans para cada componente <br> - Trace context propagation <br> - Exporters (Jaeger, OTLP) <br> - Semantic conventions |
| 4.3.2 | **Métricas Core** | - Latency P50/P95/P99 <br> - TTFT (Time to First Token) <br> - TTFA (Time to First Audio) <br> - Error rates por provider |
| 4.3.3 | **Voice-Specific Metrics** | - Barge-in count <br> - Turn duration <br> - Silence ratio <br> - Interruption rate |
| 4.3.4 | **Correlation IDs** | - Request ID em toda chain <br> - Baggage propagation <br> - Log correlation |
| 4.3.5 | **Dashboard Templates** | - Grafana dashboard JSON <br> - Prometheus queries <br> - Alerting rules |

---

## Fase 5: Testes de Integração E2E

> **Objetivo**: Confiança de que funciona em produção
> **Referência**: [Hamming AI Testing](https://hamming.ai/)

### 5.1 Test Infrastructure

| Task | Descrição | DoD |
|------|-----------|-----|
| 5.1.1 | **Audio Fixtures** | - Arquivos WAV de teste <br> - Múltiplos idiomas <br> - Cenários: silêncio, ruído, fala clara <br> - Documentação |
| 5.1.2 | **Mock Servers** | - Mock HTTP/WebSocket servers <br> - Configurable latency <br> - Failure injection |
| 5.1.3 | **Test Containers** | - Docker compose para providers <br> - Ollama container <br> - Isolated test environment |

### 5.2 Integration Tests

| Task | Descrição | DoD |
|------|-----------|-----|
| 5.2.1 | **Provider Integration Tests** | - Teste com cada provider real <br> - Skip se API key ausente <br> - Marcadores pytest (slow, integration) |
| 5.2.2 | **Pipeline E2E Tests** | - Audio → ASR → LLM → TTS → Audio <br> - Latency assertions <br> - Quality assertions |
| 5.2.3 | **Barge-In Tests** | - Simular interrupção mid-speech <br> - Verificar truncation <br> - Verificar estado |

### 5.3 Performance Tests

| Task | Descrição | DoD |
|------|-----------|-----|
| 5.3.1 | **Latency Benchmarks** | - Medir TTFT, TTFA, E2E <br> - Comparar providers <br> - CI integration |
| 5.3.2 | **Load Tests** | - Múltiplas conversas simultâneas <br> - Memory profiling <br> - Locust ou k6 scripts |
| 5.3.3 | **Chaos Tests** | - Provider failure simulation <br> - Network partition <br> - Recovery time |

---

## Fase 6: Developer Experience

> **Objetivo**: Framework fácil de usar e estender

### 6.1 CLI e Tooling

| Task | Descrição | DoD |
|------|-----------|-----|
| 6.1.1 | **CLI Tool** | - `voice-pipeline init` <br> - `voice-pipeline run` <br> - `voice-pipeline test-audio` <br> - Documentação |
| 6.1.2 | **Config Validation** | - Schema validation <br> - Helpful error messages <br> - Config examples |

### 6.2 Examples e Templates

| Task | Descrição | DoD |
|------|-----------|-----|
| 6.2.1 | **Basic Voice Agent** | - Exemplo mínimo funcional <br> - Comentários explicativos <br> - README |
| 6.2.2 | **Multi-Agent Example** | - Supervisor pattern <br> - Tool calling <br> - Handoffs |
| 6.2.3 | **WebRTC Browser Example** | - Frontend React/vanilla <br> - Backend FastAPI <br> - Deploy guide |
| 6.2.4 | **Local-Only Example** | - Ollama + Silero + whisper.cpp <br> - Zero API keys <br> - Testes offline |

### 6.3 Documentation

| Task | Descrição | DoD |
|------|-----------|-----|
| 6.3.1 | **API Reference** | - Docstrings completas <br> - Sphinx/MkDocs gerado <br> - Exemplos em cada classe |
| 6.3.2 | **Architecture Guide** | - Diagrams (Mermaid) <br> - Design decisions <br> - Extension points |
| 6.3.3 | **Deployment Guide** | - Docker <br> - Kubernetes <br> - Serverless options |

---

## Timeline Sugerida

```
Fase 1: Providers Concretos     [████████████████████] 3-4 semanas
Fase 2: Integração de Áudio     [████████████████    ] 2-3 semanas
Fase 3: Turn-Taking Avançado    [████████████        ] 2 semanas
Fase 4: Resiliência/Observ.     [████████████        ] 2 semanas
Fase 5: Testes E2E              [████████            ] 1-2 semanas
Fase 6: Developer Experience    [████████            ] 1-2 semanas
                                ─────────────────────────────────
                                Total: 11-15 semanas
```

---

## Priorização (MoSCoW)

### Must Have (V1)
- [x] Provider Base Infrastructure
- [ ] Silero VAD
- [ ] OpenAI GPT-4 LLM
- [ ] OpenAI TTS
- [ ] OpenAI Whisper ASR

### Should Have (V1)
- [ ] Ollama Local LLM
- [ ] WebRTC VAD
- [ ] WebSocket Transport
- [ ] Basic barge-in

### Could Have (V1.1)
- [ ] OpenAI Realtime API
- [ ] whisper.cpp local
- [ ] Ollama TTS
- [ ] Semantic turn detection

### Won't Have (V1)
- [ ] Telephony (SIP/PSTN)
- [ ] Video support
- [ ] Multi-language simultaneous
- [ ] Deepgram/AssemblyAI/ElevenLabs (futuro)

---

## Métricas de Sucesso

| Métrica | Target V1 | Stretch Goal |
|---------|-----------|--------------|
| E2E Latency (P95) | < 1000ms | < 500ms |
| TTFT | < 500ms | < 300ms |
| TTFA | < 800ms | < 500ms |
| Test Coverage | > 80% | > 90% |
| Provider Count | 5+ (OpenAI + Ollama + Silero) | 8+ |

---

## Checklist de Implementação (Fase 1)

### Provider Base (1.1)
- [ ] `BaseProvider` class
- [ ] `ProviderConfig` dataclass
- [ ] `ProviderHealth` enum e checker
- [ ] Testes unitários

### VAD (1.5)
- [ ] `SileroVADProvider`
- [ ] `WebRTCVADProvider`
- [ ] Audio fixtures para testes
- [ ] Benchmark de latência

### LLM (1.3)
- [ ] `OpenAILLMProvider`
- [ ] `OllamaLLMProvider`
- [ ] Streaming support
- [ ] Function calling support
- [ ] Testes com mocks

### TTS (1.4)
- [ ] `OpenAITTSProvider`
- [ ] `OllamaTTSProvider`
- [ ] Streaming support
- [ ] Voice selection
- [ ] Testes

### ASR (1.2)
- [ ] `OpenAIWhisperProvider`
- [ ] `WhisperCppProvider`
- [ ] Streaming support
- [ ] Multi-language
- [ ] Testes com fixtures

### Realtime (1.3.3)
- [ ] `OpenAIRealtimeProvider`
- [ ] WebSocket bidirectional
- [ ] Audio-to-audio
- [ ] Interruption handling

---

## Fontes e Referências

### Frameworks Analisados
- [Pipecat by Daily.co](https://github.com/pipecat-ai/pipecat)
- [LiveKit Agents](https://github.com/livekit/agents)
- [FastRTC by HuggingFace](https://fastrtc.org/)
- [TEN Framework](https://theten.ai/)

### Artigos Técnicos
- [Twilio: Core Latency in AI Voice Agents](https://www.twilio.com/en-us/blog/developers/best-practices/guide-core-latency-ai-voice-agents)
- [Sierra AI: Engineering low-latency voice agents](https://sierra.ai/blog/voice-latency)
- [Cresta: Engineering for Real-Time Voice Agent Latency](https://cresta.com/blog/engineering-for-real-time-voice-agent-latency)
- [Gladia: Concurrent pipelines for voice AI](https://www.gladia.io/blog/concurrent-pipelines-for-voice-ai)

### Observabilidade
- [OpenTelemetry: AI Agent Observability](https://opentelemetry.io/blog/2025/ai-agent-observability/)
- [Hamming AI: Voice Agent Testing](https://hamming.ai/)

### Padrões de Resiliência
- [pybreaker: Circuit Breaker for Python](https://github.com/danielfm/pybreaker)
- [Temporal: Error handling in distributed systems](https://temporal.io/blog/error-handling-in-distributed-systems)
