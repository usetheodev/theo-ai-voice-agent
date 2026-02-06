# Respostas Tecnicas — Theo AI Voice Agent

> **Ultima atualizacao:** 2026-02-06
>
> Este documento responde de forma estruturada e rastreavel as perguntas tecnicas, duvidas de arquitetura e decisoes pendentes do projeto Theo.
> Cada resposta contem evidencia (arquivo:linha), decisao explicita e impacto mapeado.

---

## Indice

1. [Arquitetura Geral](#1-arquitetura-geral)
2. [Controle de Chamada (Asterisk / AMI)](#2-controle-de-chamada-asterisk--ami)
3. [Estado da Chamada (Call State)](#3-estado-da-chamada-call-state)
4. [ASP Protocol](#4-asp-protocol)
5. [Tool Calling (IA)](#5-tool-calling-ia)
6. [Pipeline de Audio (STT / TTS)](#6-pipeline-de-audio-stt--tts)
7. [Observabilidade e Debug](#7-observabilidade-e-debug)
8. [Seguranca](#8-seguranca)
9. [Falhas e Fallbacks](#9-falhas-e-fallbacks)
10. [Decisoes Pendentes](#10-decisoes-pendentes)

---

## 1. Arquitetura Geral

### Qual e a responsabilidade exata de cada servico?

| Servico | Autoridade | O que NAO sabe |
|---------|-----------|----------------|
| **Asterisk** | Roteamento SIP, bridging, dialplan, MOH, fallback automatico | Que existe IA no sistema |
| **Media Server** | Orquestracao SIP↔WS, Media Fork, extrai `caller_channel`, executa AMI Redirect | Logica do LLM, linguagem natural |
| **AI Agent** | Pipeline STT→LLM→TTS, tool calling (`transfer_call`, `end_call`), conversacao | SIP, AMI, `caller_channel`, contextos do dialplan |
| **AI Transcribe** | Transcricao em tempo real → Elasticsearch, busca semantica | Logica da IA, controle de chamadas |

**Evidencia:**

- `docker-compose.yml` — definicao de servicos, portas, redes
- `ai-agent/ai_agent.py:28-93` — entry point do AI Agent
- `media-server/media_server.py:32-241` — entry point do Media Server
- `ai-transcribe/ai_transcribe.py:36-202` — entry point do AI Transcribe

### Detalhamento por servico

#### Asterisk (PABX)

- **Container:** `asterisk-pabx` (image: `mlan/asterisk`)
- **Portas:** 5160 (SIP/UDP), 8188 (HTTP/WS), 8189 (HTTPS/WSS), 20000-20100 (RTP), 5038 (AMI)
- **Responsabilidades:**
  - Gerenciar ramais SIP (1001-1005, 2000 para Media Server)
  - Roteamento de chamadas via dialplan (`extensions.conf`)
  - Manutencao de Music on Hold (MOH)
  - Gerenciamento automatico de fallback em transferencias assistidas
  - Expor interface AMI na porta 5038 para controle externo
- **Arquivo critico:** `asterisk/config/extensions.conf` (contexto `[transfer-assistida]`)

#### Media Server (SIP Bridge)

- **Container:** `sip-media-server`
- **Portas:** 40000-40100 (RTP), 9091 (Prometheus)
- **Linguagem:** Python 3 com pjsua2 (binding C para PJSIP)
- **Responsabilidades:**
  1. Registrar ramal 2000 no Asterisk via PJSIP (`sip/endpoint.py:26`)
  2. Capturar audio do chamador via streaming ports (`sip/streaming_port.py`)
  3. Orquestrar Media Fork Manager — isolamento do path critico (`core/media_fork_manager.py:61`)
  4. Conectar ao AI Agent via WebSocket ASP (`adapters/ai_agent_adapter.py:16`)
  5. Executar AMI Redirect para transferencias assistidas (`ami/client.py:22`)
  6. Conectar ao AI Transcribe (opcional) (`adapters/transcribe_adapter.py:25`)

#### AI Agent (Servidor de Conversacao)

- **Container:** `ai-conversation-agent`
- **Portas:** 8765 (WebSocket), 9090 (Prometheus)
- **Linguagem:** Python 3 assincrono (asyncio)
- **Responsabilidades:**
  1. Receber audio via WebSocket do Media Server (`server/websocket.py:58`)
  2. Pipeline STT→LLM→TTS (`pipeline/conversation.py:34`)
  3. Gerenciar Tool Calling para controle de chamadas (`tools/call_actions.py:35-82`)
  4. Emitir metricas Prometheus (`metrics/prometheus_metrics.py`)

#### AI Transcribe (Transcricao em Tempo Real)

- **Container:** `ai-transcribe`
- **Portas:** 8766 (WebSocket), 8767 (HTTP API busca semantica), 9093 (Prometheus)
- **Responsabilidades:**
  1. Receber audio via WebSocket do Media Server (`server/websocket.py`)
  2. Transcrever audio com FasterWhisper (`transcriber/stt_provider.py`)
  3. Gerar embeddings semanticos (`embeddings/embedding_provider.py`)
  4. Indexar no Elasticsearch (`indexer/elasticsearch_client.py`)
  5. Expor HTTP API para busca semantica (`server/http_api.py`)

### Onde termina a autoridade do AI Agent e comeca a do Media Server?

A fronteira e o **protocolo ASP via WebSocket** (`shared/asp_protocol/`):

```
AI Agent                                    Media Server
─────────────────────────────────────────────────────────
Recebe audio (binary frames)          ←     Captura RTP + fork
Processa STT→LLM→TTS
Envia audio sintetizado (binary)      →     Reproduz via StreamingPlaybackPort
Envia CallActionMessage (JSON)        →     Executa AMI Redirect
                                            Extrai caller_channel do INVITE
                                            Guarda pending_call_action
```

**Regra fundamental:**

- AI Agent **nunca** acessa `caller_channel`, **nunca** executa AMI, **nunca** sabe o contexto do dialplan
- Media Server **nunca** processa linguagem natural, **nunca** decide transferir

**Evidencia:** `media-server/adapters/ai_agent_adapter.py:16`, `ai-agent/tools/call_actions.py:35-82`, `docs/adr/ADR-001-call-control-ami-over-ari.md`

### Em qual camada uma mudanca deve ser feita?

| Mudanca | Camada | Arquivo |
|---------|--------|---------|
| Quando transferir | AI Agent | `ai-agent/providers/llm.py` (system prompt) |
| Para qual ramal | AI Agent | `ai-agent/config.py` (`DEPARTMENT_MAP`) ou `.env` |
| Como o Asterisk executa transfer | Asterisk | `asterisk/config/extensions.conf` |
| Fallback se destino nao atende | Asterisk | `extensions.conf` contexto `[transfer-assistida]` |
| Latencia do media fork | Media Server | `media-server/config.py` (`MEDIA_FORK_CONFIG`) |
| Providers STT/LLM/TTS | AI Agent | `ai-agent/.env` |
| Comportamento de barge-in | Media Server | `media-server/config.py` (`CALL_CONFIG`) |

**Diagrama de autoridade:**

```
┌───────────────────────────────────────────────────────────────────┐
│ ASTERISK (Autoridade: Roteamento SIP)                             │
│ ├─ Registra ramal 2000 (Media Server)                             │
│ ├─ Recebe chamada → dialplan [interno] → Dial(PJSIP/2000)        │
│ └─ [transfer-assistida] → Dial/Redirect (executado por AMI)       │
├───────────────────────────────────────────────────────────────────┤
│ MEDIA SERVER (Autoridade: Orquestracao)                           │
│ ├─ Recebe chamada SIP via pjsua2                                  │
│ ├─ Extrai caller_channel do INVITE header                         │
│ ├─ Fork audio: RTP → Ring Buffer → Consumer → AI Agent            │
│ ├─ Reproduz resposta: AI Agent → Playback Port → RTP              │
│ └─ Executa AMI Redirect → Asterisk (com caller_channel guardado)  │
├───────────────────────────────────────────────────────────────────┤
│ AI AGENT (Autoridade: Conversacao)                                │
│ ├─ Recebe audio do Media Server (ASP audio frames)                │
│ ├─ Pipeline: STT(audio) → LLM(texto) → TTS(texto) → audio        │
│ ├─ LLM decide: transfer_call("suporte") ou end_call("motivo")    │
│ └─ Envia CallActionMessage via ASP ao Media Server                │
├───────────────────────────────────────────────────────────────────┤
│ AI TRANSCRIBE (Autoridade: Indexacao)                             │
│ ├─ Recebe audio do Media Server (ASP audio frames)                │
│ ├─ STT: transcreve com FasterWhisper                              │
│ └─ Indexa no Elasticsearch (time-series)                          │
└───────────────────────────────────────────────────────────────────┘
```

- [x] Referencia direta ao README e ADR
- [x] Diagrama/fluxo afetado
- [x] Justificativa tecnica

---

## 2. Controle de Chamada (Asterisk / AMI)

### Por que AMI foi escolhido em vez de ARI?

**Evidencia:** `docs/adr/ADR-001-call-control-ami-over-ari.md`

3 razoes tecnicas:

1. **Regressao de midia evitada** (ADR linhas 40-48): ARI exigiria Stasis, reescrevendo a camada de midia. O Media Fork Manager (ring buffer, isolamento de path critico) nao tem equivalente em ARI.

2. **Resiliencia** (ADR linhas 62-64): Se conexao AMI cai, chamadas ativas continuam normalmente. AMI e usado apenas no momento do transfer. Com ARI, desconexao deixaria canais orfaos em Stasis.

3. **Simplicidade** (ADR linhas 66-69): AMI estavel ha 20+ anos. Cleanup automatico via dialplan (sem bridges orfas). AI Agent chama `transfer_call()` sem saber que AMI existe.

### Quais comandos AMI sao permitidos em producao?

**Evidencia:** `media-server/ami/client.py`

| Comando | Linhas | Uso |
|---------|--------|-----|
| `Action: Login` | 111-144 | Autenticacao TCP |
| `Action: Redirect` | 146-208 | Transfer de canal para contexto/extensao |
| `Action: Logoff` | 210-230 | Graceful shutdown |

**Protocolo AMI:**

- TCP puro (porta 5038)
- Texto delimitado por `\r\n\r\n`
- Serializacao via lock (linha 257) para evitar interleaving

**Permissoes** (`asterisk/config/manager.conf:1-24`):

```ini
[media-server]
read = call,system
write = call,originate,system
deny = 0.0.0.0/0.0.0.0
permit = 172.16.0.0/255.240.0.0   # Rede Docker
permit = 10.0.0.0/255.0.0.0
permit = 192.168.0.0/255.255.0.0
```

**Permissoes especificas:**

- `call`: le canais SIP (estado, properties)
- `originate`: inicia chamadas (usado em fallback)
- `system`: comandos gerais do Asterisk

### Como o sistema evita acoes duplicadas (redirect, hangup)?

**Evidencia:** `media-server/sip/call.py:470-533`

5 mecanismos:

1. **Fila unica:** `self.pending_call_action: Optional[tuple] = None` — tupla imutavel, sobrescreve (nao acumula)
2. **Sincronizacao:** `playback_finished` Event + Lock no AMI client evitam interleaving
3. **Execucao pos-playback:** Transfer so executa APOS `_on_playback_complete()` (linha 445)
4. **Timeout:** 10s no AMI Redirect (linha 525) — nao bloqueia indefinidamente
5. **Limpeza atomica:** `pending_tool_calls = []` APOS despacho (`ai-agent/server/websocket.py:640`)

**Validacao antes de executar** (`call.py:491-512`):

- Valida target (padrao `[0-9*#]+`) — rejeita valores invalidos
- Verifica se `caller_channel` disponivel
- Verifica se `ami_client` disponivel
- Se falha, resume streaming (fallback)

**Protecao no dialplan** (`asterisk/config/extensions.conf:140-154`):

```ini
[transfer-assistida]
exten => _X.,1,NoOp(Transfer assistida para ${EXTEN})
 same => n,Answer()
 same => n,Playback(pls-wait-connect-call)
 same => n,Dial(PJSIP/${EXTEN},30,tTm(default))
 same => n,GotoIf($["${DIALSTATUS}" = "ANSWER"]?done:no-answer)
 same => n(no-answer),Dial(PJSIP/2000,60,tTb(add-caller-header^s^1))
```

- `DIALSTATUS` check evita fallback redundante
- Fallback automatico se destino nao atende
- Nova sessao marcada com `transfer_retry` (linha 152)

---

## 3. Estado da Chamada (Call State)

### Onde o estado da chamada vive?

**Dois donos, responsabilidades distintas:**

| Dono | Estado | Arquivo | Sincronizacao |
|------|--------|---------|---------------|
| **Media Server** | `caller_channel`, `pending_call_action`, `is_streaming`, `is_playing_response` | `media-server/sip/call.py:43-122` | `threading.Event`, Lock AMI |
| **AI Agent** | `SessionState` (`idle`, `listening`, `processing`, `responding`) | `ai-agent/server/session.py:20-46` | `asyncio.Lock` |

**Decisao explicita** (ADR-001 linhas 112-120):

- **NAO usar Redis** (overkill para lifetime = chamada)
- **NAO repassar caller_channel para AI Agent** (detalhe de Asterisk)
- Estado vive no Media Server por ser stateful naturalmente

### Estados explicitos

**AI Agent** (`ai-agent/server/session.py:20`):

```python
SessionState = Literal['listening', 'processing', 'responding', 'idle']
```

**Media Server** (`shared/asp_protocol/enums.py:42-45`):

```python
class CallActionType(str, Enum):
    TRANSFER = "transfer"
    HANGUP = "hangup"
```

**Diagrama de transicoes:**

```
idle → listening → processing → responding → listening → ...
                                                 ↓ (300s inatividade)
                                               cleanup
```

**Transicoes thread-safe** (`session.py:57-63`):

```python
async def set_state(self, new_state: SessionState):
    async with self._lock:
        old_state = self.state
        self.state = new_state
        self.update_activity()
        logger.debug(f"Estado: {old_state} -> {new_state}")
```

### Quem pode alterar cada estado?

| Componente | Altera | Quem dispara | Sincronizacao |
|-----------|--------|-------------|---------------|
| **Media Server (MyCall)** | `pending_call_action`, `is_streaming`, `is_playing_response` | Callbacks PJSIP (`onCallState`, `onCallMediaState`) | `threading.Event` |
| **AI Agent (Session)** | `state` (listening/processing/responding/idle) | WebSocket handlers (`_process_and_respond`, `_send_greeting`) | `asyncio.Lock` |
| **Asterisk (Dialplan)** | Contexto do canal via AMI Redirect | Media Server via AMI + decisao da IA | Asterisk nativo |

### Como evitar race conditions entre TTS, transfer e hangup?

**Evidencia:** `media-server/sip/call.py:361-488`

```
Timeline:
1. AI Agent fala via TTS → StreamingPlaybackPort
2. Durante playback: AI envia call.action (transfer)
3. pending_call_action armazenado (tupla imutavel)
4. Response completa → callback _on_playback_complete()
5. Se pending_call_action existe → executa transfer
6. Se nao → resume streaming
```

**Protecao chave:** Transfer NUNCA executa durante playback. Sempre espera o usuario ouvir a frase completa.

**Protecoes contra duplicacao:**

1. `playback_finished` Event (linha 92) sincroniza multiplos threads
2. `pending_call_action` armazenado ATOMICAMENTE (tupla imutavel)
3. Transfer executa APOS playback terminar (linha 445)
4. Timeout de 10s em AMI Redirect (linha 525)

### O que acontece se a chamada cair durante um tool call?

**Evidencia:** `media-server/sip/call.py:126-149`

```python
def onCallState(self, prm):
    ci = self.getInfo()
    if ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
        self._stop_conversation()   # Sinaliza stop
        self._cleanup()             # Encerra ports
        if self.conversation_thread:
            self.conversation_thread.join(timeout=2)
```

- `stop_conversation` Event pausa thread
- `_cleanup()` encerra streaming ports antes de retomar
- Fallback automatico no dialplan se drop durante transfer
- Sessao no AI Agent limpa por timeout (300s)

---

## 4. ASP Protocol

### Qual e o contrato minimo do ASP?

**Evidencia:** `docs/ASP_SPECIFICATION.md:609-635`, `shared/asp_protocol/messages.py`

**Campos obrigatorios em toda mensagem:**

- `type` (string): Identificador do tipo de mensagem
- `timestamp` (ISO 8601): Quando a mensagem foi criada
- `session_id` (UUID): Identificador unico da sessao (para mensagens de sessao)

**Negociacao obrigatoria antes do streaming:**

1. Servidor envia `protocol.capabilities` na conexao
2. Cliente envia `session.start` com configuracao desejada
3. Servidor responde `session.started` (aceita/rejeita)
4. Apenas apos aceitacao o streaming pode comecar

**Politica de compatibilidade** (ASP_SPECIFICATION linhas 623-628):

- Campos novos opcionais: NAO incrementam versao major
- Novos tipos de mensagem: Incrementam versao minor
- Mudanca de campos obrigatorios: Incrementam versao major
- Deprecation: Anunciado com 2 versoes minor de antecedencia

### Quais mensagens sao obrigatorias?

**Evidencia:** `shared/asp_protocol/messages.py`

| Mensagem | Direcao | Obrigatoria | Classe (linhas) |
|----------|---------|-------------|-----------------|
| `protocol.capabilities` | Server→Client | **SIM** | `ProtocolCapabilitiesMessage` (60-97) |
| `session.start` | Client→Server | **SIM** | `SessionStartMessage` (101-157) |
| `session.started` | Server→Client | **SIM** | `SessionStartedMessage` (161-224) |
| `session.update` | Client→Server | Nao | `SessionUpdateMessage` (228-266) |
| `session.updated` | Server→Client | Nao | `SessionUpdatedMessage` (270-323) |
| `session.end` | Client→Server | Nao | `SessionEndMessage` (327-361) |
| `session.ended` | Server→Client | Nao | `SessionEndedMessage` (365-407) |
| `protocol.error` | Server→Client | Nao | `ProtocolErrorMessage` (411-445) |

**Mensagens de controle (opcionais):**

| Mensagem | Direcao | Classe (linhas) |
|----------|---------|-----------------|
| `audio.speech_start` | Server→Client | `AudioSpeechStartMessage` (451-476) |
| `audio.speech_end` | Server→Client | `AudioSpeechEndMessage` (480-510) |
| `response.start` | Server→Client | `ResponseStartMessage` (514-542) |
| `response.end` | Server→Client | `ResponseEndMessage` (546-577) |
| `call.action` | Server→Client | `CallActionMessage` (581-625) |

### Como versionamos o protocolo?

**Evidencia:** `docs/ASP_SPECIFICATION.md:609-635`, `shared/asp_protocol/negotiation.py:72-103`

- **Semver:** `MAJOR.MINOR.PATCH` (atual: `1.0.0`)
- Versao major diferente → **REJEITA** com erro `1004` (version_mismatch)

**Negociacao implementada em** `ConfigNegotiator.negotiate()` (`shared/asp_protocol/negotiation.py`):

```python
def negotiate(self, requested_audio, requested_vad) -> NegotiationResult:
    # Se versao major diferente → REJEITA (1004)
    # Se config invalida → REJEITA com erros especificos
    # Se valida com ajustes → ACEITA com accepted_with_changes
    # Se valida sem ajustes → ACEITA com accepted
```

**Codigos de erro por categoria:**

| Categoria | Faixa | Exemplos |
|-----------|-------|----------|
| Protocol | 1xxx | 1001 (invalid_message_format), 1002 (handshake_timeout), 1004 (version_mismatch) |
| Audio | 2xxx | 2001 (unsupported_sample_rate), 2002 (unsupported_encoding) |
| VAD | 3xxx | 3001 (invalid_vad_parameter), 3002 (vad_not_configurable) |
| Session | 4xxx | 4001 (session_not_found), 4002 (session_expired) |

**Formato de mensagem** (ASP_SPECIFICATION linhas 181-225):

```json
{
  "type": "protocol.capabilities",
  "version": "1.0.0",
  "server_id": "ai-agent-01",
  "capabilities": { "..." },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

**Fluxo de handshake:**

```
Client                                Server
   |                                    |
   |-------- WebSocket Connect -------->|
   |<------ protocol.capabilities ------|
   |-------- session.start ------------>|
   |<------- session.started -----------|
   |======== audio streaming ===========>|
```

---

## 5. Tool Calling (IA)

### Quais tools o LLM pode chamar?

**Evidencia:** `ai-agent/tools/call_actions.py:35-83`

| Tool | Parametros | Efeito Colateral |
|------|-----------|------------------|
| `transfer_call` | `target` (obrigatorio), `reason` (opcional) | **SIM** — transfere chamada SIP via AMI |
| `end_call` | `reason` (opcional) | **SIM** — encerra chamada SIP via AMI |

**Departamentos** (configuravel via `DEPARTMENT_MAP`):

```python
{"suporte": "1001", "vendas": "1002", "financeiro": "1003"}
```

**Formato OpenAI-compatible** (compativel com llama.cpp, vLLM, Ollama):

```python
CALL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "transfer_call",
            "description": "...",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["target"]
            }
        }
    },
    # ... end_call ...
]
```

### Como prevenimos multiplas execucoes da mesma acao?

**Evidencia:** `ai-agent/providers/llm.py:49-88, 232-271`

3 camadas de protecao:

1. **IDs unicos:** Cada tool call tem `id` unico gerado pelo LLM
2. **Historico sintetico:** Apos tool call, adiciona resultado `"Action queued for execution."` ao historico — LLM ve que ja executou
3. **Limpeza atomica:** `pending_tool_calls = []` apos despacho (`websocket.py:640`)

**Implementacao por provider:**

Anthropic (`llm.py:232-271`):

```python
if self.pending_tool_calls:
    tool_results = [{
        "type": "tool_result",
        "tool_use_id": tc["id"],
        "content": "Action queued for execution.",
    } for tc in self.pending_tool_calls]
    self.conversation_history.append({"role": "user", "content": tool_results})
```

OpenAI/Local (`llm.py:151-181`):

```python
for tc in self.pending_tool_calls:
    self.conversation_history.append({
        "role": "tool",
        "tool_call_id": tc["id"],
        "content": "Action queued for execution.",
    })
```

**O sistema NAO e idempotente por design.** Cada acao e intencional. A prevencao e via historico, nao via deduplicacao.

### O que acontece se o LLM errar?

**Evidencia:** `ai-agent/providers/llm.py:313-315` (Anthropic), `427-429` (OpenAI), `611-613` (Local)

```python
except Exception as e:
    logger.error(f"Erro no LLM: {e}")
    return "Desculpe, tive um problema ao processar sua mensagem."
```

**Estrategia:**

- Log do erro (traceback completo)
- Retorna mensagem amigavel ao usuario
- Conversa continua (nao interrompe)
- Historico continua consistente

**Erros de parsing JSON** (`llm.py:56-59`):

```python
try:
    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
except json.JSONDecodeError:
    args = {}
    logger.warning(f"Falha ao parsear tool call arguments: {tc.function.arguments}")
```

**Fallback final** (`pipeline/conversation.py:444-455`):

```python
if not self.llm:
    return f"Voce disse: {text}"  # Eco se LLM indisponivel
```

### Checklist de resposta

- [x] Tool tem efeito colateral? **SIM** — transferencia/encerramento real via AMI
- [x] Existe idempotencia? **NAO** — por design, cada acao e intencional. Prevencao via historico
- [x] Existe fallback seguro? **SIM** — mensagem de erro padrao + conversa continua

### Fluxo completo: ASP + Tool Calling

```
[Media Server]                   [AI Agent]                    [Media Server]
     |                               |                              |
     |=== Audio Streaming ==========>| STT → LLM → TTS             |
     |                               |                              |
     |                               |--- Audio Input ----> STT     |
     |                               |<-- Texto -------- STT        |
     |                               |--- Texto -------> LLM        |
     |                               |  Detecta: transfer_call()    |
     |                               |<-- Tool Call ---- LLM        |
     |                               |                              |
     |                               |--- call.action ------------>|
     |                               |  (action: transfer, target: 1001)
     |                               |                    |
     |<==== Audio Streaming =========|<--- Audio TTS ---  |
     |                               |                    |
     |                               |              Aguarda playback
     |                               |              AMI Redirect
     |                               |              Call Transferred
```

---

## 6. Pipeline de Audio (STT / TTS)

### O que define inicio e fim de fala?

**Evidencia:** `media-server/sip/streaming_port.py:53-182`, `ai-agent/pipeline/vad.py:23-231`

**Dois niveis de VAD:**

| Nivel | Local | Implementacao | Arquivo |
|-------|-------|---------------|---------|
| 1 | Media Server | WebRTC VAD (Silero) + fallback RMS | `streaming_port.py:53-182` |
| 2 | AI Agent | AudioBuffer com acumulacao | `pipeline/vad.py:23-231` |

**Inicio de fala:** VAD detecta energy acima do threshold por `min_speech_ms` (250ms)

**Fim de fala:** Silencio continuo >= `silence_threshold_ms` (500ms) + fala >= 250ms

```python
# streaming_port.py:354
speech_started, speech_ended = self.vad.process_frame(audio_data)

# vad.py:122-126
if silence_ms >= self.silence_threshold:
    if speech_ms >= self.min_speech_ms:
        audio = bytes(self.buffer)
        self._reset()
        return audio  # Retorna audio completo
```

**Configuracao** (`ai-agent/config.py:51-88`):

```python
AUDIO_CONFIG = {
    "sample_rate": 8000,              # 8kHz para telefonia
    "channels": 1,                    # Mono
    "sample_width": 2,                # 16-bit
    "frame_duration_ms": 20,          # 20ms frames
    "vad_aggressiveness": 2,          # 0-3 (balanced)
    "silence_threshold_ms": 500,      # 500ms silencio = fim
    "min_speech_ms": 250,             # Minimo 250ms para ser valido
    "energy_threshold": 500,          # Fallback RMS threshold
    "vad_ring_buffer_size": 5,        # Suavizacao (5 frames = 100ms)
    "vad_speech_ratio_threshold": 0.4, # 40% dos frames = fala
    "max_buffer_seconds": 60,         # Maximo 60s no buffer
    "chunk_size_bytes": 2000,         # ~125ms por chunk
}
```

**Tuning de VAD:**

| Aggressiveness | Comportamento |
|---------------|--------------|
| 0 | Muito sensivel — detecta fala facil, captura ruido |
| 2 | Balanced (padrao recomendado) |
| 3 | Conservador — precisa fala clara, pode perder fala fraca |

**Fluxo de deteccao:**

```
[RTP Frames 20ms] → [StreamingAudioPort.onFrameReceived]
                          ↓
                    [StreamingVAD.process_frame]
                          ├─ speech_started → on_speech_start callback
                          └─ speech_ended   → send_audio_end() → audio.end
                          ↓
                    [Media Fork / Direct Send] → AI Agent
                          ↓
                    [AI Agent: AudioBuffer.add_audio_raw]
                          ├─ Acumula ate silencio
                          └─ Retorna audio quando: silence >= 500ms + speech >= 250ms
                          ↓
                    [STT: transcribe(audio_data)]
```

**Nota importante:** STT no AI Agent tem `vad_filter=False` (`stt.py:353`) porque o Media Server ja fez VAD.

### Quando o TTS e considerado concluido?

**Evidencia:** `ai-agent/providers/tts.py:364-416` (Kokoro), `ai-agent/pipeline/sentence_pipeline.py:46-244`

**TTS e completo quando:**

1. Toda sintese executou (output gerado)
2. Audio resampled para 8kHz (Kokoro nativo = 24kHz)
3. Convertido para PCM 16-bit mono
4. Bytes retornados

**Kokoro TTS** (`tts.py:364-416`):

```python
async def synthesize(self, text: str) -> bytes:
    # 1. Preprocessa texto
    # 2. Executa sintese em thread pool
    audio_chunks = []
    for _, _, audio_chunk in self._pipeline(...):
        audio_chunks.append(audio_chunk)
    # 3. Concatena chunks
    audio = np.concatenate(audio_chunks)
    # 4. Resample 24kHz → 8kHz
    audio_8k = self._resample(audio, 24000, 8000)
    # 5. Converte para PCM 16-bit
    audio_int16 = (audio_8k * 32767).astype(np.int16)
    return audio_int16.tobytes()
```

**Pipeline sentence-level** (`sentence_pipeline.py:160`):

```python
async for sentence in llm.generate_sentences(user_text):
    async for audio_chunk in tts.synthesize_stream(sentence):
        yield sentence, audio_chunk  # Streaming real
```

Pipeline completo termina quando: LLM finaliza + ultima frase sintetizada + ultimo chunk enviado.

### Como o barge-in e tratado?

**Evidencia:** `media-server/sip/call.py:107-110, 237-245`, `media-server/sip/streaming_port.py:234-362`

**Mecanismo de 3 camadas:**

1. **Monitor Mode** (`streaming_port.py:234`): Durante playback, VAD detecta fala mas NAO envia audio

2. **Callback** (`call.py:237-245`): `on_speech_start` → `barge_in_triggered.set()`

3. **State Machine** (`websocket.py:384-389`): AI Agent ignora frames quando `state != 'listening'`

```python
# streaming_port.py modos de operacao:
# is_active=False:    Ignora completamente
# monitor_mode=True:  Detecta fala (para barge-in) mas nao envia audio
# Normal:             Detecta fala E envia audio

# websocket.py:384-389
if session.state != 'listening':
    session._ignored_frames += 1
    return  # Descarta frames durante 'responding'
```

**Configuracao** (`media-server/config.py:150-151`):

```python
CALL_CONFIG = {
    "barge_in_enabled": parse_bool(os.getenv("BARGE_IN_ENABLED", "true"), True),
}
```

**Estado atual:** Barge-in detecta inicio de fala e sinaliza, mas o playback de TTS continua ate terminar. O AI Agent ignora frames recebidos durante `responding`.

### Latencia tipica (TTFB)

**Evidencia:** `ai-agent/server/websocket.py:645-652`

```python
# Registra quando audio.end foi recebido
session.audio_end_timestamp = time.perf_counter()

# Ao enviar primeiro audio da resposta
if session.audio_end_timestamp > 0 and not session.ttfb_recorded:
    ttfb = time.perf_counter() - session.audio_end_timestamp
    VOICE_TTFB_SECONDS.observe(ttfb)
    session.ttfb_recorded = True
```

**Breakdown tipico:**

```
Total TTFB: ~500-1000ms
├─ STT: 50-200ms (faster-whisper tiny)
├─ LLM: 100-300ms (Claude API ou local)
├─ TTS: 50-200ms (Kokoro local)
└─ Overhead: 50-100ms
```

---

## 7. Observabilidade e Debug

### Como reproduzir um problema de chamada?

```bash
# 1. Status dos containers
./status.sh

# 2. Logs em tempo real (paralelo)
./logs.sh ai-agent        # Pipeline STT→LLM→TTS
./logs.sh media-server     # SIP/RTP bridge + AMI
./logs.sh asterisk         # Sinalizacao SIP

# 3. CLI Asterisk para debug SIP
docker exec -it asterisk-pabx asterisk -rvvv
> pjsip set logger on     # Ver INVITE/200OK/BYE
> core show channels       # Chamadas ativas
> pjsip show endpoints     # Ramais registrados
```

### Onde encontrar logs de uma call especifica?

| Componente | Identificador | Exemplo |
|-----------|---------------|---------|
| AI Agent | `[session_id[:8]]` | `[a1f2e3b9] Estado: listening → processing` |
| Media Server | `[unique_call_id]` | `[f7c3a2b1] Chamada conectada` |
| Asterisk | SIP Call-ID | `docker logs asterisk-pabx \| grep Call-ID` |
| Elasticsearch | `session_id` field | `voice-transcriptions-YYYY.MM.DD` |

**Exemplo de rastreamento end-to-end:**

```
1. Media Server (call.py:134)
   [f7c3a2b1] Estado: PJSIP_INV_STATE_CONFIRMED
   [f7c3a2b1] session_id: a1f2e3b9-...

2. AI Agent (websocket.py:309)
   [a1f2e3b9] Iniciando sessao
   [a1f2e3b9] VAD config aplicada: silence=500ms, min_speech=250ms

3. AI Agent (websocket.py:400)
   [a1f2e3b9] Recebido audio.end
   [a1f2e3b9] TTFB: 320ms
```

### Como correlacionar audio, texto e decisao?

**Fluxo rastreavel com metricas:**

```
1. CAPTURA     → media_server_vad_utterance_duration_ms
2. TRANSCRICAO → ai_agent_stt_latency_seconds
3. DECISAO     → ai_agent_llm_latency_seconds + ai_agent_llm_first_token_latency_seconds
4. SINTESE     → ai_agent_tts_latency_seconds + ai_agent_tts_first_byte_latency_seconds
5. ENTREGA     → ai_agent_voice_ttfb_seconds (CRITICA: audio.end → primeiro chunk)
6. E2E         → media_server_e2e_latency_seconds
```

**Kibana** (`http://localhost:5601`):

```json
POST /voice-transcriptions-*/_search
{
  "query": {
    "bool": {
      "must": [
        { "match": { "session_id": "a1f2e3b9" } },
        { "range": { "@timestamp": { "gte": "2026-02-06T10:30:00Z" } } }
      ]
    }
  }
}
```

### Metricas Prometheus expostas

**AI Agent (porta 9090):**

```
# SESSAO
ai_agent_sessions_created_total               (counter)
ai_agent_sessions_ended_total{reason}         (counter)
ai_agent_active_sessions                      (gauge)
ai_agent_session_duration_seconds             (histogram)

# PIPELINE
ai_agent_pipeline_latency_seconds             (histogram)
ai_agent_stt_latency_seconds                  (histogram)
ai_agent_llm_latency_seconds                  (histogram)
ai_agent_tts_latency_seconds                  (histogram)

# STREAMING
ai_agent_llm_first_token_latency_seconds      (histogram)
ai_agent_tts_first_byte_latency_seconds       (histogram)
ai_agent_voice_ttfb_seconds                   (histogram) ← CRITICA
ai_agent_pipeline_errors_total{component}     (counter)

# WEBSOCKET
ai_agent_websocket_connections_active         (gauge)

# ASP
ai_agent_asp_handshake_duration_seconds       (histogram)
ai_agent_asp_handshake_success_total{status}  (counter)
ai_agent_asp_handshake_failure_total{error}   (counter)
```

**Media Server (porta 9091):**

```
# SIP/RTP
media_server_sip_registration_status          (enum)
media_server_calls_active                     (gauge)
media_server_call_duration_seconds            (histogram)
media_server_rtp_jitter_ms{direction}         (histogram)
media_server_rtp_packet_loss_ratio{direction} (gauge)

# VAD
media_server_vad_utterance_duration_ms        (histogram)
media_server_vad_events_total{event_type}     (counter)

# E2E
media_server_e2e_latency_seconds              (histogram) ← CRITICA
media_server_barge_in_total                   (counter)

# MEDIA FORK
media_server_fork_buffer_fill_ratio           (gauge)
media_server_fork_frames_dropped_total        (counter)
media_server_fork_consumer_lag_ms             (histogram)
media_server_fork_ai_agent_available          (gauge)
media_server_fork_fallback_active             (gauge) ← INDICADOR DE FALHA
```

**Queries Prometheus uteis:**

```promql
# TTFB P95
histogram_quantile(0.95, rate(ai_agent_voice_ttfb_seconds_bucket[5m]))

# Taxa de erro
rate(ai_agent_pipeline_errors_total[5m]) / (rate(ai_agent_sessions_created_total[5m]) + 0.001)

# Perda de pacotes RTP
media_server_rtp_packet_loss_ratio{direction="inbound"}

# Fallback mode ativo (problema com AI Agent)
media_server_fork_fallback_active == 1
```

**Evidencia:** `observability/prometheus/rules/voice-pipeline.yml:1-131`

### Indices Elasticsearch

- **Indice:** `voice-transcriptions-YYYY.MM.DD` (rotacao diaria)
- **Campos:** `session_id`, `call_id`, `text`, `duration_ms`, `confidence`, `timestamp`
- **Dashboards Kibana:** `observability/kibana/` (importados automaticamente via `setup.sh`)
- **Acesso:** `http://localhost:5601` (sem autenticacao)
- **Config:** `ai-transcribe/.env.example:14-18`

---

## 8. Seguranca

### Quais superficies estao expostas?

| Porta | Servico | Protocolo | Autenticacao | Risco |
|-------|---------|-----------|-------------|-------|
| 5160 | Asterisk SIP | UDP | SIP auth (senha) | Medio |
| 8188 | Asterisk HTTP/WS | TCP | **Nenhuma** | **CRITICO** (dev only) |
| 8189 | Asterisk WSS | TCP | TLS + SIP auth | Baixo (cert auto-assinado) |
| 3478/5349 | TURN/STUN | UDP/TCP | Nenhuma | Baixo (publico por design) |
| 20000-20100 | RTP Asterisk | UDP | Nenhuma | Baixo (dados de audio) |
| 40000-40100 | RTP Media Server | UDP | Nenhuma | Baixo |
| 8765 | AI Agent WS | TCP | ASP protocol apenas | Medio (rede Docker privada) |
| 8766 | AI Transcribe WS | TCP | ASP protocol apenas | Medio (rede Docker privada) |
| 9200 | Elasticsearch | TCP | **Nenhuma** | **ALTO** (rede privada) |
| 5601 | Kibana | TCP | Nenhuma | Medio (rede privada) |
| 3000 | Grafana | TCP | admin/admin | Medio |

**Evidencia:** `docker-compose.yml:20-67`

**Rede:** Todos os servicos em bridge `voip-network`. Comunicacao intra-container sem TLS.

### Como o AMI esta protegido?

**Evidencia:** `asterisk/config/manager.conf:1-24`

**Protecoes atuais:**

```ini
[general]
enabled = yes
port = 5038
bindaddr = 0.0.0.0           # Escuta em todas as interfaces

[media-server]
secret = Th30V01c3AMI!2026   # Senha hardcoded
read = call,system
write = call,originate,system
deny = 0.0.0.0/0.0.0.0       # Default: nega tudo
permit = 172.16.0.0/255.240.0.0  # Redes Docker
permit = 10.0.0.0/255.0.0.0
permit = 192.168.0.0/255.255.0.0
```

**Riscos identificados:**

| Risco | Severidade | Descricao |
|-------|-----------|-----------|
| Credencial hardcoded | **CRITICA** | `secret = Th30V01c3AMI!2026` em repositorio git |
| `bindaddr = 0.0.0.0` | ALTA | Permite conexoes de qualquer IP |
| Sem TLS | ALTA | Credenciais trafegam desencriptadas |
| Sem rate limiting | MEDIA | Sem protecao contra brute-force |

**Mitigacao recomendada:**

```ini
[general]
bindaddr = 127.0.0.1        # Apenas localhost
webenabled = no

[media-server]
secret = ${AMI_SECRET_ENV}   # Carregar de variavel de ambiente
read = call
write = call                 # Apenas Redirect necessario
permit = 172.17.0.0/16       # Apenas Docker internal subnet
```

### Como evitar uso indevido das tools?

**Evidencia:** `ai-agent/tools/call_actions.py`, `ai-agent/config.py:274-285`

| Protecao | Implementacao | Arquivo |
|----------|--------------|---------|
| Whitelist de targets | `resolve_target()` valida contra `DEPARTMENT_MAP` | `call_actions.py` |
| Token limit | `LLM_MAX_TOKENS=256` (limite duro) | `config.py:159` |
| Timeout LLM | `LLM_TIMEOUT=15s` | `config.py:176` |
| Escalacao automatica | `MAX_UNRESOLVED_INTERACTIONS=3` | `config.py:274` |
| System prompt fixo | Nao dinamico (reduz risco de injection) | `config.py:176` |

---

## 9. Falhas e Fallbacks

### O que acontece se o destino nao atender?

**Evidencia:** `asterisk/config/extensions.conf:133-154`

```
Dial(PJSIP/${EXTEN}, 30s) → NOANSWER/BUSY/UNAVAILABLE
  ↓
Playback("an error occurred")
  ↓
Dial(PJSIP/2000, 60s) com header X-Transfer-Retry=true
  ↓
AI Agent recebe sessao com metadata.transfer_retry=true
  ↓
PULA saudacao, vai direto para state='listening'
```

**Evidencia de pular saudacao** (`ai-agent/server/websocket.py:243-249`):

```python
is_retry = msg.metadata and msg.metadata.get("transfer_retry")
if is_retry:
    logger.info(f"[{msg.session_id[:8]}] Transfer retry - pulando saudacao")
    await session.set_state('listening')
else:
    await self._send_greeting(websocket, session)
```

**DIALSTATUS possiveis:**

| Status | Acao |
|--------|------|
| ANSWER | Continua conversa com atendente |
| NOANSWER | Volta para AI Agent (timeout 30s) |
| BUSY | Volta para AI Agent |
| UNAVAILABLE | Volta para AI Agent |
| CHANUNAVAIL | Volta para AI Agent |

**Nenhum silencio infinito:** Caller volta para IA em ~35s (30s timeout + 5s mensagem).

### O que acontece se o AI Agent cair?

**Evidencia:** `media-server/config.py:28-43, 352-360`, `docker-compose.yml:107-112`

```
T=0s:   AI Agent cai → WebSocket fecha
T=5s:   Media Server tenta reconectar (tentativa 1 de 10)
T=10s:  Tentativa 2
...
T=55s:  Tentativa 10 (ULTIMA)
T=60s:  fork_ai_agent_available = 0
        Fallback mode ativo (mensagem pre-gravada)
```

**Configuracao de reconexao** (`media-server/config.py:28-43`):

```python
AI_AGENT_CONFIG = {
    "url": "ws://ai-agent:8765",
    "reconnect_interval": 5,          # 5s entre tentativas
    "max_reconnect_attempts": 10,     # Maximo 10 tentativas
    "ping_interval": 30,              # Ping keepalive 30s
    "ping_timeout": 10,               # Timeout ping 10s
}
```

**Fallback mode** (`media-server/config.py:352-360`):

```python
MEDIA_FORK_CONFIG = {
    "fallback_enabled": True,
    "fallback_message": "Aguarde um momento, estamos conectando voce.",
}
```

**Health check** (`docker-compose.yml:107-112`):

```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -f http://localhost:9090/metrics || exit 1"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

**Restart policy:** `restart: unless-stopped` — Docker reinicia automaticamente.

### O que acontece se o Media Server cair?

**Evidencia:** `docker-compose.yml:114-154`, `ai-agent/server/session.py:158-185`

- Docker reinicia automaticamente (`restart: unless-stopped`)
- Dependencias garantem que AI Agent ja esta rodando
- Sessao no AI Agent limpa por timeout (300s via `cleanup_stale_sessions`)
- Asterisk encerra chamada apos INVITE timeout SIP (~30s)
- **Nenhum silencio infinito:** Caller ouve silencio max ~30s ate Asterisk encerrar

**Cleanup de sessoes** (`session.py:158-185`):

```python
async def cleanup_stale_sessions(self, max_idle_seconds=300):
    now = datetime.now(timezone.utc)
    for session_id, session in self.sessions.items():
        idle_time = (now - session.last_activity).total_seconds()
        if idle_time > max_idle_seconds:
            stale.append(session_id)
```

### Prevencao de silencio infinito

4 mecanismos:

1. **Greeting timeout** (`media-server/config.py:153`): Se AI nao responde em 30s, Media Server continua mesmo assim
2. **Escalacao automatica** (`ai-agent/server/websocket.py:555-587`): Apos 3 interacoes sem tool call → transfere para humano
3. **Session timeout** (`ai-agent/config.py:261-267`): 300s inatividade → cleanup
4. **Barge-in** (`media-server/config.py:151`): Usuario pode falar a qualquer momento

**Escalacao automatica** (`ai-agent/config.py:274-285`):

```python
ESCALATION_CONFIG = {
    "max_unresolved_interactions": 3,
    "default_transfer_target": "1001",
    "transfer_message": "Estou te transferindo para outro atendente...",
}
```

```
Interacao 1: Usuario fala → AI responde → Nenhuma tool call
Interacao 2: Usuario fala → AI responde → Nenhuma tool call
Interacao 3: Usuario fala → AI responde → Nenhuma tool call
             ↓
             ESCALACAO AUTOMATICA
             ↓
             "Estou te transferindo para outro atendente..."
             ↓
             TRANSFER para operador (ramal 1001)
```

### Prevencao de loops

4 mecanismos:

1. **Escalacao automatica:** Apos 3 interacoes sem tool call → transfere para humano
2. **Session timeout:** 300s inatividade → cleanup
3. **Token limit:** `max_tokens=256` → LLM nao gera resposta infinita
4. **LLM timeout:** 15s → interrompe se travar

### Tabela de timeouts criticos

| Componente | Timeout | Impacto | Arquivo |
|-----------|---------|--------|---------|
| Greeting | 30s | Se AI nao responde rapido | `media-server/config.py:153` |
| Session Start | 60s | Se AI Agent lento para conectar | `media-server/config.py:155` |
| LLM Response | 15s | Limite de latencia LLM | `ai-agent/config.py:176` |
| Playback Drain | 10s | Limite para esvaziar playback | `media-server/config.py:157` |
| Session Idle | 300s | Limpeza de sessao obsoleta | `ai-agent/config.py:262` |
| Reconexao WS | 5s x 10 | 50s total para desistir | `media-server/config.py:35` |
| Transfer Dial | 30s | Timeout para atender | `asterisk/extensions.conf:145` |
| AMI Redirect | 10s | Timeout para executar AMI | `media-server/sip/call.py:525` |

---

## 10. Decisoes Pendentes

| Pergunta | Impacto | Status |
|----------|---------|--------|
| Mover `AMI_SECRET` para Docker secret/env var? | Seguranca — credencial hardcoded em repo | **PENDENTE** |
| Adicionar TLS ao AMI? | Seguranca — credenciais em plain text | **PENDENTE** |
| Adicionar autenticacao WebSocket (JWT)? | Seguranca — qualquer container conecta | **PENDENTE** |
| Habilitar `xpack.security` no Elasticsearch? | Seguranca — dados de transcricao expostos | **PENDENTE** |
| Barge-in interromper playback efetivamente? | UX — atualmente monitora fala mas playback continua | **PARCIAL** |
| Tracing distribuido (OpenTelemetry)? | Observabilidade — correlacao cross-service | **NAO INICIADO** |
| Circuit breaker para AI Agent? | Resiliencia — fallback mode pode ficar indefinido | **NAO INICIADO** |
| Contexto preservado apos transfer retry? | UX — sessao nova = historico perdido | **NAO IMPLEMENTADO** |
| Porta 8188 (HTTP/WS plain) em producao? | Seguranca — sem autenticacao, sem criptografia | **PENDENTE** |
| Alertas Prometheus (latencia, error rate)? | Operacao — sem alertas automaticos | **NAO INICIADO** |

---

## Definicao de Pronto (DoD)

Cada resposta neste documento atende aos criterios:

- [x] Referencia tecnica clara (arquivo:linha)
- [x] Decisao explicita ou justificativa de nao-decisao
- [x] Impacto mapeado no sistema

Perguntas sem resolucao estao na secao 10 como decisoes pendentes.

---

> **Regra de Ouro:** Se nao conseguimos explicar a resposta aqui, nao entendemos o sistema o suficiente para operar em producao.
