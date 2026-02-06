# ASP Config Flow - Como o protocolo integra com AI Agent e AI Transcribe

Como o Audio Session Protocol (ASP) negocia e propaga configuracoes de audio
para todos os servicos do pipeline de voz.

## Visao Geral

O ASP roda sobre WebSocket e tem 3 camadas:

```
+-----------------------------------------------------------+
|  Camada 1: Negociacao (JSON)                              |
|  session.start -> negotiate -> session.started             |
|  Define: sample_rate, encoding, frame_duration, VAD       |
+-----------------------------------------------------------+
|  Camada 2: Controle de Sessao (JSON)                      |
|  audio.speech_start, audio.speech_end                     |
|  response.start, response.end, call.action                |
+-----------------------------------------------------------+
|  Camada 3: Streaming de Audio (Binario)                   |
|  [0x01][direction][session_hash 8B][reserved 2B][PCM...]  |
|  Header: 12 bytes + payload PCM                           |
+-----------------------------------------------------------+
```

O **Media Server** e o **cliente ASP** - ele inicia sessoes.
O **AI Agent** e o **AI Transcribe** sao **servidores ASP** - eles recebem,
negociam e aceitam/rejeitam.

---

## Fluxo Completo: Conexao -> Negociacao -> Streaming

```
 Media Server                          AI Agent / AI Transcribe
 (cliente ASP)                         (servidor ASP)
 ===================================================================

 1. WebSocket connect
    ------------------------------------->

 2.                                    Envia capabilities
    <------------------------------------- protocol.capabilities
                                        {
                                          supported_sample_rates: [8000, 16000],
                                          supported_encodings: ["pcm_s16le"],
                                          vad_configurable: true,
                                          features: ["barge_in", "streaming_tts"]
                                        }

 3. Envia pedido de sessao
    session.start ----------------------->
    {
      session_id: "550e8400...",
      call_id: "1004-...",
      audio: {                          4. Negocia configuracao
        sample_rate: 8000,                 negotiate_config(caps, audio, vad)
        encoding: "pcm_s16le",             |
        channels: 1,                       +- sample_rate 8000 in [8000,16000]? OK
        frame_duration_ms: 20              +- encoding pcm_s16le suportado? OK
      },                                   +- VAD params dentro dos ranges? OK
      vad: {                               +- Gera NegotiatedConfig
        silence_threshold_ms: 500,
        min_speech_ms: 250             5. Responde
      }                                <-- session.started
    }                                      {
                                             status: "accepted",
                                             negotiated: {
                                               audio: { sample_rate: 8000, ... },
                                               vad: { silence_threshold_ms: 500, ... },
                                               adjustments: []
                                             }
                                           }

 6. Armazena config negociado
    ASPClientSession.negotiated = ...

 7. Comeca streaming de audio
    AudioFrame (binary) ----------------> Recebe, parsea, acumula em buffer
    AudioFrame (binary) ----------------> (buffer usa sample_rate da sessao)
    AudioFrame (binary) ---------------->
    ...

 8. VAD detecta fim de fala
    audio.speech_end ------------------->  Flush buffer -> STT -> processa
```

---

## Onde o config ASP e usado em cada servico

### AI Agent (pipeline STT -> LLM -> TTS)

```
session.start (sample_rate=8000)
    |
    v
websocket.py: _handle_session_start()
    |  negotiate_config() -> NegotiatedConfig
    |  Extrai: sample_rate, encoding, frame_duration_ms
    v
session.py: SessionManager.create_session()
    |  Cria Session com AudioConfig da negociacao
    |  Passa para AudioBuffer(sample_rate=8000, frame_duration_ms=20)
    v
vad.py: AudioBuffer.__init__()
    |  self.sample_rate = 8000  (nao hardcoded 16000)
    |  self.frame_size = 8000 * 20/1000 * 2 = 320 bytes
    |  self.MAX_BUFFER_SIZE = 8000 * 2 * 10s = 160KB
    v
websocket.py: _handle_audio_end()
    |  Flush buffer -> audio_data (bytes)
    |  Calcula buffer cap: sr * 2 * 3s (dinamico, nao hardcoded)
    |  Calcula RMS energy (pre-filtro antes do STT)
    |  Passa input_sample_rate=session.audio_config.sample_rate
    v
conversation.py: process_async(audio, input_sample_rate=8000)
    |  Calcula duracao: len(audio) / 2 / 8000 * 1000
    |  Passa input_sample_rate ao STT
    v
stt.py: FasterWhisperSTT.transcribe(audio, input_sample_rate=8000)
    |  Whisper espera 16kHz float32
    |  Resamplea 8kHz -> 16kHz com np.interp()
    |  Transcreve com modelo Whisper
    v
tts.py: synthesize_stream(text)
    |  Chunk size = output_sample_rate * 0.1 * 2 (dinamico)
    v
sentence_pipeline.py: _synthesize_sentence()
       Chunk size = tts.sample_rate * 0.1 * 2 (dinamico)
```

### AI Transcribe (STT -> Elasticsearch)

```
session.start (sample_rate=8000)
    |
    v
websocket.py: _handle_session_start()
    |  negotiate_config() -> NegotiatedConfig
    |  Extrai: sample_rate, encoding
    v
session.py: SessionManager.create_session(sample_rate=8000)
    |  TranscribeSession.sample_rate = 8000
    |  TranscribeSession.sample_width = 2
    |  __post_init__(): fallback para AUDIO_CONFIG se 0
    v
session.py: add_audio()
    |  max_buffer_size = self.sample_rate * self.sample_width * max_seconds
    |  (era: AUDIO_CONFIG["sample_rate"] * AUDIO_CONFIG["sample_width"])
    v
session.py: buffer_duration_ms
    |  bytes_per_second = self.sample_rate * self.sample_width
    |  (era: AUDIO_CONFIG["sample_rate"] * AUDIO_CONFIG["sample_width"])
    v
websocket.py: _transcribe_and_index()
    |  stt.transcribe(audio, input_sample_rate=session.sample_rate)
    v
stt_provider.py: transcribe(audio, input_sample_rate=8000)
    |  sr = input_sample_rate or self._sample_rate
    |  _calculate_audio_duration(audio, sample_rate=sr)
    |  _save_wav(f, audio, sample_rate=sr)  <- WAV header diz 8kHz
    |  faster-whisper le WAV, sabe que e 8kHz, resamplea internamente
    v
    Resultado -> Elasticsearch
```

---

## Frame Binario de Audio

Cada frame de audio enviado pelo WebSocket e binario com header de 12 bytes:

```
Offset  Size   Campo              Valor
------  -----  -----------------  ---------------------------------
0       1      Magic              0x01 (identifica frame de audio)
1       1      Direction          0x00=inbound (user), 0x01=outbound (agent)
2-9     8      Session Hash       MD5(session_id)[:8]
10-11   2      Reserved           0x0000
12+     N      Audio Data         PCM 16-bit LE, mono
```

Para 20ms @ 8kHz: `N = 8000 * 0.020 * 2 = 320 bytes`, frame total = **332 bytes**.

O **session hash** permite que o servidor identifique a qual sessao pertence
o frame sem precisar de uma mensagem JSON separada. E o MD5 truncado em 8
bytes do `session_id`.

---

## Media Fork: Como o audio chega nos dois servicos

```
                    StreamingAudioPort
                    (callback RTP do PJSUA2)
                           |
                           | audio_data (8kHz PCM)
                           v
                    MediaForkManager.fork_audio()
                    (NUNCA bloqueia - O(1) push)
                           |
                           v
                      RingBuffer (500ms)
                           |
                           v (async consumer)
                      ForkConsumer
                      +----+----+
                      |         |
                      v         v
              AIAgentAdapter  TranscribeAdapter
              send_audio()    send_audio()
                 |               |
                 |               |
                 v               v
             AI Agent       AI Transcribe
          (STT->LLM->TTS)  (STT->Elastic)
```

Ambos recebem o **mesmo audio, no mesmo formato, via o mesmo protocolo ASP**.
A diferenca e o que fazem com o resultado:

- **AI Agent**: transcreve -> raciocina (LLM) -> sintetiza voz (TTS) -> devolve audio
- **AI Transcribe**: transcreve -> indexa no Elasticsearch (sem resposta de audio)

---

## Principio fundamental: Config flui do ASP, nao de env vars

**Antes** (problema): cada servico usava `AUDIO_CONFIG` do `.env` para tudo -
sample_rate, buffer sizes, WAV headers. Se o media-server negociasse 8kHz mas
o ai-agent tivesse `SAMPLE_RATE=16000` no env, os calculos de buffer e duracao
ficavam errados.

**Agora** (correto): o config ASP negociado e armazenado **per-session** e
propagado por todo o pipeline:

```python
# AI Agent - session.py
session = Session(
    audio_config=negotiated.audio,  # <- vem do ASP
    audio_buffer=AudioBuffer(
        sample_rate=audio_config.sample_rate,           # <- ASP
        frame_duration_ms=audio_config.frame_duration_ms,  # <- ASP
    ),
)

# AI Transcribe - session.py
session = TranscribeSession(
    sample_rate=negotiated_sample_rate,   # <- ASP
    sample_width=negotiated_sample_width, # <- ASP
)
```

O `AUDIO_CONFIG` do `.env` serve apenas como **fallback** quando o ASP nao
negocia (modo legado ou campo ausente).

---

## Pontos de atencao para revisao

### 1. Resampling no ai-agent

O STT (Whisper) espera 16kHz. Quando o ASP negocia 8kHz, o `stt.py` faz
`np.interp()` para upsample antes de passar ao modelo. No ai-transcribe isso
nao e necessario porque ele salva WAV com header correto e o faster-whisper
resamplea internamente ao ler o arquivo.

**Arquivo:** `ai-agent/providers/stt.py` - metodo `transcribe()`

```python
# Whisper espera audio a 16kHz. Resamplea se necessario.
input_sr = input_sample_rate or self._stt_config.sample_rate
whisper_sr = 16000
if input_sr != whisper_sr:
    n_target = int(len(audio_np) * whisper_sr / input_sr)
    x_orig = np.arange(len(audio_np))
    x_target = np.linspace(0, len(audio_np) - 1, n_target)
    audio_np = np.interp(x_target, x_orig, audio_np)
```

### 2. Buffer backpressure

Tanto no ai-agent quanto no ai-transcribe, o tamanho maximo do buffer e
calculado com `session.sample_rate * sample_width * max_seconds`, nao com
constantes globais.

**ai-agent** (`vad.py`):
```python
self.MAX_BUFFER_SIZE = self.sample_rate * 2 * max_buffer_seconds
```

**ai-transcribe** (`session.py`):
```python
max_buffer_size = self.sample_rate * self.sample_width * AUDIO_CONFIG["max_buffer_seconds"]
```

### 3. Estado do ai-agent durante playback

Quando `session.state != 'listening'` (ex: durante TTS playback), frames de
audio sao ignorados e `audio.speech_end` e descartado para evitar processar
eco do proprio TTS.

**Arquivo:** `ai-agent/server/websocket.py` - metodo `_handle_audio_end()`

### 4. Fallback graceful

Se o servidor nao enviar `protocol.capabilities` em 5s, o media-server assume
modo legado e envia audio sem negociacao ASP. Os servidores tratam isso com
defaults do `AUDIO_CONFIG`.

---

## Arquivos relevantes

| Arquivo | Responsabilidade |
|---------|-----------------|
| `shared/asp_protocol/config.py` | AudioConfig, VADConfig, ProtocolCapabilities, NegotiatedConfig |
| `shared/asp_protocol/messages.py` | Mensagens JSON (SessionStart, SessionStarted, etc) |
| `shared/asp_protocol/negotiation.py` | ConfigNegotiator, negotiate_config() |
| `shared/asp_protocol/errors.py` | Codigos de erro (2001=unsupported_sample_rate, etc) |
| `shared/ws/protocol.py` | Frame binario (AudioFrame, magic byte, session hash) |
| `media-server/ws/client.py` | Cliente WebSocket com suporte ASP |
| `media-server/ws/client_asp.py` | Handler ASP no lado do cliente |
| `media-server/core/media_fork_manager.py` | Multiplexing para AI Agent + AI Transcribe |
| `media-server/adapters/transcribe_adapter.py` | Adapter que envia audio para AI Transcribe |
| `ai-agent/server/websocket.py` | Recebe session.start, negocia, cria sessao com config ASP |
| `ai-agent/server/session.py` | Session com AudioConfig, AudioBuffer com sample_rate ASP |
| `ai-agent/providers/stt.py` | Resampling 8kHz->16kHz usando input_sample_rate da sessao |
| `ai-transcribe/server/websocket.py` | Recebe session.start, passa config ASP para sessao |
| `ai-transcribe/server/session.py` | TranscribeSession com sample_rate/sample_width da sessao ASP |
| `ai-transcribe/transcriber/stt_provider.py` | WAV header e duracao usam sample_rate da sessao |

---

## Checklist para novos servicos

Se voce esta criando um novo servico que recebe audio via ASP:

- [ ] Importar `asp_protocol` do diretorio `shared/`
- [ ] Enviar `protocol.capabilities` ao aceitar conexao WebSocket
- [ ] Processar `session.start` com `negotiate_config()`
- [ ] Armazenar config negociado **per-session** (nao em variavel global)
- [ ] Usar `session.sample_rate` em todos os calculos de buffer e duracao
- [ ] Passar `input_sample_rate` para qualquer provider que processe audio
- [ ] Ter fallback para `AUDIO_CONFIG` quando ASP nao esta disponivel
- [ ] Logar config ASP efetivo ao criar sessao (para debug)
