#!/usr/bin/env python3
"""
AI Agent - Servidor de Conversação
Pipeline: Áudio → STT → LLM → TTS → Áudio

Recebe áudio via WebSocket do Media Server e retorna respostas processadas.
"""

import os
import sys
import signal
import logging
import asyncio

from config import LOG_CONFIG, WS_CONFIG, METRICS_CONFIG
from server.websocket import AIAgentServer
from metrics import start_metrics_server

# Logging
logging.basicConfig(
    level=getattr(logging, LOG_CONFIG["level"]),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ai-agent")


async def main():
    """Função principal"""
    logger.info("=" * 60)
    logger.info(" AI AGENT - Servidor de Conversação")
    logger.info("=" * 60)

    # Inicia servidor de métricas Prometheus
    if METRICS_CONFIG.get("enabled", True):
        metrics_port = METRICS_CONFIG.get("port", 9090)
        start_metrics_server(metrics_port)
    else:
        metrics_port = None
        logger.info(" Métricas Prometheus desabilitadas")

    # Cria servidor
    server = AIAgentServer()

    # Handler para shutdown graceful
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Recebido sinal de shutdown...")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    try:
        # Inicia servidor
        await server.start()

        logger.info("")
        logger.info(" Componentes:")
        logger.info("   • WebSocket Server")
        logger.info("   • STT (Speech-to-Text)")
        logger.info("   • LLM (Language Model)")
        logger.info("   • TTS (Text-to-Speech)")
        if metrics_port:
            logger.info("   • Prometheus Metrics")
        logger.info("")
        logger.info(f" Escutando em: ws://{WS_CONFIG['host']}:{WS_CONFIG['port']}")
        if metrics_port:
            logger.info(f" Métricas em: http://0.0.0.0:{metrics_port}/metrics")
        logger.info("")
        logger.info("   Pipeline de conversação:")
        logger.info("    Áudio →  STT →  LLM →  TTS →  Áudio")
        logger.info("")
        logger.info("   Aguardando conexões do Media Server...")
        logger.info("=" * 60)

        # Aguarda shutdown
        await shutdown_event.wait()

    except Exception as e:
        logger.error(f"Erro fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        logger.info(" Parando servidor...")
        await server.stop()
        logger.info(" Servidor parado")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
