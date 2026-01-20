# Common Module

**Responsabilidade:** Utilitários compartilhados entre todos os módulos

---

## 🎯 O Que Este Módulo Faz

O módulo Common fornece utilitários que TODOS os módulos podem usar:

1. ✅ Logging estruturado (JSON)
2. ✅ Métricas Prometheus
3. ✅ Gerenciamento de configuração
4. ✅ Custom exceptions
5. ✅ Helpers compartilhados

---

## 📦 Arquivos

```
common/
├── README.md           # Este arquivo
├── __init__.py         # Exports públicos
├── config.py           # Configuration management
├── logging.py          # Structured logging
├── metrics.py          # Prometheus metrics
└── errors.py           # Custom exceptions
```

---

## 📝 Logging Estruturado

```python
# src/common/logging.py

import logging
import json
import sys
from typing import Any, Dict
from datetime import datetime

class StructuredLogger:
    """
    JSON structured logging

    Formato:
    {
        "timestamp": "2026-01-20T10:30:45.123Z",
        "module": "sip.server",
        "level": "INFO",
        "message": "Call established",
        "session_id": "abc-123",
        "duration": 45.2
    }
    """

    def __init__(self, module_name: str, level: str = 'INFO'):
        self.module = module_name
        self.logger = logging.getLogger(module_name)
        self.logger.setLevel(getattr(logging, level))

        # Configurar handler para stdout
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        self.logger.addHandler(handler)

    def info(self, message: str, **kwargs):
        """Log INFO message"""
        self._log('INFO', message, kwargs)

    def warning(self, message: str, **kwargs):
        """Log WARNING message"""
        self._log('WARNING', message, kwargs)

    def error(self, message: str, **kwargs):
        """Log ERROR message"""
        self._log('ERROR', message, kwargs)

    def debug(self, message: str, **kwargs):
        """Log DEBUG message"""
        self._log('DEBUG', message, kwargs)

    def _log(self, level: str, message: str, context: Dict[str, Any]):
        """Internal log method"""
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'module': self.module,
            'level': level,
            'message': message,
            **context
        }

        # Log como JSON
        log_method = getattr(self.logger, level.lower())
        log_method(json.dumps(log_entry))


class JsonFormatter(logging.Formatter):
    """Custom formatter para output JSON"""

    def format(self, record):
        # Já vem formatado como JSON do StructuredLogger
        return record.getMessage()


def get_logger(module_name: str) -> StructuredLogger:
    """
    Factory para criar loggers

    Usage:
        from src.common.logging import get_logger
        logger = get_logger('sip.server')
        logger.info('Call established', session_id='abc-123')
    """
    return StructuredLogger(module_name)
```

---

## 📊 Prometheus Metrics

```python
# src/common/metrics.py

from prometheus_client import Counter, Histogram, Gauge, Summary
from prometheus_client import start_http_server

# ===== SIP METRICS =====

sip_calls_total = Counter(
    'sip_calls_total',
    'Total SIP calls',
    ['status']  # accepted, rejected, timeout
)

sip_auth_attempts_total = Counter(
    'sip_auth_attempts_total',
    'Authentication attempts',
    ['result']  # success, failed
)

sip_active_calls = Gauge(
    'sip_active_calls',
    'Currently active calls'
)

sip_call_duration_seconds = Histogram(
    'sip_call_duration_seconds',
    'Call duration in seconds',
    buckets=[10, 30, 60, 120, 300, 600, 1800, 3600]  # 10s a 1h
)

# ===== RTP METRICS =====

rtp_packets_sent_total = Counter(
    'rtp_packets_sent_total',
    'RTP packets sent'
)

rtp_packets_received_total = Counter(
    'rtp_packets_received_total',
    'RTP packets received'
)

rtp_packet_loss_percent = Gauge(
    'rtp_packet_loss_percent',
    'Packet loss percentage',
    ['session_id']
)

rtp_jitter_ms = Histogram(
    'rtp_jitter_ms',
    'RTP jitter in milliseconds',
    buckets=[5, 10, 20, 50, 100, 200]
)

rtp_codec_usage = Counter(
    'rtp_codec_usage',
    'Codec usage count',
    ['codec']  # PCMU, PCMA, opus
)

# ===== AI METRICS =====

asr_latency_seconds = Histogram(
    'asr_latency_seconds',
    'ASR transcription latency',
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0]
)

llm_latency_seconds = Histogram(
    'llm_latency_seconds',
    'LLM generation latency',
    buckets=[1.0, 2.0, 5.0, 10.0, 20.0]
)

tts_latency_seconds = Histogram(
    'tts_latency_seconds',
    'TTS synthesis latency',
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0]
)

voice_pipeline_latency_seconds = Summary(
    'voice_pipeline_latency_seconds',
    'Total voice pipeline latency (ASR+LLM+TTS)'
)

vad_speech_segments_total = Counter(
    'vad_speech_segments_total',
    'Speech segments detected by VAD'
)

vad_false_positives_total = Counter(
    'vad_false_positives_total',
    'VAD detected speech but ASR returned empty'
)

# ===== ORCHESTRATOR METRICS =====

orchestrator_active_calls = Gauge(
    'orchestrator_active_calls',
    'Currently active calls in orchestrator'
)

orchestrator_total_calls_total = Counter(
    'orchestrator_total_calls_total',
    'Total calls handled by orchestrator'
)

event_bus_events_published_total = Counter(
    'event_bus_events_published_total',
    'Events published to event bus',
    ['type']
)

event_bus_callback_errors_total = Counter(
    'event_bus_callback_errors_total',
    'Callback errors in event bus'
)


def start_metrics_server(port: int = 8000):
    """
    Start Prometheus metrics HTTP server

    Metrics will be available at http://localhost:8000/metrics

    Usage:
        from src.common.metrics import start_metrics_server
        start_metrics_server(port=8000)
    """
    start_http_server(port)
```

---

## ⚙️ Configuration Management

```python
# src/common/config.py

from dataclasses import dataclass, field
from typing import List, Optional
import yaml
import os

@dataclass
class SIPConfig:
    """SIP Server configuration"""
    host: str = '0.0.0.0'
    port: int = 5060
    realm: str = 'voiceagent'
    max_concurrent_calls: int = 100
    ringing_timeout: int = 60  # seconds

    # Trunks
    trunks: List[dict] = field(default_factory=list)

    # IP whitelist
    ip_whitelist: List[str] = field(default_factory=list)


@dataclass
class RTPConfig:
    """RTP Server configuration"""
    port_range_start: int = 10000
    port_range_end: int = 20000

    # Codecs (in preference order)
    codec_priority: List[str] = field(
        default_factory=lambda: ['PCMU', 'PCMA', 'opus']
    )

    # Jitter buffer
    jitter_buffer_ms: int = 60
    jitter_buffer_max_ms: int = 200

    # DTMF
    dtmf_detection: bool = True
    dtmf_min_duration_ms: int = 40

    # Timeouts
    rtp_timeout_ms: int = 5000


@dataclass
class AIConfig:
    """AI Pipeline configuration"""
    # ASR
    asr_model: str = 'openai/whisper-large-v3'
    asr_language: str = 'pt'

    # LLM
    llm_model: str = 'Qwen/Qwen2.5-7B'
    llm_max_tokens: int = 256
    llm_temperature: float = 0.7

    # TTS
    tts_model: str = 'kokoro-tts'
    tts_voice: str = 'af_bella'
    tts_speed: float = 1.0

    # VAD
    vad_threshold: float = 0.5
    vad_min_speech_duration_ms: int = 300

    # System prompt
    system_prompt: Optional[str] = None


@dataclass
class AppConfig:
    """Application configuration"""
    sip: SIPConfig
    rtp: RTPConfig
    ai: AIConfig

    # Logging
    log_level: str = 'INFO'

    # Metrics
    metrics_port: int = 8000

    @classmethod
    def from_yaml(cls, path: str) -> 'AppConfig':
        """
        Load configuration from YAML file

        Args:
            path: Path to YAML config file

        Returns:
            AppConfig instance

        Example:
            config = AppConfig.from_yaml('config/default.yaml')
        """
        with open(path) as f:
            data = yaml.safe_load(f)

        return cls(
            sip=SIPConfig(**data.get('sip', {})),
            rtp=RTPConfig(**data.get('rtp', {})),
            ai=AIConfig(**data.get('ai', {})),
            log_level=data.get('log_level', 'INFO'),
            metrics_port=data.get('metrics_port', 8000)
        )

    @classmethod
    def from_env(cls) -> 'AppConfig':
        """
        Load configuration from environment variables

        Environment variables override YAML config:
        - SIP_HOST, SIP_PORT, SIP_REALM
        - RTP_PORT_START, RTP_PORT_END
        - ASR_MODEL, LLM_MODEL, TTS_MODEL
        - LOG_LEVEL, METRICS_PORT

        Example:
            export SIP_PORT=5061
            export ASR_MODEL=openai/whisper-base
            config = AppConfig.from_env()
        """
        return cls(
            sip=SIPConfig(
                host=os.getenv('SIP_HOST', '0.0.0.0'),
                port=int(os.getenv('SIP_PORT', '5060')),
                realm=os.getenv('SIP_REALM', 'voiceagent')
            ),
            rtp=RTPConfig(
                port_range_start=int(os.getenv('RTP_PORT_START', '10000')),
                port_range_end=int(os.getenv('RTP_PORT_END', '20000'))
            ),
            ai=AIConfig(
                asr_model=os.getenv('ASR_MODEL', 'openai/whisper-large-v3'),
                llm_model=os.getenv('LLM_MODEL', 'Qwen/Qwen2.5-7B'),
                tts_model=os.getenv('TTS_MODEL', 'kokoro-tts')
            ),
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            metrics_port=int(os.getenv('METRICS_PORT', '8000'))
        )

    def validate(self) -> List[str]:
        """
        Validate configuration

        Returns:
            List of validation errors (empty if valid)

        Example:
            config = AppConfig.from_yaml('config.yaml')
            errors = config.validate()
            if errors:
                for error in errors:
                    print(f"Config error: {error}")
                sys.exit(1)
        """
        errors = []

        # Validate SIP
        if self.sip.port < 1 or self.sip.port > 65535:
            errors.append(f"Invalid SIP port: {self.sip.port}")

        # Validate RTP
        if self.rtp.port_range_start >= self.rtp.port_range_end:
            errors.append("RTP port_range_start must be < port_range_end")

        if self.rtp.port_range_end - self.rtp.port_range_start < 100:
            errors.append("RTP port range must be at least 100 ports")

        # Validate AI
        if self.ai.vad_threshold < 0 or self.ai.vad_threshold > 1:
            errors.append(f"VAD threshold must be 0.0-1.0, got {self.ai.vad_threshold}")

        if self.ai.llm_temperature < 0 or self.ai.llm_temperature > 2:
            errors.append(f"LLM temperature must be 0.0-2.0, got {self.ai.llm_temperature}")

        return errors
```

---

## 🚨 Custom Exceptions

```python
# src/common/errors.py

class VoiceAgentError(Exception):
    """Base exception for voice agent"""
    pass


# ===== SIP ERRORS =====

class SIPError(VoiceAgentError):
    """Base SIP error"""
    pass

class AuthenticationError(SIPError):
    """Authentication failed"""
    pass

class SDPParsingError(SIPError):
    """SDP parsing failed"""
    pass

class CallLimitExceededError(SIPError):
    """Max concurrent calls exceeded"""
    pass


# ===== RTP ERRORS =====

class RTPError(VoiceAgentError):
    """Base RTP error"""
    pass

class StreamClosedError(RTPError):
    """Stream is closed"""
    pass

class CodecError(RTPError):
    """Codec operation failed"""
    pass

class PortAllocationError(RTPError):
    """Failed to allocate RTP port"""
    pass


# ===== AI ERRORS =====

class AIError(VoiceAgentError):
    """Base AI error"""
    pass

class ASRError(AIError):
    """ASR transcription failed"""
    pass

class LLMError(AIError):
    """LLM generation failed"""
    pass

class TTSError(AIError):
    """TTS synthesis failed"""
    pass

class VADError(AIError):
    """VAD detection failed"""
    pass


# ===== ORCHESTRATOR ERRORS =====

class OrchestratorError(VoiceAgentError):
    """Base orchestrator error"""
    pass

class CallSetupError(OrchestratorError):
    """Call setup failed"""
    pass

class CallCleanupError(OrchestratorError):
    """Call cleanup failed"""
    pass
```

---

## 🧪 Uso dos Utilitários

### Logging

```python
from src.common.logging import get_logger

logger = get_logger('sip.server')

# Info
logger.info('Call established', session_id='abc-123', codec='PCMU')

# Warning
logger.warning('High packet loss', session_id='abc-123', loss=0.15)

# Error
logger.error('SDP parsing failed', sdp=sdp_body, error=str(e))

# Output (JSON):
# {"timestamp":"2026-01-20T10:30:45.123Z","module":"sip.server","level":"INFO","message":"Call established","session_id":"abc-123","codec":"PCMU"}
```

---

### Metrics

```python
from src.common.metrics import sip_calls_total, sip_call_duration_seconds

# Incrementar contador
sip_calls_total.labels(status='accepted').inc()

# Observar duração
with sip_call_duration_seconds.time():
    # ... chamada acontece ...
    pass

# Ou manual
start = time.time()
# ... chamada ...
duration = time.time() - start
sip_call_duration_seconds.observe(duration)
```

---

### Configuration

```python
from src.common.config import AppConfig

# Carregar de YAML
config = AppConfig.from_yaml('config/default.yaml')

# Validar
errors = config.validate()
if errors:
    for error in errors:
        print(f"Config error: {error}")
    sys.exit(1)

# Usar
print(f"SIP listening on {config.sip.host}:{config.sip.port}")
print(f"Using ASR model: {config.ai.asr_model}")
```

---

### Exceptions

```python
from src.common.errors import AuthenticationError, StreamClosedError

# Raise
if not valid:
    raise AuthenticationError("Invalid credentials")

# Catch específico
try:
    await stream.send(audio)
except StreamClosedError:
    logger.warning("Stream closed, cannot send audio")
    # Cleanup...

# Catch genérico
except VoiceAgentError as e:
    logger.error("Voice agent error", error=str(e))
```

---

## ✅ Checklist de Implementação

- [ ] `logging.py` - StructuredLogger
- [ ] `metrics.py` - Prometheus metrics
- [ ] `config.py` - Configuration management
- [ ] `errors.py` - Custom exceptions
- [ ] Testes unitários
- [ ] Documentação de uso

---

**Status:** 🚧 Em implementação
**Owner:** Time de Platform Engineering
