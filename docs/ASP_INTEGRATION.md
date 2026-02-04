# ASP Integration Guide

Guia para integrar o Audio Session Protocol (ASP) em clientes e servidores.

## Estrutura do Módulo

```
shared/
└── asp_protocol/
    ├── __init__.py        # Exports públicos
    ├── enums.py           # Enumerações
    ├── config.py          # Classes de configuração
    ├── messages.py        # Classes de mensagens
    ├── negotiation.py     # Lógica de negociação
    └── errors.py          # Erros pré-definidos
```

## Integração no Servidor (AI Agent)

### 1. Importar o módulo

```python
import sys
sys.path.insert(0, "/path/to/shared")

from asp_protocol import (
    ProtocolCapabilities,
    ProtocolCapabilitiesMessage,
    SessionStartMessage,
    SessionStartedMessage,
    negotiate_config,
    parse_message,
    SessionStatus,
)
```

### 2. Configurar capabilities

```python
class MyServer:
    def __init__(self):
        self.capabilities = ProtocolCapabilities(
            version="1.0.0",
            supported_sample_rates=[8000, 16000],
            supported_encodings=["pcm_s16le"],
            vad_configurable=True,
            vad_parameters=[
                "silence_threshold_ms",
                "min_speech_ms",
                "threshold"
            ],
            features=["barge_in", "streaming_tts"]
        )
```

### 3. Enviar capabilities na conexão

```python
async def handle_connection(self, websocket):
    # Envia capabilities imediatamente
    caps_msg = ProtocolCapabilitiesMessage(
        capabilities=self.capabilities,
        server_id="my-server"
    )
    await websocket.send(caps_msg.to_json())

    # Processa mensagens
    async for message in websocket:
        await self.handle_message(websocket, message)
```

### 4. Processar session.start

```python
async def handle_session_start(self, websocket, msg: SessionStartMessage):
    # Negocia configuração
    result = negotiate_config(
        self.capabilities,
        msg.audio,
        msg.vad
    )

    # Envia resposta
    response = SessionStartedMessage(
        session_id=msg.session_id,
        status=result.status,
        negotiated=result.negotiated if result.success else None,
        errors=result.errors if not result.success else None
    )
    await websocket.send(response.to_json())

    if result.success:
        # Aplica configuração negociada
        self.apply_config(msg.session_id, result.negotiated)
        return True
    return False
```

### 5. Aplicar configuração ao VAD

```python
def apply_config(self, session_id: str, config: NegotiatedConfig):
    # Obtém sessão
    session = self.sessions[session_id]

    # Aplica config de áudio
    session.sample_rate = config.audio.sample_rate
    session.encoding = config.audio.encoding

    # Aplica config de VAD
    session.vad.silence_threshold = config.vad.silence_threshold_ms
    session.vad.min_speech_ms = config.vad.min_speech_ms
    session.vad.threshold = config.vad.threshold
```

## Integração no Cliente (Media Server)

### 1. Importar o módulo

```python
from asp_protocol import (
    AudioConfig,
    VADConfig,
    AudioEncoding,
    SessionStartMessage,
    parse_message,
    is_valid_message,
    ProtocolCapabilitiesMessage,
    SessionStartedMessage,
)
```

### 2. Aguardar capabilities

```python
async def connect(self, url: str):
    self.ws = await websockets.connect(url)

    # Aguarda capabilities (com timeout)
    try:
        data = await asyncio.wait_for(self.ws.recv(), timeout=5.0)

        if is_valid_message(data):
            msg = parse_message(data)
            if isinstance(msg, ProtocolCapabilitiesMessage):
                self.server_caps = msg.capabilities
                self.asp_mode = True
                print(f"Server supports ASP v{msg.capabilities.version}")

    except asyncio.TimeoutError:
        # Servidor legado
        self.asp_mode = False
        print("Legacy server (no ASP)")
```

### 3. Enviar session.start

```python
async def start_session(self, session_id: str):
    # Cria configuração
    audio = AudioConfig(
        sample_rate=8000,
        encoding=AudioEncoding.PCM_S16LE
    )

    vad = VADConfig(
        silence_threshold_ms=500,
        min_speech_ms=250,
        threshold=0.5
    )

    # Envia session.start
    msg = SessionStartMessage(
        session_id=session_id,
        audio=audio,
        vad=vad
    )
    await self.ws.send(msg.to_json())

    # Aguarda resposta
    response_data = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
    response = parse_message(response_data)

    if isinstance(response, SessionStartedMessage):
        if response.is_accepted:
            self.negotiated_config = response.negotiated
            return True
        else:
            print(f"Session rejected: {response.errors}")

    return False
```

### 4. Usar configuração negociada

```python
def get_vad_config(self):
    if self.asp_mode and self.negotiated_config:
        vad = self.negotiated_config.vad
        return {
            "silence_threshold_ms": vad.silence_threshold_ms,
            "min_speech_ms": vad.min_speech_ms,
            "threshold": vad.threshold,
            "ring_buffer_frames": vad.ring_buffer_frames,
            "speech_ratio": vad.speech_ratio,
        }
    else:
        # Fallback para defaults
        return {
            "silence_threshold_ms": 500,
            "min_speech_ms": 250,
            "threshold": 0.5,
        }
```

## Atualização de Configuração Mid-Session

```python
async def update_vad(self, session_id: str, new_threshold: float):
    from asp_protocol import SessionUpdateMessage, VADConfig

    msg = SessionUpdateMessage(
        session_id=session_id,
        vad=VADConfig(threshold=new_threshold)
    )
    await self.ws.send(msg.to_json())

    response_data = await self.ws.recv()
    response = parse_message(response_data)

    if response.status == SessionStatus.ACCEPTED:
        self.negotiated_config = response.negotiated
        return True
    return False
```

## Tratamento de Erros

```python
from asp_protocol import errors

async def handle_error(self, error_code: int, session_id: str):
    if error_code == errors.ERROR_HANDSHAKE_TIMEOUT:
        # Reconecta
        await self.reconnect()

    elif error_code == errors.ERROR_UNSUPPORTED_SAMPLE_RATE:
        # Tenta com sample rate diferente
        await self.start_session_with_fallback(session_id)

    elif error_code == errors.ERROR_SESSION_EXPIRED:
        # Inicia nova sessão
        await self.start_new_session()
```

## Backwards Compatibility

### Detectando modo legado (cliente)

```python
async def connect(self):
    self.ws = await websockets.connect(url)

    # Tenta receber capabilities
    try:
        data = await asyncio.wait_for(self.ws.recv(), timeout=5.0)
        if is_valid_message(data):
            # Modo ASP
            self.asp_mode = True
        else:
            # Dados legados
            self.asp_mode = False
            # Reprocessa dados recebidos
            await self.handle_legacy_message(data)
    except asyncio.TimeoutError:
        # Servidor legado
        self.asp_mode = False
```

### Suportando clientes legados (servidor)

```python
async def handle_message(self, websocket, message):
    try:
        # Tenta parsear como ASP
        if is_valid_message(message):
            msg = parse_message(message)
            await self.handle_asp_message(websocket, msg)
        else:
            # Fallback: protocolo legado
            await self.handle_legacy_message(websocket, message)
    except Exception:
        await self.handle_legacy_message(websocket, message)
```

## Testes

### Teste de handshake

```python
import pytest
from asp_protocol import (
    ProtocolCapabilities,
    AudioConfig,
    VADConfig,
    negotiate_config,
    SessionStatus,
)

def test_negotiation_success():
    caps = ProtocolCapabilities(supported_sample_rates=[8000, 16000])
    audio = AudioConfig(sample_rate=8000)
    vad = VADConfig()

    result = negotiate_config(caps, audio, vad)

    assert result.success
    assert result.status == SessionStatus.ACCEPTED

def test_negotiation_with_adjustment():
    caps = ProtocolCapabilities()
    vad = VADConfig(threshold=1.5)  # Acima do máximo

    result = negotiate_config(caps, None, vad)

    assert result.success
    assert result.status == SessionStatus.ACCEPTED_WITH_CHANGES
    assert result.negotiated.vad.threshold == 1.0  # Ajustado
```

## Checklist de Integração

- [ ] Módulo `asp_protocol` acessível no path
- [ ] Servidor envia `protocol.capabilities` na conexão
- [ ] Cliente aguarda capabilities com timeout
- [ ] Cliente envia `session.start` com config desejada
- [ ] Servidor negocia e responde `session.started`
- [ ] Configuração negociada aplicada ao VAD
- [ ] Suporte a clientes/servidores legados
- [ ] Métricas de handshake implementadas
- [ ] Logs de config negociada
- [ ] Testes de integração passando
