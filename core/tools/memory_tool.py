from memory.memory import Memory


class MemoryTool:
    def __init__(self):
        self.memory = Memory()

        self.functions = {
            "memory_remember": self.remember,
            "memory_search": self.search,
            "memory_forget": self.forget
        }

    def remember(self, category, content):
        self.memory.remember(category, content)

        return {
            "success": True,
            "message": "Memory saved successfully."
        }

    def search(self, query):
        memories = self.memory.search(query)

        return [
            {
                "id": memory[0],
                "category": memory[1],
                "content": memory[2],
                "created_at": memory[3]
            }
            for memory in memories
        ]

    def forget(self, memory_id):
        self.memory.forget(memory_id)

        return {
            "success": True,
            "message": "Memory deleted successfully."
        }

    def get_tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "memory_remember",
                    "description": (
                        "Store important information about the user "
                        "for future conversations."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "description": "Category of the memory."
                            },
                            "content": {
                                "type": "string",
                                "description": "Information to remember."
                            }
                        },
                        "required": ["category", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_search",
                    "description": (
                        "Search the user's long-term memory."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Information to search for."
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_forget",
                    "description": (
                        "Delete a memory from the user's long-term memory."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "memory_id": {
                                "type": "integer",
                                "description": "ID of the memory to delete."
                            }
                        },
                        "required": ["memory_id"]
                    }
                }
            }
        ]