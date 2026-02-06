"""
MOS Estimator — Simplified E-model (ITU-T G.107)

Estimates Mean Opinion Score (MOS) from network quality metrics:
- Packet loss percentage
- Jitter (ms)
- Round-trip time (ms)
- Codec type

MOS scale: 1.0 (bad) to 4.5 (excellent)
"""

import logging
import math

logger = logging.getLogger("media-server.mos")

# Codec-specific impairment factors (Ie)
# Lower = better quality
CODEC_IMPAIRMENT = {
    "g711": 0,       # G.711 (ulaw/alaw) - no impairment
    "ulaw": 0,
    "alaw": 0,
    "g729": 10,      # G.729 - some compression artifacts
    "opus": 5,       # Opus - very good but not transparent
    "g722": 2,       # G.722 - wideband, minimal impairment
}


def estimate_mos(
    packet_loss_pct: float = 0.0,
    jitter_ms: float = 0.0,
    rtt_ms: float = 0.0,
    codec: str = "g711",
) -> float:
    """
    Estimate MOS using simplified E-model (ITU-T G.107).

    Args:
        packet_loss_pct: Packet loss percentage (0-100)
        jitter_ms: Jitter in milliseconds
        rtt_ms: Round-trip time in milliseconds
        codec: Codec name for impairment factor

    Returns:
        MOS score (1.0-4.5)
    """
    # Base R-factor (excellent quality)
    R = 93.2

    # Delay impairment (Id)
    # Effective delay = one-way delay + jitter buffer delay
    one_way_delay = rtt_ms / 2.0 + jitter_ms
    if one_way_delay < 177.3:
        Id = 0.024 * one_way_delay + 0.11 * max(0, one_way_delay - 177.3)
    else:
        Id = 0.024 * one_way_delay + 0.11 * (one_way_delay - 177.3)

    # Equipment impairment (Ie-eff)
    # Includes codec impairment + packet loss penalty
    Ie = CODEC_IMPAIRMENT.get(codec.lower(), 5)
    # Packet loss penalty (BurstR=1 for random loss)
    Ppl = packet_loss_pct
    BurstR = 1.0
    Ie_eff = Ie + (95 - Ie) * (Ppl / (Ppl + BurstR))

    # Advantage factor (0 for VoIP/wired)
    A = 0

    # R-factor
    R = R - Id - Ie_eff + A

    # Clamp R to valid range
    R = max(0, min(100, R))

    # R-factor to MOS conversion
    if R < 6.5:
        mos = 1.0
    elif R > 100:
        mos = 4.5
    else:
        mos = 1 + 0.035 * R + R * (R - 60) * (100 - R) * 7e-6

    # Clamp MOS
    mos = max(1.0, min(4.5, mos))

    return round(mos, 2)
