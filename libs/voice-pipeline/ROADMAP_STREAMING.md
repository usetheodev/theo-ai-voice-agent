# Roadmap: Implementação de Streaming Real no Voice-Pipeline

> **Objetivo**: Reduzir TTFA (Time-to-First-Audio) de ~2-3s para ~0.6-0.8s
> **Referência**: [Artigo Telecom](https://arxiv.org/html/2508.04721v1), [Pipecat](https://github.com/pipecat-ai/pipecat), [LiveKit](https://docs.livekit.io/agents/)

---

## Visão Geral da Arquitetura

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     ARQUITETURA STREAMING                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────┐    ┌─────────────────┐    ┌──────────────┐    ┌─────────┐ │
│  │   ASR   │───▶│  LLM Streaming  │───▶│  Sentence    │───▶│   TTS   │ │
│  │         │    │  (tokens)       │    │  Aggregator  │    │Streaming│ │
│  └─────────┘    └─────────────────┘    └──────────────┘    └─────────┘ │
│                         │                      │                  │     │
│                         │              ┌───────▼───────┐          │     │
│                         │              │ Sentence Queue│          │     │
│                         │              │ (thread-safe) │          │     │
│                         │              └───────┬───────┘          │     │
│                         │                      │                  │     │
│                         └──────────────────────┴──────────────────┘     │
│                              Producer-Consumer Pattern                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Fase 1: SentenceAggregator

### 1.1 Criar classe SentenceAggregator

**Arquivo**: `src/voice_pipeline/streaming/sentence_aggregator.py`

**Microtasks**:

| # | Task | DoD (Definition of Done) |
|---|------|--------------------------|
| 1.1.1 | Criar classe `SentenceAggregator` com buffer interno | Classe existe com `__init__`, `_buffer: str`, `_sentences: asyncio.Queue` |
| 1.1.2 | Implementar método `feed(text: str)` | Método adiciona texto ao buffer |
| 1.1.3 | Implementar detecção de fim de sentença com regex | Regex `[.!?]+\s*` detecta fim de sentença |
| 1.1.4 | Implementar método `get_sentence()` async | Retorna sentença completa ou None |
| 1.1.5 | Implementar método `flush()` | Retorna texto restante no buffer |
| 1.1.6 | Adicionar suporte a delimitadores customizáveis | `sentence_delimiters` configurável no `__init__` |
| 1.1.7 | Tratar casos especiais (abreviações, números) | "Mr.", "Dr.", "$29.99" não quebram sentença |

**Código esperado**:
```python
class SentenceAggregator:
    def __init__(
        self,
        sentence_delimiters: str = ".!?",
        min_sentence_length: int = 10,
        max_buffer_size: int = 1000,
    ):
        self._buffer = ""
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._delimiters = sentence_delimiters
        self._min_length = min_sentence_length
        self._max_buffer = max_buffer_size

    async def feed(self, text: str) -> None:
        """Adiciona texto e detecta sentenças completas."""

    async def get_sentence(self, timeout: float = 0.1) -> Optional[str]:
        """Retorna próxima sentença ou None."""

    def flush(self) -> str:
        """Retorna e limpa buffer restante."""
```

**DoD da Fase 1.1**:
- [ ] Testes unitários passando (`test_sentence_aggregator.py`)
- [ ] Detecta sentenças corretamente em 95%+ dos casos
- [ ] Não quebra em abreviações comuns (Mr., Dr., etc.)
- [ ] Não quebra em números com ponto ($29.99, 3.14)

---

### 1.2 Criar testes para SentenceAggregator

**Arquivo**: `tests/unit/test_sentence_aggregator.py`

**Microtasks**:

| # | Task | DoD |
|---|------|-----|
| 1.2.1 | Teste básico de detecção de sentença | `"Olá. Tudo bem?"` → `["Olá.", "Tudo bem?"]` |
| 1.2.2 | Teste com streaming de tokens | Tokens um a um produzem sentenças |
| 1.2.3 | Teste com abreviações | `"Dr. Smith chegou."` → uma sentença |
| 1.2.4 | Teste com números | `"Custa $29.99 hoje."` → uma sentença |
| 1.2.5 | Teste de flush | Buffer incompleto é retornado |
| 1.2.6 | Teste de timeout | `get_sentence()` retorna None após timeout |
| 1.2.7 | Teste de max_buffer | Buffer grande é forçado a flush |

**DoD da Fase 1.2**:
- [ ] 7+ testes escritos
- [ ] Cobertura > 90% do código
- [ ] Todos os testes passando

---

## Fase 2: StreamingVoiceChain

### 2.1 Criar classe StreamingVoiceChain

**Arquivo**: `src/voice_pipeline/chains/streaming_chain.py`

**Microtasks**:

| # | Task | DoD |
|---|------|-----|
| 2.1.1 | Criar classe herdando de `VoiceRunnable` | Classe existe com assinatura correta |
| 2.1.2 | Implementar `__init__` com ASR, LLM, TTS, VAD | Todos os providers armazenados |
| 2.1.3 | Criar `_sentence_aggregator` interno | Instância de SentenceAggregator |
| 2.1.4 | Implementar `_llm_producer()` async | Gera tokens e alimenta aggregator |
| 2.1.5 | Implementar `_tts_consumer()` async | Consome sentenças e gera áudio |
| 2.1.6 | Implementar `astream()` com asyncio.gather | Producer e consumer em paralelo |
| 2.1.7 | Implementar métricas de latência | TTFT, TTFA, tempo total |
| 2.1.8 | Implementar suporte a barge-in | Cancelamento via Event |

**Código esperado**:
```python
class StreamingVoiceChain(VoiceRunnable[bytes, AudioChunk]):
    """Chain com streaming sentence-level entre LLM e TTS."""

    def __init__(
        self,
        asr: ASRInterface,
        llm: LLMInterface,
        tts: TTSInterface,
        vad: Optional[VADInterface] = None,
        system_prompt: Optional[str] = None,
        sentence_aggregator: Optional[SentenceAggregator] = None,
    ):
        self.asr = asr
        self.llm = llm
        self.tts = tts
        self.vad = vad
        self._aggregator = sentence_aggregator or SentenceAggregator()
        self._cancel_event = asyncio.Event()

    async def astream(
        self,
        input: bytes,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[AudioChunk]:
        """Processa áudio com streaming sentence-level."""

        # 1. ASR
        transcription = await self.asr.ainvoke(input)

        # 2. Parallel LLM + TTS
        audio_queue: asyncio.Queue[AudioChunk] = asyncio.Queue()

        async def llm_producer():
            async for token in self.llm.astream(messages):
                await self._aggregator.feed(token.text)

        async def tts_consumer():
            while True:
                sentence = await self._aggregator.get_sentence()
                if sentence is None:
                    break
                async for chunk in self.tts.astream(sentence):
                    await audio_queue.put(chunk)

        # 3. Run in parallel
        await asyncio.gather(llm_producer(), tts_consumer())

        # 4. Yield audio chunks
        while not audio_queue.empty():
            yield await audio_queue.get()
```

**DoD da Fase 2.1**:
- [ ] Classe implementada e funcional
- [ ] LLM e TTS executam em paralelo
- [ ] Áudio começa a ser gerado antes do LLM terminar
- [ ] TTFA medido e < 1 segundo

---

### 2.2 Implementar métricas de latência

**Arquivo**: `src/voice_pipeline/streaming/metrics.py`

**Microtasks**:

| # | Task | DoD |
|---|------|-----|
| 2.2.1 | Criar dataclass `StreamingMetrics` | TTFT, TTFA, total_time, sentences_count |
| 2.2.2 | Implementar coleta de TTFT | Tempo até primeiro token do LLM |
| 2.2.3 | Implementar coleta de TTFA | Tempo até primeiro chunk de áudio |
| 2.2.4 | Implementar coleta de tempo por sentença | Lista de tempos por sentença |
| 2.2.5 | Adicionar logging estruturado | Métricas logadas em JSON |

**Código esperado**:
```python
@dataclass
class StreamingMetrics:
    ttft: float  # Time to First Token
    ttfa: float  # Time to First Audio
    total_time: float
    asr_time: float
    llm_time: float
    tts_time: float
    sentences_count: int
    tokens_count: int
    audio_duration: float

    @property
    def rtf(self) -> float:
        """Real-Time Factor."""
        return self.total_time / self.audio_duration if self.audio_duration > 0 else 0
```

**DoD da Fase 2.2**:
- [ ] Dataclass criada
- [ ] Todas as métricas sendo coletadas
- [ ] Logging funcionando
- [ ] RTF calculado corretamente

---

### 2.3 Testes para StreamingVoiceChain

**Arquivo**: `tests/unit/test_streaming_chain.py`

**Microtasks**:

| # | Task | DoD |
|---|------|-----|
| 2.3.1 | Teste básico de streaming | Chain processa áudio e retorna resposta |
| 2.3.2 | Teste de paralelismo | LLM e TTS executam concorrentemente |
| 2.3.3 | Teste de TTFA | TTFA < tempo total (prova streaming) |
| 2.3.4 | Teste de barge-in | Cancelamento interrompe processamento |
| 2.3.5 | Teste de métricas | Métricas são coletadas corretamente |
| 2.3.6 | Teste com múltiplas sentenças | 3+ sentenças processadas em streaming |

**DoD da Fase 2.3**:
- [ ] 6+ testes escritos
- [ ] Cobertura > 85%
- [ ] Todos os testes passando

---

## Fase 3: Integração com Builder

### 3.1 Atualizar VoiceAgentBuilder

**Arquivo**: `src/voice_pipeline/agents/base.py`

**Microtasks**:

| # | Task | DoD |
|---|------|-----|
| 3.1.1 | Adicionar atributo `_streaming: bool` | Default: False |
| 3.1.2 | Adicionar método `.streaming(enabled: bool)` | Retorna self |
| 3.1.3 | Atualizar `build()` para escolher chain | Streaming → StreamingVoiceChain |
| 3.1.4 | Adicionar configuração de sentence_delimiters | Configurável via builder |
| 3.1.5 | Documentar nova API | Docstrings atualizadas |

**Código esperado**:
```python
class VoiceAgentBuilder:
    def __init__(self):
        # ... existing code ...
        self._streaming = False
        self._sentence_delimiters = ".!?"

    def streaming(self, enabled: bool = True) -> "VoiceAgentBuilder":
        """Ativa streaming sentence-level (baixa latência).

        Quando ativado:
        - LLM e TTS executam em paralelo
        - Áudio começa a ser gerado antes do LLM terminar
        - TTFA reduzido de ~2-3s para ~0.6-0.8s
        """
        self._streaming = enabled
        return self

    def sentence_delimiters(self, delimiters: str) -> "VoiceAgentBuilder":
        """Define delimitadores de sentença para streaming."""
        self._sentence_delimiters = delimiters
        return self

    def build(self):
        # ... existing validation ...

        if self._asr and self._tts:
            if self._streaming:
                from voice_pipeline.chains import StreamingVoiceChain
                return StreamingVoiceChain(
                    asr=self._asr,
                    llm=self._llm,
                    tts=self._tts,
                    vad=self._vad,
                    system_prompt=self._system_prompt,
                    sentence_delimiters=self._sentence_delimiters,
                )
            else:
                from voice_pipeline.chains import ConversationChain
                return ConversationChain(...)
```

**DoD da Fase 3.1**:
- [ ] `.streaming()` implementado
- [ ] `build()` retorna StreamingVoiceChain quando streaming=True
- [ ] Testes de integração passando

---

### 3.2 Atualizar exports

**Arquivos**:
- `src/voice_pipeline/chains/__init__.py`
- `src/voice_pipeline/streaming/__init__.py`
- `src/voice_pipeline/__init__.py`

**Microtasks**:

| # | Task | DoD |
|---|------|-----|
| 3.2.1 | Exportar SentenceAggregator | Disponível em `voice_pipeline.streaming` |
| 3.2.2 | Exportar StreamingVoiceChain | Disponível em `voice_pipeline.chains` |
| 3.2.3 | Exportar StreamingMetrics | Disponível em `voice_pipeline.streaming` |
| 3.2.4 | Atualizar `__all__` no __init__.py raiz | Todos os novos componentes listados |

**DoD da Fase 3.2**:
- [ ] Imports funcionam: `from voice_pipeline import StreamingVoiceChain`
- [ ] Imports funcionam: `from voice_pipeline.streaming import SentenceAggregator`

---

## Fase 4: Exemplos e Documentação

### 4.1 Criar exemplo de streaming

**Arquivo**: `examples/streaming_demo.py`

**Microtasks**:

| # | Task | DoD |
|---|------|-----|
| 4.1.1 | Criar exemplo com modo batch | Demonstra uso tradicional |
| 4.1.2 | Criar exemplo com modo streaming | Demonstra baixa latência |
| 4.1.3 | Comparar métricas lado a lado | Mostra diferença de TTFA |
| 4.1.4 | Adicionar logging de métricas | Exibe TTFT, TTFA, total |

**Código esperado**:
```python
"""Comparação: Batch vs Streaming."""

import asyncio
from voice_pipeline import VoiceAgent

async def main():
    print("=" * 60)
    print("Voice Pipeline - Batch vs Streaming")
    print("=" * 60)

    # Modo Batch (padrão atual)
    print("\n[1] Modo Batch")
    batch_agent = await (
        VoiceAgent.builder()
        .asr("whisper", model="base", language="pt")
        .llm("ollama", model="qwen2.5:0.5b")
        .tts("kokoro", voice="pf_dora")
        .streaming(False)
        .build_async()
    )

    # Modo Streaming (baixa latência)
    print("\n[2] Modo Streaming")
    stream_agent = await (
        VoiceAgent.builder()
        .asr("whisper", model="base", language="pt")
        .llm("ollama", model="qwen2.5:0.5b")
        .tts("kokoro", voice="pf_dora")
        .streaming(True)
        .build_async()
    )

    # Comparar métricas
    # ...
```

**DoD da Fase 4.1**:
- [ ] Exemplo executa sem erros
- [ ] Mostra diferença clara de latência
- [ ] Métricas são exibidas

---

### 4.2 Atualizar webapp

**Arquivo**: `examples/webapp/backend/agent.py`

**Microtasks**:

| # | Task | DoD |
|---|------|-----|
| 4.2.1 | Adicionar opção de streaming no builder | `.streaming(True)` |
| 4.2.2 | Atualizar `_process_speech()` para streaming | Usa astream() com yield |
| 4.2.3 | Adicionar métricas no WebSocket | Envia TTFA para frontend |

**DoD da Fase 4.2**:
- [ ] Webapp funciona com streaming
- [ ] Latência perceptivelmente menor
- [ ] Métricas exibidas no frontend

---

### 4.3 Atualizar quickstart.py

**Arquivo**: `examples/quickstart.py`

**Microtasks**:

| # | Task | DoD |
|---|------|-----|
| 4.3.1 | Adicionar opção 5: Streaming | Nova seção demonstrando streaming |
| 4.3.2 | Exibir métricas de latência | TTFT, TTFA, total |

**DoD da Fase 4.3**:
- [ ] Quickstart mostra 5 opções
- [ ] Streaming é demonstrado
- [ ] Métricas são exibidas

---

## Fase 5: Testes de Integração

### 5.1 Testes end-to-end

**Arquivo**: `tests/integration/test_streaming_e2e.py`

**Microtasks**:

| # | Task | DoD |
|---|------|-----|
| 5.1.1 | Teste e2e com áudio real | Pipeline completo funciona |
| 5.1.2 | Teste de TTFA < 1 segundo | Métrica validada |
| 5.1.3 | Teste de qualidade de áudio | Áudio gerado é válido |
| 5.1.4 | Teste de múltiplas sentenças | 5+ sentenças processadas |
| 5.1.5 | Teste de barge-in | Interrupção funciona |
| 5.1.6 | Teste de stress | 10 requisições sequenciais |

**DoD da Fase 5.1**:
- [ ] 6+ testes de integração
- [ ] TTFA consistentemente < 1s
- [ ] Sem memory leaks

---

## Fase 6: Otimizações (Futuro)

### 6.1 ASR Streaming (opcional)

**Descrição**: Integrar ASR com streaming real (Deepgram, AssemblyAI)

| # | Task | DoD |
|---|------|-----|
| 6.1.1 | Pesquisar APIs de streaming ASR | Documento de comparação |
| 6.1.2 | Implementar DeepgramStreamingASR | Provider funcional |
| 6.1.3 | Integrar com pipeline | ASR streaming → LLM |

### 6.2 Quantização de LLM (opcional)

**Descrição**: Usar quantização 4-bit para menor latência

| # | Task | DoD |
|---|------|-----|
| 6.2.1 | Adicionar suporte a bitsandbytes | Configurável no builder |
| 6.2.2 | Testar com Ollama quantizado | Métricas comparadas |

---

## Cronograma Sugerido

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CRONOGRAMA                                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Fase 1: SentenceAggregator                                              │
│  ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  (~2h)                        │
│                                                                          │
│  Fase 2: StreamingVoiceChain                                             │
│  ░░░░░░░░████████████████░░░░░░░░░░░░░░░░  (~4h)                        │
│                                                                          │
│  Fase 3: Integração com Builder                                          │
│  ░░░░░░░░░░░░░░░░░░░░░░░░████████░░░░░░░░  (~2h)                        │
│                                                                          │
│  Fase 4: Exemplos e Documentação                                         │
│  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░████████  (~2h)                        │
│                                                                          │
│  Fase 5: Testes de Integração                                            │
│  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░████  (~1h)                        │
│                                                                          │
│  TOTAL ESTIMADO: ~11 horas de desenvolvimento                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Métricas de Sucesso

| Métrica | Atual | Objetivo | Stretch |
|---------|-------|----------|---------|
| **TTFA** | ~2-3s | < 1s | < 0.7s |
| **TTFT** | ~0.5s | < 0.3s | < 0.2s |
| **RTF** | ~1.5 | < 1.0 | < 0.8 |
| **Testes** | - | > 90% | 100% |

---

## Checklist Final

- [ ] Fase 1: SentenceAggregator implementado e testado
- [ ] Fase 2: StreamingVoiceChain implementado e testado
- [ ] Fase 3: Builder atualizado com `.streaming()`
- [ ] Fase 4: Exemplos e documentação atualizados
- [ ] Fase 5: Testes de integração passando
- [ ] TTFA < 1 segundo confirmado
- [ ] Webapp funcionando com streaming

---

## Referências

- [Artigo: Low-Latency Voice Agents for Telecom](https://arxiv.org/html/2508.04721v1)
- [Pipecat Framework](https://github.com/pipecat-ai/pipecat)
- [LiveKit Agents](https://docs.livekit.io/agents/)
- [RealtimeTTS](https://github.com/KoljaB/RealtimeTTS)
- [How to optimize latency](https://rnikhil.com/2025/05/18/how-to-reduce-latency-voice-agents)
