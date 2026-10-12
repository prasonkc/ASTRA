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
missing, checks that Ollama is reachable, and starts the server on
`http://127.0.0.1:8765` by default.

## Configuration

| Env var       | Default     | Purpose                          |
|---------------|-------------|----------------------------------|
| `ASTRA_MODEL` | `qwen3:14b` | Ollama model used by the agent   |
| `ASTRA_VENV`  | `core/.venv`| Python venv used by the launcher |
| `ASTRA_PYTHON`| (venv python)| Explicit python binary override  |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint check |

## How it wraps the core

The wrapper imports the core's own modules (`ai.ollama`, `memory.chat_history`)
and runs them with the working directory set to `core/`, matching the terminal
app exactly (DB paths, identity, downloads). There is no duplicated agent logic.

Because the core is single-threaded and some of its components are
thread-affine (SQLite connections, the Playwright event loop), the service runs
**all** core operations on one persistent worker thread. Chat turns stream back
to the browser via a per-request in-process queue:

```
Browser ──POST /api/chat──▶ FastAPI ──▶ queue ──▶ core worker thread
        ◀──NDJSON stream─── (thinking/content/tool events) ◀── OllamaModel
```

Supported API:

| Method   | Path                               | Purpose                          |
|----------|------------------------------------|----------------------------------|
| GET      | `/api/health`                      | Server + model status            |
| GET      | `/api/sessions`                    | List conversations (+ current)   |
| POST     | `/api/sessions`                    | Create a new conversation        |
| POST     | `/api/sessions/switch`             | Switch to a conversation         |
| DELETE   | `/api/sessions/{id}`               | Delete a conversation            |
| GET      | `/api/sessions/{id}/messages`      | Full message history             |
| POST     | `/api/chat`                        | Stream a chat turn (NDJSON)      |
| GET      | `/api/files?path=…`                | Serve a generated file           |

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