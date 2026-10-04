import sqlite3
from utils.colors import warning


class Memory:
    def __init__(self, database_path: str = "./memory/astra.db"):
        try:
            self.connection = sqlite3.connect(database_path, timeout=30.0)
            self._init_schema()
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to connect to memory database: {e}") from e

    def _init_schema(self):
        try:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.connection.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to initialize memory schema: {e}") from e

    def remember(self, category: str, content: str) -> bool:
        """Store a memory. Returns True on success."""
        if not category or not content:
            return False
        try:
            self.connection.execute(
                """
                INSERT INTO memories (category, content)
                VALUES (?, ?)
                """,
                (category, content)
            )
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            print(warning(f"Memory error (remember): {e}"))
            return False

    def search(self, query: str) -> list:
        """Search memories. Returns list of (id, category, content, created_at)."""
        if not query:
            return []
        try:
            cursor = self.connection.execute(
                """
                SELECT id, category, content, created_at
                FROM memories
                WHERE content LIKE ? OR category LIKE ?
                ORDER BY created_at DESC
                """,
                (f"%{query}%", f"%{query}%")
            )
            return cursor.fetchall()
        except sqlite3.Error as e:
            print(warning(f"Memory error (search): {e}"))
            return []

    def forget(self, memory_id: int) -> bool:
        """Delete a memory by ID. Returns True on success."""
        if not isinstance(memory_id, int) or memory_id <= 0:
            return False
        try:
            cursor = self.connection.execute(
                "DELETE FROM memories WHERE id = ?",
                (memory_id,)
            )
            self.connection.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(warning(f"Memory error (forget): {e}"))
            return False

    def close(self):
        try:
            if self.connection:
                self.connection.close()
        except Exception:
            pass