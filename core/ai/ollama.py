import ollama

from tools.memory_tool import MemoryTool
from memory.chat_history import ChatHistory


class OllamaModel:
    def __init__(self, model_name: str, session_id: str = None):
        self.model_name = model_name
        self.memory_tool = MemoryTool()
        self.chat_history = ChatHistory()
        
        self.session_id = session_id or self.chat_history.create_session()
        
        # Load existing history or initialize with system prompt
        history = self.chat_history.get_history(self.session_id)
        if not history:
            with open("./config/identity.txt") as f:
                system_prompt = f.read().strip()
            self.history = [{"role": "system", "content": system_prompt}]
            self.chat_history.add_message(self.session_id, "system", system_prompt)
        else:
            self.history = history

    def generate(self, prompt: str):
        self.history.append({"role": "user", "content": prompt})
        self.chat_history.add_message(self.session_id, "user", prompt)

        while True:
            response = ollama.chat(
                model=self.model_name,
                messages=self.history,
                tools=self.memory_tool.get_tools(),
                think=True,
                stream=True
            )

            chunks = []
            tool_calls = []
            content = ""

            for chunk in response:
                chunks.append(chunk)

                if chunk.message.content:
                    content += chunk.message.content

                if chunk.message.tool_calls:
                    tool_calls.extend(chunk.message.tool_calls)

            if not tool_calls:
                return iter(chunks)

            # Store the assistant's tool call in conversation history
            self.history.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls
            })
            self.chat_history.add_message(self.session_id, "assistant", content, tool_calls)

            # Execute requested tools
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                arguments = tool_call.function.arguments

                function = self.memory_tool.functions.get(tool_name)

                if function is None:
                    result = f"Unknown tool: {tool_name}"
                else:
                    result = function(**arguments)

                self.history.append({
                    "role": "tool",
                    "content": str(result)
                })
                self.chat_history.add_message(self.session_id, "tool", str(result))

    def add_response(self, content: str):
        self.history.append({"role": "assistant", "content": content})
        self.chat_history.add_message(self.session_id, "assistant", content)

    def switch_session(self, session_id: str) -> bool:
        """Switch to a different session. Returns True if successful."""
        if not self.chat_history.session_exists(session_id):
            return False
        
        self.session_id = session_id
        history = self.chat_history.get_history(self.session_id)
        if not history:
            with open("./config/identity.txt") as f:
                system_prompt = f.read().strip()
            self.history = [{"role": "system", "content": system_prompt}]
            self.chat_history.add_message(self.session_id, "system", system_prompt)
        else:
            self.history = history
        return True

    def new_session(self) -> str:
        """Create and switch to a new session. Returns the new session_id."""
        self.session_id = self.chat_history.create_session()
        with open("./config/identity.txt") as f:
            system_prompt = f.read().strip()
        self.history = [{"role": "system", "content": system_prompt}]
        self.chat_history.add_message(self.session_id, "system", system_prompt)
        return self.session_id

    def resume_last_session(self) -> bool:
        """Resume the most recent session. Returns True if successful."""
        latest_session = self.chat_history.get_latest_session_id()
        if latest_session:
            return self.switch_session(latest_session)
        return False

    def list_sessions(self, limit: int = 20) -> list:
        """List available sessions."""
        return self.chat_history.list_sessions(limit)

    def list_sessions_with_preview(self, limit: int = 20) -> list:
        """List available sessions with preview."""
        return self.chat_history.list_sessions_with_preview(limit)

    def switch_session_by_index(self, index: int) -> bool:
        """Switch to a session by index (0 = most recent). Returns True if successful."""
        session_id = self.chat_history.get_session_id_by_index(index)
        if session_id:
            return self.switch_session(session_id)
        return False

    def delete_session(self, session_id: str) -> bool:
        """Delete a session by ID."""
        return self.chat_history.delete_session(session_id)

    def delete_session_by_index(self, index: int) -> bool:
        """Delete a session by index (0 = most recent)."""
        session_id = self.chat_history.get_session_id_by_index(index)
        if session_id:
            return self.chat_history.delete_session(session_id)
        return False

    def clear_all_sessions(self) -> int:
        """Clear all sessions. Returns number of deleted sessions."""
        return self.chat_history.delete_all_sessions()

    def close(self):
        self.chat_history.close()