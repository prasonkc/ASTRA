import sqlite3


class Memory:
    def __init__(self, database_path="./memory/astra.db"):
        self.connection = sqlite3.connect(database_path)

        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.connection.commit()

    def remember(self, category, content):
        self.connection.execute(
            """
            INSERT INTO memories (category, content)
            VALUES (?, ?)
            """,
            (category, content)
        )

        self.connection.commit()

    def search(self, query):
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

    def forget(self, memory_id):
        self.connection.execute(
            "DELETE FROM memories WHERE id = ?",
            (memory_id,)
        )

        self.connection.commit()

    def close(self):
        self.connection.close()