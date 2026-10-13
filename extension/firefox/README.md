# ASTRA Firefox Extension

Connects your local ASTRA agent to your real Firefox browser. It **observes** the
page you are viewing (so ASTRA can explain it), lets ASTRA **automate** the
browser (tabs, navigation, search, clicking, typing) through tools, lets you
**chat** with the running agent straight from the popup, and jumps into
hands-free **voice mode** with one click.

> For the full design — wire protocol, command lifecycle, security model — see
> [`ARCHITECTURE.md`](ARCHITECTURE.md).

## What it does

### Observe

The extension has a single button: **Integrate ASTRA with webpages**. When it is
on, the content script in the page you are viewing streams a snapshot to the
local ASTRA backend, which parks it in memory. The always-available
`browser_context` tool reads that snapshot, so you can ask ASTRA things like
*"explain this page"*, *"summarise what I'm reading"*, or *"what does the
highlighted text mean?"*.

The snapshot contains:

| Field       | Source                                              |
| ----------- | --------------------------------------------------- |
| `url`       | `location.href`                                     |
| `title`     | `document.title`                                    |
| `html`      | `document.documentElement.outerHTML` (+ doctype)    |
| `text`      | `document.body.innerText` (visible text)            |
| `selection` | the text the user has highlighted                   |
| `mouse`     | `{ x, y, pageX, pageY }` of the pointer             |

### Automate

While integration is on, the extension also polls the backend for queued
commands and runs them in your browser. ASTRA exposes these to the model as the
`browser_control` tools:

| Tool               | What it does                                                     |
| ------------------ | ---------------------------------------------------------------- |
| `ext_open_tab`     | Open a new tab (optionally at a URL)                             |
| `ext_list_tabs`    | List open tabs (index, title, URL, active)                       |
| `ext_switch_tab`   | Make a tab active by index or URL/title substring                |
| `ext_close_tab`    | Close the active tab                                             |
| `ext_navigate`     | Go to a URL in the active tab and wait for load                  |
| `ext_search`       | Search Google/DuckDuckGo/Bing and return the results page text   |
| `ext_click`        | Click an element by CSS selector or visible text                 |
| `ext_type`         | Type text into a field (focused field, or a CSS selector)        |
| `ext_press_key`    | Press a key (Enter, Tab, Escape, ArrowDown, …)                   |
| `ext_scroll`       | Scroll down/up/to top/to bottom                                  |
| `ext_eval_js`      | Evaluate a JavaScript expression and return the value            |
| `ext_read_page`    | Read the active tab (text/html/url/title/selection)              |

Example: *"In my browser, search for the ASTRA project and open the first
result"* — ASTRA calls `ext_search`, reads the results, calls `ext_click`, then
`ext_read_page` to summarise it.

Actions happen **visibly in your browser** and only while integration is on.
The popup shows only the toggle button, a small connection status, and the
message box. Nothing leaves your machine — data goes to `http://127.0.0.1:8765`
(the local ASTRA backend).

### Message ASTRA

The popup also has a small **Message ASTRA** box. Type a question and press
**Send** (or Enter): it POSTs `{message}` to `POST /api/browser/message`, the
running agent answers using the *same conversation* as the terminal and web UI,
and the reply appears in the popup. The background script owns the request, so
the reply still completes if you close the popup before it arrives — reopen it to
see the result.

Because the agent shares the session, a message sent from the browser is saved in
your normal chat history and can use every tool, including `browser_context`
(so *"explain this page"* works straight from the popup).

### Voice mode

The **🎙 Voice mode** button opens the web app's voice mode (`{endpoint}/?voice=1`),
backed by the local speech layer (whisper.cpp speech-to-text + piper
text-to-speech). Behind the scenes it first checks `GET /api/voice/status`; if
the speech models aren't installed (or the web app isn't the frontend running)
it says so instead of opening a dead page. Voice mode lives in the web app
because the mic/speaker UI needs a full page — the terminal app's stdlib bridge
does not serve it.

## Requirements

- ASTRA running locally with the browser bridge reachable at
  `http://127.0.0.1:8765`. Either frontend provides it:
  - **Web app:** `./web/astra-web` (FastAPI serves the routes), or
  - **Terminal app:** `cd core && ./.venv/bin/python main.py` — the core starts
    its own tiny localhost listener (`core/browser_server.py`) on the same
    port, so no web server is needed.

## Loading it in Firefox

1. Start ASTRA: `./web/astra-web` **or** `cd core && ./.venv/bin/python main.py`.
2. Open `about:debugging#/runtime/this-firefox`.
3. Click **Load Temporary Add-on…** and select `extension/firefox/manifest.json`.
4. Open a page and click the ASTRA toolbar button, then **Integrate ASTRA with
   webpages**.
5. Ask ASTRA about the page (*"What is this page about?"*) or ask it to act
   (*"open a new tab to example.com"*).
6. Or type in the popup's **Message ASTRA** box and press Enter — the reply
   appears right there (the same conversation as the terminal/web UI).

The add-on is temporary and is removed when Firefox closes. A permanent install
would need signing or a development profile.

> Note: content scripts do not run on privileged pages (`about:`,
> `addons.mozilla.org`, DOM commands cannot run there), but tabs can still be
> managed. `library:` and `about:` pages cannot be read.

## How it works

```
                          ┌── observe ──────────────────────────────────────┐
page --mouse/selection/DOM--> content.js --page-context--> background.js
                                                              │ POST /api/browser/context
                                                              ▼
                                                    browser_bridge (in-memory)
                                                              │
                                            browser_context tool ──▶ agent
                          └─────────────────────────────────────────────────┘

                          ┌── automate ─────────────────────────────────────┐
ext_* tool ──enqueue──▶ browser_bridge command queue ◀── GET /api/browser/commands
                                   ▲                     (background polls every 500 ms)
                     POST result   │                            │ execute
                                   └────────────────── background.js / content.js
                          └─────────────────────────────────────────────────┘

                          ┌── chat ─────────────────────────────────────────┐
popup Send ──chat-send──▶ background.js ──POST /api/browser/message──▶ agent turn
     ▲                        (owns the request)                              │
     └──────── poll chat-state ◀────────── {reply} ◀──────────────────────────┘
                          └─────────────────────────────────────────────────┘
```

- `content.js` builds the snapshot (debounced), tracks the mouse (throttled) and
  the selection, re-sends when the URL changes (including SPAs), and executes
  DOM commands (`ext_click`, `ext_type`, `ext_press_key`, `ext_scroll`,
  `ext_eval_js`, `ext_read_page`).
- `background.js` owns the on/off toggle, keeps one snapshot per tab, only posts
  the tab you are looking at, and runs the command poller. Tab and navigation
  commands (`ext_open_tab`, `ext_list_tabs`, `ext_switch_tab`, `ext_close_tab`,
  `ext_navigate`, `ext_search`) use the WebExtension `tabs` API.
- The backend **merges** partial snapshots so heavy fields (HTML/text) are not
  re-sent constantly, and hands out one command per poll.
- Disabling the button clears the stored snapshot on the backend
  (`DELETE /api/browser/context`) and stops the poller from picking up commands.
- For **chat**, `background.js` owns the POST to `/api/browser/message` (so the
  request survives the popup closing) and the popup polls `chat-state` for the
  reply. The turn runs in the same session/history as the terminal or web UI.

## Files

```
manifest.json    extension definition (Manifest V3)
content.js       page snapshot + mouse + selection + DOM command executor
background.js    toggle, per-tab state, context posts, command poller, chat sender
popup.html       toggle button + status + message box
popup.js         toggle, connection status, chat send/poll
ARCHITECTURE.md  full design: protocol, lifecycle, security, roadmap
```

## Message API (extension-internal)

| Message            | From → To            | Response                              |
| ------------------ | -------------------- | ------------------------------------- |
| `mouse-position`   | content → background | none                                  |
| `page-context`     | content → background | none                                  |
| `content-ready`    | content → background | `{ enabled }`                         |
| `get-context`      | background → content | the page snapshot                     |
| `run-command`      | background → content | command result `{ ok, ... }`          |
| `set-integration`  | popup → background   | `{ enabled, endpoint, status }`       |
| `get-integration`  | popup → background   | `{ enabled, endpoint, status }`       |
| `chat-send`        | popup → background   | `{ pending, message, ... }`           |
| `chat-state`       | popup → background   | current chat state (polled)           |
| `chat-clear`       | popup → background   | cleared chat state                    |

## Backend API used

| Method | Path                                | Purpose                              |
| ------ | ----------------------------------- | ------------------------------------ |
| POST   | `/api/browser/context`              | Push/merge a page snapshot           |
| GET    | `/api/browser/context`              | Read the latest snapshot (debug)     |
| DELETE | `/api/browser/context`              | Forget the snapshot                  |
| GET    | `/api/browser/commands`             | Claim the next queued command        |
| POST   | `/api/browser/commands/{id}/result` | Report a command's result            |
| POST   | `/api/browser/message`              | Send a popup message to the agent; returns the reply |

These routes are served by whichever ASTRA frontend is running: the web app
(FastAPI) or the terminal app (its stdlib `browser_server.py` listener).

## Changing the backend URL

The endpoint defaults to `http://127.0.0.1:8765`. The terminal listener can be
tuned with `ASTRA_BROWSER_BRIDGE=0` (off), `ASTRA_BROWSER_HOST`, and
`ASTRA_BROWSER_PORT`. To point the extension elsewhere, set `endpoint` in the
extension's storage (`browser.storage.local.set({ endpoint:
"http://127.0.0.1:9000" })` from the background console in
`about:debugging`).
