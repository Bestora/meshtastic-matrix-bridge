import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from bridge import MeshtasticMatrixBridge
from models import ReceptionStats

class TestBridge(unittest.TestCase):
    def setUp(self):
        # Patch NodeDatabase to prevent DB operations
        self.node_db_patcher = patch('bridge.NodeDatabase')
        self.mock_node_db_cls = self.node_db_patcher.start()
        self.mock_node_db = self.mock_node_db_cls.return_value
        self.mock_node_db.get_node_name.side_effect = lambda x: x 
        self.mock_node_db.load_message_states.return_value = {}

        self.bridge = MeshtasticMatrixBridge()
        self.bridge.matrix_bot = AsyncMock()
        self.bridge.mqtt_client = MagicMock()
        self.bridge.meshtastic_interface = MagicMock()
        
    def tearDown(self):
        self.node_db_patcher.stop()

    def test_new_message_flow(self):
        async def run():
            stats = ReceptionStats(gateway_id="GatewayA", rssi=-80, snr=10.0)
            packet = {"id": 123, "fromId": "!Sender", "decoded": {"text": "Hello"}}
            
            # Mock Matrix send return
            self.bridge.matrix_bot.send_message.return_value = "event_id_1"
            
            await self.bridge.handle_meshtastic_message(packet, "mqtt", stats)
            
            # Verify sent to Matrix
            self.bridge.matrix_bot.send_message.assert_called_once()
            args = self.bridge.matrix_bot.send_message.call_args[0]
            self.assertIn("[!Sender]: Hello", args[0])
            self.assertIn("GatewayA", args[0])
            
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
            event_id, new_content, _ = self.bridge.matrix_bot.edit_message.call_args[0]
            self.assertEqual(event_id, "event_id_1")
            self.assertIn("GatewayA", new_content)
            self.assertIn("GatewayB", new_content)
            
            # Duplicate from GatewayA again (should ignore)
            self.bridge.matrix_bot.reset_mock()
            await self.bridge.handle_meshtastic_message(packet, "mqtt", stats1)
            self.bridge.matrix_bot.edit_message.assert_not_called()

        asyncio.run(run())

    def test_reply_handling(self):
        async def run():
            # Initial message
            stats = ReceptionStats(gateway_id="GatewayA", rssi=-80, snr=10.0)
            packet_orig = {"id": 100, "fromId": "!Sender", "decoded": {"text": "Original"}}
            self.bridge.matrix_bot.send_message.return_value = "event_100"
            await self.bridge.handle_meshtastic_message(packet_orig, "mqtt", stats)
            
            # Text Reply (Should send NEW message)
            packet_reply = {"id": 101, "fromId": "!Sender", "decoded": {"text": "This is a reply", "replyId": 100}}
            self.bridge.matrix_bot.send_message.return_value = "event_101"
            self.bridge.matrix_bot.reset_mock()
            await self.bridge.handle_meshtastic_message(packet_reply, "mqtt", stats)
            
            # Verify send_message called with reply_to
            self.bridge.matrix_bot.send_message.assert_called_once()
            call_args = self.bridge.matrix_bot.send_message.call_args
            args = call_args[0]
            kwargs = call_args[1]
            # args: (text, html)
            self.assertIn("This is a reply", args[0])
            self.assertEqual(kwargs['reply_to'], "event_100")

            # Emoji Reply (Should EDIT original)
            packet_emoji = {"id": 102, "fromId": "!Sender", "decoded": {"text": "❤️", "replyId": 100}}
            self.bridge.matrix_bot.edit_message.reset_mock()
            self.bridge.matrix_bot.send_message.reset_mock()
            
            await self.bridge.handle_meshtastic_message(packet_emoji, "mqtt", stats)
            
            # Verify edit_message called on original event
            self.bridge.matrix_bot.edit_message.assert_called_once()
            args = self.bridge.matrix_bot.edit_message.call_args[0]
            # args: (event_id, text, html)
            self.assertEqual(args[0], "event_100")
            self.assertIn("❤️", args[1]) # Check text contains emoji
            self.bridge.matrix_bot.send_message.assert_not_called()

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
            
            self.bridge.meshtastic_interface.send_tapback.assert_called_with(999, "👍", channel_idx=0)

        asyncio.run(run())

    def test_matrix_originated_compact_mode(self):
        async def run():
            # 1. User sends message
            event = MagicMock()
            event.sender = "@user:matrix.org"
            event.body = "Matrix Message"
            event.event_id = "user_event_id_555"
            
            # Mock send_text returning a packet
            mock_packet = MagicMock()
            mock_packet.id = 555
            self.bridge.meshtastic_interface.send_text.return_value = mock_packet
            
            await self.bridge.handle_matrix_message(event)
            
            # Verify state initialized
            self.assertIn(555, self.bridge.message_state)
            state = self.bridge.message_state[555]
            self.assertTrue(state.render_only_stats)
            self.assertEqual(state.related_event_id, "user_event_id_555")
            self.assertIsNone(state.matrix_event_id)
            
            # 2. Echo received (e.g. from MQTT report)
            stats = ReceptionStats(gateway_id="GatewayX", rssi=-50, snr=5.0)
            packet_echo = {"id": 555, "fromId": "!SomeNode", "decoded": {"text": "Matrix Message"}}
            
            # Mock sending the stats message (should happen now)
            self.bridge.matrix_bot.send_message.return_value = "stats_event_id"
            
            await self.bridge.handle_meshtastic_message(packet_echo, "mqtt", stats)
            
            # Verify send_message was called with stats ONLY (and NO reply_to)
            self.bridge.matrix_bot.send_message.assert_called_once()
            call_args = self.bridge.matrix_bot.send_message.call_args
            content = call_args[0][0]
            kwargs = call_args[1]
            
            self.assertIn("GatewayX", content)
            self.assertNotIn("Matrix Message", content) # Should not repeat text
            self.assertIsNone(kwargs.get('reply_to')) # User requested no reply linkage
            
            # Verify state updated
            self.assertEqual(self.bridge.message_state[555].matrix_event_id, "stats_event_id")

        asyncio.run(run())

if __name__ == '__main__':
    unittest.main()
