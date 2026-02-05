import sqlite3
import logging
from typing import Optional
from contextlib import contextmanager
import config

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
