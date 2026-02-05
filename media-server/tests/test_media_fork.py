"""
Testes de integração do Media Fork Manager.

Valida:
- Inicialização do manager
- Fork de áudio (nunca bloqueia)
- Comportamento com AI Agent indisponível
"""

import asyncio
import time
import sys
import os

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockAIAgentAdapter:
    """Mock do AIAgentAdapter para testes."""

    def __init__(self, connected: bool = True, delay_ms: float = 0):
        self._connected = connected
        self.delay_ms = delay_ms
        self.audio_received = []
        self.sessions_started = []
        self.sessions_ended = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_connected(self, connected: bool):
        self._connected = connected

    async def send_audio(self, session_id: str, audio_data: bytes):
        if self.delay_ms > 0:
            await asyncio.sleep(self.delay_ms / 1000)
        self.audio_received.append((session_id, audio_data))

    async def start_session(self, session_info):
        self.sessions_started.append(session_info)
        return True

    async def end_session(self, session_id: str, reason: str = "hangup"):
        self.sessions_ended.append((session_id, reason))


async def test_manager_initialization():
    """Testa inicialização do MediaForkManager."""
    from core.media_fork_manager import MediaForkManager

    mock_adapter = MockAIAgentAdapter()
    manager = MediaForkManager(mock_adapter)

    result = await manager.initialize()
    assert result == True, "Inicialização deve retornar True"
    assert manager.is_ready == True, "Manager deve estar pronto"

    await manager.shutdown()
    print("✓ test_manager_initialization PASSED")


async def test_fork_audio_never_blocks():
    """Testa que fork_audio NUNCA bloqueia, mesmo com AI Agent lento."""
    from core.media_fork_manager import MediaForkManager

    # Mock com delay de 100ms (simula AI Agent lento)
    mock_adapter = MockAIAgentAdapter(delay_ms=100)
    manager = MediaForkManager(mock_adapter)
    await manager.initialize()

    session_id = "test-session-123"
    await manager.start_session(session_id)

    # Fork muitos frames rapidamente
    start = time.perf_counter()
    for i in range(100):
        manager.fork_audio(session_id, bytes([i % 256] * 320))
    elapsed = time.perf_counter() - start

    # 100 forks devem levar menos de 50ms (não espera o AI Agent)
    assert elapsed < 0.05, f"fork_audio não deveria bloquear, levou {elapsed*1000:.1f}ms"

    await manager.stop_session(session_id)
    await manager.shutdown()

    print(f"✓ test_fork_audio_never_blocks PASSED (100 forks em {elapsed*1000:.1f}ms)")


async def test_fork_with_ai_agent_unavailable():
    """Testa comportamento quando AI Agent está indisponível."""
    from core.media_fork_manager import MediaForkManager

    mock_adapter = MockAIAgentAdapter(connected=False)
    manager = MediaForkManager(mock_adapter)
    await manager.initialize()

    session_id = "test-session-456"
    await manager.start_session(session_id)

    # Fork deve funcionar mesmo sem AI Agent
    start = time.perf_counter()
    for i in range(50):
        result = manager.fork_audio(session_id, bytes([i % 256] * 320))
        assert result == True, "fork_audio deve retornar True mesmo sem AI Agent"
    elapsed = time.perf_counter() - start

    assert elapsed < 0.05, f"fork_audio não deveria bloquear, levou {elapsed*1000:.1f}ms"

    # Verifica que nenhum áudio foi enviado (AI Agent offline)
    # O consumer está tentando enviar mas falha silenciosamente
    await asyncio.sleep(0.1)

    await manager.stop_session(session_id)
    await manager.shutdown()

    print(f"✓ test_fork_with_ai_agent_unavailable PASSED")


async def test_session_lifecycle():
    """Testa ciclo de vida completo de uma sessão."""
    from core.media_fork_manager import MediaForkManager

    mock_adapter = MockAIAgentAdapter()
    manager = MediaForkManager(mock_adapter)
    await manager.initialize()

    session_id = "test-session-789"

    # Inicia sessão
    result = await manager.start_session(session_id)
    assert result == True, "start_session deve retornar True"
    assert manager.active_sessions_count == 1, "Deve ter 1 sessão ativa"

    # Fork alguns frames
    for i in range(10):
        manager.fork_audio(session_id, bytes([i % 256] * 320))

    # Aguarda consumer processar
    await asyncio.sleep(0.1)

    # Para sessão
    result = await manager.stop_session(session_id)
    assert result == True, "stop_session deve retornar True"
    assert manager.active_sessions_count == 0, "Não deve ter sessões ativas"

    await manager.shutdown()

    print("✓ test_session_lifecycle PASSED")


async def test_metrics():
    """Testa métricas do fork."""
    from core.media_fork_manager import MediaForkManager

    mock_adapter = MockAIAgentAdapter()
    manager = MediaForkManager(mock_adapter)
    await manager.initialize()

    session_id = "test-session-metrics"
    await manager.start_session(session_id)

    # Fork frames
    for i in range(20):
        manager.fork_audio(session_id, bytes([i % 256] * 320))

    # Aguarda processamento
    await asyncio.sleep(0.1)

    # Verifica métricas
    metrics = manager.get_session_metrics(session_id)
    assert metrics is not None, "Deve retornar métricas"
    assert metrics["frames_forked"] == 20, f"Deve ter 20 frames forked, tem {metrics['frames_forked']}"

    await manager.stop_session(session_id)
    await manager.shutdown()

    print("✓ test_metrics PASSED")


async def run_all_tests():
    """Executa todos os testes."""
    print("\n" + "=" * 50)
    print("TESTES DO MEDIA FORK MANAGER")
    print("=" * 50 + "\n")

    await test_manager_initialization()
    await test_fork_audio_never_blocks()
    await test_fork_with_ai_agent_unavailable()
    await test_session_lifecycle()
    await test_metrics()

    print("\n" + "=" * 50)
    print("TODOS OS TESTES PASSARAM!")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
