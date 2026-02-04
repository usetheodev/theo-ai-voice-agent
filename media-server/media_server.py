#!/usr/bin/env python3
"""
Media Server - SIP Bridge
Ponte entre Asterisk (SIP/RTP) e AI Agent (WebSocket)
"""

import os
import sys
import time
import signal
import logging
import asyncio
import threading

from config import LOG_CONFIG, SIP_CONFIG, AI_AGENT_CONFIG, SBC_CONFIG, METRICS_CONFIG
from adapters.ai_agent_adapter import AIAgentAdapter
from sip.endpoint import SIPEndpoint
from metrics import start_metrics_server

# Logging
logging.basicConfig(
    level=getattr(logging, LOG_CONFIG["level"]),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("media-server")


class MediaServer:
    """Media Server - SIP Bridge"""

    def __init__(self):
        self.audio_destination: AIAgentAdapter = None
        self.sip_endpoint: SIPEndpoint = None
        self.loop: asyncio.AbstractEventLoop = None
        self.running = False
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Inicia o Media Server"""
        logger.info("=" * 60)
        logger.info("📡 MEDIA SERVER - SIP Bridge")
        logger.info("=" * 60)

        # Inicia servidor de métricas Prometheus
        if METRICS_CONFIG.get("enabled", True):
            start_metrics_server(METRICS_CONFIG["port"])

        self.running = True
        self.loop = asyncio.get_event_loop()

        # Conecta ao destino de áudio (AI Agent por padrão)
        self.audio_destination = AIAgentAdapter()
        if not await self.audio_destination.connect():
            logger.error("Falha ao conectar ao destino de áudio")
            # Continua mesmo sem conexão - tentará reconectar
            logger.info("Continuando sem conexão - reconexão automática ativa")

        # Inicia endpoint SIP em thread separada (pjsua2 não é asyncio)
        sip_thread = threading.Thread(target=self._run_sip, daemon=True)
        sip_thread.start()

        # Aguarda SIP estar pronto
        await asyncio.sleep(2)

        self._log_status()

        # Aguarda shutdown
        await self._shutdown_event.wait()

    def _run_sip(self):
        """Executa endpoint SIP (em thread separada)"""
        try:
            self.sip_endpoint = SIPEndpoint(self.audio_destination, self.loop)
            self.sip_endpoint.start()

            # Loop principal do SIP
            while self.running:
                time.sleep(0.1)

        except Exception as e:
            logger.error(f"Erro no SIP: {e}")
            import traceback
            traceback.print_exc()

    def _log_status(self):
        """Exibe status do servidor"""
        logger.info("")
        logger.info("📦 Componentes:")
        logger.info(f"   • WebSocket Client -> {AI_AGENT_CONFIG['url']}")
        logger.info(f"   • SIP Endpoint -> {SIP_CONFIG['domain']}:{SIP_CONFIG['port']}")
        if METRICS_CONFIG.get("enabled", True):
            logger.info(f"   • Prometheus Metrics -> http://0.0.0.0:{METRICS_CONFIG['port']}/metrics")
        logger.info("")

        if SBC_CONFIG["enabled"]:
            logger.info("📡 Modo: SBC Externo")
            logger.info(f"   SBC: {SBC_CONFIG['host']}:{SBC_CONFIG['port']}")
        else:
            logger.info("📡 Modo: Asterisk Local")
            logger.info(f"   Servidor: {SIP_CONFIG['domain']}:{SIP_CONFIG['port']}")

        logger.info("")
        logger.info(f"   Ramal: {SIP_CONFIG['username']}")
        logger.info("")
        logger.info("   Fluxo de dados:")
        logger.info("   📞 SIP/RTP ←→ 🌐 WebSocket ←→ 🤖 AI Agent")
        logger.info("")
        logger.info("   Aguardando chamadas...")
        logger.info("=" * 60)

    async def stop(self):
        """Para o Media Server"""
        logger.info("🛑 Parando Media Server...")
        self.running = False

        if self.sip_endpoint:
            self.sip_endpoint.stop()

        if self.audio_destination:
            await self.audio_destination.disconnect()

        self._shutdown_event.set()
        logger.info("✅ Media Server parado")

    def trigger_shutdown(self):
        """Dispara shutdown (chamado de signal handler)"""
        if self.loop:
            self.loop.call_soon_threadsafe(self._shutdown_event.set)


async def main():
    """Função principal"""
    server = MediaServer()

    # Handler para shutdown graceful
    def signal_handler(signum, frame):
        logger.info("Recebido sinal de shutdown...")
        server.trigger_shutdown()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        await server.start()
    except Exception as e:
        logger.error(f"Erro fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
