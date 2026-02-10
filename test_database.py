import unittest
import tempfile
import os
from node_database import NodeDatabase
from models import MessageState


class TestNodeDatabase(unittest.TestCase):
    def setUp(self):
        # Create temporary database file
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.db = NodeDatabase(self.db_path)

    def tearDown(self):
        # Close and remove temporary database
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_database_initialization(self):
        # Verify tables are created
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        # Check nodes table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nodes'")
        self.assertIsNotNone(cursor.fetchone())
        
        # Check messages table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
        self.assertIsNotNone(cursor.fetchone())
        
        conn.close()

    def test_update_node_new(self):
        self.db.update_node("!abc123", "Node1", "Long Node Name")
        
        name = self.db.get_node_name("!abc123")
        self.assertEqual(name, "Node1")

    def test_update_node_existing(self):
        self.db.update_node("!abc123", "Node1", "Long Name")
        self.db.update_node("!abc123", "Node2", "New Long Name")
        
        name = self.db.get_node_name("!abc123")
        self.assertEqual(name, "Node2")

    def test_update_node_short_name_only(self):
        self.db.update_node("!def456", short_name="ShortN")
        
        name = self.db.get_node_name("!def456")
        self.assertEqual(name, "ShortN")

    def test_update_node_long_name_only(self):
        self.db.update_node("!ghi789", long_name="Long Name Only")
        
        # Should return long name if no short name
        name = self.db.get_node_name("!ghi789")
        self.assertEqual(name, "Long Name Only")

    def test_get_node_name_unknown(self):
        name = self.db.get_node_name("!unknown")
        self.assertEqual(name, "!unknown")

    def test_get_node_name_priority(self):
        # Short name should take priority over long name
        self.db.update_node("!xyz", "Short", "Very Long Name")
        
        name = self.db.get_node_name("!xyz")
        self.assertEqual(name, "Short")

    def test_get_all_nodes(self):
        self.db.update_node("!node1", "N1", "Node One")
        self.db.update_node("!node2", "N2", "Node Two")
        self.db.update_node("!node3", "N3", "Node Three")
        
        nodes = self.db.get_all_nodes()
        self.assertEqual(len(nodes), 3)
        
        node_ids = [n['node_id'] for n in nodes]
        self.assertIn("!node1", node_ids)
        self.assertIn("!node2", node_ids)
        self.assertIn("!node3", node_ids)

    def test_save_message_state(self):
        state = MessageState(
            packet_id=12345,
            matrix_event_id="$event123",
            sender="!sender",
            text="Test message",
            render_only_stats=False
        )
        
        self.db.save_message_state(state)
        
        # Load and verify
        states = self.db.load_message_states()
        self.assertIn(12345, states)
        loaded = states[12345]
        self.assertEqual(loaded.matrix_event_id, "$event123")
        self.assertEqual(loaded.sender, "!sender")
        self.assertEqual(loaded.text, "Test message")
        self.assertFalse(loaded.render_only_stats)

    def test_save_message_state_compact_mode(self):
        state = MessageState(
            packet_id=67890,
            matrix_event_id=None,
            sender="!sender",
            text="Matrix msg",
            render_only_stats=True,
            related_event_id="$matrix_evt"
        )
        
        self.db.save_message_state(state)
        
        states = self.db.load_message_states()
        loaded = states[67890]
        self.assertIsNone(loaded.matrix_event_id)
        self.assertTrue(loaded.render_only_stats)
        self.assertEqual(loaded.related_event_id, "$matrix_evt")

    def test_load_message_states_empty(self):
        states = self.db.load_message_states()
        self.assertEqual(len(states), 0)

    def test_update_message_state(self):
        # Save initial state
        state = MessageState(
            packet_id=99999,
            matrix_event_id="$evt1",
            sender="!sender",
            text="Original"
        )
        self.db.save_message_state(state)
        
        # Update state
        state.matrix_event_id = "$evt2"
        state.text = "Updated"
        self.db.save_message_state(state)
        
        # Load and verify update
        states = self.db.load_message_states()
        loaded = states[99999]
        self.assertEqual(loaded.matrix_event_id, "$evt2")
        self.assertEqual(loaded.text, "Updated")

    def test_multiple_message_states(self):
        state1 = MessageState(packet_id=1, matrix_event_id="$e1", sender="!s1", text="M1")
        state2 = MessageState(packet_id=2, matrix_event_id="$e2", sender="!s2", text="M2")
        state3 = MessageState(packet_id=3, matrix_event_id="$e3", sender="!s3", text="M3")
        
        self.db.save_message_state(state1)
        self.db.save_message_state(state2)
        self.db.save_message_state(state3)
        
        states = self.db.load_message_states()
        self.assertEqual(len(states), 3)
        self.assertIn(1, states)
        self.assertIn(2, states)
        self.assertIn(3, states)


if __name__ == '__main__':
    unittest.main()
