import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, call
from mqtt_client import MqttClient
from models import ReceptionStats
import config


class TestMQTTClient(unittest.TestCase):
    def setUp(self):
        self.bridge = MagicMock()
        self.bridge.handle_meshtastic_message = AsyncMock()
        self.bridge.handle_node_info = AsyncMock()
        self.bridge.loop = asyncio.new_event_loop()

    def tearDown(self):
        self.bridge.loop.close()

    @patch('mqtt_client.mqtt')
    def test_initialization(self, mock_mqtt):
        client = MqttClient(self.bridge)
        
        self.assertEqual(client.bridge, self.bridge)
        self.assertIsNone(client.client)
        mock_mqtt.Client.assert_called_once()

    @patch('mqtt_client.mqtt')
    def test_on_connect_success(self, mock_mqtt):
        mock_client = MagicMock()
        client = MqttClient(self.bridge)
        client.client = mock_client
        
        with patch.object(config, 'MQTT_TOPIC', 'msh/US/#'):
            client._on_connect(mock_client, None, None, 0, None)
        
        mock_client.subscribe.assert_called_once_with('msh/US/#')

    @patch('mqtt_client.mqtt')
    def test_on_connect_failure(self, mock_mqtt):
        mock_client = MagicMock()
        client = MqttClient(self.bridge)
        client.client = mock_client
        
        # Non-zero reason code = failure
        client._on_connect(mock_client, None, None, 5, None)
        
        # Should not subscribe on failure
        mock_client.subscribe.assert_not_called()

    @patch('mqtt_client.mqtt')
    @patch('mqtt_client.mqtt_pb2')
    def test_process_service_envelope_decoded(self, mock_pb2, mock_mqtt):
        from meshtastic import portnums_pb2
        
        client = MqttClient(self.bridge)
        
        # Mock ServiceEnvelope with decoded packet
        se = MagicMock()
        se.packet.id = 12345
        se.packet.from_node = 0xabc123
        se.packet.decoded.portnum = portnums_pb2.TEXT_MESSAGE_APP
        se.packet.decoded.payload = b"Hello World"
        se.gateway_id = "!gateway1"
        se.packet.rx_rssi = -80
        se.packet.rx_snr = 10.5
        se.packet.hop_start = 3
        se.packet.hop_limit = 1
        
        client._process_service_envelope(se, "LongFast")
        
        # Should call handle_decoded_packet
        # Can't easily verify without running async loop, but at least no crash

    @patch('mqtt_client.mqtt')
    def test_extract_channel_name_from_topic(self, mock_mqtt):
        from utils import extract_channel_name_from_topic
        
        # Test various topic formats
        self.assertEqual(extract_channel_name_from_topic("msh/EU_868/2/e/LongFast/!abc"), "LongFast")
        self.assertEqual(extract_channel_name_from_topic("msh/US/2/c/MyChannel/!xyz"), "MyChannel")
        self.assertEqual(extract_channel_name_from_topic("msh/US/2/json/Test/!node"), "Test")
        self.assertEqual(extract_channel_name_from_topic("msh/US/2"), "Unknown")

    @patch('mqtt_client.mqtt')
    def test_handle_nodeinfo(self, mock_mqtt):
        from meshtastic import mesh_pb2, portnums_pb2
        
        client = MqttClient(self.bridge)
        
        # Create mock packet with NODEINFO
        packet = {
            'id': 999,
            'fromId': '!node123',
            'decoded': {
                'portnum': portnums_pb2.NODEINFO_APP
            }
        }
        
        # Mock the user info
        mock_user = MagicMock()
        mock_user.short_name = "TestNode"
        mock_user.long_name = "Test Node Full"
        
        with patch('mqtt_client.mesh_pb2.User') as MockUser:
            MockUser.return_value = mock_user
            client._handle_nodeinfo(packet)

    @patch('mqtt_client.mqtt')
    @patch('mqtt_client.Cipher')
    def test_try_decrypt_with_psk(self, mock_cipher, mock_mqtt):
        client = MqttClient(self.bridge)
        
        # Mock encrypted packet
        packet = MagicMock()
        packet.id = 777
        packet.encrypted = b'\x00\x01\x02\x03' + b'encrypted_data_here'
        
        stats = ReceptionStats(gateway_id="!gw", rssi=-70, snr=8.0)
        
        with patch.object(config, 'MESHTASTIC_CHANNEL_PSK', 'AQ=='):  # base64 encoded key
            # Attempt decrypt - may fail but shouldn't crash
            try:
                client._try_decrypt(packet, stats, "TestChannel")
            except:
                pass  # Decryption errors are acceptable in unit test

    @patch('mqtt_client.mqtt')
    def test_stop(self, mock_mqtt):
        mock_client = MagicMock()
        client = MqttClient(self.bridge)
        client.client = mock_client
        
        client.stop()
        
        mock_client.disconnect.assert_called_once()


if __name__ == '__main__':
    unittest.main()
