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

from config import LOG_CONFIG, SIP_CONFIG, AI_AGENT_CONFIG, SBC_CONFIG, METRICS_CONFIG, MEDIA_FORK_CONFIG, TRANSCRIBE_CONFIG, AMI_CONFIG
from adapters.ai_agent_adapter import AIAgentAdapter
from adapters.transcribe_adapter import TranscribeAdapter
from sip.endpoint import SIPEndpoint
from metrics import start_metrics_server, SIP_REGISTRATION_STATUS
from core.media_fork_manager import MediaForkManager
from ami.client import AMIClient

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
        self.transcribe_adapter: TranscribeAdapter = None
        self.fork_manager: MediaForkManager = None
        self.ami_client: AMIClient = None
        self.sip_endpoint: SIPEndpoint = None
        self.loop: asyncio.AbstractEventLoop = None
        self.running = False
        self._shutdown_event = asyncio.Event()
        self._sip_ready_event: asyncio.Event = None  # Criado dentro do event loop

    async def start(self):
        """Inicia o Media Server"""
        logger.info("=" * 60)
        logger.info(" MEDIA SERVER - SIP Bridge")
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

        # Conecta ao AI Transcribe (se habilitado)
        if TRANSCRIBE_CONFIG.get("enabled", False):
            self.transcribe_adapter = TranscribeAdapter()
            if await self.transcribe_adapter.connect():
                logger.info("Conectado ao AI Transcribe")
            else:
                logger.warning("Falha ao conectar ao AI Transcribe - transcricao desabilitada")
                self.transcribe_adapter = None
        else:
            logger.info("AI Transcribe desabilitado via config")

        # Conecta ao AMI (Asterisk Manager Interface) para controle de chamadas
        if AMI_CONFIG.get("enabled", True):
            self.ami_client = AMIClient(
                host=AMI_CONFIG["host"],
                port=AMI_CONFIG["port"],
                username=AMI_CONFIG["username"],
                secret=AMI_CONFIG["secret"],
                timeout=AMI_CONFIG["timeout"],
            )
            if await self.ami_client.connect():
                logger.info("Conectado ao AMI (Asterisk Manager Interface)")
            else:
                logger.warning("Falha ao conectar ao AMI - transfer de chamadas indisponivel")
                self.ami_client = None
        else:
            logger.info("AMI desabilitado via config")

        # Inicializa Media Fork Manager (isolamento do path de IA)
        if MEDIA_FORK_CONFIG.get("enabled", True):
            self.fork_manager = MediaForkManager(
                self.audio_destination,
                transcribe_adapter=self.transcribe_adapter,
            )
            if await self.fork_manager.initialize():
                logger.info(" Media Fork Manager inicializado")
            else:
                logger.warning("Falha ao inicializar Media Fork Manager - continuando sem fork")
                self.fork_manager = None
        else:
            logger.info("Media Fork desabilitado via config")

        # Cria evento de sincronização dentro do event loop
        self._sip_ready_event = asyncio.Event()

        # Inicia endpoint SIP em thread separada (pjsua2 não é asyncio)
        sip_thread = threading.Thread(target=self._run_sip, daemon=True)
        sip_thread.start()

        # Aguarda SIP sinalizar que está pronto (com timeout de segurança)
        try:
            await asyncio.wait_for(self._sip_ready_event.wait(), timeout=15)
        except asyncio.TimeoutError:
            logger.warning("Timeout aguardando SIP ficar pronto - continuando")

        self._log_status()

        # Aguarda shutdown
        await self._shutdown_event.wait()

    def _on_sip_state_change(self, state: str):
        """Callback para mudança de estado SIP (chamado do event loop)"""
        logger.info(f"SIP state change: {state}")

        if state == 'registered' or state == 'recreated':
            SIP_REGISTRATION_STATUS.state('registered')
        elif state == 'unregistered':
            SIP_REGISTRATION_STATUS.state('unregistered')
        elif state == 'failed':
            SIP_REGISTRATION_STATUS.state('failed')
            # Notifica adaptadores que SIP caiu
            if self.audio_destination and self.audio_destination.is_connected:
                logger.warning("SIP down - sessões ativas podem ser afetadas")

    def _run_sip(self):
        """Executa endpoint SIP (em thread separada)"""
        try:
            self.sip_endpoint = SIPEndpoint(
                self.audio_destination,
                self.loop,
                fork_manager=self.fork_manager,
                ami_client=self.ami_client,
            )
            self.sip_endpoint.set_on_sip_state_change(self._on_sip_state_change)
            self.sip_endpoint.start()

            # Sinaliza que SIP está pronto (thread-safe)
            self.loop.call_soon_threadsafe(self._sip_ready_event.set)

            # Loop principal do SIP
            while self.running:
                time.sleep(0.1)

        except Exception as e:
            logger.error(f"Erro no SIP: {e}")
            import traceback
            traceback.print_exc()
            # Sinaliza ready mesmo em erro para não travar o startup
            if self._sip_ready_event and self.loop:
                try:
                    self.loop.call_soon_threadsafe(self._sip_ready_event.set)
                except Exception:
                    pass

    def _log_status(self):
        """Exibe status do servidor"""
        logger.info("")
        logger.info(" Componentes:")
        logger.info(f"   • WebSocket Client -> {AI_AGENT_CONFIG['url']}")
        logger.info(f"   • SIP Endpoint -> {SIP_CONFIG['domain']}:{SIP_CONFIG['port']}")
        if self.fork_manager:
            logger.info(f"   • Media Fork Manager -> buffer={MEDIA_FORK_CONFIG['buffer_ms']}ms")
        if self.ami_client:
            logger.info(f"   • AMI Client -> {AMI_CONFIG['host']}:{AMI_CONFIG['port']}")
        if self.transcribe_adapter:
            logger.info(f"   • AI Transcribe -> {TRANSCRIBE_CONFIG['url']}")
        if METRICS_CONFIG.get("enabled", True):
            logger.info(f"   • Prometheus Metrics -> http://0.0.0.0:{METRICS_CONFIG['port']}/metrics")
        logger.info("")

        if SBC_CONFIG["enabled"]:
            logger.info(" Modo: SBC Externo")
            logger.info(f"   SBC: {SBC_CONFIG['host']}:{SBC_CONFIG['port']}")
        else:
            logger.info(" Modo: Asterisk Local")
            logger.info(f"   Servidor: {SIP_CONFIG['domain']}:{SIP_CONFIG['port']}")

        logger.info("")
        logger.info(f"   Ramal: {SIP_CONFIG['username']}")
        logger.info("")

        if self.fork_manager:
            logger.info("   Fluxo de dados (Media Fork):")
            if self.transcribe_adapter:
                logger.info("    SIP/RTP → [Fork] → RingBuffer → Consumer → AI Agent")
                logger.info("                                          → AI Transcribe")
            else:
                logger.info("    SIP/RTP → [Fork] → RingBuffer → Consumer → AI Agent")
            logger.info("                ↓")
            logger.info("           Path critico NUNCA bloqueia")
        else:
            logger.info("   Fluxo de dados:")
            logger.info("    SIP/RTP ←→  WebSocket ←→  AI Agent")

        logger.info("")
        logger.info("   Aguardando chamadas...")
        logger.info("=" * 60)

    async def stop(self):
        """Para o Media Server"""
        logger.info(" Parando Media Server...")
        self.running = False

        if self.sip_endpoint:
            self.sip_endpoint.stop()

        # Para Media Fork Manager
        if self.fork_manager:
            await self.fork_manager.shutdown()

        if self.audio_destination:
            await self.audio_destination.disconnect()

        if self.transcribe_adapter:
            await self.transcribe_adapter.disconnect()

        if self.ami_client:
            await self.ami_client.close()

        self._shutdown_event.set()
        logger.info(" Media Server parado")

    def trigger_shutdown(self):
        """Dispara shutdown (chamado de signal handler)"""
        if self.loop:
            self.loop.call_soon_threadsafe(self._shutdown_event.set)


async def main():
    """Função principal"""
    server = MediaServer()

    # Handler para shutdown graceful
    def signal_handler(_signum, _frame):
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
