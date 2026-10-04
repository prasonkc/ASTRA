# ASTRA Project - TODO & Implementation Guide

## Project Overview
ASTRA is a local AI academic assistant with memory capabilities, powered by Ollama models. The project uses a modular architecture with separate components for chat, memory, tools, and model integration.

---

## Current Architecture

```
core/
├── main.py                 # Entry point
├── agent/
│   └── chat.py             # Chat loop handler
├── ai/
│   └── ollama.py           # Ollama integration with tool calling
├── model/
│   └── ollama_model.py     # Legacy model wrapper (simulated)
├── memory/
│   ├── memory.py           # SQLite-based memory store
│   └── astra.db            # SQLite database file
├── tools/
│   └── memory_tool.py      # Memory tool with function calling schema
└── config/
    └── identity.txt        # System prompt / identity
```

---

## 1. Chat History Implementation

### Current State ✅
- **In-memory history**: Stored in `OllamaModel.history` as a list of message dicts
- **Structure**: `[{role, content}, ...]` with roles: `system`, `user`, `assistant`, `tool`
- **Tool calls**: Assistant messages include `tool_calls` field when tools are invoked
- **Persistence**: ❌ Not persisted across sessions (lost on restart)

### Implementation Options for Persistent Chat History

#### Option A: SQLite Database (Recommended)
```python
# New file: memory/chat_history.py
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any

class ChatHistory:
    def __init__(self, db_path="./memory/chat_history.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_schema()
    
    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                title TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                tool_calls TEXT,  -- JSON serialized
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
        """)
        self.conn.commit()
    
    def start_session(self, title: str = None) -> str:
        session_id = f"session_{datetime.now().isoformat()}"
        self.conn.execute(
            "INSERT INTO conversations (session_id, title) VALUES (?, ?)",
            (session_id, title or "New Conversation")
        )
        self.conn.commit()
        return session_id
    
    def add_message(self, session_id: str, role: str, content: str, tool_calls: List[Dict] = None):
        cursor = self.conn.execute(
            "SELECT id FROM conversations WHERE session_id = ?", (session_id,)
        )
        conv_id = cursor.fetchone()[0]
        
        self.conn.execute(
            """INSERT INTO messages (conversation_id, role, content, tool_calls)
               VALUES (?, ?, ?, ?)""",
            (conv_id, role, content, json.dumps(tool_calls) if tool_calls else None)
        )
        self.conn.commit()
    
    def get_history(self, session_id: str, limit: int = 50) -> List[Dict]:
        cursor = self.conn.execute("""
            SELECT role, content, tool_calls FROM messages
            WHERE conversation_id = (SELECT id FROM conversations WHERE session_id = ?)
            ORDER BY created_at DESC LIMIT ?
        """, (session_id, limit))
        
        messages = []
        for row in cursor.fetchall():
            msg = {"role": row[0], "content": row[1]}
            if row[2]:
                msg["tool_calls"] = json.loads(row[2])
            messages.append(msg)
        return list(reversed(messages))
    
    def list_sessions(self, limit: int = 20) -> List[Dict]:
        cursor = self.conn.execute("""
            SELECT session_id, title, created_at FROM conversations
            ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        return [{"session_id": r[0], "title": r[1], "created_at": r[2]} for r in cursor.fetchall()]
```

#### Integration with OllamaModel
```python
# In ai/ollama.py
from memory.chat_history import ChatHistory

class OllamaModel:
    def __init__(self, model_name, session_id=None):
        self.model_name = model_name
        self.memory_tool = MemoryTool()
        self.chat_history = ChatHistory()
        
        self.session_id = session_id or self.chat_history.start_session()
        
        # Load existing history or initialize with system prompt
        history = self.chat_history.get_history(self.session_id)
        if not history:
            with open("./config/identity.txt") as f:
                system_prompt = f.read().strip()
            self.history = [{"role": "system", "content": system_prompt}]
        else:
            self.history = history
    
    def generate(self, prompt):
        self.history.append({"role": "user", "content": prompt})
        self.chat_history.add_message(self.session_id, "user", prompt)
        
        # ... existing tool calling logic ...
        
        # After generating response:
        self.chat_history.add_message(self.session_id, "assistant", content, tool_calls)
```

#### Option B: JSONL File (Simpler, No Dependencies)
```python
# Simpler file-based approach
import json
from pathlib import Path

class JSONLChatHistory:
    def __init__(self, path="./memory/chat_history.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
    
    def append(self, session_id: str, message: Dict):
        record = {"session_id": session_id, **message, "timestamp": datetime.now().isoformat()}
        with open(self.path, "a") as f:
            f.write(json.dumps(record) + "\n")
    
    def load_session(self, session_id: str) -> List[Dict]:
        messages = []
        if self.path.exists():
            with open(self.path) as f:
                for line in f:
                    record = json.loads(line)
                    if record["session_id"] == session_id:
                        msg = {k: v for k, v in record.items() 
                               if k not in ["session_id", "timestamp"]}
                        messages.append(msg)
        return messages
```

---

## 2. Tool Calling Implementation

### Current State ✅
- **Tool definitions**: Defined in `MemoryTool.get_tools()` returning OpenAI-compatible function schemas
- **Tool execution**: Handled in `OllamaModel.generate()` loop
- **Available tools**: `memory_remember`, `memory_search`, `memory_forget`
- **Streaming support**: ✅ Works with `stream=True`
- **Multi-step tool calls**: ✅ Loop continues until no tool calls returned

### Current Flow (in `ai/ollama.py`)
```python
def generate(self, prompt):
    self.history.append({"role": "user", "content": prompt})
    
    while True:  # Loop for multi-step tool calls
        response = ollama.chat(
            model=self.model_name,
            messages=self.history,
            tools=self.memory_tool.get_tools(),
            think=True,
            stream=True
        )
        
        # Collect streamed chunks
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
            return iter(chunks)  # Return stream for UI
        
        # Store assistant's tool call in history
        self.history.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls
        })
        
        # Execute each tool
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            arguments = tool_call.function.arguments
            function = self.memory_tool.functions.get(tool_name)
            
            result = function(**arguments) if function else f"Unknown tool: {tool_name}"
            
            # Add tool result to history
            self.history.append({
                "role": "tool",
                "content": str(result)
            })
```

### Adding New Tools

#### Step 1: Create Tool Module
```python
# tools/web_search_tool.py
import requests
from typing import Dict, Any

class WebSearchTool:
    def __init__(self, api_key: str = None):
        self.api_key = api_key
    
    def search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        # Implement search logic (DuckDuckGo, Google, Brave, etc.)
        pass
    
    def get_tools(self):
        return [{
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for current information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "default": 5}
                    },
                    "required": ["query"]
                }
            }
        }]
    
    @property
    def functions(self):
        return {"web_search": self.search}
```

#### Step 2: Register in OllamaModel
```python
# In ai/ollama.py
from tools.memory_tool import MemoryTool
from tools.web_search_tool import WebSearchTool

class OllamaModel:
    def __init__(self, model_name):
        self.model_name = model_name
        self.tools = {
            "memory": MemoryTool(),
            "web": WebSearchTool()
        }
        
        # Combine all tool schemas
        self.all_tool_schemas = []
        for tool in self.tools.values():
            self.all_tool_schemas.extend(tool.get_tools())
        
        # Combine all executable functions
        self.all_functions = {}
        for tool in self.tools.values():
            self.all_functions.update(tool.functions)
    
    def generate(self, prompt):
        # ... use self.all_tool_schemas and self.all_functions ...
```

### Tool Calling Best Practices

| Aspect | Recommendation |
|--------|----------------|
| **Schema design** | Use clear descriptions, enum for constrained values, required fields |
| **Error handling** | Return structured error objects, not exceptions |
| **Result formatting** | Return JSON-serializable dicts, not raw strings |
| **Timeouts** | Add timeout to external API calls |
| **Rate limiting** | Implement token bucket or similar for external APIs |
| **Parallel calls** | Ollama supports multiple tool calls per turn - handle all |

---

## 3. Immediate TODOs

### High Priority
- [x] **Persist chat history** to SQLite (Option A above) - DONE
- [x] **Add session management** CLI commands - DONE (enhanced with index-based switching, previews, delete, clear)
- [ ] **Fix memory retrieval issue** noted in progress.md - investigate why memory search doesn't return content without explicit category
- [ ] **Add tool result truncation** for very large results (token limit protection)

### Medium Priority
- [ ] **Add web search tool** for current information
- [ ] **Add file read/write tools** for code/project assistance
- [ ] **Add academic paper search** (Semantic Scholar, arXiv APIs)
- [ ] **Improve system prompt** with few-shot examples for tool usage
- [ ] **Add conversation titles** auto-generated from first exchange

### Low Priority / Nice to Have
- [ ] **Vector embeddings** for semantic memory search (replace LIKE queries)
- [ ] **Conversation branching** (fork from any message)
- [ ] **Export/import conversations** (JSON, Markdown)
- [ ] **Token usage tracking** per session
- [ ] **Streaming tool call display** in UI (show "searching..." indicator)

---

## 4. Known Issues & Debugging

### Memory Search Not Working (from progress.md)
**Symptom**: Agent can't retrieve memory contents unless explicitly given category/content
**Possible causes**:
1. `LIKE` query in `memory.py:35` requires wildcards - but they're added in Python
2. Schema mismatch between models (different embedding/tokenization?)
3. Tool schema description not clear enough for model to use correctly

**Debug steps**:
```python
# Test memory search directly
from tools.memory_tool import MemoryTool
tool = MemoryTool()
print(tool.search("test"))  # Should return results
print(tool.functions["memory_search"](query="test"))  # Via function interface
```

### Model Switching Issues
- Different models may have different tool calling capabilities
- Qwen3 supports `think=True` and native tool calling
- Other models may need different prompting strategies

---

## 5. Development Commands

```bash
# Run the chat
cd /mnt/data/Projects/ASTRA/core
python main.py

# Test memory tool directly
python -c "from tools.memory_tool import MemoryTool; t=MemoryTool(); print(t.search('test'))"

# Test Ollama model directly
python -c "from ai.ollama import OllamaModel; m=OllamaModel('qwen3:8b'); print(list(m.generate('hello')))"

# Check database
sqlite3 memory/astra.db ".schema"
sqlite3 memory/astra.db "SELECT * FROM memories;"
```

---

## 6. Future Architecture Considerations

### Plugin System for Tools
```python
# tools/registry.py
class ToolRegistry:
    def __init__(self):
        self.tools = {}
    
    def register(self, name: str, tool_instance):
        self.tools[name] = tool_instance
    
    def get_all_schemas(self):
        schemas = []
        for tool in self.tools.values():
            schemas.extend(tool.get_tools())
        return schemas
    
    def get_all_functions(self):
        funcs = {}
        for tool in self.tools.values():
            funcs.update(tool.functions)
        return funcs
```

### Multi-Model Support
```python
# Support different providers (Ollama, OpenAI, Anthropic, etc.)
class ModelProvider:
    def chat(self, messages, tools, stream): ...
    
class OllamaProvider(ModelProvider): ...
class OpenAIProvider(ModelProvider): ...
```

---

## 7. Testing Checklist

When adding features, verify:
- [x] Chat history persists across restarts
- [ ] Tool calls execute correctly and results feed back to model
- [ ] Multi-step tool calls work (tool → result → another tool → final answer)
- [ ] Streaming output still works with tool calls
- [ ] Memory tool search/retrieve works end-to-end
- [x] Session management CLI commands work
- [x] Session controller modular and testable
- [ ] No memory leaks in long conversations
- [ ] Token limits handled gracefully (truncation/summarization)

---

*Last updated: $(date)*
*Project: ASTRA Core*

---

## 8. Implementation Summary - Persistent Chat History (Completed)

### Files Created/Modified

| File | Description |
|------|-------------|
| `memory/chat_history.py` | New SQLite-based chat history persistence layer |
| `ai/ollama.py` | Updated to use ChatHistory, added session management methods |
| `agent/chat.py` | Main chat loop, uses SessionController |
| `agent/session_controller.py` | Session command handling (modular) |

### Features Implemented

1. **SQLite Persistence** (`memory/chat_history.py`):
   - `conversations` table: session_id (unique), title, created_at, updated_at
   - `messages` table: conversation_id (FK), role, content, tool_calls (JSON), created_at
   - Index on messages.conversation_id for fast lookups
   - UUID-based session IDs for uniqueness

2. **Session Management** (`ai/ollama.py`):
   - `new_session()` - Create and switch to new session
   - `switch_session(session_id)` - Switch to existing session
   - `resume_last_session()` - Resume most recent session
   - `list_sessions(limit)` - List all sessions with metadata
   - Automatic history loading on session switch

3. **Session Controller** (`agent/session_controller.py`):
   - Modular command handling separated from main chat loop
   - Clean command dispatch pattern with aliases
   - Confirmation prompts for destructive actions

4. **CLI Commands** (`agent/chat.py`):
   - `/session new` - Create new chat session
   - `/session resume` - Resume last session
   - `/session list` - List all sessions (shows current with *)
   - `/session switch <id>` - Switch to specific session

### Usage Example

```
You: /session list
Available sessions:
  0: session_abc123 *     <- current
      Title: Conversation 2026-10-04 19:05
      Created: 2026-10-04 19:05:23
      Updated: 2026-10-04 19:05:23

  1: session_def456
      Title: Conversation 2026-10-04 18:30
      Created: 2026-10-04 18:30:12
      Updated: 2026-10-04 18:45:01

You: /session switch session_def456
Switched to session: session_def456
Session has 12 messages

You: /session new
Created new session: session_ghi789

You: /session resume
Resumed session: session_ghi789
Session has 1 messages
```

### Database Schema

```sql
CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    title TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX idx_messages_conversation_id ON messages(conversation_id);
```

---

## 9. Enhanced Session Management (v2 - Completed)

### New Features

| Feature | Command | Description |
|---------|---------|-------------|
| **Number-based switching** | `/s 0`, `/s 1` | Switch by index from list (0 = most recent) |
| **Session preview** | `/s list`, `/s preview` | See conversation snippets without switching |
| **Delete single session** | `/s del <num>` | Delete with confirmation |
| **Clear all sessions** | `/s clear` | Nuclear option with double confirmation |
| **Shorthand alias** | `/s` instead of `/session` | Faster typing |
| **Quick switch** | Just type the number | `/s 2` == `/s switch 2` |

### Improved UI

```
/s list
──────────────────────────────────────────────────────────────
 ► [0] Conversation 2026-10-04 19:10
      5 messages  •  2026-10-04 19:10:23
      💬 user: How do I learn Python?

  [1] Conversation 2026-10-04 18:30
      3 messages  •  2026-10-04 18:45:01
      💬 user: What is machine learning?
──────────────────────────────────────────────────────────────
Use '/s <number>' to switch, '/s del <number>' to delete
```

### Command Reference

```
/s new              Create new session (auto-switches)
/s list             List all sessions with previews
/s <number>         Quick switch to session by number
/s switch <number>  Switch to session by number  
/s resume           Resume most recent session
/s del <number>     Delete a session (with confirmation)
/s clear            Delete ALL sessions (with confirmation)
/s preview [num]    Show conversation preview (default: current)
/s help             Show this help
```

---

## 10. Architecture Refactoring (Completed)

### Modular Structure

```
agent/
├── chat.py                 # Main chat loop (clean, minimal)
├── session_controller.py   # Session command handling (separate module)
```

### Benefits

- **Separation of concerns**: Chat loop handles streaming/display; SessionController handles session logic
- **Testability**: SessionController can be unit tested independently
- **Maintainability**: Session commands in one place, easy to extend
- **Reusability**: SessionController can be used by other interfaces (Web UI, API, etc.)

### Dependency Flow

```
main.py
    └── agent/chat.py (Chat)
            ├── ai/ollama.py (OllamaModel)
            │       └── memory/chat_history.py (ChatHistory)
            └── agent/session_controller.py (SessionController)
                    └── ai/ollama.py (OllamaModel) - for session operations
```