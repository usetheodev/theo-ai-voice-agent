# 📋 PLANO DE IMPLEMENTAÇÃO - AI Voice Agent Evolution

## 🎯 Princípios do Plano

1. **Incrementalidade**: Cada task entrega valor testável
2. **Compatibilidade**: Sistema continua funcionando durante toda evolução
3. **Feature Flags**: Novos componentes podem ser ativados/desativados
4. **Testes**: Cada entrega tem suite de testes
5. **Rollback Safety**: Sempre possível voltar para versão anterior

---

## 📊 PRIORIDADE 1: STREAMING E LATÊNCIA

### **EPIC 1.1: Migrar de Whisper.cpp para SimulStreaming**

#### **Task 1.1.1: Adicionar suporte a SimulStreaming (Parallel)**
**Estimativa**: 8h
**Dependências**: Nenhuma

**Microtasks**:
1. Adicionar `whisper-streaming` ao `requirements.txt`
2. Criar módulo `src/ai/asr_simulstreaming.py` com classe `SimulStreamingASR`
3. Implementar interface compatível com `WhisperASR` atual
4. Adicionar config `ASR_PROVIDER=whisper|simulstreaming` no `.env.example`
5. Adicionar testes unitários do provider SimulStreaming

**DoD (Definition of Done)**:
- [ ] `SimulStreamingASR` implementado com métodos `transcribe_stream(audio_iterator)`
- [ ] Testes unitários passando (mock de audio stream)
- [ ] Documentação do provider em `src/ai/README.md`
- [ ] Feature flag `ASR_PROVIDER` funcionando
- [ ] CI/CD passando sem quebrar nada existente

**Entregável Testável**:
```bash
# Teste manual
ASR_PROVIDER=simulstreaming python src/main.py
# Chamada de teste deve funcionar com novo ASR
```

---

#### **Task 1.1.2: Implementar streaming de partial results**
**Estimativa**: 6h
**Dependências**: Task 1.1.1

**Microtasks**:
1. Modificar `SimulStreamingASR` para emitir partial results
2. Criar event `ASRPartialResult` no event bus
3. Modificar `AudioPipeline` para processar partial results
4. Adicionar buffer de partial results antes de enviar ao LLM
5. Adicionar métricas `asr_partial_latency_ms` no Prometheus

**DoD**:
- [ ] Partial results emitidos a cada 500ms durante speech
- [ ] Partial results aparecem nos logs com flag `partial=True`
- [ ] Métricas de latency tracking (TTFR - Time To First Result)
- [ ] Testes de integração: audio longo → múltiplos partials
- [ ] Documentação de eventos no `src/orchestrator/README.md`

**Entregável Testável**:
```bash
# Teste: Falar por 5 segundos, ver partial results nos logs
# Verificar métrica: curl http://localhost:8001/metrics | grep asr_partial
```

---

#### **Task 1.1.3: Criar strategy de fallback Whisper ↔ SimulStreaming**
**Estimativa**: 4h
**Dependências**: Task 1.1.2

**Microtasks**:
1. Criar classe `ASRRouter` em `src/ai/asr_router.py`
2. Implementar health check para SimulStreaming (latency threshold)
3. Adicionar fallback automático para WhisperASR se SimulStreaming falhar
4. Adicionar métrica `asr_provider_active{provider="whisper|simulstreaming"}`
5. Adicionar alert no Grafana para fallback events

**DoD**:
- [ ] `ASRRouter` seleciona provider baseado em health
- [ ] Fallback acontece em <50ms se SimulStreaming crashar
- [ ] Métrica Prometheus mostra provider ativo
- [ ] Testes de falha simulada (mock de crash)
- [ ] Dashboard Grafana atualizado com painel ASR Provider

**Entregável Testável**:
```bash
# Simular falha do SimulStreaming
# Sistema deve continuar funcionando com Whisper
kill -9 $(pgrep -f simulstreaming)  # Simulação
# Verificar logs: "ASR fallback to whisper"
```

---

### **EPIC 1.2: Implementar Sentence-Level TTS Streaming**

#### **Task 1.2.1: Refatorar LLM para streaming sentence-by-sentence**
**Estimativa**: 6h
**Dependências**: Nenhuma

**Microtasks**:
1. Criar classe `SentenceDetector` em `src/ai/sentence_detector.py`
2. Implementar regex para detectar fim de sentença (`.!?。！？`)
3. Modificar `QwenLLM.generate_response()` para emitir generator de sentenças
4. Adicionar buffer para incomplete sentences
5. Adicionar testes unitários com textos multi-sentença

**DoD**:
- [ ] `SentenceDetector` identifica corretamente fim de sentença
- [ ] Generator emite sentenças assim que detectadas
- [ ] Sentenças incompletas bufferizadas até término
- [ ] Testes com casos edge (sem pontuação, múltiplos pontos)
- [ ] Benchmark: latency para primeira sentença <200ms

**Entregável Testável**:
```python
# Teste unitário
detector = SentenceDetector()
for sentence in detector.process("Olá! Como vai? Tudo bem."):
    print(sentence)
# Output: "Olá!", "Como vai?", "Tudo bem."
```

---

#### **Task 1.2.2: Pipeline LLM → TTS sentence-by-sentence**
**Estimativa**: 8h
**Dependências**: Task 1.2.1

**Microtasks**:
1. Criar classe `StreamingTTSProcessor` em `src/ai/tts_streaming.py`
2. Modificar `main.py` para processar sentenças em pipeline
3. Implementar queue assíncrona para sentenças aguardando TTS
4. Adicionar sending pacing (20ms entre RTP packets)
5. Adicionar métricas `llm_sentence_latency_ms`, `tts_sentence_latency_ms`

**DoD**:
- [ ] Primeira sentença processada antes do LLM terminar resposta completa
- [ ] TTS streaming para cada sentença independentemente
- [ ] Queue limpa ao final da resposta
- [ ] Métricas mostram latency por sentença
- [ ] Testes de integração: LLM response → múltiplos TTS calls

**Entregável Testável**:
```bash
# Teste: Fazer pergunta que gera resposta longa (3+ sentenças)
# Primeira sentença deve tocar antes de LLM terminar
# Verificar logs: "TTS started for sentence 1/3"
```

---

#### **Task 1.2.3: Otimizar TTS TTFB com pre-warming**
**Estimativa**: 4h
**Dependências**: Task 1.2.2

**Microtasks**:
1. Implementar model pre-loading no startup do TTS
2. Criar warmup sequence (gerar 5 sentenças dummy)
3. Adicionar caching de voice embeddings (se aplicável)
4. Implementar thread pool para TTS paralelo
5. Adicionar métrica `tts_ttfb_ms` (Time To First Byte)

**DoD**:
- [ ] Modelo TTS carregado na memória ao iniciar sistema
- [ ] TTFB <50ms após warmup
- [ ] Thread pool permite 3+ TTS concurrent
- [ ] Métrica TTFB tracking no Prometheus
- [ ] Documentação de tuning parameters

**Entregável Testável**:
```bash
# Após startup, primeira chamada TTS deve ter <50ms TTFB
curl http://localhost:8001/metrics | grep tts_ttfb_ms
# p50 < 50ms, p95 < 80ms
```

---

### **EPIC 1.3: Substituir WebRTC VAD por TEN VAD**

#### **Task 1.3.1: Adicionar TEN VAD como provider alternativo**
**Estimativa**: 6h
**Dependências**: Nenhuma

**Microtasks**:
1. Adicionar `ten-vad` (ou `sherpa-onnx` com TEN VAD) ao `requirements.txt`
2. Baixar modelo TEN VAD para `models/ten-vad/ten-vad.onnx`
3. Criar classe `TENVADProvider` em `src/audio/vad_ten.py`
4. Implementar interface compatível com VAD atual
5. Adicionar config `VAD_PROVIDER=webrtc|ten` no `.env.example`

**DoD**:
- [ ] `TENVADProvider` implementado com método `process_frame(audio)`
- [ ] Modelo TEN VAD downloaded automaticamente se não existir
- [ ] Feature flag `VAD_PROVIDER` funcionando
- [ ] Testes unitários com audio samples
- [ ] Benchmark: latency <2ms por frame (10ms audio)

**Entregável Testável**:
```bash
# Teste com novo VAD
VAD_PROVIDER=ten python src/main.py
# Fazer chamada e verificar logs: "Using TEN VAD"
```

---

#### **Task 1.3.2: Comparação side-by-side WebRTC vs TEN VAD**
**Estimativa**: 4h
**Dependências**: Task 1.3.1

**Microtasks**:
1. Criar script `scripts/benchmark_vad.py`
2. Preparar dataset de audio com speech/silence marcado
3. Calcular Precision/Recall/F1 para ambos VADs
4. Gerar relatório markdown com resultados
5. Adicionar dashboard Grafana com métricas VAD

**DoD**:
- [ ] Script benchmark executável com dataset
- [ ] Relatório gerado em `docs/VAD_BENCHMARK.md`
- [ ] Métricas: Precision, Recall, False Positive Rate
- [ ] Comparação de latency (WebRTC vs TEN)
- [ ] Recomendação de qual usar baseado em métricas

**Entregável Testável**:
```bash
# Executar benchmark
python scripts/benchmark_vad.py --dataset tests/fixtures/vad_dataset
# Output: docs/VAD_BENCHMARK.md
# Exemplo: TEN VAD precision: 97.2%, WebRTC: 89.3%
```

---

#### **Task 1.3.3: Migração gradual para TEN VAD como default**
**Estimativa**: 2h
**Dependências**: Task 1.3.2

**Microtasks**:
1. Atualizar `.env.example` com `VAD_PROVIDER=ten` (default)
2. Atualizar `config/default.yaml` com TEN VAD settings
3. Adicionar migration guide em `docs/MIGRATION_TEN_VAD.md`
4. Atualizar README.md principal
5. Deprecation warning se usar `VAD_PROVIDER=webrtc`

**DoD**:
- [ ] TEN VAD é o default em novas instalações
- [ ] WebRTC VAD ainda funciona (backward compatibility)
- [ ] Logs mostram deprecation warning se usar WebRTC
- [ ] Documentação atualizada
- [ ] CI/CD testa ambos providers

**Entregável Testável**:
```bash
# Instalação nova usa TEN VAD por padrão
docker-compose up
# Verificar logs: "VAD Provider: ten-vad (default)"
```

---

## 📊 PRIORIDADE 2: MULTI-PROVIDER ARCHITECTURE

### **EPIC 2.1: Criar Abstração de Providers**

#### **Task 2.1.1: Definir interfaces Python para providers**
**Estimativa**: 4h
**Dependências**: Nenhuma

**Microtasks**:
1. Criar `src/ai/interfaces.py` com Protocol classes
2. Definir `ASRProviderInterface` (métodos: `transcribe_stream`, `get_capabilities`)
3. Definir `LLMProviderInterface` (métodos: `generate_stream`, `count_tokens`)
4. Definir `TTSProviderInterface` (métodos: `synthesize_stream`, `get_voices`)
5. Definir `ProviderCapabilities` dataclass

**DoD**:
- [ ] Interfaces documentadas com docstrings completas
- [ ] Type hints para todos métodos e parâmetros
- [ ] Exemplo de implementação em docstring
- [ ] Testes de type checking com mypy
- [ ] README explicando arquitetura de providers

**Entregável Testável**:
```python
# Verificar type checking
mypy src/ai/interfaces.py
# Success: no issues found
```

---

#### **Task 2.1.2: Refatorar providers existentes para interfaces**
**Estimativa**: 6h
**Dependências**: Task 2.1.1

**Microtasks**:
1. Refatorar `WhisperASR` e `SimulStreamingASR` para `ASRProviderInterface`
2. Refatorar `QwenLLM` para `LLMProviderInterface`
3. Refatorar `KokoroTTS` para `TTSProviderInterface`
4. Adicionar método `get_capabilities()` em cada provider
5. Atualizar testes existentes

**DoD**:
- [ ] Todos providers implementam interfaces corretamente
- [ ] Type checking passa (mypy)
- [ ] Capabilities retornadas corretamente (latency, languages, etc.)
- [ ] Testes existentes continuam passando
- [ ] Nenhuma regressão funcional

**Entregável Testável**:
```python
# Teste de interface compliance
from src.ai.interfaces import ASRProviderInterface
assert isinstance(WhisperASR(), ASRProviderInterface)
```

---

#### **Task 2.1.3: Criar ProviderRegistry e ProviderFactory**
**Estimativa**: 6h
**Dependências**: Task 2.1.2

**Microtasks**:
1. Criar `src/ai/provider_registry.py`
2. Implementar `ProviderRegistry.register(id, provider_class)`
3. Implementar `ProviderFactory.create(id, config)`
4. Adicionar auto-discovery de providers (annotations)
5. Adicionar validação de config por provider

**DoD**:
- [ ] Registry permite registrar/listar providers
- [ ] Factory cria instances com config validation
- [ ] Auto-discovery funciona via decorators
- [ ] Testes de registry/factory
- [ ] Documentação de como adicionar novo provider

**Entregável Testável**:
```python
# Registrar e criar provider
registry = ProviderRegistry()
registry.register("whisper", WhisperASR)
asr = ProviderFactory.create("whisper", {"model": "base"})
assert asr.get_capabilities().provider_id == "whisper"
```

---

### **EPIC 2.2: Implementar Failover Chain**

#### **Task 2.2.1: Criar sistema de health checks**
**Estimativa**: 8h
**Dependências**: Task 2.1.3

**Microtasks**:
1. Criar `src/ai/health_monitor.py` com classe `HealthMonitor`
2. Implementar health check periódico (a cada 30s) para cada provider
3. Adicionar estados: `healthy`, `degraded`, `unhealthy`
4. Implementar métricas de health (latency p95, error rate)
5. Adicionar circuit breaker pattern (3 failures → open circuit)

**DoD**:
- [ ] Health checks rodando para todos providers
- [ ] Estados de health atualizados em tempo real
- [ ] Circuit breaker abre após threshold failures
- [ ] Métricas Prometheus: `provider_health{provider="X",state="Y"}`
- [ ] Testes de health check com mock failures

**Entregável Testável**:
```bash
# Ver health de providers
curl http://localhost:8001/health/providers
# Output: {"asr": {"whisper": "healthy", "simulstreaming": "healthy"}}
```

---

#### **Task 2.2.2: Implementar ProviderRouter com failover**
**Estimativa**: 8h
**Dependências**: Task 2.2.1

**Microtasks**:
1. Criar `src/ai/provider_router.py` com classe `ProviderRouter`
2. Implementar chain: Local (healthy) → Local (degraded) → Cloud
3. Adicionar retry logic (2 retries com exponential backoff)
4. Implementar timeout per provider (5s default)
5. Adicionar métricas de failover events

**DoD**:
- [ ] Router seleciona provider baseado em health + priority
- [ ] Failover acontece automaticamente em <50ms
- [ ] Retries não bloqueiam outras requisições
- [ ] Métricas: `provider_failover_total{from="X",to="Y"}`
- [ ] Testes de failover chain completa

**Entregável Testável**:
```python
# Simular falha de provider local
health_monitor.mark_unhealthy("whisper")
# Router deve usar cloud provider automaticamente
result = router.route("asr").transcribe(audio)
# Verificar log: "Failover: whisper → deepgram"
```

---

#### **Task 2.2.3: Configuração declarativa de failover chain**
**Estimativa**: 4h
**Dependências**: Task 2.2.2

**Microtasks**:
1. Criar schema YAML para failover config em `config/failover.yaml`
2. Implementar parser de config em `src/ai/failover_config.py`
3. Adicionar validação de config (providers existem, priorities únicas)
4. Documentar exemplos de config em `docs/FAILOVER_CONFIG.md`
5. Adicionar hot-reload de config (SIGHUP)

**DoD**:
- [ ] Config YAML define chain por tipo (ASR, LLM, TTS)
- [ ] Parser carrega e valida config
- [ ] Hot-reload funciona sem restart
- [ ] Exemplos de config para diversos cenários
- [ ] Testes de parsing e validation

**Entregável Testável**:
```yaml
# config/failover.yaml
asr:
  providers:
    - id: simulstreaming
      priority: 1
      conditions: {max_latency_ms: 150}
    - id: whisper
      priority: 2
    - id: deepgram
      priority: 3
      cloud: true
```

---

### **EPIC 2.3: Adicionar Deepgram como Cloud ASR**

#### **Task 2.3.1: Implementar DeepgramASR provider**
**Estimativa**: 6h
**Dependências**: Task 2.1.2

**Microtasks**:
1. Adicionar `deepgram-sdk` ao `requirements.txt`
2. Criar `src/ai/asr_deepgram.py` com classe `DeepgramASR`
3. Implementar streaming via WebSocket
4. Adicionar config `DEEPGRAM_API_KEY` no `.env.example`
5. Implementar retry logic para transient errors

**DoD**:
- [ ] `DeepgramASR` implementa `ASRProviderInterface`
- [ ] Streaming funciona com partial results
- [ ] API key validation no startup
- [ ] Testes unitários com mock da API
- [ ] Documentação de setup em `docs/DEEPGRAM_SETUP.md`

**Entregável Testável**:
```bash
# Teste com Deepgram (requer API key)
ASR_PROVIDER=deepgram DEEPGRAM_API_KEY=xxx python src/main.py
# Fazer chamada e verificar transcription funciona
```

---

#### **Task 2.3.2: Cost tracking para cloud providers**
**Estimativa**: 4h
**Dependências**: Task 2.3.1

**Microtasks**:
1. Criar `src/ai/cost_tracker.py` com classe `CostTracker`
2. Implementar tracking de usage (minutes, tokens, characters)
3. Adicionar custo por provider (Deepgram: $0.0043/min)
4. Implementar alertas de custo (email se >threshold)
5. Adicionar dashboard Grafana com custo estimado

**DoD**:
- [ ] Usage tracking para todos cloud providers
- [ ] Custo estimado calculado em tempo real
- [ ] Alertas enviados se ultrapassar threshold
- [ ] Métrica: `cloud_cost_usd{provider="deepgram"}`
- [ ] Dashboard mostra custo do dia/semana/mês

**Entregável Testável**:
```bash
# Após usar Deepgram por 10 minutos
curl http://localhost:8001/metrics/cost
# Output: {"deepgram": {"minutes": 10, "estimated_cost_usd": 0.043}}
```

---

### **EPIC 2.4: Adicionar Claude Haiku como Cloud LLM**

#### **Task 2.4.1: Implementar ClaudeHaikuLLM provider**
**Estimativa**: 6h
**Dependências**: Task 2.1.2

**Microtasks**:
1. Adicionar `anthropic` SDK ao `requirements.txt`
2. Criar `src/ai/llm_claude.py` com classe `ClaudeHaikuLLM`
3. Implementar streaming via SSE (Server-Sent Events)
4. Adicionar config `ANTHROPIC_API_KEY` no `.env.example`
5. Implementar rate limiting client-side (respects 429)

**DoD**:
- [ ] `ClaudeHaikuLLM` implementa `LLMProviderInterface`
- [ ] Streaming funciona token-by-token
- [ ] Rate limiting não quebra sistema
- [ ] Testes com mock da API Anthropic
- [ ] Documentação em `docs/CLAUDE_SETUP.md`

**Entregável Testável**:
```bash
# Teste com Claude (requer API key)
LLM_PROVIDER=claude ANTHROPIC_API_KEY=xxx python src/main.py
# Fazer chamada e verificar response gerada
```

---

#### **Task 2.4.2: A/B testing framework (Claude vs Qwen)**
**Estimativa**: 6h
**Dependências**: Task 2.4.1

**Microtasks**:
1. Criar `src/ai/ab_testing.py` com classe `ABTestManager`
2. Implementar split traffic (50/50, 70/30, etc.)
3. Adicionar logging de responses para comparação
4. Implementar métricas de quality (user ratings, retry rate)
5. Criar script de análise `scripts/analyze_ab_test.py`

**DoD**:
- [ ] Traffic split configurável via config
- [ ] Responses logged com provider_id para análise
- [ ] Métricas: `llm_response_rating{provider="X"}`
- [ ] Script gera relatório de comparação
- [ ] Documentação de como rodar A/B test

**Entregável Testável**:
```yaml
# config/ab_test.yaml
llm:
  enabled: true
  providers:
    - id: qwen
      weight: 70
    - id: claude
      weight: 30
  duration_days: 7
```

---

## 📊 PRIORIDADE 3: PRODUCTION READINESS

### **EPIC 3.1: Adicionar rtpengine para NAT Traversal**

#### **Task 3.1.1: Setup rtpengine via Docker Compose**
**Estimativa**: 4h
**Dependências**: Nenhuma

**Microtasks**:
1. Adicionar service `rtpengine` no `docker-compose.yml`
2. Criar config `docker/rtpengine/rtpengine.conf`
3. Configurar interfaces (external + internal)
4. Expor porta NG protocol (2223) para voiceagent
5. Adicionar healthcheck para rtpengine

**DoD**:
- [ ] rtpengine container sobe com `docker-compose up`
- [ ] Healthcheck passa (rtpengine responde a pings)
- [ ] Portas RTP expostas (30000-40000)
- [ ] Logs mostram rtpengine initialized
- [ ] Documentação em `docs/RTPENGINE_SETUP.md`

**Entregável Testável**:
```bash
docker-compose up -d rtpengine
docker logs rtpengine | grep "rtpengine started"
# Testar NG protocol
echo "ping" | nc -u 127.0.0.1 2223
```

---

#### **Task 3.1.2: Implementar cliente NG protocol**
**Estimativa**: 8h
**Dependências**: Task 3.1.1

**Microtasks**:
1. Criar `src/rtp/rtpengine_client.py` com classe `RTPEngineClient`
2. Implementar comandos: `offer`, `answer`, `delete`
3. Adicionar parsing de responses (bencode format)
4. Implementar connection pooling para NG socket
5. Adicionar timeout e retry logic

**DoD**:
- [ ] Cliente envia comandos NG e recebe responses
- [ ] Comandos offer/answer/delete funcionam
- [ ] Bencode parsing correto (encode + decode)
- [ ] Testes unitários com mock rtpengine
- [ ] Documentação de protocolo NG

**Entregável Testável**:
```python
client = RTPEngineClient("127.0.0.1:2223")
response = client.offer(session_id="test", sdp=sdp_offer)
assert response["result"] == "ok"
assert "sdp" in response
```

---

#### **Task 3.1.3: Integração SIP Server ↔ rtpengine**
**Estimativa**: 8h
**Dependências**: Task 3.1.2

**Microtasks**:
1. Modificar `src/sip/protocol.py` para usar rtpengine no INVITE
2. Passar SDP através de rtpengine (rewrite IP/ports)
3. Conectar RTP Server ao internal endpoint do rtpengine
4. Adicionar feature flag `RTP_PROXY_ENABLED=true/false`
5. Testar NAT traversal com cliente externo

**DoD**:
- [ ] SIP INVITE passa SDP por rtpengine
- [ ] SDP reescrito com IP externo correto
- [ ] RTP flui: Cliente → rtpengine → RTP Server
- [ ] Feature flag permite desabilitar proxy (direct RTP)
- [ ] Testes de integração SIP+RTP+rtpengine

**Entregável Testável**:
```bash
# Cliente externo (atrás de NAT) faz chamada
# SDP deve conter IP público do rtpengine
# Áudio bidirecional deve funcionar
RTP_PROXY_ENABLED=true docker-compose up
# Fazer chamada de rede externa
```

---

### **EPIC 3.2: Implementar Turn Detection**

#### **Task 3.2.1: Implementar detector de fim de turno (EOT)**
**Estimativa**: 6h
**Dependências**: EPIC 1.3 (TEN VAD)

**Microtasks**:
1. Criar `src/audio/turn_detector.py` com classe `TurnDetector`
2. Implementar lógica: silence duration > threshold → EOT
3. Adicionar config vars do `.env.example` (já existem)
4. Integrar com VAD para detectar speech/silence
5. Emitir evento `TurnEndDetected` no event bus

**DoD**:
- [ ] EOT detectado após silence > `TURN_DETECTION_PAUSE_DURATION`
- [ ] Mínimo de speech duration validado (`TURN_DETECTION_MIN_DURATION`)
- [ ] Evento emitido corretamente
- [ ] Testes com audio sintético (speech + silence)
- [ ] Métricas: `turn_detection_latency_ms`

**Entregável Testável**:
```python
# Audio: 2s speech + 1.5s silence (threshold 1.0s)
detector = TurnDetector(pause_duration=1.0, min_duration=0.3)
events = list(detector.process(audio_frames))
assert events[-1].type == "turn_end"
```

---

#### **Task 3.2.2: Pipeline adaptativo baseado em turn detection**
**Estimativa**: 6h
**Dependências**: Task 3.2.1

**Microtasks**:
1. Modificar `AudioPipeline` para aguardar EOT antes de enviar ao ASR
2. Adicionar buffer de "holdback" (300ms) para evitar cut-off
3. Implementar flush do buffer quando EOT confirmado
4. Adicionar modo `TURN_DETECTION_ENABLED=true/false`
5. Comparar latency com/sem turn detection

**DoD**:
- [ ] ASR recebe audio completo apenas após EOT
- [ ] Holdback buffer previne cortes prematuros
- [ ] Modo pode ser desabilitado (backward compatibility)
- [ ] Testes A/B: latency vs quality tradeoff
- [ ] Documentação de tuning parameters

**Entregável Testável**:
```bash
# Com turn detection
TURN_DETECTION_ENABLED=true python src/main.py
# Falar "Olá" + pausa 1s → ASR processa
# Falar "Olá" + continuar falando → ASR aguarda EOT
```

---

### **EPIC 3.3: Adicionar Barge-in Support**

#### **Task 3.3.1: Implementar detecção de interrupção**
**Estimativa**: 6h
**Dependências**: Task 3.2.1

**Microtasks**:
1. Criar `src/audio/interrupt_detector.py` com classe `InterruptDetector`
2. Detectar speech while bot is speaking
3. Adicionar config `INTERRUPTION_ENABLED` e `INTERRUPTION_MIN_DURATION`
4. Emitir evento `InterruptDetected` no event bus
5. Adicionar state tracking: `user_speaking`, `bot_speaking`, `both_speaking`

**DoD**:
- [ ] Interrupt detectado quando user fala durante bot response
- [ ] Mínimo de speech duration validado (evitar false positives)
- [ ] Evento emitido com timestamp
- [ ] Testes com audio overlap (bot + user simultâneo)
- [ ] Métricas: `interrupt_events_total`

**Entregável Testável**:
```python
# Bot falando + user interrompe após 0.8s
detector = InterruptDetector(min_duration=0.8)
detector.set_bot_speaking(True)
# Simular user speech
assert detector.process(user_audio) == InterruptEvent(...)
```

---

#### **Task 3.3.2: Cancelamento de TTS em progresso**
**Estimativa**: 8h
**Dependências**: Task 3.3.1

**Microtasks**:
1. Modificar `StreamingTTSProcessor` para suportar cancelamento
2. Implementar método `cancel_current_playback()`
3. Parar envio de RTP packets imediatamente
4. Limpar queue de sentenças pendentes
5. Notificar LLM para parar geração (se streaming)

**DoD**:
- [ ] TTS para de enviar RTP <50ms após interrupt
- [ ] Queue limpa sem processar sentenças pendentes
- [ ] LLM streaming cancelado (economiza compute)
- [ ] Testes de cancelamento em diversos estágios
- [ ] Métricas: `tts_cancellations_total`

**Entregável Testável**:
```bash
# Bot responde pergunta longa (5+ sentenças)
# User interrompe após 2 sentenças
# Bot para imediatamente
# Verificar logs: "TTS cancelled due to interrupt"
```

---

#### **Task 3.3.3: Re-engajamento pós-interrupção**
**Estimativa**: 6h
**Dependências**: Task 3.3.2

**Microtasks**:
1. Criar state machine para gerenciar interrupts
2. Capturar nova user speech após interrupt
3. Enviar contexto de interrupção ao LLM (o que foi dito antes)
4. Implementar response acknowledging interrupt ("Ah, entendi...")
5. Adicionar testes de conversação com múltiplos interrupts

**DoD**:
- [ ] State machine gerencia: speaking → interrupted → listening → responding
- [ ] LLM recebe contexto da interrupção
- [ ] Bot acknowledges interrupção de forma natural
- [ ] Conversation history mantém interrupted responses
- [ ] Testes de flow completo com interrupts

**Entregável Testável**:
```
User: "Me fale sobre..."
Bot: "Claro, sobre isso podemos dizer que primeiramente..."
User: "PARA! Me fale sobre Y"  [interrupt]
Bot: "Entendi, mudando para Y. Sobre Y..." [acknowledges + pivots]
```

---

### **EPIC 3.4: WebSocket API para Control Plane**

#### **Task 3.4.1: Implementar WebSocket server**
**Estimativa**: 8h
**Dependências**: Nenhuma

**Microtasks**:
1. Adicionar `websockets` library ao `requirements.txt`
2. Criar `src/api/websocket_server.py` com classe `WebSocketServer`
3. Implementar handshake e session management
4. Adicionar authentication (token-based)
5. Expor porta WS (8002) no docker-compose

**DoD**:
- [ ] WebSocket server aceita conexões em ws://localhost:8002
- [ ] Authentication obrigatória (rejeita sem token)
- [ ] Múltiplas sessões simultâneas suportadas
- [ ] Testes de conexão e handshake
- [ ] Documentação de autenticação

**Entregável Testável**:
```bash
# Testar conexão WebSocket
websocat ws://localhost:8002 -H="Authorization: Bearer test_token"
# Deve conectar e manter conexão aberta
```

---

#### **Task 3.4.2: Implementar eventos do ciclo de vida da chamada**
**Estimativa**: 6h
**Dependências**: Task 3.4.1

**Microtasks**:
1. Definir mensagens JSON para eventos: `call.started`, `call.ended`, `audio.transcribed`, etc.
2. Implementar broadcasting de eventos para WS clients
3. Adicionar filtros de eventos (client subscribe apenas ao que precisa)
4. Implementar heartbeat (ping/pong) a cada 30s
5. Adicionar schema validation (jsonschema)

**DoD**:
- [ ] Eventos JSON bem definidos e documentados
- [ ] Broadcasting funciona para múltiplos clients
- [ ] Filtros permitem subscribe seletivo
- [ ] Heartbeat detecta conexões mortas
- [ ] Schema validation rejeita mensagens inválidas

**Entregável Testável**:
```json
// Client recebe eventos via WebSocket
{"type": "call.started", "session_id": "abc", "timestamp": "..."}
{"type": "audio.transcribed", "session_id": "abc", "text": "Olá"}
{"type": "llm.response", "session_id": "abc", "text": "Como vai?"}
{"type": "call.ended", "session_id": "abc", "duration": 45.2}
```

---

#### **Task 3.4.3: Comandos de controle via WebSocket**
**Estimativa**: 8h
**Dependências**: Task 3.4.2

**Microtasks**:
1. Implementar comando `session.create` (inicia nova sessão)
2. Implementar comando `session.terminate` (encerra sessão)
3. Implementar comando `tts.cancel` (cancela TTS em progresso)
4. Implementar comando `config.update` (hot-reload de settings)
5. Adicionar rate limiting de comandos (anti-abuse)

**DoD**:
- [ ] Comandos executados e retornam success/error
- [ ] Rate limiting previne spam (10 commands/min)
- [ ] Testes de cada comando
- [ ] Documentação de API em `docs/WEBSOCKET_API.md`
- [ ] Exemplos de client em Python e JavaScript

**Entregável Testável**:
```json
// Client envia comando
→ {"type": "command", "action": "session.terminate", "session_id": "abc"}
← {"type": "response", "status": "ok", "message": "Session terminated"}

// Client envia comando inválido
→ {"type": "command", "action": "invalid"}
← {"type": "error", "code": 400, "message": "Invalid command"}
```

---

## 📊 RESUMO DO PLANO

### **Estatísticas**

| Prioridade | EPICs | Tasks | Estimativa Total |
|------------|-------|-------|------------------|
| P1 - Streaming | 3 | 9 | 58h (~7 dias) |
| P2 - Multi-Provider | 4 | 12 | 74h (~9 dias) |
| P3 - Production | 4 | 12 | 80h (~10 dias) |
| **TOTAL** | **11** | **33** | **212h (~26 dias)** |

### **Cronograma Sugerido (1 dev full-time)**

- **Sprint 1 (2 semanas)**: P1 - Streaming e Latência
- **Sprint 2 (2 semanas)**: P2 - Multi-Provider Architecture
- **Sprint 3 (2 semanas)**: P3 - Production Readiness
- **Sprint 4 (1 semana)**: Buffer, testes E2E, documentação final

**Total: ~7 semanas (1.75 meses)**

### **Milestones**

✅ **M1 (Sprint 1)**: Latency <300ms achieved
✅ **M2 (Sprint 2)**: Multi-provider failover working
✅ **M3 (Sprint 3)**: Production-ready (NAT, barge-in, WS API)
✅ **M4 (Sprint 4)**: Full documentation + E2E tests

---

## 🔄 ESTRATÉGIA DE ROLLOUT

### **Feature Flags Obrigatórias**

Todas as features devem ter flags:
```bash
# .env
ASR_PROVIDER=whisper|simulstreaming|deepgram
LLM_PROVIDER=qwen|claude
VAD_PROVIDER=webrtc|ten
RTP_PROXY_ENABLED=true|false
TURN_DETECTION_ENABLED=true|false
INTERRUPTION_ENABLED=true|false
```

### **Rollback Plan**

Cada task deve permitir rollback via:
1. Feature flag disable
2. Git revert do merge commit
3. Docker image anterior (tagged)

---

## 📈 MÉTRICAS DE SUCESSO

### **KPIs por Prioridade**

**P1 - Streaming**:
- [ ] Latency end-to-end P95 <300ms
- [ ] ASR TTFR (Time To First Result) <150ms
- [ ] TTS TTFB <50ms

**P2 - Multi-Provider**:
- [ ] Failover latency <50ms
- [ ] Cloud usage <10% of total (cost control)
- [ ] Zero downtime during provider failures

**P3 - Production**:
- [ ] NAT traversal success rate >99%
- [ ] Barge-in detection accuracy >95%
- [ ] WebSocket API uptime >99.9%

---

## 📝 NOTAS FINAIS

Este plano foi desenvolvido seguindo os princípios de:
- **Incrementalidade**: Cada task adiciona valor testável
- **Compatibilidade**: Sistema funciona durante toda evolução
- **Observabilidade**: Métricas e logs em cada etapa
- **Segurança**: Feature flags e rollback garantidos

**Última atualização**: Janeiro 2026
**Versão do documento**: 1.0
