import asyncio
import logging
import base64
import paho.mqtt.client as mqtt
from meshtastic import mesh_pb2, portnums_pb2
from meshtastic.protobuf import mqtt_pb2
from google.protobuf.message import DecodeError
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import config
from models import ReceptionStats

logger = logging.getLogger(__name__)

class MqttClient:
    def __init__(self, bridge):
        self.bridge = bridge
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        
        if config.MQTT_USER and config.MQTT_PASSWORD:
            self.client.username_pw_set(config.MQTT_USER, config.MQTT_PASSWORD)
            
        if config.MQTT_USE_TLS:
            self.client.tls_set()
            
        self._connect_task = None

    def start(self):
        self._connect_task = asyncio.create_task(self._connect_loop())

    async def _connect_loop(self):
        while True:
            try:
                logger.info(f"Connecting to MQTT Broker {config.MQTT_BROKER}...")
                await asyncio.to_thread(self.client.connect, config.MQTT_BROKER, config.MQTT_PORT, 60)
                self.client.loop_start()
                logger.info("MQTT Client loop started.")
                return
            except Exception as e:
                logger.error(f"Failed to connect to MQTT: {e}. Retrying in 5 seconds...")
                await asyncio.sleep(5)

    def stop(self):
        if self._connect_task:
            self._connect_task.cancel()
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT Broker!")
            # Convert msh/EU_868/2/e/ to msh/EU_868/2/# to get all messages (json and proto)
            # Actually, standard is msh/REGION/CHANNEL/#
            # If user provided a specific topic ending in /e/, let's verify.
            # Usually topics are msh/Region/MainChannelID/v1/mqtt_id
            topic = config.MQTT_TOPIC
            if not topic.endswith("#"):
                if topic.endswith("/"):
                    topic += "#"
                else:
                    topic += "/#"
            
            logger.info(f"Subscribing to {topic}")
            client.subscribe(topic)
        else:
            logger.error(f"Failed to connect to MQTT, return code {rc}")

    def _on_message(self, client, userdata, msg):
        try:
            # We expect ServiceEnvelope protobufs (binary) or JSON (text)
            # Meshtastic usually sends protobufs on .../c/ or .../e/ ? 
            # Modern firmware uses protobufs wrapped in ServiceEnvelope.
            
            # Simple check: is it json?
            # if msg.topic.endswith("/json"): ...
            
            # Try parsing as ServiceEnvelope
            se = mqtt_pb2.ServiceEnvelope()
            try:
                se.ParseFromString(msg.payload)
            except DecodeError:
                # Might be raw Packet or JSON. Ignoring for now if not ServiceEnvelope
                return

            self._process_service_envelope(se)

        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}", exc_info=True)

    def _process_service_envelope(self, se):
        packet = se.packet
        if not packet.id:
            return

        # Gateway Stats
        gateway_id = getattr(se, "gateway_id", "Unknown")
        rssi = 0
        snr = 0.0
        
        # Extract RSSI/SNR from the packet rx_rssi / rx_snr if available (from the reporting node's perspective)
        # Or from the ServiceEnvelope itself if it reports reception stats of the bridge?
        # Usually 'packet' contains 'rx_rssi' indicating how the gateway heard the node.
        if hasattr(packet, "rx_rssi"):
            rssi = packet.rx_rssi
        if hasattr(packet, "rx_snr"):
            snr = packet.rx_snr

        # Create ReceptionStats
        stats = ReceptionStats(gateway_id=gateway_id, rssi=rssi, snr=snr)

        # Payload Decoding
        # Packet might be encrypted. config.MESHTASTIC_CHANNEL_PSK might be needed.
        # For now, let's assume valid plaintext or handle basic text.
        
        if packet.decoded.data.payload:
            # Already decoded
            self._handle_decoded_packet(packet, stats)
        elif packet.encrypted and config.MESHTASTIC_CHANNEL_PSK:
            # Manual Decryption
            self._try_decrypt(packet, stats)
        
        # If the packet has 'decoded' field populated (protobuf), use it.
        if packet.HasField("decoded") and packet.decoded.portnum != portnums_pb2.UNKNOWN_APP:
             self._handle_decoded_packet(packet, stats)

    def _handle_decoded_packet(self, packet, stats):
        decoded = packet.decoded
        if decoded.portnum == portnums_pb2.TEXT_MESSAGE_APP:
            text = decoded.payload.decode("utf-8")
            
            # Construct a dict similar to what we expect in bridge
            packet_dict = {
                "id": packet.id,
                "fromId": self._node_id_to_str(packet.from_id),
                "decoded": {
                    "text": text
                }
            }
            
            # Bridge handling (async call from sync callback requires run_coroutine_threadsafe)
            asyncio.run_coroutine_threadsafe(
                self.bridge.handle_meshtastic_message(packet_dict, "mqtt", stats),
                asyncio.get_event_loop()
            )

    def _node_id_to_str(self, node_id):
        # Convert integer node_id to !Hex string
        return "!" + hex(node_id)[2:]

    def _try_decrypt(self, packet, stats):
        try:
            key_b64 = config.MESHTASTIC_CHANNEL_PSK
            if not key_b64:
                return

            # Key is base64 encoded
            try:
                key = base64.b64decode(key_b64)
            except Exception:
                logger.error("Invalid base64 key in MESHTASTIC_CHANNEL_PSK")
                return
            
            # Nonce Construction (Meshtastic 1.2+ usually)
            # Packet ID (4 bytes) + From Node (4 bytes) + 8 bytes padding ??
            # Official docs say: 12 bytes nonce (PacketID + SenderNodeID + extra?)
            # Actually, let's verify standard: PacketID (LE 4B) + FromNodeID (LE 4B) + 8 bytes Counter=0
            # Wait, AES-CTR requires a 16-byte block as IV.
            # Common Meshtastic usage:
            # Nonce = packetId (4 bytes) + fromNodeId (4 bytes) + 8 bytes zero
            
            packet_id_bytes = packet.id.to_bytes(4, byteorder='little')
            from_id_bytes = packet.from_id.to_bytes(4, byteorder='little')
            
            # Construct 16-byte IV for CTR mode (Nonce + Counter)
            # Meshtastic use:
            # bytes 0-3: Packet ID
            # bytes 4-7: From Node ID
            # bytes 8-15: 0 (This serves as the extra nonce space or initial counter block?)
            # Actually CTR mode in cryptography splits this. 
            # We pass full 16 bytes as 'nonce' argument to modes.CTR()
            
            nonce_iv = packet_id_bytes + from_id_bytes + (b'\x00' * 8)
            
            cipher = Cipher(algorithms.AES(key), modes.CTR(nonce_iv), backend=default_backend())
            decryptor = cipher.decryptor()
            decrypted_data = decryptor.update(packet.encrypted) + decryptor.finalize()
            
            # Parse decrypted data as 'Data' protobuf
            data_pb = mesh_pb2.Data()
            data_pb.ParseFromString(decrypted_data)
            
            # Populate packet.decoded
            packet.decoded.CopyFrom(data_pb)
            
            logger.info(f"Successfully decrypted packet {packet.id}")
            self._handle_decoded_packet(packet, stats)

        except Exception as e:
            logger.error(f"Failed to decrypt packet {packet.id}: {e}")

    def _node_id_to_str(self, node_id):
        # Convert integer node_id to !Hex string
        return "!" + hex(node_id)[2:]
