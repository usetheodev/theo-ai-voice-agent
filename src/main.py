#!/usr/bin/env python3
"""
AI Voice Agent - Main Entry Point
"""

import asyncio
import signal
import sys
from pathlib import Path

import click

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.config import AppConfig
from src.common.logging import get_logger
from src.common.metrics import start_metrics_server

logger = get_logger('main')


class Application:
    """Main application orchestrator"""

    def __init__(self, config: AppConfig):
        self.config = config
        self.orchestrator = None
        self.shutdown_event = asyncio.Event()

    async def start(self):
        """Start the application"""
        logger.info('🚀 Starting AI Voice Agent...')

        # Validate config
        errors = self.config.validate()
        if errors:
            for error in errors:
                logger.error('Configuration error', error=error)
            sys.exit(1)

        logger.info('Configuration valid', config=str(self.config))

        # Start metrics server
        start_metrics_server(port=self.config.metrics_port)
        logger.info('Metrics server started', port=self.config.metrics_port)

        # TODO: Import and initialize modules
        # from src.sip import SIPServer
        # from src.rtp import RTPServer
        # from src.ai import Voice2VoicePipeline
        # from src.orchestrator import CallOrchestrator, EventBus

        # event_bus = EventBus()
        # sip_server = SIPServer(config=self.config.sip, event_bus=event_bus)
        # rtp_server = RTPServer(config=self.config.rtp, event_bus=event_bus)
        # ai_pipeline = Voice2VoicePipeline(config=self.config.ai, event_bus=event_bus)

        # self.orchestrator = CallOrchestrator(
        #     sip_server=sip_server,
        #     rtp_server=rtp_server,
        #     ai_pipeline=ai_pipeline,
        #     event_bus=event_bus
        # )

        # await self.orchestrator.start()

        logger.info('✅ AI Voice Agent running')
        logger.info('SIP listening', host=self.config.sip.host, port=self.config.sip.port)
        logger.info('Metrics available', url=f'http://localhost:{self.config.metrics_port}/metrics')

        # Wait for shutdown signal
        await self.shutdown_event.wait()

    async def stop(self):
        """Stop the application gracefully"""
        logger.info('🛑 Shutting down AI Voice Agent...')

        if self.orchestrator:
            await self.orchestrator.stop()

        logger.info('✅ Shutdown complete')

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals (SIGINT, SIGTERM)"""
        logger.info('Shutdown signal received', signal=signum)
        self.shutdown_event.set()


@click.command()
@click.option(
    '--config',
    '-c',
    type=click.Path(exists=True),
    default='config/default.yaml',
    help='Path to configuration file'
)
@click.option(
    '--log-level',
    '-l',
    type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR']),
    default=None,
    help='Override log level from config'
)
def cli(config: str, log_level: str):
    """
    AI Voice Agent - Modular SIP/RTP voice system with AI

    Examples:

        # Use default config
        python src/main.py

        # Use custom config
        python src/main.py --config config/production.yaml

        # Override log level
        python src/main.py --log-level DEBUG
    """
    # Load configuration
    app_config = AppConfig.from_yaml(config)

    # Override log level if provided
    if log_level:
        app_config.log_level = log_level

    # Create application
    app = Application(app_config)

    # Setup signal handlers
    signal.signal(signal.SIGINT, app.handle_shutdown)
    signal.signal(signal.SIGTERM, app.handle_shutdown)

    # Run
    try:
        asyncio.run(app.start())
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(app.stop())


if __name__ == '__main__':
    cli()
