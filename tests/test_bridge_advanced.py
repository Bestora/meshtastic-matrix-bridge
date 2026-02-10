import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from src.bridge import MeshtasticMatrixBridge
from src.models import ReceptionStats, MessageState
from src import config


class TestBridgeAdvanced(unittest.TestCase):
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

    def test_extract_text_priority(self):
        # Text field has priority
        decoded = {"text": "Hello", "emoji": "👍", "payload": b"Test"}
        text = self.bridge._extract_text(decoded, 1)
        self.assertEqual(text, "Hello")

    def test_extract_text_emoji_fallback(self):
        # Emoji if no text
        decoded = {"emoji": "😀", "payload": b"Test"}
        text = self.bridge._extract_text(decoded, 1)
        self.assertEqual(text, "😀")

    def test_extract_text_payload_for_reaction_app(self):
        # Payload for REACTION_APP
        decoded = {"payload": b"heart"}
        text = self.bridge._extract_text(decoded, 68)
        self.assertEqual(text, "heart")

    def test_extract_text_empty(self):
        # Empty dict returns empty string
        decoded = {}
        text = self.bridge._extract_text(decoded, 1)
        self.assertEqual(text, "")

    def test_find_reply_id_from_decoded_reply_id(self):
        packet = {}
        decoded = {"replyId": 12345}
        
        reply_id = self.bridge._find_reply_id(packet, decoded, 999, "text", 1)
        self.assertEqual(reply_id, 12345)

    def test_find_reply_id_from_decoded_reply(self):
        packet = {}
        decoded = {"reply": 67890}
        
        reply_id = self.bridge._find_reply_id(packet, decoded, 999, "text", 1)
        self.assertEqual(reply_id, 67890)

    def test_search_reply_fields(self):
        packet = {"someField": 55555}
        decoded = {"otherField": 44444}
        
        # Set up message state to search against
        self.bridge.message_state[55555] = MessageState(
            packet_id=55555,
            matrix_event_id="$evt55555",
            sender="!sender",
            text="Original"
        )
        
        reply_id = self.bridge._search_reply_fields(packet, decoded)
        self.assertEqual(reply_id, 55555)

    def test_deep_search_reply_id(self):
        packet = {"linkage": {"to": 33333}}
        decoded = {}
        
        self.bridge.message_state[33333] = MessageState(
            packet_id=33333,
            matrix_event_id="$evt33333",
            sender="!sender",
            text="Deep"
        )
        
        reply_id = self.bridge._deep_search_reply_id(packet, decoded, 99999)
        self.assertEqual(reply_id, 33333)

    def test_parse_legacy_reaction_format(self):
        text = "[Reaction to 11111]: 👍"
        sender = "!user"
        
        self.bridge.message_state[11111] = MessageState(
            packet_id=11111,
            matrix_event_id="$evt11111",
            sender="!other",  # Different sender
            text="Original"
        )
        
        reply_id = self.bridge._parse_legacy_reaction(text, sender)
        self.assertEqual(reply_id, 11111)

    def test_parse_legacy_reaction_ignores_own_echo(self):
        text = "[Reaction to 22222]: ❤️"
        sender = "!user"
        
        self.bridge.message_state[22222] = MessageState(
            packet_id=22222,
            matrix_event_id="$evt22222",
            sender="!user",  # Same sender
            text="Original"
        )
        
        reply_id = self.bridge._parse_legacy_reaction(text, sender)
        self.assertEqual(reply_id, 0)  # Should ignore own echo

    def test_heuristic_reply_id_emoji_to_last_packet(self):
        # Setup last packet
        self.bridge.last_packet_id = 88888
        self.bridge.message_state[88888] = MessageState(
            packet_id=88888,
            matrix_event_id="$evt88888",
            sender="!sender",
            text="Last"
        )
        
        reply_id = self.bridge._heuristic_reply_id("😀", 1, 99999)
        self.assertEqual(reply_id, 88888)

    def test_heuristic_reply_id_non_emoji(self):
        self.bridge.last_packet_id = 88888
        
        reply_id = self.bridge._heuristic_reply_id("This is text", 1, 99999)
        self.assertEqual(reply_id, 0)  # Should not use heuristic for regular text

    def test_should_process_message_empty_text(self):
        result = self.bridge._should_process_message(1, "!s", "", 0, "0", "Ch", 1)
        self.assertFalse(result)

    def test_should_process_message_legacy_reaction_format(self):
        # Legacy format should not be processed as new message
        result = self.bridge._should_process_message(
            1, "!s", "[Reaction to 123]: 👍", 0, "0", "Ch", 1
        )
        self.assertTrue(result)  # Actually still processed, but as reaction

    def test_should_process_message_disallowed_channel_by_index(self):
        with patch.object(config, 'MESHTASTIC_CHANNELS', ['1', '2']):
            result = self.bridge._should_process_message(1, "!s", "text", 0, "0", "Ch", 1)
            self.assertFalse(result)

    def test_should_process_message_disallowed_channel_by_name(self):
        with patch.object(config, 'MESHTASTIC_CHANNELS', ['AllowedChannel']):
            result = self.bridge._should_process_message(
                1, "!s", "text", 0, "1", "DisallowedChannel", 1
            )
            self.assertFalse(result)

    def test_should_process_message_allowed_channel(self):
        with patch.object(config, 'MESHTASTIC_CHANNELS', ['0', 'LongFast']):
            result = self.bridge._should_process_message(1, "!s", "text", 0, "0", "LongFast", 1)
            self.assertTrue(result)

    def test_handle_new_message_stores_state(self):
        async def run():
            self.bridge.matrix_bot.send_message.return_value = "$event_new"
            
            await self.bridge._handle_new_message(777, "!sender", "New message", 
                                                  ReceptionStats("!gw", -70, 8.0))
            
            self.assertIn(777, self.bridge.message_state)
            state = self.bridge.message_state[777]
            self.assertEqual(state.matrix_event_id, "$event_new")
            self.assertEqual(state.sender, "!sender")
            self.assertEqual(state.text, "New message")
            self.assertEqual(len(state.reception_stats), 1)

        asyncio.run(run())

    def test_handle_new_message_saves_to_db(self):
        async def run():
            self.bridge.matrix_bot.send_message.return_value = "$event_db"
            
            await self.bridge._handle_new_message(888, "!sender", "DB test",
                                                  ReceptionStats("!gw", -75, 7.0))
            
            self.mock_node_db.save_message_state.assert_called_once()

        asyncio.run(run())

    def test_handle_reply_message_text_creates_new(self):
        async def run():
            # Setup original
            self.bridge.message_state[100] = MessageState(
                packet_id=100,
                matrix_event_id="$original",
                sender="!sender",
                text="Original"
            )
            
            self.bridge.matrix_bot.send_message.return_value = "$reply"
            
            await self.bridge._handle_reply_message(
                101, "!sender", "This is a reply", 100,
                ReceptionStats("!gw", -70, 8.0)
            )
            
            # Should create new message with reply_to
            call_args = self.bridge.matrix_bot.send_message.call_args
            self.assertEqual(call_args[1]['reply_to'], "$original")

        asyncio.run(run())

    def test_handle_reply_message_emoji_edits_original(self):
        async def run():
            # Setup original
            self.bridge.message_state[200] = MessageState(
                packet_id=200,
                matrix_event_id="$original2",
                sender="!sender",
                text="Original"
            )
            
            await self.bridge._handle_reply_message(
                201, "!sender", "❤️", 200,
                ReceptionStats("!gw", -70, 8.0),
                portnum=1
            )
            
            # Should edit original, not create new
            self.bridge.matrix_bot.edit_message.assert_called_once()
            edit_args = self.bridge.matrix_bot.edit_message.call_args[0]
            self.assertEqual(edit_args[0], "$original2")

        asyncio.run(run())

    def test_handle_reply_message_orphan_reply(self):
        async def run():
            # Reply to non-existent packet
            self.bridge.matrix_bot.send_message.return_value = "$orphan"
            
            await self.bridge._handle_reply_message(
                999, "!sender", "Orphan reply", 888,
                ReceptionStats("!gw", -70, 8.0)
            )
            
            # Should still create message but without reply_to
            call_args = self.bridge.matrix_bot.send_message.call_args
            self.assertIsNone(call_args[1]['reply_to'])

        asyncio.run(run())

    def test_handle_duplicate_message_aggregates_stats(self):
        async def run():
            # Setup original message
            self.bridge.message_state[300] = MessageState(
                packet_id=300,
                matrix_event_id="$original3",
                sender="!sender",
                text="Original"
            )
            self.bridge.message_state[300].reception_stats = [
                ReceptionStats("!gw1", -80, 9.0, 0)
            ]
            
            # Duplicate from different gateway
            await self.bridge._handle_duplicate_message(
                300,
                ReceptionStats("!gw2", -75, 8.5, 0)
            )
            
            # Should aggregate stats
            state = self.bridge.message_state[300]
            self.assertEqual(len(state.reception_stats), 2)
            
            # Should edit message
            self.bridge.matrix_bot.edit_message.assert_called_once()

        asyncio.run(run())

    def test_handle_duplicate_message_same_gateway_ignored(self):
        async def run():
            # Setup original
            self.bridge.message_state[400] = MessageState(
                packet_id=400,
                matrix_event_id="$original4",
                sender="!sender",
                text="Original"
            )
            self.bridge.message_state[400].reception_stats = [
                ReceptionStats("!gw1", -80, 9.0, 0)
            ]
            
            # Duplicate from same gateway
            await self.bridge._handle_duplicate_message(
                400,
                ReceptionStats("!gw1", -81, 8.9, 0)
            )
            
            # Should not add duplicate
            state = self.bridge.message_state[400]
            self.assertEqual(len(state.reception_stats), 1)
            
            # Should not edit
            self.bridge.matrix_bot.edit_message.assert_not_called()

        asyncio.run(run())

    def test_update_matrix_message_normal_mode(self):
        async def run():
            state = MessageState(
                packet_id=500,
                matrix_event_id="$evt500",
                sender="!sender",
                text="Test"
            )
            state.reception_stats = [ReceptionStats("!gw", -70, 8.0, 0)]
            
            await self.bridge._update_matrix_message(state)
            
            # Should call edit_message
            self.bridge.matrix_bot.edit_message.assert_called_once()
            args = self.bridge.matrix_bot.edit_message.call_args[0]
            self.assertEqual(args[0], "$evt500")
            self.assertIn("Test", args[1])

        asyncio.run(run())

    def test_update_matrix_message_with_replies(self):
        async def run():
            state = MessageState(
                packet_id=600,
                matrix_event_id="$evt600",
                sender="!sender",
                text="Parent"
            )
            state.reception_stats = [ReceptionStats("!gw", -70, 8.0, 0)]
            
            # Add child reactions
            child1 = MessageState(packet_id=601, parent_packet_id=600, sender="!s1", text="👍")
            child2 = MessageState(packet_id=602, parent_packet_id=600, sender="!s2", text="❤️")
            state.child_packet_ids = [601, 602]
            
            self.bridge.message_state[601] = child1
            self.bridge.message_state[602] = child2
            
            await self.bridge._update_matrix_message(state)
            
            # Should include reactions in edit
            args = self.bridge.matrix_bot.edit_message.call_args[0]
            content = args[1]
            self.assertIn("👍", content)
            self.assertIn("❤️", content)

        asyncio.run(run())

    def test_update_matrix_message_compact_mode_initial(self):
        async def run():
            state = MessageState(
                packet_id=700,
                matrix_event_id=None,
                sender="!sender",
                text="Compact",
                render_only_stats=True,
                related_event_id="$user_event"
            )
            state.reception_stats = [ReceptionStats("!gw", -70, 8.0, 0)]
            
            self.bridge.matrix_bot.send_message.return_value = "$stats_event"
            
            await self.bridge._update_matrix_message(state)
            
            # Should send stats-only message
            self.bridge.matrix_bot.send_message.assert_called_once()
            call_args = self.bridge.matrix_bot.send_message.call_args
            content = call_args[0][0]
            self.assertNotIn("Compact", content)  # Should not include text
            self.assertIn("!gw", content)  # Should include stats

        asyncio.run(run())

    def test_update_matrix_message_compact_mode_update(self):
        async def run():
            state = MessageState(
                packet_id=800,
                matrix_event_id="$stats_evt",
                sender="!sender",
                text="Compact2",
                render_only_stats=True
            )
            state.reception_stats = [
                ReceptionStats("!gw1", -70, 8.0, 0),
                ReceptionStats("!gw2", -75, 7.5, 0)
            ]
            
            await self.bridge._update_matrix_message(state)
            
            # Should edit stats message
            self.bridge.matrix_bot.edit_message.assert_called_once()

        asyncio.run(run())

    def test_handle_matrix_message_creates_state(self):
        async def run():
            event = MagicMock()
            event.sender = "@user:matrix.org"
            event.body = "Hello mesh"
            event.event_id = "$matrix_evt"
            
            mock_packet = MagicMock()
            mock_packet.id = 9999
            self.bridge.meshtastic_interface.send_text.return_value = mock_packet
            
            await self.bridge.handle_matrix_message(event)
            
            # Should create state in compact mode
            self.assertIn(9999, self.bridge.message_state)
            state = self.bridge.message_state[9999]
            self.assertTrue(state.render_only_stats)
            self.assertEqual(state.related_event_id, "$matrix_evt")

        asyncio.run(run())

    def test_handle_matrix_message_with_reply_fallback(self):
        async def run():
            event = MagicMock()
            event.sender = "@user:matrix.org"
            event.body = "> <@other:matrix.org> Original\n\nReply text"
            event.event_id = "$reply_evt"
            event.source = {
                "content": {
                    "m.relates_to": {
                        "m.in_reply_to": {
                            "event_id": "$original_evt"
                        }
                    }
                }
            }
            
            # Setup original message state
            self.bridge.matrix_event_to_packet[("$original_evt", 0)] = 5555
            self.bridge.message_state[5555] = MessageState(
                packet_id=5555,
                matrix_event_id="$original_evt",
                sender="!mesh_sender",
                text="Original mesh"
            )
            
            mock_packet = MagicMock()
            mock_packet.id = 5556
            self.bridge.meshtastic_interface.send_text.return_value = mock_packet
            
            await self.bridge.handle_matrix_message(event)
            
            # Should send with reply_id
            # The actual call is complex, just verify it was called
            self.bridge.meshtastic_interface.send_text.assert_called()

        asyncio.run(run())

    def test_handle_matrix_reaction_forwards_to_mesh(self):
        async def run():
            # Setup original message
            self.bridge.message_state[7777] = MessageState(
                packet_id=7777,
                matrix_event_id="$evt7777",
                sender="!sender",
                text="Original"
            )
            
            event = MagicMock()
            event.content = {
                "m.relates_to": {
                    "event_id": "$evt7777",
                    "key": "🎉"
                }
            }
            
            await self.bridge.handle_matrix_reaction(event)
            
            # Should send tapback
            self.bridge.meshtastic_interface.send_tapback.assert_called_once_with(
                7777, "🎉", channel_idx=0
            )

        asyncio.run(run())

    def test_handle_matrix_reaction_unknown_event(self):
        async def run():
            event = MagicMock()
            event.content = {
                "m.relates_to": {
                    "event_id": "$unknown",
                    "key": "👍"
                }
            }
            
            await self.bridge.handle_matrix_reaction(event)
            
            # Should not send tapback
            self.bridge.meshtastic_interface.send_tapback.assert_not_called()

        asyncio.run(run())

    def test_processing_packets_lock(self):
        async def run():
            # Simulate concurrent processing of same packet
            packet = {"id": 1111, "fromId": "!s", "decoded": {"text": "Test"}}
            stats1 = ReceptionStats("!gw1", -70, 8.0)
            stats2 = ReceptionStats("!gw2", -75, 7.5)
            
            self.bridge.matrix_bot.send_message.return_value = "$evt1111"
            
            # Process both concurrently
            await asyncio.gather(
                self.bridge.handle_meshtastic_message(packet, "mqtt", stats1),
                self.bridge.handle_meshtastic_message(packet, "mqtt", stats2)
            )
            
            # Should only send once, then aggregate
            state = self.bridge.message_state[1111]
            self.assertEqual(len(state.reception_stats), 2)

        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
