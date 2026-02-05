"""
Ring Buffer Lock-Free para Media Forking.

Implementa buffer circular que NUNCA bloqueia o produtor (RTP callback).
Usa collections.deque com maxlen para drop oldest automático.

Características:
- Thread-safe para single producer / single consumer (SPSC)
- Drop oldest policy (frames antigos descartados automaticamente)
- Métricas de overflow para observabilidade
- Timestamp em cada frame para cálculo de lag

Uso típico:
    buffer = RingBuffer(capacity_ms=500, sample_rate=8000)

    # Producer (RTP callback - NUNCA bloqueia)
    buffer.push(session_id, audio_data)

    # Consumer (async worker)
    frame = buffer.pop()
    if frame:
        await send_to_ai_agent(frame)
"""

import time
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Dict
from threading import Lock

logger = logging.getLogger("media-server.ring_buffer")


@dataclass
class AudioFrame:
    """Frame de áudio com metadados para rastreamento."""

    session_id: str
    data: bytes
    timestamp: float  # time.perf_counter() quando foi inserido
    sequence: int     # Número sequencial para debug

    @property
    def age_ms(self) -> float:
        """Idade do frame em milissegundos."""
        return (time.perf_counter() - self.timestamp) * 1000

    def __len__(self) -> int:
        return len(self.data)


@dataclass
class BufferMetrics:
    """Métricas do RingBuffer para observabilidade."""

    frames_received: int = 0
    frames_dropped: int = 0
    frames_consumed: int = 0
    bytes_received: int = 0
    bytes_dropped: int = 0
    bytes_consumed: int = 0
    overflow_events: int = 0  # Quantas vezes o buffer transbordou
    last_overflow_timestamp: float = 0.0
    peak_size_bytes: int = 0

    def record_push(self, frame_size: int, dropped: bool = False):
        """Registra um push no buffer."""
        self.frames_received += 1
        self.bytes_received += frame_size
        if dropped:
            self.frames_dropped += 1
            self.bytes_dropped += frame_size

    def record_overflow(self, dropped_frame_size: int):
        """Registra evento de overflow (frame antigo descartado)."""
        self.overflow_events += 1
        self.last_overflow_timestamp = time.perf_counter()
        self.frames_dropped += 1
        self.bytes_dropped += dropped_frame_size

    def record_pop(self, frame_size: int):
        """Registra um pop do buffer."""
        self.frames_consumed += 1
        self.bytes_consumed += frame_size

    def update_peak(self, current_size: int):
        """Atualiza tamanho máximo observado."""
        if current_size > self.peak_size_bytes:
            self.peak_size_bytes = current_size

    @property
    def drop_rate(self) -> float:
        """Taxa de descarte (0.0 a 1.0)."""
        if self.frames_received == 0:
            return 0.0
        return self.frames_dropped / self.frames_received

    def to_dict(self) -> dict:
        """Exporta métricas como dicionário."""
        return {
            "frames_received": self.frames_received,
            "frames_dropped": self.frames_dropped,
            "frames_consumed": self.frames_consumed,
            "bytes_received": self.bytes_received,
            "bytes_dropped": self.bytes_dropped,
            "bytes_consumed": self.bytes_consumed,
            "overflow_events": self.overflow_events,
            "drop_rate": self.drop_rate,
            "peak_size_bytes": self.peak_size_bytes,
        }


class RingBuffer:
    """
    Ring Buffer lock-free para media forking.

    Implementa padrão SPSC (Single Producer, Single Consumer) usando
    collections.deque com maxlen, que garante:
    - Push O(1) amortizado
    - Pop O(1)
    - Drop oldest automático quando cheio
    - Thread-safe para SPSC

    Args:
        capacity_ms: Capacidade do buffer em milissegundos de áudio
        sample_rate: Taxa de amostragem em Hz (default: 8000)
        sample_width: Bytes por sample (default: 2 para 16-bit)
        channels: Número de canais (default: 1 para mono)

    Example:
        buffer = RingBuffer(capacity_ms=500)  # 500ms de capacidade

        # No RTP callback (producer):
        buffer.push("session-123", audio_bytes)

        # No async worker (consumer):
        frame = buffer.pop()
        if frame:
            lag_ms = frame.age_ms
            await process(frame.data)
    """

    def __init__(
        self,
        capacity_ms: int = 500,
        sample_rate: int = 8000,
        sample_width: int = 2,
        channels: int = 1,
    ):
        self.capacity_ms = capacity_ms
        self.sample_rate = sample_rate
        self.sample_width = sample_width
        self.channels = channels

        # Calcula capacidade em bytes
        # bytes = (sample_rate * sample_width * channels * ms) / 1000
        self.capacity_bytes = int(
            (sample_rate * sample_width * channels * capacity_ms) / 1000
        )

        # Calcula número máximo de frames (assumindo 20ms por frame)
        frame_duration_ms = 20
        bytes_per_frame = int(
            (sample_rate * sample_width * channels * frame_duration_ms) / 1000
        )
        self.bytes_per_frame = bytes_per_frame
        max_frames = max(1, self.capacity_bytes // bytes_per_frame)

        # Buffer principal - deque com maxlen para drop oldest automático
        self._buffer: deque[AudioFrame] = deque(maxlen=max_frames)

        # Métricas
        self._metrics = BufferMetrics()

        # Contador de sequência
        self._sequence = 0

        # Lock leve para métricas (não bloqueia push/pop)
        self._metrics_lock = Lock()

        # Tamanho atual em bytes (atualizado atomicamente)
        self._current_size_bytes = 0

        logger.info(
            f"RingBuffer criado: capacity={capacity_ms}ms, "
            f"max_frames={max_frames}, capacity_bytes={self.capacity_bytes}"
        )

    def push(self, session_id: str, data: bytes) -> bool:
        """
        Adiciona frame ao buffer. NUNCA bloqueia.

        Se o buffer estiver cheio, o frame mais antigo é automaticamente
        descartado (drop oldest policy).

        Args:
            session_id: ID da sessão
            data: Bytes de áudio

        Returns:
            True se adicionado sem overflow, False se houve descarte
        """
        frame = AudioFrame(
            session_id=session_id,
            data=data,
            timestamp=time.perf_counter(),
            sequence=self._sequence,
        )
        self._sequence += 1

        # Verifica se vai haver overflow
        was_full = len(self._buffer) == self._buffer.maxlen

        if was_full:
            # Pega frame que será descartado para métricas
            old_frame = self._buffer[0]
            with self._metrics_lock:
                self._metrics.record_overflow(len(old_frame.data))

            logger.debug(
                f"[{session_id[:8]}] Buffer overflow: dropping frame seq={old_frame.sequence}, "
                f"age={old_frame.age_ms:.1f}ms"
            )

        # Push - se cheio, descarta automaticamente o mais antigo
        self._buffer.append(frame)

        # Atualiza tamanho e métricas
        self._current_size_bytes = sum(len(f.data) for f in self._buffer)

        with self._metrics_lock:
            self._metrics.record_push(len(data), dropped=False)
            self._metrics.update_peak(self._current_size_bytes)

        return not was_full

    def pop(self) -> Optional[AudioFrame]:
        """
        Remove e retorna o frame mais antigo. Não bloqueia.

        Returns:
            AudioFrame se houver, None se buffer vazio
        """
        try:
            frame = self._buffer.popleft()

            # Atualiza métricas
            self._current_size_bytes = sum(len(f.data) for f in self._buffer)

            with self._metrics_lock:
                self._metrics.record_pop(len(frame.data))

            return frame

        except IndexError:
            # Buffer vazio
            return None

    def peek(self) -> Optional[AudioFrame]:
        """
        Retorna o frame mais antigo sem remover.

        Returns:
            AudioFrame se houver, None se buffer vazio
        """
        try:
            return self._buffer[0]
        except IndexError:
            return None

    def clear(self) -> int:
        """
        Limpa o buffer.

        Returns:
            Número de frames descartados
        """
        count = len(self._buffer)
        self._buffer.clear()
        self._current_size_bytes = 0

        logger.debug(f"Buffer cleared: {count} frames discarded")
        return count

    @property
    def size(self) -> int:
        """Número de frames no buffer."""
        return len(self._buffer)

    @property
    def size_bytes(self) -> int:
        """Tamanho atual do buffer em bytes."""
        return self._current_size_bytes

    @property
    def size_ms(self) -> float:
        """Tamanho atual do buffer em milissegundos de áudio."""
        if self._current_size_bytes == 0:
            return 0.0
        bytes_per_ms = (self.sample_rate * self.sample_width * self.channels) / 1000
        return self._current_size_bytes / bytes_per_ms

    @property
    def capacity(self) -> int:
        """Capacidade máxima em frames."""
        return self._buffer.maxlen

    @property
    def is_empty(self) -> bool:
        """Verifica se buffer está vazio."""
        return len(self._buffer) == 0

    @property
    def is_full(self) -> bool:
        """Verifica se buffer está cheio."""
        return len(self._buffer) == self._buffer.maxlen

    @property
    def fill_ratio(self) -> float:
        """Taxa de preenchimento (0.0 a 1.0)."""
        if self._buffer.maxlen == 0:
            return 0.0
        return len(self._buffer) / self._buffer.maxlen

    @property
    def metrics(self) -> BufferMetrics:
        """Retorna cópia das métricas atuais."""
        with self._metrics_lock:
            return BufferMetrics(
                frames_received=self._metrics.frames_received,
                frames_dropped=self._metrics.frames_dropped,
                frames_consumed=self._metrics.frames_consumed,
                bytes_received=self._metrics.bytes_received,
                bytes_dropped=self._metrics.bytes_dropped,
                bytes_consumed=self._metrics.bytes_consumed,
                overflow_events=self._metrics.overflow_events,
                last_overflow_timestamp=self._metrics.last_overflow_timestamp,
                peak_size_bytes=self._metrics.peak_size_bytes,
            )

    def get_oldest_frame_age_ms(self) -> float:
        """
        Retorna idade do frame mais antigo em ms.

        Útil para calcular consumer_lag_ms.

        Returns:
            Idade em ms, ou 0.0 se buffer vazio
        """
        frame = self.peek()
        if frame:
            return frame.age_ms
        return 0.0

    def __len__(self) -> int:
        return len(self._buffer)

    def __repr__(self) -> str:
        return (
            f"RingBuffer(size={self.size}/{self.capacity}, "
            f"size_ms={self.size_ms:.1f}/{self.capacity_ms}, "
            f"fill={self.fill_ratio:.1%})"
        )
