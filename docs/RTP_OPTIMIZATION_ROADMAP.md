# RTP Server Optimization - Implementation Roadmap

**Project:** AI Voice Agent - Theo
**Component:** RTP Layer Optimization
**Created:** 2026-01-21
**Status:** Planning Phase
**Test Method:** Manual call to extension 100 after each implementation

---

## 🎯 Objetivo Geral

Implementar todas as otimizações críticas do RTP Server mantendo o sistema funcionando em produção. Cada microtask será testada individualmente ligando para o ramal 100 e validando que o agente continua respondendo corretamente.

---

## 📊 Visão Geral do Roadmap

```
PHASE 1: Security & Session Management (Week 1)
├── EPIC-001: IP Access Control & Validation
├── EPIC-002: Session Limits & Resource Management
└── EPIC-003: RTP Hijacking Protection

PHASE 2: Audio Quality (Week 2-3)
├── EPIC-004: Adaptive Jitter Buffer
├── EPIC-005: Packet Loss Detection & Concealment
└── EPIC-006: Sequence Number Validation

PHASE 3: Performance & Monitoring (Week 4)
├── EPIC-007: DatagramProtocol Migration
├── EPIC-008: RTCP Implementation
└── EPIC-009: Circuit Breaker & Error Recovery

PHASE 4: Advanced Features (Week 5+)
├── EPIC-010: DTMF Detection (RFC 2833)
├── EPIC-011: Queue Optimization
└── EPIC-012: Metrics & Monitoring Dashboard
```

---

# PHASE 1: Security & Session Management

**Duration:** Week 1 (5 dias úteis)
**Priority:** 🔴 CRITICAL
**Goal:** Proteger o sistema contra ataques e limitar recursos

---

## EPIC-001: IP Access Control & Validation

**Owner:** Backend Team
**Priority:** 🔴 CRITICAL
**Estimated Effort:** 1 day
**Dependencies:** None

### Context
Atualmente o rate limiter tem whitelist/blacklist, mas o RTP Connection não valida IP de origem. Precisamos integrar ACL no RTP layer.

### Microtasks

#### Task 1.1: Add IP Validation to RTP Connection
**Effort:** 2 hours

**Implementation:**
```python
# src/rtp/connection.py

class RTPConnection:
    def __init__(self, config: Optional[RTPConnectionConfig] = None):
        # ... existing init ...

        # Add expected remote IP (from SIP SDP)
        self.expected_remote_ip: Optional[str] = None
        self.ip_validation_enabled: bool = True

    def set_expected_remote_ip(self, ip: str):
        """Set expected remote IP from SIP SDP"""
        self.expected_remote_ip = ip
        logger.info("Expected remote IP set", ip=ip)

    def _validate_remote_ip(self, addr: Tuple[str, int]) -> bool:
        """Validate if packet is from expected source"""
        if not self.ip_validation_enabled:
            return True

        if not self.expected_remote_ip:
            # First packet - accept but log warning
            logger.warn("No expected IP set - accepting first packet",
                       remote_ip=addr[0])
            return True

        if addr[0] != self.expected_remote_ip:
            logger.error("🚨 RTP HIJACKING ATTEMPT DETECTED",
                        expected_ip=self.expected_remote_ip,
                        actual_ip=addr[0],
                        action="PACKET_DROPPED")
            return False

        return True
```

**DoD (Definition of Done):**
- [ ] Código implementado em `src/rtp/connection.py`
- [ ] Método `set_expected_remote_ip()` chamado no SIP INVITE handler
- [ ] Método `_validate_remote_ip()` chamado antes de processar cada packet
- [ ] Log de erro emitido quando IP diferente tenta enviar RTP
- [ ] **TESTE MANUAL**: Ligar para ramal 100, agente atende e responde normalmente
- [ ] **TESTE MANUAL**: Verificar logs que IP correto foi validado
- [ ] Sem regressões: chamada completa funciona (SIP + RTP + AI)

---

#### Task 1.2: Integrate SDP IP into RTP Session
**Effort:** 1 hour

**Implementation:**
```python
# src/sip/server.py - Método _handle_invite()

# Após criar RTP session:
rtp_session = await self.rtp_server.create_session(
    session_id=call_id,
    remote_ip=remote_ip,
    remote_port=remote_port
)

# Adicionar IP esperado
rtp_session.connection.set_expected_remote_ip(remote_ip)
```

**DoD:**
- [ ] SDP parser extrai IP corretamente
- [ ] IP é passado para `RTPConnection.set_expected_remote_ip()`
- [ ] **TESTE MANUAL**: Ligar para 100, verificar log mostra "Expected remote IP set"
- [ ] **TESTE MANUAL**: Agente responde normalmente

---

#### Task 1.3: Add Config Flag for IP Validation
**Effort:** 30 min

**Implementation:**
```yaml
# config/default.yaml

rtp:
  # ... existing config ...

  # Security
  ip_validation_enabled: true  # Set to false to disable (testing only)
```

**DoD:**
- [ ] Config YAML atualizado
- [ ] Config carregado em `RTPConnectionConfig`
- [ ] Flag usado em `_validate_remote_ip()`
- [ ] **TESTE MANUAL**: Com flag=true, chamada funciona
- [ ] **TESTE MANUAL**: Com flag=false, chamada funciona (sem validação)

---

#### Task 1.4: Add Metrics for IP Validation
**Effort:** 30 min

**Implementation:**
```python
# src/rtp/connection.py

class RTPConnectionStats:
    def __init__(self):
        self.packets_accepted = 0
        self.packets_rejected_invalid_ip = 0
        self.hijacking_attempts = 0

def _validate_remote_ip(self, addr: Tuple[str, int]) -> bool:
    if not valid:
        self.stats.packets_rejected_invalid_ip += 1
        self.stats.hijacking_attempts += 1
        return False

    self.stats.packets_accepted += 1
    return True
```

**DoD:**
- [ ] Stats class implementada
- [ ] Métricas incrementadas corretamente
- [ ] `get_stats()` retorna métricas
- [ ] **TESTE MANUAL**: Ligar para 100, verificar stats.packets_accepted > 0
- [ ] Stats aparecem em logs de debug

---

### EPIC-001 Final DoD

**Acceptance Criteria:**
- [x] IP validation implementado e funcionando
- [x] Config flag permite disable (testing)
- [x] Métricas de segurança coletadas
- [x] **TESTE FINAL**: Ligar para ramal 100
  - [ ] Agente atende
  - [ ] Áudio funciona (consegue ouvir o agente)
  - [ ] Consegue falar e agente responde
  - [ ] Logs mostram IP validation passou
  - [ ] Stats mostram packets_accepted > 0, packets_rejected = 0
- [x] Documentação atualizada
- [x] Code review aprovado

---

## EPIC-002: Session Limits & Resource Management

**Owner:** Backend Team
**Priority:** 🔴 CRITICAL
**Estimated Effort:** 1 day
**Dependencies:** None

### Context
Config define `max_concurrent_calls: 100` mas não é enforced. Precisamos limitar sessões para proteger recursos do servidor.

### Microtasks

#### Task 2.1: Add Session Counter to SIP Server
**Effort:** 1 hour

**Implementation:**
```python
# src/sip/server.py

class SIPServer:
    def __init__(self, config: SIPServerConfig, ...):
        # ... existing init ...

        # Session tracking
        self.active_sessions: Dict[str, Any] = {}
        self.max_concurrent_calls = config.max_concurrent_calls

    def _can_accept_call(self) -> Tuple[bool, Optional[str]]:
        """Check if we can accept a new call"""
        current_sessions = len(self.active_sessions)

        if current_sessions >= self.max_concurrent_calls:
            logger.warn("🚫 Max concurrent calls reached",
                       current=current_sessions,
                       max=self.max_concurrent_calls)
            return False, "Service Unavailable - Max Sessions Reached"

        return True, None
```

**DoD:**
- [ ] Método `_can_accept_call()` implementado
- [ ] Contador `active_sessions` atualizado em INVITE/BYE
- [ ] Log de warning quando limite atingido
- [ ] **TESTE MANUAL**: Ligar para 100, agente atende (sessions < max)
- [ ] **TESTE MANUAL**: Verificar log mostra session count

---

#### Task 2.2: Reject INVITE When Max Sessions Reached
**Effort:** 1 hour

**Implementation:**
```python
# src/sip/server.py - _handle_invite()

async def _handle_invite(self, message: SIPMessage, addr: tuple):
    # ... existing code ...

    # Check session limits BEFORE authentication
    can_accept, reason = self._can_accept_call()
    if not can_accept:
        await self._send_response(
            message, addr,
            SIPStatus.SERVICE_UNAVAILABLE,
            reason
        )
        return

    # Continue with authentication, rate limiting, etc...
```

**DoD:**
- [ ] Check de session limit antes de autenticar
- [ ] Resposta `503 Service Unavailable` enviada quando limite atingido
- [ ] **TESTE MANUAL**: Com 1 sessão ativa, segunda chamada para 100 funciona
- [ ] **TESTE MANUAL**: (Futuro) Com max_concurrent_calls=1, segunda chamada recebe 503

---

#### Task 2.3: Track Sessions in RTP Server
**Effort:** 30 min

**Implementation:**
```python
# src/rtp/server.py

class RTPServer:
    async def create_session(...):
        # Check if at capacity
        if len(self.sessions) >= MAX_RTP_SESSIONS:
            raise RuntimeError("Max RTP sessions reached")

        # ... create session ...

        logger.info("RTP session created",
                   session_id=session_id,
                   active_sessions=len(self.sessions),
                   max_sessions=MAX_RTP_SESSIONS)
```

**DoD:**
- [ ] RTP Server também limita sessões
- [ ] Log mostra contagem de sessões ativas
- [ ] **TESTE MANUAL**: Ligar para 100, verificar log mostra active_sessions=1
- [ ] Exception lançada se RTP limit atingido

---

#### Task 2.4: Add Session Cleanup on Timeout
**Effort:** 1 hour

**Implementation:**
```python
# src/sip/server.py

async def _cleanup_stale_sessions(self):
    """Cleanup sessions that exceeded timeout"""
    while self.running:
        await asyncio.sleep(60)  # Check every minute

        now = time.time()
        stale_sessions = []

        for session_id, session in self.active_sessions.items():
            age_seconds = now - session.created_at

            if age_seconds > self.config.session_timeout_seconds:
                logger.warn("Session timeout - cleaning up",
                           session_id=session_id,
                           age_seconds=age_seconds)
                stale_sessions.append(session_id)

        # Cleanup stale sessions
        for session_id in stale_sessions:
            await self._end_session(session_id, reason="TIMEOUT")

async def start(self):
    # ... existing code ...

    # Start cleanup task
    asyncio.create_task(self._cleanup_stale_sessions())
```

**DoD:**
- [ ] Cleanup task implementado
- [ ] Config `session_timeout_seconds` adicionado (default: 3600s = 1h)
- [ ] Sessões antigas são removidas automaticamente
- [ ] **TESTE MANUAL**: Ligar para 100, desligar, verificar session foi removida
- [ ] Log mostra cleanup de sessões antigas (se houver)

---

#### Task 2.5: Add Session Metrics
**Effort:** 30 min

**Implementation:**
```python
# src/sip/server.py

class SIPServerStats:
    def __init__(self):
        self.total_sessions_created = 0
        self.total_sessions_rejected_limit = 0
        self.total_sessions_timeout = 0
        self.current_active_sessions = 0
        self.peak_concurrent_sessions = 0
```

**DoD:**
- [ ] Métricas de sessão implementadas
- [ ] `peak_concurrent_sessions` rastreado
- [ ] **TESTE MANUAL**: Ligar para 100, stats.total_sessions_created == 1
- [ ] Stats disponíveis via `/metrics` endpoint

---

### EPIC-002 Final DoD

**Acceptance Criteria:**
- [x] Session limits enforced em SIP e RTP layers
- [x] 503 Service Unavailable quando limite atingido
- [x] Cleanup automático de sessões antigas
- [x] Métricas de sessão coletadas
- [x] **TESTE FINAL**: Ligar para ramal 100
  - [ ] Agente atende normalmente
  - [ ] Logs mostram "active_sessions=1"
  - [ ] Após desligar, session é removida
  - [ ] Logs mostram "active_sessions=0"
- [x] **TESTE STRESS**: (Opcional) Fazer 5 chamadas simultâneas
  - [ ] Todas atendem se < max_concurrent_calls
  - [ ] Rejeitadas com 503 se >= max_concurrent_calls
- [x] Code review aprovado

---

## EPIC-003: RTP Hijacking Protection

**Owner:** Backend Team
**Priority:** 🔴 CRITICAL
**Estimated Effort:** 1 day
**Dependencies:** EPIC-001 (IP Validation)

### Context
Além de validar IP, precisamos validar SSRC para evitar session hijacking onde atacante envia RTP com IP spoofed.

### Microtasks

#### Task 3.1: Add SSRC Tracking
**Effort:** 1 hour

**Implementation:**
```python
# src/rtp/connection.py

class RTPConnection:
    def __init__(self, config: Optional[RTPConnectionConfig] = None):
        # ... existing init ...

        # SSRC tracking
        self.expected_ssrc: Optional[int] = None
        self.ssrc_locked: bool = False

    def _validate_ssrc(self, header: RTPHeader) -> bool:
        """Validate SSRC to prevent hijacking"""

        # Lock SSRC on first valid packet
        if not self.ssrc_locked:
            self.expected_ssrc = header.ssrc
            self.ssrc_locked = True
            logger.info("SSRC locked",
                       ssrc=f"{header.ssrc:08x}")
            return True

        # Validate subsequent packets
        if header.ssrc != self.expected_ssrc:
            logger.error("🚨 SSRC MISMATCH - Possible hijacking attempt",
                        expected=f"{self.expected_ssrc:08x}",
                        actual=f"{header.ssrc:08x}",
                        action="PACKET_DROPPED")
            return False

        return True
```

**DoD:**
- [ ] SSRC validation implementado
- [ ] Primeiro packet válido "lock" o SSRC
- [ ] Packets com SSRC diferente são rejeitados
- [ ] **TESTE MANUAL**: Ligar para 100, verificar log "SSRC locked"
- [ ] **TESTE MANUAL**: Agente responde normalmente

---

#### Task 3.2: Integrate SSRC Validation in Packet Handler
**Effort:** 30 min

**Implementation:**
```python
# src/rtp/connection.py - _read_loop()

# Parse RTP packet
packet = RTPPacket.parse(data)

# Validate IP
if not self._validate_remote_ip(addr):
    self.stats.packets_rejected_invalid_ip += 1
    continue

# Validate SSRC
if not self._validate_ssrc(packet.header):
    self.stats.packets_rejected_invalid_ssrc += 1
    continue

# Packet is valid - process
self.on_rtp_callback(packet.header, packet.payload)
```

**DoD:**
- [ ] SSRC validation chamado para cada packet
- [ ] Stats `packets_rejected_invalid_ssrc` incrementado
- [ ] **TESTE MANUAL**: Ligar para 100, todos packets aceitos (SSRC válido)
- [ ] Sem regressões

---

#### Task 3.3: Add SSRC Reset on Session Restart
**Effort:** 30 min

**Implementation:**
```python
# src/rtp/connection.py

def reset_ssrc_lock(self):
    """Reset SSRC lock (e.g., on session restart)"""
    self.expected_ssrc = None
    self.ssrc_locked = False
    logger.info("SSRC lock reset")
```

**DoD:**
- [ ] Método `reset_ssrc_lock()` implementado
- [ ] Chamado quando session é reiniciada
- [ ] **TESTE MANUAL**: Fazer 2 chamadas seguidas para 100
  - [ ] Primeira chamada: SSRC locked
  - [ ] Segunda chamada: SSRC re-locked (novo valor OK)

---

### EPIC-003 Final DoD

**Acceptance Criteria:**
- [x] SSRC validation implementado
- [x] Primeiro packet válido "trava" SSRC esperado
- [x] Packets com SSRC diferente rejeitados
- [x] Métricas de hijacking tentativas coletadas
- [x] **TESTE FINAL**: Ligar para ramal 100
  - [ ] Agente atende
  - [ ] Log mostra "SSRC locked: 0xXXXXXXXX"
  - [ ] Áudio funciona perfeitamente
  - [ ] Stats: packets_rejected_invalid_ssrc == 0
- [x] Code review aprovado

---

# PHASE 2: Audio Quality

**Duration:** Week 2-3 (10 dias úteis)
**Priority:** 🟠 HIGH
**Goal:** Melhorar qualidade de áudio sob condições adversas de rede

---

## EPIC-004: Adaptive Jitter Buffer

**Owner:** Audio Team
**Priority:** 🟠 HIGH
**Estimated Effort:** 3 days
**Dependencies:** None

### Context
Implementar jitter buffer para reordenar packets, detectar loss, e adaptar buffer depth baseado em jitter observado.

### Microtasks

#### Task 4.1: Create JitterBuffer Class (Core Logic)
**Effort:** 4 hours

**Implementation:** (Ver código completo em ADR-001)

**DoD:**
- [ ] Arquivo `src/rtp/jitter_buffer.py` criado
- [ ] Classes implementadas:
  - [ ] `JitterBufferConfig`
  - [ ] `JitterBufferStats`
  - [ ] `AdaptiveJitterBuffer`
- [ ] Métodos implementados:
  - [ ] `push()` - adicionar packet
  - [ ] `pop()` - obter packet ordenado
  - [ ] `_update_jitter()` - calcular jitter (RFC 3550)
  - [ ] `_adapt_buffer_depth()` - ajustar buffer dinamicamente
- [ ] Unit tests criados (pytest)
- [ ] **TESTE UNITÁRIO**: Packets fora de ordem são reordenados
- [ ] **TESTE UNITÁRIO**: Packet loss é detectado

---

#### Task 4.2: Integrate JitterBuffer into RTPSession
**Effort:** 2 hours

**Implementation:**
```python
# src/rtp/server.py

from .jitter_buffer import AdaptiveJitterBuffer, JitterBufferConfig

class RTPSession:
    def __init__(self, session_id: str, connection: RTPConnection):
        # ... existing init ...

        # Add jitter buffer
        jb_config = JitterBufferConfig(
            initial_depth_ms=60,
            min_depth_ms=20,
            max_depth_ms=300
        )
        self.jitter_buffer = AdaptiveJitterBuffer(config=jb_config)

        # Playout task
        self.playout_task: Optional[asyncio.Task] = None

    def on_rtp_received(self, header: RTPHeader, payload: bytes):
        """Push packet to jitter buffer"""
        accepted = self.jitter_buffer.push(header, payload)

        if not accepted:
            logger.debug("Packet rejected",
                        seq=header.sequence_number,
                        reason="duplicate or late")
```

**DoD:**
- [ ] JitterBuffer integrado em RTPSession
- [ ] `on_rtp_received()` usa `jitter_buffer.push()`
- [ ] **TESTE MANUAL**: Ligar para 100, agente atende (sem regressão)
- [ ] Log mostra packets being pushed to jitter buffer

---

#### Task 4.3: Implement Playout Loop
**Effort:** 3 hours

**Implementation:**
```python
# src/rtp/server.py

async def _playout_loop(self):
    """Read from jitter buffer at regular intervals"""
    PACKET_DURATION_MS = 20  # 20ms per packet

    while self.running:
        try:
            # Get next packet
            result = await self.jitter_buffer.pop()

            if result:
                header, payload = result
                # Put in audio queue for AI processing
                try:
                    self.audio_in_queue.put_nowait((header, payload))
                except asyncio.QueueFull:
                    logger.warn("Audio queue full")
            else:
                # Packet lost (será tratado no EPIC-005)
                logger.debug("Packet loss detected")

            # Wait for next packet time
            await asyncio.sleep(PACKET_DURATION_MS / 1000.0)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Playout loop error", error=str(e))
```

**DoD:**
- [ ] Playout loop implementado
- [ ] Loop roda a 20ms intervals (50 packets/second)
- [ ] Packets são entregues ordenados para audio queue
- [ ] **TESTE MANUAL**: Ligar para 100
  - [ ] Agente atende
  - [ ] Áudio continua funcionando
  - [ ] Log mostra playout loop running

---

#### Task 4.4: Add Jitter Buffer Configuration to YAML
**Effort:** 30 min

**Implementation:**
```yaml
# config/default.yaml

rtp:
  # ... existing config ...

  # Jitter Buffer
  jitter_buffer:
    enabled: true
    initial_depth_ms: 60   # Start with 60ms
    min_depth_ms: 20       # Minimum (low latency)
    max_depth_ms: 300      # Maximum (high jitter tolerance)
    packet_duration_ms: 20 # 20ms per packet @ 8kHz
```

**DoD:**
- [ ] Config YAML atualizado
- [ ] Config carregado em `RTPServerConfig`
- [ ] Config passado para `JitterBuffer`
- [ ] **TESTE MANUAL**: Alterar `initial_depth_ms=100`, reiniciar, verificar stats

---

#### Task 4.5: Add Jitter Buffer Metrics & Logging
**Effort:** 1 hour

**Implementation:**
```python
# src/rtp/jitter_buffer.py - get_stats()

{
    'packets_received': 1234,
    'packets_lost': 5,
    'packets_out_of_order': 23,
    'packets_duplicate': 2,
    'current_depth_ms': 75,
    'avg_jitter_ms': 12.5,
    'max_jitter_ms': 45.2,
    'loss_rate': '0.40%'
}
```

**DoD:**
- [ ] Stats completos implementados
- [ ] `get_stats()` retorna todas métricas
- [ ] Stats incluídos em `RTPSession.get_stats()`
- [ ] **TESTE MANUAL**: Ligar para 100, verificar stats via logs
- [ ] Stats mostram jitter buffer funcionando

---

#### Task 4.6: Unit Tests for JitterBuffer
**Effort:** 2 hours

**Tests:**
```python
# tests/unit/test_jitter_buffer.py

def test_packet_reordering():
    """Packets 1,3,2 should be delivered as 1,2,3"""

def test_packet_loss_detection():
    """Gap in sequence (1,3) should detect loss of packet 2"""

def test_jitter_calculation():
    """Jitter should be calculated per RFC 3550"""

def test_buffer_adaptation():
    """Buffer depth should increase with higher jitter"""

def test_duplicate_rejection():
    """Duplicate packets should be rejected"""
```

**DoD:**
- [ ] Todos unit tests passando
- [ ] Coverage > 80% no jitter_buffer.py
- [ ] **TESTE**: `pytest tests/unit/test_jitter_buffer.py -v`

---

### EPIC-004 Final DoD

**Acceptance Criteria:**
- [x] JitterBuffer class completa e testada
- [x] Integrado em RTPSession com playout loop
- [x] Config YAML permite ajustes
- [x] Métricas detalhadas coletadas
- [x] Unit tests > 80% coverage
- [x] **TESTE FINAL**: Ligar para ramal 100
  - [ ] Agente atende
  - [ ] Áudio funciona perfeitamente
  - [ ] Log mostra "Jitter buffer initialized"
  - [ ] Stats mostram:
    - [ ] `packets_received > 0`
    - [ ] `current_depth_ms` adaptando (ex: começa 60ms, pode subir/descer)
    - [ ] `packets_out_of_order` detectados (se houver)
    - [ ] `avg_jitter_ms` calculado
- [x] **TESTE STRESS**: Simular jitter de rede (tc qdisc)
  - [ ] Buffer adapta profundidade
  - [ ] Áudio continua fluido
- [x] Code review aprovado

---

## EPIC-005: Packet Loss Detection & Concealment

**Owner:** Audio Team
**Priority:** 🟠 HIGH
**Estimated Effort:** 2 days
**Dependencies:** EPIC-004 (Jitter Buffer)

### Context
Quando jitter buffer detecta packet loss (gap de sequência), precisamos "esconder" a perda gerando áudio de substituição (PLC).

### Microtasks

#### Task 5.1: Create PacketLossConcealment Class
**Effort:** 3 hours

**Implementation:** (Ver código completo em ADR-002)

**DoD:**
- [ ] Arquivo `src/rtp/packet_loss_concealment.py` criado
- [ ] Classe `PacketLossConcealment` implementada
- [ ] Métodos implementados:
  - [ ] `conceal()` - gerar packet de substituição
  - [ ] `update_last_packet()` - armazenar referência
  - [ ] `_repeat_last_packet()` - Level 1 (0-3% loss)
  - [ ] `_fade_to_comfort_noise()` - Level 2 (3-10% loss)
  - [ ] `_generate_comfort_noise()` - Level 3 (>10% loss)
- [ ] Suporte a PCMU (μ-law) codec
- [ ] Unit tests criados

---

#### Task 5.2: Integrate PLC into JitterBuffer
**Effort:** 2 hours

**Implementation:**
```python
# src/rtp/jitter_buffer.py

from .packet_loss_concealment import PacketLossConcealment

class AdaptiveJitterBuffer:
    def __init__(self, config: Optional[JitterBufferConfig] = None):
        # ... existing init ...

        # Add PLC
        self.plc = PacketLossConcealment(codec="PCMU")

    async def pop(self) -> Optional[Tuple[RTPHeader, bytes]]:
        # ... existing code ...

        # If packet in buffer - return it
        if seq in self.buffer:
            header, payload, arrival_time = self.buffer.pop(seq)

            # Update PLC with good packet
            self.plc.update_last_packet(header, payload)

            return (header, payload)

        # Packet lost - generate concealment
        loss_rate = self.stats.packets_lost / max(1, self.stats.packets_received)
        header, payload = self.plc.conceal(seq, loss_rate)

        logger.debug("PLC inserted",
                    seq=seq,
                    loss_rate=f"{loss_rate*100:.2f}%",
                    level=self._get_plc_level(loss_rate))

        return (header, payload)
```

**DoD:**
- [ ] PLC integrado no jitter buffer
- [ ] Packet loss automaticamente "escondido"
- [ ] Log mostra quando PLC é usado
- [ ] **TESTE MANUAL**: Ligar para 100, áudio funciona mesmo com packet loss simulado

---

#### Task 5.3: Add PLC Metrics
**Effort:** 30 min

**Implementation:**
```python
# src/rtp/jitter_buffer.py - JitterBufferStats

class JitterBufferStats:
    def __init__(self):
        # ... existing fields ...

        self.packets_concealed = 0
        self.plc_level_1_count = 0  # Repeat
        self.plc_level_2_count = 0  # Fade
        self.plc_level_3_count = 0  # Comfort noise
```

**DoD:**
- [ ] PLC stats implementados
- [ ] Stats incrementados corretamente
- [ ] **TESTE MANUAL**: Simular loss, verificar stats.packets_concealed > 0

---

#### Task 5.4: Unit Tests for PLC
**Effort:** 2 hours

**Tests:**
```python
# tests/unit/test_packet_loss_concealment.py

def test_level_1_repeat_packet():
    """Low loss (0-3%) should repeat last packet"""

def test_level_2_fade_to_noise():
    """Medium loss (3-10%) should fade to comfort noise"""

def test_level_3_comfort_noise():
    """High loss (>10%) should generate comfort noise only"""

def test_consecutive_losses():
    """Multiple consecutive losses should degrade gracefully"""
```

**DoD:**
- [ ] Todos unit tests passando
- [ ] Coverage > 80%
- [ ] **TESTE**: `pytest tests/unit/test_packet_loss_concealment.py -v`

---

#### Task 5.5: Integration Test with Simulated Loss
**Effort:** 2 hours

**Implementation:**
```python
# tests/integration/test_jitter_buffer_with_loss.py

async def test_audio_quality_under_loss():
    """Test that PLC maintains audio continuity"""

    jb = AdaptiveJitterBuffer()

    # Send 100 packets with 5% random loss
    for i in range(100):
        if random.random() > 0.05:  # 95% success rate
            jb.push(RTPHeader(sequence_number=i), b'audio_data')

    # Verify PLC filled gaps
    packets_received = 0
    for _ in range(100):
        packet = await jb.pop()
        if packet:
            packets_received += 1

    # Should receive all 100 (95 real + 5 PLC)
    assert packets_received == 100
    assert jb.stats.packets_concealed == 5
```

**DoD:**
- [ ] Integration test passa
- [ ] PLC compensa packet loss
- [ ] **TESTE**: `pytest tests/integration/ -v`

---

### EPIC-005 Final DoD

**Acceptance Criteria:**
- [x] PLC class implementada (3 níveis)
- [x] Integrado no jitter buffer
- [x] Métricas de PLC coletadas
- [x] Unit tests > 80% coverage
- [x] **TESTE FINAL**: Ligar para ramal 100
  - [ ] Agente atende normalmente
  - [ ] Áudio continua fluido (sem clicks/pops)
  - [ ] Log mostra stats de PLC (se houver loss)
- [x] **TESTE STRESS**: Simular 5% packet loss (tc netem)
  - [ ] Áudio continua aceitável (sem cortes audíveis)
  - [ ] Stats mostram `packets_concealed` > 0
  - [ ] Stats mostram `plc_level_1_count` > 0 (repetindo packets)
- [x] **TESTE STRESS**: Simular 15% packet loss
  - [ ] Áudio degradado mas inteligível
  - [ ] Stats mostram uso de PLC Level 2/3
- [x] Code review aprovado

---

## EPIC-006: Sequence Number Validation

**Owner:** Backend Team
**Priority:** 🟡 MEDIUM
**Estimated Effort:** 1 day
**Dependencies:** EPIC-004 (Jitter Buffer - já valida sequence)

### Context
Jitter buffer já faz sequence tracking, mas precisamos adicionar detecção de replay attacks e métricas.

### Microtasks

#### Task 6.1: Add Replay Protection Window
**Effort:** 2 hours

**Implementation:**
```python
# src/rtp/jitter_buffer.py

class AdaptiveJitterBuffer:
    def __init__(self, config: Optional[JitterBufferConfig] = None):
        # ... existing init ...

        # Replay protection
        self.replay_window_size = 64  # RFC 3711 recommends 64
        self.seen_sequences: deque = deque(maxlen=self.replay_window_size)

    def _is_replay(self, seq: int) -> bool:
        """Check if sequence number is replayed"""

        # Check if already seen in window
        if seq in self.seen_sequences:
            logger.warn("🚨 REPLAY ATTACK DETECTED",
                       seq=seq,
                       action="PACKET_DROPPED")
            return True

        # Add to window
        self.seen_sequences.append(seq)
        return False

    def push(self, header: RTPHeader, payload: bytes) -> bool:
        # Check for replay
        if self._is_replay(header.sequence_number):
            self.stats.packets_rejected_replay += 1
            return False

        # ... rest of push logic ...
```

**DoD:**
- [ ] Replay detection implementado
- [ ] Window de 64 packets
- [ ] Log de warning para replay attempts
- [ ] **TESTE MANUAL**: Ligar para 100, sem replays detectados
- [ ] **TESTE UNITÁRIO**: Replay é detectado e rejeitado

---

#### Task 6.2: Add Sequence Jump Detection
**Effort:** 1 hour

**Implementation:**
```python
def _detect_sequence_jump(self, seq: int) -> bool:
    """Detect abnormal sequence number jumps"""

    if self.highest_seq_received is None:
        return False

    jump = self._seq_diff(seq, self.highest_seq_received)

    # Alert on jumps > 1000 packets (abnormal)
    if jump > 1000:
        logger.warn("⚠️ Large sequence jump detected",
                   from_seq=self.highest_seq_received,
                   to_seq=seq,
                   jump=jump,
                   possible_reason="network_restart_or_attack")
        return True

    return False
```

**DoD:**
- [ ] Sequence jumps detectados
- [ ] Log de warning para jumps anormais
- [ ] **TESTE MANUAL**: Ligar para 100, sem jumps anormais

---

### EPIC-006 Final DoD

**Acceptance Criteria:**
- [x] Replay protection implementado (window de 64)
- [x] Sequence jump detection implementado
- [x] Métricas de segurança coletadas
- [x] **TESTE FINAL**: Ligar para ramal 100
  - [ ] Agente funciona normalmente
  - [ ] Stats: `packets_rejected_replay == 0`
  - [ ] Sequence tracking funcionando
- [x] Code review aprovado

---

# PHASE 3: Performance & Monitoring

**Duration:** Week 4 (5 dias úteis)
**Priority:** 🟡 MEDIUM
**Goal:** Melhorar performance e visibilidade do sistema

---

## EPIC-007: DatagramProtocol Migration

**Owner:** Backend Team
**Priority:** 🟡 MEDIUM
**Estimated Effort:** 1 day
**Dependencies:** None (mas requer cuidado para não quebrar)

### Context
Migrar de `loop.add_reader()` para `asyncio.DatagramProtocol` para melhor performance (~2.5x faster).

### Microtasks

#### Task 7.1: Create RTPProtocol Class
**Effort:** 2 hours

**Implementation:** (Ver código completo em ADR-003)

**DoD:**
- [ ] Arquivo `src/rtp/protocol.py` criado
- [ ] Classe `RTPProtocol(asyncio.DatagramProtocol)` implementada
- [ ] Callbacks: `datagram_received()`, `error_received()`
- [ ] Unit tests criados

---

#### Task 7.2: Create RTPConnectionV2 with Protocol
**Effort:** 2 hours

**Implementation:**
```python
# src/rtp/connection_v2.py

class RTPConnectionV2:
    """New implementation using DatagramProtocol"""

    async def listen(self, port_min: int, port_end: int, ...):
        loop = asyncio.get_running_loop()

        transport, protocol = await loop.create_datagram_endpoint(
            lambda: RTPProtocol(
                on_packet_callback=self._on_packet,
                on_error_callback=self._on_error
            ),
            local_addr=(listen_addr, port)
        )

        self.transport = transport
        self.protocol = protocol
```

**DoD:**
- [ ] RTPConnectionV2 implementado
- [ ] Interface compatível com RTPConnection original
- [ ] **TESTE UNITÁRIO**: Create endpoint, send/receive packets

---

#### Task 7.3: Add Feature Flag for Protocol Version
**Effort:** 30 min

**Implementation:**
```yaml
# config/default.yaml

rtp:
  # ... existing config ...

  # Performance
  use_datagram_protocol: false  # Set true to use new implementation
```

**DoD:**
- [ ] Feature flag adicionado
- [ ] RTPServer escolhe implementation baseado em flag
- [ ] **TESTE MANUAL**: Com flag=false, usa old implementation (funciona)
- [ ] **TESTE MANUAL**: Com flag=true, usa new implementation (funciona)

---

#### Task 7.4: A/B Testing & Benchmarking
**Effort:** 2 hours

**Benchmark:**
```bash
# Benchmark packet processing latency
python tests/benchmark/rtp_latency.py --old-protocol
python tests/benchmark/rtp_latency.py --new-protocol

# Expected results:
# Old: ~50µs per packet
# New: ~20µs per packet (2.5x faster)
```

**DoD:**
- [ ] Benchmark mostra new protocol é 2-3x mais rápido
- [ ] **TESTE MANUAL**: Ligar para 100 com ambas implementações
  - [ ] Ambas funcionam perfeitamente
  - [ ] Latência menor com new protocol

---

#### Task 7.5: Gradual Migration & Deprecation
**Effort:** 1 hour

**Plan:**
1. Week 4: Deploy com flag=false (old protocol)
2. Week 5: Enable flag=true para 10% do tráfego (canary)
3. Week 6: Enable flag=true para 50%
4. Week 7: Enable flag=true para 100%
5. Week 8: Remover old implementation

**DoD:**
- [ ] Migration plan documentado
- [ ] Deprecation notice adicionado ao código old
- [ ] Monitoring em ambas implementações

---

### EPIC-007 Final DoD

**Acceptance Criteria:**
- [x] RTPProtocol + RTPConnectionV2 implementados
- [x] Feature flag permite switch entre implementações
- [x] Benchmark mostra 2-3x speedup
- [x] **TESTE FINAL**: Ligar para ramal 100 (new protocol)
  - [ ] Agente atende
  - [ ] Latência menor (verificar via benchmark)
  - [ ] Sem regressões
- [x] Migration plan aprovado
- [x] Code review aprovado

---

## EPIC-008: RTCP Implementation

**Owner:** Backend Team
**Priority:** 🟡 MEDIUM
**Estimated Effort:** 2 days
**Dependencies:** None

### Context
Implementar RTCP (RTP Control Protocol) para obter feedback de qualidade de rede (loss rate, jitter, RTT).

### Microtasks

#### Task 8.1: Create RTCP Packet Classes
**Effort:** 2 hours

**Implementation:** (Ver código em ADR-004)

**DoD:**
- [ ] Arquivo `src/rtp/rtcp.py` criado
- [ ] Classes implementadas:
  - [ ] `RTCPSenderReport`
  - [ ] `RTCPReceiverReport`
  - [ ] `RTCPReportBlock`
  - [ ] `RTCPSession`
- [ ] Parser/marshaller de RTCP packets
- [ ] Unit tests criados

---

#### Task 8.2: Implement RTCP RR Generation
**Effort:** 2 hours

**Implementation:**
```python
# src/rtp/rtcp.py

class RTCPSession:
    def generate_rr(self) -> bytes:
        """Generate RTCP Receiver Report"""

        # Calculate fraction lost
        fraction = int((self.packets_lost / self.packets_expected) * 256)

        # Build RR packet (RFC 3550)
        packet = struct.pack('!BBH', 0b10000001, 201, 7)  # Header
        packet += struct.pack('!I', self.ssrc)  # Our SSRC
        packet += self._build_report_block()

        return packet
```

**DoD:**
- [ ] RR packet generation implementado
- [ ] Formato RFC 3550 compliant
- [ ] **TESTE UNITÁRIO**: RR packet é válido

---

#### Task 8.3: Add RTCP Send Loop
**Effort:** 1 hour

**Implementation:**
```python
# src/rtp/server.py - RTPSession

async def _rtcp_loop(self):
    """Send RTCP RR every 5 seconds"""
    while self.running:
        await asyncio.sleep(5.0)

        # Generate RR
        rr_packet = self.rtcp_session.generate_rr()

        # Send via RTCP socket (TODO: create RTCP socket)
        # For now, just log stats
        logger.info("RTCP stats",
                   session_id=self.session_id,
                   stats=self.rtcp_session.get_stats())
```

**DoD:**
- [ ] RTCP loop implementado
- [ ] RR gerado a cada 5 segundos
- [ ] Stats logados
- [ ] **TESTE MANUAL**: Ligar para 100, ver RTCP stats nos logs

---

#### Task 8.4: Create RTCP Socket (Separate from RTP)
**Effort:** 2 hours

**Implementation:**
```python
# RTCP usa porta RTP + 1
rtcp_port = rtp_port + 1

# Create RTCP socket
self.rtcp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
self.rtcp_socket.bind((listen_addr, rtcp_port))
```

**DoD:**
- [ ] RTCP socket criado (porta RTP+1)
- [ ] RTCP packets enviados via socket separado
- [ ] **TESTE MANUAL**: Wireshark mostra RTCP packets sendo enviados

---

#### Task 8.5: Parse Incoming RTCP SR (from remote)
**Effort:** 2 hours

**Implementation:**
```python
async def _rtcp_receive_loop(self):
    """Receive RTCP SR from remote"""
    while self.running:
        data, addr = await self.rtcp_socket.recvfrom(1500)

        # Parse RTCP packet
        self.rtcp_session.process_sr(data)

        # Calculate RTT
        rtt = self.rtcp_session.calculate_rtt(dlsr)
        logger.info("RTT measured", rtt_ms=rtt)
```

**DoD:**
- [ ] RTCP SR parsing implementado
- [ ] RTT calculation funcionando
- [ ] **TESTE MANUAL**: Ver RTT nos logs (se remote enviar SR)

---

### EPIC-008 Final DoD

**Acceptance Criteria:**
- [x] RTCP RR generation + sending implementado
- [x] RTCP SR parsing + RTT calculation implementado
- [x] RTCP socket separado (porta RTP+1)
- [x] Stats completos (loss, jitter, RTT)
- [x] **TESTE FINAL**: Ligar para ramal 100
  - [ ] Agente funciona normalmente
  - [ ] Logs mostram RTCP stats a cada 5s
  - [ ] Stats incluem: loss_rate, jitter_ms, RTT (se disponível)
- [x] **TESTE WIRESHARK**: Capturar tráfego
  - [ ] Ver RTCP RR packets sendo enviados
  - [ ] Porta correta (RTP+1)
- [x] Code review aprovado

---

## EPIC-009: Circuit Breaker & Error Recovery

**Owner:** Backend Team
**Priority:** 🟡 MEDIUM
**Estimated Effort:** 1 day
**Dependencies:** None

### Context
Adicionar circuit breaker para fail fast quando rede está down e recuperar automaticamente quando volta.

### Microtasks

#### Task 9.1: Create CircuitBreaker Class
**Effort:** 2 hours

**Implementation:** (Ver código em ADR-007)

**DoD:**
- [ ] Arquivo `src/common/circuit_breaker.py` criado
- [ ] Classe `CircuitBreaker` implementada
- [ ] Estados: CLOSED, OPEN, HALF_OPEN
- [ ] Métodos: `call()`, `_on_success()`, `_on_failure()`
- [ ] Unit tests criados

---

#### Task 9.2: Integrate Circuit Breaker in RTP Write
**Effort:** 1 hour

**Implementation:**
```python
# src/rtp/connection.py

class RTPConnection:
    def __init__(self, config: Optional[RTPConnectionConfig] = None):
        # ... existing init ...

        # Circuit breaker
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=10,
            recovery_timeout=30.0,
            success_threshold=5
        )

    async def write_rtp(self, header: RTPHeader, payload: bytes) -> int:
        """Send RTP with circuit breaker protection"""
        try:
            return await self.circuit_breaker.call(
                self._write_rtp_internal,
                header,
                payload
            )
        except CircuitOpenError:
            logger.warn("Circuit breaker OPEN - dropping packet")
            return 0
```

**DoD:**
- [ ] Circuit breaker integrado
- [ ] Write operations protegidas
- [ ] **TESTE MANUAL**: Ligar para 100, funciona normalmente (circuit CLOSED)

---

#### Task 9.3: Add Circuit Breaker Metrics
**Effort:** 30 min

**Implementation:**
```python
class CircuitBreakerStats:
    circuit_state = Gauge('circuit_breaker_state',
                         'Circuit breaker state (0=CLOSED, 1=OPEN, 2=HALF_OPEN)')
    circuit_failures = Counter('circuit_breaker_failures_total',
                              'Total failures')
    circuit_trips = Counter('circuit_breaker_trips_total',
                           'Total times circuit opened')
```

**DoD:**
- [ ] Métricas Prometheus implementadas
- [ ] Dashboard mostra circuit state
- [ ] **TESTE**: Ver métricas em `/metrics`

---

#### Task 9.4: Test Circuit Breaker Behavior
**Effort:** 2 hours

**Tests:**
```python
# tests/integration/test_circuit_breaker.py

async def test_circuit_opens_on_failures():
    """Circuit should open after threshold failures"""

async def test_circuit_recovers():
    """Circuit should attempt recovery after timeout"""

async def test_half_open_closes_on_success():
    """HALF_OPEN should go to CLOSED after success threshold"""
```

**DoD:**
- [ ] Todos integration tests passando
- [ ] **TESTE MANUAL**: Simular falha de rede
  - [ ] Circuit abre após 10 falhas
  - [ ] Aguarda 30s para recovery
  - [ ] Tenta recovery (HALF_OPEN)
  - [ ] Fecha após 5 sucessos

---

### EPIC-009 Final DoD

**Acceptance Criteria:**
- [x] CircuitBreaker implementado (3 estados)
- [x] Integrado em RTP write operations
- [x] Métricas de circuit state
- [x] **TESTE FINAL**: Ligar para ramal 100
  - [ ] Funciona normalmente (circuit CLOSED)
  - [ ] Metrics: `circuit_state = 0` (CLOSED)
- [x] **TESTE STRESS**: Desconectar rede
  - [ ] Circuit abre após falhas
  - [ ] Metrics: `circuit_state = 1` (OPEN)
  - [ ] Reconectar rede
  - [ ] Circuit recupera automaticamente
- [x] Code review aprovado

---

# PHASE 4: Advanced Features

**Duration:** Week 5+ (ongoing)
**Priority:** 🟢 LOW
**Goal:** Features avançadas e nice-to-have

---

## EPIC-010: DTMF Detection (RFC 2833)

**Owner:** Audio Team
**Priority:** 🟢 MEDIUM
**Estimated Effort:** 2 days
**Dependencies:** None

### Context
Detectar DTMF (tons de teclado telefônico) para navegar menus IVR.

### Microtasks

#### Task 10.1: Parse RFC 2833 RTP Event Packets
**Effort:** 3 hours

**Implementation:**
```python
# src/rtp/dtmf.py

class DTMFDetector:
    """DTMF Detection via RFC 2833 (RTP Event)"""

    # Payload type for telephone-event (tipicamente 101)
    DTMF_PAYLOAD_TYPE = 101

    def process_rtp(self, header: RTPHeader, payload: bytes) -> Optional[str]:
        """Process RTP packet, return DTMF digit if detected"""

        if header.payload_type != self.DTMF_PAYLOAD_TYPE:
            return None

        # Parse RFC 2833 payload
        if len(payload) < 4:
            return None

        event = payload[0]
        end_bit = (payload[1] >> 7) & 0x01

        # Map event to digit
        digit = self._event_to_digit(event)

        if end_bit and digit:
            logger.info("DTMF detected", digit=digit)
            return digit

        return None

    def _event_to_digit(self, event: int) -> Optional[str]:
        """Map RFC 2833 event code to digit"""
        mapping = {
            0: '0', 1: '1', 2: '2', 3: '3', 4: '4',
            5: '5', 6: '6', 7: '7', 8: '8', 9: '9',
            10: '*', 11: '#'
        }
        return mapping.get(event)
```

**DoD:**
- [ ] DTMFDetector implementado
- [ ] RFC 2833 parsing correto
- [ ] **TESTE UNITÁRIO**: Event codes mapeados para dígitos

---

#### Task 10.2: Integrate DTMF in Audio Pipeline
**Effort:** 1 hour

**Implementation:**
```python
# src/audio/pipeline.py

from ..rtp.dtmf import DTMFDetector

class AudioPipeline:
    def __init__(self, config: AudioPipelineConfig):
        # ... existing init ...

        # DTMF detector
        self.dtmf_detector = DTMFDetector()
        self.on_dtmf_callback: Optional[Callable[[str], None]] = None

    async def process_call(self, rtp_session: RTPSession):
        # Get RTP packet
        header, payload = await rtp_session.audio_in_queue.get()

        # Check for DTMF
        digit = self.dtmf_detector.process_rtp(header, payload)
        if digit and self.on_dtmf_callback:
            self.on_dtmf_callback(digit)

        # Continue with normal processing...
```

**DoD:**
- [ ] DTMF detector integrado
- [ ] Callback `on_dtmf` disponível
- [ ] **TESTE MANUAL**: Pressionar dígito no telefone
  - [ ] Log mostra "DTMF detected: X"

---

#### Task 10.3: Add DTMF to AI Conversation Context
**Effort:** 1 hour

**Implementation:**
```python
# src/ai/conversation.py

class ConversationManager:
    def handle_dtmf(self, digit: str):
        """Handle DTMF input during conversation"""

        logger.info("DTMF received during conversation", digit=digit)

        # Add to conversation context
        self.add_user_message(f"[User pressed: {digit}]")

        # Trigger special handling if needed
        if digit == '*':
            return "You pressed star. How can I help?"
        elif digit == '#':
            return "You pressed pound. Transferring..."
```

**DoD:**
- [ ] DTMF handling implementado
- [ ] DTMF aparece no contexto da conversa
- [ ] **TESTE MANUAL**: Ligar para 100, pressionar dígito
  - [ ] Agente reconhece: "Você pressionou 5"

---

### EPIC-010 Final DoD

**Acceptance Criteria:**
- [x] DTMF detection (RFC 2833) implementado
- [x] Integrado no audio pipeline
- [x] DTMF aparece no contexto AI
- [x] **TESTE FINAL**: Ligar para ramal 100
  - [ ] Durante conversa, pressionar dígito (ex: 5)
  - [ ] Log mostra "DTMF detected: 5"
  - [ ] Agente responde reconhecendo o dígito
- [x] Code review aprovado

---

## EPIC-011: Queue Optimization

**Owner:** Backend Team
**Priority:** 🟢 LOW
**Estimated Effort:** 1 day
**Dependencies:** None

### Context
Substituir `asyncio.Queue` por `collections.deque` para melhor performance (10x faster).

### Microtasks

#### Task 11.1: Replace audio_in_queue with deque
**Effort:** 2 hours

**Implementation:** (Ver código em ADR-005)

**DoD:**
- [ ] `audio_in_queue` agora é `deque`
- [ ] Lock para thread-safety
- [ ] Event para signal data available
- [ ] **TESTE MANUAL**: Ligar para 100, funciona normalmente

---

#### Task 11.2: Benchmark Queue Performance
**Effort:** 1 hour

**Benchmark:**
```python
# Benchmark queue operations
import time
from collections import deque
import asyncio

# asyncio.Queue
queue = asyncio.Queue(maxsize=100)
start = time.time()
for i in range(10000):
    await queue.put(i)
    await queue.get()
print(f"asyncio.Queue: {time.time() - start:.3f}s")

# deque
dq = deque(maxlen=100)
start = time.time()
for i in range(10000):
    dq.append(i)
    dq.popleft()
print(f"deque: {time.time() - start:.3f}s")

# Expected: deque is ~10x faster
```

**DoD:**
- [ ] Benchmark mostra deque 5-10x mais rápido
- [ ] Sem regressões funcionais

---

### EPIC-011 Final DoD

**Acceptance Criteria:**
- [x] Queue otimizado com deque
- [x] Performance improvement verificado
- [x] **TESTE FINAL**: Ligar para 100, funciona normalmente
- [x] Benchmark mostra speedup
- [x] Code review aprovado

---

## EPIC-012: Metrics & Monitoring Dashboard

**Owner:** DevOps + Backend
**Priority:** 🟢 MEDIUM
**Estimated Effort:** 2 days
**Dependencies:** EPIC-008 (RTCP)

### Context
Criar dashboard Grafana para visualizar métricas de RTP/RTCP.

### Microtasks

#### Task 12.1: Export Prometheus Metrics
**Effort:** 2 hours

**Metrics:**
```python
# src/rtp/metrics.py

from prometheus_client import Counter, Histogram, Gauge

# Packet metrics
rtp_packets_received = Counter('rtp_packets_received_total', ...)
rtp_packets_sent = Counter('rtp_packets_sent_total', ...)
rtp_packets_lost = Counter('rtp_packets_lost_total', ...)

# Quality metrics
rtp_jitter_ms = Histogram('rtp_jitter_milliseconds', ...)
rtp_loss_rate = Gauge('rtp_loss_rate_percent', ...)
rtp_buffer_depth = Gauge('rtp_buffer_depth_ms', ...)

# RTCP metrics
rtcp_rtt_ms = Gauge('rtcp_rtt_milliseconds', ...)
```

**DoD:**
- [ ] Todas métricas exportadas
- [ ] Disponíveis em `/metrics`
- [ ] **TESTE**: `curl localhost:8000/metrics | grep rtp_`

---

#### Task 12.2: Create Grafana Dashboard
**Effort:** 3 hours

**Panels:**
- Packet Loss Rate (%)
- Jitter Distribution
- Buffer Depth Adaptation
- RTCP RTT
- Circuit Breaker State
- Active Sessions

**DoD:**
- [ ] Dashboard JSON criado
- [ ] Importado no Grafana
- [ ] **TESTE**: Ligar para 100, ver métricas atualizando em real-time

---

#### Task 12.3: Add Alerting Rules
**Effort:** 2 hours

**Alerts:**
```yaml
# prometheus/alerts.yml

groups:
  - name: rtp_quality
    rules:
      - alert: HighPacketLoss
        expr: rtp_loss_rate_percent > 5
        for: 1m
        annotations:
          summary: "High packet loss detected (>5%)"

      - alert: HighJitter
        expr: histogram_quantile(0.95, rtp_jitter_ms) > 100
        for: 2m
        annotations:
          summary: "High jitter detected (p95 > 100ms)"
```

**DoD:**
- [ ] Alerting rules configurados
- [ ] Alerts testados
- [ ] Notificações funcionando (Slack/email)

---

### EPIC-012 Final DoD

**Acceptance Criteria:**
- [x] Prometheus metrics exportadas
- [x] Grafana dashboard criado
- [x] Alerting configurado
- [x] **TESTE FINAL**: Ligar para 100
  - [ ] Dashboard mostra métricas em tempo real
  - [ ] Packet loss, jitter, buffer depth visíveis
- [x] Code review aprovado

---

# 🧪 TESTING STRATEGY

## Manual Testing Checklist

Após cada EPIC, executar este checklist:

### ✅ Basic Call Test
- [ ] Ligar para ramal 100 do browser-phone
- [ ] Agente atende em < 3 segundos
- [ ] Consegue ouvir o agente claramente
- [ ] Consegue falar e agente responde corretamente
- [ ] Desligar sem erros

### ✅ Audio Quality Test
- [ ] Áudio sem clicks/pops
- [ ] Áudio sem cortes (dropouts)
- [ ] Latência aceitável (< 500ms end-to-end)
- [ ] Volume adequado

### ✅ Logs Verification
- [ ] Logs INFO mostram fluxo correto (INVITE → 200 OK → RTP session)
- [ ] Logs DEBUG mostram métricas relevantes
- [ ] Sem logs ERROR ou EXCEPTION
- [ ] Stats mostram valores esperados

### ✅ Metrics Verification
- [ ] `/metrics` mostra métricas atualizadas
- [ ] Counters incrementando corretamente
- [ ] Gauges com valores realistas

---

## Stress Testing

### Network Stress Tests

```bash
# 1. Simular packet loss (5%)
sudo tc qdisc add dev eth0 root netem loss 5%

# Testar: Ligar para 100, verificar PLC compensando

# 2. Simular jitter (50ms ±25ms)
sudo tc qdisc add dev eth0 root netem delay 50ms 25ms

# Testar: Verificar jitter buffer adaptando

# 3. Simular bandwidth limit (256kbps)
sudo tc qdisc add dev eth0 root tbf rate 256kbit burst 1540 latency 50ms

# Testar: Verificar qualidade sob bandwidth limitado

# Cleanup
sudo tc qdisc del dev eth0 root
```

### Load Testing

```bash
# Teste de carga: 10 chamadas simultâneas
python tests/load/concurrent_calls.py --calls 10 --duration 60

# Verificar:
# - Todas chamadas atendem
# - CPU < 80%
# - Memory < 2GB
# - Packet loss < 1%
```

---

## Regression Testing

Após cada mudança:

```bash
# 1. Unit tests
pytest tests/unit/ -v --cov=src/rtp

# 2. Integration tests
pytest tests/integration/ -v

# 3. Manual call test
# Ligar para 100, validar funcionamento básico

# 4. Check metrics
curl localhost:8000/metrics | grep -E "rtp_|sip_"
```

---

# 📈 SUCCESS METRICS

## Phase 1 Success Criteria
- [ ] 0 RTP hijacking attempts possíveis
- [ ] Session limits enforced (max 100 concurrent)
- [ ] 0 security vulnerabilities (validated IP + SSRC)

## Phase 2 Success Criteria
- [ ] Packet loss até 15% resulta em áudio aceitável (MOS > 3.5)
- [ ] Jitter até 200ms compensado automaticamente
- [ ] 0 clicks/pops audíveis sob condições normais

## Phase 3 Success Criteria
- [ ] Latência de processamento RTP < 50µs (2x speedup com DatagramProtocol)
- [ ] RTCP stats disponíveis (loss, jitter, RTT)
- [ ] Circuit breaker recupera automaticamente em < 60s

## Phase 4 Success Criteria
- [ ] DTMF detection funcionando (RFC 2833)
- [ ] Queue operations 5-10x mais rápidas
- [ ] Dashboard Grafana mostra métricas em real-time

---

# 📅 TIMELINE SUMMARY

| Week | Phase | EPICs | Effort | Priority |
|------|-------|-------|--------|----------|
| **Week 1** | Phase 1: Security | EPIC-001, 002, 003 | 3 days | 🔴 CRITICAL |
| **Week 2** | Phase 2: Audio Quality (Part 1) | EPIC-004, 005 | 5 days | 🟠 HIGH |
| **Week 3** | Phase 2: Audio Quality (Part 2) | EPIC-006 | 1 day | 🟡 MEDIUM |
| **Week 4** | Phase 3: Performance | EPIC-007, 008, 009 | 4 days | 🟡 MEDIUM |
| **Week 5+** | Phase 4: Advanced | EPIC-010, 011, 012 | 5 days | 🟢 LOW |

**Total Estimated Effort:** ~18 days (3.5 weeks)

---

# 🎯 NEXT STEPS

1. **Review este roadmap** com a equipe técnica
2. **Aprovar priorização** dos EPICs
3. **Criar branch** `feature/rtp-optimization`
4. **Começar EPIC-001** (IP Access Control)
5. **Test after each task** ligando para ramal 100

---

**Status:** Ready for Implementation ✅
**Last Updated:** 2026-01-21
**Owner:** Backend Team + Audio Team
**Approvers:** Tech Lead, Product Owner
