#!/usr/bin/env python3
"""
ARI (Asterisk REST Interface) Client using asyncari
Handles communication with Asterisk via HTTP/WebSocket
"""

import logging
import asyncio
from typing import Dict, Any, Optional, Callable
from asyncari import connect as ari_connect
from asyncari.model import Channel, Bridge


class ARIClient:
    """
    Asterisk REST Interface (ARI) client using asyncari

    Manages:
    - WebSocket connection for real-time events
    - HTTP API calls for channel/bridge control
    - ExternalMedia channel creation
    """

    def __init__(self,
                 host: str = 'asterisk',
                 port: int = 8088,
                 username: str = 'aiagent',
                 password: str = 'ChangeMe123!',
                 app_name: str = 'aiagent'):
        """
        Initialize ARI client

        Args:
            host: Asterisk hostname/IP
            port: ARI HTTP port (default 8088)
            username: ARI user (configured in ari.conf)
            password: ARI password
            app_name: Stasis application name
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.app_name = app_name

        self.base_url = f"http://{host}:{port}"

        self.logger = logging.getLogger("ai-voice-agent.ari")

        self.client = None
        self.running = False

        # Event handlers
        self.handlers: Dict[str, Callable] = {}

        self.logger.info(f"ARI Client initialized: {host}:{port} app={app_name}")

    def on(self, event_type: str, handler: Callable):
        """
        Register event handler

        Args:
            event_type: ARI event type (e.g., 'StasisStart', 'ChannelDtmfReceived')
            handler: Async callback function(event_data)
        """
        self.handlers[event_type] = handler
        self.logger.debug(f"Registered handler for event: {event_type}")

    async def run(self):
        """
        Connect to ARI and run event loop

        This should be called as the main entry point.
        It will block until disconnected.
        """
        try:
            self.logger.info("Connecting to ARI WebSocket...")

            # Connect using asyncari context manager
            async with ari_connect(
                self.base_url,
                self.app_name,
                self.username,
                self.password
            ) as client:
                self.client = client
                self.running = True

                self.logger.info("✅ ARI WebSocket connected")

                # Main event loop - iterate over all events
                async for msg in client:
                    event_type = msg.type
                    self.logger.debug(f"ARI Event: {event_type}")

                    # Call registered handler if exists
                    if event_type in self.handlers:
                        try:
                            handler = self.handlers[event_type]
                            # Call handler (may be sync or async)
                            if asyncio.iscoroutinefunction(handler):
                                # Use taskgroup to run handler concurrently
                                client.taskgroup.start_soon(handler, msg)
                            else:
                                handler(msg)
                        except Exception as e:
                            self.logger.error(f"Error in event handler for {event_type}: {e}", exc_info=True)

        except Exception as e:
            self.logger.error(f"ARI connection error: {e}", exc_info=True)
            self.running = False
        finally:
            self.running = False
            self.client = None
            self.logger.info("ARI disconnected")

    async def create_external_media(self,
                                   external_host: str,
                                   external_port: int,
                                   codec: str = 'alaw',
                                   channel_id: Optional[str] = None) -> Optional[Channel]:
        """
        Create ExternalMedia channel

        This routes audio to/from an external RTP endpoint (AI Agent)

        Args:
            external_host: IP/hostname of AI Agent
            external_port: RTP port of AI Agent
            codec: Audio codec (alaw, ulaw)
            channel_id: Optional custom channel ID

        Returns:
            Channel object or None on error
        """
        try:
            self.logger.info(f"Creating ExternalMedia channel: {external_host}:{external_port} codec={codec}")

            # Build parameters according to Asterisk ARI Swagger docs
            params = {
                'app': self.app_name,
                'external_host': f"{external_host}:{external_port}",
                'format': codec,
                'encapsulation': 'rtp',  # RTP encapsulation
                'transport': 'udp',      # UDP transport
                'direction': 'both'      # Bidirectional audio (send + receive)
            }

            if channel_id:
                params['channelId'] = channel_id

            channel = await self.client.channels.externalMedia(**params)

            self.logger.info(f"✅ ExternalMedia channel created: {channel.id}")
            return channel

        except Exception as e:
            self.logger.error(f"Failed to create ExternalMedia channel: {e}", exc_info=True)
            return None

    async def answer_channel(self, channel) -> bool:
        """
        Answer incoming channel

        Args:
            channel: Channel object (from event)

        Returns:
            True if successful
        """
        try:
            await channel.answer()

            self.logger.info(f"✅ Channel answered: {channel.id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to answer channel {channel.id}: {e}")
            return False

    async def create_bridge(self, bridge_type: str = 'mixing') -> Optional[Bridge]:
        """
        Create a bridge to connect channels

        Args:
            bridge_type: 'mixing' or 'holding'

        Returns:
            Bridge object or None on error
        """
        try:
            bridge = await self.client.bridges.create(type=bridge_type)

            self.logger.info(f"✅ Bridge created: {bridge.id} type={bridge_type}")
            return bridge

        except Exception as e:
            self.logger.error(f"Failed to create bridge: {e}")
            return None

    async def add_channel_to_bridge(self, bridge_id: str, channel_id: str, role: Optional[str] = None) -> bool:
        """
        Add channel to bridge

        Args:
            bridge_id: Bridge unique ID
            channel_id: Channel unique ID
            role: Optional role (e.g., 'announcer' for dummy channels)

        Returns:
            True if successful
        """
        try:
            # Get bridge object (needs await)
            bridge = await self.client.bridges.get(bridgeId=bridge_id)
            # Add channel to bridge (needs await)
            if role:
                await bridge.addChannel(channel=channel_id, role=role)
                self.logger.info(f"✅ Channel {channel_id} added to bridge {bridge_id} as {role}")
            else:
                await bridge.addChannel(channel=channel_id)
                self.logger.info(f"✅ Channel {channel_id} added to bridge {bridge_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to add channel to bridge: {e}", exc_info=True)
            return False

    async def create_announcer_channel(self) -> Optional[Channel]:
        """
        Create a silent Announcer channel to force softmix bridge technology.

        Phase 5.1: Bridge Optimization Fix
        Asterisk automatically uses simple_bridge for 2-channel bridges, which causes
        native RTP bridging and prevents our agent's audio from reaching the client.

        Adding a 3rd channel (Announcer) forces Asterisk to use softmix, which ensures
        all media flows through the bridge correctly.

        Returns:
            Announcer Channel object or None on error
        """
        try:
            # Create Announcer channel (silent, no media sent to it)
            channel = await self.client.channels.originate(
                endpoint='Announcer/dummy',
                app=self.app_name
            )

            self.logger.info(f"✅ Announcer channel created: {channel.id}")
            return channel

        except Exception as e:
            self.logger.error(f"Failed to create Announcer channel: {e}")
            return None

    async def hangup_channel(self, channel) -> bool:
        """
        Hangup channel

        Args:
            channel: Channel object or channel ID string

        Returns:
            True if successful
        """
        try:
            # If string, get channel object
            if isinstance(channel, str):
                channel = await self.client.channels.get(channelId=channel)

            await channel.hang_up()  # Note: it's hang_up() not hangup()

            self.logger.info(f"✅ Channel hung up: {channel.id}")
            return True

        except Exception as e:
            channel_id = channel if isinstance(channel, str) else channel.id
            self.logger.error(f"Failed to hangup channel {channel_id}: {e}")
            return False

    async def destroy_bridge(self, bridge_id: str) -> bool:
        """
        Destroy bridge

        Args:
            bridge_id: Bridge unique ID

        Returns:
            True if successful
        """
        try:
            # Get bridge object (needs await)
            bridge = await self.client.bridges.get(bridgeId=bridge_id)
            # Destroy bridge (needs await)
            await bridge.destroy()

            self.logger.info(f"✅ Bridge destroyed: {bridge_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to destroy bridge {bridge_id}: {e}", exc_info=True)
            return False

    async def stop_playback(self, playback_id: str) -> bool:
        """
        Stop ongoing audio playback (for barge-in support).

        This method stops TTS playback when user interrupts the agent.
        Added in Phase 4 (Barge-in Support).

        Args:
            playback_id: Playback unique ID (from play() operation)

        Returns:
            True if successful, False otherwise

        Reference:
            Asterisk-AI-Voice-Agent/src/ari_client.py:486
        """
        try:
            # Get playback object via asyncari
            playback = await self.client.playbacks.get(playbackId=playback_id)

            # Stop playback
            await playback.stop()

            self.logger.info(f"⏹️  Playback stopped (barge-in): {playback_id}")
            return True

        except Exception as e:
            self.logger.warning(f"Failed to stop playback {playback_id}: {e}")
            return False
