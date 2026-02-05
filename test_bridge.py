import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock
from bridge import MeshtasticMatrixBridge
from models import ReceptionStats

class TestBridge(unittest.TestCase):
    def setUp(self):
        self.bridge = MeshtasticMatrixBridge()
        self.bridge.matrix_bot = AsyncMock()
        self.bridge.mqtt_client = MagicMock()
        self.bridge.meshtastic_interface = MagicMock()

    def test_new_message_flow(self):
        async def run():
            stats = ReceptionStats(gateway_id="GatewayA", rssi=-80, snr=10.0)
            packet = {"id": 123, "fromId": "!Sender", "decoded": {"text": "Hello"}}
            
            # Mock Matrix send return
            self.bridge.matrix_bot.send_message.return_value = "event_id_1"
            
            await self.bridge.handle_meshtastic_message(packet, "mqtt", stats)
            
            # Verify sent to Matrix
            self.bridge.matrix_bot.send_message.assert_called_once()
            args = self.bridge.matrix_bot.send_message.call_args[0][0]
            self.assertIn("[!Sender]: Hello", args)
            self.assertIn("GatewayA", args)
            
            # Verify state stored
            self.assertIn(123, self.bridge.message_state)
            self.assertEqual(self.bridge.message_state[123].matrix_event_id, "event_id_1")

        asyncio.run(run())

    def test_deduplication_aggregation(self):
        async def run():
            # Initial message
            stats1 = ReceptionStats(gateway_id="GatewayA", rssi=-80, snr=10.0)
            packet = {"id": 123, "fromId": "!Sender", "decoded": {"text": "Hello"}}
            self.bridge.matrix_bot.send_message.return_value = "event_id_1"
            await self.bridge.handle_meshtastic_message(packet, "mqtt", stats1)
            
            # Duplicate from GatewayB
            stats2 = ReceptionStats(gateway_id="GatewayB", rssi=-90, snr=5.0)
            await self.bridge.handle_meshtastic_message(packet, "mqtt", stats2)
            
            # Verify edit called
            self.bridge.matrix_bot.edit_message.assert_called_once()
            event_id, new_content = self.bridge.matrix_bot.edit_message.call_args[0]
            self.assertEqual(event_id, "event_id_1")
            self.assertIn("GatewayA", new_content)
            self.assertIn("GatewayB", new_content)
            
            # Duplicate from GatewayA again (should ignore)
            self.bridge.matrix_bot.reset_mock()
            await self.bridge.handle_meshtastic_message(packet, "mqtt", stats1)
            self.bridge.matrix_bot.edit_message.assert_not_called()

        asyncio.run(run())

    def test_matrix_message_splitting(self):
        async def run():
            event = MagicMock()
            event.sender = "@user:matrix.org"
            event.body = "A" * 300 # 300 chars
            
            await self.bridge.handle_matrix_message(event)
            
            # Verify split
            # "[@user:matrix.org]: AAAA..." is > 200 bytes
            # Should call send_text multiple times
            self.assertTrue(self.bridge.meshtastic_interface.send_text.call_count >= 2)
            
            calls = self.bridge.meshtastic_interface.send_text.call_args_list
            first_msg = calls[0][0][0]
            self.assertTrue(first_msg.startswith("(1/"))

        asyncio.run(run())

    def test_reaction_forwarding(self):
        async def run():
            # Setup state
            stats = ReceptionStats(gateway_id="A", rssi=0, snr=0)
            packet = {"id": 999, "fromId": "!Sender", "decoded": {"text": "Hi"}}
            self.bridge.matrix_bot.send_message.return_value = "event_id_999"
            await self.bridge.handle_meshtastic_message(packet, "mqtt", stats)
            
            # Mock Reaction Event
            event = MagicMock()
            # structure for bridge.py: event.content.get("m.relates_to")...
            event.content = {
                "m.relates_to": {
                    "event_id": "event_id_999",
                    "key": "👍"
                }
            }
            
            # Mock send_tapback method (since we added it to MeshtasticInterface class)
            self.bridge.meshtastic_interface.send_tapback = MagicMock()
            
            await self.bridge.handle_matrix_reaction(event)
            
            self.bridge.meshtastic_interface.send_tapback.assert_called_with(999, "👍")

        asyncio.run(run())

if __name__ == '__main__':
    unittest.main()
