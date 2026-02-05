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
                    last_update REAL,
                    render_only_stats BOOLEAN DEFAULT 0,
                    related_event_id TEXT DEFAULT NULL
                )
            ''')
            
            # Migration for existing tables
            try:
                conn.execute('ALTER TABLE messages ADD COLUMN render_only_stats BOOLEAN DEFAULT 0')
            except sqlite3.OperationalError:
                pass # Already exists

            try:
                conn.execute('ALTER TABLE messages ADD COLUMN related_event_id TEXT DEFAULT NULL')
            except sqlite3.OperationalError:
                pass # Already exists

            conn.commit()
            logger.info(f"Node database initialized at {self.db_path}")

    # ... (omit methods until save_message_state)

    def save_message_state(self, state: MessageState):
        """Save or update a MessageState object."""
        reception_json = json.dumps([asdict(s) for s in state.reception_list])
        replies_json = json.dumps(state.replies)
        
        with self._get_connection() as conn:
            conn.execute('''
                INSERT INTO messages (packet_id, matrix_event_id, original_text, sender, reception_list_json, replies_json, last_update, render_only_stats, related_event_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(packet_id) DO UPDATE SET
                    matrix_event_id = excluded.matrix_event_id,
                    original_text = excluded.original_text,
                    sender = excluded.sender,
                    reception_list_json = excluded.reception_list_json,
                    replies_json = excluded.replies_json,
                    last_update = excluded.last_update,
                    render_only_stats = excluded.render_only_stats,
                    related_event_id = excluded.related_event_id
            ''', (
                state.packet_id, 
                state.matrix_event_id, 
                state.original_text, 
                state.sender, 
                reception_json, 
                replies_json, 
                state.last_update,
                state.render_only_stats,
                state.related_event_id
            ))
            conn.commit()
    
    def load_message_states(self) -> Dict[int, MessageState]:
        """Load all MessageState objects from the database."""
        states = {}
        with self._get_connection() as conn:
            cursor = conn.execute('SELECT packet_id, matrix_event_id, original_text, sender, reception_list_json, replies_json, last_update, render_only_stats, related_event_id FROM messages')
            rows = cursor.fetchall()
            
            for row in rows:
                packet_id, matrix_event_id, text, sender, rx_json, replies_json, last_update, render_only_stats, related_event_id = row
                
                try:
                    rx_list_data = json.loads(rx_json)
                    reception_list = [ReceptionStats(**d) for d in rx_list_data]
                    
                    replies = json.loads(replies_json)
                    
                    state = MessageState(
                        packet_id=packet_id,
                        matrix_event_id=matrix_event_id, # Can be None
                        original_text=text,
                        sender=sender,
                        reception_list=reception_list,
                        replies=replies,
                        last_update=last_update,
                        render_only_stats=bool(render_only_stats),
                        related_event_id=related_event_id
                    )
                    states[packet_id] = state
                except Exception as e:
                    logger.error(f"Failed to load message state for {packet_id}: {e}")
        
        logger.info(f"Loaded {len(states)} messages from database.")
        return states
