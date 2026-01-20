#!/usr/bin/env python3
"""
AI Voice Agent - Main Entry Point
Handles real-time voice conversations via Asterisk ARI + RTP
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from utils.logger import setup_logger
from utils.config import load_config
from rtp.server import RTPServer
from ari.client import ARIClient


# Global state for call management
active_calls = {}


async def main():
    """Main application entry point"""

    # Setup logging
    logger = setup_logger()
    logger.info("=" * 60)
    logger.info("🤖 AI Voice Agent Starting (Asterisk ARI)...")
    logger.info("=" * 60)

    try:
        # Load configuration
        config = load_config()
        logger.info(f"Configuration loaded: {config.get('app_env', 'development')} environment")

        # Initialize RTP server
        rtp_host = config.get('rtp_host', '0.0.0.0')
        rtp_port = config.get('rtp_port', 5080)

        logger.info(f"Initializing RTP server on {rtp_host}:{rtp_port}")
        rtp_server = RTPServer(host=rtp_host, port=rtp_port, config=config)

        # Start RTP server
        await rtp_server.start()

        # Initialize ARI client
        ari_host = config.get('asterisk_host', 'asterisk')
        ari_port = config.get('asterisk_ari_port', 8088)
        ari_user = config.get('asterisk_ari_user', 'aiagent')
        ari_pass = config.get('asterisk_ari_password', 'ChangeMe123!')

        logger.info(f"Initializing ARI client: {ari_host}:{ari_port}")
        ari_client = ARIClient(
            host=ari_host,
            port=ari_port,
            username=ari_user,
            password=ari_pass,
            app_name='aiagent'
        )

        # Register ARI event handlers
        async def on_stasis_start(msg):
            """Handle incoming call entering Stasis application"""
            channel = msg.channel
            channel_id = channel.id

            # CRITICAL: Ignore StasisStart from ExternalMedia channels to prevent infinite loop
            # ExternalMedia channels start with "UnicastRTP/" technology
            if channel.json.get('name', '').startswith('UnicastRTP/'):
                logger.debug(f"Ignoring StasisStart for ExternalMedia channel: {channel_id}")
                return

            logger.info("=" * 60)
            logger.info("📞 New call received!")

            caller_number = channel.json.get('caller', {}).get('number', 'Unknown')

            logger.info(f"   Channel ID: {channel_id}")
            logger.info(f"   Caller: {caller_number}")

            # Answer the call
            await ari_client.answer_channel(channel)

            # Create ExternalMedia channel (routes RTP to AI Agent)
            # Use alaw codec to match WebRTC endpoint priority
            external_channel = await ari_client.create_external_media(
                external_host='172.20.0.20',  # AI Agent container IP
                external_port=rtp_port,
                codec='alaw'  # Match WebRTC endpoint codec priority
            )

            if not external_channel:
                logger.error("Failed to create ExternalMedia channel")
                await ari_client.hangup_channel(channel)
                return

            external_channel_id = external_channel.id
            logger.info(f"✅ ExternalMedia channel created: {external_channel_id}")

            # Create bridge and connect both channels
            bridge = await ari_client.create_bridge(bridge_type='mixing')
            if not bridge:
                logger.error("Failed to create bridge")
                await ari_client.hangup_channel(channel)
                return

            bridge_id = bridge.id

            # Add both channels to bridge
            await ari_client.add_channel_to_bridge(bridge_id, channel_id)
            await ari_client.add_channel_to_bridge(bridge_id, external_channel_id)

            # Store call state
            active_calls[channel_id] = {
                'channel_id': channel_id,
                'external_channel_id': external_channel_id,
                'bridge_id': bridge_id,
                'caller': caller_number
            }

            logger.info(f"✅ Call bridged successfully!")
            logger.info(f"   Bridge ID: {bridge_id}")
            logger.info("=" * 60)

        async def on_stasis_end(msg):
            """Handle call leaving Stasis application (hangup)"""
            channel = msg.channel
            channel_id = channel.id

            logger.info(f"📞 Call ended: {channel_id}")

            # Cleanup
            if channel_id in active_calls:
                call_data = active_calls[channel_id]

                # Destroy bridge
                await ari_client.destroy_bridge(call_data['bridge_id'])

                # Hangup external channel (pass channel ID string)
                await ari_client.hangup_channel(call_data['external_channel_id'])

                del active_calls[channel_id]

                logger.info(f"✅ Call cleanup completed")

        async def on_channel_dtmf_received(msg):
            """Handle DTMF tones (future use for barge-in)"""
            channel = msg.channel
            channel_id = channel.id
            digit = msg.digit

            logger.info(f"📟 DTMF received on {channel_id}: {digit}")

        # Register handlers
        ari_client.on('StasisStart', on_stasis_start)
        ari_client.on('StasisEnd', on_stasis_end)
        ari_client.on('ChannelDtmfReceived', on_channel_dtmf_received)

        logger.info("✅ AI Voice Agent is ready!")
        logger.info(f"   - RTP listening on UDP {rtp_host}:{rtp_port}")
        logger.info(f"   - ARI connecting to {ari_host}:{ari_port}")
        logger.info(f"   - Stasis app: aiagent")
        logger.info(f"   - Dial 9999 from extension 1000 to test")
        logger.info("=" * 60)

        # Run ARI event loop (blocks until disconnected)
        await ari_client.run()

    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down gracefully...")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("👋 AI Voice Agent stopped")


if __name__ == "__main__":
    asyncio.run(main())
