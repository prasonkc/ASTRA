from memory.memory import Memory
from utils.colors import warning


class MemoryTool:
    def __init__(self):
        try:
            self.memory = Memory()
        except Exception as e:
            print(f"Failed to initialize memory tool: {e}")
            # Create a dummy memory that always fails gracefully
            self.memory = None

        self.functions = {
            "memory_remember": self.remember,
            "memory_search": self.search,
            "memory_forget": self.forget
        }

    def remember(self, category: str, content: str) -> dict:
        """Store a memory. Returns result dict."""
        if not self.memory:
            return {"success": False, "message": "Memory system unavailable"}
        
        try:
            if not category or not category.strip():
                return {"success": False, "message": "Category cannot be empty"}
            if not content or not content.strip():
                return {"success": False, "message": "Content cannot be empty"}
            
            success = self.memory.remember(category.strip(), content.strip())
            if success:
                return {"success": True, "message": "Memory saved successfully."}
            else:
                return {"success": False, "message": "Failed to save memory"}
        except Exception as e:
            return {"success": False, "message": f"Error saving memory: {e}"}

    def search(self, query: str) -> list:
        """Search memories. Returns list of memory dicts."""
        if not self.memory:
            return [{"error": "Memory system unavailable"}]
        
        try:
            if not query or not query.strip():
                return []
            
            memories = self.memory.search(query.strip())
            return [
                {
                    "id": memory[0],
                    "category": memory[1],
                    "content": memory[2],
                    "created_at": memory[3]
                }
                for memory in memories
            ]
        except Exception as e:
            return [{"error": f"Error searching memory: {e}"}]

    def forget(self, memory_id: int) -> dict:
        """Delete a memory by ID. Returns result dict."""
        if not self.memory:
            return {"success": False, "message": "Memory system unavailable"}
        
        try:
            if not isinstance(memory_id, int) or memory_id <= 0:
                return {"success": False, "message": "Invalid memory ID"}
            
            success = self.memory.forget(memory_id)
            if success:
                return {"success": True, "message": "Memory deleted successfully."}
            else:
                return {"success": False, "message": "Memory not found or failed to delete"}
        except Exception as e:
            return {"success": False, "message": f"Error deleting memory: {e}"}

    def get_tools(self) -> list:
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