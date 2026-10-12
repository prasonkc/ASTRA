# ASTRA Architecture: Chat History & Session Management

## Overview

This document describes the persistent chat history and session management system implemented in ASTRA. The system provides SQLite-based conversation persistence with multi-session support, allowing users to create, switch, preview, and delete chat sessions.

---

## System Components

### 1. ChatHistory (`memory/chat_history.py`)

**Purpose:** Low-level SQLite database operations for conversation persistence.

**Database Schema:**

```sql
-- Conversations table
CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,      -- UUID-based identifier
    title TEXT,                           -- Human-readable title
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Messages table
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,     -- FK to conversations
    role TEXT NOT NULL,                   -- 'system', 'user', 'assistant', 'tool'
    content TEXT,                         -- Message content
    tool_calls TEXT,                      -- JSON-serialized tool calls (for assistant messages)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

-- Index for fast message lookups
CREATE INDEX idx_messages_conversation_id ON messages(conversation_id);
```

**Key Methods:**

| Method | Description |
|--------|-------------|
| `create_session(title?)` | Creates new session, returns session_id |
| `get_session_id_by_index(index)` | Gets session_id by recency (0 = latest) |
| `get_latest_session_id()` | Returns most recent session_id |
| `session_exists(session_id)` | Checks if session exists |
| `add_message(session_id, role, content, tool_calls?)` | Persists a message |
| `get_history(session_id, limit?)` | Loads conversation history (oldest first) |
| `list_sessions(limit?)` | Lists sessions with metadata |
| `list_sessions_with_preview(limit?)` | Lists sessions with message count + preview |
| `get_session_preview(session_id, max_messages?)` | Returns last N user/assistant messages as text |
| `delete_session(session_id)` | Deletes session and all messages (CASCADE) |
| `delete_all_sessions()` | Deletes all sessions, returns count |
| `get_message_count(session_id)` | Returns message count for session |
| `update_session_title(session_id, title)` | Updates session title |
| `close()` | Closes database connection |

**Error Handling:**
- All DB operations wrapped in try/except
- Returns sensible defaults (empty lists, False, None) on failure
- Logs warnings via `utils.colors.warning()` but never crashes
- SQLite timeout set to 30 seconds for concurrent access
- Corrupted JSON in `tool_calls` column handled gracefully

---

### 2. AgentModel Session Management (`ai/model.py`)

> Historical note: this class used to live in `ai/ollama.py` as `OllamaModel`.
> `ai/ollama.py` is now a thin backwards-compatibility shim that re-exports
> `AgentModel` as `OllamaModel`; new code should import from `ai.model`.

**Purpose:** High-level session management integrated with LLM conversation
history. `AgentModel` owns the agent loop (tool calling, streaming, persistence)
and delegates the actual model call to a swappable provider — local Ollama or a
cloud provider (OpenAI, Anthropic, Gemini). See §6.

**Session Lifecycle:**

```
┌─────────────────────────────────────────────────────────────┐
│                      AgentModel                             │
├─────────────────────────────────────────────────────────────┤
│  - provider_name: str           ← 'ollama'|'openai'|…       │
│  - model_name: str                                          │
│  - provider: Provider           ← backend for this provider │
│  - chat_history: ChatHistory                                │
│  - session_id: str                                          │
│  - history: List[Dict]          ← In-memory (OpenAI shape)  │
└─────────────────────────────────────────────────────────────┘
```

**Key Methods:**

| Method | Description |
|--------|-------------|
| `new_session()` | Creates new session, loads system prompt, returns session_id |
| `switch_session(session_id)` | Loads history from DB into `self.history` |
| `switch_session_by_index(index)` | Switches by recency index (0 = latest) |
| `resume_last_session()` | Convenience: switches to most recent |
| `list_sessions(limit)` | Delegates to ChatHistory |
| `list_sessions_with_preview(limit)` | Delegates to ChatHistory |
| `delete_session(session_id)` | Delegates to ChatHistory |
| `delete_session_by_index(index)` | Delegates to ChatHistory |
| `clear_all_sessions()` | Delegates to ChatHistory |
| `generate(prompt, on_event=None)` | Main generation loop with tool calling |
| `describe()` | Returns `{provider, provider_label, model, session_id, thinking}` |
| `thinking_enabled()` / `set_thinking(bool)` | Read/toggle reasoning for the active model |
| `reconfigure(provider, model)` | Switch provider/model without touching history |
| `close()` | Closes ChatHistory connection |

**History Synchronization:**

```python
# On session switch/create:
history = chat_history.get_history(session_id)
if not history:
    # New session: initialize with system prompt
    self.history = [{"role": "system", "content": system_prompt}]
    chat_history.add_message(session_id, "system", system_prompt)
else:
    # Existing session: load full history
    self.history = history

# On each user message:
self.history.append({"role": "user", "content": prompt})
chat_history.add_message(session_id, "user", prompt)

# On assistant response (after tool calls):
self.history.append({"role": "assistant", "content": content, "tool_calls": [...]})
chat_history.add_message(session_id, "assistant", content, tool_calls)

# On tool results:
self.history.append({"role": "tool", "content": str(result)})
chat_history.add_message(session_id, "tool", str(result))
```

**Error Handling:**
- File loading (`identity.txt`) has fallback default prompt
- Ollama connection errors caught and returned as error chunks
- Tool execution failures logged, conversation continues
- Database errors caught, operations return False/empty

---

### 3. SessionController (`agent/session_controller.py`)

**Purpose:** User-facing command handler for session operations. Modular, testable, separated from main chat loop.

**Command Interface:**

```
/s new                    # Create new session (auto-switches)
/s list                   # List all sessions with previews
/s <number>               # Quick switch by index (0 = latest)
/s switch <number>        # Explicit switch by index
/s resume                 # Resume most recent session
/s del <number>           # Delete session (with confirmation)
/s clear                  # Delete ALL sessions (type YES to confirm)
/s preview [number]       # Show conversation preview
/s help                   # Show help
```

**Command Dispatch Pattern:**

```python
handlers = {
    "new": self._cmd_new,
    "n": self._cmd_new,
    "list": self._cmd_list,
    "l": self._cmd_list,
    "switch": self._cmd_switch,
    "sw": self._cmd_switch,
    "s": self._cmd_switch,
    "use": self._cmd_switch,
    "u": self._cmd_switch,
    "resume": self._cmd_resume,
    "r": self._cmd_resume,
    "delete": self._cmd_delete,
    "del": self._cmd_delete,
    "rm": self._cmd_delete,
    "remove": self._cmd_delete,
    "d": self._cmd_delete,
    "clear": self._cmd_clear,
    "clr": self._cmd_clear,
    "purge": self._cmd_clear,
    "preview": self._cmd_preview,
    "p": self._cmd_preview,
    "show": self._cmd_preview,
    "info": self._cmd_preview,
    "help": self._print_help,
    "h": self._print_help,
    "?": self._print_help,
}
```

**Features:**
- Number-based switching (no UUID memorization)
- Session previews in list view (last user/assistant message)
- Current session marked with `>` indicator
- Confirmation prompts for destructive operations
- EOF/KeyboardInterrupt handling
- All errors caught and displayed with color coding

---

### 4. Chat Loop (`agent/chat.py`)

**Purpose:** Main REPL loop, delegates session commands to SessionController.

**Flow:**

```python
while True:
    user_input = input("You: ")
    
    if user_input == "exit": break
    if user_input == "": continue
    
    # Session commands
    if user_input.startswith("/session") or user_input.startswith("/s "):
        session_controller.handle(user_input)
        continue
    
    # Normal chat
    response_stream = model.generate(user_input)
    # ... stream response ...
    model.add_response(content)
```

**Error Handling:**
- Main loop wrapped in try/except
- Streaming errors caught per-chunk
- Cleanup on exit (`model.close()`)
- Ctrl+C handled gracefully (shows "Interrupted", continues)

---

### 5. Color System (`utils/colors.py`)

**Purpose:** ANSI color codes for consistent terminal output.

**Color Mapping:**

| Semantic | Color | Use Case |
|----------|-------|----------|
| `error()` | Red (91m) | Failures, invalid input |
| `success()` | Green (92m) | Successful operations |
| `warning()` | Yellow (93m) | Cautions, confirmations |
| `info()` | Blue (94m) | Neutral information |
| `title()` | Brown (33m) | Section headers, important info |
| `dim()` | Grey (90m) | Secondary text, dividers |
| `user_msg()` | Grey (90m) | User-facing messages |
| `important()` | Magenta (95m) | Highlights |
| `secondary()` | Cyan (96m) | Auxiliary info |
| `bold()` | Bold (1m) | Emphasis |

**Helper Functions:**
```python
def error(text): return f"{Colors.RED}{text}{Colors.RESET}"
def success(text): return f"{Colors.GREEN}{text}{Colors.RESET}"
def warning(text): return f"{Colors.YELLOW}{text}{Colors.RESET}"
# ... etc
```

### 6. Provider & Model Configuration (`ai/settings.py`, `ai/providers/`)

**Purpose:** Make ASTRA model- and provider-agnostic. The agent loop only ever
talks to a normalized `Provider`, so adding a backend never touches the loop.

**Layout:**

```
ai/
├── settings.py         # provider/model/API-key config + env precedence
├── model.py            # AgentModel — the agent loop (backend-agnostic)
├── local_setup.py      # install Ollama + list/download models (best effort)
├── ollama.py           # backwards-compat shim (OllamaModel = AgentModel)
└── providers/
    ├── base.py         # Provider, Chunk, ToolCall, ProviderError, SSE helper
    ├── ollama_provider.py
    ├── openai_provider.py
    ├── anthropic_provider.py
    ├── gemini_provider.py
    └── __init__.py     # get_provider(name) factory
```

**How a call flows:**

```
AgentModel.generate()
   └─ provider.stream_chat(model, messages, tools, think)
          └─ yields normalized Chunk(message=ResponseMessage(
                 content, thinking, tool_calls[ToolCall]))     ◀── same shape
                                                                   for every backend
```

Each provider translates the internal OpenAI-flavored `self.history` into its own
wire format at call time (tool calls and results are paired by order; tool-call
ids are preserved across reloads, synthesizing one when a backend doesn't supply
it). This keeps history storage portable while letting each API use its native
protocol.

**Configuration precedence** (highest first):

1. `ASTRA_PROVIDER` / `ASTRA_MODEL` / `ASTRA_THINKING` and per-provider
   `*_API_KEY` / `*_BASE_URL` environment variables,
2. `core/config/settings.json` (written by `/provider` / the web Settings panel;
   git-ignored, mode `600`),
3. built-in defaults (`ollama`, `qwen3:14b`, thinking on).

`Settings.to_public()` returns a snapshot with API keys **masked**, which is what
the web UI and `/provider status` display — the raw key never leaves the process.

**Commands:**

```
/provider                 Interactive provider setup menu
/provider status          Show current provider/model (+ key source)
/provider local           Pick an installed Ollama model
/provider local_setup     Install Ollama (if needed) and download a model
/provider openai          Add an OpenAI key (also: /provider gpt)
/provider anthropic       Add an Anthropic (Claude) key
/provider gemini          Add a Google (Gemini) key
/provider set <p> [model] Set the active provider (and model) directly
/model [name]             Show or switch the model for the current provider
/thinking [on|off|toggle] Toggle reasoning for the active model
```

---

## Data Flow Diagram

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   User      │────▶│  Chat Loop       │────▶│ SessionController│
│   Input     │     │  (agent/chat.py) │     │                 │
└─────────────┘     └────────┬─────────┘     └────────┬────────┘
                             │                        │
                    ┌────────▼────────┐     ┌─────────▼────────┐
                    │  Session Cmd?   │────▶│  AgentModel      │
                    │  (starts with   │     │  Session Methods │
                    │   /s or /session)     │                  │
                    └────────┬────────┘     └────────┬─────────┘
                             │                       │
                    ┌────────▼────────┐     ┌─────────▼────────┐
                    │  Normal Chat    │     │  ChatHistory     │
                    │  model.generate()│    │  (SQLite)        │
                    └────────┬────────┘     └────────┬─────────┘
                             │                       │
                    ┌────────▼────────┐              │
                    │  Provider       │              │
                    │  (streaming)    │              │
                    │  ollama · openai│              │
                    │  claude · gemini│              │
                    └─────────────────┘              │
                                                     │
                    ┌────────────────────────────────┘
                    │
                    ▼
            ┌───────────────┐
            │ SQLite Database │
            │ chat_history.db │
            └───────────────┘
```

---

## Session Persistence Details

### Message Format in Database

```json
// User message
{"role": "user", "content": "Hello", "tool_calls": null}

// Assistant message (with tool calls)
{"role": "assistant", "content": "I'll search for that", "tool_calls": [
    {"function": {"name": "memory_search", "arguments": {"query": "test"}}}
]}

// Tool result message
{"role": "tool", "content": "[{'id': 1, 'category': 'test', ...}]", "tool_calls": null}
```

### History Loading

- Messages loaded in chronological order (ASC by `created_at`)
- `tool_calls` JSON parsed back to list of dicts
- Corrupted JSON → empty list (doesn't crash)
- Limit parameter (default 100) prevents memory issues

### Session Titles

- Auto-generated: `Conversation YYYY-MM-DD HH:MM`
- Can be updated via `update_session_title()`
- Displayed in list view for identification

---

## Configuration

**Database Paths:**
- Chat history: `./memory/chat_history.db` (override with `ASTRA_DB_PATH`)
- Long-term memory: `./memory/astra.db`

**Provider / Model:**
- Settings file: `./config/settings.json` (override with `ASTRA_SETTINGS_PATH`)
- See §6 for environment variables and precedence.

**Default Limits:**
- Session list: 20 sessions
- History load: 100 messages
- Preview: 3 messages

---

## Testing

Run tests manually:

```bash
# Test session controller
python -c "
from ai.model import AgentModel
from agent.session_controller import SessionController
model = AgentModel()
ctrl = SessionController(model)
ctrl.handle('/s list')
ctrl.handle('/s new')
ctrl.handle('/s 0')
ctrl.handle('/s preview')
ctrl.handle('/s del 0')  # requires 'y' input
ctrl.handle('/s clear')  # requires 'YES' input
model.close()
"

# Test persistence
python -c "
from ai.model import AgentModel
m1 = AgentModel()
sid = m1.session_id
m1.chat_history.add_message(sid, 'user', 'test')
m1.chat_history.add_message(sid, 'assistant', 'response')
m1.close()

# Simulate restart
m2 = AgentModel(session_id=sid)
print(len(m2.history))  # Should be 3 (system + user + assistant)
m2.close()
"

# Test provider switching (no API calls made by reconfigure)
python -c "
from ai.model import AgentModel
m = AgentModel()
print(m.describe())
m.reconfigure('openai', 'gpt-4o-mini')
print(m.describe())
m.close()
"
```

`OllamaModel` remains importable from `ai.ollama` for any older scripts.

---

## Error Handling Strategy

1. **Never crash the main loop** - All exceptions caught at command level
2. **Graceful degradation** - Failed DB ops return False/empty, chat continues
3. **Informative feedback** - Color-coded messages explain what happened
4. **Defensive validation** - Input validated before DB operations
5. **Resource cleanup** - Connections closed on exit/error

---

## Future Extensions

- **Auto-title generation** from first user message
- **Conversation branching** (fork from any message)
- **Export/import** (JSON, Markdown)
- **Search across sessions** (full-text search)
- **Token usage tracking** per session
- **Vector embeddings** for semantic session search