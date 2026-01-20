# SIP Server Module

**Responsabilidade:** Gerenciar signaling SIP (INVITE, ACK, BYE, etc.)

---

## 🎯 O Que Este Módulo Faz

O módulo SIP Server é responsável por:

1. ✅ Aceitar chamadas SIP INVITE de qualquer endpoint
2. ✅ Autenticação Digest (RFC 2617)
3. ✅ Negociação SDP (Session Description Protocol)
4. ✅ Gerenciar estado de chamadas (ringing → active → hangup)
5. ✅ Emitir eventos para outros módulos via EventBus

---

## 📦 Arquivos

```
sip/
├── README.md           # Este arquivo
├── __init__.py         # Exports públicos
├── server.py           # SIPServer class (main)
├── session.py          # CallSession dataclass
├── auth.py             # DigestAuth implementation
├── sdp.py              # SDP parser/generator
├── protocol.py         # SIP protocol utilities
└── events.py           # Event definitions
```

---

## 🔌 Interface Pública

### SIPServer

```python
from src.sip import SIPServer
from src.orchestrator.events import EventBus

# Criar servidor SIP
event_bus = EventBus()
sip_server = SIPServer(
    host='0.0.0.0',
    port=5060,
    realm='voiceagent',
    event_bus=event_bus
)

# Registrar callbacks
async def on_call_established(event):
    session = event.data['session']
    print(f"Call established: {session.session_id}")

event_bus.subscribe(EventType.CALL_ESTABLISHED, on_call_established)

# Iniciar servidor
await sip_server.start()
```

---

## 📤 Eventos Emitidos

### CALL_INVITE_RECEIVED

Emitido quando INVITE é recebido (antes de aceitar).

```python
{
    'type': EventType.CALL_INVITE_RECEIVED,
    'data': {
        'caller_id': '+5511999999999',
        'called_number': '+5511888888888',
        'sdp_offer': 'v=0\no=...'
    }
}
```

### CALL_ESTABLISHED

Emitido quando chamada é aceita (200 OK enviado).

```python
{
    'type': EventType.CALL_ESTABLISHED,
    'data': {
        'session': CallSession(
            session_id='abc-123',
            remote_ip='192.168.1.100',
            remote_port=10000,
            codec='PCMU',
            status=CallStatus.ACTIVE,
            local_port=20000
        )
    }
}
```

### CALL_ENDED

Emitido quando BYE é recebido ou enviado.

```python
{
    'type': EventType.CALL_ENDED,
    'data': {
        'session_id': 'abc-123',
        'reason': 'user_hangup',
        'duration': 45.2  # segundos
    }
}
```

---

## 🔐 Autenticação

### Digest Authentication (RFC 2617)

```python
# Configurar trunks autorizados
sip_server.add_trunk(
    username='carrier_abc',
    password='secret123',
    trunk_id='trunk-001'
)

# Fluxo de autenticação:
# 1. Client envia INVITE sem auth
# 2. Server responde 401 Unauthorized + nonce
# 3. Client envia INVITE com Authorization header
# 4. Server valida digest response
# 5. Se válido → 200 OK, senão → 403 Forbidden
```

### IP-based Authentication

```python
# Permitir IPs específicos sem senha
sip_server.allow_ip_range('203.0.113.0/24', trunk_id='trunk-002')

# Chamadas desse range são aceitas automaticamente
```

---

## 📋 CallSession

Estrutura de dados compartilhada com RTP Server.

```python
@dataclass(frozen=True)
class CallSession:
    """
    Contrato entre SIP Server e RTP Server
    """
    session_id: str              # UUID único
    remote_ip: str               # IP do endpoint remoto (extraído do SDP)
    remote_port: int             # Porta RTP remota (extraído do SDP)
    codec: str                   # Codec negociado (PCMU, PCMA, opus)
    status: CallStatus           # RINGING | ACTIVE | HANGUP
    local_port: int              # Porta RTP local alocada

    # Metadata
    caller_id: Optional[str] = None
    trunk_id: Optional[str] = None
    remote_sdp: str = ''         # SDP completo (para debug)
```

---

## 🧪 Testes

### Teste Unitário

```python
# tests/unit/test_sip_server.py
import pytest
from src.sip import SIPServer
from src.orchestrator.events import EventBus, EventType

@pytest.mark.asyncio
async def test_sip_accepts_invite():
    """Test: SIP server aceita INVITE válido"""

    event_bus = EventBus()
    events = []

    def capture(event):
        events.append(event)

    event_bus.subscribe(EventType.CALL_ESTABLISHED, capture)

    sip = SIPServer(host='127.0.0.1', port=5060, event_bus=event_bus)
    await sip.start()

    # Simular INVITE (via pjsua client)
    # ...

    # Assert
    assert len(events) == 1
    assert events[0].type == EventType.CALL_ESTABLISHED

    await sip.stop()
```

### Teste com Softphone Real

```bash
# 1. Iniciar servidor
python src/main.py

# 2. Configurar softphone (Zoiper/Linphone)
# Domínio: <server_ip>:5060
# Usuário: test_user
# Senha: test_pass

# 3. Fazer chamada
# sip:agent@<server_ip>:5060

# 4. Verificar logs
tail -f logs/sip.log
# Deve ver: "Call established: session_id=..."
```

---

## 🐛 Debug

### Habilitar SIP logs detalhados

```python
# src/sip/server.py
import logging

logging.getLogger('sip').setLevel(logging.DEBUG)
```

### Capturar pacotes SIP

```bash
# Capturar INVITE/200 OK/ACK/BYE
sudo tcpdump -i any -n -A port 5060

# Salvar em arquivo
sudo tcpdump -i any -w sip_capture.pcap port 5060

# Analisar com Wireshark
wireshark sip_capture.pcap
```

### Logs estruturados

```json
{
  "module": "sip.server",
  "level": "INFO",
  "message": "INVITE received",
  "caller_id": "+5511999999999",
  "cseq": 1,
  "has_auth": false
}

{
  "module": "sip.server",
  "level": "INFO",
  "message": "Call established",
  "session_id": "abc-123",
  "codec_negotiated": "PCMU",
  "remote_endpoint": "192.168.1.100:10000"
}
```

---

## ⚙️ Configuração

### config/default.yaml

```yaml
sip:
  # Endereço e porta do servidor
  host: 0.0.0.0
  port: 5060

  # Realm para autenticação digest
  realm: voiceagent

  # Máximo de chamadas simultâneas
  max_concurrent_calls: 100

  # Timeout de ringing (segundos)
  ringing_timeout: 60

  # Trunks autorizados
  trunks:
    - username: carrier_abc
      password: secret123
      trunk_id: trunk-001

    - username: carrier_xyz
      password: secret456
      trunk_id: trunk-002

  # Ranges de IP autorizados (sem senha)
  ip_whitelist:
    - 203.0.113.0/24  # Carrier ABC
    - 198.51.100.0/24 # Carrier XYZ
```

---

## 📊 Métricas

### Prometheus Metrics

```python
# Total de chamadas
sip_calls_total{status="accepted"} 1234
sip_calls_total{status="rejected"} 56

# Tentativas de autenticação
sip_auth_attempts_total{result="success"} 890
sip_auth_attempts_total{result="failed"} 34

# Chamadas ativas
sip_active_calls 12

# Duração média
sip_call_duration_seconds{quantile="0.5"} 45.2
sip_call_duration_seconds{quantile="0.95"} 180.3
```

Endpoint: `http://localhost:8000/metrics`

---

## 🔧 Troubleshooting

### Problema: INVITE recebido mas 200 OK não é enviado

**Causa provável:** Falha na autenticação ou SDP parsing

**Debug:**
```bash
# Verificar logs
grep "Authentication failed" logs/sip.log

# Verificar SDP
grep "SDP parsing error" logs/sip.log
```

**Solução:**
- Verificar credenciais no config
- Validar formato do SDP (c=, m=, a= lines)

---

### Problema: 200 OK enviado mas ACK não é recebido

**Causa provável:** Problema de rede (NAT/Firewall)

**Debug:**
```bash
# Verificar se ACK está chegando
sudo tcpdump -i any -n -A port 5060 | grep ACK
```

**Solução:**
- Configurar STUN/TURN se atrás de NAT
- Abrir porta 5060 no firewall

---

### Problema: Codec não suportado

**Causa provável:** Client oferece apenas codecs que não suportamos

**Debug:**
```bash
# Ver codecs oferecidos
grep "SDP offer" logs/sip.log

# Ver codec negociado
grep "codec negotiated" logs/sip.log
```

**Solução:**
- Adicionar codec ao RTP Server
- Atualizar codec_priority no config

---

## 🎓 Lições do LiveKit SIP

### 1. AUDIO_BRIDGE_MAX_DELAY = 1s

```python
# Aguardar 1s antes de enviar áudio inicial
# Evita cutoff de áudio no início da chamada
# Observado em produção (battle-tested)

AUDIO_BRIDGE_MAX_DELAY = 1.0  # segundos
```

### 2. Retry de 200 OK

```python
# SIP sobre UDP perde pacotes
# DEVE reenviar 200 OK até receber ACK

INVITE_OK_RETRY_INTERVAL = 0.25  # 250ms (1/2 de T1)
INVITE_OK_RETRY_ATTEMPTS = 5
```

### 3. Diferença entre DROP e REJECT

```python
class AuthResult(Enum):
    DROP = 1    # Ignora silenciosamente (sem resposta)
    REJECT = 2  # Responde 403 Forbidden

# Use DROP para IPs suspeitos (evita flood)
# Use REJECT para autenticação falha (user feedback)
```

---

## 📚 Referências

- **RFC 3261**: SIP - Session Initiation Protocol
- **RFC 2617**: HTTP Digest Authentication
- **RFC 4566**: SDP - Session Description Protocol
- **PJSIP Docs**: https://docs.pjsip.org/

---

## ✅ Checklist de Implementação

- [ ] `server.py` - SIPServer class
- [ ] `session.py` - CallSession dataclass
- [ ] `auth.py` - Digest authentication
- [ ] `sdp.py` - SDP parser
- [ ] `protocol.py` - SIP utilities
- [ ] `events.py` - Event definitions
- [ ] Testes unitários (>90% coverage)
- [ ] Testes com softphone real
- [ ] Documentação de API
- [ ] Métricas Prometheus

---

**Status:** 🚧 Em implementação
**Owner:** Time de Voice Engineering
