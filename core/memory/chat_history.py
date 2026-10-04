import sqlite3
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional


class ChatHistory:
    def __init__(self, db_path: str = "./memory/chat_history.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
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

    def create_session(self, title: str = None) -> str:
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        if title is None:
            title = f"Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        self.conn.execute(
            "INSERT INTO conversations (session_id, title) VALUES (?, ?)",
            (session_id, title)
        )
        self.conn.commit()
        return session_id

    def get_session_id_by_index(self, index: int) -> Optional[str]:
        """Get session_id by index (0 = most recent)"""
        cursor = self.conn.execute(
            "SELECT session_id FROM conversations ORDER BY updated_at DESC LIMIT 1 OFFSET ?",
            (index,)
        )
        row = cursor.fetchone()
        return row["session_id"] if row else None

    def get_latest_session_id(self) -> Optional[str]:
        return self.get_session_id_by_index(0)

    def session_exists(self, session_id: str) -> bool:
        cursor = self.conn.execute(
            "SELECT 1 FROM conversations WHERE session_id = ?", (session_id,)
        )
        return cursor.fetchone() is not None

    def add_message(self, session_id: str, role: str, content: str = None, tool_calls: List[Dict] = None):
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

    def get_history(self, session_id: str, limit: int = 100) -> List[Dict]:
        cursor = self.conn.execute("""
            SELECT role, content, tool_calls FROM messages
            WHERE conversation_id = (SELECT id FROM conversations WHERE session_id = ?)
            ORDER BY created_at ASC
        """, (session_id,))
        
        messages = []
        for row in cursor.fetchall():
            msg = {"role": row["role"], "content": row["content"]}
            if row["tool_calls"]:
                msg["tool_calls"] = json.loads(row["tool_calls"])
            messages.append(msg)
        
        if limit and len(messages) > limit:
            messages = messages[-limit:]
        return messages

    def list_sessions(self, limit: int = 20) -> List[Dict]:
        cursor = self.conn.execute("""
            SELECT session_id, title, created_at, updated_at 
            FROM conversations 
            ORDER BY updated_at DESC 
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def delete_session(self, session_id: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM conversations WHERE session_id = ?", (session_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def update_session_title(self, session_id: str, title: str):
        self.conn.execute(
            "UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (title, session_id)
        )
        self.conn.commit()

    def get_message_count(self, session_id: str) -> int:
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM messages
            WHERE conversation_id = (SELECT id FROM conversations WHERE session_id = ?)
        """, (session_id,))
        return cursor.fetchone()[0]

    def close(self):
        self.conn.close()

    def delete_all_sessions(self) -> int:
        """Delete all sessions. Returns number of deleted sessions."""
        cursor = self.conn.execute("DELETE FROM conversations")
        self.conn.commit()
        return cursor.rowcount

    def get_session_preview(self, session_id: str, max_messages: int = 3) -> str:
        """Get a preview of the session content (last few user/assistant messages)."""
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

    def list_sessions_with_preview(self, limit: int = 20) -> List[Dict]:
        """List sessions with message count and preview."""
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