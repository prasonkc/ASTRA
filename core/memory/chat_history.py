import sqlite3
import json
import os
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from utils.colors import error, warning


class ChatHistory:
    def __init__(self, db_path: str = None):
        # Allow the database location to be overridden (useful for tests and for
        # running more than one ASTRA instance side by side). Defaults to the
        # core-relative path used by the terminal app.
        if not db_path:
            db_path = os.environ.get("ASTRA_DB_PATH") or "./memory/chat_history.db"
        self.db_path = db_path
        try:
            self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
            self.conn.row_factory = sqlite3.Row
            # Enforce foreign keys so deleting a conversation actually removes
            # its messages (ON DELETE CASCADE). Without this pragma SQLite
            # silently ignores the cascade and deleted conversations leave
            # orphaned messages behind.
            self.conn.execute("PRAGMA foreign_keys = ON")
            self._init_schema()
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to connect to database: {e}") from e

    def _init_schema(self):
        try:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    title TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_calls TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_id 
                ON messages(conversation_id)
            """)
            self.conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to initialize database schema: {e}") from e

    def create_session(self, title: str = None) -> str:
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        if title is None:
            title = f"Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        try:
            self.conn.execute(
                "INSERT INTO conversations (session_id, title) VALUES (?, ?)",
                (session_id, title)
            )
            self.conn.commit()
            return session_id
        except sqlite3.IntegrityError:
            # Extremely unlikely with UUID, but handle gracefully
            return self.create_session(title)
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to create session: {e}") from e

    def get_session_id_by_index(self, index: int) -> Optional[str]:
        """Get session_id by index (0 = most recent)"""
        if index < 0:
            return None
        try:
            cursor = self.conn.execute(
                "SELECT session_id FROM conversations ORDER BY updated_at DESC LIMIT 1 OFFSET ?",
                (index,)
            )
            row = cursor.fetchone()
            return row["session_id"] if row else None
        except sqlite3.Error as e:
            print(warning(f"Database error getting session by index: {e}"))
            return None

    def get_latest_session_id(self) -> Optional[str]:
        return self.get_session_id_by_index(0)

    def session_exists(self, session_id: str) -> bool:
        try:
            cursor = self.conn.execute(
                "SELECT 1 FROM conversations WHERE session_id = ?", (session_id,)
            )
            return cursor.fetchone() is not None
        except sqlite3.Error as e:
            print(warning(f"Database error checking session existence: {e}"))
            return False

    def add_message(self, session_id: str, role: str, content: str = None, tool_calls: List[Dict] = None):
        try:
            cursor = self.conn.execute(
                "SELECT id FROM conversations WHERE session_id = ?", (session_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Session not found: {session_id}")
            conv_id = row["id"]

            self.conn.execute(
                """INSERT INTO messages (conversation_id, role, content, tool_calls)
                   VALUES (?, ?, ?, ?)""",
                (conv_id, role, content, json.dumps(tool_calls) if tool_calls else None)
            )
            
            self.conn.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conv_id,)
            )
            self.conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to add message: {e}") from e
        except (TypeError, ValueError) as e:
            raise RuntimeError(f"Invalid message data: {e}") from e

    def get_history(self, session_id: str, limit: int = 100) -> List[Dict]:
        try:
            cursor = self.conn.execute("""
                SELECT role, content, tool_calls FROM messages
                WHERE conversation_id = (SELECT id FROM conversations WHERE session_id = ?)
                ORDER BY created_at ASC, id ASC
            """, (session_id,))
            
            messages = []
            for row in cursor.fetchall():
                msg = {"role": row["role"], "content": row["content"]}
                if row["tool_calls"]:
                    try:
                        msg["tool_calls"] = json.loads(row["tool_calls"])
                    except json.JSONDecodeError:
                        msg["tool_calls"] = []  # Corrupted data, skip
                messages.append(msg)
            
            if limit and len(messages) > limit:
                messages = messages[-limit:]
            return messages
        except sqlite3.Error as e:
            print(warning(f"Database error getting history: {e}"))
            return []

    def list_sessions(self, limit: int = 20) -> List[Dict]:
        try:
            cursor = self.conn.execute("""
                SELECT session_id, title, created_at, updated_at 
                FROM conversations 
                ORDER BY updated_at DESC 
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(warning(f"Database error listing sessions: {e}"))
            return []

    def delete_session(self, session_id: str) -> bool:
        try:
            cursor = self.conn.execute(
                "DELETE FROM conversations WHERE session_id = ?", (session_id,)
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(warning(f"Database error deleting session: {e}"))
            return False

    def update_session_title(self, session_id: str, title: str):
        try:
            self.conn.execute(
                "UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (title, session_id)
            )
            self.conn.commit()
        except sqlite3.Error as e:
            print(warning(f"Database error updating session title: {e}"))

    def get_message_count(self, session_id: str) -> int:
        try:
            cursor = self.conn.execute("""
                SELECT COUNT(*) FROM messages
                WHERE conversation_id = (SELECT id FROM conversations WHERE session_id = ?)
            """, (session_id,))
            return cursor.fetchone()[0]
        except sqlite3.Error as e:
            print(warning(f"Database error getting message count: {e}"))
            return 0

    def close(self):
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass

    def delete_all_sessions(self) -> int:
        """Delete all sessions. Returns number of deleted sessions."""
        try:
            cursor = self.conn.execute("DELETE FROM conversations")
            self.conn.commit()
            return cursor.rowcount
        except sqlite3.Error as e:
            print(warning(f"Database error clearing all sessions: {e}"))
            return 0

    def get_session_preview(self, session_id: str, max_messages: int = 3) -> str:
        """Get a preview of the session content (last few user/assistant messages)."""
        try:
            cursor = self.conn.execute("""
                SELECT role, content FROM messages
                WHERE conversation_id = (SELECT id FROM conversations WHERE session_id = ?)
                AND role IN ('user', 'assistant')
                ORDER BY created_at DESC
                LIMIT ?
            """, (session_id, max_messages))
            
            messages = []
            for row in cursor.fetchall():
                role = row["role"]
                content = row["content"] or ""
                # Truncate long messages
                if len(content) > 80:
                    content = content[:77] + "..."
                messages.append(f"{role}: {content}")
            
            return "\n".join(reversed(messages)) if messages else "(empty)"
        except sqlite3.Error as e:
            print(warning(f"Database error getting session preview: {e}"))
            return "(error loading preview)"

    def list_sessions_with_preview(self, limit: int = 20) -> List[Dict]:
        """List sessions with message count and preview."""
        try:
            cursor = self.conn.execute("""
                SELECT c.session_id, c.title, c.created_at, c.updated_at,
                       COUNT(m.id) as message_count
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                GROUP BY c.id
                ORDER BY c.updated_at DESC 
                LIMIT ?
            """, (limit,))
            
            sessions = []
            for row in cursor.fetchall():
                session = dict(row)
                session["preview"] = self.get_session_preview(session["session_id"])
                sessions.append(session)
            return sessions
        except sqlite3.Error as e:
            print(warning(f"Database error listing sessions with preview: {e}"))
            return []