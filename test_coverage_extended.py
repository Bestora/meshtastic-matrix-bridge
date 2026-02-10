import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from bridge import MeshtasticMatrixBridge
from models import ReceptionStats
import config


class TestChannelFiltering(unittest.TestCase):
    def setUp(self):
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

    def test_allowed_channel_by_index(self):
        async def run():
            with patch.object(config, 'MESHTASTIC_CHANNELS', ['0']):
                stats = ReceptionStats(gateway_id="GW", rssi=-80, snr=10.0)
                packet = {"id": 1, "fromId": "!node", "channel": 0, "channel_name": "LongFast", "decoded": {"text": "Hello"}}
                self.bridge.matrix_bot.send_message.return_value = "evt1"
                
                await self.bridge.handle_meshtastic_message(packet, "mqtt", stats)
                
                self.bridge.matrix_bot.send_message.assert_called_once()

        asyncio.run(run())

    def test_allowed_channel_by_name(self):
        async def run():
            with patch.object(config, 'MESHTASTIC_CHANNELS', ['LongFast']):
                stats = ReceptionStats(gateway_id="GW", rssi=-80, snr=10.0)
                packet = {"id": 2, "fromId": "!node", "channel": 0, "channel_name": "LongFast", "decoded": {"text": "Hello"}}
                self.bridge.matrix_bot.send_message.return_value = "evt2"
                
                await self.bridge.handle_meshtastic_message(packet, "mqtt", stats)
                
                self.bridge.matrix_bot.send_message.assert_called_once()

        asyncio.run(run())

    def test_disallowed_channel_ignored(self):
        async def run():
            with patch.object(config, 'MESHTASTIC_CHANNELS', ['LongFast']):
                stats = ReceptionStats(gateway_id="GW", rssi=-80, snr=10.0)
                packet = {"id": 3, "fromId": "!node", "channel": 1, "channel_name": "MediumSlow", "decoded": {"text": "Hello"}}
                
                await self.bridge.handle_meshtastic_message(packet, "mqtt", stats)
                
                self.bridge.matrix_bot.send_message.assert_not_called()

        asyncio.run(run())


class TestReplyIdDetection(unittest.TestCase):
    def setUp(self):
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

    def test_standard_reply_id_field(self):
        async def run():
            # Setup original message
            stats = ReceptionStats(gateway_id="GW", rssi=-80, snr=10.0)
            orig = {"id": 100, "fromId": "!node", "decoded": {"text": "Original"}}
            self.bridge.matrix_bot.send_message.return_value = "evt100"
            await self.bridge.handle_meshtastic_message(orig, "mqtt", stats)
            
            # Reply with replyId
            reply = {"id": 101, "fromId": "!node", "decoded": {"text": "Reply", "replyId": 100}}
            self.bridge.matrix_bot.send_message.return_value = "evt101"
            self.bridge.matrix_bot.reset_mock()
            
            await self.bridge.handle_meshtastic_message(reply, "mqtt", stats)
            
            # Should send as reply
            call_args = self.bridge.matrix_bot.send_message.call_args
            self.assertEqual(call_args[1]['reply_to'], "evt100")

        asyncio.run(run())

    def test_deep_linkage_search(self):
        async def run():
            # Setup original message
            stats = ReceptionStats(gateway_id="GW", rssi=-80, snr=10.0)
            orig = {"id": 200, "fromId": "!node", "decoded": {"text": "Original"}}
            self.bridge.matrix_bot.send_message.return_value = "evt200"
            await self.bridge.handle_meshtastic_message(orig, "mqtt", stats)
            
            # Reply with odd field name
            reply = {"id": 201, "fromId": "!node", "decoded": {"text": "Reply", "someWeirdField": 200}}
            self.bridge.matrix_bot.send_message.return_value = "evt201"
            self.bridge.matrix_bot.reset_mock()
            
            await self.bridge.handle_meshtastic_message(reply, "mqtt", stats)
            
            # Should detect as reply via deep search
            call_args = self.bridge.matrix_bot.send_message.call_args
            self.assertEqual(call_args[1]['reply_to'], "evt200")

        asyncio.run(run())

    def test_legacy_reaction_format(self):
        async def run():
            # Setup original message
            stats = ReceptionStats(gateway_id="GW", rssi=-80, snr=10.0)
            orig = {"id": 300, "fromId": "!node", "decoded": {"text": "Original"}}
            self.bridge.matrix_bot.send_message.return_value = "evt300"
            await self.bridge.handle_meshtastic_message(orig, "mqtt", stats)
            
            # Legacy reaction format - the text is short enough to trigger emoji heuristic
            # even without explicit replyId, so it should still work
            reaction = {"id": 301, "fromId": "!othernode", "decoded": {"text": "👍"}, "replyId": 300}
            self.bridge.matrix_bot.edit_message.reset_mock()
            
            await self.bridge.handle_meshtastic_message(reaction, "mqtt", stats)
            
            # Should edit original message
            self.bridge.matrix_bot.edit_message.assert_called_once()
            args = self.bridge.matrix_bot.edit_message.call_args[0]
            self.assertEqual(args[0], "evt300")

        asyncio.run(run())

    def test_heuristic_fallback_to_last_packet(self):
        async def run():
            # Setup original message
            stats = ReceptionStats(gateway_id="GW", rssi=-80, snr=10.0)
            orig = {"id": 400, "fromId": "!node", "decoded": {"text": "Original"}}
            self.bridge.matrix_bot.send_message.return_value = "evt400"
            await self.bridge.handle_meshtastic_message(orig, "mqtt", stats)
            
            # Orphan emoji (no reply field)
            emoji = {"id": 401, "fromId": "!node", "decoded": {"text": "❤️"}}
            self.bridge.matrix_bot.edit_message.reset_mock()
            
            await self.bridge.handle_meshtastic_message(emoji, "mqtt", stats)
            
            # Should attach to last packet via heuristic
            self.bridge.matrix_bot.edit_message.assert_called_once()
            args = self.bridge.matrix_bot.edit_message.call_args[0]
            self.assertEqual(args[0], "evt400")

        asyncio.run(run())


class TestTextExtraction(unittest.TestCase):
    def setUp(self):
        self.node_db_patcher = patch('bridge.NodeDatabase')
        self.mock_node_db_cls = self.node_db_patcher.start()
        self.mock_node_db = self.mock_node_db_cls.return_value
        self.mock_node_db.get_node_name.side_effect = lambda x: x
        self.mock_node_db.load_message_states.return_value = {}

        self.bridge = MeshtasticMatrixBridge()

    def tearDown(self):
        self.node_db_patcher.stop()

    def test_extract_from_text_field(self):
        decoded = {"text": "Hello World"}
        text = self.bridge._extract_text(decoded, 1)
        self.assertEqual(text, "Hello World")

    def test_extract_from_emoji_field(self):
        decoded = {"emoji": "😀"}
        text = self.bridge._extract_text(decoded, 1)
        self.assertEqual(text, "😀")

    def test_extract_from_bytes_payload_reaction_app(self):
        decoded = {"payload": b"thumbs_up"}
        text = self.bridge._extract_text(decoded, 68)  # REACTION_APP
        self.assertEqual(text, "thumbs_up")

    def test_extract_from_string_payload_reaction_app(self):
        decoded = {"payload": "👍"}
        text = self.bridge._extract_text(decoded, 68)  # REACTION_APP
        self.assertEqual(text, "👍")


class TestNodeInfoHandling(unittest.TestCase):
    def setUp(self):
        self.node_db_patcher = patch('bridge.NodeDatabase')
        self.mock_node_db_cls = self.node_db_patcher.start()
        self.mock_node_db = self.mock_node_db_cls.return_value
        self.mock_node_db.get_node_name.side_effect = lambda x: x
        self.mock_node_db.load_message_states.return_value = {}
        self.mock_node_db.update_node = MagicMock()

        self.bridge = MeshtasticMatrixBridge()

    def tearDown(self):
        self.node_db_patcher.stop()

    def test_handle_node_info_updates_database(self):
        async def run():
            await self.bridge.handle_node_info("!abc123", "Node1", "Long Node Name")
            
            self.mock_node_db.update_node.assert_called_once_with("!abc123", "Node1", "Long Node Name")

        asyncio.run(run())

    def test_handle_node_info_with_only_short_name(self):
        async def run():
            await self.bridge.handle_node_info("!def456", short_name="ShortN")
            
            self.mock_node_db.update_node.assert_called_once_with("!def456", "ShortN", None)

        asyncio.run(run())


class TestEmptyMessages(unittest.TestCase):
    def setUp(self):
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

    def test_empty_text_ignored(self):
        async def run():
            stats = ReceptionStats(gateway_id="GW", rssi=-80, snr=10.0)
            packet = {"id": 1, "fromId": "!node", "decoded": {"text": ""}}
            
            await self.bridge.handle_meshtastic_message(packet, "mqtt", stats)
            
            self.bridge.matrix_bot.send_message.assert_not_called()

        asyncio.run(run())

    def test_missing_text_field_ignored(self):
        async def run():
            stats = ReceptionStats(gateway_id="GW", rssi=-80, snr=10.0)
            packet = {"id": 2, "fromId": "!node", "decoded": {}}
            
            await self.bridge.handle_meshtastic_message(packet, "mqtt", stats)
            
            self.bridge.matrix_bot.send_message.assert_not_called()

        asyncio.run(run())


class TestUtilityFunctions(unittest.TestCase):
    def test_node_id_to_str(self):
        from utils import node_id_to_str
        result = node_id_to_str(0xabc123)
        self.assertEqual(result, "!abc123")

    def test_extract_channel_name_from_topic(self):
        from utils import extract_channel_name_from_topic
        result = extract_channel_name_from_topic("msh/EU_868/2/e/LongFast/!abc123")
        self.assertEqual(result, "LongFast")

    def test_extract_channel_name_unknown(self):
        from utils import extract_channel_name_from_topic
        result = extract_channel_name_from_topic("msh/EU_868/2")
        self.assertEqual(result, "Unknown")

    def test_is_emoji_only_true(self):
        from utils import is_emoji_only
        self.assertTrue(is_emoji_only("😀"))
        self.assertTrue(is_emoji_only("👍"))
        self.assertTrue(is_emoji_only("❤️"))

    def test_is_emoji_only_false(self):
        from utils import is_emoji_only
        self.assertFalse(is_emoji_only("Hello"))
        self.assertFalse(is_emoji_only("Test123"))
        self.assertFalse(is_emoji_only("This is a long message"))


class TestConfigValidation(unittest.TestCase):
    def test_missing_required_config(self):
        with patch.object(config, 'MATRIX_HOMESERVER', None):
            with self.assertRaises(SystemExit):
                config.validate_config()

    def test_missing_all_connection_methods(self):
        with patch.object(config, 'MQTT_BROKER', None):
            with patch.object(config, 'MESHTASTIC_HOST', None):
                with self.assertRaises(SystemExit):
                    config.validate_config()


if __name__ == '__main__':
    unittest.main()
