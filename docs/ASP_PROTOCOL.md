# Audio Session Protocol (ASP) - Documentação Técnica

## Visão Geral

O Audio Session Protocol (ASP) é um protocolo de negociação de configuração para sessões de áudio em tempo real sobre WebSocket. Ele garante que o Media Server (cliente) e o AI Agent (servidor) estejam configurados de forma consistente antes do início do streaming de áudio.

## Por que ASP?

Antes do ASP, o sistema tinha um problema grave: **configurações de áudio e VAD eram hardcoded e inconsistentes** entre Media Server e AI Agent:

| Problema | Impacto |
|----------|---------|
| `silence_threshold_ms` diferente | Fala cortada ou interrupções prematuras |
| `min_speech_ms` diferente | Falas curtas rejeitadas |
| `speech_ratio` diferente | Detecção de fala inconsistente |
| Sem negociação | Impossível debugar ou ajustar dinamicamente |

O ASP resolve isso através de **negociação explícita** de configuração no início de cada sessão.

## Arquitetura

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌─────────────────┐                    ┌─────────────────┐    │
│  │  Media Server   │                    │    AI Agent     │    │
│  │    (Cliente)    │                    │   (Servidor)    │    │
│  │                 │                    │                 │    │
│  │  ┌───────────┐  │                    │  ┌───────────┐  │    │
│  │  │ ASP       │  │  WebSocket + ASP   │  │ ASP       │  │    │
│  │  │ Client    │◄─┼────────────────────┼─►│ Handler   │  │    │
│  │  │ Handler   │  │                    │  │           │  │    │
│  │  └─────┬─────┘  │                    │  └─────┬─────┘  │    │
│  │        │        │                    │        │        │    │
│  │  ┌─────▼─────┐  │                    │  ┌─────▼─────┐  │    │
│  │  │ VAD       │  │                    │  │ VAD       │  │    │
│  │  │ (config)  │  │                    │  │ (config)  │  │    │
│  │  └───────────┘  │                    │  └───────────┘  │    │
│  └─────────────────┘                    └─────────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │          shared/asp_protocol/ (módulo compartilhado)    │   │
│  │  • enums.py     • config.py    • messages.py            │   │
│  │  • negotiation.py • errors.py                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Fluxo do Protocolo

### 1. Handshake Inicial

```
Media Server (Cliente)                    AI Agent (Servidor)
      │                                        │
      │──────── WebSocket Connect ────────────►│
      │                                        │
      │◄─────── protocol.capabilities ─────────│
      │         (versão, sample_rates,         │
      │          encodings, vad_params)        │
      │                                        │
      │──────── session.start ────────────────►│
      │         (session_id, audio, vad)       │
      │                                        │
      │◄─────── session.started ──────────────│
      │         (status, negotiated_config)    │
      │                                        │
      │═══════ Audio Streaming ═══════════════│
      │                                        │
```

### 2. Atualização Mid-Session

```
      │═══════ Audio Streaming ═══════════════│
      │                                        │
      │──────── session.update ───────────────►│
      │         (new vad config)               │
      │                                        │
      │◄─────── session.updated ──────────────│
      │         (status, new_config)           │
      │                                        │
      │═══════ Audio Streaming ═══════════════│
```

### 3. Encerramento

```
      │──────── session.end ──────────────────►│
      │         (reason)                       │
      │                                        │
      │◄─────── session.ended ────────────────│
      │         (duration, statistics)         │
      │                                        │
      │──────── WebSocket Close ──────────────►│
```

## Mensagens do Protocolo

### protocol.capabilities (Server → Client)

Enviada automaticamente pelo servidor após conexão WebSocket.

```json
{
  "type": "protocol.capabilities",
  "version": "1.0.0",
  "server_id": "ai-agent-01",
  "capabilities": {
    "version": "1.0.0",
    "supported_sample_rates": [8000, 16000],
    "supported_encodings": ["pcm_s16le", "mulaw", "alaw"],
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

### session.start (Client → Server)

Inicia sessão com configuração desejada.

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
    "caller_number": "+5511999999999"
  },
  "timestamp": "2024-01-15T10:30:01.000Z"
}
```

### session.started (Server → Client)

Confirma ou rejeita a sessão.

**Aceita:**
```json
{
  "type": "session.started",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "accepted",
  "negotiated": {
    "audio": { "sample_rate": 8000, "encoding": "pcm_s16le", ... },
    "vad": { "silence_threshold_ms": 500, ... },
    "adjustments": []
  },
  "timestamp": "2024-01-15T10:30:01.100Z"
}
```

**Aceita com ajustes:**
```json
{
  "type": "session.started",
  "session_id": "...",
  "status": "accepted_with_changes",
  "negotiated": {
    "audio": { ... },
    "vad": { "threshold": 0.1, ... },
    "adjustments": [
      {
        "field": "vad.threshold",
        "requested": 0.05,
        "applied": 0.1,
        "reason": "Value below minimum (0.1)"
      }
    ]
  }
}
```

**Rejeitada:**
```json
{
  "type": "session.started",
  "session_id": "...",
  "status": "rejected",
  "errors": [
    {
      "code": 2001,
      "category": "audio",
      "message": "Sample rate 44100Hz not supported",
      "details": { "requested": 44100, "supported": [8000, 16000] },
      "recoverable": true
    }
  ]
}
```

## Configurações

### AudioConfig

| Campo | Tipo | Default | Valores Válidos |
|-------|------|---------|-----------------|
| `sample_rate` | int | 8000 | 8000, 16000, 24000, 48000 |
| `encoding` | string | "pcm_s16le" | "pcm_s16le", "mulaw", "alaw" |
| `channels` | int | 1 | 1 (mono apenas) |
| `frame_duration_ms` | int | 20 | 10, 20, 30 |

### VADConfig

| Campo | Tipo | Default | Range | Descrição |
|-------|------|---------|-------|-----------|
| `enabled` | bool | true | - | Se VAD está ativo |
| `silence_threshold_ms` | int | 500 | 100-2000 | Silêncio para fim de fala |
| `min_speech_ms` | int | 250 | 100-1000 | Duração mínima de fala |
| `threshold` | float | 0.5 | 0.0-1.0 | Sensibilidade |
| `ring_buffer_frames` | int | 5 | 3-10 | Frames para suavização |
| `speech_ratio` | float | 0.4 | 0.2-0.8 | Proporção mínima de fala |
| `prefix_padding_ms` | int | 300 | 0-500 | Áudio antes da fala |

### Valores Recomendados por Ambiente

**Ambiente silencioso (escritório):**
```json
{
  "silence_threshold_ms": 500,
  "min_speech_ms": 200,
  "threshold": 0.4,
  "speech_ratio": 0.3
}
```

**Ambiente ruidoso (call center):**
```json
{
  "silence_threshold_ms": 700,
  "min_speech_ms": 300,
  "threshold": 0.6,
  "speech_ratio": 0.5
}
```

## Códigos de Erro

| Código | Categoria | Mensagem | Recuperável |
|--------|-----------|----------|-------------|
| 1001 | protocol | invalid_message_format | Sim |
| 1002 | protocol | handshake_timeout | Não |
| 1003 | protocol | invalid_message_type | Sim |
| 1004 | protocol | version_mismatch | Não |
| 2001 | audio | unsupported_sample_rate | Sim |
| 2002 | audio | unsupported_encoding | Sim |
| 3001 | vad | invalid_vad_parameter | Sim |
| 3002 | vad | vad_not_configurable | Sim |
| 4001 | session | session_not_found | Sim |
| 4002 | session | session_expired | Não |

## Backwards Compatibility

O protocolo mantém compatibilidade com clientes e servidores legados:

### Cliente Legado
Se o servidor não receber `session.start` ASP em 5 segundos:
- Usa configuração default
- Marca sessão como `legacy_mode: true`
- Log de warning

### Servidor Legado
Se o cliente não receber `protocol.capabilities` em 5 segundos:
- Assume servidor legado
- Envia `session.start` no formato antigo
- Usa configuração default

## Métricas

O ASP expõe métricas Prometheus:

| Métrica | Tipo | Descrição |
|---------|------|-----------|
| `ai_agent_asp_handshake_duration_seconds` | Histogram | Duração do handshake |
| `ai_agent_asp_handshake_success_total` | Counter | Handshakes bem-sucedidos |
| `ai_agent_asp_handshake_failure_total` | Counter | Falhas por categoria |
| `ai_agent_asp_negotiation_adjustments_total` | Counter | Ajustes por campo |
| `ai_agent_asp_config_value` | Gauge | Valores de config ativos |

## Ferramenta de Debug

Use `tools/asp_debug.py` para testar o handshake:

```bash
# Handshake básico
python tools/asp_debug.py ws://localhost:8765

# Com config customizada
python tools/asp_debug.py ws://localhost:8765 --vad-silence 700

# Output JSON
python tools/asp_debug.py ws://localhost:8765 --json
```
