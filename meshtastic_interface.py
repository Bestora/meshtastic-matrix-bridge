import asyncio
from typing import Optional
import logging
import meshtastic.tcp_interface
from meshtastic import portnums_pb2
import config
from models import ReceptionStats
from pubsub import pub

logger = logging.getLogger(__name__)

class MeshtasticInterface:
    def __init__(self, bridge):
        self.bridge = bridge
        self.interface = None
        self._connect_task = None
        self._disconnect_future = None
        self.node_id = "LAN_Node"

    def start(self):
        self._connect_task = asyncio.create_task(self._connect_loop())

    async def _connect_loop(self):
        while True:
            try:
                if self.interface:
                    try:
                        self.interface.close()
                    except:
                        pass
                    self.interface = None

                logger.info(f"Connecting to Meshtastic Node at {config.MESHTASTIC_HOST}:{config.MESHTASTIC_PORT}...")
                
                # TCPInterface starts its own threads for reading and heartbeats
                self.interface = await asyncio.to_thread(
                    meshtastic.tcp_interface.TCPInterface,
                    hostname=config.MESHTASTIC_HOST,
                    portNumber=config.MESHTASTIC_PORT
                )
                
                # Subscribe to events
                pub.subscribe(self._on_meshtastic_message, "meshtastic.receive")
                pub.subscribe(self._on_connection_lost, "meshtastic.connection.lost")
                
                # Get Local Node ID
                try:
                    my_node = self.interface.myNodeInfo.myNode
                    self.node_id = "!" + hex(my_node.id)[2:]
                    logger.info(f"Connected to Meshtastic Node! Local ID: {self.node_id}")
                except Exception as e:
                    logger.warning(f"Could not get local node ID: {e}")
                    self.node_id = "LAN_Node"

                # Create a future to wait for disconnect
                self._disconnect_future = asyncio.get_running_loop().create_future()
                
                # Wait for either the disconnect future or the task being cancelled
                await self._disconnect_future
                logger.warning("Meshtastic connection lost detected.")

            except Exception as e:
                logger.error(f"Meshtastic LAN connection error: {e}")
            
            # Clean up and wait before retrying
            logger.info("Retrying Meshtastic connection in 5 seconds...")
            self._cleanup_interface()
            await asyncio.sleep(5)

    def _cleanup_interface(self):
        """Safely close and clean up the current interface."""
        pub.unsubscribe(self._on_meshtastic_message, "meshtastic.receive")
        pub.unsubscribe(self._on_connection_lost, "meshtastic.connection.lost")
        
        if self.interface:
            try:
                self.interface.close()
            except Exception as e:
                logger.debug(f"Error closing interface: {e}")
            self.interface = None
        
        if self._disconnect_future and not self._disconnect_future.done():
            self._disconnect_future.set_result(None)

    def _on_connection_lost(self, interface):
        """Callback from meshtastic library when connection is lost."""
        if interface == self.interface:
            logger.warning("Meshtastic library reported connection lost")
            if self._disconnect_future and not self._disconnect_future.done():
                self._disconnect_future.get_loop().call_soon_threadsafe(
                    lambda: not self._disconnect_future.done() and self._disconnect_future.set_result(True)
                )

    def stop(self):
        if self._connect_task:
            self._connect_task.cancel()
        self._cleanup_interface()

    def send_tapback(self, target_packet_id: int, emoji: str, channel_idx: int = 0):
        """
        Sends a tapback (reaction) to the mesh.
        Uses REACTION_APP (68) so clients render it properly.
        """
        if not self.interface:
            logger.error("Cannot send tapback: Interface not connected")
            return

        try:
            self.interface.sendData(
                data=emoji.encode("utf-8"),
                portNum=68,
                replyId=target_packet_id,
                channelIndex=channel_idx
            )
            logger.info(f"Sent tapback '{emoji}' to {target_packet_id}")
        except Exception as e:
            logger.error(f"Failed to send tapback: {e}")
            # If we hit a broken pipe or similar, trigger a reconnect
            if isinstance(e, BrokenPipeError) or "Broken pipe" in str(e):
                self._on_connection_lost(self.interface)

    def send_text(self, text: str, channel_idx: int = 0, reply_id: Optional[int] = None):
        if not self.interface:
            logger.error("Cannot send text: Interface not connected")
            return None
            
        try:
            return self.interface.sendText(text, channelIndex=channel_idx, replyId=reply_id)
        except Exception as e:
            logger.error(f"Failed to send text: {e}")
            if isinstance(e, BrokenPipeError) or "Broken pipe" in str(e):
                self._on_connection_lost(self.interface)
            return None

    def _on_meshtastic_message(self, packet, interface):
        if interface != self.interface:
            return

        try:
            # packet is a dict
            logger.debug(f"LAN Message received: {packet}")
            
            # Extract basic info
            packet_id = packet.get("id")
            from_id = packet.get("fromId")
            
            decoded = packet.get("decoded", {})
            portnum = decoded.get("portnum")
            
            # Handle NODEINFO packets
            if portnum == portnums_pb2.NODEINFO_APP:
                self._handle_nodeinfo(packet)
                return
            
            # Check for supported apps
            # TEXT_MESSAGE_APP = 1
            # REACTION_APP = 68
            is_text_like = portnum == portnums_pb2.TEXT_MESSAGE_APP or portnum == 68
            
            if is_text_like:
                # Create Mock Stats for LAN
                rssi = packet.get("rxRssi", 0)
                snr = packet.get("rxSnr", 0.0)
                
                # Extract hop count
                hop_count = 0
                if "hopStart" in packet and "hopLimit" in packet:
                    hop_count = packet["hopStart"] - packet["hopLimit"]
                
                stats = ReceptionStats(
                    gateway_id=self.node_id,
                    rssi=rssi,
                    snr=snr,
                    hop_count=hop_count
                )
                
                # Extract channel name from interface settings
                channel_idx = packet.get("channel", 0)
                channel_name = "Unknown"
                if self.interface and self.interface.channels:
                    for c in self.interface.channels:
                        if c.index == channel_idx:
                            channel_name = c.settings.name if hasattr(c.settings, 'name') else "Unknown"
                            break
                
                packet["channel_name"] = channel_name

                asyncio.run_coroutine_threadsafe(
                    self.bridge.handle_meshtastic_message(packet, "lan", stats),
                    asyncio.get_event_loop()
                )
                
        except Exception as e:
            logger.error(f"Error processing LAN message: {e}", exc_info=True)
    
    def _handle_nodeinfo(self, packet):
        """Handle NODEINFO packets from LAN to update the node database."""
        try:
            from_id = packet.get("fromId")
            decoded = packet.get("decoded", {})
            user_info = decoded.get("user", {})
            
            short_name = user_info.get("shortName")
            long_name = user_info.get("longName")
            
            if from_id:
                asyncio.run_coroutine_threadsafe(
                    self.bridge.handle_node_info(from_id, short_name, long_name),
                    asyncio.get_event_loop()
                )
        except Exception as e:
            logger.error(f"Error processing NODEINFO: {e}", exc_info=True)

