# Arquitetura Modular: AI Voice Agent

**Data:** 2026-01-20
**Versão:** 1.0
**Princípio:** Separação de responsabilidades (SoC) + Baixo acoplamento

---

## 🎯 Visão Geral

### Filosofia de Design

```
┌─────────────────────────────────────────────────────────────┐
│ PRINCÍPIOS FUNDAMENTAIS:                                     │
│                                                               │
│ 1. Single Responsibility: Cada módulo faz UMA coisa          │
│ 2. Interface-based: Módulos comunicam via interfaces claras  │
│ 3. Testável: Cada módulo pode ser testado isoladamente       │
│ 4. Substituível: Trocar implementação sem quebrar sistema    │
│ 5. Observable: Logging/metrics em cada módulo                │
└─────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Arquitetura de Alto Nível

```
┌──────────────────────────────────────────────────────────────┐
│                       USER (SIP Phone)                        │
│                    sip:user@voiceagent.com                    │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            │ SIP (UDP:5060)
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  MODULE 1: SIP SERVER                                         │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Responsabilidade:                                        │ │
│  │ - Accept/Reject INVITE                                  │ │
│  │ - SDP negotiation (offer/answer)                        │ │
│  │ - Digest authentication                                 │ │
│  │ - Call state management (ringing, active, hangup)       │ │
│  │                                                          │ │
│  │ Input:  SIP INVITE (UDP packet)                         │ │
│  │ Output: CallSession (id, remote_sdp, status)            │ │
│  └─────────────────────────────────────────────────────────┘ │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            │ Event: on_call_established(session)
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  MODULE 2: RTP SERVER                                         │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Responsabilidade:                                        │ │
│  │ - Receive RTP packets (G.711/Opus)                      │ │
│  │ - Decode audio codec → raw PCM                          │ │
│  │ - Encode PCM → codec                                    │ │
│  │ - Send RTP packets                                      │ │
│  │ - Handle jitter buffer                                  │ │
│  │ - DTMF detection                                        │ │
│  │                                                          │ │
│  │ Input:  CallSession (remote_ip, remote_port, codec)     │ │
│  │ Output: AudioStream (send(), receive())                 │ │
│  └─────────────────────────────────────────────────────────┘ │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            │ Interface: AudioStream
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  MODULE 3: AI VOICE2VOICE                                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Responsabilidade:                                        │ │
│  │ - VAD (Voice Activity Detection)                        │ │
│  │ - ASR (Speech-to-Text via Whisper)                      │ │
│  │ - LLM (Text generation via Qwen2.5)                     │ │
│  │ - TTS (Text-to-Speech via Kokoro)                       │ │
│  │ - Conversation state management                         │ │
│  │                                                          │ │
│  │ Input:  AudioStream                                     │ │
│  │ Output: AudioStream (synthesized response)              │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 📦 Estrutura de Diretórios

```
ai-voice-agent/
├── README.md
├── pyproject.toml              # Poetry/pip dependencies
├── docker-compose.yml          # Dev environment
├── .env.example
│
├── src/
│   ├── __init__.py
│   │
│   ├── sip/                    # MODULE 1: SIP Server
│   │   ├── __init__.py
│   │   ├── server.py           # SIPServer class
│   │   ├── session.py          # CallSession dataclass
│   │   ├── auth.py             # DigestAuth handler
│   │   ├── sdp.py              # SDP parser/generator
│   │   ├── protocol.py         # SIP protocol utilities
│   │   └── events.py           # SIP events (on_invite, on_bye, etc.)
│   │
│   ├── rtp/                    # MODULE 2: RTP Server
│   │   ├── __init__.py
│   │   ├── server.py           # RTPServer class
│   │   ├── stream.py           # AudioStream interface
│   │   ├── codec.py            # Codec handler (G.711, Opus)
│   │   ├── jitter.py           # Jitter buffer
│   │   └── dtmf.py             # DTMF detection
│   │
│   ├── ai/                     # MODULE 3: AI Voice2Voice
│   │   ├── __init__.py
│   │   ├── pipeline.py         # Voice2VoicePipeline orchestrator
│   │   ├── vad.py              # Voice Activity Detection
│   │   ├── asr.py              # ASR (Whisper)
│   │   ├── llm.py              # LLM (Qwen2.5)
│   │   ├── tts.py              # TTS (Kokoro)
│   │   └── conversation.py     # Conversation state manager
│   │
│   ├── orchestrator/           # GLUE: Connect modules
│   │   ├── __init__.py
│   │   ├── call_handler.py     # Main orchestrator
│   │   └── events.py           # Event bus
│   │
│   └── common/                 # Shared utilities
│       ├── __init__.py
│       ├── config.py           # Configuration management
│       ├── logging.py          # Structured logging
│       ├── metrics.py          # Prometheus metrics
│       └── errors.py           # Custom exceptions
│
├── tests/
│   ├── unit/
│   │   ├── test_sip_server.py
│   │   ├── test_rtp_server.py
│   │   └── test_ai_pipeline.py
│   ├── integration/
│   │   └── test_full_call_flow.py
│   └── fixtures/
│       ├── sample_invite.txt
│       └── sample_audio.wav
│
├── config/
│   ├── default.yaml            # Default configuration
│   ├── development.yaml
│   └── production.yaml
│
└── docs/
    ├── API.md                  # API documentation
    ├── DEPLOYMENT.md
    └── TROUBLESHOOTING.md
```

---

## 🔌 Interfaces Entre Módulos

### Interface 1: SIP Server → RTP Server

```python
# src/sip/session.py
from dataclasses import dataclass
from typing import Optional
from enum import Enum

class CallStatus(Enum):
    RINGING = "ringing"
    ACTIVE = "active"
    HANGUP = "hangup"

@dataclass
class CallSession:
    """
    Contrato entre SIP Server e RTP Server
    SIP Server cria, RTP Server consome
    """
    session_id: str              # Unique call ID
    remote_ip: str               # User RTP endpoint IP
    remote_port: int             # User RTP endpoint port
    codec: str                   # Negotiated codec (PCMU, PCMA, Opus)
    status: CallStatus           # Current call status
    local_port: int              # Our RTP port for this call
    remote_sdp: str              # Full remote SDP (for debugging)

    # Optional
    caller_id: Optional[str] = None
    trunk_id: Optional[str] = None


# src/sip/server.py
from abc import ABC, abstractmethod

class SIPServerInterface(ABC):
    """Interface pública do SIP Server"""

    @abstractmethod
    def start(self, host: str, port: int) -> None:
        """Start SIP server on host:port"""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop SIP server gracefully"""
        pass

    @abstractmethod
    def register_callback(self, event: str, callback: callable) -> None:
        """
        Register callback for SIP events:
        - on_call_established(session: CallSession)
        - on_call_ended(session_id: str)
        """
        pass
```

---

### Interface 2: RTP Server → AI Pipeline

```python
# src/rtp/stream.py
from abc import ABC, abstractmethod
from typing import AsyncIterator
import asyncio

class AudioStream(ABC):
    """
    Contrato entre RTP Server e AI Pipeline
    RTP Server implementa, AI Pipeline consome
    """

    @abstractmethod
    async def receive(self) -> bytes:
        """
        Receive raw PCM audio chunk (blocking)
        Returns: PCM 16-bit, 8kHz mono (160 bytes = 20ms)
        """
        pass

    @abstractmethod
    async def send(self, pcm_data: bytes) -> None:
        """
        Send raw PCM audio chunk
        Args: PCM 16-bit, 8kHz mono
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close stream gracefully"""
        pass

    @property
    @abstractmethod
    def is_active(self) -> bool:
        """Check if stream is still active"""
        pass


# src/rtp/server.py
class RTPServerInterface(ABC):
    """Interface pública do RTP Server"""

    @abstractmethod
    async def create_stream(self, session: CallSession) -> AudioStream:
        """
        Create bidirectional audio stream for a call
        Returns: AudioStream instance
        """
        pass

    @abstractmethod
    async def close_stream(self, session_id: str) -> None:
        """Close audio stream for a call"""
        pass
```

---

### Interface 3: AI Pipeline (standalone)

```python
# src/ai/pipeline.py
from abc import ABC, abstractmethod

class Voice2VoiceInterface(ABC):
    """
    AI Pipeline é standalone - não depende de SIP nem RTP
    Recebe AudioStream, processa, retorna áudio
    """

    @abstractmethod
    async def process_call(self, stream: AudioStream) -> None:
        """
        Main loop: receive audio → ASR → LLM → TTS → send audio
        Runs until stream closes
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop pipeline gracefully"""
        pass
```

---

## 🔗 Comunicação: Event-Driven Architecture

```python
# src/orchestrator/events.py
from enum import Enum
from dataclasses import dataclass
from typing import Any, Callable, Dict, List
import asyncio

class EventType(Enum):
    """Todos os eventos do sistema"""
    # SIP events
    CALL_INVITE_RECEIVED = "call.invite.received"
    CALL_ESTABLISHED = "call.established"
    CALL_ENDED = "call.ended"

    # RTP events
    RTP_STREAM_STARTED = "rtp.stream.started"
    RTP_STREAM_ENDED = "rtp.stream.ended"
    RTP_PACKET_LOST = "rtp.packet.lost"

    # AI events
    ASR_TRANSCRIPTION_READY = "asr.transcription.ready"
    LLM_RESPONSE_READY = "llm.response.ready"
    TTS_AUDIO_READY = "tts.audio.ready"


@dataclass
class Event:
    """Evento genérico"""
    type: EventType
    data: Dict[str, Any]
    timestamp: float


class EventBus:
    """
    Pub/Sub event bus para comunicação entre módulos
    Desacopla completamente os módulos
    """

    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}

    def subscribe(self, event_type: EventType, callback: Callable) -> None:
        """Subscribe to an event"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    async def publish(self, event: Event) -> None:
        """Publish event to all subscribers"""
        if event.type in self._subscribers:
            for callback in self._subscribers[event.type]:
                # Run callback async
                asyncio.create_task(callback(event))


# Uso:
# bus = EventBus()
# bus.subscribe(EventType.CALL_ESTABLISHED, rtp_server.handle_call)
# bus.publish(Event(type=EventType.CALL_ESTABLISHED, data={'session': session}))
```

---

## 🎭 Orchestrator: Conectando os Módulos

```python
# src/orchestrator/call_handler.py
import asyncio
from src.sip.server import SIPServer
from src.rtp.server import RTPServer
from src.ai.pipeline import Voice2VoicePipeline
from src.orchestrator.events import EventBus, Event, EventType
from src.common.logging import get_logger

logger = get_logger(__name__)


class CallOrchestrator:
    """
    Orquestrador principal: conecta SIP + RTP + AI
    É o ÚNICO ponto que conhece todos os módulos
    """

    def __init__(
        self,
        sip_server: SIPServer,
        rtp_server: RTPServer,
        ai_pipeline: Voice2VoicePipeline,
        event_bus: EventBus
    ):
        self.sip = sip_server
        self.rtp = rtp_server
        self.ai = ai_pipeline
        self.bus = event_bus

        # Registrar callbacks
        self._register_callbacks()

    def _register_callbacks(self):
        """Wire up modules via event bus"""

        # SIP events
        self.bus.subscribe(
            EventType.CALL_ESTABLISHED,
            self._handle_call_established
        )
        self.bus.subscribe(
            EventType.CALL_ENDED,
            self._handle_call_ended
        )

    async def _handle_call_established(self, event: Event):
        """
        Workflow quando SIP aceita chamada:
        1. SIP Server aceita INVITE → emite CALL_ESTABLISHED
        2. RTP Server cria stream
        3. AI Pipeline inicia processamento
        """
        session = event.data['session']
        logger.info(f"📞 Call established: {session.session_id}")

        try:
            # 1. Criar RTP stream
            stream = await self.rtp.create_stream(session)
            logger.info(f"🎵 RTP stream created for {session.session_id}")

            # 2. Iniciar AI pipeline
            asyncio.create_task(self.ai.process_call(stream))
            logger.info(f"🤖 AI pipeline started for {session.session_id}")

        except Exception as e:
            logger.error(f"❌ Error handling call: {e}")
            # Cleanup
            await self.sip.hangup(session.session_id)

    async def _handle_call_ended(self, event: Event):
        """Cleanup quando chamada termina"""
        session_id = event.data['session_id']
        logger.info(f"📴 Call ended: {session_id}")

        # Cleanup RTP stream
        await self.rtp.close_stream(session_id)

    async def start(self):
        """Start all modules"""
        logger.info("🚀 Starting Call Orchestrator...")

        # Start modules in order
        await self.sip.start()
        await self.rtp.start()
        await self.ai.start()

        logger.info("✅ All modules started")

    async def stop(self):
        """Stop all modules gracefully"""
        logger.info("🛑 Stopping Call Orchestrator...")

        # Stop in reverse order
        await self.ai.stop()
        await self.rtp.stop()
        await self.sip.stop()

        logger.info("✅ All modules stopped")
```

---

## 🧪 Testabilidade: Mock de Cada Módulo

### Testando SIP Server isoladamente

```python
# tests/unit/test_sip_server.py
import pytest
from src.sip.server import SIPServer
from src.orchestrator.events import EventBus, EventType

@pytest.mark.asyncio
async def test_sip_accepts_invite():
    """Test: SIP server aceita INVITE e emite evento"""

    # Mock event bus
    event_bus = EventBus()
    events_received = []

    def capture_event(event):
        events_received.append(event)

    event_bus.subscribe(EventType.CALL_ESTABLISHED, capture_event)

    # Create SIP server
    sip = SIPServer(event_bus=event_bus)
    await sip.start(host='127.0.0.1', port=5060)

    # Simulate INVITE (usando pjsua como client)
    # ...

    # Assert: evento foi emitido
    assert len(events_received) == 1
    assert events_received[0].type == EventType.CALL_ESTABLISHED

    await sip.stop()
```

---

### Testando RTP Server com mock AudioStream

```python
# tests/unit/test_rtp_server.py
import pytest
from src.rtp.server import RTPServer
from src.sip.session import CallSession, CallStatus

@pytest.mark.asyncio
async def test_rtp_creates_stream():
    """Test: RTP server cria stream corretamente"""

    rtp = RTPServer()

    # Mock session
    session = CallSession(
        session_id='test-123',
        remote_ip='192.168.1.100',
        remote_port=10000,
        codec='PCMU',
        status=CallStatus.ACTIVE,
        local_port=20000
    )

    # Create stream
    stream = await rtp.create_stream(session)

    # Assert
    assert stream is not None
    assert stream.is_active is True

    # Test send/receive
    pcm_data = b'\x00' * 160  # 20ms de silêncio
    await stream.send(pcm_data)

    received = await stream.receive()
    assert len(received) == 160

    await rtp.close_stream(session.session_id)
```

---

### Testando AI Pipeline com mock AudioStream

```python
# tests/unit/test_ai_pipeline.py
import pytest
from src.ai.pipeline import Voice2VoicePipeline
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_ai_pipeline_processes_audio():
    """Test: AI pipeline processa áudio corretamente"""

    # Mock stream
    mock_stream = AsyncMock()
    mock_stream.receive.return_value = b'\x00' * 160  # Silêncio
    mock_stream.is_active = True

    # Create pipeline
    pipeline = Voice2VoicePipeline()

    # Process (should detect silence, skip ASR, send silence back)
    # Testamos com timeout para não rodar infinito
    async with asyncio.timeout(2):
        await pipeline.process_call(mock_stream)

    # Assert: send foi chamado
    assert mock_stream.send.called
```

---

## 📊 Observabilidade: Logging e Metrics

### Logging Estruturado por Módulo

```python
# src/common/logging.py
import logging
import json
from typing import Any, Dict

class StructuredLogger:
    """JSON structured logging para cada módulo"""

    def __init__(self, module_name: str):
        self.module = module_name
        self.logger = logging.getLogger(module_name)

    def info(self, message: str, **kwargs):
        self._log('INFO', message, kwargs)

    def error(self, message: str, **kwargs):
        self._log('ERROR', message, kwargs)

    def _log(self, level: str, message: str, context: Dict[str, Any]):
        log_entry = {
            'module': self.module,
            'level': level,
            'message': message,
            **context
        }
        self.logger.info(json.dumps(log_entry))


# Uso em cada módulo:
# from src.common.logging import StructuredLogger
# logger = StructuredLogger('sip.server')
# logger.info('Call established', session_id='abc-123', duration=45.2)
```

---

### Metrics: Prometheus por Módulo

```python
# src/common/metrics.py
from prometheus_client import Counter, Histogram, Gauge

# SIP metrics
sip_calls_total = Counter('sip_calls_total', 'Total SIP calls', ['status'])
sip_auth_attempts = Counter('sip_auth_attempts', 'Auth attempts', ['result'])

# RTP metrics
rtp_packets_sent = Counter('rtp_packets_sent', 'RTP packets sent')
rtp_packets_received = Counter('rtp_packets_received', 'RTP packets received')
rtp_packet_loss = Gauge('rtp_packet_loss_percent', 'Packet loss %')

# AI metrics
asr_latency = Histogram('asr_latency_seconds', 'ASR latency')
llm_latency = Histogram('llm_latency_seconds', 'LLM latency')
tts_latency = Histogram('tts_latency_seconds', 'TTS latency')


# Uso:
# from src.common.metrics import sip_calls_total
# sip_calls_total.labels(status='accepted').inc()
```

---

## 🔐 Configuration Management

```python
# src/common/config.py
from dataclasses import dataclass
from typing import Optional
import yaml

@dataclass
class SIPConfig:
    host: str = '0.0.0.0'
    port: int = 5060
    realm: str = 'voiceagent'
    max_concurrent_calls: int = 100

@dataclass
class RTPConfig:
    port_range_start: int = 10000
    port_range_end: int = 20000
    codec_priority: list = None

    def __post_init__(self):
        if self.codec_priority is None:
            self.codec_priority = ['PCMU', 'PCMA', 'opus']

@dataclass
class AIConfig:
    asr_model: str = 'openai/whisper-large-v3'
    llm_model: str = 'Qwen/Qwen2.5-7B'
    tts_model: str = 'kokoro-tts'
    vad_threshold: float = 0.5

@dataclass
class AppConfig:
    sip: SIPConfig
    rtp: RTPConfig
    ai: AIConfig

    @classmethod
    def from_yaml(cls, path: str) -> 'AppConfig':
        """Load config from YAML file"""
        with open(path) as f:
            data = yaml.safe_load(f)

        return cls(
            sip=SIPConfig(**data.get('sip', {})),
            rtp=RTPConfig(**data.get('rtp', {})),
            ai=AIConfig(**data.get('ai', {}))
        )


# config/default.yaml:
# sip:
#   host: 0.0.0.0
#   port: 5060
#   realm: voiceagent
# rtp:
#   port_range_start: 10000
#   port_range_end: 20000
# ai:
#   asr_model: openai/whisper-large-v3
```

---

## 🚀 Main Application Entry Point

```python
# src/main.py
import asyncio
from src.sip.server import SIPServer
from src.rtp.server import RTPServer
from src.ai.pipeline import Voice2VoicePipeline
from src.orchestrator.call_handler import CallOrchestrator
from src.orchestrator.events import EventBus
from src.common.config import AppConfig
from src.common.logging import StructuredLogger

logger = StructuredLogger('main')


async def main():
    """Application entry point"""

    # 1. Load config
    config = AppConfig.from_yaml('config/default.yaml')
    logger.info('Config loaded', config=str(config))

    # 2. Create event bus
    event_bus = EventBus()

    # 3. Create modules (dependency injection)
    sip_server = SIPServer(
        config=config.sip,
        event_bus=event_bus
    )

    rtp_server = RTPServer(
        config=config.rtp,
        event_bus=event_bus
    )

    ai_pipeline = Voice2VoicePipeline(
        config=config.ai,
        event_bus=event_bus
    )

    # 4. Create orchestrator
    orchestrator = CallOrchestrator(
        sip_server=sip_server,
        rtp_server=rtp_server,
        ai_pipeline=ai_pipeline,
        event_bus=event_bus
    )

    # 5. Start
    try:
        await orchestrator.start()
        logger.info('🚀 AI Voice Agent running')

        # Keep running
        await asyncio.Event().wait()

    except KeyboardInterrupt:
        logger.info('🛑 Shutdown requested')
    finally:
        await orchestrator.stop()
        logger.info('✅ Shutdown complete')


if __name__ == '__main__':
    asyncio.run(main())
```

---

## 📋 Checklist de Implementação

### Módulo 1: SIP Server (Semana 1)
- [ ] `server.py` - SIPServer class com pjsua2
- [ ] `session.py` - CallSession dataclass
- [ ] `auth.py` - Digest authentication
- [ ] `sdp.py` - SDP parser
- [ ] `events.py` - Event emission
- [ ] Tests unitários (90% coverage)

### Módulo 2: RTP Server (Semana 1)
- [ ] `server.py` - RTPServer class
- [ ] `stream.py` - AudioStream implementation
- [ ] `codec.py` - G.711/Opus codec handling
- [ ] `jitter.py` - Jitter buffer
- [ ] Tests unitários (90% coverage)

### Módulo 3: AI Pipeline (Semana 2)
- [ ] `pipeline.py` - Voice2VoicePipeline orchestrator
- [ ] `vad.py` - VAD implementation
- [ ] `asr.py` - Whisper integration
- [ ] `llm.py` - Qwen2.5 integration
- [ ] `tts.py` - Kokoro integration
- [ ] Tests unitários (80% coverage - AI é mais difícil)

### Orchestrator (Semana 2)
- [ ] `call_handler.py` - CallOrchestrator
- [ ] `events.py` - EventBus
- [ ] Integration tests (full call flow)

### Common/Infrastructure (Contínuo)
- [ ] `config.py` - Configuration management
- [ ] `logging.py` - Structured logging
- [ ] `metrics.py` - Prometheus metrics
- [ ] `errors.py` - Custom exceptions

---

## 🎯 Vantagens Desta Arquitetura

### ✅ Testabilidade
- Cada módulo pode ser testado isoladamente
- Mocks fáceis (interfaces bem definidas)
- Integration tests claros (orchestrator)

### ✅ Manutenibilidade
- Mudança em um módulo não afeta outros
- Código organizado por responsabilidade
- Fácil de entender (cada arquivo faz UMA coisa)

### ✅ Substituibilidade
- Quer trocar Whisper por Deepgram? → Só muda `asr.py`
- Quer usar FreeSWITCH em vez de pjsua2? → Só muda `sip/server.py`
- Interface garante compatibilidade

### ✅ Escalabilidade
- Módulos podem rodar em processos separados (futuro)
- Event bus permite distribuição (Redis pub/sub)
- Cada módulo pode ter pool de workers

### ✅ Observabilidade
- Logging estruturado por módulo
- Metrics por módulo (fácil identificar bottleneck)
- Tracing distribuído (OpenTelemetry)

---

## 🚨 Anti-Patterns a Evitar

### ❌ God Object
```python
# ERRADO: Tudo em uma classe
class VoiceAgent:
    def handle_sip(self): ...
    def handle_rtp(self): ...
    def do_asr(self): ...
    def do_llm(self): ...
    def do_tts(self): ...
```

### ❌ Acoplamento Direto
```python
# ERRADO: Módulos conhecem uns aos outros
class SIPServer:
    def __init__(self):
        self.rtp = RTPServer()  # ❌ Tight coupling!
```

### ❌ Shared State Mutable
```python
# ERRADO: Estado compartilhado mutável
global_sessions = {}  # ❌ Race conditions!

class SIPServer:
    def on_invite(self):
        global_sessions[id] = session  # ❌ Não faça isso!
```

### ✅ Faça Assim: Dependency Injection + Imutabilidade
```python
# CERTO: Dependency injection
class SIPServer:
    def __init__(self, event_bus: EventBus):  # ✅ Injected!
        self.bus = event_bus

# CERTO: Immutable state
@dataclass(frozen=True)  # ✅ Immutable!
class CallSession:
    session_id: str
    remote_ip: str
```

---

## 🎓 Próximos Passos

1. **Aprovar esta arquitetura** (você + time)
2. **Criar estrutura de diretórios** (5 min)
3. **Implementar esqueleto de cada módulo** (interfaces apenas - 2h)
4. **Implementar módulo por módulo** (2 semanas)
5. **Integration tests** (garantir que tudo funciona junto)

**Posso começar criando a estrutura de diretórios e os esqueletos de código?** 🚀
