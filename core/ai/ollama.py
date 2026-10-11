import ollama
from typing import List

from tools.tool_registry import get_tool_registry
from memory.chat_history import ChatHistory
from utils.colors import (
    Colors, error, success, warning, info, title, dim, user_msg, important, secondary, bold
)


class OllamaModel:
    def __init__(self, model_name: str, session_id: str = None):
        self.model_name = model_name
        self.chat_history = ChatHistory()
        
        # Initialize tool registry (manages all tools and filtering)
        self.tool_registry = get_tool_registry()
        
        # Keep reference to all functions for execution
        self.all_functions = self.tool_registry.get_all_functions()
        
        try:
            self.session_id = session_id or self.chat_history.create_session()
        except Exception as e:
            raise RuntimeError(f"Failed to initialize session: {e}") from e
        
        # Load existing history or initialize with system prompt
        try:
            history = self.chat_history.get_history(self.session_id)
            if not history:
                system_prompt = self._load_system_prompt()
                self.history = [{"role": "system", "content": system_prompt}]
                self.chat_history.add_message(self.session_id, "system", system_prompt)
            else:
                self.history = history
        except Exception as e:
            # Fallback to minimal history if loading fails
            print(warning(f"Warning: Failed to load history, starting fresh: {e}"))
            system_prompt = self._load_system_prompt()
            self.history = [{"role": "system", "content": system_prompt}]
            try:
                self.chat_history.add_message(self.session_id, "system", system_prompt)
            except Exception:
                pass

    def _load_system_prompt(self) -> str:
        """Load system prompt from config file with fallback."""
        try:
            with open("./config/identity.txt") as f:
                return f.read().strip()
        except FileNotFoundError:
            return "You are ASTRA, an AI academic assistant."
        except Exception as e:
            print(warning(f"Warning: Could not load identity.txt: {e}"))
            return "You are ASTRA, an AI academic assistant."

    def _get_tools_for_query(self, prompt: str) -> List[Dict[str, Any]]:
        """Get filtered tool schemas relevant to the user's query."""
        return self.tool_registry.get_filtered_schemas(prompt)

    def generate(self, prompt: str, on_event=None):
        """Generate a response from the model with tool calling support.

        ``on_event`` is an optional callback used by embedders (such as the
        astra-web wrapper) to observe what the agent is doing while it works.
        It receives plain, JSON-serializable dicts, for example::

            {"type": "tool_call",   "name": "web_search", "arguments": {...}}
            {"type": "tool_result", "name": "web_search", "success": True,
             "result": "..."}

        The terminal application does not pass it, so its behaviour is
        completely unchanged.
        """
        if not prompt or not prompt.strip():
            return iter([])

        def emit(event: dict):
            if on_event is None:
                return
            try:
                on_event(event)
            except Exception as e:
                print(warning(f"Warning: event callback failed: {e}"))

        try:
            self.history.append({"role": "user", "content": prompt})
            self.chat_history.add_message(self.session_id, "user", prompt)
        except Exception as e:
            print(warning(f"Warning: Failed to save user message: {e}"))

        # Get relevant tools for this query
        relevant_tools = self._get_tools_for_query(prompt)

        while True:
            try:
                response = ollama.chat(
                    model=self.model_name,
                    messages=self.history,
                    tools=relevant_tools,
                    think=True,
                    stream=True
                )
            except ollama.ResponseError as e:
                yield self._error_chunk(f"Model error: {e.error}")
                return
            except ConnectionError as e:
                yield self._error_chunk(f"Cannot connect to Ollama. Is it running? ({e})")
                return
            except Exception as e:
                yield self._error_chunk(f"Unexpected error calling model: {e}")
                return

            tool_calls = []
            content = ""

            try:
                for chunk in response:
                    if chunk.message.content:
                        content += chunk.message.content

                    if chunk.message.tool_calls:
                        tool_calls.extend(chunk.message.tool_calls)

                    # Stream every chunk straight through so the terminal app and
                    # embedders see tokens as they are produced, not only once the
                    # whole response is finished.
                    yield chunk
            except Exception as e:
                yield self._error_chunk(f"Error reading response stream: {e}")
                return

            if not tool_calls:
                # Persist the assistant's final answer. The core owns
                # conversation persistence, so the terminal app and the web
                # wrapper stay consistent.
                try:
                    self.history.append({"role": "assistant", "content": content})
                    self.chat_history.add_message(self.session_id, "assistant", content)
                except Exception as e:
                    print(warning(f"Warning: Failed to save assistant response: {e}"))
                return

            # Convert tool_calls to serializable dicts
            serializable_tool_calls = []
            for tc in tool_calls:
                serializable_tool_calls.append({
                    "id": tc.id if hasattr(tc, 'id') else None,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                })

            # Store the assistant's tool call in conversation history
            try:
                self.history.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": serializable_tool_calls
                })
                self.chat_history.add_message(self.session_id, "assistant", content, serializable_tool_calls)
            except Exception as e:
                print(warning(f"Warning: Failed to save assistant tool call: {e}"))

            # Execute requested tools
            for tool_call in tool_calls:
                tool_name = getattr(tool_call.function, "name", "unknown")
                arguments = getattr(tool_call.function, "arguments", {}) or {}
                emit({"type": "tool_call", "name": tool_name, "arguments": arguments})
                try:
                    function = self.all_functions.get(tool_name)

                    if function is None:
                        result = f"Unknown tool: {tool_name}"
                        emit({
                            "type": "tool_result",
                            "name": tool_name,
                            "success": False,
                            "result": result,
                        })
                    else:
                        result = function(**arguments)
                        emit({
                            "type": "tool_result",
                            "name": tool_name,
                            "success": True,
                            "result": str(result),
                        })

                    self.history.append({
                        "role": "tool",
                        "content": str(result)
                    })
                    self.chat_history.add_message(self.session_id, "tool", str(result))
                except Exception as e:
                    error_msg = f"Tool execution failed: {e}"
                    print(warning(f"  {error_msg}"))
                    emit({
                        "type": "tool_result",
                        "name": tool_name,
                        "success": False,
                        "result": error_msg,
                    })
                    self.history.append({
                        "role": "tool",
                        "content": error_msg
                    })
                    try:
                        self.chat_history.add_message(self.session_id, "tool", error_msg)
                    except Exception:
                        pass

    def _error_chunk(self, message: str):
        """Create a mock chunk with error message for streaming."""
        class ErrorChunk:
            class Message:
                content = ""
                thinking = ""
            message = Message()
            message.content = message
        return ErrorChunk()

    def add_response(self, content: str):
        """Add assistant response to history."""
        if not content:
            return
        try:
            self.history.append({"role": "assistant", "content": content})
            self.chat_history.add_message(self.session_id, "assistant", content)
        except Exception as e:
            print(warning(f"Warning: Failed to save assistant response: {e}"))

    def switch_session(self, session_id: str) -> bool:
        """Switch to a different session. Returns True if successful."""
        try:
            if not self.chat_history.session_exists(session_id):
                return False
            
            self.session_id = session_id
            history = self.chat_history.get_history(self.session_id)
            if not history:
                system_prompt = self._load_system_prompt()
                self.history = [{"role": "system", "content": system_prompt}]
                self.chat_history.add_message(self.session_id, "system", system_prompt)
            else:
                self.history = history
            return True
        except Exception as e:
            print(error(f"Failed to switch session: {e}"))
            return False

    def new_session(self) -> str:
        """Create and switch to a new session. Returns the new session_id."""
        try:
            self.session_id = self.chat_history.create_session()
            system_prompt = self._load_system_prompt()
            self.history = [{"role": "system", "content": system_prompt}]
            self.chat_history.add_message(self.session_id, "system", system_prompt)
            return self.session_id
        except Exception as e:
            raise RuntimeError(f"Failed to create new session: {e}") from e

    def resume_last_session(self) -> bool:
        """Resume the most recent session. Returns True if successful."""
        try:
            latest_session = self.chat_history.get_latest_session_id()
            if latest_session:
                return self.switch_session(latest_session)
            return False
        except Exception as e:
            print(error(f"Failed to resume session: {e}"))
            return False

    def list_sessions(self, limit: int = 20) -> list:
        """List available sessions."""
        try:
            return self.chat_history.list_sessions(limit)
        except Exception as e:
            print(error(f"Failed to list sessions: {e}"))
            return []

    def list_sessions_with_preview(self, limit: int = 20) -> list:
        """List available sessions with preview."""
        try:
            return self.chat_history.list_sessions_with_preview(limit)
        except Exception as e:
            print(error(f"Failed to list sessions with preview: {e}"))
            return []

    def switch_session_by_index(self, index: int) -> bool:
        """Switch to a session by index (0 = most recent). Returns True if successful."""
        try:
            if index < 0:
                return False
            session_id = self.chat_history.get_session_id_by_index(index)
            if session_id:
                return self.switch_session(session_id)
            return False
        except Exception as e:
            print(error(f"Failed to switch session by index: {e}"))
            return False

    def delete_session(self, session_id: str) -> bool:
        """Delete a session by ID."""
        try:
            return self.chat_history.delete_session(session_id)
        except Exception as e:
            print(error(f"Failed to delete session: {e}"))
            return False

    def delete_session_by_index(self, index: int) -> bool:
        """Delete a session by index (0 = most recent)."""
        try:
            if index < 0:
                return False
            session_id = self.chat_history.get_session_id_by_index(index)
            if session_id:
                return self.chat_history.delete_session(session_id)
            return False
        except Exception as e:
            print(error(f"Failed to delete session by index: {e}"))
            return False

    def clear_all_sessions(self) -> int:
        """Clear all sessions. Returns number of deleted sessions."""
        try:
            return self.chat_history.delete_all_sessions()
        except Exception as e:
            print(error(f"Failed to clear sessions: {e}"))
            return 0

    def close(self):
        """Close database connections."""
        try:
            self.chat_history.close()
        except Exception:
            pass