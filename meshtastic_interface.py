import asyncio
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

    def start(self):
        logger.info(f"Connecting to Meshtastic Node at {config.MESHTASTIC_HOST}...")
        try:
            self.interface = meshtastic.tcp_interface.TCPInterface(
                hostname=config.MESHTASTIC_HOST,
                retryOutage=True
            )
            
            # Subscribe to message events
            pub.subscribe(self._on_meshtastic_message, "meshtastic.receive")
            
        except Exception as e:
            logger.error(f"Failed to connect to Meshtastic LAN node: {e}")

    def stop(self):
        if self.interface:
            self.interface.close()

    def send_tapback(self, target_packet_id: int, emoji: str, channel_idx: int = 0):
        """
        Sends a tapback (reaction) to the mesh.
        Since the Python API doesn't have a direct 'sendTapback' yet, we send a text message.
        """
        text = f"[Reaction to {target_packet_id}]: {emoji}"
        self.send_text(text, channel_idx)

    def send_text(self, text: str, channel_idx: int = 0):
        if self.interface:
            self.interface.sendText(text, channelIndex=channel_idx)
        else:
            logger.error("Cannot send text: Interface not connected")

    def _on_meshtastic_message(self, packet, interface):
        try:
            # packet is a dict
            logger.debug(f"LAN Message received: {packet}")
            
            # Extract basic info
            packet_id = packet.get("id")
            from_id = packet.get("fromId")
            
            decoded = packet.get("decoded", {})
            portnum = decoded.get("portnum")
            
            if portnum == portnums_pb2.TEXT_MESSAGE_APP:
                # Create Mock Stats for LAN
                # For LAN, RSSI/SNR might be in 'rxRSSI'/'rxSNR'
                rssi = packet.get("rxRSSI", 0)
                snr = packet.get("rxSNR", 0)
                
                stats = ReceptionStats(
                    gateway_id="LAN_Node", # Indicator for local node
                    rssi=rssi,
                    snr=snr
                )
                
                asyncio.run_coroutine_threadsafe(
                    self.bridge.handle_meshtastic_message(packet, "lan", stats),
                    asyncio.get_event_loop()
                )
                
        except Exception as e:
            logger.error(f"Error processing LAN message: {e}", exc_info=True)
