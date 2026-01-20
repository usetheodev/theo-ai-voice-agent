# Orchestrator Module

**Responsabilidade:** Orquestrar comunicação entre SIP, RTP e AI módulos

---

## 🎯 O Que Este Módulo Faz

O Orchestrator é o **único** módulo que conhece todos os outros. Ele:

1. ✅ Conecta eventos do SIP Server com RTP Server
2. ✅ Conecta RTP streams com AI Pipeline
3. ✅ Gerencia lifecycle de chamadas (setup → active → teardown)
4. ✅ Implementa Event Bus para comunicação desacoplada
5. ✅ Garante que recursos sejam liberados corretamente

---

## 📦 Arquivos

```
orchestrator/
├── README.md           # Este arquivo
├── __init__.py         # Exports públicos
├── call_handler.py     # CallOrchestrator (main)
└── events.py           # EventBus + Event types
```

---

## 🎭 CallOrchestrator

```python
# src/orchestrator/call_handler.py

class CallOrchestrator:
    """
    Orquestrador principal: conecta SIP + RTP + AI

    Responsabilidades:
    - Registrar callbacks em EventBus
    - Coordenar lifecycle de chamadas
    - Garantir cleanup correto
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

        # Active calls tracking
        self.active_calls: Dict[str, dict] = {}

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

        # RTP events
        self.bus.subscribe(
            EventType.RTP_STREAM_ENDED,
            self._handle_rtp_stream_ended
        )

    async def _handle_call_established(self, event: Event):
        """
        Workflow quando SIP aceita chamada:
        1. SIP Server aceita INVITE → emite CALL_ESTABLISHED
        2. RTP Server cria stream
        3. AI Pipeline inicia processamento
        """
        session = event.data['session']
        session_id = session.session_id

        logger = get_logger('orchestrator')
        logger.info('Call established', session_id=session_id)

        try:
            # 1. Criar RTP stream
            stream = await self.rtp.create_stream(session)
            logger.info('RTP stream created', session_id=session_id)

            # Track call
            self.active_calls[session_id] = {
                'session': session,
                'stream': stream,
                'started_at': time.time()
            }

            # 2. Iniciar AI pipeline (non-blocking)
            asyncio.create_task(
                self._run_ai_pipeline(session_id, stream)
            )

            logger.info('AI pipeline started', session_id=session_id)

        except Exception as e:
            logger.error('Error handling call', session_id=session_id, error=str(e))

            # Cleanup: hangup call
            await self.sip.hangup(session_id)

    async def _run_ai_pipeline(self, session_id: str, stream: AudioStream):
        """Run AI pipeline for a call (background task)"""
        logger = get_logger('orchestrator')

        try:
            await self.ai.process_call(stream)

        except Exception as e:
            logger.error('AI pipeline error', session_id=session_id, error=str(e))

        finally:
            # Pipeline terminou → cleanup
            logger.info('AI pipeline ended', session_id=session_id)

            # Se call ainda ativa, fazer hangup
            if session_id in self.active_calls:
                await self.sip.hangup(session_id)

    async def _handle_call_ended(self, event: Event):
        """
        Cleanup quando chamada termina (BYE recebido)
        """
        session_id = event.data['session_id']
        logger = get_logger('orchestrator')
        logger.info('Call ended', session_id=session_id)

        # Cleanup RTP stream
        await self.rtp.close_stream(session_id)

        # Remove from tracking
        if session_id in self.active_calls:
            call_info = self.active_calls.pop(session_id)
            duration = time.time() - call_info['started_at']
            logger.info('Call cleanup complete', session_id=session_id, duration=duration)

    async def _handle_rtp_stream_ended(self, event: Event):
        """
        RTP stream terminou (timeout ou erro)
        """
        session_id = event.data['session_id']
        logger = get_logger('orchestrator')
        logger.info('RTP stream ended', session_id=session_id)

        # Fazer hangup se call ainda ativa
        if session_id in self.active_calls:
            await self.sip.hangup(session_id)

    async def start(self):
        """Start all modules"""
        logger = get_logger('orchestrator')
        logger.info('Starting orchestrator...')

        # Start modules in order
        await self.sip.start()
        await self.rtp.start()
        await self.ai.start()

        logger.info('All modules started')

    async def stop(self):
        """Stop all modules gracefully"""
        logger = get_logger('orchestrator')
        logger.info('Stopping orchestrator...')

        # Hangup all active calls
        for session_id in list(self.active_calls.keys()):
            await self.sip.hangup(session_id)

        # Stop modules in reverse order
        await self.ai.stop()
        await self.rtp.stop()
        await self.sip.stop()

        logger.info('All modules stopped')

    def get_stats(self) -> dict:
        """
        Retorna estatísticas do orchestrator

        Returns:
            {
                'active_calls': 5,
                'total_calls': 123,
                'avg_call_duration': 45.2
            }
        """
        return {
            'active_calls': len(self.active_calls),
            'calls': list(self.active_calls.keys())
        }
```

---

## 🚌 Event Bus

Sistema Pub/Sub para comunicação desacoplada.

```python
# src/orchestrator/events.py

from enum import Enum
from dataclasses import dataclass
from typing import Any, Callable, Dict, List
import asyncio
import time

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
    VAD_SPEECH_DETECTED = "vad.speech.detected"


@dataclass
class Event:
    """Evento genérico"""
    type: EventType
    data: Dict[str, Any]
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class EventBus:
    """
    Pub/Sub event bus

    Permite comunicação desacoplada entre módulos:
    - Módulos publicam eventos (publish)
    - Outros módulos subscrevem eventos (subscribe)
    - EventBus roteia eventos para subscribers
    """

    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._event_history: List[Event] = []  # Para debug
        self._max_history = 100

    def subscribe(self, event_type: EventType, callback: Callable) -> None:
        """
        Subscribe to an event

        Args:
            event_type: Tipo de evento
            callback: Função async a ser chamada quando evento ocorrer
                      Signature: async def callback(event: Event) -> None

        Example:
            async def on_call_established(event: Event):
                session = event.data['session']
                print(f"Call: {session.session_id}")

            bus.subscribe(EventType.CALL_ESTABLISHED, on_call_established)
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []

        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable) -> None:
        """Unsubscribe from an event"""
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(callback)

    async def publish(self, event: Event) -> None:
        """
        Publish event to all subscribers

        Args:
            event: Event to publish

        Example:
            await bus.publish(Event(
                type=EventType.CALL_ESTABLISHED,
                data={'session': session}
            ))
        """
        # Store in history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)

        # Notify subscribers
        if event.type in self._subscribers:
            tasks = []
            for callback in self._subscribers[event.type]:
                # Run callback async (non-blocking)
                task = asyncio.create_task(
                    self._safe_callback(callback, event)
                )
                tasks.append(task)

            # Wait all callbacks (with timeout)
            if tasks:
                await asyncio.wait(tasks, timeout=5.0)

    async def _safe_callback(self, callback: Callable, event: Event):
        """Run callback with error handling"""
        try:
            await callback(event)
        except Exception as e:
            logger = get_logger('event_bus')
            logger.error(
                'Callback error',
                event_type=event.type.value,
                error=str(e)
            )

    def get_history(self, event_type: EventType = None) -> List[Event]:
        """
        Get event history (for debug)

        Args:
            event_type: Filter by event type (optional)

        Returns:
            List of recent events
        """
        if event_type:
            return [e for e in self._event_history if e.type == event_type]
        return self._event_history.copy()

    def get_stats(self) -> dict:
        """
        Get event bus statistics

        Returns:
            {
                'total_subscribers': 8,
                'events_processed': 123,
                'events_by_type': {
                    'call.established': 45,
                    'call.ended': 45,
                    ...
                }
            }
        """
        total_subscribers = sum(
            len(callbacks) for callbacks in self._subscribers.values()
        )

        events_by_type = {}
        for event in self._event_history:
            key = event.type.value
            events_by_type[key] = events_by_type.get(key, 0) + 1

        return {
            'total_subscribers': total_subscribers,
            'events_processed': len(self._event_history),
            'events_by_type': events_by_type
        }
```

---

## 📊 Fluxo Completo de Chamada

```
1. User liga → SIP INVITE
   ├─> SIP Server recebe INVITE
   └─> Publica: CALL_INVITE_RECEIVED

2. SIP Server autentica e aceita
   ├─> Responde 200 OK
   └─> Publica: CALL_ESTABLISHED {session}

3. Orchestrator recebe CALL_ESTABLISHED
   ├─> Chama: rtp.create_stream(session)
   ├─> Publica: RTP_STREAM_STARTED
   └─> Chama: ai.process_call(stream) [background]

4. AI Pipeline processa áudio
   ├─> VAD detecta fala → Publica: VAD_SPEECH_DETECTED
   ├─> ASR transcreve → Publica: ASR_TRANSCRIPTION_READY
   ├─> LLM responde → Publica: LLM_RESPONSE_READY
   └─> TTS sintetiza → Publica: TTS_AUDIO_READY

5. User desliga → SIP BYE
   ├─> SIP Server recebe BYE
   └─> Publica: CALL_ENDED {session_id}

6. Orchestrator recebe CALL_ENDED
   ├─> Chama: rtp.close_stream(session_id)
   ├─> Stream fecha → AI Pipeline para
   └─> Cleanup completo
```

---

## 🧪 Testes

### Teste de Orquestração Completa

```python
# tests/integration/test_full_call_flow.py
import pytest
from src.orchestrator import CallOrchestrator, EventBus
from src.sip import SIPServer
from src.rtp import RTPServer
from src.ai import Voice2VoicePipeline

@pytest.mark.asyncio
async def test_full_call_lifecycle():
    """Test: Lifecycle completo de chamada (setup → active → teardown)"""

    # Setup
    event_bus = EventBus()
    sip = SIPServer(event_bus=event_bus)
    rtp = RTPServer(event_bus=event_bus)
    ai = Voice2VoicePipeline()

    orchestrator = CallOrchestrator(sip, rtp, ai, event_bus)
    await orchestrator.start()

    # Simulate call
    # 1. SIP INVITE
    # 2. Verificar se RTP stream foi criado
    # 3. Verificar se AI pipeline iniciou
    # 4. Simulate BYE
    # 5. Verificar se cleanup ocorreu

    # Cleanup
    await orchestrator.stop()

    # Assert
    assert orchestrator.get_stats()['active_calls'] == 0
```

---

## 📊 Métricas

```python
# Orchestrator metrics
orchestrator_active_calls 5
orchestrator_total_calls_total 123

# Event bus metrics
event_bus_subscribers_total 8
event_bus_events_published_total{type="call.established"} 123
event_bus_callback_errors_total 2
```

---

## 🔧 Troubleshooting

### Problema: Evento não é recebido

**Debug:**
```python
# Verificar subscribers
stats = event_bus.get_stats()
print(stats)

# Verificar histórico de eventos
history = event_bus.get_history(EventType.CALL_ESTABLISHED)
for event in history:
    print(f"{event.timestamp}: {event.data}")
```

**Solução:**
- Verificar se callback foi registrado corretamente
- Verificar se callback é async (não sync!)

---

### Problema: Chamada não termina corretamente

**Debug:**
```python
# Verificar chamadas ativas
stats = orchestrator.get_stats()
print(f"Active calls: {stats['active_calls']}")
print(f"Calls: {stats['calls']}")
```

**Solução:**
- Verificar se BYE foi recebido pelo SIP
- Verificar se RTP stream fechou corretamente
- Adicionar timeout para chamadas (force cleanup após X minutos)

---

## ✅ Checklist de Implementação

- [ ] `call_handler.py` - CallOrchestrator
- [ ] `events.py` - EventBus + EventType
- [ ] Testes de integração (full call flow)
- [ ] Métricas de orchestrator
- [ ] Timeout de chamadas (force cleanup)
- [ ] Graceful shutdown (hangup all active calls)

---

**Status:** 🚧 Em implementação
**Owner:** Time de Platform Engineering
