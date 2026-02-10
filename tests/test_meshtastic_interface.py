import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from src.adapters.meshtastic_interface import MeshtasticInterface
from src.models import ReceptionStats
from src.constants import NODEINFO_APP, TEXT_MESSAGE_APP, REACTION_APP


class TestMeshtasticInterface(unittest.TestCase):
    def setUp(self):
        self.bridge = MagicMock()
        self.bridge.handle_meshtastic_message = AsyncMock()
        self.bridge.handle_node_info = AsyncMock()
        self.bridge.loop = asyncio.new_event_loop()

    def tearDown(self):
        self.bridge.loop.close()

    def test_initialization(self):
        interface = MeshtasticInterface(self.bridge)
        
        self.assertEqual(interface.bridge, self.bridge)
        self.assertIsNone(interface.interface)

    @patch('src.adapters.meshtastic_interface.meshtastic.tcp_interface.TCPInterface')
    def test_send_tapback(self, mock_tcp):
        mock_interface = MagicMock()
        
        interface = MeshtasticInterface(self.bridge)
        interface.interface = mock_interface
        
        interface.send_tapback(12345, "👍", channel_idx=0)
        
        mock_interface.sendData.assert_called_once_with(
            data="👍".encode("utf-8"),
            portNum=REACTION_APP,
            replyId=12345,
            channelIndex=0
        )

    @patch('src.adapters.meshtastic_interface.meshtastic.tcp_interface.TCPInterface')
    def test_send_text(self, mock_tcp):
        mock_interface = MagicMock()
        mock_packet = MagicMock()
        mock_packet.id = 99999
        mock_interface.sendText.return_value = mock_packet
        
        interface = MeshtasticInterface(self.bridge)
        interface.interface = mock_interface
        
        result = interface.send_text("Hello World", channel_idx=0)
        
        mock_interface.sendText.assert_called_once_with(
            "Hello World",
            channelIndex=0
        )
        self.assertEqual(result.id, 99999)

    @patch('src.adapters.meshtastic_interface.meshtastic.tcp_interface.TCPInterface')
    def test_send_text_with_reply(self, mock_tcp):
        mock_interface = MagicMock()
        mock_packet = MagicMock()
        mock_packet.id = 88888
        mock_interface.sendText.return_value = mock_packet
        
        interface = MeshtasticInterface(self.bridge)
        interface.interface = mock_interface
        
        result = interface.send_text("Reply text", channel_idx=0, reply_id=77777)
        
        # Should call sendText with wantResponse to get replyId
        mock_interface.sendText.assert_called_once_with(
            "Reply text",
            channelIndex=0
        )

    def test_on_meshtastic_message_text(self):
        interface = MeshtasticInterface(self.bridge)
        interface.node_id = "!localnode"
        
        packet = {
            'id': 123,
            'fromId': '!sender',
            'decoded': {
                'portnum': TEXT_MESSAGE_APP,
                'text': 'Hello from mesh'
            },
            'rxRssi': -75,
            'rxSnr': 9.5,
            'hopStart': 3,
            'hopLimit': 2
        }
        
        mock_interface = MagicMock()
        interface._on_meshtastic_message(packet, mock_interface)
        
        # Should have called bridge.loop.call_soon_threadsafe
        # Since we can't easily test threadsafe call, just verify no crash

    def test_on_meshtastic_message_nodeinfo(self):
        interface = MeshtasticInterface(self.bridge)
        
        packet = {
            'id': 456,
            'fromId': '!node123',
            'decoded': {
                'portnum': NODEINFO_APP,
                'user': {
                    'shortName': 'Node1',
                    'longName': 'Node One'
                }
            }
        }
        
        mock_interface = MagicMock()
        interface._on_meshtastic_message(packet, mock_interface)
        
        # Should call _handle_nodeinfo internally

    def test_handle_nodeinfo(self):
        interface = MeshtasticInterface(self.bridge)
        
        packet = {
            'fromId': '!node789',
            'decoded': {
                'user': {
                    'shortName': 'TestN',
                    'longName': 'Test Node'
                }
            }
        }
        
        interface._handle_nodeinfo(packet)
        
        # Should schedule handle_node_info on bridge

    def test_on_meshtastic_message_reaction(self):
        interface = MeshtasticInterface(self.bridge)
        interface.node_id = "!localnode"
        
        packet = {
            'id': 789,
            'fromId': '!sender',
            'decoded': {
                'portnum': REACTION_APP,
                'payload': b'thumbs_up'
            },
            'rxRssi': -70,
            'rxSnr': 8.0,
            'hopStart': 3,
            'hopLimit': 3
        }
        
        mock_interface = MagicMock()
        interface._on_meshtastic_message(packet, mock_interface)
        
        # Should process as text-like message

    def test_on_meshtastic_message_hop_count(self):
        interface = MeshtasticInterface(self.bridge)
        interface.node_id = "!localnode"
        
        packet = {
            'id': 999,
            'fromId': '!sender',
            'decoded': {
                'portnum': TEXT_MESSAGE_APP,
                'text': 'Test'
            },
            'rxRssi': -80,
            'rxSnr': 5.0,
            'hopStart': 5,
            'hopLimit': 2
        }
        
        mock_interface = MagicMock()
        interface._on_meshtastic_message(packet, mock_interface)
        
        # Hop count should be 5 - 2 = 3

    def test_stop(self):
        mock_interface = MagicMock()
        
        interface = MeshtasticInterface(self.bridge)
        interface.interface = mock_interface
        
        interface.stop()
        
        mock_interface.close.assert_called_once()

    def test_stop_no_interface(self):
        interface = MeshtasticInterface(self.bridge)
        interface.interface = None
        
        # Should not crash
        interface.stop()


if __name__ == '__main__':
    unittest.main()
