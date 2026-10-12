# ASTRA Documentation

ASTRA is an AI academic assistant. It ships as a **standalone terminal
application** (`core/`) with an optional **web wrapper** (`web/`) that runs the
exact same core in a browser. It is fully **model- and provider-agnostic**:

- run locally through [Ollama](https://ollama.com), or
- use a cloud provider — **OpenAI**, **Anthropic (Claude)**, or **Google
  (Gemini)** — with your own API key.

Nothing about the model is hard-coded. Pick a backend once and it is shared by
both the terminal app and the web UI, because they both read the same
configuration (`core/ai/settings.py`).

---

## Table of contents

1. [Requirements](#1-requirements)
2. [Install & run](#2-install--run)
3. [Choosing a provider & model](#3-choosing-a-provider--model)
4. [The `local_setup` flow](#4-the-local_setup-flow)
5. [Web app](#5-web-app)
6. [Configuration reference](#6-configuration-reference)
7. [Terminal commands](#7-terminal-commands)
8. [Architecture](#8-architecture)
9. [Web API](#9-web-api)
10. [Troubleshooting](#10-troubleshooting)
11. [Security & privacy](#11-security--privacy)

---

## 1. Requirements

- **Python 3.10+** (developed and tested on Python 3.14).
- A terminal. The web app is served locally and needs no Node/npm build step.
- **Nothing else is mandatory.** Ollama is only needed if you want to run models
  locally; cloud providers need only an API key.

Python dependencies (installed automatically by the launcher) are listed in:

- [`requirements.txt`](requirements.txt) — core (Ollama client, `requests`, web
  scraping/parsing, document generation, `rich`).
- [`web/requirements.txt`](web/requirements.txt) — web backend (`fastapi`,
  `uvicorn`).

> ASTRA deliberately does **not** depend on the `openai`, `anthropic`, or
> `google-genai` SDKs. Cloud providers are called directly over HTTPS, which
> keeps the install lightweight and avoids version churn.

---

## 2. Install & run

Clone the repository, then start the web app:

```bash
git clone https://github.com/prasonkc/ASTRA.git
cd ASTRA
./web/astra-web
```

On first run the launcher will:

1. create a virtual environment at `core/.venv` (override with `ASTRA_VENV`),
2. install the core and web dependencies,
3. check whether the **active** provider is reachable (it only nags about Ollama
   when Ollama is actually selected), and
4. start the server at <http://127.0.0.1:8765> and open your browser.

Useful flags:

```bash
./web/astra-web --no-browser      # don't open a browser
./web/astra-web --port 9000       # custom port
./start-dev.sh                    # repo-root alias for ./web/astra-web
```

### Running the terminal app

The terminal app is the source of truth and runs independently of the web
wrapper. It uses the same virtual environment:

```bash
cd core
./.venv/bin/python main.py
```

There is no provider configured on a fresh install, so the first thing you may
want to do is run `/provider` (see below) — or start the web app and use the
**Settings** popup.

---

## 3. Choosing a provider & model

ASTRA supports four providers:

| Provider id | Label              | Default model                 | Needs an API key |
|-------------|--------------------|-------------------------------|------------------|
| `ollama`    | Local (Ollama)     | `qwen3:14b`                   | no (local)       |
| `openai`    | OpenAI             | `gpt-4o-mini`                 | yes              |
| `anthropic` | Anthropic (Claude) | `claude-3-5-sonnet-latest`    | yes              |
| `gemini`    | Google (Gemini)    | `gemini-2.0-flash`            | yes              |

You can switch providers in either interface; both write to the same config, so
the change is shared.

### From the terminal

Run the interactive setup menu:

```
/provider
```

It walks you through picking local or cloud, pasting a key, or running the local
installer. There are also direct commands:

```
/provider status          # show the current provider and model
/provider local           # pick an Ollama model already on this machine
/provider local_setup     # install Ollama (if needed) and download a model
/provider openai          # add an OpenAI key (also: /provider gpt)
/provider anthropic       # add an Anthropic (Claude) key
/provider gemini          # add a Google (Gemini) key
/provider set <p> [model] # set the active provider (and model) directly
/model [name]             # show or switch the model for the current provider
```

API keys are read with a hidden prompt (nothing is echoed) and stored in
`core/config/settings.json` with file mode `600`.

### From the web app

Click **⚙ Settings** in the header (or the model badge). A popup opens with a
short guided flow:

1. **Where should ASTRA run?** — four cards, each showing its live status
   (`Running · 3 models`, `API key saved`, `Needs an API key`, …). The active one
   is highlighted and shown in a banner at the top.
2. Click a card to configure it:
   - **Local (Ollama):** tap any already-installed model to use it instantly, or
     download a new one.
   - **Cloud:** paste your API key and confirm or change the model, then press
     **Connect & activate**.
3. A toast confirms the switch (e.g. *"Now using OpenAI · gpt-4o-mini"*) and the
   header badge updates.

Keys are **never** sent back to the browser — the API only ever returns a masked
form such as `sk-a…f3d9`.

---

## 4. The `local_setup` flow

`local_setup` is the zero-to-working path for running models on your own
machine. It is available as `/provider local_setup` in the terminal and as the
**Download a model** section in the web **Settings** popup. It:

1. **Detects** Ollama (checks `PATH` and common install locations),
2. **installs** it if missing — best effort, per OS:
   - Linux: the official `curl -fsSL https://ollama.com/install.sh | sh` script
   - macOS: `brew install ollama`
   - Windows: `winget install Ollama.Ollama`
3. **starts** the Ollama server if it isn't running,
4. **pulls** the model you chose, streaming progress (`status  42.7%
   (3.1 GB/7.3 GB)`) to the terminal or the web log,
5. **activates** the pulled model.

Ollama has no "list the whole registry" API, so instead of pretending to
enumerate everything, ASTRA offers a curated set of recommended models and lets
you type any tag. Clicking a recommendation in the web UI only fills the input;
nothing is installed until you press **Install & download**.

| Recommended model | Size    | Notes                                             |
|-------------------|---------|---------------------------------------------------|
| `qwen3:14b`       | ~9 GB   | Best all-rounder; strong reasoning and tools (default) |
| `qwen3:8b`        | ~5 GB   | Lighter Qwen3; good speed/quality balance         |
| `qwen3:4b`        | ~2.6 GB | Fast and small; great on laptops                  |
| `llama3.2:3b`     | ~2 GB   | Very light general model from Meta                |
| `llama3.1:8b`     | ~4.7 GB | Solid general-purpose 8B model                    |
| `gemma3:4b`       | ~3.3 GB | Google's compact open model                       |
| `mistral:7b`      | ~4.1 GB | Classic fast 7B instruct model                    |
| `deepseek-r1:8b`  | ~4.9 GB | Reasoning-focused distilled model                 |

You can also install Ollama yourself from
<https://ollama.com/download> and use `/provider local` to pick a model.

> Automatic install is intentionally **best effort** and only ever runs when you
> explicitly ask for it. If it can't install (no installer, no permissions), it
> tells you how to install manually and stops.

---

## 5. Web app

The web app is a thin wrapper around the core — no agent logic is duplicated. It
serves a vanilla HTML/CSS/JS frontend in ASTRA's black + yellow theme, and runs
all core operations on a single worker thread (the core is single-threaded and
some components are thread-affine).

```
web/
├── astra-web          # single launcher (start with one command)
├── requirements.txt   # backend deps (fastapi, uvicorn)
├── backend/
│   ├── run.py         # entrypoint (arg parsing, browser open, uvicorn)
│   ├── app.py         # HTTP routes + static file serving
│   └── astra_service.py  # wraps the core (chat, sessions, providers)
└── frontend/
    ├── index.html
    ├── styles.css
    ├── app.js
    └── favicon.svg
```

The web UI mirrors the terminal’s behavior: chat streaming (including thinking
and tool calls), conversation list, and clickable **download pills** for any file
ASTRA generates (served from `core/`, path-traversal safe).

See [`web/README.md`](web/README.md) for the wrapper-specific details and the
full endpoint table.

---

## 6. Configuration reference

Configuration is resolved in this order of precedence (highest first):

1. **Environment variables** — always win (great for deployments and CI).
2. **`core/config/settings.json`** — written by `/provider` and the web Settings
   popup. Git-ignored, file mode `600` because it holds secrets.
3. **Built-in defaults.**

### Settings file

`core/config/settings.json` is created on first save. Shape:

```json
{
  "provider": "openai",
  "model": "gpt-4o-mini",
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

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ASTRA_PROVIDER` | `ollama` | Active provider: `ollama`, `openai`, `anthropic`, `gemini` |
| `ASTRA_MODEL` | per provider | Model name for the active provider |
| `ASTRA_OPENAI_API_KEY` / `OPENAI_API_KEY` | — | OpenAI key |
| `ASTRA_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY` | — | Anthropic (Claude) key |
| `ASTRA_GEMINI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY` | — | Google (Gemini) key |
| `ASTRA_OLLAMA_HOST` / `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |
| `ASTRA_OPENAI_BASE_URL` / `OPENAI_BASE_URL` | OpenAI default | Override endpoint (proxy/gateway) |
| `ASTRA_ANTHROPIC_BASE_URL` | Anthropic default | Override endpoint |
| `ASTRA_GEMINI_BASE_URL` | Gemini default | Override endpoint |
| `ASTRA_SETTINGS_PATH` | `core/config/settings.json` | Where settings are stored |
| `ASTRA_DB_PATH` | `core/memory/chat_history.db` | Conversation database |
| `ASTRA_VENV` | `core/.venv` | Virtualenv used by the launcher |
| `ASTRA_PYTHON` | venv python | Explicit python binary override |

Provider/model aliases are accepted: `local`→`ollama`, `gpt`→`openai`,
`claude`→`anthropic`, `google`→`gemini`.

**Example — pin everything via env (overrides the file):**

```bash
ASTRA_PROVIDER=anthropic \
ASTRA_MODEL=claude-3-5-sonnet-latest \
ANTHROPIC_API_KEY=sk-ant-… \
./web/astra-web
```

Base URLs must not include a trailing slash (it is stripped automatically).

---

## 7. Terminal commands

**Chat:** type any message and press Enter. `exit` (or Ctrl-D) quits.

**Provider / model:**

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
/provider help            Show help
```

**Sessions:**

```
/s new                    Create a new session (auto-switches)
/s list                   List sessions with previews
/s <number>               Switch by index (0 = most recent)
/s resume                 Resume the most recent session
/s del <number>           Delete a session (with confirmation)
/s clear                  Delete ALL sessions (type YES to confirm)
/s preview [number]       Show a conversation preview
/s help                   Show help
```

---

## 8. Architecture

```
core/
├── main.py                     # terminal entrypoint
├── agent/chat.py               # REPL loop
├── controller/
│   ├── provider_controller.py  # /provider and /model commands
│   └── session_controller.py   # /s commands
├── ai/
│   ├── settings.py             # provider/model/API-key config + env precedence
│   ├── model.py                # AgentModel — the backend-agnostic agent loop
│   ├── local_setup.py          # detect/install Ollama, list/pull models
│   ├── ollama.py               # back-compat shim (OllamaModel = AgentModel)
│   └── providers/
│       ├── base.py             # Provider, Chunk, ToolCall, ProviderError, SSE helper
│       ├── ollama_provider.py
│       ├── openai_provider.py
│       ├── anthropic_provider.py
│       ├── gemini_provider.py
│       └── __init__.py         # get_provider(name) factory
├── memory/chat_history.py      # SQLite conversation store
├── tools/                      # tool registry (web search, docs, files, …)
└── downloads/                  # generated files
```

The agent loop **never** talks to a specific API. It calls
`provider.stream_chat(model, messages, tools, think)` and receives a stream of
normalized chunks:

```
Chunk(message=ResponseMessage(content, thinking, tool_calls[ToolCall]))
```

Each provider translates ASTRA's internal (OpenAI-flavored) history into its own
wire format at call time, keeping stored history portable. Tool calls and results
are paired by order; tool-call ids are preserved across reloads and synthesized
when a backend doesn't supply one.

Provider-specific notes:

- **Thinking / reasoning:** `think=True` is effectively Ollama-only. Gemini’s
  thought parts are captured automatically. OpenAI and Anthropic reasoning is off
  by default.
- **Streaming:** all providers stream over SSE. Cloud providers use `requests`
  directly (no vendor SDK).

For the deeper session/history design, see
[`core/architecture.md`](core/architecture.md).

---

## 9. Web API

The FastAPI backend exposes:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Server + active provider/model status |
| `GET` | `/api/sessions` | List conversations (+ current) |
| `POST` | `/api/sessions` | Create a new conversation |
| `POST` | `/api/sessions/switch` | Switch conversation |
| `DELETE` | `/api/sessions/{id}` | Delete a conversation |
| `GET` | `/api/sessions/{id}/messages` | Full message history |
| `POST` | `/api/chat` | Stream a chat turn (NDJSON) |
| `GET` | `/api/files?path=…` | Serve a generated file (core-scoped) |
| `GET` | `/api/providers` | Provider config (**keys masked**) |
| `POST` | `/api/providers` | Activate provider/model, save key/base URL |
| `GET` | `/api/providers/ollama/status` | Ollama install/run state + model list |
| `POST` | `/api/providers/ollama/setup` | Install Ollama + pull a model (NDJSON) |

### Chat stream events

Each line of the `/api/chat` response is a JSON object with a `type`:

| Type | Payload | Meaning |
|------|---------|---------|
| `session` | `session_id` | Active conversation for this turn |
| `thinking` | `delta` | Reasoning tokens |
| `content` | `delta` | Answer tokens |
| `tool_call` | `id`, `name`, `arguments` | Model requested a tool |
| `tool_result` | `id`, `name`, `success`, `result` | Tool finished |
| `error` | `message` | Something failed |
| `done` | `session_id` | Turn finished |

The **Stop** button aborts the client request; the backend notices the
disconnect, sets a stop flag the core observes between tokens, and releases the
model so the next message isn't delayed.

### Example: switch provider over HTTP

```bash
curl -s http://127.0.0.1:8765/api/providers | jq
curl -s -X POST http://127.0.0.1:8765/api/providers \
  -H 'Content-Type: application/json' \
  -d '{"provider":"openai","model":"gpt-4o-mini","api_key":"sk-…"}' | jq
```

---

## 10. Troubleshooting

**"Ollama does not appear to be running"** — Either start it (`ollama serve`) or
switch provider. From the web Settings popup, open **Local (Ollama)** →
**Install & download**. From the terminal, run `/provider local_setup`.

**Cloud provider returns authentication errors** — Check that the key is saved
and not overridden by an environment variable. `/provider status` shows the key’s
source (`env` vs config file). Note that env vars always win.

**The model I typed isn’t used** — `ASTRA_MODEL` or `ASTRA_PROVIDER` may be set in
your environment and will override the saved value. The web UI flags
environment-locked settings.

**Automatic Ollama install failed** — Install it manually from
<https://ollama.com/download>, then run `/provider local` to select a model.
On Linux the installer needs `curl`; on macOS it uses Homebrew; on Windows it
uses `winget`.

**Downloads / generated files** — They live under `core/` (`core/downloads/`).
The web UI turns recognized paths into download pills; the file endpoint refuses
anything outside `core/`.

**Where is my data?** — Conversations: `core/memory/chat_history.db` (override
with `ASTRA_DB_PATH`). Provider config: `core/config/settings.json` (override
with `ASTRA_SETTINGS_PATH`).

---

## 11. Security & privacy

- API keys are stored only in `core/config/settings.json`, which is
  **git-ignored** and written with mode **`600`**.
- The web backend exposes only **masked** keys (`sk-a…f3d9`) — the raw key never
  leaves the Python process.
- Cloud calls go directly to the provider you configure; no telemetry is added.
- The file endpoint is confined to the `core/` directory (traversal and host
  paths such as `/etc/passwd` are rejected with `404`).

---

## Development

- The core is importable as namespace packages (`ai`, `memory`, `tools`, …) with
  the working directory set to `core/`.
- `OllamaModel` is still importable from `ai.ollama` as a shim for older scripts;
  new code should import `AgentModel` from `ai.model`.
- Run the web app from source with `./web/astra-web`; frontend edits are hot
  (served from disk), backend edits need a restart.

There is no test suite checked in yet; the modules are exercised manually and via
the endpoints above. See [`core/architecture.md`](core/architecture.md#testing)
for example snippets that exercise sessions and provider switching without making
network calls.
