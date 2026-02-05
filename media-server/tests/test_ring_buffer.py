"""
Testes do RingBuffer para Media Forking.

Valida:
- Push/Pop básico
- Drop oldest quando cheio
- Métricas de overflow
- Thread-safety básico
"""

import time
import threading
import sys
import os

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ring_buffer import RingBuffer, AudioFrame


def test_basic_push_pop():
    """Testa push e pop básico."""
    buffer = RingBuffer(capacity_ms=100, sample_rate=8000)

    # Push um frame
    audio_data = b'\x00' * 160  # 10ms de áudio @ 8kHz, 16-bit
    result = buffer.push("session-1", audio_data)

    assert result == True, "Push deve retornar True quando não há overflow"
    assert buffer.size == 1, f"Buffer deve ter 1 frame, tem {buffer.size}"

    # Pop o frame
    frame = buffer.pop()
    assert frame is not None, "Pop deve retornar um frame"
    assert frame.session_id == "session-1"
    assert frame.data == audio_data
    assert buffer.size == 0, "Buffer deve estar vazio após pop"

    print("✓ test_basic_push_pop PASSED")


def test_drop_oldest():
    """Testa que frames antigos são descartados quando buffer cheio."""
    # Buffer pequeno: 100ms = ~5 frames de 20ms
    buffer = RingBuffer(capacity_ms=100, sample_rate=8000)

    # Preenche o buffer
    for i in range(buffer.capacity):
        audio_data = bytes([i] * 320)  # 20ms de áudio
        buffer.push(f"session-{i}", audio_data)

    assert buffer.is_full, "Buffer deve estar cheio"
    initial_size = buffer.size

    # Push mais um frame (deve descartar o mais antigo)
    new_data = bytes([99] * 320)
    result = buffer.push("session-new", new_data)

    assert result == False, "Push deve retornar False quando há overflow"
    assert buffer.size == initial_size, "Tamanho deve permanecer igual"

    # O primeiro frame (session-0) deve ter sido descartado
    # O primeiro frame agora deve ser session-1
    frame = buffer.pop()
    assert frame.session_id == "session-1", f"Primeiro frame deveria ser session-1, é {frame.session_id}"

    print("✓ test_drop_oldest PASSED")


def test_metrics():
    """Testa métricas de overflow."""
    buffer = RingBuffer(capacity_ms=100, sample_rate=8000)

    # Preenche o buffer
    for i in range(buffer.capacity):
        buffer.push("session", bytes([i] * 320))

    initial_overflow = buffer.metrics.overflow_events

    # Causa overflow
    buffer.push("session", bytes([0] * 320))
    buffer.push("session", bytes([0] * 320))
    buffer.push("session", bytes([0] * 320))

    metrics = buffer.metrics
    assert metrics.overflow_events == initial_overflow + 3, f"Deveria ter 3 overflows, tem {metrics.overflow_events - initial_overflow}"
    assert metrics.frames_dropped >= 3, f"Deveria ter pelo menos 3 frames dropped, tem {metrics.frames_dropped}"

    print("✓ test_metrics PASSED")


def test_consumer_lag():
    """Testa cálculo de lag do consumer."""
    buffer = RingBuffer(capacity_ms=500, sample_rate=8000)

    # Push um frame
    buffer.push("session", bytes([0] * 320))

    # Aguarda um pouco
    time.sleep(0.05)  # 50ms

    # Verifica lag
    lag = buffer.get_oldest_frame_age_ms()
    assert lag >= 50, f"Lag deveria ser >= 50ms, é {lag:.1f}ms"
    assert lag < 100, f"Lag deveria ser < 100ms, é {lag:.1f}ms"

    print("✓ test_consumer_lag PASSED")


def test_thread_safety():
    """Testa thread-safety básico (SPSC)."""
    buffer = RingBuffer(capacity_ms=500, sample_rate=8000)
    frames_pushed = [0]
    frames_popped = [0]
    errors = []

    def producer():
        for i in range(100):
            try:
                buffer.push("session", bytes([i % 256] * 320))
                frames_pushed[0] += 1
                time.sleep(0.001)
            except Exception as e:
                errors.append(f"Producer error: {e}")

    def consumer():
        for _ in range(100):
            try:
                frame = buffer.pop()
                if frame:
                    frames_popped[0] += 1
                time.sleep(0.001)
            except Exception as e:
                errors.append(f"Consumer error: {e}")

    producer_thread = threading.Thread(target=producer)
    consumer_thread = threading.Thread(target=consumer)

    producer_thread.start()
    consumer_thread.start()

    producer_thread.join()
    consumer_thread.join()

    assert len(errors) == 0, f"Não deveria ter erros: {errors}"
    assert frames_pushed[0] == 100, f"Deveria ter pushed 100 frames, pushed {frames_pushed[0]}"

    print(f"✓ test_thread_safety PASSED (pushed={frames_pushed[0]}, popped={frames_popped[0]})")


def test_never_blocks():
    """Testa que push NUNCA bloqueia, mesmo com buffer cheio."""
    buffer = RingBuffer(capacity_ms=50, sample_rate=8000)  # Buffer bem pequeno

    start = time.perf_counter()

    # Push muitos frames rapidamente
    for i in range(1000):
        buffer.push("session", bytes([i % 256] * 320))

    elapsed = time.perf_counter() - start

    # 1000 pushes devem levar menos de 100ms (não há bloqueio)
    assert elapsed < 0.1, f"Push não deveria bloquear, levou {elapsed*1000:.1f}ms"

    print(f"✓ test_never_blocks PASSED (1000 pushes em {elapsed*1000:.1f}ms)")


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("TESTES DO RING BUFFER")
    print("=" * 50 + "\n")

    test_basic_push_pop()
    test_drop_oldest()
    test_metrics()
    test_consumer_lag()
    test_thread_safety()
    test_never_blocks()

    print("\n" + "=" * 50)
    print("TODOS OS TESTES PASSARAM!")
    print("=" * 50 + "\n")
