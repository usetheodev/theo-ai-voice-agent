"""
Latency Budget Tracker — mede latência voice-to-voice E2E por estágio.

Cada interação (audio_end → primeiro byte de resposta) é rastreada com
breakdown por estágio: STT, LLM (TTFT + total), TTS (TTFB).

Quando a latência total excede o budget, emite warning com breakdown.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from metrics import VOICE_TO_VOICE_LATENCY, LATENCY_BUDGET_EXCEEDED

logger = logging.getLogger("ai-agent.latency-budget")

# Budget padrão em ms (voice-to-voice)
DEFAULT_BUDGET_MS = 1500.0


@dataclass
class LatencyBudget:
    """Rastreia latência E2E de uma interação com breakdown por estágio.

    Usage:
        budget = LatencyBudget()
        budget.start()

        # ... STT ...
        budget.record_stage('stt', duration_ms)

        # ... LLM ...
        budget.record_stage('llm_ttft', duration_ms)
        budget.record_stage('llm_total', duration_ms)

        # ... TTS ...
        budget.record_stage('tts_ttfb', duration_ms)

        budget.finish()
    """

    target_ms: float = DEFAULT_BUDGET_MS
    stages: Dict[str, float] = field(default_factory=dict)
    _start_time: Optional[float] = None
    _end_time: Optional[float] = None

    def start(self):
        """Marca início da interação (audio_end recebido)"""
        self._start_time = time.perf_counter()

    def start_from(self, timestamp: float):
        """Usa um timestamp perf_counter já existente como início"""
        self._start_time = timestamp

    def record_stage(self, stage: str, duration_ms: float):
        """Registra duração de um estágio em ms"""
        self.stages[stage] = duration_ms

    def finish(self):
        """Finaliza a medição, registra métricas e loga se excedeu budget"""
        if self._start_time is None:
            return

        self._end_time = time.perf_counter()
        total_s = self._end_time - self._start_time
        total_ms = total_s * 1000

        # Registra métrica Prometheus
        VOICE_TO_VOICE_LATENCY.observe(total_s)

        # Verifica budget
        if total_ms > self.target_ms:
            LATENCY_BUDGET_EXCEEDED.inc()
            stages_str = ", ".join(
                f"{k}: {v:.0f}ms" for k, v in self.stages.items()
            )
            logger.warning(
                f"Latency budget exceeded: {total_ms:.0f}ms "
                f"(budget: {self.target_ms:.0f}ms) - {stages_str}"
            )
        else:
            stages_str = ", ".join(
                f"{k}: {v:.0f}ms" for k, v in self.stages.items()
            )
            logger.info(
                f"Latency OK: {total_ms:.0f}ms "
                f"(budget: {self.target_ms:.0f}ms) - {stages_str}"
            )

    @property
    def total_ms(self) -> float:
        """Retorna latência total em ms"""
        if self._start_time is None:
            return 0.0
        end = self._end_time or time.perf_counter()
        return (end - self._start_time) * 1000

    @property
    def is_over_budget(self) -> bool:
        """Verifica se a latência atual excede o budget"""
        return self.total_ms > self.target_ms

    def report(self) -> dict:
        """Retorna relatório da interação"""
        return {
            "total_ms": self.total_ms,
            "target_ms": self.target_ms,
            "over_budget": self.is_over_budget,
            "stages": dict(self.stages),
        }
