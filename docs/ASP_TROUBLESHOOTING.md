# ASP Troubleshooting Guide

Guia para diagnóstico e resolução de problemas com o Audio Session Protocol.

## Ferramenta de Debug

Use `asp_debug.py` para diagnóstico rápido:

```bash
# Teste básico de conectividade e handshake
python tools/asp_debug.py ws://localhost:8765

# Saída JSON para scripts
python tools/asp_debug.py ws://localhost:8765 --json

# Teste com config específica
python tools/asp_debug.py ws://localhost:8765 --vad-silence 700 --vad-threshold 0.6
```

## Problemas Comuns

### 1. Timeout ao conectar

**Sintoma:**
```
❌ Timeout waiting for server response
```

**Causas:**
- Servidor não está rodando
- Porta incorreta
- Firewall bloqueando conexão

**Solução:**
```bash
# Verificar se servidor está rodando
docker ps | grep ai-agent

# Verificar porta
netstat -tlnp | grep 8765

# Testar conectividade
nc -zv localhost 8765
```

### 2. Servidor não envia capabilities

**Sintoma:**
```
📜 Modo legado (servidor sem ASP)
```

**Causas:**
- Servidor não implementa ASP
- ASP handler não está configurado

**Solução:**
Verificar se o servidor está enviando capabilities:
```python
# No servidor, após conexão WebSocket
await self._asp_handler.send_capabilities(websocket)
```

### 3. Sessão rejeitada por sample rate

**Sintoma:**
```json
{
  "code": 2001,
  "message": "Sample rate 44100Hz not supported"
}
```

**Causa:**
Cliente solicitou sample rate não suportado pelo servidor.

**Solução:**
Use um sample rate suportado:
```bash
python tools/asp_debug.py ws://localhost:8765 --sample-rate 8000
```

### 4. VAD não detecta fala

**Sintomas:**
- Usuário fala mas `audio.end` nunca é enviado
- Áudio não chega ao pipeline

**Causas possíveis:**
1. `threshold` muito alto
2. `min_speech_ms` muito alto
3. `silence_threshold_ms` muito baixo

**Diagnóstico:**
```bash
# Verificar config negociada
python tools/asp_debug.py ws://localhost:8765 --json | jq '.negotiated.vad'
```

**Solução:**
Ajuste os parâmetros VAD:
```bash
# Para ambiente ruidoso
python tools/asp_debug.py ws://localhost:8765 \
  --vad-threshold 0.6 \
  --vad-silence 700 \
  --vad-min-speech 300
```

### 5. Fala cortada prematuramente

**Sintoma:**
- Frases são interrompidas no meio
- VAD detecta fim de fala durante pausas naturais

**Causa:**
`silence_threshold_ms` muito baixo

**Solução:**
Aumente o threshold de silêncio:
```python
vad = VADConfig(
    silence_threshold_ms=700,  # Era 300
    min_speech_ms=250
)
```

### 6. Configuração não aplicada

**Sintoma:**
- Sessão aceita mas comportamento não muda
- Logs mostram valores antigos

**Diagnóstico:**
```bash
# Verificar métricas
curl http://localhost:9090/metrics | grep asp_config
```

**Causa:**
Config negociada não está sendo aplicada ao VAD interno.

**Solução:**
Após receber `session.started`, aplicar config:
```python
if response.is_accepted:
    vad_config = response.negotiated.vad
    session.audio_buffer.silence_threshold = vad_config.silence_threshold_ms
    session.audio_buffer.min_speech_ms = vad_config.min_speech_ms
```

### 7. Ajustes inesperados

**Sintoma:**
```
⚠️ Ajuste: vad.threshold: 0.05 → 0.1 (Value below minimum)
```

**Causa:**
Valor solicitado está fora do range válido.

**Solução:**
Consulte os ranges válidos na especificação:

| Parâmetro | Min | Max |
|-----------|-----|-----|
| silence_threshold_ms | 100 | 2000 |
| min_speech_ms | 100 | 1000 |
| threshold | 0.0 | 1.0 |
| ring_buffer_frames | 3 | 10 |
| speech_ratio | 0.2 | 0.8 |

### 8. Handshake muito lento

**Sintoma:**
```
⏱️  Total time: 2500ms
```

**Diagnóstico:**
```bash
# Verificar breakdown de tempo
python tools/asp_debug.py ws://localhost:8765 --json | jq '.timings'
```

**Causas possíveis:**
- Latência de rede
- Servidor sobrecarregado
- DNS lento

**Solução:**
```bash
# Verificar latência de rede
ping ai-agent

# Verificar métricas do servidor
curl http://ai-agent:9090/metrics | grep handshake
```

## Logs

### Habilitar logs de debug

```python
import logging
logging.getLogger("asp").setLevel(logging.DEBUG)
```

### Logs importantes

**Servidor (AI Agent):**
```
📞 ASP session.start: 550e8400 (call: sip-123)
✅ Sessão ASP aceita: 550e8400 (status=accepted)
   VAD config aplicada: silence=500ms, min_speech=250ms
```

**Cliente (Media Server):**
```
📥 Recebido capabilities v1.0.0
📤 Enviado session.start: 550e8400
✅ Sessão ASP aceita: 550e8400 (status=accepted)
   Config negociada: sample_rate=8000, vad.silence=500ms
```

### Formato de log estruturado

Para integração com sistemas de log:
```python
logger.info(
    "asp_handshake_complete",
    extra={
        "session_id": session_id,
        "status": result.status.value,
        "duration_ms": duration * 1000,
        "adjustments": len(result.negotiated.adjustments)
    }
)
```

## Métricas

### Dashboard de Handshake

```promql
# Taxa de sucesso de handshake
sum(rate(ai_agent_asp_handshake_success_total[5m])) /
sum(rate(ai_agent_asp_handshake_success_total[5m]) +
    rate(ai_agent_asp_handshake_failure_total[5m]))

# Latência P95 de handshake
histogram_quantile(0.95,
  rate(ai_agent_asp_handshake_duration_seconds_bucket[5m]))

# Ajustes por campo
topk(5, sum by (field) (rate(ai_agent_asp_negotiation_adjustments_total[1h])))
```

### Alertas sugeridos

```yaml
groups:
- name: asp
  rules:
  - alert: ASPHandshakeFailureHigh
    expr: |
      sum(rate(ai_agent_asp_handshake_failure_total[5m])) /
      sum(rate(ai_agent_asp_handshake_success_total[5m]) +
          rate(ai_agent_asp_handshake_failure_total[5m])) > 0.1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High ASP handshake failure rate (>10%)"

  - alert: ASPHandshakeLatencyHigh
    expr: |
      histogram_quantile(0.95,
        rate(ai_agent_asp_handshake_duration_seconds_bucket[5m])) > 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "ASP handshake P95 latency > 1s"
```

## FAQ

### Q: O que acontece se o servidor não suportar ASP?

**R:** O cliente detecta ausência de capabilities (timeout de 5s) e entra em modo legado, usando configuração default.

### Q: Posso mudar a configuração de áudio mid-session?

**R:** Não. Apenas a configuração de VAD pode ser atualizada via `session.update`. Para mudar áudio, inicie uma nova sessão.

### Q: Como sei se estou em modo ASP ou legado?

**Cliente:**
```python
if client.is_asp_mode:
    print("Modo ASP")
else:
    print("Modo legado")
```

**Logs:**
```
🔒 Modo ASP ativado (server v1.0.0)
# ou
📜 Modo legado (servidor sem ASP)
```

### Q: Por que meu threshold foi ajustado de 0.05 para 0.1?

**R:** O range válido de threshold é 0.0-1.0, mas valores muito baixos (<0.1) causam falsos positivos. O servidor ajusta automaticamente para o mínimo recomendado.

### Q: Como testar se a negociação está funcionando?

```bash
# Teste com valor inválido para forçar ajuste
python tools/asp_debug.py ws://localhost:8765 --vad-threshold 1.5

# Deve mostrar:
# status: accepted_with_changes
# Ajuste: vad.threshold: 1.5 → 1.0
```

## Suporte

Para problemas não cobertos neste guia:

1. Verifique os logs com nível DEBUG
2. Execute `asp_debug.py` com `--json`
3. Colete métricas do endpoint `/metrics`
4. Abra issue com os dados coletados
