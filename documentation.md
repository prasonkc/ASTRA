# ASTRA — Technical Documentation

> **Audience:** engineers and AI agents who need to understand, run, extend or
> take over the ASTRA codebase.
>
> **Scope:** every tracked file, module, class and function, plus the
> architecture, configuration, data model, HTTP API and operational notes.
>
> **Related documents:** [`README.md`](README.md) (user-facing quick start),
> [`web/README.md`](web/README.md) (web wrapper),
> [`voice/README.md`](voice/README.md) (voice wrapper), and
> [`core/architecture.md`](core/architecture.md) (deep dive on sessions and
> history).

| Field | Value |
|-------|-------|
| Project | ASTRA — AI academic assistant |
| Entry points | `core/main.py` (terminal), `web/backend/run.py` (web), `voice/backend/run.py` (voice) |
| Runtime | Python 3.10+ (developed on 3.14) |
| Last updated | 2026-10-13 |
| License | See [`LICENSE`](LICENSE) |

---

## Table of contents

1. [Introduction](#1-introduction)
2. [High-level architecture](#2-high-level-architecture)
3. [Repository layout](#3-repository-layout)
4. [Getting started](#4-getting-started)
5. [Configuration & environment](#5-configuration--environment)
6. [Core AI subsystem (`core/ai/`)](#6-core-ai-subsystem)
7. [Agent & entry points](#7-agent--entry-points)
8. [Memory & persistence](#8-memory--persistence)
9. [Controllers & CLI commands](#9-controllers--cli-commands)
10. [Tool system](#10-tool-system)
11. [Web application](#11-web-application)
12. [Voice application](#12-voice-application)
13. [HTTP API reference](#13-http-api-reference)
14. [Frontend reference](#14-frontend-reference)
15. [Utilities & assets](#15-utilities--assets)
16. [Development guide](#16-development-guide)
17. [Data & file locations](#17-data--file-locations)
18. [Security & privacy](#18-security--privacy)
19. [Known limitations & technical debt](#19-known-limitations--technical-debt)
20. [Troubleshooting](#20-troubleshooting)
21. [Glossary](#21-glossary)

Appendices: [A. Environment variables](#appendix-a-environment-variables) ·
[B. Tool catalog](#appendix-b-tool-catalog) ·
[C. HTTP API](#appendix-c-http-api) ·
[D. Symbol index](#appendix-d-symbol-index)

---

## 1. Introduction

ASTRA is an AI **academic assistant**: a chat agent that can search the web,
read and produce documents, run shell commands and remember facts. It ships in
two forms that share one brain:

- a **standalone terminal application** (`core/`), and
- an optional **web wrapper** (`web/`) that runs the *same* core in a browser.

The single most important design property is that ASTRA is **model- and
provider-agnostic**. Nothing about the model is hard-coded. At startup the agent
asks its settings layer which backend to use, and talks only to a normalized
`Provider` interface. Four backends are supported:

| Provider id | Label | Default model | Auth |
|-------------|-------|---------------|------|
| `ollama` | Local (Ollama) | `qwen3:14b` | none (local) |
| `openai` | OpenAI | `gpt-4o-mini` | API key |
| `anthropic` | Anthropic (Claude) | `claude-3-5-sonnet-latest` | API key |
| `gemini` | Google (Gemini) | `gemini-2.0-flash` | API key |

### Design principles

1. **One brain, two shells.** The web layer contains *no agent logic*; it imports
   and drives the core. A change to the core is automatically reflected in both.
2. **Backend-agnostic agent loop.** `AgentModel.generate()` never talks to a
   vendor API directly; it consumes a stream of normalized `Chunk` objects.
3. **Portable history.** Conversation history is stored in a neutral,
   OpenAI-flavored shape; each provider translates it at call time.
4. **Configuration, not code.** Provider, model, keys, endpoints and the
   thinking flag are resolved from environment → settings file → defaults.
5. **Secrets stay local.** API keys live in a git-ignored `600` file and are only
   ever exposed masked.
6. **Single-threaded core.** The core (and its SQLite/Playwright components) is
   used on exactly one thread, so the web wrapper serializes everything onto one
   worker thread.

### Conventions used in this document

- Paths are relative to the repository root unless stated otherwise.
- `foo(args) -> ret` denotes a signature.
- Line references like `ai/model.py:148` point at the current source.
- "Tool name" means the function name the model calls (e.g. `web_search`), which
  may differ from the Python method name (e.g. `WebTool.search`).

---

## 2. High-level architecture

```
                          ┌──────────────────────────────────────────────┐
   terminal:              │                core/  (the brain)             │
   core/main.py ──▶ Chat ─┤  AgentModel ──▶ Provider ──▶ model backend    │
                          │      │                                        │
   web:                   │      ├── ToolRegistry ──▶ tool modules        │
   web/backend/run.py     │      │                                        │
      └▶ FastAPI ─▶        │      └── ChatHistory (SQLite) ──▶ disk        │
         AstraService ────▶│                                              │
            (1 worker     │                                              │
             thread)      │                                              │
   voice:                 │                                              │
   voice/backend/run.py   │                                              │
      └▶ VoiceLoop ─▶      │                                             │
         VoiceAgent ──────▶│  (embeds AstraService; whisper.cpp + piper)  │
                          └──────────────────────────────────────────────┘
                                              ▲
                                              │ shared
                                       core/config/settings.json
                                       (provider/model/keys/thinking)
```

### Layers

| Layer | Location | Responsibility |
|-------|----------|----------------|
| Entry points | `core/main.py`, `web/backend/run.py` | Boot a UI (terminal / HTTP). |
| Controllers | `core/controller/` | Parse slash commands; mutate the model/session. |
| Agent | `core/agent/chat.py`, `core/ai/model.py` | REPL loop; the agent loop (stream, tools, persist). |
| Providers | `core/ai/providers/` | Translate history to a vendor wire format and normalize the response stream. |
| Config | `core/ai/settings.py` | Resolve and persist provider/model/keys/thinking. |
| Local setup | `core/ai/local_setup.py` | Detect/install/start Ollama, list/pull models. |
| Tools | `core/tools/` | Callable capabilities exposed to the model. |
| Memory | `core/memory/` | SQLite conversation store + long-term memory. |
| Web backend | `web/backend/` | FastAPI routes + a thin, thread-safe service wrapper. |
| Web frontend | `web/frontend/` | Vanilla HTML/CSS/JS single-page app. |
| Voice backend | `voice/backend/` | Optional speech layer (whisper.cpp STT, piper TTS) and a loop that embeds the core. |
| Utilities | `core/utils/colors.py` | ANSI colors for terminal output. |

### A chat turn, end to end

1. User types a message (terminal `Chat.start` or web `POST /api/chat`).
2. `AgentModel.generate(prompt)` appends the user message to in-memory
   `self.history` and persists it via `ChatHistory`.
3. `ToolRegistry.get_filtered_schemas(prompt)` selects a bounded, relevant set of
   tool schemas (max 20).
4. `provider.stream_chat(model, messages, tools, think)` is called; it translates
   history and streams normalized `Chunk`s.
5. The loop forwards each chunk to the caller (terminal prints; web wraps it as
   NDJSON `thinking`/`content` events) and accumulates content + tool calls.
6. If the model requested tools, they are executed, results are appended as
   `role: "tool"` messages, and the provider is called again (loop).
7. When a response has no tool calls, the assistant text is persisted and the
   turn ends.

### The normalized stream

Every provider yields the same dataclasses (defined in
`core/ai/providers/base.py`):

```python
Chunk(message=ResponseMessage(content="", thinking="", tool_calls=[ToolCall(id, FunctionCall(name, arguments))]))
```

This mirrors the Ollama SDK shape (`chunk.message.content`,
`chunk.message.thinking`, `chunk.message.tool_calls[].function.name`), which is
why the agent loop can treat every backend identically. SSE responses from cloud
providers are decoded by the shared `iter_sse_data()` helper.

---

## 3. Repository layout

```
ASTRA/
├── README.md                  # user-facing quick start
├── documentation.md           # ← this file (technical reference)
├── LICENSE
├── requirements.txt           # core Python dependencies
├── start-dev.sh               # repo-root alias for ./web/astra-web
├── .gitignore
├── core/                      # standalone terminal app — the source of truth
│   ├── main.py                # terminal entry point
│   ├── architecture.md        # sessions/history deep dive
│   ├── browser_bridge.py      # shared store: page snapshot, command queue, messages
│   ├── browser_server.py      # localhost HTTP receiver for the extension
│   ├── config/
│   │   ├── identity.txt       # system prompt
│   │   └── settings.json      # provider config (git-ignored, created on save)
│   ├── agent/
│   │   └── chat.py            # terminal REPL loop
│   ├── controller/
│   │   ├── session_controller.py    # /session, /s
│   │   └── provider_controller.py   # /provider, /model, /thinking
│   ├── ai/
│   │   ├── settings.py        # provider/model/key/thinking config
│   │   ├── model.py           # AgentModel — the agent loop
│   │   ├── local_setup.py     # Ollama detect/install/start/list/pull
│   │   ├── ollama.py          # back-compat shim (OllamaModel = AgentModel)
│   │   └── providers/
│   │       ├── base.py        # Provider, Chunk, ToolCall, ProviderError, SSE
│   │       ├── __init__.py    # get_provider() factory
│   │       ├── ollama_provider.py
│   │       ├── openai_provider.py
│   │       ├── anthropic_provider.py
│   │       └── gemini_provider.py
│   ├── memory/
│   │   ├── chat_history.py    # SQLite conversation store
│   │   └── memory.py          # SQLite long-term memory store
│   ├── tools/
│   │   ├── tool_registry.py   # discovery, categorization, relevance filtering
│   │   ├── memory_tool.py     # memory_remember / _search / _forget
│   │   ├── shell_tool.py      # shell_exec + file ops
│   │   ├── web_tool.py        # web_search / fetch / download / crawl / find_files
│   │   ├── browser_tool.py    # HTTP+BeautifulSoup "browser"
│   │   ├── browser_context_tool.py  # page the user is viewing (extension)
│   │   ├── browser_control_tool.py  # automate the user's browser (extension)
│   │   ├── playwright_tool.py # real Chromium automation (async Playwright)
│   │   ├── file_reader_tool.py# read PDF/DOCX/PPTX/XLSX/CSV/JSON/text
│   │   ├── word_tool.py       # create/edit .docx
│   │   ├── powerpoint_tool.py # create/edit .pptx
│   │   └── excel_tool.py      # create/edit .xlsx
│   ├── utils/
│   │   └── colors.py          # ANSI color helpers
│   ├── downloads/             # generated files (git-ignored)
│   └── .venv/                 # virtualenv (git-ignored)
├── web/
    ├── astra-web              # single launcher (bash)
    ├── requirements.txt       # fastapi, uvicorn
    ├── README.md
    ├── backend/
    │   ├── __init__.py
    │   ├── run.py             # entrypoint (arg parsing, browser, uvicorn)
    │   ├── app.py             # FastAPI routes + static serving
    │   └── astra_service.py   # thread-safe wrapper over the core
    └── frontend/
        ├── index.html
        ├── styles.css
        ├── app.js
        └── favicon.svg
├── extension/                 # ASTRA Firefox extension (observe + automate)
│   └── firefox/
│       ├── manifest.json      # MV3 manifest
│       ├── background.js      # toggle, per-tab context, command poller
│       ├── content.js         # page snapshot + mouse/selection + DOM executor
│       ├── popup.html         # one-button integrate UI
│       ├── popup.js           # toggle + status
│       ├── README.md
│       └── ARCHITECTURE.md    # protocol, lifecycle, security, roadmap
└── voice/                     # optional local speech frontend (whisper.cpp + piper)
    ├── astra-voice            # single launcher (bash)
    ├── requirements.txt       # optional audio extras (sounddevice, numpy)
    ├── README.md
    ├── ARCHITECTURE.md        # pipeline, data flows, degradation, roadmap
    ├── models/                # downloaded models (git-ignored)
    └── backend/
        ├── __init__.py
        ├── run.py             # entrypoint (arg parsing, mode dispatch)
        ├── config.py          # env-first resolution of binaries/models/devices
        ├── deps.py            # readiness detection + report
        ├── audio.py           # record / VAD / play / 16 kHz conversion
        ├── stt.py             # whisper.cpp wrapper (speech → text)
        ├── tts.py             # piper wrapper (text → speech)
        ├── agent.py           # bridge to the core (reuses AstraService)
        ├── voice_loop.py      # record → transcribe → ask → speak
        └── install.py         # --setup: build/download local models
```

---

## 4. Getting started

### Requirements

- Python 3.10+ (tested on 3.14).
- No frontend build step (vanilla HTML/CSS/JS).
- Ollama only if you want local models; cloud providers need only an API key.

Python dependencies:

- `requirements.txt` (core): `ollama`, `requests`, `beautifulsoup4`, `lxml`,
  `rich`, `python-docx`, `python-pptx`, `openpyxl`.
- `web/requirements.txt` (web backend): `fastapi`, `uvicorn`.
- `voice/requirements.txt` (voice, **optional**): `sounddevice`, `numpy` — the
  cleaner audio backend; the voice layer otherwise shells out to
  `arecord`/`aplay`/`ffmpeg`. Continuous listening works on either backend.

Two optional features require packages that are **not** declared in
`requirements.txt` and must be installed manually:

- `pdfplumber` — PDF reading (`file_read_pdf`).
- `playwright` (+ browsers) — the `playwright_*` automation tools.

ASTRA deliberately does **not** depend on the `openai`, `anthropic` or
`google-genai` SDKs; cloud providers are called directly over HTTPS.

### Run the web app

```bash
git clone https://github.com/prasonkc/ASTRA.git
cd ASTRA
./web/astra-web                 # start + open the browser
./web/astra-web --no-browser    # headless
./web/astra-web --port 9000     # custom port
./start-dev.sh                  # alias for ./web/astra-web
```

On first run the launcher creates `core/.venv` (override with `ASTRA_VENV`),
installs missing dependencies, sanity-checks the **active** provider, and serves
`http://127.0.0.1:8765`.

### Run the terminal app

The terminal app is the source of truth and needs no web server:

```bash
cd core
./.venv/bin/python main.py
```

The terminal starts a tiny localhost HTTP listener (`core/browser_server.py`) on
`127.0.0.1:8765` so the ASTRA Firefox extension can push the page the user is
viewing straight into the core — no web app involved. Same routes as the web
app (`POST|GET|DELETE /api/browser/context`, plus `GET /api/browser/commands`
and `POST /api/browser/commands/<id>/result` for automation, and
`POST /api/browser/message` so the extension popup can hold a conversation with
the running agent). Control it with `ASTRA_BROWSER_BRIDGE=0` (off),
`ASTRA_BROWSER_HOST`, `ASTRA_BROWSER_PORT`. If the port is already taken
(astra-web is running), the bridge stays off and the web server handles the
requests instead.

### Run the voice app

The optional voice wrapper adds a local speech layer (whisper.cpp for
speech-to-text, piper for text-to-speech) and runs the same core in a voice loop:

```bash
./voice/astra-voice --setup          # one-time: fetch models, build whisper.cpp
./voice/astra-voice                  # continuous listening (default)
./voice/astra-voice --push-to-talk   # press Enter to talk, Enter again to send
./voice/astra-voice --status         # show readiness / what is missing
```

It reuses `core/.venv` and needs no web server. Audio uses the optional Python
extras (`sounddevice`+`numpy`) when present, otherwise `arecord`/`aplay` or
`ffmpeg`. See [section 12](#12-voice-application) and
[`voice/README.md`](voice/README.md).

### Verify a fresh checkout

```bash
cd core
./.venv/bin/python -c "from ai.model import AgentModel; m = AgentModel(); print(m.describe())"
```

This prints the resolved provider, model, session id and thinking flag without
making any network call.

---

## 5. Configuration & environment

Configuration is resolved with strict precedence (highest first):

1. **Environment variables** — always win.
2. **`core/config/settings.json`** — written by `/provider` and the web Settings
   panel. Git-ignored and written with file mode `600` (it holds secrets).
3. **Built-in defaults.**

Provider/model names accept aliases: `local`→`ollama`, `gpt`→`openai`,
`claude`→`anthropic`, `google`→`gemini` (see `normalize_provider`).

### `core/config/settings.json` schema

Created on first save:

```json
{
  "provider": "openai",
  "model": "gpt-4o-mini",
  "thinking": true,
  "providers": {
    "openai": {
      "api_key": "sk-…",
      "model": "gpt-4o-mini",
      "base_url": "https://api.openai.com/v1"
    },
    "anthropic": { "api_key": "sk-ant-…" },
    "gemini":    { "api_key": "AIza…" }
  }
}
```

- `provider` / `model` — the active selection.
- `thinking` — global reasoning toggle (`true` by default).
- `providers.<id>` — per-provider `api_key`, `model`, `base_url`. API keys for
  all providers can coexist; switching providers does not erase a key.

See [Appendix A](#appendix-a-environment-variables) for the full environment
variable list. Note that base URLs have any trailing slash stripped. The optional
voice wrapper has its own `ASTRA_VOICE_*` variables, resolved separately (see
[section 12](#12-voice-application)).

---

## 6. Core AI subsystem

### 6.1 `core/ai/settings.py`

**Purpose.** Resolves provider, model, API keys, base URLs and the thinking flag
from env → file → defaults, and persists changes atomically.

**Module constants**

| Name | Value / meaning |
|------|-----------------|
| `PROVIDERS` | `("ollama", "openai", "anthropic", "gemini")` |
| `DEFAULT_PROVIDER` | `"ollama"` |
| `DEFAULT_MODELS` | per-provider default model names |
| `DEFAULT_BASE_URLS` | per-provider default endpoints |
| `PROVIDER_LABELS` | human labels for CLI/web |
| `_KEY_ENV` | per-provider key env-var tuples (first match wins) |
| `_BASE_ENV` | per-provider base-URL env-var tuples |
| `_ENV_PROVIDER` / `_ENV_MODEL` / `_ENV_THINKING` | `ASTRA_PROVIDER` / `ASTRA_MODEL` / `ASTRA_THINKING` |
| `DEFAULT_THINKING` | `True` (preserves historical behaviour) |
| `_TRUE_WORDS` / `_FALSE_WORDS` | accepted boolean spellings |
| `_settings` / `_settings_lock` | module singleton + its lock |

**Functions / methods**

- `_parse_bool(value) -> Optional[bool]` — coerce `1/true/yes/on/…` and
  `0/false/no/off/…` to bool; returns `None` when unrecognized.
- `default_settings_path() -> Path` — `ASTRA_SETTINGS_PATH` or
  `core/config/settings.json` (derived from the module file location).
- `_first_env(names) -> Optional[str]` — first non-empty env value.
- `normalize_provider(name) -> str` — map aliases to canonical ids.
- `default_model(provider) -> str`, `default_base_url(provider) -> str`.
- `get_settings() -> Settings` — lazily create and cache the process singleton.
- `Settings(path=None)` — construct, acquire an `RLock`, and `load()`.
- `Settings.load() -> dict` — read JSON; never raises; applies defaults;
  guarantees `provider` and a dict `providers`.
- `Settings.save() -> None` — atomic write via `tempfile.mkstemp` + `os.replace`,
  `chmod 0600`.
- `Settings.active_provider() -> str` — `ASTRA_PROVIDER` → file → default.
- `Settings.active_model(provider=None) -> str` — precedence: `ASTRA_MODEL` (only
  when the queried provider is active) → stored top-level `model` (active only) →
  per-provider `model` → default.
- `Settings.set_active(provider, model=None) -> None` — persist active
  provider/model.
- `Settings.api_key(provider) -> Optional[str]` / `api_key_source(provider)
  -> "env"|"file"|None`.
- `Settings.base_url(provider) -> str` — env → file → default, trailing `/`
  stripped.
- `Settings.set_api_key(provider, key)` / `set_base_url(provider, url)` — persist
  (empty value removes the entry).
- `Settings.thinking() -> bool` — `ASTRA_THINKING` → stored → `True`;
  `thinking_source() -> "env"|"file"|"default"`; `set_thinking(enabled)` persists.
- `Settings.provider_options(provider) -> dict` — `{model, base_url, api_key,
  api_key_source}` for the factory (env base URL intentionally ignored here).
- `Settings._mask(secret) -> str` — `first4…last4` (or bullets for short keys).
- `Settings.to_public() -> dict` — masked snapshot used by the web UI and
  `/provider status`: active provider/model, per-provider
  `{label, model, default_model, base_url, default_base_url, api_key_masked,
  api_key_source, api_key_from_env, configured, requires_key}`, plus `thinking`,
  `thinking_from_env`, `env_provider_locked`, `env_model_locked`.

### 6.2 `core/ai/model.py` — `AgentModel`

**Purpose.** The backend-agnostic agent: owns the agent loop, tool execution,
streaming, history persistence and session management.

**Constructor.** `AgentModel(model_name=None, session_id=None, provider=None)`:

1. Resolve the settings singleton and open `ChatHistory`.
2. Build the `ToolRegistry` and cache `all_functions` (tool-name → callable).
3. Resolve `provider_name` (arg or settings) and `model_name`.
4. Instantiate the provider via `get_provider(...)`.
5. Resolve/create the session, load history, or seed it with the system prompt.
6. On history-load failure, fall back to a minimal system-prompt-only history.

**Methods**

- `describe() -> dict` — `{provider, provider_label, model, session_id, thinking,
  thinking_source}`.
- `thinking_enabled() -> bool` — reads settings fresh each call, so `/thinking`
  and the web checkbox take effect without reconfiguring the backend.
- `set_thinking(enabled) -> bool` — persist and return the effective value.
- `reconfigure(provider=None, model=None) -> dict` — swap the backend/model
  **without touching history**; returns a fresh `describe()`.
- `_load_system_prompt() -> str` — read `./config/identity.txt` (or the path
  relative to the module), else a built-in fallback.
- `_get_tools_for_query(prompt) -> list` — filtered tool schemas.
- `generate(prompt, on_event=None)` — **generator**; see below.
- `_error_chunk(message)` — wraps an error as a fake chunk (used by
  `generate`).
- Session management: `switch_session(id) -> bool`, `new_session() -> str`,
  `resume_last_session() -> bool`, `list_sessions(limit=20)`,
  `list_sessions_with_preview(limit=20)`, `switch_session_by_index(i) -> bool`,
  `delete_session(id) -> bool`, `delete_session_by_index(i) -> bool`,
  `clear_all_sessions() -> int`, `close()`.

**The agent loop (`generate`)**

```python
if not prompt.strip(): return
self.history.append({"role": "user", "content": prompt})
chat_history.add_message(session_id, "user", prompt)
tools = registry.get_filtered_schemas(prompt)

while True:
    stream = provider.stream_chat(model, self.history, tools, think=thinking_enabled())
    content, tool_calls = "", []
    for chunk in stream:              # yield each chunk straight through
        content    += chunk.message.content
        tool_calls += chunk.message.tool_calls
        yield chunk

    if not tool_calls:
        if content.strip():          # skip empty replies
            history.append({"role":"assistant","content":content})
            chat_history.add_message(session_id, "assistant", content)
        return

    # serialize + persist the assistant tool-call turn
    history.append({"role":"assistant","content":content,"tool_calls":[...]})
    chat_history.add_message(session_id,"assistant",content,[...])

    for tc in tool_calls:
        result = all_functions[tc.name](**tc.arguments)   # or "Unknown tool"
        history.append({"role":"tool","content":str(result)})
        chat_history.add_message(session_id,"tool",str(result))
```

Key behaviours:

- `ProviderError` and unexpected exceptions are converted to error chunks (the
  stream never raises mid-turn).
- Each provider call is repeated until the model stops requesting tools, so a
  single user turn may involve many tool round-trips.
- Tool call/result messages are **paired by order** for providers that need
  explicit ids.
- `on_event` (optional) receives `{"type":"tool_call",...}` and
  `{"type":"tool_result",...}` dicts; the terminal passes nothing, the web layer
  uses it to render tool cards.

**Internal history format** (persisted verbatim):

```python
{"role": "system",    "content": str}
{"role": "user",      "content": str}
{"role": "assistant", "content": str, "tool_calls": [
     {"id": str|None, "type": "function",
      "function": {"name": str, "arguments": dict}}]}
{"role": "tool",      "content": str}
```

`thinking` is streamed but **never persisted**.

### 6.3 `core/ai/providers/base.py`

Defines the provider contract and shared helpers.

- `ProviderError(RuntimeError)` — user-actionable provider failure (auth,
  network, bad request).
- `@dataclass FunctionCall(name, arguments={})`
- `@dataclass ToolCall(id, function)`
- `@dataclass ResponseMessage(content="", thinking="", tool_calls=[])`
- `@dataclass Chunk(message)`
- `parse_arguments(raw) -> dict` — best-effort JSON/dict coercion; never raises.
- `text_chunk(text) -> Chunk`, `thinking_chunk(text) -> Chunk`.
- `Provider` — base class with `name`, `__init__(**config)` and the abstract
  `stream_chat(*, model, messages, tools, think=True) -> Iterator[Chunk]`.
- `iter_sse_data(response) -> Iterator[str]` — line-based SSE decoder that yields
  `data:` payloads; prefixes Anthropic-style events as `"event|payload"`; stops
  at `data: [DONE]`.

### 6.4 `core/ai/providers/__init__.py`

- `_PROVIDER_CLASSES` — id → provider class.
- `KEYED_PROVIDERS = ("openai", "anthropic", "gemini")`.
- `get_provider(name=None, *, settings=None, **overrides) -> Provider` — normalize
  the id, resolve base URL and API key from settings unless overridden, then
  instantiate. Raises `ProviderError` for an unknown provider. Passes `api_key`
  only for keyed providers.

### 6.5 Provider modules

All providers implement the same `stream_chat` contract. Each translates ASTRA's
internal history into its wire format at call time.

#### `ollama_provider.py` — `OllamaProvider`

- Wraps the `ollama` Python SDK; `__init__(host=None, **config)`.
- `_client()` — returns an `ollama.Client(host=…)` when a host is configured,
  else `None` (so the SDK reads `OLLAMA_HOST`).
- `stream_chat(...)` — calls `client.chat(model, messages, tools, think,
  stream=True)` and normalizes chunks. Maps `ollama.ResponseError`,
  `ConnectionError` and other exceptions to `ProviderError`.
- No translation and no SSE parsing (the SDK streams).

#### `openai_provider.py` — `OpenAIProvider`

- REST via `requests`; works with any OpenAI-compatible endpoint by overriding
  `base_url`.
- `DEFAULT_TIMEOUT = 600`.
- `to_openai_messages(messages) -> list` — translate history; pair tool results
  with the originating `tool_call_id`; synthesize stable ids when missing.
- `OpenAIProvider.__init__(api_key=None, base_url=..., timeout=600, **config)`;
  `_headers()` returns `Authorization: Bearer …`.
- `stream_chat(...)` — `POST {base_url}/chat/completions`, stream; yields
  `thinking` from `reasoning_content`/`reasoning`, `content` from `delta.content`,
  and consolidates streamed `tool_calls` deltas before yielding one final chunk.
- `_http_error(provider, response)` — extract a human-readable error string.

#### `anthropic_provider.py` — `AnthropicProvider`

- `DEFAULT_TIMEOUT = 600`, `ANTHROPIC_VERSION = "2023-06-01"`.
- `to_anthropic(messages) -> (system, convo)` — split the system prompt into a
  separate string; build strictly alternating turns; carry tool results as
  `tool_result` blocks in `user` messages; emit `tool_use` blocks on assistant
  turns.
- `to_anthropic_tools(tools) -> list` — OpenAI schemas → `{name, description,
  input_schema}`.
- `AnthropicProvider.__init__(api_key=None, base_url=..., timeout=600,
  max_tokens=8192, **config)`; `_headers()` uses `x-api-key` +
  `anthropic-version`.
- `stream_chat(...)` — `POST {base_url}/v1/messages`; handles
  `content_block_start` (tool_use), `content_block_delta`
  (`text_delta`/`thinking_delta`/`input_json_delta`), buffering tool JSON and
  materializing tool calls at end of stream.
- `_http_error(...)`.

#### `gemini_provider.py` — `GeminiProvider`

- `DEFAULT_TIMEOUT = 600`.
- `sanitize_schema(schema)` — recursively keep only JSON-schema keys Gemini's
  `functionDeclarations` accepts (drops `$schema`, `additionalProperties`, etc.);
  adds `type: "object"` when properties are present.
- `to_gemini(messages) -> (system, contents)` — roles become `user`/`model`;
  tool calls become `functionCall` parts; tool results become `functionResponse`
  parts.
- `to_gemini_tools(tools) -> list` — `functionDeclarations` with sanitized
  parameters.
- `GeminiProvider.__init__(api_key=None, base_url=..., timeout=600, **config)`.
- `stream_chat(...)` — `POST {base_url}/v1beta/models/{model}:streamGenerateContent?alt=sse`,
  with the key as a query param; yields `thinking` for parts flagged `thought`,
  `content` otherwise; synthesizes tool-call ids (`call_N`).
- `_http_error(...)`.

### 6.6 `core/ai/local_setup.py`

Drives the zero-to-working local experience. Every long-running step takes an
optional `progress(text: str) -> None` callback.

**Constants:** `Progress`, `DEFAULT_HOST = "http://localhost:11434"`,
`RECOMMENDED_MODELS` (qwen3:14b/8b/4b, llama3.2:3b, llama3.1:8b, gemma3:4b,
mistral:7b, deepseek-r1:8b).

**Functions**

- `_emit(progress, text)` — safely invoke the callback.
- `host_url(host=None) -> str` — resolve env/default host, add scheme, strip `/`.
- `is_ollama_installed() -> bool` — `PATH` plus common install locations.
- `ollama_version() -> Optional[str]` — run `ollama --version`.
- `is_ollama_running(host=None, timeout=2.0) -> bool` — `GET /api/version`.
- `list_local_models(host=None) -> list` — `GET /api/tags`, mapped to
  `{name, size, size_human, modified_at}`.
- `_human_size(num) -> str` — base-1000 formatting.
- `install_ollama(progress=None) -> bool` — best-effort per OS: Linux
  `curl … | sh`, macOS `brew install ollama`, Windows `winget install
  Ollama.Ollama`. Returns `False` (with guidance) when the tool is unavailable.
- `_run_streaming(cmd, progress=None, timeout=None) -> bool` — run a shell
  command, streaming combined output line by line.
- `start_ollama_server(progress=None, host=None, wait=20.0) -> bool` — spawn
  `ollama serve` detached and poll until ready.
- `pull_model(model, progress=None, host=None) -> bool` — `POST /api/pull`,
  parse progress events, emit `status 42.7% (3.1 GB/7.3 GB)` style lines.
- `install_and_pull(model, progress=None, host=None) -> bool` — install (if
  needed) → start → pull.
- `local_status(host=None) -> dict` — `{installed, running, version, host,
  models, recommended}` for the CLI/web UI.

### 6.7 `core/ai/ollama.py`

Backwards-compatibility shim: `OllamaModel = AgentModel` plus `ProviderError`,
exported via `__all__`. New code should import `AgentModel` from `ai.model`.

---

## 7. Agent & entry points

### `core/main.py`

```python
from agent.chat import Chat
if __name__ == "__main__":
    Chat().start()
```

Four lines; all logic lives in `Chat`.

### `core/agent/chat.py` — `Chat`

The terminal REPL and reference behaviour.

- `Chat()` — construct `AgentModel`, `SessionController`,
  `ProviderController`; exit (with a traceback) if the model cannot initialize.
- `start()` — print the welcome banner + current model, then loop:
  - dispatch `/provider`, `/model`, `/thinking` to `ProviderController`;
  - dispatch `/session` or `/s ` to `SessionController`;
  - otherwise stream `model.generate(user_input)`, rendering a thinking
    indicator (`.`, `..`, `...`) while reasoning tokens arrive, then the answer;
  - handle `exit`, EOF, Ctrl-C and unexpected errors gracefully;
  - `_cleanup()` on exit.
- `_safe_input(prompt) -> str | None` — `input()` with EOF/Ctrl-C handling.
- `_safe_show_current_session()` — best-effort current-session banner.
- `_cleanup()` — `model.close()`.

Note: `/s` **without** a trailing space is not routed (the check is
`startswith("/s ")`), a known quirk; `/s help` etc. work.

---

## 8. Memory & persistence

### 8.1 `core/memory/chat_history.py` — `ChatHistory`

Low-level SQLite conversation store.

**Database schema**

```sql
CREATE TABLE conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    title      TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role            TEXT NOT NULL,      -- system | user | assistant | tool
    content         TEXT,
    tool_calls      TEXT,               -- JSON array, or NULL
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX idx_messages_conversation_id ON messages(conversation_id);
```

- **Path resolution:** `db_path` arg → `ASTRA_DB_PATH` → `./memory/chat_history.db`
  (resolved relative to the CWD, which is `core/`).
- **Connection:** `check_same_thread=False`, `timeout=30.0`,
  `row_factory = sqlite3.Row`, `PRAGMA foreign_keys=ON`.
- **Session ids:** `"session_" + uuid4().hex[:12]`.

**Methods**

- `__init__(db_path=None)` — connect, enable FKs, init schema.
- `_init_schema()` — create tables + index (`IF NOT EXISTS`).
- `create_session(title=None) -> str` — new session (default timestamped title);
  retries on `IntegrityError`.
- `get_session_id_by_index(index) -> Optional[str]` — index 0 = most recently
  updated.
- `get_latest_session_id() -> Optional[str]`.
- `session_exists(session_id) -> bool`.
- `add_message(session_id, role, content=None, tool_calls=None) -> None` —
  insert + bump `updated_at`; serializes `tool_calls` to JSON; raises
  `RuntimeError` on failure.
- `get_history(session_id, limit=100) -> List[Dict]` — chronological, `tool_calls`
  decoded (corrupt JSON → `[]`), tail-limited in Python.
- `list_sessions(limit=20) -> List[Dict]` — ordered by `updated_at DESC`.
- `list_sessions_with_preview(limit=20) -> List[Dict]` — sessions plus
  `message_count` and `preview` (note: N+1 queries).
- `get_session_preview(session_id, max_messages=3) -> str` — last user/assistant
  lines, 80 chars each.
- `delete_session(session_id) -> bool` — cascade-deletes messages.
- `delete_all_sessions() -> int` — returns rows deleted.
- `get_message_count(session_id) -> int`.
- `update_session_title(session_id, title)`.
- `close()`.

**Errors** are caught and degraded (empty lists / `False` / `None`); warnings go
through `utils.colors.warning` but never crash the loop.

### 8.2 `core/memory/memory.py` — `Memory`

The long-term memory store that backs the `memory_*` tools.

```sql
CREATE TABLE memories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

- Stored at `./memory/astra.db` by default (constructor arg, **not**
  env-configurable).
- `__init__(database_path="./memory/astra.db")`, `_init_schema()`.
- `remember(category, content) -> bool` — rejects blank inputs.
- `search(query) -> list` — case-insensitive `LIKE` on content/category, newest
  first.
- `forget(memory_id) -> bool` — delete by positive integer id.
- `close()`.

No indexes or FTS; fine for small datasets.

---

## 9. Controllers & CLI commands

Controllers parse slash commands in the REPL and mutate the model/settings. They
return `True` when they handled the input.

### 9.1 `core/controller/session_controller.py` — `SessionController`

Normalizes `/s` → `/session`. Unknown subcommands are printed with a help hint.
Bare `/session`/`/s` prints help.

| Command (aliases) | Effect |
|-------------------|--------|
| `/s new` (`n`) | Create and switch to a new session. |
| `/s list` (`l`, `ls`) | List sessions with message counts + previews; current marked `>`. |
| `/s switch <n>` (`sw`, `s`, `use`, `u`) | Switch by index, else by session id. |
| `/s <number>` | Quick switch by index (0 = most recent). |
| `/s resume` (`r`) | Resume the most recent session. |
| `/s del <n>` (`del`, `rm`, `remove`, `d`) | Confirm then delete; auto-switch if it was current. |
| `/s clear` (`clr`, `purge`) | Confirm (type `YES`), delete all, create a fresh session. |
| `/s preview [n]` (`p`, `show`, `info`) | Show a conversation preview. |
| `/s help` (`h`, `?`) | Print help. |

Methods: `handle(user_input) -> bool` plus one `_cmd_*` per command and the
display helpers `_list_sessions`, `_show_current_session`,
`_show_session_preview`, `_confirm_delete`, `_confirm_clear`, `_print_help`.

### 9.2 `core/controller/provider_controller.py` — `ProviderController`

Handles `/provider`, `/model`, `/thinking`.

| Command | Effect |
|---------|--------|
| `/provider` (`menu`, `setup`) | Interactive setup menu (local / local_setup / OpenAI / Anthropic / Gemini). |
| `/provider status` (`show`, `current`) | Print provider, model and key source; for Ollama, running state. |
| `/provider help` (`?`, `h`) | Print help. |
| `/provider local_setup` (`local-setup`, `install`, …) | Install Ollama if needed and pull a model (progress-streamed). |
| `/provider local` (`ollama`) | Pick an already-installed Ollama model (or type a tag). |
| `/provider openai` (`gpt`) | Prompt for an OpenAI key + model. |
| `/provider anthropic` (`claude`) | Prompt for an Anthropic key + model. |
| `/provider gemini` (`google`) | Prompt for a Gemini key + model. |
| `/provider set <p> [model]` | Set the active provider/model directly. |
| `/model [name]` (`/models`) | Show or switch the model for the current provider. |
| `/thinking [on|off|toggle|status]` | Toggle/set/print reasoning output. |

Methods: `handle`, `_menu`, `_configure_cloud(provider, extra=None)`,
`_configure_local`, `_local_setup`, `_model_command`, `_thinking_command`,
`_print_thinking`, `_apply(provider, model=None)`, `_show_status`, `_read`,
`_read_secret` (uses `getpass`), `_progress_printer`, `_print_help`.

Notes:

- `_apply` persists via `Settings.set_active`, swaps the backend via
  `AgentModel.reconfigure`, and warns (without blocking) when a keyed provider
  has no key.
- `_configure_cloud` accepts inline `extra` args (key, model) — useful for
  scripting and tests.
- `/thinking` with no argument flips the current value; `ASTRA_THINKING` overrides
  it and the CLI says so.

### 9.3 Slash commands vs. normal input

`agent/chat.py` only treats input starting with `/provider`, `/model`,
`/thinking`, `/session` or `/s ` as commands. Everything else is sent to the
model.

---

## 10. Tool system

### 10.1 `core/tools/tool_registry.py` — `ToolRegistry`

Discovers all tool instances, groups them into keyword-scored categories, and
returns a bounded, relevance-filtered subset per query.

- `MAX_TOOLS = 20` — hard cap on schemas returned per query.
- `ToolCategory` (dataclass): `name`, `description`, `keywords`, `tools`,
  `always_include`.
- `__init__()` — build `tools`, `categories`, `tool_to_category`.
- `_register_all_tools()` — instantiate the eleven tool objects
  (`PlaywrightBrowserTool(headless=False)`, `BrowserContextTool()`,
  `BrowserControlTool()`) and define categories. **All tools are constructed with
  no arguments**, so `working_dir` defaults to the CWD (`core/`).
- `get_all_tool_schemas() -> list` — concatenate every tool's `get_tools()`.
- `get_all_functions() -> dict` — merge every tool's `.functions` map
  (tool-name → bound method). Later duplicates overwrite earlier ones.
- `get_tool_category(tool_name) -> Optional[str]`.
- `get_categories_for_query(query) -> list` — substring-count keyword scoring;
  `always_include` categories score `inf`; `core` is always first.
- `get_filtered_schemas(query, max_tools=None) -> list` — core tools first, then
  relevant categories in score order, then a fallback priority
  (`shell`, `web_search`, `browser`, `playwright`), capped at `MAX_TOOLS`.
- `get_filtered_functions(query) -> dict` — callables matching the selected
  schemas.
- `get_tool_registry() -> ToolRegistry` — lazily-created module singleton.

**Category → tools**

| Category | Tools |
|----------|-------|
| `core` (always) | `memory_remember`, `memory_search`, `memory_forget` |
| `browser_context` (always) | `browser_context` |
| `browser_control` (always) | 12 `ext_*` tools (see below) |
| `shell` | `shell_exec`, `shell_read`, `shell_write`, `shell_list`, `shell_glob`, `shell_exists` |
| `web_search` | `web_search`, `web_fetch`, `web_download`, `web_crawl`, `web_find_files` |
| `browser` | `browser_open`, `browser_back`, `browser_status`, `browser_text`, `browser_links`, `browser_click`, `browser_extract`, `browser_forms`, `browser_fill`, `browser_submit`, `browser_search` |
| `playwright` | 25 `playwright_*` tools (see below) |
| `file_reader` | `file_read`, `file_read_pdf`, `file_read_docx`, `file_read_pptx`, `file_read_xlsx`, `file_read_csv`, `file_read_json`, `file_read_text`, `file_list`, `file_info` |
| `word` | `word_create`, `word_read`, `word_info`, `word_add_heading`, `word_add_paragraph`, `word_add_bullet`, `word_add_table`, `word_format`, `word_replace`, `word_delete_paragraph` |
| `powerpoint` | `ppt_create`, `ppt_read`, `ppt_info`, `ppt_add_slide`, `ppt_add_text`, `ppt_add_bullets`, `ppt_add_table`, `ppt_add_image`, `ppt_format`, `ppt_delete_slide` |
| `excel` | `excel_create`, `excel_read`, `excel_info`, `excel_write`, `excel_write_rows`, `excel_format`, `excel_formula`, `excel_find`, `excel_stats`, `excel_add_sheet`, `excel_delete_sheet`, `excel_to_csv`, `csv_to_excel` |

**How execution works.** Each tool class exposes:

- `get_tools() -> list` — OpenAI-format function schemas.
- `self.functions` — `{tool_name: bound_method}`.

`ToolRegistry.get_all_functions()` merges the maps; `AgentModel.generate` calls
`all_functions[name](**arguments)`. Tools therefore receive their schema
parameters as keyword arguments.

**Maintainer notes.** The `playwright` category alone defines 25 tools, more than
`MAX_TOOLS`, so it can never be fully selected in one query. Keyword scoring is
naive substring matching. `playwright` is imported at module import time with no
fallback (see §19). The always-included categories (`core`, `browser_context`,
`browser_control`) already occupy 16 of the 20 slots, so keep new always-on tools
rare.

### 10.2 Tool reference

Every tool returns a JSON-serializable `dict` (or `list`) — usually
`{"success": bool, ...}` — which is stringified into the `tool` history message.
All paths are resolved against the process CWD (`core/`) unless noted.

#### `memory_tool.py` — `MemoryTool`

Wraps `Memory` (SQLite at `./memory/astra.db`).

- `remember(category, content) -> dict` — store a fact.
- `search(query) -> list` — `LIKE` search; returns
  `[{id, category, content, created_at}]`.
- `forget(memory_id) -> dict` — delete by id.
- Tools: `memory_remember`, `memory_search`, `memory_forget`.

#### `shell_tool.py` — `ShellTool`

Shell execution + filesystem operations.

- `exec(command, cwd=None, timeout=None) -> dict` — `subprocess.run(shell=True)`;
  returns success/stdout/stderr/returncode.
- `read_file(path, encoding="utf-8") -> dict`
- `write_file(path, content, encoding="utf-8", create_dirs=True) -> dict`
- `list_dir(path=".", show_hidden=False) -> dict`
- `glob_files(pattern, path=".") -> dict`
- `path_exists(path) -> dict`
- Helpers: `_validate_command` (optional allowlist; `None` = allow all),
  `_resolve_path`.
- Tools: `shell_exec`, `shell_read`, `shell_write`, `shell_list`, `shell_glob`,
  `shell_exists`.

> **Security.** Commands run through a shell with no sandbox; the allowlist can
> be bypassed by chaining. Treat this as a trusted-local feature.

#### `web_tool.py` — `WebTool`

HTTP-only web access (no browser).

- `search(query, max_results=10, search_engine="duckduckgo") -> dict` — only
  DuckDuckGo is implemented.
- `fetch(url, max_length=100000) -> dict` — size-guarded GET; returns content plus
  title/description/text/links metadata.
- `download(url, filename=None, overwrite=False) -> dict` — streams into
  `./downloads`, enforcing `max_file_size`.
- `crawl(url, max_depth=2, max_pages=20, same_domain=True, follow_patterns=None)
  -> dict` — BFS crawl with politeness delay.
- `find_files(url, extensions=None, max_depth=2, max_files=50) -> dict` — crawl
  for links matching extensions.
- Tools: `web_search`, `web_fetch`, `web_download`, `web_crawl`,
  `web_find_files`.

> **Maintainer notes.** `download` derives the filename from the server with no
> sanitization (path traversal risk); the crawler ignores `robots.txt` and is
> SSRF-capable. Hardening these is a natural task.

#### `browser_tool.py` — `BrowserTool`

A **stateful HTTP + BeautifulSoup** "browser" with **no JavaScript**.

- `open(url) -> dict`, `back() -> dict`, `status() -> dict`
- `text(max_length=5000) -> dict` — cleaned visible text.
- `links(filter_text=None, limit=50) -> dict`
- `click(target) -> dict` — follow by index, link text or URL substring.
- `extract(selector, limit=50, attribute=None) -> dict`
- `forms() -> dict`, `fill(fields) -> dict`, `submit(form_index=0, fields=None)
  -> dict`
- `search(query, max_results=10) -> dict`
- Helpers: `_normalize_url`, `_load`, `_require_page`, `_clean_soup`.
- Tools: the 11 `browser_*` schemas.

Use `playwright_tool` when a page needs JavaScript.

#### `browser_context_tool.py` — `BrowserContextTool`

Exposes the page the **user is currently viewing in their own Firefox browser**
to the agent, via the ASTRA browser extension (`extension/firefox/`). The
extension POSTs a snapshot (URL, title, HTML, visible text, selected text, mouse
position) to `POST /api/browser/context`; `web/backend` merges it into
:mod:`browser_bridge` and this always-included tool reads the latest snapshot.

- `context(field="all") -> dict` — `field` is `text`, `html`, `selection`, `url`,
  `title`, `mouse` or `all`. Returns `{"available": False, …}` when nothing has
  been shared yet. HTML/text are clipped (`MAX_HTML_CHARS` 50 000,
  `MAX_TEXT_CHARS` 20 000) because the result is written into conversation
  history.
- Tools: the single `browser_context` schema (category `browser_context`,
  `always_include=True`).

> **Maintainer notes.** The store is in-memory only and cleared with the process
> (or `DELETE /api/browser/context`). The tool is always offered so ASTRA can
> answer "explain this page" without the user naming it, but it returns
> `available: False` until the extension is switched on.

#### `browser_control_tool.py` — `BrowserControlTool`

Automates the **user's own Firefox browser** through the ASTRA extension
(`extension/firefox/`), so actions happen visibly in the tab the user has open.
This is the counterpart to `browser_context_tool`: `browser_context` *reads* what
the user sees, `browser_control` *acts* on it.

Every call is a round-trip through :mod:`browser_bridge`:

```
tool ─enqueue_command─▶ queue ──GET /api/browser/commands──▶ extension (Firefox)
  ▲                                                            │ execute
  └──────────── tool returns ──POST /api/browser/commands/{id}/result◀────────┘
```

The tool blocks on a `threading.Condition` until the extension posts a result or
`COMMAND_TIMEOUT` (60 s) elapses, then returns
`{"id", "name", "success", "result", "error"}`. See
`extension/firefox/ARCHITECTURE.md` for the full protocol.

- Tab management: `open_tab(url="")`, `list_tabs()`, `switch_tab(target)`,
  `close_tab()`.
- Navigation: `navigate(url)`, `search(query, engine="google")` (also
  duckduckgo/bing; returns the results page's visible text).
- Page interaction: `click(selector, text)`, `type_text(text, selector)`,
  `press_key(key)`, `scroll(direction, amount)`.
- Scripting / reading: `eval_js(expression)` (content-script world),
  `read_page(part="text")` (text/html/url/title/selection/all).
- Tools: the 12 `ext_*` schemas (category `browser_control`,
  `always_include=True`) — names in the registry table above.

> **Maintainer notes.** Requires the extension to be on **and** a normal page in
> the active tab; otherwise calls time out with an explanatory message. Tab and
> navigation commands run in `background.js` via the `tabs` API; DOM commands are
> delegated to `content.js`. `ext_eval_js` runs in the content-script world, not
> the page's JS world. The command channel is unauthenticated and localhost-only —
> see the security section in `extension/firefox/ARCHITECTURE.md`.

#### Browser chat messages — `POST /api/browser/message`

The extension popup can hold a conversation with the running agent. It POSTs
`{message}` to `POST /api/browser/message`; the frontend that owns the process
(the terminal `Chat` or the web `AstraService`) registers a handler with
:mod:`browser_bridge`, and :func:`browser_bridge.run_message` runs one
**ordinary chat turn** — same model, session and history as the terminal/web UI —
and returns `{ok, reply, error, session_id}`.

This is the reverse of the command channel: the agent is *already running* and
the browser is the caller, so no polling is needed on the backend side. Turn
execution is serialized with the frontend's own turns (`Chat._turn_lock` in the
terminal, `AstraService._lock` in the web app) so the two paths never interleave.

```
popup ──POST /api/browser/message {message}──▶ run_message ──▶ agent turn
      ◀────────── {ok, reply, error, session_id} ─────────────────────┘
```

> **Maintainer notes.** Because the popup shares the session, a message sent from
> the browser is persisted in normal chat history and can use every tool
> (including `browser_context`, so "explain this page" works from the popup).
> The background script owns the request, so it completes even if the popup is
> closed before the reply arrives. Unauthenticated and localhost-only, like the
> rest of the bridge.

#### `playwright_tool.py` — `PlaywrightBrowserTool`

Real Chromium automation via async Playwright. **Headed by default**
(`headless=False`), so it needs a display.

- Lifecycle: `open(url=None)`, `close_browser()`.
- Navigation: `navigate(url)`, `go_back()`, `go_forward()`, `reload()`.
- Interaction: `click`, `type_text`, `fill`, `select_option`,
  `wait_for_selector`, `hover`, `press_key`, `scroll`.
- Extraction: `extract(selector, attribute=None)`, `get_text`, `get_html`,
  `get_url`, `get_title`.
- Capture: `screenshot(path, full_page=False)`, `save_pdf(path)`.
- Scripting: `evaluate(script)` — arbitrary JS in the page.
- Tabs: `new_tab`, `switch_tab`, `close_tab`.
- Internals: `_ensure_initialized()`, `_run_async(coro)`.
- Tools: 25 `playwright_*` schemas (names in the registry table above).

> **Maintainer notes.** Launches with permissive Chromium flags
> (`ignore_https_errors`, `--disable-web-security`, disabled process isolation).
> `evaluate`, screenshots and PDFs are arbitrary-JS/arbitrary-write vectors.
> Requires the `playwright` package and browser download (not in
> `requirements.txt`). Async resources are not auto-closed except via
> `close_browser`.

#### `file_reader_tool.py` — `FileReaderTool`

Read-only extraction from many formats (`max_file_size` 50 MB).

- `read_file(path)` — dispatch by extension; unknown extensions are attempted as
  text.
- `read_pdf(path)` — lazy `pdfplumber`.
- `read_docx(path)` — `python-docx`; paragraphs + tables.
- `read_pptx(path)` — `python-pptx`; per-slide text + tables.
- `read_xlsx(path, sheet_name=None, max_rows=1000)` — `openpyxl` read-only;
  defaults to the first 5 sheets.
- `read_csv(path, delimiter=",", max_rows=1000)`.
- `read_json(path)`, `read_text(path, encoding="utf-8")` (latin-1 fallback).
- `list_files(directory=".", pattern="*", recursive=False)`.
- `get_file_info(path)`.
- Tools: `file_read`, `file_read_pdf`, `file_read_docx`, `file_read_pptx`,
  `file_read_xlsx`, `file_read_csv`, `file_read_json`, `file_read_text`,
  `file_list`, `file_info`.

Missing optional libraries yield an install-hint error dict rather than raising.

#### `word_tool.py` — `WordTool`

Create/edit `.docx` via `python-docx`.

- `create(path, title=None, content=None, author=None)`
- `read(path)`, `info(path)`
- `add_heading(path, text, level=1)`,
  `add_paragraph(path, text, bold=False, …, align=None)`,
  `add_bullet(path, text)`, `add_table(path, data, header=True)`
- `format(path, find=None, index=None, bold=None, …)`,
  `replace(path, old, new, replace_all=True)`,
  `delete_paragraph(path, index)`
- Helpers: `_resolve`, `_unavailable`, `_parse_color`, `_apply_run_style`,
  `_apply_alignment`, `_load`, `_save`, `_matches`, `_replace_in_paragraph`.
- Tools: the ten `word_*` names above.

`DOCX_AVAILABLE` guards the import; `_unavailable()` returns a friendly error.

#### `powerpoint_tool.py` — `PowerPointTool`

Create/edit `.pptx` via `python-pptx` (inch coordinates).

- `create(path, title=None, subtitle=None, author=None)`
- `read(path)`, `info(path)`
- `add_slide(path, title=None, bullets=None, layout="title_content")`,
  `add_text(...)`, `add_bullets(...)`, `add_table(...)`, `add_image(...)`,
  `format(...)`, `delete_slide(path, slide_index)`
- Helpers: `_resolve`, `_unavailable`, `_parse_color`, `_apply_run_style`,
  `_apply_alignment`, `_pick_layout`, `_content_placeholder`, `_slide_text`,
  `_load`, `_save`, `_slide_at`.
- Constants: `PPTX_AVAILABLE`, `_LAYOUT_INDEX`, `_ALIGNMENTS`.
- Tools: the ten `ppt_*` names above.

`delete_slide` uses the private `_sldIdLst` API (leaves orphan parts).

#### `excel_tool.py` — `ExcelTool`

Create/edit `.xlsx` via `openpyxl`.

- `create(path, sheets=None, headers=None)`, `read(path, sheet=None,
  cell_range=None, max_rows=None)`, `info(path)`
- `write_cell(path, cell, value, sheet=None, create_file=True)`,
  `write_rows(path, rows, start_cell="A1", sheet=None, header=None)`
- `set_formula(path, cell, formula, sheet=None)`
- `format(path, cell_range, sheet=None, bold=None, …, border=None)`
- `find(path, query, sheet=None, max_results=100)`,
  `stats(path, column, sheet=None, header=True)`
- `add_sheet(path, name)`, `delete_sheet(path, name)`
- `to_csv(path, out_path=None, sheet=None, delimiter=",")`,
  `csv_to_excel(csv_path, out_path=None, sheet="Sheet1", delimiter=",",
  header=True)`
- Helpers: `_resolve`, `_unavailable`, `_load`, `_load_or_create` (unused),
  `_sheet`, `_parse_cell`, `_cell_value`, `_hex`, `_jsonable`, `_font_attrs`,
  `_save`.
- Constants: `XLSX_AVAILABLE`.

`read` returns formulas as strings; `find`/`stats` use `data_only=True`.

---

## 11. Web application

The web wrapper is deliberately thin: it imports the core and drives it. It
serves a vanilla single-page frontend and exposes a small JSON/NDJSON API.

### 11.1 Launcher — `web/astra-web` / `start-dev.sh`

`web/astra-web` (bash, `set -euo pipefail`):

1. `CORE_DIR=repo/core`, `VENV_DIR=${ASTRA_VENV:-CORE/.venv}`,
   `PYTHON_BIN=${ASTRA_PYTHON:-VENV/bin/python}`.
2. Create the venv if missing (fails loudly if `ASTRA_PYTHON` is set but not
   executable).
3. Install `requirements.txt` if `import ollama` fails; install
   `web/requirements.txt` if `import fastapi, uvicorn` fails.
4. Determine the active provider via inline Python on `ai.settings`; if it is
   `ollama`, probe `${OLLAMA_HOST:-http://localhost:11434}/api/tags` with `curl`
   and print a warning when it is down. Non-Ollama providers get an informational
   line.
5. `exec "$PYTHON_BIN" backend/run.py "$@"`.

`start-dev.sh` is a 6-line repo-root alias that `exec`s `./web/astra-web "$@"`.

### 11.2 `web/backend/run.py`

- `_parse_args()` — `--host` (default `127.0.0.1`), `--port` (default `8765`),
  `--no-browser`, `--reload`.
- `main()` — import `uvicorn` (exit 1 with a pip hint if missing); print the URL;
  open a browser after 1.2 s unless `--no-browser`; run
  `uvicorn.run("backend.app:app", host, port, reload, app_dir=WEB_DIR)`.
- Inserts `web/` on `sys.path` so `backend.app` resolves.

### 11.3 `web/backend/astra_service.py`

**Module setup.** Computes `WEB_DIR`, `REPO_DIR`, `CORE_DIR`, `FRONTEND_DIR`;
inserts `CORE_DIR` on `sys.path`; **`os.chdir(CORE_DIR)`** (so the core's
CWD-relative DB/config/download paths match the terminal app); then imports
`ai.local_setup`, `ai.settings`, `ai.model.AgentModel`, `memory.chat_history`.

**Concurrency model (important).** The core is single-threaded and some
components (SQLite connections, the Playwright event loop) are thread-affine.
`AstraService` therefore:

- owns one persistent `ThreadPoolExecutor(max_workers=1,
  thread_name_prefix="astra-core")`;
- constructs the model **on** that worker thread;
- runs every core operation on it via `_call(operation, *args)` (which takes an
  `RLock`, submits, and blocks for the result);
- runs chat turns with the `RLock` held for the **entire turn**, bridging the
  worker to the HTTP response with a per-turn `queue.Queue`, and cancels via a
  `threading.Event` when the client disconnects;
- deliberately bypasses the worker+lock for `get_config`, `set_thinking`,
  `local_status` and `list_local_models` (settings has its own lock), so the
  settings panel stays responsive during a long reply;
- runs `stream_local_setup` on a separate daemon thread, marshalling only the
  final activation back onto the worker.

**Helpers.** `_build_model(model_name=None, provider=None)` resumes the most
recent session; `_latest_session_id()`; `_truncate(text, limit=MAX_RESULT_CHARS)`
with `MAX_RESULT_CHARS = 20_000`.

**Class `AstraService`**

- `__init__(model_name=None, provider=None)` — RLock + worker; builds the model
  on the worker; caches `model_name`/`provider_name`.
- `_call(operation, *args)`.
- Worker-bound operations: `_recover_session_if_missing` (recover a dead
  session id), `_op_current_session`, `_op_list_sessions`, `_op_create_session`,
  `_op_switch_session`, `_op_delete_session`, `_op_get_messages` (strips the
  system prompt), `_op_close`, `_op_set_provider`.
- Public proxies: `current_session()`, `list_sessions(limit=50)`,
  `create_session(title=None)`, `switch_session(id)`, `delete_session(id)`,
  `get_messages(id, limit=200)`, `close()` (shuts the executor).
- `get_config() -> dict` — `settings.to_public()` + live `describe()` + Ollama
  status.
- `set_provider(provider, model=None, api_key=None, base_url=None,
  thinking=None) -> dict` — persists then reconfigures the live model.
- `set_thinking(enabled) -> bool` — writes settings directly (returns the
  effective value).
- `local_status() -> dict` / `list_local_models() -> list`.
- `stream_local_setup(model, install=True)` — daemon thread + queue; emits
  `progress`/`result`/`config`/`error` events; activates on success.
- `stream_chat(prompt, session_id=None)` — blocking generator of event dicts;
  holds the lock; sets `stop_event` on disconnect.
- `_op_chat_turn(prompt, session_id, events, stop_event)` — recovers/switches the
  session, auto-titles brand-new conversations from the first prompt (≤60 chars),
  emits `session`, then forwards `thinking`/`content` and maps tool events to
  sequential ids (truncating large results), finally `done`/`error`.
- `run_message(prompt) -> {reply, session_id, error}` — drains `stream_chat` and
  returns just the reply text; backs the extension popup chat.
- `get_service() -> AstraService` — lazy process singleton under a lock.

**Browser bridge helpers.** `run_browser_message(message)` calls
`browser_bridge.run_message` (the route handler);
`register_browser_message_handler()` binds `get_service().run_message` as the
popup chat handler. `app.py`'s `lifespan` calls the latter at startup.

### 11.4 `web/backend/app.py`

FastAPI application. `lifespan` warms `get_service()` at startup so the first
request is fast and registers the browser-popup chat handler
(`register_browser_message_handler`). Static files are served from
`web/frontend` at `/static`; `/` returns `index.html`; `/favicon.ico` returns
the SVG.

Request models: `ChatRequest{message, session_id?}`,
`NewSessionRequest{title?}`, `SwitchRequest{session_id}`,
`ProviderRequest{provider, model?, api_key?, base_url?, thinking?}`,
`ThinkingRequest{thinking}`, `LocalSetupRequest{model, install=True}`,
`BrowserContextPayload`, `CommandResultPayload`, `BrowserMessagePayload{message}`.
See [§13](#13-http-api-reference) for the route table.

### 11.5 Generated files (`GET /api/files`)

The core resolves relative output paths against `core/` (downloads go to
`core/downloads/`), so `serve_generated_file` accepts an absolute path or a path
relative to `CORE_DIR`, resolves it, and refuses anything that is not a file
strictly inside `CORE_DIR` (traversal and host paths return `404`). Responses are
served inline.

---

## 12. Voice application

An **optional** local speech frontend (`voice/`). Like the web wrapper it embeds
the core and drives it; it adds a microphone and a speaker but no new server and
no new agent logic. Everything runs on-device. Full design in
[`voice/ARCHITECTURE.md`](voice/ARCHITECTURE.md); usage in
[`voice/README.md`](voice/README.md).

```
microphone ─▶ whisper.cpp (STT) ─▶ ASTRA agent ─▶ piper (TTS) ─▶ speaker
```

The default mode listens **continuously**: the microphone is opened per utterance,
an energy gate detects when you stop speaking, and that utterance is transcribed,
answered and spoken. `--push-to-talk` restores press-Enter-to-talk.

### 12.1 Launcher — `voice/astra-voice`

A bash launcher mirroring `web/astra-web`: it reuses
`VENV_DIR=${ASTRA_VENV:-core/.venv}`, installs the core dependencies if missing,
installs the **optional** audio extras (`sounddevice`, `numpy`) *best-effort*
(failure falls back to command-line audio), then `exec`s
`python voice/backend/run.py "$@"`.

### 12.2 `voice/backend/run.py`

Arg-parsing and mode dispatch. Modes: `--status`, `--setup`, `--file PATH`,
`--text TEXT`, `--say TEXT`, `--seconds N`, and the default **continuous
listening** loop (`--push-to-talk` switches to press-Enter-to-talk; `--listen` is
kept as a compatibility alias for the default). Flags: `--no-enter` (ignore the
Enter key in continuous mode), `--stt-only`, `--no-tts`, `--no-stream`, `--model`,
`--models-dir`. It validates the pieces the chosen mode needs via
`deps.build_status()` and exits with a clear message (and a non-zero code) when
something is missing.

### 12.3 `voice/backend/config.py` — `VoiceConfig`

Resolves every location env-first: `ASTRA_VOICE_WHISPER_BIN`,
`ASTRA_VOICE_STT_MODEL`, `ASTRA_VOICE_PIPER_BIN`, `ASTRA_VOICE_TTS_MODEL`,
`ASTRA_VOICE_MODELS_DIR`, `ASTRA_VOICE_LANG`, `ASTRA_VOICE_THREADS`,
`ASTRA_VOICE_INPUT_DEVICE`/`_OUTPUT_DEVICE`, `ASTRA_VOICE_AUDIO_BACKEND`,
`ASTRA_VOICE_KEEP_AUDIO`. Binaries fall back to a project-local build then
`PATH`; models are auto-discovered by glob (`ggml-*.bin` preferring `.en`,
`*.onnx`). Repository constants `VOICE_DIR`/`REPO_DIR`/`CORE_DIR`/`WEB_DIR` are
defined here.

### 12.4 `voice/backend/audio.py` — `AudioIO`

Two interchangeable backends: **sounddevice** (`sounddevice`+`numpy`) and **cli**
(`arecord`/`ffmpeg`/`rec` for capture, `aplay`/`ffplay`/`play` for playback).
`select_backend("auto")` prefers sounddevice. Key methods: `record(seconds?,
stop_event?)` (fixed length or Enter-terminated), `record_utterance(...)`
(energy-gate endpoint detection used by continuous listening on **both** backends;
the CLI path streams raw 16 kHz PCM and computes RMS with the stdlib `array`
module, so it needs no numpy. A `force_event` commits the utterance early — this
is how Enter-to-send works), `play(path)`, and the module-level
`ensure_wav16k(path)` which converts any input to whisper's required 16 kHz mono
16-bit PCM (no-op when already correct; uses `ffmpeg` or `sox`). `AudioError`
signals a hard failure.

### 12.5 `voice/backend/stt.py` — `WhisperCppSTT`

Invokes `whisper-cli -m MODEL -f WAV -otxt -of BASE -nt -l LANG [-t N]`, prefers
the `.txt` sidecar and falls back to stdout, then `clean_transcript()` strips
timestamps and non-speech markers (`[BLANK_AUDIO]`, `[Music]`, …). `WhisperError`
on missing binary / empty output.

### 12.6 `voice/backend/tts.py` — `PiperTTS`

Feeds text on stdin to `piper -m VOICE -f OUT [-s SPEAKER]` and returns the WAV
path. `PiperError` on failure or empty text.

### 12.7 `voice/backend/agent.py` — `VoiceAgent`

The bridge to the core. It reuses `web.backend.astra_service.AstraService`
(added to `sys.path` via `REPO_DIR`) so the thread-affine core handling is not
duplicated and provider/model selection stays shared. `ask(prompt, on_delta,
on_tool)` consumes `AstraService.stream_chat()` and returns
`{reply, error, session_id, tools}`; `on_delta` receives content fragments for
live printing. `AgentError` wraps initialisation failures.

### 12.8 `voice/backend/voice_loop.py` — `VoiceLoop`

Orchestrates a turn: `handle_wav()` (transcribe → answer → speak) and
`handle_text()`. Interaction modes: `run_continuous()` (the default — keeps
listening, answers when the user stops talking, prints a `🎤 listening…`
indicator on a TTY, and retries a microphone error a few times before giving up)
and `run_interactive()` (push-to-talk; typing sends text; `q` quits). In
continuous mode an Enter watcher thread (`_start_enter_watcher`) sets a
`force_event` so pressing Enter sends early; `_NoEcho` (termios) hides the
keypress while listening and is always restored. A failed utterance or TTS hiccup
is reported and the loop continues. `_paint()` provides optional ANSI colour.

### 12.9 `voice/backend/deps.py`

`build_status(config)` returns a `VoiceStatus` (readiness flags, resolved paths,
`problems`, `notes`); `format_status()` renders the `--status` report. `stt` and
`audio` are required for a conversation; `tts` is optional (degradation note
added automatically).

### 12.10 `voice/backend/install.py`

`--setup`. `build_whisper_cpp()` (git clone + cmake, with manual instructions
when tools are missing), `ensure_whisper_model()` (Hugging Face `ggml-*.bin`),
`install_piper()` (platform release asset into `voice/models/piper/`), and
`ensure_piper_voice()` (Hugging Face `.onnx` + `.onnx.json`). Idempotent and
network-failure tolerant.

### 12.11 Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ASTRA_VOICE_WHISPER_BIN` | autodetect | whisper.cpp CLI |
| `ASTRA_VOICE_STT_MODEL` | autodetect | `ggml-*.bin` model |
| `ASTRA_VOICE_PIPER_BIN` | autodetect | `piper` binary |
| `ASTRA_VOICE_TTS_MODEL` | autodetect | piper `.onnx` voice |
| `ASTRA_VOICE_MODELS_DIR` | `voice/models` | model directory |
| `ASTRA_VOICE_LANG` | `en` | whisper language |
| `ASTRA_VOICE_THREADS` | whisper default | whisper thread count |
| `ASTRA_VOICE_INPUT_DEVICE` / `ASTRA_VOICE_OUTPUT_DEVICE` | system default | audio devices |
| `ASTRA_VOICE_AUDIO_BACKEND` | `auto` | `auto`/`sounddevice`/`cli` |
| `ASTRA_VOICE_VAD_THRESHOLD` | `0` (auto) | energy gate for endpoint detection |
| `ASTRA_VOICE_SILENCE` | `0.8` | seconds of silence that ends an utterance |
| `ASTRA_VOICE_MAX_UTTERANCE` | `15` | max seconds for one utterance |
| `ASTRA_VOICE_ENTER_SEND` | on | press Enter to send early (continuous mode) |
| `ASTRA_VOICE_KEEP_AUDIO` | off | keep temporary WAVs |

---

## 13. HTTP API reference

All endpoints are on the FastAPI app. JSON bodies unless noted.

| Method | Path | Request | Response |
|--------|------|---------|----------|
| `GET` | `/api/health` | — | `{status, model, provider, session_id}` |
| `GET` | `/api/providers` | — | config snapshot (keys masked) |
| `POST` | `/api/providers` | `ProviderRequest` | `{ok, live, config}` |
| `POST` | `/api/thinking` | `ThinkingRequest` | `{ok, thinking, config}` |
| `GET` | `/api/providers/ollama/status` | — | `{installed, running, version, host, models, recommended}` |
| `POST` | `/api/providers/ollama/setup` | `LocalSetupRequest` | NDJSON stream |
| `GET` | `/api/sessions` | — | `{session_id, sessions}` |
| `POST` | `/api/sessions` | `NewSessionRequest?` | `{session_id}` |
| `POST` | `/api/sessions/switch` | `SwitchRequest` | `{session_id}` (404 if absent) |
| `DELETE` | `/api/sessions/{id}` | — | `{ok, session_id}` (404 if absent) |
| `GET` | `/api/sessions/{id}/messages` | — | `{session_id, messages}` |
| `POST` | `/api/chat` | `ChatRequest` | NDJSON stream (400 if empty) |
| `POST` | `/api/browser/context` | `BrowserContextPayload` | `{ok, received_at}` |
| `GET` | `/api/browser/context` | — | `{context}` (latest page snapshot or `null`) |
| `DELETE` | `/api/browser/context` | — | `{ok}` |
| `GET` | `/api/browser/commands` | — | `{command}` (`{id, name, arguments}` or `null`) |
| `POST` | `/api/browser/commands/{id}/result` | `CommandResultPayload` | `{accepted}` (404 if unknown/finished) |
| `POST` | `/api/browser/message` | `BrowserMessagePayload` | `{ok, reply, error, session_id}` (extension popup chat) |
| `GET` | `/api/files?path=…` | — | file (inline) or 404 |
| `GET` | `/` | — | `index.html` |
| `GET` | `/favicon.ico` | — | `favicon.svg` or 404 |

### Chat stream events

Each line of an NDJSON response is a JSON object with a `type`:

| Type | Payload | Meaning |
|------|---------|---------|
| `session` | `session_id` | Active conversation for this turn |
| `thinking` | `delta` | Reasoning tokens |
| `content` | `delta` | Answer tokens |
| `tool_call` | `id`, `name`, `arguments` | Model requested a tool |
| `tool_result` | `id`, `name`, `success`, `result` | Tool finished (result truncated to 20 000 chars) |
| `error` | `message` | Something failed |
| `done` | `session_id` | Turn finished |

The Ollama setup stream emits `progress` (`message`), `result` (`ok`, `model`),
`config` and `error` events.

### Examples

```bash
# Health & provider snapshot
curl -s http://127.0.0.1:8765/api/health | jq
curl -s http://127.0.0.1:8765/api/providers | jq

# Activate a cloud provider and store its key
curl -s -X POST http://127.0.0.1:8765/api/providers \
  -H 'Content-Type: application/json' \
  -d '{"provider":"openai","model":"gpt-4o-mini","api_key":"sk-…"}' | jq

# Toggle thinking
curl -s -X POST http://127.0.0.1:8765/api/thinking \
  -H 'Content-Type: application/json' -d '{"thinking":false}' | jq

# Chat (streams NDJSON)
curl -N -s -X POST http://127.0.0.1:8765/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Summarize photosynthesis"}'
```

---

## 14. Frontend reference

The frontend is a dependency-free single-page app in `web/frontend/`. All code is
inside one IIFE in `app.js`.

### 14.1 `index.html`

Structural shell:

- `.app` flex container.
  - `aside#sidebar` — brand, `#new-chat`, `#session-list`, footer with
    `#status-dot`/`#status-text` and `#model-badge`.
  - `div#scrim` — mobile drawer scrim.
  - `main.chat` — header (`#menu-toggle`, `#chat-title-text`, `#settings-btn`,
    `#header-model`), `#messages` (with `#empty-state` and suggestion buttons),
    and the composer (`#input`, `#send`, `#stop`, `#composer-hint`).
- Settings panel: `#settings-scrim` + `aside.settings-panel#settings-modal`
  containing `#settings-close` and `#settings-body`.
- `#toast-wrap` for notifications.

### 14.2 `app.js`

**Global state:** `currentSessionId`, `streaming`, `abortController`,
`sessionsCache`, `settingsConfig`, `selectedProvider`.

**Helpers**

- `$(id)` — `getElementById` shorthand.
- `escapeHtml(s)` — entity-escape `&<>"'`.
- `toolIcon(name)` — regex→emoji map per tool family (🧠 memory, 🖥️ shell,
  🌐 web, 🧭 browser, 🎭 playwright, 📄 file, 📝 word, 📊 ppt, 📈 excel).
- `formatArgs(args)` — parse/pretty-print tool arguments.
- `formatDate(value)` — relative ("just now", "5m ago", …) or locale date.
- `scrollToBottom()`.

**File links.** `FILE_PATH_RE` combines regexes for absolute, relative and bare
paths by extension. `linkifyFilePaths(root)` walks text nodes
(`document.createTreeWalker`) and `linkifyTextNode(node)` replaces matches with
`<a class="file-link" href="/api/files?path=…">`.

**Markdown.** `renderMarkdown(md)` is a hand-rolled parser: code fences are
stashed behind `\u0000C{i}\u0000` placeholders, the rest is escaped, then inline
code/emphasis/links/autolinks are applied, followed by line-based headings
(`#`–`###`), unordered/ordered lists, blockquotes, horizontal rules and
paragraphs.

**API / sessions.** `api(path, options)` wraps `fetch` and throws on non-OK
(using `detail` when present). `renderSessions`, `refreshSessions`,
`updateTitle`, `loadMessages`, `selectSession`, `createSession`,
`deleteSession` manage the conversation list and transcript.

**Streaming.** `sendMessage(text)`:

1. Renders the user turn and an assistant turn, disables input, shows **Stop**.
2. `POST /api/chat` with an `AbortController`.
3. Reads `res.body.getReader()` + `TextDecoder`, accumulates a buffer, splits on
   `\n`, `JSON.parse`s each complete line and dispatches via `handleEvent`.
4. In `finally`: finalize the turn, re-enable input, refresh the session list.

`handleEvent(evt, turn)` dispatches `session`/`thinking`/`content`/`tool_call`/
`tool_result`/`error`/`done`. Turn rendering uses
`appendThinking` (collapsible "Reasoning" `<details>`), `appendContent`
(rAF-coalesced markdown), `addToolCard`/`completeToolCard` (spinner → ok/fail with
details), `appendError`, and `finalizeTurn` (flush pending render, close the
cursor, fall back to "(no response)"). `renderHistory(messages)` rebuilds a
persisted transcript, re-pairing tool cards with `role: "tool"` messages.

**Composer / sidebar.** `autoResize`, Enter-to-send (Shift+Enter newline), the
`.suggestions` buttons, and `openSidebar`/`closeSidebar` for the mobile drawer.

**Settings panel.** `el(tag, props, children)` is a tiny DOM builder;
`fieldEl(label, input, hint)` a labelled field. The panel is config-driven:

- `applyConfigToUI(cfg)` updates the header badge, model badge and composer hint.
- `renderThinkingRow(cfg)` builds the Thinking checkbox, disabled/locked when
  `cfg.thinking_from_env`; on change it `POST`s `/api/thinking`, toasts and
  re-renders.
- `renderSettings()` draws the active banner, the thinking row, the provider grid
  (status per provider), and the section for `selectedProvider`.
- `renderCloudSection(section, cfg, name)` — API key + model + advanced base URL
  form with a **Connect & activate** / **Save changes** button.
- `renderOllamaSection(section, cfg)` — running state, installed-model chips
  (tap to activate), recommended-model chips, an "install automatically"
  checkbox, an **Install & download** button, a progress bar and a live log.
- `activateModel(provider, model)` and `runLocalSetup(...)` (streams
  `/api/providers/ollama/setup` NDJSON, driving the progress bar from `%`).
- `toggleSettings`/`openSettings`/`closeSettings` (also closed by the scrim and
  `Esc`), `toast(message, kind)`, `checkHealth()`, and `init()` (health →
  sessions → messages → config → focus).

### 14.3 `styles.css`

Black + gold theme driven by CSS variables in `:root`:

- Backgrounds: `--bg #000`, `--bg-soft #050505`, panels `#0c0c0c`/`#131313`/
  `#1b1b1b`; borders `#2a2a2a`/`#1d1d1d`.
- Text: `#f7f4e9` / `#d6d2c2` / `#8d8d8d` (muted); accent `--accent #facc15`,
  `--accent-2 #fde047`, `--accent-strong #eab308`.
- Status: `--green`, `--red`, `--amber`; radii, shadows, fonts and a mono font.

Major component groups: sidebar/brand/new-chat/session list; chat header/messages;
turns (`.turn`, `.avatar`, `.bubble`); markdown (`.md`); thinking panel; tool cards
(`.tool*`, `.spinner`, `.tool-status`); file links (`.file-link`); empty state and
suggestions; composer + error lines; scrollbars; responsive rules at `@820px`
(sliding sidebar/scrim) and `@560px`; the settings panel (`.settings-panel*`,
`.active-banner`, `.provider-grid`/`.provider-card`/`.pc-*`, fields/chips/buttons,
callouts, `.thinking-row`, progress and setup log); and toasts.

### 14.4 `favicon.svg`

A 64×64 black rounded square with a gold gradient inner square and a bold black
"A".

---

## 15. Utilities & assets

- **`core/utils/colors.py`** — `Colors` ANSI constants (`RESET`, `BOLD`, `DIM`,
  foregrounds, backgrounds); `colorize(text, color)`; and wrappers `error`,
  `success`, `warning`, `info`, `title`, `dim`, `user_msg`, `important`,
  `secondary`, `bold`. Imported as `from utils.colors import …`.
- **`core/config/identity.txt`** — the system prompt. It establishes ASTRA as an
  academic assistant, states that ASTRA is the identity (not the underlying
  model), forbids fabricating sources/capabilities, and encourages teaching over
  answer-dumping. Loaded by `AgentModel._load_system_prompt()` with a fallback
  string.
- **`requirements.txt` / `web/requirements.txt`** — dependency manifests.
- **`.gitignore`** — ignores Python artifacts, virtualenvs, `*.db`/`*.sqlite*`,
  `core/config/settings.json`, `downloads/`, editor/OS files and logs.

### Import-path note

Core modules import each other as top-level namespace packages (`from ai.model
import AgentModel`, `from tools.tool_registry import …`, `from utils.colors import
…`). This works only when `core/` is on `sys.path` **and** is the intended CWD
(which both entry points guarantee). There is no packaging/`setup.py`; the code
is run from source.

---

## 16. Development guide

### Adding a provider

1. Add the id to `PROVIDERS`, `DEFAULT_MODELS`, `DEFAULT_BASE_URLS`,
   `PROVIDER_LABELS`, and (if keyed) `_KEY_ENV`/`_BASE_ENV` in
   `core/ai/settings.py`.
2. Create `core/ai/providers/<name>_provider.py` subclassing `Provider` with a
   `stream_chat` that yields normalized `Chunk`s, plus a message-translation
   helper if needed.
3. Register it in `_PROVIDER_CLASSES` in `core/ai/providers/__init__.py` and add
   it to `KEYED_PROVIDERS` if it authenticates with a key.
4. Optionally surface it in the web provider grid (the frontend renders whatever
   `to_public()` returns, so usually no change is required).

The agent loop needs no changes.

### Adding a tool

1. Create a tool class in `core/tools/` exposing `get_tools()` (OpenAI schemas)
   and `self.functions = {tool_name: method}`.
2. Instantiate it in `ToolRegistry._register_all_tools()`.
3. Add a `ToolCategory` (keywords + tool names) so relevance filtering can select
   it. Keep the number of tools per category within `MAX_TOOLS`.

### Adding an HTTP endpoint

Add the route in `web/backend/app.py`. If it touches the core, add a worker-bound
`_op_*` method plus a public proxy on `AstraService`; if it only touches
settings, call `get_settings()` directly as `get_config`/`set_thinking` do.

### Testing manually

There is no checked-in test suite. The architecture doc has runnable snippets;
useful patterns:

```bash
# Settings precedence (use a temp ASTRA_SETTINGS_PATH)
ASTRA_SETTINGS_PATH=/tmp/s.json python - <<'PY'
from ai import settings
s = settings.Settings()
print(s.thinking(), s.thinking_source())
PY

# Session persistence round-trip
python - <<'PY'
from ai.model import AgentModel
m1 = AgentModel(); sid = m1.session_id
m1.chat_history.add_message(sid, "user", "test"); m1.close()
m2 = AgentModel(session_id=sid); print(len(m2.history)); m2.close()
PY

# Provider switch without network calls
python - <<'PY'
from ai.model import AgentModel
m = AgentModel(); print(m.describe())
m.reconfigure('openai', 'gpt-4o-mini'); print(m.describe()); m.close()
PY
```

### Hot reload

Frontend edits are picked up on refresh (files are served from disk). Backend
edits need a restart; `run.py --reload` enables uvicorn auto-reload for
development.

---

## 17. Data & file locations

| Data | Default location | Override |
|------|------------------|----------|
| Conversations | `core/memory/chat_history.db` | `ASTRA_DB_PATH` |
| Long-term memory | `core/memory/astra.db` | constructor arg only |
| Provider config | `core/config/settings.json` | `ASTRA_SETTINGS_PATH` |
| Downloads / generated files | `core/downloads/` | tool argument |
| Virtualenv | `core/.venv` | `ASTRA_VENV` |
| Python binary | `core/.venv/bin/python` | `ASTRA_PYTHON` |
| Speech models (voice) | `voice/models/` (git-ignored) | `ASTRA_VOICE_MODELS_DIR` |

---

## 18. Security & privacy

- **Keys** are stored only in `core/config/settings.json`, which is git-ignored
  and written with mode `600`. The web backend only ever returns a masked form
  (`sk-a…f3d9`); the raw key never leaves the Python process.
- **Env vars** always win over the file, which is convenient for CI/deployments
  but means an exported key silently overrides a saved one.
- **File serving** (`GET /api/files`) is confined to `core/`; traversal and host
  paths return `404`.
- **Shell tool** executes arbitrary commands via `subprocess(shell=True)` with no
  sandbox — it is a local trusted-user feature.
- **Web tools** can reach arbitrary URLs (SSRF) and download files derived from
  server-provided filenames.
- **Playwright** runs with permissive Chromium flags and exposes `evaluate`
  (arbitrary JS) plus screenshot/PDF writes.
- **Cloud calls** go directly to the configured provider; nothing is proxied and
  no telemetry is added.

---

## 19. Known limitations & technical debt

These are accurate as of the last update and are good first tasks for a new
maintainer.

- **Optional deps not declared.** `pdfplumber` (PDF reading) and `playwright`
  (browser automation) are imported but absent from `requirements.txt`.
  `playwright_tool.py` imports `playwright` at module import time with no
  fallback, so a missing package can break tool-registry construction.
- **`MAX_TOOLS` vs. the playwright category.** 25 playwright tools exceed the
  cap; they can never all be offered in one query, and the naive keyword scoring
  may not select the useful ones.
- **Naive relevance filtering.** Categories are scored by substring counts only.
- **Long-term memory DB path is not configurable** via env (constructor arg
  only).
- **Shared SQLite connection** in `ChatHistory` (`check_same_thread=False`) is
  used unsynchronized; the web layer serializes access onto one thread, but the
  class itself is not thread-safe.
- **`list_sessions_with_preview` is N+1** (a per-session count/preview query).
- **`/s` without a trailing space** is not routed by the REPL (`startswith("/s ")`).
- **Masked display semantics.** `Settings.to_public()["providers"][ollama]
  ["configured"]` is hard-wired `True` (local needs no key).
- **Dead code.** `_ErrorChunk`/`AgentModel._error_chunk`, `ExcelTool._load_or_create`,
  and several unused color/typing imports remain.
- **Frontend duplication of session state.** `currentSessionId` is tracked
  client-side and on the server; recovery logic exists on both sides.
- **Voice frontends are separate processes.** `voice/astra-voice` embeds the core
  like `web/`; running it alongside the terminal or web app yields independent
  in-memory sessions (they share only the SQLite history file). Run one frontend
  at a time for a single live conversation.
- **Voice speech stack is not exercised by tests.** whisper.cpp/piper are
  external binaries invoked per turn; use `--status` and `--file` for manual
  verification.
- **No automated test suite** is checked in.

---

## 20. Troubleshooting

**"Ollama does not appear to be running."** Start it (`ollama serve`) or switch
provider. Web: Settings → Local (Ollama) → Install & download. Terminal:
`/provider local_setup`.

**Cloud provider authentication errors.** Confirm the key is saved and not
overridden by an environment variable. `/provider status` shows the key source
(`env` vs config file); env always wins.

**The model I typed isn't used.** `ASTRA_MODEL`/`ASTRA_PROVIDER` may be set in the
environment and override the saved value; the web UI flags environment-locked
settings.

**Automatic Ollama install failed.** Install manually from
<https://ollama.com/download>, then run `/provider local`. On Linux the installer
needs `curl`; macOS uses Homebrew; Windows uses `winget`.

**Thinking toggle has no effect.** Only reasoning-capable backends act on it
(chiefly Ollama models such as `qwen3`). OpenAI/Anthropic ignore the flag; Gemini
thought parts are captured automatically. If `ASTRA_THINKING` is set, it wins and
the toggle is shown locked.

**Generated files / downloads.** They live under `core/` (`core/downloads/`). The
web UI turns recognized paths into download pills; `/api/files` refuses anything
outside `core/`.

**Where is my data?** Conversations: `core/memory/chat_history.db` (override with
`ASTRA_DB_PATH`). Provider config: `core/config/settings.json` (override with
`ASTRA_SETTINGS_PATH`).

**Frontend change isn't visible.** Hard-refresh; backend changes require a
restart (`run.py --reload` for auto-reload).

**Voice mode hears nothing / cuts off mid-sentence.** Continuous listening
calibrates ambient noise and ends an utterance on a pause. In a noisy room or with
a quiet mic, raise `ASTRA_VOICE_VAD_THRESHOLD` (e.g. `400`) or increase
`ASTRA_VOICE_SILENCE`; press **Enter** to send early, or use `--push-to-talk` to
skip endpoint detection entirely. `--status` shows which audio backend was
selected.

---

## 21. Glossary

| Term | Meaning |
|------|---------|
| **Agent loop** | The `while` loop in `AgentModel.generate` that streams a response, executes tool calls and repeats until the model stops asking for tools. |
| **Chunk** | A single normalized piece of a streamed model response (`content`, `thinking`, or `tool_calls`). |
| **Provider** | A backend adapter (`ollama`/`openai`/`anthropic`/`gemini`) that translates history and yields chunks. |
| **Tool** | A callable capability exposed to the model as an OpenAI-style function schema (`web_search`, `word_create`, …). |
| **Tool category** | A keyword-scored group used to select relevant tools per query. |
| **Session** | A conversation row in `conversations`, identified by `session_<12 hex>`. |
| **Thinking** | Optional reasoning output (chain-of-thought) streamed before the answer; controlled by `thinking`/`ASTRA_THINKING`. |
| **local_setup** | The flow that installs Ollama and pulls a model. |
| **Masked key** | The `first4…last4` form the API returns instead of the real API key. |
| **Worker thread** | The single persistent thread on which the web service runs all core operations. |

---

## Appendix A. Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ASTRA_PROVIDER` | `ollama` | Active provider (`ollama`/`openai`/`anthropic`/`gemini`) |
| `ASTRA_MODEL` | per provider | Model for the active provider |
| `ASTRA_THINKING` | `true` | Reasoning on/off (`1/0`, `on/off`, `true/false`) |
| `ASTRA_OPENAI_API_KEY` / `OPENAI_API_KEY` | — | OpenAI key |
| `ASTRA_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY` | — | Anthropic key |
| `ASTRA_GEMINI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY` | — | Gemini key |
| `ASTRA_OLLAMA_HOST` / `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |
| `ASTRA_OPENAI_BASE_URL` / `OPENAI_BASE_URL` | OpenAI default | OpenAI-compatible endpoint |
| `ASTRA_ANTHROPIC_BASE_URL` | Anthropic default | Endpoint override |
| `ASTRA_GEMINI_BASE_URL` | Gemini default | Endpoint override |
| `ASTRA_SETTINGS_PATH` | `core/config/settings.json` | Settings file location |
| `ASTRA_DB_PATH` | `core/memory/chat_history.db` | Conversation DB location |
| `ASTRA_VENV` | `core/.venv` | Virtualenv used by the launcher |
| `ASTRA_PYTHON` | venv python | Explicit Python binary |
| `ASTRA_VOICE_WHISPER_BIN` | autodetect | whisper.cpp CLI (voice) |
| `ASTRA_VOICE_STT_MODEL` | autodetect | whisper `ggml-*.bin` model (voice) |
| `ASTRA_VOICE_PIPER_BIN` | autodetect | `piper` binary (voice) |
| `ASTRA_VOICE_TTS_MODEL` | autodetect | piper `.onnx` voice (voice) |
| `ASTRA_VOICE_MODELS_DIR` | `voice/models` | Speech model directory (voice) |
| `ASTRA_VOICE_LANG` | `en` | whisper language code (voice) |
| `ASTRA_VOICE_THREADS` | whisper default | whisper thread count (voice) |
| `ASTRA_VOICE_INPUT_DEVICE` / `ASTRA_VOICE_OUTPUT_DEVICE` | system default | audio devices (voice) |
| `ASTRA_VOICE_AUDIO_BACKEND` | `auto` | `auto`/`sounddevice`/`cli` (voice) |
| `ASTRA_VOICE_VAD_THRESHOLD` | `0` (auto) | energy gate for endpoint detection (voice) |
| `ASTRA_VOICE_SILENCE` | `0.8` | seconds of silence that ends an utterance (voice) |
| `ASTRA_VOICE_MAX_UTTERANCE` | `15` | max seconds for one utterance (voice) |
| `ASTRA_VOICE_ENTER_SEND` | on | press Enter to send early (voice) |
| `ASTRA_VOICE_KEEP_AUDIO` | off | keep temporary WAVs (voice) |

Provider/model aliases: `local`→`ollama`, `gpt`→`openai`, `claude`→`anthropic`,
`google`/`google-gemini`→`gemini`.

---

## Appendix B. Tool catalog

| Domain | Tool names |
|--------|-----------|
| Memory | `memory_remember`, `memory_search`, `memory_forget` |
| Shell & files | `shell_exec`, `shell_read`, `shell_write`, `shell_list`, `shell_glob`, `shell_exists` |
| Web (HTTP) | `web_search`, `web_fetch`, `web_download`, `web_crawl`, `web_find_files` |
| Browser (HTTP+BS4) | `browser_open`, `browser_back`, `browser_status`, `browser_text`, `browser_links`, `browser_click`, `browser_extract`, `browser_forms`, `browser_fill`, `browser_submit`, `browser_search` |
| Browser (Playwright) | `playwright_open`, `playwright_close`, `playwright_navigate`, `playwright_click`, `playwright_type`, `playwright_fill`, `playwright_select`, `playwright_wait`, `playwright_extract`, `playwright_screenshot`, `playwright_pdf`, `playwright_eval`, `playwright_scroll`, `playwright_hover`, `playwright_press`, `playwright_get_text`, `playwright_get_html`, `playwright_get_url`, `playwright_get_title`, `playwright_go_back`, `playwright_go_forward`, `playwright_reload`, `playwright_new_tab`, `playwright_switch_tab`, `playwright_close_tab` |
| File readers | `file_read`, `file_read_pdf`, `file_read_docx`, `file_read_pptx`, `file_read_xlsx`, `file_read_csv`, `file_read_json`, `file_read_text`, `file_list`, `file_info` |
| Word | `word_create`, `word_read`, `word_info`, `word_add_heading`, `word_add_paragraph`, `word_add_bullet`, `word_add_table`, `word_format`, `word_replace`, `word_delete_paragraph` |
| PowerPoint | `ppt_create`, `ppt_read`, `ppt_info`, `ppt_add_slide`, `ppt_add_text`, `ppt_add_bullets`, `ppt_add_table`, `ppt_add_image`, `ppt_format`, `ppt_delete_slide` |
| Excel | `excel_create`, `excel_read`, `excel_info`, `excel_write`, `excel_write_rows`, `excel_format`, `excel_formula`, `excel_find`, `excel_stats`, `excel_add_sheet`, `excel_delete_sheet`, `excel_to_csv`, `csv_to_excel` |

---

## Appendix C. HTTP API

| Method | Path | Streaming | Purpose |
|--------|------|-----------|---------|
| `GET` | `/api/health` | no | Status + active provider/model |
| `GET` | `/api/providers` | no | Provider config (masked) |
| `POST` | `/api/providers` | no | Activate provider/model, save key/URL |
| `POST` | `/api/thinking` | no | Toggle reasoning |
| `GET` | `/api/providers/ollama/status` | no | Ollama install/run + models |
| `POST` | `/api/providers/ollama/setup` | NDJSON | Install Ollama + pull model |
| `GET` | `/api/sessions` | no | List conversations |
| `POST` | `/api/sessions` | no | Create conversation |
| `POST` | `/api/sessions/switch` | no | Switch conversation |
| `DELETE` | `/api/sessions/{id}` | no | Delete conversation |
| `GET` | `/api/sessions/{id}/messages` | no | Message history |
| `POST` | `/api/chat` | NDJSON | Stream a chat turn |
| `POST` | `/api/browser/context` | no | Receive a page snapshot from the ASTRA Firefox extension |
| `GET` | `/api/browser/context` | no | Latest page snapshot |
| `DELETE` | `/api/browser/context` | no | Forget the page snapshot |
| `GET` | `/api/browser/commands` | no | Extension claims the next queued browser command |
| `POST` | `/api/browser/commands/{id}/result` | no | Extension reports a command's result |
| `POST` | `/api/browser/message` | no | Extension popup sends a chat message to the running agent |
| `GET` | `/api/files` | no | Serve a generated file |

---

## Appendix D. Symbol index

A quick map of the most important symbols to their files.

| Symbol | File |
|--------|------|
| `Chat` | `core/agent/chat.py` |
| `SessionController` | `core/controller/session_controller.py` |
| `ProviderController` | `core/controller/provider_controller.py` |
| `AgentModel`, `_ErrorChunk` | `core/ai/model.py` |
| `Settings`, `get_settings`, `normalize_provider`, `_parse_bool`, `default_settings_path` | `core/ai/settings.py` |
| `Provider`, `ProviderError`, `Chunk`, `ResponseMessage`, `ToolCall`, `FunctionCall`, `parse_arguments`, `iter_sse_data` | `core/ai/providers/base.py` |
| `get_provider`, `KEYED_PROVIDERS` | `core/ai/providers/__init__.py` |
| `OllamaProvider` | `core/ai/providers/ollama_provider.py` |
| `OpenAIProvider`, `to_openai_messages` | `core/ai/providers/openai_provider.py` |
| `AnthropicProvider`, `to_anthropic`, `to_anthropic_tools` | `core/ai/providers/anthropic_provider.py` |
| `GeminiProvider`, `to_gemini`, `to_gemini_tools`, `sanitize_schema` | `core/ai/providers/gemini_provider.py` |
| `install_and_pull`, `local_status`, `list_local_models`, `RECOMMENDED_MODELS` | `core/ai/local_setup.py` |
| `OllamaModel` (shim) | `core/ai/ollama.py` |
| `ChatHistory` | `core/memory/chat_history.py` |
| `Memory` | `core/memory/memory.py` |
| `ToolRegistry`, `ToolCategory`, `get_tool_registry` | `core/tools/tool_registry.py` |
| `MemoryTool` | `core/tools/memory_tool.py` |
| `ShellTool` | `core/tools/shell_tool.py` |
| `WebTool` | `core/tools/web_tool.py` |
| `BrowserTool` | `core/tools/browser_tool.py` |
| `BrowserContextTool` | `core/tools/browser_context_tool.py` |
| `BrowserControlTool` | `core/tools/browser_control_tool.py` |
| `set_context`, `get_context`, `clear_context` | `core/browser_bridge.py` |
| `enqueue_command`, `next_command`, `submit_command_result` | `core/browser_bridge.py` |
| `set_message_handler`, `run_message` | `core/browser_bridge.py` |
| `start_browser_context_server`, `browser_bridge_endpoint` | `core/browser_server.py` |
| `PlaywrightBrowserTool` | `core/tools/playwright_tool.py` |
| `FileReaderTool` | `core/tools/file_reader_tool.py` |
| `WordTool` | `core/tools/word_tool.py` |
| `PowerPointTool` | `core/tools/powerpoint_tool.py` |
| `ExcelTool` | `core/tools/excel_tool.py` |
| `Colors`, `colorize`, color helpers | `core/utils/colors.py` |
| `app`, route handlers | `web/backend/app.py` |
| `AstraService`, `get_service`, `run_browser_message`, `register_browser_message_handler` | `web/backend/astra_service.py` |
| `main`, `_parse_args` | `web/backend/run.py` |
| `VoiceConfig`, `from_env` | `voice/backend/config.py` |
| `build_status`, `format_status`, `VoiceStatus` | `voice/backend/deps.py` |
| `AudioIO`, `ensure_wav16k`, `select_backend`, `AudioError` | `voice/backend/audio.py` |
| `WhisperCppSTT`, `clean_transcript`, `WhisperError` | `voice/backend/stt.py` |
| `PiperTTS`, `PiperError` | `voice/backend/tts.py` |
| `VoiceAgent`, `AgentError` | `voice/backend/agent.py` |
| `VoiceLoop` (`run_continuous`, `run_interactive`) | `voice/backend/voice_loop.py` |
| `main`, `build_whisper_cpp`, `ensure_whisper_model`, `install_piper`, `ensure_piper_voice` | `voice/backend/install.py` |
| `main`, `_parse_args` | `voice/backend/run.py` |
