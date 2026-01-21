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

            # =========================================================
            # Phase 5.2: Allocate Dynamic Port Per Call
            # =========================================================

            # Allocate dedicated RTP port for this call
            call_id_temp = f"{channel_id}_temp"  # Temporary call_id for port allocation
            allocated_port = await rtp_server.allocate_port(call_id_temp)

            if not allocated_port:
                logger.error("Failed to allocate RTP port (all ports in use)")
                await ari_client.hangup_channel(channel)
                return

            logger.info(f"🔌 Allocated RTP port {allocated_port} for call {channel_id}")

            # Create ExternalMedia channel (routes RTP to AI Agent)
            # Use allocated port instead of shared port
            external_channel = await ari_client.create_external_media(
                external_host='172.20.0.20',  # AI Agent container IP
                external_port=allocated_port,  # Use dynamically allocated port
                codec='alaw'  # Match WebRTC endpoint codec priority
            )

            if not external_channel:
                logger.error("Failed to create ExternalMedia channel")
                # Release allocated port on failure
                rtp_server._release_port(allocated_port)
                await ari_client.hangup_channel(channel)
                return

            external_channel_id = external_channel.id
            logger.info(f"✅ ExternalMedia channel created: {external_channel_id}")

            # CRITICAL: Get UNICASTRTP variables - these tell us WHERE to SEND RTP back to Asterisk
            # ExternalMedia creates a UnicastRTP channel with specific listen address/port
            # We must send to THOSE coordinates, not to where we receive from (different ports!)
            unicast_address = None
            unicast_port = None

            try:
                # Get UNICASTRTP_LOCAL_ADDRESS
                addr_result = await ari_client.client.channels.getChannelVar(
                    channelId=external_channel_id,
                    variable='UNICASTRTP_LOCAL_ADDRESS'
                )
                unicast_address = addr_result.get('value')

                # Get UNICASTRTP_LOCAL_PORT
                port_result = await ari_client.client.channels.getChannelVar(
                    channelId=external_channel_id,
                    variable='UNICASTRTP_LOCAL_PORT'
                )
                unicast_port = port_result.get('value')

                if unicast_address and unicast_port:
                    logger.info(f"📍 Asterisk RTP listen endpoint: {unicast_address}:{unicast_port}")
                else:
                    logger.warning(f"⚠️  UNICASTRTP variables not found - will use symmetric RTP fallback")
            except Exception as e:
                logger.warning(f"⚠️  Failed to get UNICASTRTP variables: {e}")

            # Create RTP session with dedicated socket on allocated port
            call_id = f"{channel_id}_rtp"
            session = await rtp_server.create_session_with_port(call_id, allocated_port)

            # CRITICAL CHANGE: Use SYMMETRIC RTP (learn from received packets)
            # The reference project (Asterisk-AI-Voice-Agent) uses symmetric RTP successfully
            # UNICASTRTP variables stored for potential future use, but NOT pre-setting remote_addr
            if unicast_address and unicast_port:
                logger.info(f"📝 UNICASTRTP available: {unicast_address}:{unicast_port} (using symmetric RTP instead)")

            logger.info(f"✅ RTP session created with symmetric RTP (will learn from first packet)")

            if not session:
                logger.error("Failed to create RTP session with allocated port")
                # Release allocated port on failure
                rtp_server._release_port(allocated_port)
                await ari_client.hangup_channel(channel)
                return

            logger.info(f"✅ RTP session created: {call_id} on port {allocated_port}")

            # Create bridge with 'mixing' type (forces softmix)
            # Reference: Asterisk-AI-Voice-Agent uses bridge_type='mixing' exactly
            bridge = await ari_client.create_bridge(bridge_type='mixing')
            if not bridge:
                logger.error("Failed to create bridge")
                await ari_client.hangup_channel(channel)
                return

            bridge_id = bridge.id

            # Add both channels to bridge
            await ari_client.add_channel_to_bridge(bridge_id, channel_id)
            await ari_client.add_channel_to_bridge(bridge_id, external_channel_id)

            logger.info(f"✅ Channels bridged with mixing bridge (softmix)")

            # Store call state
            active_calls[channel_id] = {
                'channel_id': channel_id,
                'external_channel_id': external_channel_id,
                'bridge_id': bridge_id,
                'caller': caller_number,
                'rtp_call_id': call_id,  # For RTP session cleanup
                'allocated_port': allocated_port  # For port release on hangup
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

                # Phase 5.3: Cleanup RTP session (closes socket and releases port)
                if 'rtp_call_id' in call_data:
                    await rtp_server.cleanup_session(call_data['rtp_call_id'])
                    logger.info(f"✅ RTP session cleaned up: {call_data['rtp_call_id']}")

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
        logger.info(f"   - RTP dynamic port range: {rtp_server.port_range[0]}-{rtp_server.port_range[1]}")
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
