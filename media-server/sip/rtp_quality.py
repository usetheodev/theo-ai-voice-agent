"""
RTP Quality Tracker - Calcula packet loss e jitter

Analisa qualidade RTP baseado em frames de áudio recebidos,
calculando métricas de jitter e estimando packet loss.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

from metrics import track_rtp_jitter, track_rtp_packet, track_rtp_packet_loss_ratio

logger = logging.getLogger("media-server.rtp_quality")


@dataclass
class RtpQualityTracker:
    """Rastreia qualidade RTP baseado em análise de frames"""

    # Configuração
    expected_interval_ms: float = 20.0  # 20ms frames (padrão PJSIP)
    direction: str = "inbound"

    # Estado
    last_timestamp: Optional[float] = None

    # Contadores
    packets_received: int = 0
    packets_expected: int = 0
    jitter_sum: float = 0.0
    jitter_count: int = 0

    # Para detectar gaps (possível packet loss)
    gap_threshold_factor: float = 1.5  # Gap > 1.5x intervalo = possível loss

    def track_frame(self, frame_size: int):
        """
        Chamado para cada frame de áudio recebido.

        Args:
            frame_size: Tamanho do frame em bytes
        """
        now = time.perf_counter()

        self.packets_received += 1
        self.packets_expected += 1

        if self.last_timestamp is not None:
            # Calcula intervalo real entre frames
            interval_ms = (now - self.last_timestamp) * 1000

            # Calcula jitter (variação do inter-arrival time)
            jitter = abs(interval_ms - self.expected_interval_ms)

            self.jitter_sum += jitter
            self.jitter_count += 1

            # Registra no Prometheus
            track_rtp_jitter(self.direction, jitter)

            # Detecta possível packet loss (gap > 1.5x intervalo esperado)
            if interval_ms > self.expected_interval_ms * self.gap_threshold_factor:
                # Estima quantos pacotes foram perdidos
                estimated_lost = int(interval_ms / self.expected_interval_ms) - 1
                if estimated_lost > 0:
                    self.packets_expected += estimated_lost
                    track_rtp_packet(self.direction, 'lost', estimated_lost)
                    logger.debug(
                        f"[RTP] Possível packet loss: gap={interval_ms:.1f}ms, "
                        f"estimado {estimated_lost} pacotes perdidos"
                    )

        self.last_timestamp = now
        track_rtp_packet(self.direction, 'received')

    def get_loss_ratio(self) -> float:
        """Retorna taxa de perda (0-1)"""
        if self.packets_expected == 0:
            return 0.0
        return 1.0 - (self.packets_received / self.packets_expected)

    def get_avg_jitter_ms(self) -> float:
        """Retorna jitter médio em ms"""
        if self.jitter_count == 0:
            return 0.0
        return self.jitter_sum / self.jitter_count

    def update_gauges(self):
        """Atualiza gauges do Prometheus com valores finais"""
        loss_ratio = self.get_loss_ratio()
        track_rtp_packet_loss_ratio(self.direction, loss_ratio)

        avg_jitter = self.get_avg_jitter_ms()
        logger.info(
            f"[RTP Quality] {self.direction}: "
            f"received={self.packets_received}, "
            f"expected={self.packets_expected}, "
            f"loss={loss_ratio*100:.2f}%, "
            f"avg_jitter={avg_jitter:.1f}ms"
        )

    def reset(self):
        """Reseta contadores para nova sessão"""
        self.last_timestamp = None
        self.packets_received = 0
        self.packets_expected = 0
        self.jitter_sum = 0.0
        self.jitter_count = 0
