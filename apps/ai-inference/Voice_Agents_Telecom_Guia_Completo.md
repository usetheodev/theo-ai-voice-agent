# Voice Agents para Telecomunicações: Guia Completo

> **Referência:** Ethiraj, V., David, A., Menon, S., & Vijay, D. (2025). Toward Low-Latency End-to-End Voice Agents for Telecommunications Using Streaming ASR, Quantized LLMs, and Real-Time TTS. *arXiv:2508.04721v1* [cs.SD]. NetoAI.

---

## Sumário

1. [Visão Geral](#-visão-geral)
2. [Arquitetura do Pipeline](#️-arquitetura-do-pipeline)
3. [Componentes Detalhados](#-componentes-detalhados)
4. [Técnicas de Otimização](#-técnicas-de-otimização)
5. [Dataset Customizado](#-dataset-customizado)
6. [Resultados Experimentais](#-resultados-experimentais)
7. [Como Reproduzir o Experimento](#-como-reproduzir-o-experimento)
8. [Ferramentas e Recursos](#-ferramentas-e-recursos)
9. [Limitações](#️-limitações)
10. [Conclusões](#-conclusões)

---

## 📋 Visão Geral

### O Problema

Interfaces de fala em tempo real exigem processamento de baixa latência em três frentes:
- **ASR** (Automatic Speech Recognition)
- **NLU** (Natural Language Understanding)
- **TTS** (Text-to-Speech)

**Problema tradicional:** Encadear modelos sequencialmente resulta em atrasos cumulativos, limitando a usabilidade prática.

### A Solução Proposta

O artigo apresenta um **pipeline end-to-end de voz-para-voz** otimizado para cenários de telecomunicações, como:
- Automação de call centers
- Sistemas IVR (Interactive Voice Response) conversacionais
- Suporte ao cliente
- Diagnósticos técnicos

### Principais Contribuições

| Contribuição | Descrição |
|--------------|-----------|
| **Sentence-level streaming** | O LLM transmite sentenças incrementalmente ao TTS para saída de áudio contínua |
| **Quantização 4-bit** | Reduz footprint de memória GPU e latência de inferência |
| **Execução concorrente** | ASR, LLM e TTS operam em paralelo via padrão producer-consumer |
| **RAG integrado** | Retrieval-Augmented Generation sobre documentos de telecom |
| **Análise detalhada** | Breakdown de latência por componente |

### Resultado Principal

- **Latência média total:** 0.934 segundos
- **RTF (Real-Time Factor):** < 1.0 em todos os componentes
- **Time-to-First-Audio:** 0.678 segundos

---

## 🏗️ Arquitetura do Pipeline

### Diagrama Geral

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PIPELINE COMPLETO                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐    ┌─────────────┐    ┌─────────────────────────┐    │
│  │ Input Audio  │───▶│ Streaming   │───▶│      Transcript         │    │
│  │              │    │ ASR (TTE)   │    │                         │    │
│  └──────────────┘    └─────────────┘    └───────────┬─────────────┘    │
│                                                     │                   │
│                                                     ▼                   │
│                      ┌──────────────────────────────────────────┐      │
│                      │           RAG SUBSYSTEM                  │      │
│                      │  ┌─────────────┐   ┌─────────────────┐  │      │
│                      │  │ Embed       │   │  Document       │  │      │
│                      │  │ Transcript  │   │  Index (FAISS)  │  │      │
│                      │  │ (T-VEC)     │   │                 │  │      │
│                      │  └──────┬──────┘   └────────┬────────┘  │      │
│                      │         │                   │           │      │
│                      │         └───────┬───────────┘           │      │
│                      │                 ▼                       │      │
│                      │     ┌───────────────────────┐          │      │
│                      │     │  FAISS Similarity     │          │      │
│                      │     │  Search               │          │      │
│                      │     └───────────┬───────────┘          │      │
│                      │                 │                       │      │
│                      │                 ▼                       │      │
│                      │     ┌───────────────────────┐          │      │
│                      │     │  Retrieved Chunks     │          │      │
│                      │     └───────────┬───────────┘          │      │
│                      └─────────────────┼────────────────────────┘      │
│                                        │                               │
│                                        ▼                               │
│                      ┌───────────────────────────────┐                 │
│                      │   Contextualized Prompt       │                 │
│                      └───────────────┬───────────────┘                 │
│                                      │                                 │
│         ┌────────────────────────────┴────────────────────────┐       │
│         │                  THREADING                          │       │
│         │  ┌─────────────────────┐  ┌─────────────────────┐  │       │
│         │  │ LLM Thread          │  │ TTS Thread          │  │       │
│         │  │ (TSLAM-Mini-2B)     │  │ (T-SYNTH)           │  │       │
│         │  │                     │  │                     │  │       │
│         │  │ Producer            │─▶│ Consumer            │  │       │
│         │  │ (sentences)         │  │ (audio chunks)      │  │       │
│         │  └─────────────────────┘  └──────────┬──────────┘  │       │
│         └──────────────────────────────────────┼──────────────┘       │
│                                                │                       │
│                                                ▼                       │
│                               ┌───────────────────────────┐           │
│                               │      Output Audio         │           │
│                               │      (WAV file)           │           │
│                               └───────────────────────────┘           │
└─────────────────────────────────────────────────────────────────────────┘
```

### Fluxo de Dados

```
1. Input Audio
      │
      ▼
2. ASR (T-Transcribe Engine) ──────────────────▶ Transcript
      │
      ▼
3. Embed Transcript (T-VEC) ──▶ Query Vector
      │
      ▼
4. FAISS Search ──▶ Retrieved Context Chunks
      │
      ▼
5. Contextualized Prompt = Transcript + Context
      │
      ▼
6. LLM Generation (TSLAM-Mini-2B, 4-bit) ──▶ Streaming Sentences
      │                                              │
      │                            ┌─────────────────┘
      │                            ▼
      │                   7. Binary Serialization (msgpack)
      │                            │
      │                            ▼
      └─────────────────▶ 8. TTS Synthesis (T-SYNTH) ──▶ Audio Chunks
                                   │
                                   ▼
                          9. Concatenated WAV Output
```

---

## 🔧 Componentes Detalhados

### 3.1 Streaming ASR Module (T-Transcribe Engine - TTE)

#### Arquitetura

| Característica | Especificação |
|----------------|---------------|
| **Tipo** | Conformer-based |
| **Training** | CTC (Connectionist Temporal Classification) |
| **RTF** | < 0.2 em GPU |
| **Otimização** | Específico para telecom/call-center |

#### O que é Conformer?

O **Conformer** (Convolution-augmented Transformer) combina:
- **Camadas convolucionais:** Capturam dependências acústicas locais
- **Camadas de self-attention:** Capturam dependências globais

```
┌─────────────────────────────────────────┐
│           CONFORMER BLOCK               │
├─────────────────────────────────────────┤
│                                         │
│  Input                                  │
│    │                                    │
│    ▼                                    │
│  ┌─────────────────────┐               │
│  │ Feed-Forward (1/2)  │               │
│  └──────────┬──────────┘               │
│             │                           │
│             ▼                           │
│  ┌─────────────────────┐               │
│  │ Multi-Head Self-    │               │
│  │ Attention           │               │
│  └──────────┬──────────┘               │
│             │                           │
│             ▼                           │
│  ┌─────────────────────┐               │
│  │ Convolution Module  │  ◀── Local    │
│  └──────────┬──────────┘      features │
│             │                           │
│             ▼                           │
│  ┌─────────────────────┐               │
│  │ Feed-Forward (1/2)  │               │
│  └──────────┬──────────┘               │
│             │                           │
│             ▼                           │
│  Output                                 │
│                                         │
└─────────────────────────────────────────┘
```

#### CTC (Connectionist Temporal Classification)

- Permite saída **alignment-free** e **frame-synchronous**
- Não requer alinhamento prévio entre áudio e texto
- Ideal para streaming em tempo real

#### Modelos Alternativos de Referência

| Modelo | Framework | Uso |
|--------|-----------|-----|
| `nvidia/stt_en_conformer_ctc_small` | NVIDIA NeMo | Inglês geral |
| IndicConformer | AI4Bharat | Multilingual (Índia) |
| Conformer-1 | AssemblyAI | Treinado em 1M horas |
| SpeechBrain Conformer | SpeechBrain | Open-source toolkit |

### 3.2 Retrieval-Augmented Generation (RAG)

#### Componentes

| Componente | Ferramenta | Função |
|------------|------------|--------|
| **Embedding Model** | T-VEC (`NetoAISolutions/T-VEC`) | Codifica documentos e queries em vetores densos |
| **Vector Store** | FAISS | Busca de similaridade eficiente |
| **Indexação** | Inner-product search | Busca k-nearest neighbors |

#### Processo de Indexação (Offline/Startup)

```python
# Pseudocódigo do processo de indexação

# 1. Carregar documentos de texto
documents = load_text_files(document_directory)

# 2. Gerar embeddings com T-VEC
embeddings = t_vec_model.encode(documents)

# 3. Normalizar vetores
embeddings = normalize(embeddings)

# 4. Criar índice FAISS
index = faiss.IndexFlatIP(embedding_dim)  # Inner Product
index.add(embeddings)

# 5. Salvar índice serializado para cache
faiss.write_index(index, "index.faiss")
save_documents(documents, "documents.pkl")
```

#### Processo de Retrieval (Runtime)

```python
# 1. Receber transcript do ASR
transcript = asr_output

# 2. Gerar embedding da query
query_embedding = t_vec_model.encode(transcript)
query_embedding = normalize(query_embedding)

# 3. Buscar k vizinhos mais próximos
k = 5  # Configurável
distances, indices = index.search(query_embedding, k)

# 4. Recuperar chunks de contexto
context_chunks = [documents[i] for i in indices[0]]

# 5. Concatenar para o prompt
contextualized_prompt = f"""
Context:
{' '.join(context_chunks)}

Question: {transcript}

Answer:
"""
```

#### Por que RAG?

- **Grounding factual:** Respostas baseadas em documentos reais
- **Sem retreinamento:** Atualiza conhecimento sem fine-tuning
- **Específico de domínio:** Usa documentos RFC de telecomunicações
- **Latência baixa:** Busca em sub-segundos

### 3.3 Quantized LLM (TSLAM-Mini-2B)

#### Especificações

| Característica | Valor |
|----------------|-------|
| **Modelo** | `NetoAISolutions/TSLAM-Mini-2B` |
| **Arquitetura** | Causal LM (decoder-only) |
| **Quantização** | 4-bit (BitsAndBytes) |
| **Framework** | Hugging Face Transformers |

#### Quantização 4-bit com BitsAndBytes

**Benefícios:**
- Redução de até **40% na latência**
- Mantém **95%+ da performance original**
- Redução de **60× na complexidade computacional**
- Menor footprint de memória GPU

**Configuração:**

```python
from transformers import AutoModelForCausalLM, BitsAndBytesConfig

# Configuração de quantização 4-bit
quantization_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",  # Normal Float 4
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True  # Nested quantization
)

# Carregar modelo quantizado
model = AutoModelForCausalLM.from_pretrained(
    "NetoAISolutions/TSLAM-Mini-2B",
    quantization_config=quantization_config,
    device_map="auto"
)
```

#### Streaming Generation com PunctuatedBufferStreamer

Classe customizada que:
1. Detecta sentenças completas via regex de pontuação
2. Coloca sentenças em uma fila thread-safe
3. Permite que o TTS comece antes do LLM terminar

```python
import re
from queue import Queue
from transformers import TextStreamer

class PunctuatedBufferStreamer(TextStreamer):
    """Streamer que segmenta output em sentenças."""

    def __init__(self, tokenizer, sentence_queue, skip_prompt=True):
        super().__init__(tokenizer, skip_prompt=skip_prompt)
        self.sentence_queue = sentence_queue
        self.buffer = ""
        self.first_token_time = None

        # Regex para detectar fim de sentença
        self.sentence_end_pattern = re.compile(r'[.!?]\s*')

    def on_finalized_text(self, text, stream_end=False):
        # Registrar time-to-first-token
        if self.first_token_time is None:
            self.first_token_time = time.time()

        self.buffer += text

        # Verificar se há sentenças completas
        sentences = self.sentence_end_pattern.split(self.buffer)

        if len(sentences) > 1:
            # Enviar sentenças completas para a fila
            for sentence in sentences[:-1]:
                if sentence.strip():
                    self.sentence_queue.put(sentence.strip())

            # Manter texto incompleto no buffer
            self.buffer = sentences[-1]

        # Se streaming terminou, enviar resto do buffer
        if stream_end and self.buffer.strip():
            self.sentence_queue.put(self.buffer.strip())
            self.sentence_queue.put(None)  # Sinal de fim
```

### 3.4 Real-Time TTS (T-SYNTH)

#### Características

| Característica | Descrição |
|----------------|-----------|
| **Modelo** | T-SYNTH (proprietário NetoAI) |
| **Otimização** | Específico para telecom |
| **Warmup** | Pré-carrega com voz de referência |
| **Síntese** | Por sentença (sentence-level) |

#### Pipeline de Síntese

```python
def tts_synthesis_thread(sentence_queue, audio_chunks, tts_model):
    """Thread consumidora que sintetiza sentenças em áudio."""

    while True:
        # Aguardar próxima sentença (timeout de 0.05s)
        try:
            sentence = sentence_queue.get(timeout=0.05)
        except Empty:
            continue

        if sentence is None:  # Sinal de fim
            break

        # Deserializar se usando msgpack
        if isinstance(sentence, bytes):
            sentence = msgpack.unpackb(sentence, raw=False)

        # Sintetizar áudio
        start_time = time.time()
        audio_chunk = tts_model.synthesize(sentence)
        synthesis_time = time.time() - start_time

        # Adicionar à lista de chunks
        audio_chunks.append({
            'audio': audio_chunk,
            'sentence': sentence,
            'synthesis_time': synthesis_time
        })

    # Concatenar todos os chunks em arquivo WAV final
    final_audio = concatenate_audio(audio_chunks)
    save_wav(final_audio, "output.wav")
```

#### Warmup para Reduzir Jitter

```python
# Executar síntese dummy antes do pipeline principal
dummy_text = "This is a warmup sentence."
_ = tts_model.synthesize(dummy_text)

# Isso pré-carrega:
# - Componentes do vocoder
# - Buffers de GPU
# - Voice embeddings de referência
```

---

## ⚡ Técnicas de Otimização

### 4.1 Multi-threading e Sincronização

#### Padrão Producer-Consumer

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  LLM Thread     │     │  Sentence Queue  │     │  TTS Thread     │
│  (Producer)     │────▶│  (Thread-safe)   │────▶│  (Consumer)     │
│                 │     │                  │     │                 │
│  Gera sentenças │     │  FIFO buffer     │     │  Sintetiza      │
│  incrementais   │     │  timeout=0.05s   │     │  em paralelo    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

#### Ordem de Inicialização

```python
import threading

# 1. Iniciar TTS thread ANTES do LLM thread
#    (para carregar componentes enquanto LLM processa)
tts_thread = threading.Thread(target=tts_synthesis_thread, args=(...))
tts_thread.start()

# 2. Iniciar LLM thread
llm_thread = threading.Thread(target=llm_generation_thread, args=(...))
llm_thread.start()

# 3. Aguardar ambos terminarem
llm_thread.join()
tts_thread.join()
```

### 4.2 Serialização Binária (msgpack)

**Problema:** Overhead de comunicação entre threads com strings Python.

**Solução:** Usar `msgpack` para serialização binária.

```python
import msgpack

# No LLM thread (producer)
def send_sentence(sentence, queue):
    # Serializar para binário
    packed = msgpack.packb(sentence, use_bin_type=True)
    queue.put(packed)

# No TTS thread (consumer)
def receive_sentence(queue):
    packed = queue.get(timeout=0.05)
    # Deserializar
    sentence = msgpack.unpackb(packed, raw=False)
    return sentence
```

**Benefício:** Redução de **0.8-1.0 segundos** no tempo total do pipeline.

### 4.3 Configurações de Timeout

| Componente | Timeout | Propósito |
|------------|---------|-----------|
| Sentence Queue | 0.05s | Polling rápido sem bloqueio |
| FAISS Search | Sub-segundo | Busca eficiente em índice |
| LLM Generation | Streaming | Sem timeout fixo, usa streaming |

### 4.4 Resumo das Técnicas de Otimização

```
┌─────────────────────────────────────────────────────────────┐
│              TÉCNICAS DE BAIXA LATÊNCIA                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Conformer-based streaming ASR                           │
│     └─▶ RTF < 0.2, saída frame-synchronous                 │
│                                                             │
│  2. 4-bit LLM quantization                                  │
│     └─▶ 40% redução de latência, 95%+ qualidade            │
│                                                             │
│  3. Parallel LLM + TTS synthesis                            │
│     └─▶ Producer-consumer threading                         │
│                                                             │
│  4. Binary serialization (msgpack)                          │
│     └─▶ 0.8-1.0s economia no pipeline                       │
│                                                             │
│  5. Efficient RAG retrieval (FAISS)                         │
│     └─▶ Sub-second similarity search                        │
│                                                             │
│  6. TTS warmup                                              │
│     └─▶ Reduz jitter na primeira síntese                    │
│                                                             │
│  7. Sentence-level streaming                                │
│     └─▶ TTS começa antes do LLM terminar                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 Dataset Customizado

### Especificações

| Característica | Valor |
|----------------|-------|
| **Tamanho** | 500 utterances |
| **Tipo** | Perguntas de telecomunicações |
| **Fonte** | Documentos RFC (Request for Comments) |
| **Formato** | WAV |
| **Duração total** | ~45 minutos |
| **Duração média** | 6.36 segundos por utterance |
| **Speakers** | 2 (sotaques e velocidades variados) |

### Por que um Dataset Customizado?

| Dataset Existente | Problema para este caso |
|-------------------|-------------------------|
| LibriSpeech | Domain-agnostic, narrativo |
| Common Voice | Sem alinhamento com knowledge base |
| Spoken Wikipedia | Estrutura narrativa, não Q&A |

**Solução:** Dataset alinhado com documentos RFC para:
- Simulação realista de queries de telecom
- Compatibilidade com RAG
- Avaliação de retrieval performance

### Estrutura do Dataset

```
telecom_dataset/
├── audio/
│   ├── utterance_001.wav
│   ├── utterance_002.wav
│   └── ... (500 arquivos)
├── transcripts/
│   ├── utterance_001.txt
│   ├── utterance_002.txt
│   └── ...
├── rfc_documents/
│   ├── rfc_xxxx.txt
│   └── ... (documentos RFC)
└── metadata.json
```

### Exemplo de Utterances

```json
{
  "id": "utterance_042",
  "audio_file": "audio/utterance_042.wav",
  "transcript": "What is the purpose of the TCP three-way handshake?",
  "duration_seconds": 5.8,
  "speaker_id": "speaker_1",
  "related_rfc": "rfc793"
}
```

---

## 📈 Resultados Experimentais

### Hardware Utilizado

| Componente | Especificação |
|------------|---------------|
| **GPU** | NVIDIA H100 (80GB) |
| **RAM** | 256 GB |
| **Setup** | Single-node |
| **Precision** | Mixed-precision inference |

### Métricas de Latência (Tabela Principal)

| Métrica | Mean | Min | Max |
|---------|------|-----|-----|
| **ASR Processing** | 0.049s | 0.029s | 0.069s |
| **RAG Retrieval** | 0.008s | 0.008s | 0.012s |
| **LLM Generation** | 0.670s | 0.218s | 1.706s |
| **TTS Synthesis** | 0.286s | 0.106s | 1.769s |
| **Total Time** | **0.934s** | 0.417s | 3.154s |

### Métricas de Throughput

| Métrica | Mean | Min | Max |
|---------|------|-----|-----|
| **ASR Speed** | 394.18 words/sec | 134.24 | 1010.15 |
| **LLM Speed** | 80.06 tokens/sec | 58.60 | 86.97 |
| **Cosine Similarity** | 87.3% | 65.9% | 100% |
| **TTFT** | 0.106s | 0.077s | 0.181s |
| **TTFA** | 0.678s | 0.412s | 1.482s |

### Definições das Métricas

| Sigla | Nome | Descrição |
|-------|------|-----------|
| **RTF** | Real-Time Factor | Tempo de processamento / Duração do áudio. RTF < 1.0 = tempo real |
| **TTFT** | Time-to-First-Token | Tempo até o LLM gerar o primeiro token |
| **TTFA** | Time-to-First-Audio | Tempo até o primeiro chunk de áudio ser sintetizado |

### Análise dos Resultados

#### 1. Performance em Tempo Real

```
Threshold para interatividade: < 1.0 segundo
Média alcançada:              0.934 segundos ✓

O pipeline é adequado para sistemas interativos.
```

#### 2. Breakdown de Latência

```
┌─────────────────────────────────────────────────────────────┐
│                    BREAKDOWN DE LATÊNCIA                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  LLM Generation ████████████████████████████████░░ 71.7%   │
│  TTS Synthesis  ████████████░░░░░░░░░░░░░░░░░░░░░ 30.6%   │
│  ASR Processing ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  5.2%   │
│  RAG Retrieval  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  0.9%   │
│                                                             │
│  * Nota: LLM e TTS rodam em paralelo, então soma > 100%    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### 3. Streaming Efficiency

```
Gap entre TTFT e TTFA:
  TTFT (primeiro token LLM): 0.106s
  TTFA (primeiro áudio):     0.678s
  ─────────────────────────────────
  Gap:                       0.572s

Este gap representa o tempo para:
- Acumular tokens suficientes para uma sentença
- Serializar e transferir para TTS thread
- Sintetizar primeiro chunk de áudio
```

#### 4. Preservação Semântica

```
Cosine Similarity média: 0.873 (87.3%)

Indica forte preservação semântica entre:
- Input (transcript do ASR)
- Output (resposta do LLM)
```

#### 5. Variabilidade

```
Latência total:
- Melhor caso:  0.417s
- Média:        0.934s
- Pior caso:    3.154s

Outliers (> 2s) são raros e atribuídos a:
- Flutuações de processamento GPU
- Respostas mais longas do LLM
- Sentenças mais complexas para TTS
```

### Visualização de Latências

```
                    Latências por Componente (segundos)

RAG Retrieval   |█|                                          0.008s
                |
ASR Processing  |██|                                         0.049s
                |
TTS Synthesis   |████████████|                               0.286s
                |
LLM Generation  |████████████████████████████|               0.670s
                |
                0.0   0.2   0.4   0.6   0.8   1.0   1.2   1.4   1.6   1.8

                ├─── Error bars mostram range min-max ───┤
```

---

## 🔧 Como Reproduzir o Experimento

### Requisitos de Hardware

| Componente | Mínimo | Recomendado |
|------------|--------|-------------|
| **GPU** | NVIDIA com 24GB VRAM | NVIDIA H100 (80GB) |
| **RAM** | 64 GB | 256 GB |
| **Storage** | 50 GB SSD | 100 GB NVMe |

### Passo 1: Instalação de Dependências

```bash
# Criar ambiente virtual
python -m venv voice_agent_env
source voice_agent_env/bin/activate

# Instalar dependências principais
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

pip install transformers>=4.36.0
pip install bitsandbytes>=0.41.0
pip install faiss-gpu  # ou faiss-cpu se não tiver GPU
pip install soundfile
pip install msgpack
pip install sentence-transformers

# Para métricas
pip install numpy pandas matplotlib
```

### Passo 2: Download dos Modelos

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
from sentence_transformers import SentenceTransformer

# 1. Modelo de Embedding (T-VEC ou alternativa)
embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
# Ou modelo específico: NetoAISolutions/T-VEC

# 2. LLM com quantização 4-bit
from transformers import BitsAndBytesConfig

quantization_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
)

# Usar modelo alternativo se TSLAM-Mini-2B não disponível
llm_model = AutoModelForCausalLM.from_pretrained(
    "microsoft/phi-2",  # ou outro modelo 2-3B
    quantization_config=quantization_config,
    device_map="auto"
)
tokenizer = AutoTokenizer.from_pretrained("microsoft/phi-2")

# 3. ASR (usar NeMo ou Whisper como alternativa)
# pip install nemo_toolkit['asr']
# Ou usar openai-whisper para teste rápido
```

### Passo 3: Preparar Índice RAG

```python
import faiss
import numpy as np
from pathlib import Path

def build_rag_index(documents_dir, embedding_model, output_path):
    """Constrói índice FAISS a partir de documentos."""

    # 1. Carregar documentos
    documents = []
    doc_paths = list(Path(documents_dir).glob("*.txt"))

    for path in doc_paths:
        with open(path, 'r') as f:
            content = f.read()
            # Chunking: dividir em parágrafos ou tamanho fixo
            chunks = content.split('\n\n')
            documents.extend(chunks)

    print(f"Loaded {len(documents)} document chunks")

    # 2. Gerar embeddings
    embeddings = embedding_model.encode(
        documents,
        show_progress_bar=True,
        normalize_embeddings=True  # Normalizar para inner product
    )
    embeddings = np.array(embeddings).astype('float32')

    # 3. Criar índice FAISS
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)  # Inner Product
    index.add(embeddings)

    # 4. Salvar
    faiss.write_index(index, f"{output_path}/index.faiss")

    # Salvar documentos também
    import pickle
    with open(f"{output_path}/documents.pkl", 'wb') as f:
        pickle.dump(documents, f)

    return index, documents

# Executar
index, documents = build_rag_index(
    documents_dir="./rfc_documents",
    embedding_model=embedding_model,
    output_path="./rag_index"
)
```

### Passo 4: Implementar Pipeline Principal

```python
import threading
import time
from queue import Queue, Empty
import soundfile as sf
import msgpack
import re

class VoiceAgentPipeline:
    def __init__(self, asr_model, llm_model, tokenizer,
                 tts_model, embedding_model, faiss_index, documents):
        self.asr_model = asr_model
        self.llm_model = llm_model
        self.tokenizer = tokenizer
        self.tts_model = tts_model
        self.embedding_model = embedding_model
        self.faiss_index = faiss_index
        self.documents = documents

        # Configurações
        self.k_neighbors = 5
        self.queue_timeout = 0.05

        # Métricas
        self.metrics = {}

    def process_audio(self, audio_path):
        """Pipeline completo de processamento."""

        total_start = time.time()

        # ===== 1. ASR =====
        asr_start = time.time()
        audio, sr = sf.read(audio_path)
        transcript = self.asr_model.transcribe(audio)
        self.metrics['asr_time'] = time.time() - asr_start
        self.metrics['asr_words'] = len(transcript.split())

        # ===== 2. RAG Retrieval =====
        rag_start = time.time()
        context = self.retrieve_context(transcript)
        self.metrics['rag_time'] = time.time() - rag_start

        # ===== 3. Build Prompt =====
        prompt = self.build_prompt(transcript, context)

        # ===== 4. Parallel LLM + TTS =====
        sentence_queue = Queue()
        audio_chunks = []

        # TTS thread (consumer) - iniciar ANTES do LLM
        tts_thread = threading.Thread(
            target=self.tts_thread_func,
            args=(sentence_queue, audio_chunks)
        )
        tts_thread.start()

        # LLM thread (producer)
        llm_thread = threading.Thread(
            target=self.llm_thread_func,
            args=(prompt, sentence_queue)
        )
        llm_start = time.time()
        llm_thread.start()

        # Aguardar conclusão
        llm_thread.join()
        self.metrics['llm_time'] = time.time() - llm_start

        tts_thread.join()

        # ===== 5. Concatenar áudio =====
        final_audio = self.concatenate_audio(audio_chunks)

        self.metrics['total_time'] = time.time() - total_start

        return final_audio, self.metrics

    def retrieve_context(self, query):
        """Busca contexto relevante via RAG."""

        # Gerar embedding da query
        query_embedding = self.embedding_model.encode(
            [query],
            normalize_embeddings=True
        ).astype('float32')

        # Buscar k vizinhos
        distances, indices = self.faiss_index.search(
            query_embedding,
            self.k_neighbors
        )

        # Recuperar documentos
        context_chunks = [self.documents[i] for i in indices[0]]

        # Calcular similaridade média
        self.metrics['cosine_similarity'] = float(distances[0].mean())

        return "\n".join(context_chunks)

    def build_prompt(self, transcript, context):
        """Constrói prompt contextualizado."""

        return f"""You are a helpful telecommunications expert assistant.

Context from documentation:
{context}

User question: {transcript}

Please provide a clear, concise answer based on the context above:"""

    def llm_thread_func(self, prompt, sentence_queue):
        """Thread de geração do LLM (producer)."""

        # Tokenizar
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            padding=True
        ).to(self.llm_model.device)

        # Configurar streamer
        streamer = PunctuatedBufferStreamer(
            tokenizer=self.tokenizer,
            sentence_queue=sentence_queue,
            skip_prompt=True
        )

        # Gerar com streaming
        self.llm_model.generate(
            **inputs,
            max_new_tokens=256,
            do_sample=True,
            temperature=0.7,
            streamer=streamer
        )

        # Capturar métricas
        self.metrics['ttft'] = streamer.first_token_time - time.time()
        self.metrics['llm_tokens'] = streamer.total_tokens

    def tts_thread_func(self, sentence_queue, audio_chunks):
        """Thread de síntese TTS (consumer)."""

        # Warmup
        _ = self.tts_model.synthesize("Warmup sentence.")

        first_audio_time = None
        tts_start = time.time()

        while True:
            try:
                item = sentence_queue.get(timeout=self.queue_timeout)
            except Empty:
                continue

            if item is None:  # Sinal de fim
                break

            # Deserializar se necessário
            if isinstance(item, bytes):
                sentence = msgpack.unpackb(item, raw=False)
            else:
                sentence = item

            # Sintetizar
            synthesis_start = time.time()
            audio_chunk = self.tts_model.synthesize(sentence)
            synthesis_time = time.time() - synthesis_start

            if first_audio_time is None:
                first_audio_time = time.time()
                self.metrics['ttfa'] = first_audio_time - tts_start

            audio_chunks.append(audio_chunk)

        self.metrics['tts_time'] = time.time() - tts_start

    def concatenate_audio(self, audio_chunks):
        """Concatena chunks de áudio."""
        if not audio_chunks:
            return np.array([])
        return np.concatenate(audio_chunks)


class PunctuatedBufferStreamer:
    """Streamer que detecta sentenças e envia para fila."""

    def __init__(self, tokenizer, sentence_queue, skip_prompt=True):
        self.tokenizer = tokenizer
        self.sentence_queue = sentence_queue
        self.skip_prompt = skip_prompt
        self.buffer = ""
        self.first_token_time = None
        self.total_tokens = 0
        self.sentence_pattern = re.compile(r'([.!?])\s*')
        self.prompt_ended = False

    def put(self, token_ids):
        """Chamado para cada batch de tokens gerados."""

        if self.first_token_time is None:
            self.first_token_time = time.time()

        # Decodificar tokens
        text = self.tokenizer.decode(token_ids, skip_special_tokens=True)
        self.total_tokens += len(token_ids)

        # Skip prompt tokens
        if self.skip_prompt and not self.prompt_ended:
            if "[/INST]" in text or "Answer:" in text:
                self.prompt_ended = True
                text = text.split("[/INST]")[-1].split("Answer:")[-1]
            else:
                return

        self.buffer += text
        self._flush_sentences()

    def _flush_sentences(self):
        """Envia sentenças completas para a fila."""

        parts = self.sentence_pattern.split(self.buffer)

        # Reconstruir sentenças com pontuação
        sentences = []
        i = 0
        while i < len(parts) - 1:
            if parts[i].strip():
                sentence = parts[i].strip()
                if i + 1 < len(parts) and parts[i + 1] in '.!?':
                    sentence += parts[i + 1]
                sentences.append(sentence)
            i += 2

        # Enviar sentenças para fila (com serialização msgpack)
        for sentence in sentences:
            packed = msgpack.packb(sentence, use_bin_type=True)
            self.sentence_queue.put(packed)

        # Manter resto no buffer
        if len(parts) > 0:
            self.buffer = parts[-1]

    def end(self):
        """Chamado quando geração termina."""

        # Enviar resto do buffer
        if self.buffer.strip():
            packed = msgpack.packb(self.buffer.strip(), use_bin_type=True)
            self.sentence_queue.put(packed)

        # Sinal de fim
        self.sentence_queue.put(None)
```

### Passo 5: Executar e Avaliar

```python
import json
from pathlib import Path

def evaluate_pipeline(pipeline, test_audio_dir, output_dir):
    """Avalia o pipeline em um conjunto de áudios de teste."""

    results = []
    audio_files = list(Path(test_audio_dir).glob("*.wav"))

    for audio_path in audio_files:
        print(f"Processing: {audio_path.name}")

        try:
            output_audio, metrics = pipeline.process_audio(str(audio_path))

            # Salvar áudio de saída
            output_path = Path(output_dir) / f"output_{audio_path.name}"
            sf.write(output_path, output_audio, 22050)

            results.append({
                'input_file': audio_path.name,
                'output_file': output_path.name,
                **metrics
            })

        except Exception as e:
            print(f"Error processing {audio_path.name}: {e}")
            results.append({
                'input_file': audio_path.name,
                'error': str(e)
            })

    # Salvar resultados
    with open(Path(output_dir) / "evaluation_results.json", 'w') as f:
        json.dump(results, f, indent=2)

    # Calcular estatísticas
    valid_results = [r for r in results if 'error' not in r]

    stats = {
        'mean_total_time': np.mean([r['total_time'] for r in valid_results]),
        'mean_asr_time': np.mean([r['asr_time'] for r in valid_results]),
        'mean_rag_time': np.mean([r['rag_time'] for r in valid_results]),
        'mean_llm_time': np.mean([r['llm_time'] for r in valid_results]),
        'mean_tts_time': np.mean([r['tts_time'] for r in valid_results]),
        'mean_ttft': np.mean([r['ttft'] for r in valid_results]),
        'mean_ttfa': np.mean([r['ttfa'] for r in valid_results]),
        'mean_cosine_similarity': np.mean([r['cosine_similarity'] for r in valid_results]),
    }

    print("\n=== EVALUATION STATISTICS ===")
    for key, value in stats.items():
        print(f"{key}: {value:.4f}")

    return results, stats


# Executar avaliação
if __name__ == "__main__":
    # Inicializar pipeline
    pipeline = VoiceAgentPipeline(
        asr_model=asr_model,
        llm_model=llm_model,
        tokenizer=tokenizer,
        tts_model=tts_model,
        embedding_model=embedding_model,
        faiss_index=index,
        documents=documents
    )

    # Avaliar
    results, stats = evaluate_pipeline(
        pipeline=pipeline,
        test_audio_dir="./test_audio",
        output_dir="./output"
    )
```

### Passo 6: Coletar Métricas Detalhadas

```python
class MetricsReporter:
    """Classe para coleta e relatório de métricas."""

    def __init__(self):
        self.metrics = {
            'asr': [],
            'rag': [],
            'llm': [],
            'tts': [],
            'total': [],
            'ttft': [],
            'ttfa': [],
            'asr_speed': [],
            'llm_speed': [],
            'cosine_similarity': []
        }

    def add_sample(self, sample_metrics):
        """Adiciona métricas de uma amostra."""

        self.metrics['asr'].append(sample_metrics['asr_time'])
        self.metrics['rag'].append(sample_metrics['rag_time'])
        self.metrics['llm'].append(sample_metrics['llm_time'])
        self.metrics['tts'].append(sample_metrics['tts_time'])
        self.metrics['total'].append(sample_metrics['total_time'])
        self.metrics['ttft'].append(sample_metrics['ttft'])
        self.metrics['ttfa'].append(sample_metrics['ttfa'])

        # Calcular speeds
        asr_speed = sample_metrics['asr_words'] / sample_metrics['asr_time']
        llm_speed = sample_metrics['llm_tokens'] / sample_metrics['llm_time']

        self.metrics['asr_speed'].append(asr_speed)
        self.metrics['llm_speed'].append(llm_speed)
        self.metrics['cosine_similarity'].append(
            sample_metrics['cosine_similarity']
        )

    def report(self):
        """Gera relatório completo."""

        print("\n" + "="*60)
        print("LATENCY AND PERFORMANCE METRICS")
        print("="*60)

        headers = ['Metric', 'Mean', 'Min', 'Max', 'Std']

        metrics_to_report = [
            ('ASR Processing (s)', 'asr'),
            ('RAG Retrieval (s)', 'rag'),
            ('LLM Generation (s)', 'llm'),
            ('TTS Synthesis (s)', 'tts'),
            ('Total Time (s)', 'total'),
            ('TTFT (s)', 'ttft'),
            ('TTFA (s)', 'ttfa'),
            ('ASR Speed (words/s)', 'asr_speed'),
            ('LLM Speed (tokens/s)', 'llm_speed'),
            ('Cosine Similarity', 'cosine_similarity'),
        ]

        for name, key in metrics_to_report:
            values = self.metrics[key]
            print(f"{name:25} | "
                  f"Mean: {np.mean(values):8.3f} | "
                  f"Min: {np.min(values):8.3f} | "
                  f"Max: {np.max(values):8.3f}")

        print("="*60)

        # GPU info
        if torch.cuda.is_available():
            print(f"\nGPU: {torch.cuda.get_device_name(0)}")
            print(f"GPU Memory: {torch.cuda.memory_allocated()/1e9:.2f} GB / "
                  f"{torch.cuda.get_device_properties(0).total_memory/1e9:.2f} GB")
```

---

## 📚 Ferramentas e Recursos

### Modelos Utilizados (NetoAI - Proprietários)

| Modelo | Função | Alternativa Open-Source |
|--------|--------|------------------------|
| **T-Transcribe Engine (TTE)** | Streaming ASR | `nvidia/stt_en_conformer_ctc_small`, Whisper |
| **T-VEC** | Document Embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| **TSLAM-Mini-2B** | LLM | `microsoft/phi-2`, `TinyLlama/TinyLlama-1.1B-Chat` |
| **T-SYNTH** | TTS | `suno/bark`, `coqui/XTTS-v2` |

### Bibliotecas e Frameworks

| Biblioteca | Versão | Uso |
|------------|--------|-----|
| **PyTorch** | >= 2.0 | Backend de deep learning |
| **Transformers** | >= 4.36 | Carregamento de modelos |
| **BitsAndBytes** | >= 0.41 | Quantização 4-bit |
| **FAISS** | >= 1.7 | Busca de similaridade |
| **soundfile** | >= 0.12 | Leitura/escrita de áudio |
| **msgpack** | >= 1.0 | Serialização binária |
| **NeMo** | >= 1.20 | ASR (opcional) |

### Links Úteis

| Recurso | URL |
|---------|-----|
| NVIDIA NeMo ASR | https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/models.html |
| BitsAndBytes | https://github.com/TimDettmers/bitsandbytes |
| FAISS | https://github.com/facebookresearch/faiss |
| SpeechBrain | https://speechbrain.readthedocs.io |
| Hugging Face Transformers | https://huggingface.co/docs/transformers |

### Datasets de Referência

| Dataset | Uso | Link |
|---------|-----|------|
| LibriSpeech | Benchmark ASR | https://www.openslr.org/12 |
| Common Voice | Multilingual ASR | https://commonvoice.mozilla.org |
| RFC Documents | Telecom knowledge base | https://www.rfc-editor.org |

---

## ⚠️ Limitações

### 1. Erros de ASR Propagam para RAG

```
Problema:
  ASR com erros em abreviações, nomes próprios, termos técnicos
  ↓
  Embedding incorreto
  ↓
  Retrieval de documentos irrelevantes
  ↓
  Resposta do LLM degradada
```

**Mitigação sugerida:**
- Usar ASR maiores ou especializados no domínio
- Post-processamento de correção ortográfica
- Fine-tuning do ASR em terminologia de telecom

### 2. Variabilidade de Latência

```
Melhor caso:  0.417s
Média:        0.934s
Pior caso:    3.154s  (7.5× o melhor caso)
```

**Causas:**
- Flutuações de processamento GPU
- Comprimento variável de respostas
- Complexidade de síntese TTS

### 3. Dependência de Hardware

- Requer GPU com alto VRAM para performance ótima
- Quantização 4-bit ainda exige GPU moderna
- H100 usado nos experimentos não é acessível para todos

### 4. Modelos Proprietários

- T-Transcribe Engine, T-VEC, TSLAM-Mini, T-SYNTH são proprietários
- Reprodução exata requer acesso aos modelos NetoAI
- Alternativas open-source podem ter performance diferente

---

## 🎯 Conclusões

### Principais Achievements

1. **Latência média < 1 segundo** - Adequado para sistemas interativos
2. **RTF < 1.0** em todos os componentes - Processamento em tempo real
3. **87.3% de similaridade semântica** - Preservação do significado
4. **RAG eficiente** - Retrieval em ~8ms
5. **Pipeline reproduzível** - Metodologia documentada

### Técnicas-Chave para Baixa Latência

```
┌─────────────────────────────────────────────────────────────┐
│           RECEITA PARA VOZ EM TEMPO REAL                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. ASR Streaming (Conformer + CTC)                         │
│     • Saída frame-synchronous                               │
│     • RTF < 0.2                                             │
│                                                             │
│  2. LLM Quantizado (4-bit)                                  │
│     • 40% redução de latência                               │
│     • 95%+ qualidade mantida                                │
│                                                             │
│  3. Streaming Sentence-Level                                │
│     • TTS começa antes do LLM terminar                      │
│     • Detecção de sentenças via regex                       │
│                                                             │
│  4. Threading Producer-Consumer                             │
│     • Execução paralela LLM + TTS                           │
│     • Queue thread-safe com timeout                         │
│                                                             │
│  5. Serialização Binária (msgpack)                          │
│     • 0.8-1.0s economia                                     │
│                                                             │
│  6. RAG com FAISS                                           │
│     • Busca em sub-segundo                                  │
│     • Grounding factual                                     │
│                                                             │
│  7. TTS Warmup                                              │
│     • Pré-carrega componentes                               │
│     • Reduz jitter na primeira síntese                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Aplicabilidade

O pipeline é adequado para:
- Call center automation
- IVR (Interactive Voice Response) conversacional
- Suporte ao cliente
- Diagnósticos técnicos
- Assistentes de voz empresariais

### Trabalhos Futuros (Sugeridos pelos Autores)

1. **Escalabilidade multi-domínio** - Além de telecom
2. **Suporte multilíngue** - Não apenas inglês
3. **Aprendizado adaptativo** - Melhoria contínua em produção

---

## 📝 Comparação: Este Artigo vs LLaMA-Omni 2

| Aspecto | Voice Agents (este artigo) | LLaMA-Omni 2 |
|---------|---------------------------|--------------|
| **Abordagem** | Pipeline cascata otimizado | Modelo end-to-end integrado |
| **ASR** | Streaming Conformer-CTC | Whisper encoder integrado |
| **LLM** | Quantizado 4-bit separado | LLM base (Qwen2.5) integrado |
| **TTS** | Modelo separado (T-SYNTH) | Autoregressive streaming decoder |
| **Latência média** | 0.934s | ~0.58s (7B model) |
| **RAG** | Sim (FAISS) | Não |
| **Treinamento** | Usa modelos pré-treinados | 200K amostras fine-tuning |
| **Foco** | Telecom/Call center | General-purpose |
| **Modularidade** | Alta (substituir componentes) | Baixa (modelo integrado) |

---

*Documento criado para fins educacionais e de reprodução de experimentos.*
*Baseado no artigo arXiv:2508.04721v1 (Agosto 2025).*
