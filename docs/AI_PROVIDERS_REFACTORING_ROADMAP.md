# 🗺️ AI Providers Refactoring - Roadmap Completo

**Data:** 2026-01-22
**Versão:** 1.0
**Status:** Análise Completa

---

## 📋 ÍNDICE

1. [Análise do Estado Atual](#1-análise-do-estado-atual)
2. [Arquitetura Proposta](#2-arquitetura-proposta)
3. [Design Pattern: Provider Pattern](#3-design-pattern-provider-pattern)
4. [Roadmap de Implementação](#4-roadmap-de-implementação)
5. [Riscos e Mitigações](#5-riscos-e-mitigações)
6. [Comparação de Performance](#6-comparação-de-performance)
7. [Decisão: Ollama vs vLLM](#7-decisão-ollama-vs-vllm)
8. [Próximos Passos](#8-próximos-passos)

---

## 1. ANÁLISE DO ESTADO ATUAL

### 1.1. Resposta às Perguntas Iniciais

#### ❌ Q1: Nossa aplicação tem transcrição Real-Time?

**NÃO.** A aplicação atual usa **batch processing**:

```
Usuário fala → VAD detecta início → Acumula frames → VAD detecta fim (500ms silêncio) →
→ ENTÃO começa transcrição → LLM → TTS → Envia resposta
```

**Latência típica:**
- 500ms (VAD silence) + 1-3s (Whisper) + 2-5s (LLM) + 0.5-1s (TTS) = **4-9.5s total**

---

#### ❌ Q2: É possível testar com OpenAI, Anthropic ou Ollama facilmente?

**NÃO - Requer refatoração significativa:**

**Problemas Identificados:**

1. **Código Fortemente Acoplado:**
   ```python
   # main.py:105-151
   whisper_asr = WhisperASR(...)  # Classe específica hardcoded
   qwen_llm = QwenLLM(...)        # Classe específica hardcoded
   kokoro_tts = KokoroTTS(...)    # Classe específica hardcoded
   ```

2. **Sem Abstrações:**
   - Não existe interface `ASRProvider`, `LLMProvider`, `TTSProvider`
   - Cada modelo tem API diferente
   - `main.py` conhece detalhes de implementação

3. **Config Específico:**
   ```yaml
   # config/default.yaml
   ai:
     asr_model_path: models/whisper/ggml-base.bin  # Whisper-specific
     llm_model: Qwen/Qwen2.5-1.5B-Instruct         # Qwen-specific
     tts_voice: pf_dora                            # Kokoro-specific
   ```

**Para trocar para OpenAI/Anthropic/Ollama hoje:**
- ❌ Reescrever `main.py`
- ❌ Criar classes novas manualmente
- ❌ Ajustar config YAML
- ❌ Modificar pipeline de áudio

---

#### ⚠️ Q3: Existe padrão de integração RTP → IA e IA → RTP?

**PARCIAL - Existe fluxo, mas sem abstração:**

**RTP → AI (Input):**
```
RTP Session → audio_in_queue → AudioPipeline → VAD → Buffer →
→ Callback on_speech_ready → main.py transcribe_audio()
```

✅ **Bom:** Queue-based, desacoplado
❌ **Ruim:** Callback espera formato específico (bytes PCM 16kHz)

**AI → RTP (Output):**
```python
# main.py:256-342
async def send_tts_audio(session_id, tts_audio, rtp_session):
    # Hardcoded: resample 24kHz→8kHz, encode G.711, split packets
```

❌ **Ruim:**
- Lógica hardcoded em `main.py`
- Não reutilizável para outros modelos TTS
- Assume formato específico (float32, 24kHz)

---

#### 🎯 Q4: Usar Ollama ou vLLM?

**RESPOSTA: vLLM para Qwen3-Omni**

| Critério | **Ollama** | **vLLM** | **Recomendação** |
|----------|-----------|---------|------------------|
| **Qwen3-Omni Support** | ❌ Não suporta (issue #12376) | ✅ Suportado (v0.13.0+) | **vLLM** |
| **Audio Streaming** | ❌ N/A | ✅ Sim (vLLM-Omni) | **vLLM** |
| **Setup Complexity** | ✅ Muito simples | ⚠️ Médio | Ollama |
| **Performance** | ⚠️ Boa (CPU/GPU) | ✅ Excelente (GPU otimizado) | **vLLM** |
| **Multi-GPU** | ❌ Limitado | ✅ tensor_parallel_size | **vLLM** |
| **Batch Inference** | ⚠️ Básico | ✅ Avançado (max_num_seqs) | **vLLM** |
| **Production Ready** | ✅ Sim | ✅ Sim | Empate |

**Motivos:**
1. ✅ **Qwen3-Omni oficialmente suportado** (documentação confirma)
2. ✅ **vLLM-Omni** lançado em Nov 2025 para omni-modalidade
3. ✅ **Audio streaming** suportado desde Apr 2025
4. ✅ **Performance superior** para produção
5. ❌ **Ollama NÃO suporta Qwen3-Omni** (GitHub issue aberto)

**Ressalva:** Use Ollama para **testes rápidos** com Qwen2.5 text-only durante desenvolvimento.

---

### 1.2. Limitações dos Componentes Atuais

#### A) ASR (Whisper) - `src/ai/whisper.py`

**❌ LIMITAÇÕES CRÍTICAS:**

1. **NÃO SUPORTA STREAMING**
   - Método `transcribe_array()` processa **áudio completo** de uma vez
   - Requer **fim da fala** para começar transcrição (batch mode)
   - Latência alta: só inicia após VAD detectar silêncio (500ms)

2. **Arquitetura Bloqueante:**
   ```python
   # main.py:170-176
   text = await asyncio.wait_for(
       asyncio.to_thread(
           whisper_asr.transcribe_array,
           audio_float32
       ),
       timeout=10.0
   )
   ```

3. **Dependência de VAD:**
   - Só processa após `_on_speech_end()`
   - Não suporta chunks progressivos

**✅ PONTOS POSITIVOS:**
- Filtro de alucinações implementado
- Performance otimizada com pywhispercpp (C++ bindings)
- Rate limiting com semáforo (10 concurrent)

---

#### B) LLM (Qwen) - `src/ai/llm.py`

**❌ LIMITAÇÕES CRÍTICAS:**

1. **MODELO TEXT-ONLY:**
   - Qwen2.5-1.5B-Instruct: NÃO É OMNI-MODAL
   - Só aceita texto, sem áudio/vídeo direto
   - Sem suporte nativo a streaming de áudio

2. **Pipeline Sequencial Rígido:**
   ```python
   # main.py:183-205
   # Fase 1: ASR (Whisper) → texto
   # Fase 2: Texto → LLM → texto
   # Fase 3: Texto → TTS (Kokoro)
   ```
   - Não aproveita modelos end-to-end (Qwen3-Omni)
   - Cada etapa adiciona latência

3. **Sem Streaming de Resposta:**
   - `return_full_text=False` gera tudo de uma vez
   - Não suporta token streaming para TTS incremental

**✅ PONTOS POSITIVOS:**
- Async wrapper bem implementado
- Concurrency control (semáforo)
- Suporte GPU/CPU configurável

---

#### C) TTS (Kokoro) - `src/ai/kokoro.py`

**⚠️ LIMITAÇÕES MODERADAS:**

1. **Streaming Parcial:**
   ```python
   # kokoro.py:121-153
   def synthesize_stream(self, text: str) -> Generator[np.ndarray, None, None]:
       for i, (gs, ps, audio) in enumerate(self.pipeline(text, voice=self.voice)):
           yield audio  # ✅ Suporta chunks
   ```
   - ✅ **TEM streaming**, mas **NÃO é usado** no código atual
   - `main.py:212-215` usa `synthesize()` (não-streaming)

2. **Resampling Manual:**
   - Processamento adicional após TTS (24kHz → 8kHz)
   - Adiciona latência

**✅ PONTOS POSITIVOS:**
- **JÁ TEM** método `synthesize_stream()` implementado!
- Voz brasileira de qualidade (pf_dora)
- Baixa latência nativa (Kokoro-82M)

---

#### D) Audio Pipeline - `src/audio/pipeline.py`

**❌ LIMITAÇÕES CRÍTICAS:**

1. **Callback Baseado em Eventos (Não-Streaming):**
   ```python
   # pipeline.py:90-91
   self.on_speech_ready: Optional[Callable[[bytes], None]] = None
   ```
   - Callback dispara **UMA VEZ** após fim da fala
   - Não suporta callbacks progressivos durante fala

2. **VAD com Latência Alta:**
   - `vad_silence_duration_ms: int = 500`
   - Adiciona 500ms de latência ao fim de cada fala

3. **Buffer Acumulativo:**
   - Acumula **TODOS** os frames até fim da fala
   - Não há processamento incremental

**✅ PONTOS POSITIVOS:**
- DTMF monitoring implementado
- Dual-mode VAD (WebRTC + Energy)
- Integração com RTP bem estruturada

---

## 2. ARQUITETURA PROPOSTA

### 2.1. Hierarquia de Providers

```
┌─────────────────────────────────────────────────────────┐
│          ABSTRACT BASE PROVIDERS                        │
└─────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
  ┌──────────┐      ┌──────────┐      ┌──────────┐
  │   ASR    │      │   LLM    │      │   TTS    │
  │ Provider │      │ Provider │      │ Provider │
  └──────────┘      └──────────┘      └──────────┘
        │                  │                  │
   ┌────┴────┐        ┌────┴────┐        ┌────┴────┐
   ▼         ▼        ▼         ▼        ▼         ▼
Whisper  OpenAI   Qwen2.5  Claude   Kokoro  OpenAI
 Local    API      Local    API      Local    API

┌─────────────────────────────────────────────────────────┐
│          OMNI-MODAL PROVIDER (All-in-One)               │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ Qwen3-Omni   │
                    │ (vLLM/Trans) │
                    └──────────────┘
         Audio In → [Model] → Audio Out + Text Out
```

---

### 2.2. Interfaces Core

#### Base Types
```python
# src/ai/providers/base.py

@dataclass
class AudioChunk:
    """Representa um chunk de áudio"""
    data: np.ndarray          # Audio samples (float32, [-1.0, 1.0])
    sample_rate: int          # Hz (8000, 16000, 24000, etc.)
    timestamp_ms: int         # Timestamp relativo ao início
    is_final: bool = False    # True = último chunk

@dataclass
class TranscriptionResult:
    """Resultado de transcrição (streaming ou completo)"""
    text: str
    is_partial: bool = False  # True = transcrição parcial (streaming)
    confidence: Optional[float] = None
    language: Optional[str] = None

@dataclass
class LLMResponse:
    """Resposta do LLM"""
    text: str
    is_partial: bool = False  # True = token streaming
    finish_reason: Optional[str] = None

@dataclass
class SynthesisResult:
    """Resultado de síntese de voz"""
    audio: AudioChunk
    text_processed: str

class ProviderCapabilities:
    """Capabilities de um provider"""
    supports_streaming: bool = False
    supports_realtime: bool = False
    supports_multimodal: bool = False
    input_modalities: list[str] = []   # ['audio', 'text', 'image', 'video']
    output_modalities: list[str] = []  # ['text', 'audio']
```

#### ASR Provider Interface
```python
# src/ai/providers/asr_provider.py

class ASRProvider(ABC):
    @abstractmethod
    async def initialize(self) -> None:
        """Inicializa o provider"""
        pass

    @abstractmethod
    async def transcribe(self,
                        audio: Union[AudioChunk, bytes, np.ndarray],
                        language: Optional[str] = None) -> TranscriptionResult:
        """Transcrição batch (áudio completo)"""
        pass

    @abstractmethod
    async def transcribe_stream(self,
                                audio_stream: AsyncGenerator[AudioChunk, None],
                                language: Optional[str] = None
                               ) -> AsyncGenerator[TranscriptionResult, None]:
        """Transcrição streaming (chunks progressivos)"""
        pass

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """Retorna capabilities deste provider"""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Cleanup de recursos"""
        pass
```

#### LLM Provider Interface
```python
# src/ai/providers/llm_provider.py

class LLMProvider(ABC):
    @abstractmethod
    async def generate(self,
                      messages: List[Dict[str, Any]],
                      temperature: float = 0.7,
                      max_tokens: int = 128,
                      **kwargs) -> LLMResponse:
        """Geração batch (resposta completa)"""
        pass

    @abstractmethod
    async def generate_stream(self,
                             messages: List[Dict[str, Any]],
                             temperature: float = 0.7,
                             max_tokens: int = 128,
                             **kwargs) -> AsyncGenerator[LLMResponse, None]:
        """Geração streaming (token por token)"""
        pass
```

#### TTS Provider Interface
```python
# src/ai/providers/tts_provider.py

class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self,
                        text: str,
                        voice: Optional[str] = None,
                        language: Optional[str] = None,
                        **kwargs) -> AudioChunk:
        """Síntese batch (áudio completo)"""
        pass

    @abstractmethod
    async def synthesize_stream(self,
                               text: str,
                               voice: Optional[str] = None,
                               language: Optional[str] = None,
                               **kwargs) -> AsyncGenerator[SynthesisResult, None]:
        """Síntese streaming (chunks progressivos)"""
        pass
```

#### Omni-Modal Provider Interface
```python
# src/ai/providers/omni_provider.py

@dataclass
class OmniInput:
    """Input multimodal para modelo omni"""
    text: Optional[str] = None
    audio: Optional[Union[AudioChunk, List[AudioChunk]]] = None
    images: Optional[List[Any]] = None
    video: Optional[Any] = None

@dataclass
class OmniOutput:
    """Output multimodal de modelo omni"""
    text: Optional[str] = None
    audio: Optional[AudioChunk] = None
    is_partial: bool = False

class OmniModalProvider(ABC):
    """Interface para modelos omni-modais end-to-end"""

    @abstractmethod
    async def process(self,
                     inputs: OmniInput,
                     conversation_history: Optional[List[Dict[str, Any]]] = None,
                     output_audio: bool = True,
                     output_text: bool = True,
                     **kwargs) -> OmniOutput:
        """Processamento batch (resposta completa)"""
        pass

    @abstractmethod
    async def process_stream(self,
                            inputs: OmniInput,
                            conversation_history: Optional[List[Dict[str, Any]]] = None,
                            output_audio: bool = True,
                            output_text: bool = True,
                            **kwargs) -> AsyncGenerator[OmniOutput, None]:
        """Processamento streaming (resposta progressiva)"""
        pass
```

---

### 2.3. Provider Factory

```python
# src/ai/providers/factory.py

class ProviderFactory:
    """Factory para criar providers baseado em config"""

    _asr_providers = {}
    _llm_providers = {}
    _tts_providers = {}
    _omni_providers = {}

    @classmethod
    def register_asr(cls, name: str, provider_class):
        cls._asr_providers[name] = provider_class

    @classmethod
    def create_asr(cls, provider_name: str, config: dict) -> ASRProvider:
        if provider_name not in cls._asr_providers:
            raise ValueError(f"ASR provider '{provider_name}' não registrado")
        return cls._asr_providers[provider_name](config)

    # Similar para LLM, TTS, Omni...
```

---

### 2.4. Nova Estrutura de Config YAML

```yaml
# config/default.yaml (NOVO FORMATO)

ai:
  # Modo de operação: 'pipeline' (ASR+LLM+TTS separados) ou 'omni' (end-to-end)
  mode: pipeline  # ou 'omni'

  # ===== PIPELINE MODE =====
  pipeline:
    # ASR Provider
    asr:
      provider: whisper_local  # whisper_local | openai_api | deepgram_api
      config:
        model_path: models/whisper/ggml-base.bin
        language: pt
        threads: 4
        streaming: false

    # LLM Provider
    llm:
      provider: qwen_local  # qwen_local | openai_api | anthropic_api | ollama
      config:
        model: Qwen/Qwen2.5-1.5B-Instruct
        max_tokens: 128
        temperature: 0.7
        streaming: true

    # TTS Provider
    tts:
      provider: kokoro_local  # kokoro_local | openai_api | elevenlabs_api
      config:
        lang_code: p
        voice: pf_dora
        sample_rate: 24000
        streaming: true

  # ===== OMNI MODE =====
  omni:
    provider: qwen3_omni_vllm  # qwen3_omni_vllm | qwen3_omni_transformers
    config:
      model_path: Qwen/Qwen3-Omni-30B-A3B-Instruct
      backend: vllm
      tensor_parallel_size: 2
      max_model_len: 32768
      speaker: Ethan
      streaming: true
      use_audio_in_video: true

      vllm:
        gpu_memory_utilization: 0.95
        max_num_seqs: 8
        limit_mm_per_prompt:
          image: 3
          video: 3
          audio: 3
```

---

## 3. DESIGN PATTERN: PROVIDER PATTERN

### 3.1. Arquitetura de Streaming

```
┌─────────────────────────────────────────────────────────────┐
│                  RTP AUDIO INPUT FLOW                       │
└─────────────────────────────────────────────────────────────┘

RTP Packets → Jitter Buffer → Decode G.711 → PCM Queue
                                                    ↓
                                            ┌───────────────┐
                                            │ Audio Stream  │
                                            │   Manager     │
                                            └───────┬───────┘
                                                    ↓
                    ┌───────────────────────────────┴─────────────────┐
                    ▼                                                 ▼
          ┌─────────────────┐                              ┌──────────────────┐
          │  PIPELINE MODE  │                              │   OMNI MODE      │
          └─────────────────┘                              └──────────────────┘
                    │                                                 │
        ┌───────────┼───────────┐                                    │
        ▼           ▼           ▼                                    ▼
    ┌─────┐    ┌─────┐    ┌─────┐                           ┌───────────────┐
    │ VAD │ →  │ ASR │ →  │ LLM │ → TTS                     │ Qwen3-Omni    │
    └─────┘    └─────┘    └─────┘    ↓                      │  (vLLM)       │
                                      │                      └───────┬───────┘
                                      ▼                              │
                              ┌──────────────┐                       ▼
                              │ Audio Output │              ┌────────────────┐
                              │   Manager    │              │ Audio + Text   │
                              └──────┬───────┘              │   Streaming    │
                                     │                      └────────┬───────┘
                                     ▼                               │
┌─────────────────────────────────────────────────────────────────┐
│                  RTP AUDIO OUTPUT FLOW                          │
└─────────────────────────────────────────────────────────────────┘
                                     │
                  PCM Stream → Resample → Encode G.711 → RTP Packets
```

---

### 3.2. StreamingAudioManager

**Responsabilidades:**
- Converter RTP packets → AudioChunks para AI
- Converter AI AudioChunks → RTP packets
- Buffer management para streaming
- Sincronização de timestamps

**Localização:** `src/audio/stream_manager.py`

**Key Features:**
```python
class StreamingAudioManager:
    def __init__(self, rtp_session, target_chunk_duration_ms: int = 100):
        # 100ms chunks = low latency

    async def input_stream(self) -> AsyncGenerator[AudioChunk, None]:
        """RTP packets → AudioChunks"""

    async def send_audio_chunk(self, chunk: AudioChunk):
        """AudioChunks → RTP packets"""

    async def _output_sender_task(self):
        """Background task que envia chunks via RTP com pacing"""
```

---

## 4. ROADMAP DE IMPLEMENTAÇÃO

### 📌 FASE 1: REFATORAÇÃO BASE (Provider Pattern)
**Duração:** 3-5 dias
**Risco:** 🟢 Baixo

#### Tasks:
1. ✅ Criar estrutura de interfaces
   ```
   src/ai/providers/
   ├── base.py
   ├── asr_provider.py
   ├── llm_provider.py
   ├── tts_provider.py
   ├── omni_provider.py
   └── factory.py
   ```

2. ✅ Adaptar código existente
   ```
   src/ai/providers/implementations/
   ├── whisper_local.py
   ├── qwen_local.py
   └── kokoro_local.py
   ```

3. ✅ Criar StreamingAudioManager
   ```
   src/audio/stream_manager.py
   ```

4. ✅ Atualizar config YAML
5. ✅ Modificar main.py para usar factory

#### Critérios de Sucesso:
- ✅ Código existente funciona via providers
- ✅ Testes passam (sem regressão)
- ✅ Config YAML permite escolher provider

#### Riscos:
| Risco | Prob | Impacto | Mitigação |
|-------|------|---------|-----------|
| Quebrar funcionalidade | 🟡 Média | 🔴 Alto | Testes automatizados |
| Overhead de abstrações | 🟢 Baixa | 🟡 Médio | Benchmark |

---

### 📌 FASE 2: IMPLEMENTAR QWEN3-OMNI (vLLM)
**Duração:** 5-7 dias
**Risco:** 🟡 Médio

#### Pre-requisitos:
- ✅ Fase 1 completa
- ⚠️ GPU com 80GB+ VRAM (A100) ou 2x GPUs
- ⚠️ vLLM 0.13.0+ instalado

#### Tasks:
1. ✅ Implementar Qwen3OmniVLLMProvider
   ```python
   src/ai/providers/implementations/qwen3_omni_vllm.py
   ```

2. ✅ Adaptar AudioPipeline para modo omni
   ```python
   async def process_call_omni(self, rtp_session):
       stream_manager = StreamingAudioManager(rtp_session)
       async for output in self.ai_provider.process_stream(...):
           if output.audio:
               await stream_manager.send_audio_chunk(output.audio)
   ```

3. ✅ Criar config para Qwen3-Omni
4. ✅ Implementar conversão de formatos
5. ✅ Testes de integração end-to-end

#### Critérios de Sucesso:
- ✅ Qwen3-Omni responde a áudio via RTP
- ✅ Latência < 2s (first token/audio chunk)
- ✅ Qualidade de áudio: MOS > 3.5
- ✅ Streaming sem buffer overflow

#### Riscos:
| Risco | Prob | Impacto | Mitigação |
|-------|------|---------|-----------|
| GPU OOM | 🟡 Média | 🔴 Alto | Quantização INT8, reduzir max_model_len |
| Latência alta | 🟡 Média | 🟡 Médio | Otimizar chunk size, tensor parallelism |
| vLLM incompatibilidade | 🟢 Baixa | 🔴 Alto | Docker oficial Qwen3-Omni |
| Audio degradation | 🟡 Média | 🟡 Médio | Benchmark MOS, testar sample rates |

---

### 📌 FASE 3: PROVIDERS EXTERNOS (OpenAI, Anthropic)
**Duração:** 3-4 dias
**Risco:** 🟢 Baixo

#### Tasks:
1. ✅ OpenAI Providers
   ```
   src/ai/providers/implementations/
   ├── openai_asr.py    # Whisper API
   ├── openai_llm.py    # GPT-4o
   └── openai_tts.py    # TTS API
   ```

2. ✅ Anthropic Provider
   ```
   src/ai/providers/implementations/anthropic_llm.py
   ```

3. ✅ Ollama Provider (Qwen2.5 text-only)
   ```
   src/ai/providers/implementations/ollama_llm.py
   ```

4. ✅ Configs para cada provider
5. ✅ Documentação de comparação

---

### 📌 FASE 4: OTIMIZAÇÕES E PRODUÇÃO
**Duração:** 5-7 dias
**Risco:** 🟡 Médio

#### Tasks:
1. ✅ Implementar TTS streaming (Kokoro)
2. ✅ VAD otimizado para streaming (200ms silence)
3. ✅ Metrics Prometheus
   - asr_latency_histogram
   - llm_latency_histogram
   - tts_latency_histogram
   - end_to_end_latency
4. ✅ Fallback strategies
5. ✅ Documentation completa
6. ✅ Testes de stress (10+ chamadas simultâneas)

---

## 5. RISCOS E MITIGAÇÕES

### 🔴 RISCOS CRÍTICOS

#### 1. GPU Memory Requirements (Qwen3-Omni)
- **Problema:** Modelo requer 78GB+ VRAM
- **Mitigação:**
  - Usar tensor_parallel_size=2 (multi-GPU)
  - Quantização INT8 (reduz para ~40GB)
  - Testar Qwen3-Omni-Flash (versão menor, via API)
  - Fallback para pipeline mode se GPU insuficiente

#### 2. vLLM Stability Issues
- **Problema:** vLLM em desenvolvimento ativo, breaking changes
- **Mitigação:**
  - Pin version exata: `vllm==0.13.0`
  - Usar Docker oficial do Qwen3-Omni
  - Testar em staging antes de prod

#### 3. Audio Quality Degradation
- **Problema:** Resampling, codec conversions degradam qualidade
- **Mitigação:**
  - Benchmark MOS score em cada etapa
  - Testar diferentes sample rates (16kHz vs 24kHz)
  - Quality monitoring em produção

---

### 🟡 RISCOS MÉDIOS

#### 4. Latência Acumulativa
- **Problema:** Streaming pode adicionar overhead
- **Mitigação:**
  - Benchmark cada componente
  - Otimizar chunk sizes (100ms ideal)
  - Async I/O em todo pipeline

#### 5. API Rate Limits (OpenAI, Anthropic)
- **Problema:** Custo e limites de requisições
- **Mitigação:**
  - Rate limiting no client
  - Fallback para modelos locais
  - Caching de respostas comuns

---

## 6. COMPARAÇÃO DE PERFORMANCE

### 6.1. Latências Esperadas

| Mode | ASR | LLM | TTS | **Total (E2E)** | Streaming? |
|------|-----|-----|-----|-----------------|------------|
| **Atual (Pipeline)** | 1-3s | 2-5s | 0.5-1s | **4-9s** | ❌ Não |
| **Pipeline + Streaming TTS** | 1-3s | 2-5s | 0.1s (first chunk) | **3.5-8s** | ⚠️ Parcial |
| **Qwen3-Omni (vLLM)** | - | - | - | **0.5-2s** | ✅ Sim |
| **OpenAI API** | 0.5-1s | 1-2s | 0.3-0.5s | **2-3.5s** | ⚠️ Parcial |

**Observações:**
- **Qwen3-Omni:** Melhor latência (end-to-end), mas requer GPU potente
- **OpenAI API:** Boa latência, mas custo por chamada
- **Pipeline atual:** Alta latência, mas flexível e testado

---

### 6.2. GPU Requirements

| Model | Precision | 15s Video | 30s Video | 60s Video | 120s Video |
|-------|-----------|-----------|-----------|-----------|------------|
| Qwen3-Omni-30B-A3B-Instruct | BF16 | 78.85 GB | 88.52 GB | 107.74 GB | 144.81 GB |
| Qwen3-Omni-30B-A3B-Thinking | BF16 | 68.74 GB | 77.79 GB | 95.76 GB | 131.65 GB |

**Soluções:**
- **Multi-GPU:** tensor_parallel_size=2 (divide carga)
- **Quantização:** INT8 reduz ~50% memória
- **API Cloud:** DashScope (sem GPU local)

---

## 7. DECISÃO: OLLAMA VS vLLM

### 7.1. Análise Detalhada

#### Ollama
**Pros:**
- ✅ Setup extremamente simples (`ollama pull qwen3`)
- ✅ API REST fácil de usar
- ✅ Bom para desenvolvimento/testes rápidos

**Cons:**
- ❌ **NÃO suporta Qwen3-Omni** (confirmado - GitHub issue #12376)
- ❌ Sem audio streaming capabilities
- ❌ Performance inferior para produção
- ❌ Limitado para modelos text-only

**Recomendação de Uso:**
- ✅ Testes rápidos com Qwen2.5-1.5B-Instruct (text-only)
- ✅ Desenvolvimento da arquitetura de providers
- ❌ **NÃO usar** para Qwen3-Omni ou produção

---

#### vLLM
**Pros:**
- ✅ **Oficialmente recomendado** pela documentação Qwen3-Omni
- ✅ vLLM-Omni lançado em Nov 2025 para omni-modalidade
- ✅ Audio streaming nativo suportado
- ✅ Performance excelente (GPU otimizado)
- ✅ Multi-GPU via tensor_parallel_size
- ✅ Batch inference avançado (max_num_seqs)
- ✅ Production-ready

**Cons:**
- ⚠️ Setup mais complexo que Ollama
- ⚠️ Requer GPU com boa VRAM
- ⚠️ Documentação pode ser complexa

**Recomendação de Uso:**
- ✅ **USAR para Qwen3-Omni** (único suportado)
- ✅ Produção com requisitos de performance
- ✅ Quando GPU disponível

---

### 7.2. Decisão Final

**🎯 USAR vLLM PARA QWEN3-OMNI**

**Justificativa:**
1. Ollama não suporta Qwen3-Omni (deal-breaker)
2. vLLM é oficialmente recomendado
3. vLLM-Omni foi criado especificamente para omni-modalidade
4. Performance superior em produção
5. Único com audio streaming nativo

**Estratégia Híbrida:**
- **Desenvolvimento:** Ollama para testes rápidos com Qwen2.5 text-only
- **Produção:** vLLM para Qwen3-Omni omni-modal

---

## 8. PRÓXIMOS PASSOS

### 8.1. Duas Opções de Implementação

#### OPÇÃO A: Implementação Incremental (Recomendado)

**Fluxo:**
1. ✅ Aprovar design da arquitetura
2. ✅ Implementar Fase 1 (Provider Pattern)
3. ✅ Testar com providers atuais (sem regressão)
4. ✅ Implementar Fase 2 (Qwen3-Omni)
5. ✅ Benchmark e comparação
6. ✅ Fases 3 e 4

**Vantagens:**
- 🟢 Baixo risco
- 🟢 Validação contínua
- 🟢 Código production-ready desde o início

**Desvantagens:**
- ⚠️ Mais tempo (3-4 semanas)

**Tempo Total:** 3-4 semanas

---

#### OPÇÃO B: Prototipagem Rápida

**Fluxo:**
1. ✅ Criar branch experimental
2. ✅ Implementar Qwen3-Omni diretamente (sem refatoração completa)
3. ✅ Testar viabilidade (latência, qualidade)
4. ✅ Se funcionar → Refatorar com provider pattern
5. ✅ Se não funcionar → Descartar e usar pipeline

**Vantagens:**
- ✅ Validação rápida de viabilidade
- ✅ Menor esforço inicial

**Desvantagens:**
- 🔴 Alto risco de código throwaway
- 🔴 Possível retrabalho significativo

**Tempo Total:** 1-2 semanas (prototipagem) + 2-3 semanas (refatoração se aprovar)

---

### 8.2. Perguntas para Decisão

Para prosseguir com implementação, precisamos confirmar:

**Q1:** Qual opção de implementação?
- [ ] Opção A (Incremental - Recomendado)
- [ ] Opção B (Prototipagem Rápida)

**Q2:** Hardware disponível?
- [ ] GPU com 80GB+ VRAM (A100)
- [ ] 2x GPUs para tensor parallelism
- [ ] GPU menor (quantização necessária)
- [ ] Sem GPU (usar DashScope API)

**Q3:** Prioridade principal?
- [ ] Latência baixa (priorizar Qwen3-Omni)
- [ ] Flexibilidade (priorizar provider pattern)
- [ ] Ambos (implementação incremental)

**Q4:** Começar implementação agora?
- [ ] Sim, Fase 1 (Provider Pattern)
- [ ] Sim, Opção B (Protótipo Qwen3-Omni)
- [ ] Não, revisar design primeiro

---

### 8.3. Estrutura de Diretórios Final

```
src/
├── ai/
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py                    # Tipos base (AudioChunk, etc.)
│   │   ├── asr_provider.py            # Interface ASR
│   │   ├── llm_provider.py            # Interface LLM
│   │   ├── tts_provider.py            # Interface TTS
│   │   ├── omni_provider.py           # Interface Omni-Modal
│   │   ├── factory.py                 # ProviderFactory
│   │   └── implementations/
│   │       ├── whisper_local.py       # WhisperASR → ASRProvider
│   │       ├── qwen_local.py          # QwenLLM → LLMProvider
│   │       ├── kokoro_local.py        # KokoroTTS → TTSProvider
│   │       ├── qwen3_omni_vllm.py     # Qwen3-Omni (vLLM)
│   │       ├── qwen3_omni_transformers.py  # Qwen3-Omni (Transformers)
│   │       ├── openai_asr.py          # OpenAI Whisper API
│   │       ├── openai_llm.py          # GPT-4o
│   │       ├── openai_tts.py          # OpenAI TTS
│   │       ├── anthropic_llm.py       # Claude
│   │       └── ollama_llm.py          # Ollama (Qwen2.5 text-only)
│   ├── whisper.py                     # Legacy (migrar para providers/)
│   ├── llm.py                         # Legacy (migrar para providers/)
│   └── kokoro.py                      # Legacy (migrar para providers/)
│
├── audio/
│   ├── pipeline.py                    # AudioPipeline (atualizar)
│   ├── stream_manager.py              # StreamingAudioManager (NOVO)
│   ├── codec.py
│   ├── buffer.py
│   └── vad.py
│
├── rtp/
│   └── ...
│
└── main.py                            # Atualizar para usar ProviderFactory
```

---

## 9. CONCLUSÕES

### 9.1. Situação Atual vs Desejada

| Aspecto | Atual | Desejado | Gap |
|---------|-------|----------|-----|
| **Streaming** | ❌ Batch | ✅ Real-time | Alto |
| **Latência E2E** | 4-9s | 0.5-2s | Alto |
| **Troca de Modelos** | ❌ Hardcoded | ✅ Config YAML | Alto |
| **Providers** | 3 (fixos) | 10+ (flexível) | Médio |
| **Qualidade** | ✅ Boa | ✅ Excelente | Baixo |

---

### 9.2. Benefícios da Refatoração

1. **Flexibilidade Total:**
   - Trocar ASR/LLM/TTS via config YAML
   - Testar múltiplos providers facilmente
   - A/B testing em produção

2. **Latência Reduzida:**
   - Qwen3-Omni: 4-9s → 0.5-2s (redução de 80%+)
   - TTS streaming: 1s → 0.1s (first chunk)

3. **Código Limpo:**
   - Separação de responsabilidades
   - Testabilidade melhorada
   - Manutenibilidade a longo prazo

4. **Futuro-Pronto:**
   - Fácil adicionar novos providers (GPT-4o Audio, Gemini 2.0)
   - Arquitetura escalável
   - Production-ready com monitoring

---

### 9.3. Esforço vs Retorno

| Fase | Esforço (dias) | Retorno |
|------|----------------|---------|
| **Fase 1** | 3-5 | Alto - Base sólida, código limpo |
| **Fase 2** | 5-7 | Muito Alto - Latência reduzida 80% |
| **Fase 3** | 3-4 | Médio - Flexibilidade, comparação |
| **Fase 4** | 5-7 | Alto - Production-ready, monitoring |
| **Total** | 16-23 dias | **Transformacional** |

---

## 10. REFERÊNCIAS

### 10.1. Documentação Oficial

- **Qwen3-Omni:** https://github.com/QwenLM/Qwen3-Omni
- **vLLM:** https://docs.vllm.ai/
- **vLLM-Omni:** https://blog.vllm.ai/2025/11/30/vllm-omni.html
- **Ollama:** https://ollama.com/library/qwen3

### 10.2. Papers de Referência

- Qwen3-Omni Technical Report (arXiv:2509.17765)
- vLLM V1: Multimodal Inference (Red Hat Developer)

### 10.3. Issues Relevantes

- Qwen3-Omni Ollama Support: https://github.com/ollama/ollama/issues/12376
- vLLM Streaming Multimodal I/O: https://github.com/vllm-project/vllm/issues/25066

---

**Documento gerado em:** 2026-01-22
**Autor:** Claude Code
**Status:** ✅ Análise Completa - Aguardando Aprovação para Implementação
