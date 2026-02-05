import sqlite3
import logging
import json
from dataclasses import asdict
from typing import Optional, Dict
from contextlib import contextmanager
import config
from models import MessageState, ReceptionStats

logger = logging.getLogger(__name__)


class NodeDatabase:
    def __init__(self, db_path: str = config.NODE_DB_PATH):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize the database schema."""
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    short_name TEXT,
                    long_name TEXT,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    packet_id INTEGER PRIMARY KEY,
                    matrix_event_id TEXT,
                    original_text TEXT,
                    sender TEXT,
                    reception_list_json TEXT,
                    replies_json TEXT,
                    last_update REAL
                )
            ''')
            conn.commit()
            logger.info(f"Node database initialized at {self.db_path}")
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()
    
    def update_node(self, node_id: str, short_name: Optional[str] = None, long_name: Optional[str] = None):
        """Update or insert a node's information."""
        with self._get_connection() as conn:
            conn.execute('''
                INSERT INTO nodes (node_id, short_name, long_name, last_seen)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(node_id) DO UPDATE SET
                    short_name = COALESCE(?, short_name),
                    long_name = COALESCE(?, long_name),
                    last_seen = CURRENT_TIMESTAMP
            ''', (node_id, short_name, long_name, short_name, long_name))
            conn.commit()
            logger.debug(f"Updated node {node_id}: short={short_name}, long={long_name}")
    
    def get_node_name(self, node_id: str) -> str:
        """Get a human-readable name for a node ID.
        
        Returns the short_name if available, otherwise long_name, otherwise the node_id.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                'SELECT short_name, long_name FROM nodes WHERE node_id = ?',
                (node_id,)
            )
            row = cursor.fetchone()
            
            if row:
                short_name, long_name = row
                if short_name:
                    return short_name
                elif long_name:
                    return long_name
            
            # Fallback to node_id
            return node_id
    
    def get_all_nodes(self):
        """Get all nodes from the database."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                'SELECT node_id, short_name, long_name, last_seen FROM nodes ORDER BY last_seen DESC'
            )
            return cursor.fetchall()

    def save_message_state(self, state: MessageState):
        """Save or update a MessageState object."""
        reception_json = json.dumps([asdict(s) for s in state.reception_list])
        replies_json = json.dumps(state.replies)
        
        with self._get_connection() as conn:
            conn.execute('''
                INSERT INTO messages (packet_id, matrix_event_id, original_text, sender, reception_list_json, replies_json, last_update)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(packet_id) DO UPDATE SET
                    matrix_event_id = excluded.matrix_event_id,
                    original_text = excluded.original_text,
                    sender = excluded.sender,
                    reception_list_json = excluded.reception_list_json,
                    replies_json = excluded.replies_json,
                    last_update = excluded.last_update
            ''', (
                state.packet_id, 
                state.matrix_event_id, 
                state.original_text, 
                state.sender, 
                reception_json, 
                replies_json, 
                state.last_update
            ))
            conn.commit()
    
    def load_message_states(self) -> Dict[int, MessageState]:
        """Load all MessageState objects from the database."""
        states = {}
        with self._get_connection() as conn:
            cursor = conn.execute('SELECT packet_id, matrix_event_id, original_text, sender, reception_list_json, replies_json, last_update FROM messages')
            rows = cursor.fetchall()
            
            for row in rows:
                packet_id, matrix_event_id, text, sender, rx_json, replies_json, last_update = row
                
                try:
                    rx_list_data = json.loads(rx_json)
                    reception_list = [ReceptionStats(**d) for d in rx_list_data]
                    
                    replies = json.loads(replies_json)
                    
                    state = MessageState(
                        packet_id=packet_id,
                        matrix_event_id=matrix_event_id,
                        original_text=text,
                        sender=sender,
                        reception_list=reception_list,
                        replies=replies,
                        last_update=last_update
                    )
                    states[packet_id] = state
                except Exception as e:
                    logger.error(f"Failed to load message state for {packet_id}: {e}")
        
        logger.info(f"Loaded {len(states)} messages from database.")
        return states
