# Audio Session Protocol (ASP) - Plano de Implementação

## Contexto e Motivação

### Problema Identificado

Durante auditoria técnica do sistema de voz, identificamos uma **falha arquitetural grave**: o Media Server e o AI Agent possuem configurações de áudio e VAD **hardcoded e inconsistentes**, causando:

1. **Fala não detectada** - thresholds diferentes entre módulos
2. **Interrupções prematuras** - silence_threshold muito baixo
3. **Rejeição de falas curtas** - min_speech_ms inconsistente
4. **Impossibilidade de debug** - sem log de configuração negociada

### Evidências do Problema

| Parâmetro | Media-Server | AI-Agent | Impacto |
|-----------|-------------|----------|---------|
| `silence_threshold_ms` | 300ms | 300ms | Interrompia pausas naturais |
| `min_speech_ms` | 200ms | 300ms | AI-Agent rejeitava falas curtas |
| `ring_buffer` | 3 frames | 5 frames | Tempos de resposta diferentes |
| `speech_ratio` | > 0.4 | > 0.5 | AI-Agent mais restritivo |

---

## Pesquisa de Mercado: Como Outros Resolvem

### 1. OpenAI Realtime API

**Fonte:** https://platform.openai.com/docs/api-reference/realtime

**Abordagem:** Mensagens JSON sobre WebSocket com capability exchange.

```json
// Servidor envia após conexão
{
  "type": "session.created",
  "session": {
    "id": "sess_001",
    "model": "gpt-4o-realtime-preview",
    "audio": {
      "input": { "type": "audio/pcm", "rate": 24000 },
      "output": { "type": "audio/pcm", "rate": 24000 }
    },
    "turn_detection": {
      "type": "server_vad",
      "threshold": 0.5,
      "prefix_padding_ms": 300,
      "silence_duration_ms": 500,
      "create_response": true
    }
  }
}

// Cliente pode atualizar configuração
{
  "type": "session.update",
  "session": {
    "turn_detection": {
      "type": "semantic_vad",
      "eagerness": "medium"
    }
  }
}
```

**Parâmetros VAD suportados:**
- `threshold` (0.0-1.0): Sensibilidade de detecção
- `prefix_padding_ms`: Áudio incluído antes da fala detectada
- `silence_duration_ms`: Silêncio para considerar fim de turno
- `type`: `server_vad` ou `semantic_vad`

**Fonte VAD:** https://platform.openai.com/docs/guides/realtime-vad

---

### 2. Twilio Media Streams

**Fonte:** https://www.twilio.com/docs/voice/media-streams/websocket-messages

**Abordagem:** Sequência de mensagens `connected` → `start` → `media`.

```json
// 1. Mensagem de conexão estabelecida
{
  "event": "connected",
  "protocol": "Call",
  "version": "1.0.0"
}

// 2. Mensagem de início com metadata
{
  "event": "start",
  "sequenceNumber": "1",
  "streamSid": "MZ18ad3ab5a1...",
  "start": {
    "accountSid": "AC...",
    "callSid": "CA...",
    "tracks": ["inbound"],
    "mediaFormat": {
      "encoding": "audio/x-mulaw",
      "sampleRate": 8000,
      "channels": 1
    },
    "customParameters": {
      "FirstName": "Jane",
      "LastName": "Doe"
    }
  }
}

// 3. Mensagens de mídia
{
  "event": "media",
  "sequenceNumber": "3",
  "media": {
    "track": "inbound",
    "chunk": "1",
    "timestamp": "5",
    "payload": "no+JhoaJ..."  // Base64
  }
}
```

**Características:**
- Protocolo versionado (`version: "1.0.0"`)
- Metadata de sessão no `start`
- Formato de áudio explícito
- Parâmetros customizáveis

---

### 3. LiveKit Agents

**Fonte:** https://docs.livekit.io/agents/logic/sessions/

**Abordagem:** Configuração programática via objetos.

```python
from livekit.agents import AgentSession
from livekit.plugins import silero

session = AgentSession(
    vad=silero.VAD.load(
        min_silence_duration=0.5,    # 500ms
        min_speech_duration=0.25,    # 250ms
        activation_threshold=0.5,
        sample_rate=16000
    ),
    stt=deepgram.STT(),
    llm=openai.LLM(),
    tts=cartesia.TTS()
)

# Configuração de áudio
room_options = room_io.RoomOptions(
    audio_input=room_io.AudioInputOptions(
        noise_cancellation=noise_cancellation.BVC(),
    ),
    audio_output=room_io.AudioOutputOptions(
        sample_rate=24000,
    ),
)
```

**VAD Models suportados:**
- Silero VAD (CPU-efficient, 8kHz/16kHz)
- WebRTC VAD (lightweight)

**Fonte VAD:** https://docs.livekit.io/agents/v0/integrations/openai/customize/vad

---

### 4. Agora Conversational AI

**Fonte:** https://medium.com/agora-io/a-playground-for-testing-voice-ai-agents-dc62c142047b

**Parâmetros VAD:**

```json
{
  "vad": {
    "interrupt_duration_ms": 160,   // 160-500ms
    "silence_duration_ms": 640,      // 400-800ms
    "threshold": 0.5                 // 0.3-0.7
  }
}
```

**Recomendações:**
- `interrupt_duration_ms`: 160ms (ambiente limpo) → 500ms (ruidoso)
- `silence_duration_ms`: 400ms (Q&A rápido) → 800ms (conversas reflexivas)
- `threshold`: 0.3 (voz baixa) → 0.7 (evitar falsos positivos)

---

### 5. SDP (Session Description Protocol)

**Fonte:** https://www.rfc-editor.org/rfc/rfc8124.html

**Abordagem:** Modelo Offer/Answer para negociação.

```
v=0
o=- 20518 0 IN IP4 192.0.2.1
s=Example
c=IN IP4 192.0.2.1
t=0 0
m=audio 9 UDP/TLS/RTP/SAVPF 96 0 8
a=rtpmap:96 opus/48000/2
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=setup:actpass
a=websocket-uri:wss://server.example.com/ws
```

**Características:**
- Padrão IETF (RFC 4566, RFC 8124)
- Negociação de codecs
- Modelo Offer/Answer

---

### 6. Pipecat Framework

**Fonte:** https://docs.pipecat.ai/guides/telephony/twilio-websockets

**Valores Default VAD:**

```python
VAD_STOP_SECS = 0.8      # 800ms de silêncio para parar
VAD_START_SECS = 0.2     # 200ms de fala para iniciar
VAD_CONFIDENCE = 0.7     # Confiança mínima
VAD_MIN_VOLUME = 0.6     # Volume mínimo
```

---

## Tabela Comparativa

| Plataforma | Protocolo | VAD Config | Negociação | Versioning |
|------------|-----------|------------|------------|------------|
| OpenAI Realtime | WebSocket JSON | `session.created/update` | Sim | Não explícito |
| Twilio Streams | WebSocket JSON | `start.mediaFormat` | Não | `version: "1.0.0"` |
| LiveKit | Objetos Python/TS | Construtor | Não | Semver |
| Agora | Config JSON | Objeto `vad` | Não | Não |
| SDP | Texto SDP | Offer/Answer | Sim | RFC version |

---

## Solução Proposta: Audio Session Protocol (ASP)

### Princípios de Design

1. **Inspirado em OpenAI** - Mensagens `session.*` para lifecycle
2. **Inspirado em Twilio** - Versionamento de protocolo
3. **Inspirado em SDP** - Modelo Offer/Answer
4. **KISS** - Simples de implementar e debugar
5. **Extensível** - Novos parâmetros sem quebrar compatibilidade

### Diagrama de Sequência

```
┌──────────────────┐                         ┌──────────────────┐
│   Media Server   │                         │    AI Agent      │
│   (Client)       │                         │    (Server)      │
└────────┬─────────┘                         └────────┬─────────┘
         │                                            │
         │ ═══ WebSocket Connect ═══════════════════▶ │
         │                                            │
         │ ◀─── protocol.capabilities ─────────────── │
         │      {                                     │
         │        "type": "protocol.capabilities",   │
         │        "version": "1.0.0",                │
         │        "audio": {...},                    │
         │        "vad": {...}                       │
         │      }                                     │
         │                                            │
         │ ──── session.start ───────────────────────▶│
         │      {                                     │
         │        "type": "session.start",           │
         │        "session_id": "uuid",              │
         │        "audio": {...},                    │
         │        "vad": {...}                       │
         │      }                                     │
         │                                            │
         │ ◀─── session.started ───────────────────── │
         │      {                                     │
         │        "type": "session.started",         │
         │        "session_id": "uuid",              │
         │        "negotiated": {...}                │
         │      }                                     │
         │                                            │
         │ ═══ audio.data (binary frames) ══════════▶ │
         │ ◀══ audio.data (binary frames) ═══════════ │
         │                                            │
         │ ──── audio.end ───────────────────────────▶│
         │                                            │
         │ ◀─── response.start ──────────────────────│
         │ ◀══ audio.data (response) ════════════════ │
         │ ◀─── response.end ────────────────────────│
         │                                            │
         │ ──── session.end ─────────────────────────▶│
         │ ◀─── session.ended ───────────────────────│
         │                                            │
```

---

## Epics, Sprints, Microtasks e DoD

---

# EPIC 1: Definição do Protocolo ASP

**Objetivo:** Especificar formalmente o Audio Session Protocol.

**Duração estimada:** 1 Sprint (1 semana)

---

## Sprint 1.1: Especificação do Protocolo

### Microtask 1.1.1: Criar documento de especificação do protocolo

**Descrição:** Documentar formalmente todas as mensagens, campos e comportamentos do ASP.

**Entregáveis:**
- [ ] Documento `docs/ASP_SPECIFICATION.md`
- [ ] Diagrama de estados da sessão
- [ ] Exemplos de todas as mensagens

**DoD (Definition of Done):**
- [ ] Todas as mensagens documentadas com campos obrigatórios/opcionais
- [ ] Tipos de dados definidos (string, int, float, enum)
- [ ] Valores default especificados
- [ ] Exemplos JSON para cada mensagem
- [ ] Revisado por pelo menos 1 pessoa

---

### Microtask 1.1.2: Definir schema JSON das mensagens

**Descrição:** Criar JSON Schema para validação das mensagens.

**Entregáveis:**
- [ ] `schemas/asp_protocol.schema.json`
- [ ] Schemas individuais por tipo de mensagem

**DoD:**
- [ ] JSON Schema válido (draft-07 ou superior)
- [ ] Todos os campos com `type`, `description`, `required`
- [ ] Enums para valores fixos (ex: `encoding`)
- [ ] Testes de validação passando

---

### Microtask 1.1.3: Definir mensagens de erro

**Descrição:** Especificar mensagens de erro e códigos.

**Entregáveis:**
- [ ] Tabela de códigos de erro
- [ ] Formato da mensagem `protocol.error`

**DoD:**
- [ ] Códigos de erro categorizados (1xxx=protocol, 2xxx=audio, 3xxx=vad)
- [ ] Mensagens human-readable
- [ ] Ações de recovery documentadas

---

### Microtask 1.1.4: Definir versionamento do protocolo

**Descrição:** Estabelecer política de versionamento semântico.

**Entregáveis:**
- [ ] Documento de versionamento
- [ ] Regras de compatibilidade

**DoD:**
- [ ] Versão inicial: `1.0.0`
- [ ] Regras para MAJOR.MINOR.PATCH definidas
- [ ] Política de deprecation documentada

---

# EPIC 2: Implementação das Estruturas de Dados

**Objetivo:** Criar classes e tipos compartilhados entre Media Server e AI Agent.

**Duração estimada:** 1 Sprint (1 semana)

---

## Sprint 2.1: Estruturas de Dados Compartilhadas

### Microtask 2.1.1: Criar módulo `asp_protocol` compartilhado

**Descrição:** Implementar classes Python para representar as mensagens do protocolo.

**Entregáveis:**
- [ ] `shared/asp_protocol/__init__.py`
- [ ] `shared/asp_protocol/messages.py`
- [ ] `shared/asp_protocol/config.py`
- [ ] `shared/asp_protocol/validation.py`

**DoD:**
- [ ] Usar `dataclasses` ou `pydantic` para type safety
- [ ] Métodos `to_json()` e `from_json()` em todas as classes
- [ ] Validação de campos obrigatórios
- [ ] 100% de cobertura de testes unitários
- [ ] Docstrings em todas as classes públicas

**Código esperado:**

```python
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

class AudioEncoding(Enum):
    PCM_S16LE = "pcm_s16le"
    MULAW = "mulaw"
    ALAW = "alaw"

@dataclass
class AudioConfig:
    sample_rate: int = 8000
    encoding: AudioEncoding = AudioEncoding.PCM_S16LE
    channels: int = 1
    frame_duration_ms: int = 20

    def validate(self) -> List[str]:
        errors = []
        if self.sample_rate not in [8000, 16000, 24000, 48000]:
            errors.append(f"Invalid sample_rate: {self.sample_rate}")
        return errors

@dataclass
class VADConfig:
    silence_threshold_ms: int = 500
    min_speech_ms: int = 250
    threshold: float = 0.5
    ring_buffer_frames: int = 5
    speech_ratio: float = 0.4

    def validate(self) -> List[str]:
        errors = []
        if not 100 <= self.silence_threshold_ms <= 2000:
            errors.append(f"silence_threshold_ms must be 100-2000ms")
        if not 0.0 <= self.threshold <= 1.0:
            errors.append(f"threshold must be 0.0-1.0")
        return errors

@dataclass
class ProtocolCapabilities:
    version: str = "1.0.0"
    supported_sample_rates: List[int] = field(default_factory=lambda: [8000, 16000])
    supported_encodings: List[str] = field(default_factory=lambda: ["pcm_s16le"])
    vad_configurable: bool = True
    vad_parameters: List[str] = field(default_factory=lambda: [
        "silence_threshold_ms",
        "min_speech_ms",
        "threshold"
    ])
```

---

### Microtask 2.1.2: Criar classes de mensagens do protocolo

**Descrição:** Implementar todas as mensagens definidas no protocolo.

**Entregáveis:**
- [ ] `ProtocolCapabilitiesMessage`
- [ ] `SessionStartMessage`
- [ ] `SessionStartedMessage`
- [ ] `SessionEndMessage`
- [ ] `SessionEndedMessage`
- [ ] `ProtocolErrorMessage`

**DoD:**
- [ ] Herança de classe base `ASPMessage`
- [ ] Método `message_type` em cada classe
- [ ] Serialização/deserialização JSON funcionando
- [ ] Factory method `parse_message(json_str) -> ASPMessage`

---

### Microtask 2.1.3: Implementar validador de configuração

**Descrição:** Criar validador que verifica compatibilidade entre configs.

**Entregáveis:**
- [ ] `ConfigValidator` class
- [ ] Método `negotiate(client_config, server_capabilities) -> NegotiatedConfig`

**DoD:**
- [ ] Retorna config negociada ou lista de incompatibilidades
- [ ] Log detalhado de negociação
- [ ] Testes com cenários de sucesso e falha

---

### Microtask 2.1.4: Criar testes unitários para estruturas

**Descrição:** Implementar suite de testes completa.

**Entregáveis:**
- [ ] `tests/test_asp_protocol.py`
- [ ] Fixtures com mensagens de exemplo
- [ ] Testes de edge cases

**DoD:**
- [ ] Cobertura > 90%
- [ ] Testes de serialização roundtrip
- [ ] Testes de validação (válido e inválido)
- [ ] Testes de negociação

---

# EPIC 3: Implementação no AI Agent (Server)

**Objetivo:** Implementar o protocolo ASP no lado do servidor (AI Agent).

**Duração estimada:** 2 Sprints (2 semanas)

---

## Sprint 3.1: Handler de Capabilities e Session

### Microtask 3.1.1: Refatorar WebSocket server para suportar ASP

**Descrição:** Modificar `ai-agent/server/websocket.py` para implementar o handshake.

**Entregáveis:**
- [ ] Enviar `protocol.capabilities` ao conectar
- [ ] Handler para `session.start`
- [ ] Responder `session.started` com config negociada

**DoD:**
- [ ] Servidor envia capabilities automaticamente na conexão
- [ ] Validação de `session.start` com erros descritivos
- [ ] Config negociada armazenada na sessão
- [ ] Log de todas as mensagens de protocolo
- [ ] Backwards compatible (aceita clientes antigos)

**Código esperado:**

```python
class AIAgentServer:
    PROTOCOL_VERSION = "1.0.0"

    def get_capabilities(self) -> ProtocolCapabilities:
        return ProtocolCapabilities(
            version=self.PROTOCOL_VERSION,
            supported_sample_rates=[8000, 16000],
            supported_encodings=["pcm_s16le"],
            vad_configurable=True,
            vad_parameters=[
                "silence_threshold_ms",
                "min_speech_ms",
                "threshold",
                "ring_buffer_frames"
            ]
        )

    async def _handle_connection(self, websocket):
        # 1. Enviar capabilities
        caps = self.get_capabilities()
        await websocket.send(ProtocolCapabilitiesMessage(caps).to_json())

        # 2. Aguardar session.start
        async for message in websocket:
            msg = parse_message(message)
            if isinstance(msg, SessionStartMessage):
                await self._handle_session_start(websocket, msg)
            # ...
```

---

### Microtask 3.1.2: Implementar negociação de configuração

**Descrição:** Criar lógica de negociação entre config solicitada e capabilities.

**Entregáveis:**
- [ ] `SessionNegotiator` class
- [ ] Método `negotiate(requested, capabilities) -> (accepted, effective_config)`

**DoD:**
- [ ] Aceita config compatível
- [ ] Rejeita config incompatível com erro descritivo
- [ ] Ajusta valores fora do range para valores válidos (com warning)
- [ ] Retorna config efetiva que será usada

---

### Microtask 3.1.3: Aplicar config negociada ao AudioBuffer/VAD

**Descrição:** Usar configuração negociada para inicializar VAD.

**Entregáveis:**
- [ ] Modificar `AudioBuffer.__init__` para aceitar `VADConfig`
- [ ] Aplicar config da sessão ao criar AudioBuffer

**DoD:**
- [ ] AudioBuffer usa config da sessão, não hardcoded
- [ ] Log de config aplicada
- [ ] Testes com diferentes configs

---

## Sprint 3.2: Testes e Robustez

### Microtask 3.2.1: Implementar timeout de handshake

**Descrição:** Adicionar timeout para cliente enviar `session.start`.

**Entregáveis:**
- [ ] Timeout configurável (default: 30s)
- [ ] Desconectar cliente que não completa handshake

**DoD:**
- [ ] Timeout funciona corretamente
- [ ] Mensagem de erro enviada antes de desconectar
- [ ] Métrica de handshake timeouts

---

### Microtask 3.2.2: Implementar backwards compatibility

**Descrição:** Suportar clientes antigos que não implementam ASP.

**Entregáveis:**
- [ ] Detectar cliente legado (envia `session.start` antigo)
- [ ] Usar config default para clientes legados

**DoD:**
- [ ] Clientes antigos continuam funcionando
- [ ] Warning no log para clientes legados
- [ ] Flag `legacy_mode` na sessão

---

### Microtask 3.2.3: Criar testes de integração do servidor

**Descrição:** Implementar testes end-to-end do handshake.

**Entregáveis:**
- [ ] `tests/test_asp_integration.py`
- [ ] Mock WebSocket client
- [ ] Cenários de sucesso e falha

**DoD:**
- [ ] Teste de handshake completo
- [ ] Teste de config incompatível
- [ ] Teste de timeout
- [ ] Teste de cliente legado

---

# EPIC 4: Implementação no Media Server (Client)

**Objetivo:** Implementar o protocolo ASP no lado do cliente (Media Server).

**Duração estimada:** 2 Sprints (2 semanas)

---

## Sprint 4.1: Handshake do Cliente

### Microtask 4.1.1: Refatorar WebSocket client para suportar ASP

**Descrição:** Modificar `media-server/ws/client.py` para implementar o handshake.

**Entregáveis:**
- [ ] Receber e parsear `protocol.capabilities`
- [ ] Enviar `session.start` com config desejada
- [ ] Processar `session.started` e armazenar config negociada

**DoD:**
- [ ] Cliente aguarda capabilities antes de enviar session.start
- [ ] Valida que servidor suporta config desejada
- [ ] Armazena config negociada para uso no streaming
- [ ] Retry se handshake falhar

**Código esperado:**

```python
class WebSocketClient:
    async def connect(self):
        self._ws = await websockets.connect(self._url, ...)

        # 1. Receber capabilities
        caps_msg = await asyncio.wait_for(
            self._receive_capabilities(),
            timeout=10.0
        )
        self._server_capabilities = caps_msg.capabilities

        logger.info(f"Server capabilities: {self._server_capabilities}")

    async def start_session(self, session_info: SessionInfo) -> bool:
        # 2. Enviar session.start com nossa config
        config = self._build_session_config(session_info)
        start_msg = SessionStartMessage(
            session_id=session_info.session_id,
            call_id=session_info.call_id,
            audio=config.audio,
            vad=config.vad
        )
        await self._ws.send(start_msg.to_json())

        # 3. Aguardar session.started
        response = await asyncio.wait_for(
            self._receive_session_response(),
            timeout=10.0
        )

        if response.status == "accepted":
            self._session_config = response.negotiated
            return True
        else:
            logger.error(f"Session rejected: {response.errors}")
            return False
```

---

### Microtask 4.1.2: Criar ConfigBuilder para Media Server

**Descrição:** Implementar builder que cria config baseada em capabilities do servidor.

**Entregáveis:**
- [ ] `MediaServerConfigBuilder` class
- [ ] Lê config local e ajusta para capabilities do servidor

**DoD:**
- [ ] Builder pattern implementado
- [ ] Valida config contra capabilities antes de enviar
- [ ] Log de ajustes feitos

---

### Microtask 4.1.3: Aplicar config negociada ao StreamingAudioPort

**Descrição:** Usar configuração negociada para inicializar VAD do streaming.

**Entregáveis:**
- [ ] Modificar `StreamingVAD.__init__` para aceitar `VADConfig`
- [ ] Passar config da sessão para streaming port

**DoD:**
- [ ] StreamingVAD usa config da sessão
- [ ] Log de config aplicada
- [ ] Consistência garantida com AI Agent

---

## Sprint 4.2: Robustez e Fallback

### Microtask 4.2.1: Implementar fallback para servidor sem ASP

**Descrição:** Suportar servidores que não implementam ASP.

**Entregáveis:**
- [ ] Detectar servidor legado (não envia capabilities)
- [ ] Usar fluxo antigo com config default

**DoD:**
- [ ] Timeout de 5s para capabilities
- [ ] Fallback automático para modo legado
- [ ] Warning no log

---

### Microtask 4.2.2: Implementar renegociação de sessão

**Descrição:** Permitir atualizar config durante sessão (ex: ajustar VAD).

**Entregáveis:**
- [ ] Mensagem `session.update`
- [ ] Handler para `session.updated`

**DoD:**
- [ ] Config pode ser ajustada mid-session
- [ ] Novo config aplicado sem interromper streaming
- [ ] Casos de uso: ajustar threshold se muito ruído

---

### Microtask 4.2.3: Criar testes de integração do cliente

**Descrição:** Implementar testes end-to-end do cliente.

**Entregáveis:**
- [ ] `tests/test_ws_client_asp.py`
- [ ] Mock WebSocket server
- [ ] Cenários de sucesso e falha

**DoD:**
- [ ] Teste de handshake completo
- [ ] Teste de servidor sem ASP
- [ ] Teste de renegociação
- [ ] Teste de reconexão com nova sessão

---

# EPIC 5: Observabilidade e Métricas

**Objetivo:** Implementar logging, métricas e debugging do protocolo.

**Duração estimada:** 1 Sprint (1 semana)

---

## Sprint 5.1: Observabilidade

### Microtask 5.1.1: Adicionar métricas Prometheus para ASP

**Descrição:** Criar métricas para monitorar o protocolo.

**Entregáveis:**
- [ ] `asp_handshake_duration_seconds` - Histogram
- [ ] `asp_handshake_success_total` - Counter
- [ ] `asp_handshake_failure_total` - Counter (por tipo de erro)
- [ ] `asp_session_config` - Gauge (current config values)
- [ ] `asp_negotiation_adjustments_total` - Counter

**DoD:**
- [ ] Métricas expostas em `/metrics`
- [ ] Dashboard Grafana atualizado
- [ ] Alertas para falhas de handshake

---

### Microtask 5.1.2: Implementar logging estruturado do protocolo

**Descrição:** Adicionar logs detalhados para debugging.

**Entregáveis:**
- [ ] Log de todas as mensagens ASP (DEBUG level)
- [ ] Log de config negociada (INFO level)
- [ ] Log de erros de protocolo (WARNING/ERROR)

**DoD:**
- [ ] Logs incluem session_id para correlação
- [ ] Formato JSON para parsing
- [ ] Redação de dados sensíveis

---

### Microtask 5.1.3: Criar comando de debug ASP

**Descrição:** Implementar ferramenta CLI para testar handshake.

**Entregáveis:**
- [ ] Script `tools/asp_debug.py`
- [ ] Conecta ao servidor e mostra capabilities
- [ ] Permite enviar session.start customizado

**DoD:**
- [ ] Output colorido e legível
- [ ] Mostra tempo de cada etapa
- [ ] Exporta resultado em JSON

---

# EPIC 6: Documentação e Release

**Objetivo:** Documentar o protocolo e preparar release.

**Duração estimada:** 1 Sprint (1 semana)

---

## Sprint 6.1: Documentação Final

### Microtask 6.1.1: Criar documentação técnica completa

**Descrição:** Documentar o protocolo para desenvolvedores.

**Entregáveis:**
- [ ] `docs/ASP_PROTOCOL.md` - Especificação completa
- [ ] `docs/ASP_INTEGRATION.md` - Guia de integração
- [ ] `docs/ASP_TROUBLESHOOTING.md` - Guia de troubleshooting

**DoD:**
- [ ] Todos os campos documentados
- [ ] Exemplos de código em Python
- [ ] Diagramas de sequência atualizados
- [ ] FAQ com problemas comuns

---

### Microtask 6.1.2: Criar changelog e migration guide

**Descrição:** Documentar mudanças e como migrar.

**Entregáveis:**
- [ ] `CHANGELOG.md` atualizado
- [ ] `docs/MIGRATION_TO_ASP.md`

**DoD:**
- [ ] Breaking changes listados
- [ ] Passo-a-passo de migração
- [ ] Exemplos antes/depois

---

### Microtask 6.1.3: Atualizar README e exemplos

**Descrição:** Atualizar documentação principal.

**Entregáveis:**
- [ ] README.md atualizado
- [ ] Exemplos de configuração
- [ ] Docker-compose com novos env vars

**DoD:**
- [ ] Quick start funciona com ASP
- [ ] Env vars documentados
- [ ] Exemplos testados

---

# Cronograma Resumido

| Sprint | Epic | Duração | Entregável Principal |
|--------|------|---------|---------------------|
| 1.1 | Epic 1: Definição | 1 semana | Especificação ASP |
| 2.1 | Epic 2: Estruturas | 1 semana | Módulo `asp_protocol` |
| 3.1 | Epic 3: AI Agent | 1 semana | Server com handshake |
| 3.2 | Epic 3: AI Agent | 1 semana | Testes e robustez |
| 4.1 | Epic 4: Media Server | 1 semana | Client com handshake |
| 4.2 | Epic 4: Media Server | 1 semana | Fallback e testes |
| 5.1 | Epic 5: Observabilidade | 1 semana | Métricas e logging |
| 6.1 | Epic 6: Documentação | 1 semana | Docs e release |

**Total: 8 semanas**

---

# Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|-------|--------------|---------|-----------|
| Quebra de compatibilidade | Alta | Alto | Modo legado obrigatório |
| Complexidade de negociação | Média | Médio | Começar com config simples |
| Performance do handshake | Baixa | Médio | Cache de capabilities |
| Adoção por clientes externos | Média | Baixo | Documentação clara |

---

# Critérios de Sucesso do Projeto

1. **Zero inconsistências de config** entre Media Server e AI Agent
2. **100% das sessões** com config explicitamente negociada
3. **Backwards compatibility** com clientes existentes
4. **Métricas** mostrando taxa de sucesso de handshake > 99%
5. **Documentação** completa e atualizada

---

# Referências

1. OpenAI Realtime API - https://platform.openai.com/docs/api-reference/realtime
2. OpenAI VAD Documentation - https://platform.openai.com/docs/guides/realtime-vad
3. Twilio Media Streams - https://www.twilio.com/docs/voice/media-streams/websocket-messages
4. LiveKit Agents Sessions - https://docs.livekit.io/agents/logic/sessions/
5. LiveKit VAD - https://docs.livekit.io/agents/v0/integrations/openai/customize/vad
6. Agora Conversational AI - https://medium.com/agora-io/a-playground-for-testing-voice-ai-agents
7. RFC 8124 (SDP WebSocket) - https://www.rfc-editor.org/rfc/rfc8124.html
8. RFC 6455 (WebSocket Protocol) - https://datatracker.ietf.org/doc/html/rfc6455
9. Pipecat Framework - https://docs.pipecat.ai/guides/telephony/twilio-websockets
