# astra-web

A lightweight web wrapper around the standalone **ASTRA** terminal application.
ASTRA core remains a fully standalone terminal app (`core/`); `web/` only boots
it up inside a browser.

```
web/
├── astra-web          # single launcher script (start with one click/command)
├── requirements.txt   # backend dependencies (fastapi, uvicorn)
├── README.md
├── backend/           # FastAPI service that proxies the ASTRA core
│   ├── run.py         # entrypoint (arg parsing, browser open, uvicorn)
│   ├── app.py         # HTTP routes + static frontend serving
│   └── astra_service.py
└── frontend/          # vanilla HTML/CSS/JS, black + yellow theme
    ├── index.html
    ├── styles.css
    ├── app.js
    └── favicon.svg
```

## Start

```bash
./web/astra-web            # start and open the browser
./web/astra-web --no-browser
./web/astra-web --port 9000
./start-dev.sh             # repo-root alias that delegates to web/astra-web
```

The launcher reuses `core/.venv`, installs the core + web dependencies if
missing, checks that the *active* provider is reachable (Ollama by default), and
starts the server on `http://127.0.0.1:8765`.

## Configuration

ASTRA is model **and** provider agnostic. You can use a local model through
[Ollama](https://ollama.com) or a cloud provider (OpenAI, Anthropic, Google
Gemini) using your own API key. Configuration can be set three ways, in order of
precedence:

1. **Environment variables** (always win),
2. the saved config file `core/config/settings.json` (written by `/provider` or
   the in-app **Settings** panel; git-ignored, file mode `600`),
3. built-in defaults.

| Env var                       | Default                    | Purpose                                   |
|-------------------------------|----------------------------|-------------------------------------------|
| `ASTRA_PROVIDER`              | `ollama`                   | `ollama`, `openai`, `anthropic`, `gemini` |
| `ASTRA_MODEL`                 | per provider (see below)   | Model name for the active provider        |
| `ASTRA_THINKING`              | `true`                     | Reasoning output on/off for the active model |
| `ASTRA_OPENAI_API_KEY` / `OPENAI_API_KEY` | — | OpenAI API key                |
| `ASTRA_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY` | — | Anthropic (Claude) API key |
| `ASTRA_GEMINI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY` | — | Google (Gemini) API key |
| `ASTRA_OLLAMA_HOST` / `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint         |
| `ASTRA_*_BASE_URL`            | provider default           | Override an endpoint (proxies, gateways)  |
| `ASTRA_SETTINGS_PATH`         | `core/config/settings.json`| Where settings are stored                 |
| `ASTRA_DB_PATH`               | `core/memory/chat_history.db` | Conversation database                  |
| `ASTRA_VENV`                  | `core/.venv`               | Python venv used by the launcher          |
| `ASTRA_PYTHON`                | (venv python)              | Explicit python binary override           |

Default model per provider: `qwen3:14b` (ollama), `gpt-4o-mini` (openai),
`claude-3-5-sonnet-latest` (anthropic), `gemini-2.0-flash` (gemini).

## How it wraps the core

The wrapper imports the core's own modules (`ai.model`, `memory.chat_history`)
and runs them with the working directory set to `core/`, matching the terminal
app exactly (DB paths, identity, downloads). There is no duplicated agent logic.
Provider/model selection is shared with the terminal app through `ai.settings`,
so a change made in the web **Settings** panel also applies when you run the
terminal app — and vice versa.

Because the core is single-threaded and some of its components are
thread-affine (SQLite connections, the Playwright event loop), the service runs
**all** core operations on one persistent worker thread. Chat turns stream back
to the browser via a per-request in-process queue:

```
Browser ──POST /api/chat──▶ FastAPI ──▶ queue ──▶ core worker thread
        ◀──NDJSON stream─── (thinking/content/tool events) ◀── AgentModel
                                                                 │
                                                       ┌─────────┴─────────┐
                                                       │  Provider         │
                                                       │  ollama / openai  │
                                                       │  anthropic / gemini│
                                                       └───────────────────┘
```

Supported API:

| Method   | Path                               | Purpose                          |
|----------|------------------------------------|----------------------------------|
| GET      | `/api/health`                      | Server + provider/model status   |
| GET      | `/api/sessions`                    | List conversations (+ current)   |
| POST     | `/api/sessions`                    | Create a new conversation        |
| POST     | `/api/sessions/switch`             | Switch to a conversation         |
| DELETE   | `/api/sessions/{id}`               | Delete a conversation            |
| GET      | `/api/sessions/{id}/messages`      | Full message history             |
| POST     | `/api/chat`                        | Stream a chat turn (NDJSON)      |
| GET      | `/api/files?path=…`                | Serve a generated file           |
| GET      | `/api/providers`                   | Provider config (keys masked)    |
| POST     | `/api/providers`                   | Activate provider/model + save key |
| POST     | `/api/thinking`                    | Toggle reasoning for the active model |
| GET      | `/api/providers/ollama/status`     | Ollama install/run + model list  |
| POST     | `/api/providers/ollama/setup`      | Install Ollama + pull a model (NDJSON) |
| POST     | `/api/browser/context`             | Receive a page snapshot from the ASTRA Firefox extension |
| GET      | `/api/browser/context`             | Latest page snapshot (debug)     |
| DELETE   | `/api/browser/context`             | Forget the page snapshot         |
| GET      | `/api/browser/commands`            | Extension claims the next queued browser command |
| POST     | `/api/browser/commands/{id}/result`| Extension reports a command's result |

## Browser integration (Firefox extension)

The `extension/firefox/` add-on has one button, **Integrate ASTRA with
webpages**. When enabled on a page, it pushes a snapshot of what you are viewing
(URL, title, HTML, visible text, selected text, mouse position) to
`POST /api/browser/context`. The core parks the latest snapshot in memory
(`browser_bridge`) and exposes it to the model through the always-available
`browser_context` tool, so you can ask ASTRA to explain the page you are reading,
summarise it, or answer questions about the highlighted text. Disabling the
button calls `DELETE /api/browser/context` to forget it. See
`extension/firefox/README.md` for setup.

The same button also turns on **browser automation**. While integration is on,
the extension polls `GET /api/browser/commands` for work and reports outcomes to
`POST /api/browser/commands/{id}/result`. The core exposes `browser_control`
tools (`ext_open_tab`, `ext_list_tabs`, `ext_switch_tab`, `ext_close_tab`,
`ext_navigate`, `ext_search`, `ext_click`, `ext_type`, `ext_press_key`,
`ext_scroll`, `ext_eval_js`, `ext_read_page`) that enqueue commands, so ASTRA can
open tabs, search, click and type visibly in your own Firefox. The command
channel and full design are documented in
`extension/firefox/ARCHITECTURE.md`; the web app serves both channels through
FastAPI.

This works with **either** frontend: the web app serves the routes through
FastAPI, while the terminal app starts the same routes itself in a tiny stdlib
listener (`core/browser_server.py`, `127.0.0.1:8765`) — so `cd core && python
main.py` needs no web server for the integration.

## Choosing a model / provider

The web app has a **Settings** panel (the ⚙ button in the header, or click the
model badge). It lets you:

* **Local (Ollama)** — pick a model already installed on this machine.
* **local_setup** — install Ollama (Linux/macOS/Windows, best-effort) and
  download a model, streaming progress into the panel. Useful on a new machine.
* **OpenAI / Anthropic (Claude) / Google (Gemini)** — paste an API key and pick
  a model. Keys are stored in `core/config/settings.json` (mode `600`) and never
  sent back to the browser (only a masked form is ever returned).
* **Thinking** — a checkbox that toggles the active model's reasoning output
  (the web equivalent of `/thinking`). It is shown locked when `ASTRA_THINKING`
  is set in the environment.

The same actions are available in the terminal app via the `/provider` and
`/thinking` commands (run `/provider help`). Because both use `ai.settings`, the
choice is shared.

### Chat stream events

Each line is a JSON object with a `type`:

* `session` — the active `session_id` for this turn
* `thinking` — reasoning tokens from the model (`delta`)
* `content` — normal answer tokens (`delta`)
* `tool_call` — the model requested a tool (`id`, `name`, `arguments`)
* `tool_result` — that tool finished (`id`, `name`, `success`, `result`)
* `error` — something failed (`message`)
* `done` — turn finished (`session_id`)

### Can I stop a reply?

Yes — the Stop button aborts the client request; the backend notices the
disconnect, sets a stop flag the core worker observes between tokens, and
releases the model so the next message isn't delayed.

### Opening generated files

When ASTRA creates a file (Word/PowerPoint/Excel document, PDF, screenshot,
downloaded page, …) it lives under `core/` (downloads go to `core/downloads/`).
Instead of only printing the on-disk location, the web UI turns any file path it
sees in the reply — or in a tool call/result — into a clickable **download
pill**. Clicking one streams the file from `GET /api/files?path=…`, which:

* accepts an absolute path or a path relative to `core/`,
* serves it inline with the right content type (PDFs/images preview, office
  files download), and
* **refuses anything outside the core directory** (traversal attempts and host
  paths such as `/etc/passwd` return `404`).