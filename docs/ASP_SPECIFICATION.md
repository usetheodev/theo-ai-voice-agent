# Audio Session Protocol (ASP) - Especificação v1.0.0

## Visão Geral

O Audio Session Protocol (ASP) é um protocolo de negociação de configuração para sessões de áudio em tempo real sobre WebSocket. Ele garante que o Media Server (cliente) e o AI Agent (servidor) estejam configurados de forma consistente antes do início do streaming de áudio.

## Princípios de Design

1. **Simplicidade** - Mensagens JSON claras e autoexplicativas
2. **Extensibilidade** - Novos campos podem ser adicionados sem quebrar compatibilidade
3. **Explicitação** - Toda configuração é negociada explicitamente
4. **Backwards Compatibility** - Suporta clientes/servidores legados

---

## Diagrama de Estados da Sessão

```
                    ┌─────────────────────────────────────────────────────┐
                    │                                                     │
                    ▼                                                     │
    ┌───────────┐   WebSocket    ┌──────────────────┐                    │
    │           │   Connect      │                  │                    │
    │  IDLE     │──────────────▶│  CONNECTED       │                    │
    │           │               │  (awaiting caps) │                    │
    └───────────┘               └────────┬─────────┘                    │
                                         │                               │
                                         │ protocol.capabilities         │
                                         ▼                               │
                               ┌──────────────────┐                      │
                               │                  │                      │
                               │  CAPS_RECEIVED   │                      │
                               │                  │                      │
                               └────────┬─────────┘                      │
                                        │                                │
                                        │ session.start                  │
                                        ▼                                │
                               ┌──────────────────┐                      │
                               │                  │     protocol.error   │
                               │  NEGOTIATING     │─────────────────────▶│
                               │                  │                      │
                               └────────┬─────────┘                      │
                                        │                                │
                                        │ session.started                │
                                        ▼                                │
                               ┌──────────────────┐                      │
                               │                  │                      │
                               │  ACTIVE          │◀───────────┐        │
                               │  (streaming)     │            │        │
                               └────────┬─────────┘            │        │
                                        │                      │        │
                        session.update  │                      │        │
                                        ▼                      │        │
                               ┌──────────────────┐            │        │
                               │                  │            │        │
                               │  UPDATING        │────────────┘        │
                               │                  │  session.updated    │
                               └────────┬─────────┘                     │
                                        │                               │
                                        │ session.end                   │
                                        ▼                               │
                               ┌──────────────────┐                     │
                               │                  │                     │
                               │  ENDING          │                     │
                               │                  │                     │
                               └────────┬─────────┘                     │
                                        │                               │
                                        │ session.ended                 │
                                        ▼                               │
                               ┌──────────────────┐                     │
                               │                  │                     │
                               │  CLOSED          │─────────────────────┘
                               │                  │    (pode reconectar)
                               └──────────────────┘
```

---

## Tipos de Dados

### Enumerações

#### AudioEncoding
| Valor | Descrição |
|-------|-----------|
| `pcm_s16le` | PCM 16-bit signed little-endian (padrão) |
| `mulaw` | G.711 μ-law |
| `alaw` | G.711 A-law |

#### SessionStatus
| Valor | Descrição |
|-------|-----------|
| `accepted` | Configuração aceita integralmente |
| `accepted_with_changes` | Configuração aceita com ajustes |
| `rejected` | Configuração rejeitada |

#### ErrorCategory
| Valor | Descrição |
|-------|-----------|
| `protocol` | Erro de protocolo (versão, formato) |
| `audio` | Erro de configuração de áudio |
| `vad` | Erro de configuração de VAD |
| `session` | Erro de sessão (timeout, duplicada) |

### Objetos

#### AudioConfig
Configuração de formato de áudio.

| Campo | Tipo | Obrigatório | Default | Descrição |
|-------|------|-------------|---------|-----------|
| `sample_rate` | integer | Não | `8000` | Taxa de amostragem em Hz |
| `encoding` | AudioEncoding | Não | `pcm_s16le` | Codificação do áudio |
| `channels` | integer | Não | `1` | Número de canais (1=mono) |
| `frame_duration_ms` | integer | Não | `20` | Duração de cada frame em ms |

**Valores válidos:**
- `sample_rate`: 8000, 16000, 24000, 48000
- `channels`: 1 (mono apenas nesta versão)
- `frame_duration_ms`: 10, 20, 30

#### VADConfig
Configuração do Voice Activity Detection.

| Campo | Tipo | Obrigatório | Default | Range | Descrição |
|-------|------|-------------|---------|-------|-----------|
| `enabled` | boolean | Não | `true` | - | Se VAD está habilitado |
| `silence_threshold_ms` | integer | Não | `500` | 100-2000 | Silêncio para considerar fim de fala |
| `min_speech_ms` | integer | Não | `250` | 100-1000 | Duração mínima de fala válida |
| `threshold` | float | Não | `0.5` | 0.0-1.0 | Sensibilidade de detecção |
| `ring_buffer_frames` | integer | Não | `5` | 3-10 | Frames para suavização |
| `speech_ratio` | float | Não | `0.4` | 0.2-0.8 | Proporção mínima de fala no buffer |
| `prefix_padding_ms` | integer | Não | `300` | 0-500 | Áudio incluído antes da fala detectada |

#### ProtocolCapabilities
Capacidades suportadas pelo servidor.

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `version` | string | Sim | Versão do protocolo (semver) |
| `supported_sample_rates` | integer[] | Sim | Sample rates suportados |
| `supported_encodings` | string[] | Sim | Encodings suportados |
| `supported_frame_durations` | integer[] | Não | Frame durations suportados |
| `vad_configurable` | boolean | Sim | Se VAD é configurável |
| `vad_parameters` | string[] | Não | Parâmetros VAD configuráveis |
| `max_session_duration_seconds` | integer | Não | Duração máxima da sessão |
| `features` | string[] | Não | Features suportadas (ex: "barge_in", "streaming_tts") |

#### NegotiatedConfig
Configuração efetiva após negociação.

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `audio` | AudioConfig | Sim | Configuração de áudio negociada |
| `vad` | VADConfig | Sim | Configuração de VAD negociada |
| `adjustments` | Adjustment[] | Não | Lista de ajustes feitos |

#### Adjustment
Ajuste feito durante negociação.

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `field` | string | Sim | Campo ajustado (ex: "vad.threshold") |
| `requested` | any | Sim | Valor solicitado |
| `applied` | any | Sim | Valor aplicado |
| `reason` | string | Sim | Motivo do ajuste |

#### ProtocolError
Erro de protocolo.

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `code` | integer | Sim | Código do erro |
| `category` | ErrorCategory | Sim | Categoria do erro |
| `message` | string | Sim | Mensagem human-readable |
| `details` | object | Não | Detalhes adicionais |
| `recoverable` | boolean | Não | Se o erro é recuperável |

---

## Mensagens do Protocolo

### 1. protocol.capabilities

**Direção:** Server → Client

**Descrição:** Enviada pelo servidor imediatamente após a conexão WebSocket ser estabelecida. Informa ao cliente as capacidades e limitações do servidor.

**Campos:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `type` | string | Sim | Sempre `"protocol.capabilities"` |
| `version` | string | Sim | Versão do protocolo |
| `server_id` | string | Não | Identificador do servidor |
| `capabilities` | ProtocolCapabilities | Sim | Capacidades suportadas |
| `timestamp` | string | Não | ISO 8601 timestamp |

**Exemplo:**

```json
{
  "type": "protocol.capabilities",
  "version": "1.0.0",
  "server_id": "ai-agent-01",
  "capabilities": {
    "version": "1.0.0",
    "supported_sample_rates": [8000, 16000],
    "supported_encodings": ["pcm_s16le", "mulaw"],
    "supported_frame_durations": [10, 20, 30],
    "vad_configurable": true,
    "vad_parameters": [
      "silence_threshold_ms",
      "min_speech_ms",
      "threshold",
      "ring_buffer_frames",
      "speech_ratio",
      "prefix_padding_ms"
    ],
    "max_session_duration_seconds": 3600,
    "features": ["barge_in", "streaming_tts", "sentence_pipeline"]
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

---

### 2. session.start

**Direção:** Client → Server

**Descrição:** Enviada pelo cliente para iniciar uma sessão de áudio com a configuração desejada.

**Campos:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `type` | string | Sim | Sempre `"session.start"` |
| `session_id` | string | Sim | UUID único da sessão |
| `call_id` | string | Não | ID da chamada SIP (se aplicável) |
| `audio` | AudioConfig | Não | Configuração de áudio desejada |
| `vad` | VADConfig | Não | Configuração de VAD desejada |
| `metadata` | object | Não | Metadados customizados |
| `timestamp` | string | Não | ISO 8601 timestamp |

**Exemplo:**

```json
{
  "type": "session.start",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "call_id": "sip-call-12345",
  "audio": {
    "sample_rate": 8000,
    "encoding": "pcm_s16le",
    "channels": 1,
    "frame_duration_ms": 20
  },
  "vad": {
    "enabled": true,
    "silence_threshold_ms": 500,
    "min_speech_ms": 250,
    "threshold": 0.5,
    "ring_buffer_frames": 5,
    "speech_ratio": 0.4,
    "prefix_padding_ms": 300
  },
  "metadata": {
    "caller_number": "+5511999999999",
    "language": "pt-BR"
  },
  "timestamp": "2024-01-15T10:30:01.000Z"
}
```

---

### 3. session.started

**Direção:** Server → Client

**Descrição:** Resposta do servidor confirmando ou rejeitando o início da sessão.

**Campos:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `type` | string | Sim | Sempre `"session.started"` |
| `session_id` | string | Sim | UUID da sessão |
| `status` | SessionStatus | Sim | Status da negociação |
| `negotiated` | NegotiatedConfig | Sim* | Config negociada (*se aceita) |
| `errors` | ProtocolError[] | Não | Erros (se rejeitada) |
| `timestamp` | string | Não | ISO 8601 timestamp |

**Exemplo (aceita):**

```json
{
  "type": "session.started",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "accepted",
  "negotiated": {
    "audio": {
      "sample_rate": 8000,
      "encoding": "pcm_s16le",
      "channels": 1,
      "frame_duration_ms": 20
    },
    "vad": {
      "enabled": true,
      "silence_threshold_ms": 500,
      "min_speech_ms": 250,
      "threshold": 0.5,
      "ring_buffer_frames": 5,
      "speech_ratio": 0.4,
      "prefix_padding_ms": 300
    },
    "adjustments": []
  },
  "timestamp": "2024-01-15T10:30:01.100Z"
}
```

**Exemplo (aceita com ajustes):**

```json
{
  "type": "session.started",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "accepted_with_changes",
  "negotiated": {
    "audio": {
      "sample_rate": 8000,
      "encoding": "pcm_s16le",
      "channels": 1,
      "frame_duration_ms": 20
    },
    "vad": {
      "enabled": true,
      "silence_threshold_ms": 500,
      "min_speech_ms": 250,
      "threshold": 0.5,
      "ring_buffer_frames": 5,
      "speech_ratio": 0.4,
      "prefix_padding_ms": 300
    },
    "adjustments": [
      {
        "field": "vad.threshold",
        "requested": 0.05,
        "applied": 0.1,
        "reason": "Value below minimum (0.1)"
      },
      {
        "field": "vad.silence_threshold_ms",
        "requested": 50,
        "applied": 100,
        "reason": "Value below minimum (100ms)"
      }
    ]
  },
  "timestamp": "2024-01-15T10:30:01.100Z"
}
```

**Exemplo (rejeitada):**

```json
{
  "type": "session.started",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "rejected",
  "errors": [
    {
      "code": 2001,
      "category": "audio",
      "message": "Sample rate 44100 not supported",
      "details": {
        "requested": 44100,
        "supported": [8000, 16000]
      },
      "recoverable": true
    }
  ],
  "timestamp": "2024-01-15T10:30:01.100Z"
}
```

---

### 4. session.update

**Direção:** Client → Server

**Descrição:** Atualiza a configuração durante uma sessão ativa (ex: ajustar VAD threshold).

**Campos:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `type` | string | Sim | Sempre `"session.update"` |
| `session_id` | string | Sim | UUID da sessão |
| `vad` | VADConfig | Não | Nova configuração de VAD |
| `timestamp` | string | Não | ISO 8601 timestamp |

**Exemplo:**

```json
{
  "type": "session.update",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "vad": {
    "silence_threshold_ms": 700,
    "threshold": 0.6
  },
  "timestamp": "2024-01-15T10:35:00.000Z"
}
```

**Nota:** Apenas campos de VAD podem ser atualizados. Configuração de áudio requer nova sessão.

---

### 5. session.updated

**Direção:** Server → Client

**Descrição:** Confirma atualização da configuração.

**Campos:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `type` | string | Sim | Sempre `"session.updated"` |
| `session_id` | string | Sim | UUID da sessão |
| `status` | SessionStatus | Sim | Status da atualização |
| `negotiated` | NegotiatedConfig | Sim* | Config atualizada (*se aceita) |
| `errors` | ProtocolError[] | Não | Erros (se rejeitada) |
| `timestamp` | string | Não | ISO 8601 timestamp |

**Exemplo:**

```json
{
  "type": "session.updated",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "accepted",
  "negotiated": {
    "audio": {
      "sample_rate": 8000,
      "encoding": "pcm_s16le",
      "channels": 1,
      "frame_duration_ms": 20
    },
    "vad": {
      "enabled": true,
      "silence_threshold_ms": 700,
      "min_speech_ms": 250,
      "threshold": 0.6,
      "ring_buffer_frames": 5,
      "speech_ratio": 0.4,
      "prefix_padding_ms": 300
    },
    "adjustments": []
  },
  "timestamp": "2024-01-15T10:35:00.100Z"
}
```

---

### 6. session.end

**Direção:** Client → Server

**Descrição:** Encerra uma sessão de forma graciosa.

**Campos:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `type` | string | Sim | Sempre `"session.end"` |
| `session_id` | string | Sim | UUID da sessão |
| `reason` | string | Não | Motivo do encerramento |
| `timestamp` | string | Não | ISO 8601 timestamp |

**Exemplo:**

```json
{
  "type": "session.end",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "reason": "call_hangup",
  "timestamp": "2024-01-15T10:45:00.000Z"
}
```

---

### 7. session.ended

**Direção:** Server → Client

**Descrição:** Confirma encerramento da sessão.

**Campos:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `type` | string | Sim | Sempre `"session.ended"` |
| `session_id` | string | Sim | UUID da sessão |
| `duration_seconds` | float | Não | Duração total da sessão |
| `statistics` | SessionStats | Não | Estatísticas da sessão |
| `timestamp` | string | Não | ISO 8601 timestamp |

**Exemplo:**

```json
{
  "type": "session.ended",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "duration_seconds": 900.5,
  "statistics": {
    "audio_frames_received": 45025,
    "audio_frames_sent": 38000,
    "vad_speech_events": 42,
    "barge_in_count": 3,
    "average_response_latency_ms": 450
  },
  "timestamp": "2024-01-15T10:45:00.100Z"
}
```

---

### 8. protocol.error

**Direção:** Server → Client

**Descrição:** Informa erro de protocolo que pode resultar em desconexão.

**Campos:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `type` | string | Sim | Sempre `"protocol.error"` |
| `error` | ProtocolError | Sim | Detalhes do erro |
| `session_id` | string | Não | UUID da sessão (se aplicável) |
| `timestamp` | string | Não | ISO 8601 timestamp |

**Exemplo:**

```json
{
  "type": "protocol.error",
  "error": {
    "code": 1002,
    "category": "protocol",
    "message": "Handshake timeout: session.start not received within 30s",
    "recoverable": false
  },
  "timestamp": "2024-01-15T10:30:31.000Z"
}
```

---

## Códigos de Erro

### Erros de Protocolo (1xxx)

| Código | Mensagem | Descrição | Recuperável |
|--------|----------|-----------|-------------|
| 1001 | `invalid_message_format` | JSON inválido ou formato incorreto | Sim |
| 1002 | `handshake_timeout` | Timeout aguardando session.start | Não |
| 1003 | `invalid_message_type` | Tipo de mensagem desconhecido | Sim |
| 1004 | `version_mismatch` | Versão do protocolo incompatível | Não |
| 1005 | `session_already_active` | Tentativa de iniciar sessão duplicada | Sim |

### Erros de Áudio (2xxx)

| Código | Mensagem | Descrição | Recuperável |
|--------|----------|-----------|-------------|
| 2001 | `unsupported_sample_rate` | Sample rate não suportado | Sim |
| 2002 | `unsupported_encoding` | Encoding não suportado | Sim |
| 2003 | `invalid_frame_duration` | Frame duration inválido | Sim |
| 2004 | `audio_processing_error` | Erro ao processar áudio | Sim |

### Erros de VAD (3xxx)

| Código | Mensagem | Descrição | Recuperável |
|--------|----------|-----------|-------------|
| 3001 | `invalid_vad_parameter` | Parâmetro VAD fora do range | Sim |
| 3002 | `vad_not_configurable` | Servidor não permite configurar VAD | Sim |
| 3003 | `vad_initialization_error` | Erro ao inicializar VAD | Não |

### Erros de Sessão (4xxx)

| Código | Mensagem | Descrição | Recuperável |
|--------|----------|-----------|-------------|
| 4001 | `session_not_found` | Sessão não existe | Sim |
| 4002 | `session_expired` | Sessão expirada por timeout | Não |
| 4003 | `session_limit_reached` | Limite de sessões atingido | Não |
| 4004 | `session_update_not_allowed` | Atualização não permitida neste estado | Sim |

---

## Versionamento

### Formato de Versão

O protocolo segue [Semantic Versioning 2.0.0](https://semver.org/):

```
MAJOR.MINOR.PATCH
```

- **MAJOR**: Mudanças incompatíveis (breaking changes)
- **MINOR**: Novas funcionalidades retrocompatíveis
- **PATCH**: Correções de bugs retrocompatíveis

### Política de Compatibilidade

1. **Campos novos opcionais**: Não incrementam versão major
2. **Novos tipos de mensagem**: Incrementam versão minor
3. **Mudança de campos obrigatórios**: Incrementam versão major
4. **Deprecation**: Anunciado com 2 versões minor de antecedência

### Negociação de Versão

- Servidor envia sua versão em `protocol.capabilities`
- Cliente deve enviar `session.start` compatível com a versão do servidor
- Se versão major diferente, servidor rejeita com erro `1004`

---

## Sequência de Mensagens

### Handshake Normal

```
Client                                Server
   |                                    |
   |-------- WebSocket Connect -------->|
   |                                    |
   |<------ protocol.capabilities ------|
   |                                    |
   |-------- session.start ------------>|
   |                                    |
   |<------- session.started -----------|
   |                                    |
   |======== audio streaming ===========>|
   |<========= audio streaming ==========|
   |                                    |
```

### Atualização de Configuração

```
Client                                Server
   |                                    |
   |======== audio streaming ===========>|
   |                                    |
   |-------- session.update ----------->|
   |                                    |
   |<------- session.updated -----------|
   |                                    |
   |======== audio streaming ===========>|
   |                                    |
```

### Encerramento Gracioso

```
Client                                Server
   |                                    |
   |-------- session.end -------------->|
   |                                    |
   |<------- session.ended -------------|
   |                                    |
   |-------- WebSocket Close ---------->|
   |                                    |
```

### Erro e Recuperação

```
Client                                Server
   |                                    |
   |-------- session.start ------------>|
   |        (invalid config)            |
   |                                    |
   |<------- session.started -----------|
   |        (status: rejected)          |
   |                                    |
   |-------- session.start ------------>|
   |        (corrected config)          |
   |                                    |
   |<------- session.started -----------|
   |        (status: accepted)          |
   |                                    |
```

---

## Mensagens de Áudio (Binárias)

### Frame de Áudio (Client → Server)

Após `session.started`, o cliente envia frames de áudio como mensagens binárias WebSocket:

```
Bytes 0-1:   Frame type (0x01 = audio input)
Bytes 2-5:   Sequence number (uint32, little-endian)
Bytes 6-13:  Timestamp (uint64, microseconds since session start)
Bytes 14+:   Audio data (PCM samples)
```

### Frame de Áudio (Server → Client)

O servidor envia respostas de áudio:

```
Bytes 0-1:   Frame type (0x02 = audio output)
Bytes 2-5:   Sequence number (uint32, little-endian)
Bytes 6-13:  Timestamp (uint64, microseconds)
Bytes 14:    Flags (bit 0: is_final, bit 1: is_barge_in_response)
Bytes 15+:   Audio data (PCM samples)
```

### Mensagem de Controle (JSON sobre WebSocket texto)

Mensagens de controle continuam sendo enviadas como JSON:

```json
{
  "type": "audio.speech_start",
  "session_id": "...",
  "timestamp": "..."
}
```

```json
{
  "type": "audio.speech_end",
  "session_id": "...",
  "duration_ms": 1500,
  "timestamp": "..."
}
```

```json
{
  "type": "response.start",
  "session_id": "...",
  "response_id": "...",
  "timestamp": "..."
}
```

```json
{
  "type": "response.end",
  "session_id": "...",
  "response_id": "...",
  "interrupted": false,
  "timestamp": "..."
}
```

---

## Backwards Compatibility

### Detectando Clientes Legados

Se o servidor não receber `session.start` com campos ASP dentro de 5 segundos após enviar `protocol.capabilities`, deve assumir cliente legado e:

1. Usar configuração default
2. Aceitar mensagens no formato antigo
3. Marcar sessão como `legacy_mode: true`
4. Emitir warning no log

### Detectando Servidores Legados

Se o cliente não receber `protocol.capabilities` dentro de 5 segundos após conectar:

1. Assumir servidor legado
2. Enviar `session.start` no formato antigo
3. Usar configuração default
4. Marcar sessão como `legacy_mode: true`
5. Emitir warning no log

---

## Considerações de Segurança

1. **Validação de Entrada**: Todos os valores devem ser validados contra ranges permitidos
2. **Rate Limiting**: Limitar tentativas de `session.start` (ex: 5/minuto)
3. **Timeout de Handshake**: Desconectar clientes que não completam handshake
4. **Sanitização de Metadata**: Não confiar em metadata enviado pelo cliente

---

## Apêndice A: JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://example.com/asp/1.0.0/schema.json",
  "title": "Audio Session Protocol",
  "description": "Schema for ASP messages",

  "definitions": {
    "AudioEncoding": {
      "type": "string",
      "enum": ["pcm_s16le", "mulaw", "alaw"]
    },

    "AudioConfig": {
      "type": "object",
      "properties": {
        "sample_rate": {
          "type": "integer",
          "enum": [8000, 16000, 24000, 48000],
          "default": 8000
        },
        "encoding": {
          "$ref": "#/definitions/AudioEncoding",
          "default": "pcm_s16le"
        },
        "channels": {
          "type": "integer",
          "enum": [1],
          "default": 1
        },
        "frame_duration_ms": {
          "type": "integer",
          "enum": [10, 20, 30],
          "default": 20
        }
      }
    },

    "VADConfig": {
      "type": "object",
      "properties": {
        "enabled": {
          "type": "boolean",
          "default": true
        },
        "silence_threshold_ms": {
          "type": "integer",
          "minimum": 100,
          "maximum": 2000,
          "default": 500
        },
        "min_speech_ms": {
          "type": "integer",
          "minimum": 100,
          "maximum": 1000,
          "default": 250
        },
        "threshold": {
          "type": "number",
          "minimum": 0.0,
          "maximum": 1.0,
          "default": 0.5
        },
        "ring_buffer_frames": {
          "type": "integer",
          "minimum": 3,
          "maximum": 10,
          "default": 5
        },
        "speech_ratio": {
          "type": "number",
          "minimum": 0.2,
          "maximum": 0.8,
          "default": 0.4
        },
        "prefix_padding_ms": {
          "type": "integer",
          "minimum": 0,
          "maximum": 500,
          "default": 300
        }
      }
    }
  }
}
```

---

## Apêndice B: Valores Recomendados

### Para Ambiente Silencioso (Escritório)
```json
{
  "vad": {
    "silence_threshold_ms": 500,
    "min_speech_ms": 200,
    "threshold": 0.4,
    "speech_ratio": 0.3
  }
}
```

### Para Ambiente Ruidoso (Call Center)
```json
{
  "vad": {
    "silence_threshold_ms": 700,
    "min_speech_ms": 300,
    "threshold": 0.6,
    "speech_ratio": 0.5
  }
}
```

### Para Conversas Reflexivas (Suporte Técnico)
```json
{
  "vad": {
    "silence_threshold_ms": 800,
    "min_speech_ms": 250,
    "threshold": 0.5,
    "speech_ratio": 0.4
  }
}
```

### Para Q&A Rápido (FAQ Bot)
```json
{
  "vad": {
    "silence_threshold_ms": 400,
    "min_speech_ms": 150,
    "threshold": 0.5,
    "speech_ratio": 0.4
  }
}
```
