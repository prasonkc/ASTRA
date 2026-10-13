# ASTRA Firefox Extension — Architecture

This document describes how the ASTRA browser extension connects the user's real
Firefox browser to the ASTRA core, both to **observe** the page and to
**automate** it.

- Audience: maintainers of `extension/firefox`, `core/browser_*`,
  `core/tools/browser_control_tool.py`, and the HTTP frontends.
- Scope: the wire protocol, the extension internals, the tool mapping, and the
  failure model.

---

## 1. Goals & constraints

- **Observe**: ASTRA can read the page the user is viewing (URL, title, HTML,
  visible text, selection, mouse position).
- **Automate**: ASTRA can open/navigate tabs, search, click, type, press keys,
  scroll and evaluate JS — in the user's *own* browser, visibly.
- **Chat**: the user can send a message to the running agent straight from the
  popup and see the reply, continuing the same conversation as the terminal/web
  UI.
- **Work with either frontend**: the standalone terminal app (`cd core &&
  python main.py`) and the web wrapper (`./web/astra-web`) must both work, with
  no change to the extension.
- **Constraint — extensions cannot be servers.** A WebExtension background
  script cannot accept an inbound connection. Therefore all core→browser traffic
  is a **poll-based reverse channel**: the core queues a command and the
  extension pulls it.

Non-goals (for now): multi-browser support, per-site permissions/scoping,
running in the page's `MAIN` JS world (see §8).

---

## 2. Component map

```
┌──────────────────────────── ASTRA process ─────────────────────────────┐
│                                                                        │
│  terminal app (core/main.py)          web app (web/backend/app.py)      │
│    agent/chat.py ──┐                    FastAPI routes ──┐              │
│                    │                                     │              │
│         ┌──────────▼─────────────────────────────────────▼──────────┐  │
│         │                    browser_bridge.py                        │  │
│         │   • page-context store            (extension → core)         │  │
│         │   • command queue + condition     (core → extension → core)  │  │
│         │   • message handler               (extension → core → ext)   │  │
│         └───────▲──────────────────────────────────────────┬──────────┘  │
│                 │                                          │             │
│      browser_context_tool                      browser_control_tool      │
│      (reads context)                           (enqueues ext_* commands)  │
│                                                                        │
│  HTTP receiver:  browser_server.py (stdlib, terminal)  ─┐               │
│                  FastAPI routes (web)                   ─┴─ same paths  │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ HTTP on 127.0.0.1 (default :8765)
┌──────────────────────────────────▼─────────────────────────────────────┐
│                        Firefox — ASTRA extension                        │
│                                                                        │
│  background.js   toggle • per-tab context • command poller • chat sender │
│  content.js      page snapshot • mouse/selection • DOM command executor │
│  popup.js/html   integration button + status • message box             │
└────────────────────────────────────────────────────────────────────────┘
```

**Why one bridge for both frontends?** The web wrapper imports the core, so it
shares `browser_bridge`'s module state. The terminal app has no web framework, so
`browser_server.py` gives it an equivalent stdlib listener. Both expose the same
routes on the same default port, so the extension is oblivious to which is
running. Only one binds the port; the other detects the conflict and stays off
(§7).

---

## 3. Data flow A — Observe (extension → core)

```
page ─mousemove/selectionchange/DOM─▶ content.js
        (debounced snapshot + throttled mouse)
   content.js ─page-context / mouse-position─▶ background.js
   background.js ─POST /api/browser/context─▶ browser_bridge.set_context (merge)
                                                   │
                        browser_context_tool ◀─────┘   (read by the agent)
```

- The context store **merges** partial updates so the extension can post large
  fields (HTML/text) only when the page changes and tiny fields (mouse) often.
- `background.js` keeps one snapshot per tab and only forwards the **active**
  tab, so ASTRA sees what the user is looking at.

---

## 4. Data flow B — Automate (core → extension → core)

```
tool call (agent)                       extension background
───────────────                         ────────────────────
enqueue_command(name,args)                     │
  status=pending, wait on Condition            │
        │                                      │
        │        GET /api/browser/commands ────┘  (poll every 500 ms when on)
        └────────────▶ returns {id,name,args}, status=claimed
                                               │
                                    executeCommand() ── tabs API for tab ops
                                               │       └ content.js for DOM ops
        ┌──────────────────────────────────────┘
        │  POST /api/browser/commands/{id}/result {ok,result|error}
        ▼
submit_command_result() → status=done/error, notify Condition
        │
enqueue_command returns {success,result,error} ──▶ tool ──▶ agent history
```

### Command lifecycle

| State     | Set by                         | Meaning                                   |
| --------- | ------------------------------ | ----------------------------------------- |
| `pending` | `enqueue_command`              | queued, not yet handed to the extension   |
| `claimed` | `next_command` (GET)           | delivered, executing in the browser       |
| `done`    | `submit_command_result(ok=1)`  | result received                           |
| `error`   | `submit_command_result(ok=0)` or timeout | failed / no extension        |

- The tool blocks on a `threading.Condition` until `done`/`error` or the
  `COMMAND_TIMEOUT` (60 s) elapses, then returns a message telling the model to
  check the extension/tab.
- Unclaimed commands older than `COMMAND_TTL` (120 s) are pruned.
- The extension executes **one command at a time** (a single poll chain), which
  matches the agent's serial tool execution and keeps actions ordered.

---

## 4b. Data flow C — Chat (extension → core → extension)

```
popup.js ─ send (Enter/button) ─▶ background.js
                                   │  chatState = {pending:true, message}
                                   │  POST /api/browser/message {message}
                                   │        (background owns the request,
                                   │         so it survives popup close)
   browser_bridge.run_message ─────┘
        │  handler(message)   ← registered by the frontend
        ▼
   agent turn (same model/session/history as the frontend)
        │  {ok, reply, error, session_id}
        ▼
   background.js  chatState = {pending:false, reply}
   popup.js ─ poll "chat-state" every 600 ms until pending:false ─▶ render
```

- Unlike the command channel, no backend polling is needed: the agent is already
  running, so the request is a plain synchronous POST that blocks until the turn
  finishes.
- The **background owns the POST**, not the popup, so closing the popup does not
  cancel the turn; reopening it reads the current state.
- Turn execution is serialized with the frontend's own turns (terminal
  `Chat._turn_lock`, web `AstraService._lock`), so popup and in-app messages
  never interleave.
- Because the session is shared, a popup message is persisted in normal chat
  history and can call every tool — including `browser_context` ("explain this
  page") and the `ext_*` automation tools.

---

## 5. Wire protocol (HTTP, localhost only)

| Method | Path                                  | Body / params                     | Response |
| ------ | ------------------------------------- | --------------------------------- | -------- |
| POST   | `/api/browser/context`                | partial page snapshot             | `{ok, received_at}` |
| GET    | `/api/browser/context`                | —                                 | `{context}` |
| DELETE | `/api/browser/context`                | —                                 | `{ok}` |
| GET    | `/api/browser/commands`               | —                                 | `{command: {id,name,arguments}}` or `{command: null}` |
| POST   | `/api/browser/commands/{id}/result`   | `{ok, result?, error?}`           | `{accepted}` / `404` |
| POST   | `/api/browser/message`                | `{message}`                       | `{ok, reply, error, session_id}` |

CORS: the extension runs on its own origin, so responses carry
`Access-Control-Allow-Origin: *` and `OPTIONS` is handled. The listener binds
`127.0.0.1` only and performs **no authentication** — it is reachable by any
local process (see §8).

---

## 6. Tool ↔ command ↔ implementation map

ASTRA tools live in `core/tools/browser_control_tool.py`; each enqueues a command
whose `name` matches its tool name.

| ASTRA tool          | Execution site | Mechanism |
| ------------------- | -------------- | --------- |
| `ext_open_tab`      | background     | `tabs.create` |
| `ext_list_tabs`     | background     | `tabs.query` → `{index,title,url,active}` |
| `ext_switch_tab`    | background     | `tabs.update({active})` + `windows.update({focused})` |
| `ext_close_tab`     | background     | `tabs.remove(active)` |
| `ext_navigate`      | background     | `tabs.update({url})` + wait for `status:"complete"` |
| `ext_search`        | background     | build engine URL → `tabs.update` → wait → content read |
| `ext_click`         | content        | `querySelector` or visible-text match → `.click()` |
| `ext_type`          | content        | focus + set value (+ `input`/`change` events) |
| `ext_press_key`     | content        | synthetic `keydown`/`keypress`/`keyup` |
| `ext_scroll`        | content        | `window.scrollBy` / `scrollTo` |
| `ext_eval_js`       | content        | `new Function` in the content-script world |
| `ext_read_page`     | content        | text/html/url/title/selection from the DOM |

`ext_search`, `ext_navigate` and the tab tools are handled in `background.js`;
the rest are delegated to `content.js` via the `run-command` message.

### Extension-internal messages

| Message           | From → To            | Purpose / response |
| ----------------- | -------------------- | ------------------ |
| `content-ready`   | content → background | content script booted → `{enabled}` |
| `mouse-position`  | content → background | throttled pointer update |
| `page-context`    | content → background | debounced page snapshot |
| `set-integration` | background → content | start/stop streaming |
| `get-context`     | background → content | read a fresh snapshot (tab switch) |
| `run-command`     | background → content | execute a DOM command → result |
| `get-integration` | popup → background   | toggle state + status |
| `set-integration` | popup → background   | flip integration |
| `chat-send`       | popup → background   | start a chat turn → `{pending, message}` |
| `chat-state`      | popup → background   | current chat state (polled while pending) |
| `chat-clear`      | popup → background   | forget the last exchange |

---

## 7. Startup, toggling, and port ownership

- **Terminal**: `Chat.start()` calls `start_browser_context_server()`
  (`core/browser_server.py`). It is idempotent; if `127.0.0.1:8765` is taken
  (astra-web running) it stays off. Env: `ASTRA_BROWSER_BRIDGE=0`,
  `ASTRA_BROWSER_HOST`, `ASTRA_BROWSER_PORT`.
- **Web**: FastAPI already owns `:8765` and serves the routes directly.
- **Toggle**: the popup flips `integrated` (persisted in `storage.local`),
  notifies every tab (`set-integration`), and (on enable) posts an initial
  snapshot; disabling clears the backend store with `DELETE`. The command poller
  runs every 500 ms while integrated, 2 s otherwise.

---

## 8. Security & privacy

- **Localhost only.** The receiver binds `127.0.0.1`; the extension only talks to
  the configured endpoint (default `http://127.0.0.1:8765`).
- **No data leaves the machine.** Snapshots go straight from the browser to the
  local ASTRA process; nothing is sent to third parties by the extension.
- **The extension can fully drive the browser** while integrated: navigation,
  clicking, typing, and `ext_eval_js`. This is powerful — treat "Integrate ASTRA
  with webpages" as handing ASTRA the same control a user has. Disable it when
  not needed.
- **No auth on the bridge.** Any local process can read snapshots or enqueue
  commands. Acceptable for a single-user desktop tool; a token scheme is a
  possible hardening (see §9).
- **`ext_eval_js` runs in the content-script world** (Firefox X-ray vision):
  DOM reads/writes work, but page-private JS variables are not reachable, and it
  cannot break out of the extension sandbox into privileged APIs.

---

## 9. Failure model & limitations

| Situation | Behaviour |
| --------- | --------- |
| Extension off / not installed | tools time out after 60 s with a message to enable integration |
| Active tab is `about:` / add-ons | content-script commands return "could not reach the page" |
| Tab closed mid-command | `waitForTabComplete` rejects → command returns error |
| Slow page (>30 s) | navigation/search time out with "timed out waiting for page to load" |
| astra-web already on :8765 | terminal bridge stays off; web serves the routes |
| Frontend restarted | in-memory store is fresh; extension re-sends context on next poll/enable |
| Popup chat, ASTRA not reachable | POST fails; popup shows "Could not reach ASTRA: …" |
| Popup closed mid-turn | background-owned POST finishes; reply shown on reopen |

**Known limitations**

- Firefox-only; `ext_eval_js` cannot touch page globals; no per-site permission
  scoping; no screenshots; no file upload/download helpers yet; single command in
  flight at a time.

**Possible roadmap**

- Long-poll (`GET /api/browser/commands?wait=25`) to cut idle chatter.
- A shared token header between the extension and the server.
- `ext_screenshot` via `tabs.captureTab`, `ext_hover`, `ext_select_option`,
  `ext_wait_for_selector`, history back/forward, and MAIN-world eval via
  `scripting.executeScript({world:"MAIN"})`.
- Cross-process store so terminal and web can run simultaneously.

---

## 10. File reference

| File | Responsibility |
| ---- | -------------- |
| `extension/firefox/manifest.json` | MV3 manifest; `<all_urls>` host permission, `storage` |
| `extension/firefox/background.js` | toggle, per-tab context, command poller + executors, chat sender |
| `extension/firefox/content.js` | snapshot + mouse/selection + DOM command executor |
| `extension/firefox/popup.*` | integrate button + status + message box |
| `core/browser_bridge.py` | page-context store + command queue/condition + message handler |
| `core/browser_server.py` | terminal stdlib receiver for all channels |
| `core/browser_context_tool.py` | `browser_context` tool (read snapshots) |
| `core/browser_control_tool.py` | 12 `ext_*` tools (enqueue commands) |
| `core/agent/chat.py` | terminal REPL; registers the popup chat handler |
| `web/backend/astra_service.py` | web service; `run_message` for popup chat |
| `web/backend/app.py` | FastAPI routes for all channels |