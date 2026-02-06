"""
Testes unitários para VAD (Voice Activity Detection) e Circuit Breaker.

VAD: AudioBuffer com detecção de fim de fala
Circuit Breaker: Pattern de resiliência nos providers
"""

import asyncio
import math
import struct
import time
import pytest
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

_mock_audio_config = {
    "sample_rate": 8000,
    "channels": 1,
    "sample_width": 2,
    "frame_duration_ms": 20,
    "vad_aggressiveness": 2,
    "silence_threshold_ms": 500,
    "min_speech_ms": 250,
    "energy_threshold": 500,
    "max_buffer_seconds": 60,
    "chunk_size_bytes": 1600,
    "max_pending_audio_ms": 30000,
    "vad_ring_buffer_size": 5,
    "vad_speech_ratio_threshold": 0.4,
}


@pytest.fixture(autouse=True)
def mock_vad_config(monkeypatch):
    """Mock config para testes VAD."""
    monkeypatch.setattr("pipeline.vad.AUDIO_CONFIG", _mock_audio_config)


def _generate_silence_frame(frame_duration_ms: int = 20, sample_rate: int = 8000) -> bytes:
    """Gera frame de silêncio (zeros)."""
    num_samples = int(sample_rate * frame_duration_ms / 1000)
    return b'\x00\x00' * num_samples


def _generate_speech_frame(
    frame_duration_ms: int = 20,
    sample_rate: int = 8000,
    freq: int = 440,
    amplitude: int = 10000
) -> bytes:
    """Gera frame com fala simulada (sine wave alta energia)."""
    num_samples = int(sample_rate * frame_duration_ms / 1000)
    samples = []
    for i in range(num_samples):
        value = int(amplitude * math.sin(2 * math.pi * freq * i / sample_rate))
        samples.append(value)
    return struct.pack(f'<{len(samples)}h', *samples)


# ==================== AudioBuffer Tests ====================

class TestAudioBuffer:
    """Testes para AudioBuffer (VAD)."""

    @pytest.fixture
    def buffer(self):
        """Cria AudioBuffer sem WebRTC VAD (usa energy fallback)."""
        with patch("pipeline.vad.WEBRTC_VAD_AVAILABLE", False):
            from pipeline.vad import AudioBuffer
            return AudioBuffer()

    def test_init_defaults(self, buffer):
        """Verifica valores padrão."""
        assert buffer.sample_rate == 8000
        assert buffer.frame_duration_ms == 20
        assert buffer.silence_threshold == 500
        assert not buffer.has_audio
        assert buffer.duration_ms == 0

    def test_add_frame_silence_no_return(self, buffer):
        """Silêncio sem fala prévia não retorna nada."""
        frame = _generate_silence_frame()
        result = buffer.add_frame(frame)
        assert result is None

    def test_add_frame_speech_detects(self, buffer):
        """Fala é detectada e acumulada no buffer."""
        frame = _generate_speech_frame()
        result = buffer.add_frame(frame)
        # Primeiro frame não retorna (precisa detectar fim de fala)
        assert result is None
        assert buffer.has_audio

    def test_speech_then_silence_returns_audio(self, buffer):
        """Fala seguida de silêncio suficiente retorna áudio."""
        # Simula fala por 300ms (15 frames de 20ms)
        for _ in range(15):
            buffer.add_frame(_generate_speech_frame())

        # Simula silêncio por 500ms (25 frames de 20ms) para atingir threshold
        result = None
        for _ in range(30):  # Mais que o necessário
            r = buffer.add_frame(_generate_silence_frame())
            if r is not None:
                result = r
                break

        assert result is not None
        assert len(result) > 0

    def test_short_speech_ignored(self, buffer):
        """Fala muito curta (< min_speech_ms) é ignorada."""
        # Apenas 2 frames = 40ms (< 250ms min_speech_ms)
        buffer.add_frame(_generate_speech_frame())
        buffer.add_frame(_generate_speech_frame())

        # Silêncio para trigger
        result = None
        for _ in range(30):
            r = buffer.add_frame(_generate_silence_frame())
            if r is not None:
                result = r
                break

        # Deve ser ignorado por ser muito curto
        assert result is None

    def test_flush_returns_accumulated_audio(self, buffer):
        """flush() retorna áudio acumulado."""
        # Acumula fala suficiente (>= min_speech_ms = 250ms = 13 frames)
        for _ in range(15):
            buffer.add_frame(_generate_speech_frame())

        result = buffer.flush()
        assert result is not None
        assert len(result) > 0

    def test_flush_short_audio_returns_none(self, buffer):
        """flush() com áudio curto retorna None."""
        buffer.add_frame(_generate_speech_frame())
        buffer.add_frame(_generate_speech_frame())
        result = buffer.flush()
        assert result is None

    def test_reset_clears_buffer(self, buffer):
        """_reset() limpa todo estado."""
        buffer.add_frame(_generate_speech_frame())
        buffer._reset()
        assert not buffer.has_audio
        assert buffer.duration_ms == 0

    def test_max_buffer_resets(self, buffer):
        """Buffer excedendo limite máximo reseta."""
        buffer.MAX_BUFFER_SIZE = 1000  # Limite baixo para teste

        # Enche o buffer além do limite
        for _ in range(100):
            buffer.add_frame(_generate_speech_frame())

        # Deve ter resetado
        assert len(buffer.buffer) < 1000

    def test_add_audio_raw_no_vad(self, buffer):
        """add_audio_raw acumula sem processar VAD."""
        audio = _generate_speech_frame() * 5
        buffer.add_audio_raw(audio)
        assert buffer.has_audio
        assert buffer.speech_detected

    def test_add_audio_raw_backpressure(self, buffer):
        """add_audio_raw descarta áudio antigo quando buffer cheio."""
        buffer.MAX_BUFFER_SIZE = 1000  # Limite baixo
        large_audio = b'\x01\x00' * 600  # 1200 bytes

        buffer.add_audio_raw(large_audio)
        # Buffer deve ter no máximo MAX_BUFFER_SIZE
        assert len(buffer.buffer) <= buffer.MAX_BUFFER_SIZE

    def test_add_audio_processes_frames(self, buffer):
        """add_audio processa frame a frame."""
        # Gera áudio com múltiplos frames
        frames = b''
        for _ in range(15):
            frames += _generate_speech_frame()
        for _ in range(30):
            frames += _generate_silence_frame()

        result = buffer.add_audio(frames)
        # Pode retornar áudio se detectou fim de fala
        # Ou None se não completou o ciclo
        # O importante é não crashar

    def test_duration_ms_calculation(self, buffer):
        """Verifica cálculo de duração em ms."""
        # 8000 Hz, 16-bit = 16000 bytes/s = 16 bytes/ms
        # 320 bytes = 20ms
        buffer.buffer = bytearray(b'\x00' * 320)
        assert buffer.duration_ms == pytest.approx(20, abs=1)

    def test_energy_calculation(self, buffer):
        """Verifica cálculo de energia RMS."""
        # Frame de silêncio = energia 0
        silence = _generate_silence_frame()
        energy = buffer._calculate_energy(silence)
        assert energy == 0

        # Frame com sinal = energia > 0
        speech = _generate_speech_frame()
        energy = buffer._calculate_energy(speech)
        assert energy > 0


# ==================== Circuit Breaker Tests ====================

class TestCircuitBreaker:
    """Testes para Circuit Breaker em BaseProvider."""

    @pytest.fixture
    def provider(self):
        """Cria provider concreto para teste."""
        from providers.base import BaseProvider, ProviderConfig, HealthCheckResult, ProviderHealth

        class TestProvider(BaseProvider):
            provider_name = "test"

            async def _do_health_check(self):
                return HealthCheckResult(status=ProviderHealth.HEALTHY, message="ok")

        return TestProvider(config=ProviderConfig(
            circuit_failure_threshold=3,
            circuit_recovery_timeout=0.1,  # 100ms para testes rápidos
        ))

    def test_initial_state_closed(self, provider):
        """Verifica que estado inicial é CLOSED."""
        from providers.base import CircuitState
        assert provider.circuit_state == CircuitState.CLOSED

    def test_opens_after_failures(self, provider):
        """Verifica que abre após N falhas consecutivas."""
        from providers.base import CircuitState

        for _ in range(3):
            provider._record_circuit_failure()

        assert provider._circuit_state == CircuitState.OPEN

    def test_fail_fast_when_open(self, provider):
        """Verifica que chamadas falham imediatamente quando OPEN."""
        from providers.base import CircuitState, ProviderUnavailableError

        # Força estado OPEN
        for _ in range(3):
            provider._record_circuit_failure()

        with pytest.raises(ProviderUnavailableError):
            provider._check_circuit_breaker()

    def test_transitions_to_half_open(self, provider):
        """Verifica transição OPEN -> HALF_OPEN após timeout."""
        from providers.base import CircuitState

        # Abre circuit breaker
        for _ in range(3):
            provider._record_circuit_failure()
        assert provider._circuit_state == CircuitState.OPEN

        # Simula passagem de tempo
        provider._last_failure_time = time.time() - 1  # 1s atrás (> 0.1s timeout)

        # _check_circuit_breaker() deve transicionar para HALF_OPEN e permitir 1 chamada
        provider._check_circuit_breaker()
        assert provider.circuit_state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self, provider):
        """Verifica que sucesso em HALF_OPEN fecha o circuito."""
        from providers.base import CircuitState

        # Coloca em HALF_OPEN
        for _ in range(3):
            provider._record_circuit_failure()
        provider._last_failure_time = time.time() - 1
        provider._check_circuit_breaker()  # Trigger OPEN -> HALF_OPEN

        # Registra sucesso
        provider._record_circuit_success()
        assert provider._circuit_state == CircuitState.CLOSED
        assert provider._failure_count == 0

    def test_half_open_failure_reopens(self, provider):
        """Verifica que falha em HALF_OPEN reabre o circuito."""
        from providers.base import CircuitState

        # Coloca em HALF_OPEN
        for _ in range(3):
            provider._record_circuit_failure()
        provider._last_failure_time = time.time() - 1
        provider._check_circuit_breaker()  # Trigger OPEN -> HALF_OPEN

        # Registra falha
        provider._record_circuit_failure()
        assert provider._circuit_state == CircuitState.OPEN

    def test_manual_reset(self, provider):
        """Verifica reset manual do circuit breaker."""
        from providers.base import CircuitState

        # Abre circuit breaker
        for _ in range(3):
            provider._record_circuit_failure()
        assert provider._circuit_state == CircuitState.OPEN

        # Reset manual
        provider.reset_circuit_breaker()
        assert provider._circuit_state == CircuitState.CLOSED
        assert provider._failure_count == 0

    def test_success_resets_failure_count(self, provider):
        """Verifica que sucesso em CLOSED reseta contador de falhas."""
        provider._record_circuit_failure()
        provider._record_circuit_failure()
        assert provider._failure_count == 2

        provider._record_circuit_success()
        assert provider._failure_count == 0

    def test_half_open_max_calls(self, provider):
        """Verifica que HALF_OPEN limita número de chamadas."""
        from providers.base import CircuitState, ProviderUnavailableError

        # Coloca em HALF_OPEN via _check_circuit_breaker
        for _ in range(3):
            provider._record_circuit_failure()
        provider._last_failure_time = time.time() - 1
        provider._check_circuit_breaker()  # Trigger OPEN -> HALF_OPEN (consome 1 chamada)

        # A transição já consumiu a única chamada permitida (max_calls=1)
        # Próxima chamada deve ser bloqueada
        with pytest.raises(ProviderUnavailableError):
            provider._check_circuit_breaker()


# ==================== LatencyBudget Tests ====================

class TestLatencyBudget:
    """Testes para LatencyBudget."""

    def test_start_and_finish(self):
        """Verifica ciclo start/finish."""
        from pipeline.latency_budget import LatencyBudget

        budget = LatencyBudget(target_ms=1000)
        budget.start()
        time.sleep(0.01)  # 10ms
        budget.finish()

        assert budget.total_ms > 0

    def test_record_stages(self):
        """Verifica registro de estágios."""
        from pipeline.latency_budget import LatencyBudget

        budget = LatencyBudget()
        budget.start()
        budget.record_stage('stt', 200)
        budget.record_stage('llm', 500)
        budget.record_stage('tts', 150)

        assert budget.stages['stt'] == 200
        assert budget.stages['llm'] == 500
        assert budget.stages['tts'] == 150

    def test_over_budget_detection(self):
        """Verifica detecção de budget excedido."""
        from pipeline.latency_budget import LatencyBudget

        budget = LatencyBudget(target_ms=100)
        budget.start()
        time.sleep(0.15)  # 150ms > 100ms target

        assert budget.is_over_budget

    def test_within_budget(self):
        """Verifica detecção dentro do budget."""
        from pipeline.latency_budget import LatencyBudget

        budget = LatencyBudget(target_ms=5000)
        budget.start()
        # Sem sleep, deve ser < 5000ms

        assert not budget.is_over_budget

    def test_report(self):
        """Verifica relatório."""
        from pipeline.latency_budget import LatencyBudget

        budget = LatencyBudget(target_ms=1500)
        budget.start()
        budget.record_stage('stt', 300)
        budget.record_stage('llm', 800)

        report = budget.report()
        assert 'total_ms' in report
        assert 'target_ms' in report
        assert 'stages' in report
        assert report['target_ms'] == 1500

    def test_start_from_timestamp(self):
        """Verifica start_from com timestamp externo."""
        from pipeline.latency_budget import LatencyBudget

        budget = LatencyBudget()
        ts = time.perf_counter()
        time.sleep(0.01)
        budget.start_from(ts)

        assert budget.total_ms > 0
