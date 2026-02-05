"""
Transcriber - Modulo para transcricao de audio
"""

from transcriber.stt_provider import STTProvider, create_stt_provider

__all__ = [
    "STTProvider",
    "create_stt_provider",
]
