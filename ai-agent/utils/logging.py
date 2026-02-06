"""
Structured logging com correlation ID (session_id / call_id).

Fornece um SessionLoggerAdapter que injeta automaticamente session_id
em todas as mensagens de log, permitindo filtrar por sessão.

Uso:
    from utils.logging import get_session_logger

    logger = get_session_logger("ai-agent.pipeline", session_id="abc123")
    logger.info("Processando áudio")
    # Output: [session_id=abc123] Processando áudio

    logger.info("STT completo", extra={"stage": "stt", "duration_ms": 890})
    # Output: [session_id=abc123] [stage=stt] STT completo (890ms)
"""

import logging
from typing import Optional, MutableMapping, Any


class SessionLoggerAdapter(logging.LoggerAdapter):
    """Logger que injeta session_id e stage em todas as mensagens."""

    def __init__(
        self,
        logger: logging.Logger,
        session_id: str,
        call_id: str = "",
    ):
        super().__init__(logger, {
            "session_id": session_id[:8] if session_id else "",
            "call_id": call_id[:8] if call_id else "",
        })

    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple:
        """Adiciona prefixo com session_id e stage opcional."""
        extra = kwargs.get("extra", {})

        # Prefixo com session_id
        session_id = self.extra.get("session_id", "")
        prefix = f"[session_id={session_id}]" if session_id else ""

        # Stage opcional (stt, llm, tts) - usa get() para não mutar dict do caller
        stage = extra.get("stage")
        if stage:
            prefix = f"{prefix} [stage={stage}]"

        # Duration opcional
        duration_ms = extra.get("duration_ms")
        suffix = f" ({duration_ms:.0f}ms)" if duration_ms is not None else ""

        # Copia extra sem campos consumidos para evitar mutar dict do caller
        filtered_extra = {k: v for k, v in extra.items() if k not in ("stage", "duration_ms")}
        kwargs["extra"] = {**self.extra, **filtered_extra}
        return f"{prefix} {msg}{suffix}", kwargs


def get_session_logger(
    name: str,
    session_id: str,
    call_id: str = "",
) -> SessionLoggerAdapter:
    """Cria um logger com correlation ID para uma sessão.

    Args:
        name: Nome do logger (ex: "ai-agent.pipeline")
        session_id: ID da sessão (será truncado para 8 chars)
        call_id: ID da chamada (opcional)

    Returns:
        SessionLoggerAdapter com contexto de sessão
    """
    base_logger = logging.getLogger(name)
    return SessionLoggerAdapter(base_logger, session_id, call_id)
