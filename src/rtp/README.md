# RTP Server Module

**Responsabilidade:** Gerenciar streams de áudio RTP/RTCP

---

## 🎯 O Que Este Módulo Faz

O módulo RTP Server é responsável por:

1. ✅ Receber pacotes RTP de endpoints remotos
2. ✅ Decodificar áudio (G.711, Opus, etc.) → PCM raw
3. ✅ Codificar PCM raw → áudio comprimido
4. ✅ Enviar pacotes RTP para endpoints remotos
5. ✅ Gerenciar jitter buffer (compensar variação de latência)
6. ✅ Detectar DTMF (tons de telefone)
7. ✅ Fornecer interface AudioStream para AI Pipeline

---

## 📦 Arquivos

```
rtp/
├── README.md           # Este arquivo
├── __init__.py         # Exports públicos
├── server.py           # RTPServer class (main)
├── stream.py           # AudioStream implementation
├── codec.py            # Codec handlers (G.711, Opus)
├── jitter.py           # Jitter buffer
├── dtmf.py             # DTMF detection
└── stats.py            # RTP statistics (packet loss, jitter)
```

---

## 🔌 Interface Pública

### RTPServer

```python
from src.rtp import RTPServer
from src.sip.session import CallSession, CallStatus

# Criar servidor RTP
rtp_server = RTPServer(
    port_range_start=10000,
    port_range_end=20000,
    codec_priority=['PCMU', 'PCMA', 'opus']
)

# Criar stream para uma chamada
session = CallSession(
    session_id='abc-123',
    remote_ip='192.168.1.100',
    remote_port=10000,
    codec='PCMU',
    status=CallStatus.ACTIVE,
    local_port=20000
)

stream = await rtp_server.create_stream(session)

# Usar stream
audio_chunk = await stream.receive()  # bytes (PCM 16-bit, 8kHz)
await stream.send(audio_chunk)        # Enviar de volta

# Fechar stream
await rtp_server.close_stream(session.session_id)
```

---

## 🎤 AudioStream Interface

Interface consumida pelo AI Pipeline.

```python
from abc import ABC, abstractmethod

class AudioStream(ABC):
    """
    Stream bidirecional de áudio PCM
    """

    @abstractmethod
    async def receive(self) -> bytes:
        """
        Recebe chunk de áudio (blocking)

        Returns:
            bytes: PCM 16-bit, 8kHz, mono (160 bytes = 20ms)

        Raises:
            StreamClosedError: Se stream foi fechado
        """
        pass

    @abstractmethod
    async def send(self, pcm_data: bytes) -> None:
        """
        Envia chunk de áudio

        Args:
            pcm_data: PCM 16-bit, 8kHz, mono

        Raises:
            StreamClosedError: Se stream foi fechado
            CodecError: Se encoding falhar
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Fecha stream gracefully"""
        pass

    @property
    @abstractmethod
    def is_active(self) -> bool:
        """Verifica se stream ainda está ativo"""
        pass

    @property
    @abstractmethod
    def stats(self) -> dict:
        """
        Retorna estatísticas do stream

        Returns:
            {
                'packets_sent': 1234,
                'packets_received': 1230,
                'packets_lost': 4,
                'jitter_ms': 12.5,
                'codec': 'PCMU'
            }
        """
        pass
```

---

## 🎵 Codecs Suportados

### G.711 (PCMU/PCMA)

```python
# G.711 μ-law (PCMU) - Padrão nos EUA
codec = G711UCodec()
encoded = codec.encode(pcm_data)  # PCM → G.711
decoded = codec.decode(encoded)   # G.711 → PCM

# Características:
# - Taxa: 64 kbps
# - Sample rate: 8 kHz
# - Latência baixíssima
# - Qualidade: boa para voz
```

### Opus (futuro)

```python
# Opus - Codec moderno
codec = OpusCodec(bitrate=32000)
encoded = codec.encode(pcm_data)
decoded = codec.decode(encoded)

# Características:
# - Taxa: 6-510 kbps (configurável)
# - Sample rate: 8-48 kHz
# - Latência baixa
# - Qualidade: excelente
```

---

## 📊 Jitter Buffer

Compensa variação de latência de rede.

```python
# src/rtp/jitter.py

class JitterBuffer:
    """
    Buffer adaptativo para compensar jitter de rede
    """

    def __init__(self, target_delay_ms: int = 60):
        """
        Args:
            target_delay_ms: Delay alvo do buffer (padrão 60ms)
        """
        self.target_delay = target_delay_ms
        self.buffer = []

    def add(self, packet: RTPPacket) -> None:
        """Adiciona packet ao buffer (ordenado por timestamp)"""
        pass

    def get(self) -> Optional[RTPPacket]:
        """
        Retorna próximo packet (se disponível)

        Strategy:
        - Se buffer < target_delay: espera
        - Se buffer > target_delay * 2: descarta packets antigos
        """
        pass

    def get_stats(self) -> dict:
        """
        Returns:
            {
                'buffer_size_ms': 65,
                'packets_dropped': 3,
                'avg_jitter_ms': 12.5
            }
        """
        pass
```

---

## 📞 DTMF Detection

Detecta tons de telefone (0-9, *, #).

```python
# src/rtp/dtmf.py

class DTMFDetector:
    """
    Detecta DTMF (Dual-Tone Multi-Frequency)
    """

    def detect(self, pcm_data: bytes) -> Optional[str]:
        """
        Detecta DTMF em chunk de áudio

        Returns:
            str: Dígito detectado ('0'-'9', '*', '#')
            None: Nenhum DTMF detectado

        Example:
            detector = DTMFDetector()
            digit = detector.detect(audio_chunk)
            if digit:
                print(f"User pressed: {digit}")
        """
        pass
```

**Uso no AI Pipeline:**

```python
# Exemplo: IVR (menu de opções)
dtmf = DTMFDetector()

async for audio_chunk in stream.receive():
    digit = dtmf.detect(audio_chunk)

    if digit:
        if digit == '1':
            await play_audio(stream, 'option1.wav')
        elif digit == '2':
            await play_audio(stream, 'option2.wav')
```

---

## 🧪 Testes

### Teste Unitário

```python
# tests/unit/test_rtp_server.py
import pytest
from src.rtp import RTPServer
from src.sip.session import CallSession, CallStatus

@pytest.mark.asyncio
async def test_rtp_creates_stream():
    """Test: RTP server cria stream corretamente"""

    rtp = RTPServer(port_range_start=10000, port_range_end=10100)

    session = CallSession(
        session_id='test-123',
        remote_ip='127.0.0.1',
        remote_port=10000,
        codec='PCMU',
        status=CallStatus.ACTIVE,
        local_port=10050
    )

    stream = await rtp.create_stream(session)

    # Assert
    assert stream is not None
    assert stream.is_active is True

    # Test send
    pcm_silence = b'\x00' * 160  # 20ms de silêncio
    await stream.send(pcm_silence)

    # Cleanup
    await rtp.close_stream(session.session_id)
    assert stream.is_active is False
```

### Teste de Codec

```python
# tests/unit/test_codec.py
import pytest
from src.rtp.codec import G711UCodec

def test_g711_encode_decode():
    """Test: G.711 encode/decode é lossless"""

    codec = G711UCodec()

    # PCM original (silêncio)
    original = b'\x00' * 160

    # Encode
    encoded = codec.encode(original)
    assert len(encoded) == 160  # G.711 é 1:1

    # Decode
    decoded = codec.decode(encoded)
    assert len(decoded) == 160

    # G.711 é lossy, mas silêncio deve ser idêntico
    assert decoded == original
```

### Teste com Pacotes RTP Reais

```bash
# Capturar RTP de chamada real
sudo tcpdump -i any -w rtp_capture.pcap udp portrange 10000-20000

# Reproduzir capture em teste
pytest tests/integration/test_rtp_playback.py --capture=rtp_capture.pcap
```

---

## 📊 Métricas

### Prometheus Metrics

```python
# Packets enviados/recebidos
rtp_packets_sent_total{session_id="abc-123"} 1234
rtp_packets_received_total{session_id="abc-123"} 1230

# Packet loss
rtp_packet_loss_percent{session_id="abc-123"} 0.32

# Jitter
rtp_jitter_ms{session_id="abc-123", quantile="0.5"} 12.5
rtp_jitter_ms{session_id="abc-123", quantile="0.95"} 35.2

# Codec usage
rtp_codec_usage{codec="PCMU"} 45
rtp_codec_usage{codec="PCMA"} 12
rtp_codec_usage{codec="opus"} 3
```

---

## 🐛 Debug

### Capturar Pacotes RTP

```bash
# Capturar RTP em todas interfaces
sudo tcpdump -i any -n udp portrange 10000-20000

# Salvar em arquivo
sudo tcpdump -i any -w rtp.pcap udp portrange 10000-20000

# Analisar com Wireshark
wireshark rtp.pcap
# Statistics → RTP → Stream Analysis
```

### Logs Estruturados

```json
{
  "module": "rtp.server",
  "level": "INFO",
  "message": "Stream created",
  "session_id": "abc-123",
  "local_port": 10050,
  "remote_endpoint": "192.168.1.100:10000",
  "codec": "PCMU"
}

{
  "module": "rtp.stream",
  "level": "DEBUG",
  "message": "RTP packet received",
  "session_id": "abc-123",
  "seq": 1234,
  "timestamp": 160000,
  "payload_size": 160
}

{
  "module": "rtp.stream",
  "level": "WARNING",
  "message": "Packet loss detected",
  "session_id": "abc-123",
  "expected_seq": 1235,
  "received_seq": 1237,
  "packets_lost": 2
}
```

### Verificar Qualidade de Áudio

```python
# src/rtp/stats.py

class RTPStats:
    """Estatísticas de qualidade RTP"""

    def get_mos_score(self) -> float:
        """
        Calculate MOS (Mean Opinion Score) - 1.0 to 5.0

        Based on:
        - Packet loss
        - Jitter
        - Round-trip time

        Returns:
            5.0: Excelente
            4.0: Bom
            3.0: Razoável
            2.0: Pobre
            1.0: Ruim
        """
        pass
```

---

## ⚙️ Configuração

### config/default.yaml

```yaml
rtp:
  # Range de portas para RTP
  port_range_start: 10000
  port_range_end: 20000

  # Prioridade de codecs (ordem de preferência)
  codec_priority:
    - PCMU    # G.711 μ-law (padrão USA)
    - PCMA    # G.711 A-law (padrão Europa)
    - opus    # Opus (moderno, melhor qualidade)

  # Jitter buffer
  jitter_buffer_ms: 60          # Target delay
  jitter_buffer_max_ms: 200     # Max delay antes de descartar

  # DTMF
  dtmf_detection: true
  dtmf_min_duration_ms: 40      # Mínimo de duração para considerar válido

  # Timeouts
  rtp_timeout_ms: 5000          # Sem RTP por 5s → considerar stream morto
```

---

## 🔧 Troubleshooting

### Problema: Não recebe pacotes RTP

**Causa provável:** Firewall bloqueando, NAT issue, ou SDP incorreto

**Debug:**
```bash
# Verificar se portas estão abertas
sudo ufw status | grep 10000:20000

# Verificar se pacotes estão chegando
sudo tcpdump -i any -n udp portrange 10000-20000

# Verificar SDP negociado
grep "SDP answer" logs/sip.log
```

**Solução:**
```bash
# Abrir range de portas
sudo ufw allow 10000:20000/udp

# Configurar STUN se atrás de NAT
# config/local.yaml:
# rtp:
#   stun_server: stun.l.google.com:19302
```

---

### Problema: Áudio cortado (choppy)

**Causa provável:** Packet loss alto ou jitter excessivo

**Debug:**
```bash
# Verificar métricas
curl http://localhost:8000/metrics | grep rtp_packet_loss
curl http://localhost:8000/metrics | grep rtp_jitter

# Ver logs de warning
grep "Packet loss" logs/rtp.log
```

**Solução:**
```yaml
# Aumentar jitter buffer
rtp:
  jitter_buffer_ms: 100  # Era 60
```

---

### Problema: Eco na chamada

**Causa provável:** Áudio sendo enviado de volta sem processamento

**Debug:**
```python
# Adicionar flag de debug
stream._debug_echo = True

# Logs devem mostrar:
# "Received 160 bytes"
# "Sent 160 bytes"  ← Se aparecer imediatamente, é eco!
```

**Solução:**
- Implementar AEC (Acoustic Echo Cancellation)
- Ou garantir que AI Pipeline não envia silêncio de volta

---

### Problema: Codec não suportado

**Causa provável:** Client quer codec que não implementamos

**Debug:**
```bash
grep "Codec negotiation failed" logs/rtp.log
```

**Solução:**
- Adicionar codec ao `codec.py`
- Ou atualizar SDP para rejeitar codec não suportado

---

## 📐 Especificações Técnicas

### Formato de Áudio Interno

```
Format: PCM (raw)
Bit depth: 16-bit signed
Sample rate: 8 kHz (telefonia) ou 16 kHz (HD voice)
Channels: 1 (mono)
Chunk size: 160 bytes (20ms @ 8kHz)
```

### RTP Header

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|V=2|P|X|  CC   |M|     PT      |       sequence number         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           timestamp                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|           synchronization source (SSRC) identifier            |
+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+
|                       payload (variable)                      |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

- **PT (Payload Type)**: 0 = PCMU, 8 = PCMA, 96-127 = dynamic (Opus)
- **Timestamp**: Incrementa 160 a cada packet (20ms @ 8kHz)
- **Sequence**: Incrementa 1 a cada packet

---

## 🎓 Lições do LiveKit SIP

### 1. AUDIO_BRIDGE_MAX_DELAY = 1s

```python
# NÃO envie áudio imediatamente após stream abrir
# Aguarde primeiro RTP packet chegar OU 1s (o que vier primeiro)

async def wait_for_first_packet(stream: AudioStream):
    """Wait for first RTP or timeout"""
    try:
        async with asyncio.timeout(1.0):  # AUDIO_BRIDGE_MAX_DELAY
            first_packet = await stream.receive()
            return first_packet
    except TimeoutError:
        # OK, iniciar mesmo sem RTP
        return None
```

**Por quê?** Evita cutoff de áudio no início da chamada (observado em produção).

---

### 2. Packet Loss Tolerance

```python
# Telefonia tolera ~5% packet loss sem degradação perceptível
# Acima de 10% = qualidade ruim

MAX_ACCEPTABLE_PACKET_LOSS = 0.05  # 5%

if stream.stats['packet_loss'] > MAX_ACCEPTABLE_PACKET_LOSS:
    logger.warning('High packet loss', loss=stream.stats['packet_loss'])
```

---

### 3. Jitter Buffer Adaptativo

```python
# Jitter buffer deve ser adaptativo (não fixo)
# Começar com 60ms, ajustar baseado em jitter medido

class AdaptiveJitterBuffer:
    def adjust_target_delay(self):
        """Adjust based on measured jitter"""
        if self.avg_jitter > self.target_delay * 0.8:
            # Jitter alto → aumentar buffer
            self.target_delay = min(200, self.target_delay + 20)
        elif self.avg_jitter < self.target_delay * 0.3:
            # Jitter baixo → reduzir buffer (menos latência)
            self.target_delay = max(40, self.target_delay - 10)
```

---

## 📚 Referências

- **RFC 3550**: RTP - Real-time Transport Protocol
- **RFC 3551**: RTP Audio/Video Profiles
- **RFC 2833**: DTMF over RTP
- **G.711**: ITU-T Recommendation (PCMU/PCMA)
- **Opus**: RFC 6716

---

## ✅ Checklist de Implementação

- [ ] `server.py` - RTPServer class
- [ ] `stream.py` - AudioStream implementation
- [ ] `codec.py` - G.711 codec
- [ ] `jitter.py` - Jitter buffer
- [ ] `dtmf.py` - DTMF detector
- [ ] `stats.py` - RTP statistics
- [ ] Testes unitários (>90% coverage)
- [ ] Testes com RTP capture real
- [ ] Métricas Prometheus
- [ ] AUDIO_BRIDGE_MAX_DELAY implementado

---

**Status:** 🚧 Em implementação
**Owner:** Time de Voice Engineering
