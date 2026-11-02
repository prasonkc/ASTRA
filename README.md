# ASTRA

**ASTRA is a private, local-first AI academic assistant.** It runs in your browser, in a terminal, or with your voice. Use a free model on your own computer with [Ollama](https://ollama.com), or connect your own OpenAI, Anthropic (Claude), or Google Gemini API key.

> **You do not need to know Git, GitHub, Python, or the command line to use this.**
> Follow the numbered steps below and copy/paste the commands exactly.

---

## Contents

1. [Install in one command](#1-install-in-one-command)
2. [First start: choose your AI](#2-first-start-choose-your-ai)
3. [What you can do](#3-what-you-can-do)
4. [The four ways to use ASTRA](#4-the-four-ways-to-use-astra)
5. [Voice setup](#5-voice-setup)
6. [Firefox extension](#6-firefox-extension-optional)
7. [Updating, backing up, uninstalling](#7-updating-backing-up-uninstalling)
8. [Configuration reference](#8-configuration-reference)
9. [Where your data lives](#9-where-your-data-lives)
10. [Manual install (developers)](#10-manual-install-developers)
11. [Project layout and documentation](#11-project-layout-and-documentation)
12. [Troubleshooting](#12-troubleshooting)
13. [Privacy and security](#13-privacy-and-security)

---

## 1) Install in one command

### macOS or Linux

1. Open a **Terminal**:
   - **macOS:** press `Cmd + Space`, type `Terminal`, press `Enter`.
   - **Linux:** press `Ctrl + Alt + T` on most distributions.
2. Copy this whole line, paste it into the Terminal, and press `Enter`:

```bash
curl -fsSL https://raw.githubusercontent.com/prasonkc/ASTRA/main/install.sh | bash
```

3. Follow the prompts. That's it.

The installer:

- Checks for **Python 3.10+** and installs it if missing (it may ask for your password).
- Downloads ASTRA into **`~/ASTRA`** — no Git or GitHub account needed.
- Creates a private Python environment and installs all dependencies.
- Adds an **`astra`** command to your terminal.
- Creates a **desktop shortcut** on Linux and an **`ASTRA.command`** shortcut on macOS.
- Offers to install **Ollama** and a **free local AI model** (recommended, private, about 2–3 GB).

A normal install takes **5–15 minutes**. Re-running the same command later **updates** ASTRA and keeps your chats and settings.

### Windows (recommended: WSL)

ASTRA's launchers are for macOS/Linux, so on Windows use **WSL** (Windows Subsystem for Linux):

1. Open **PowerShell as Administrator** and run:

   ```powershell
   wsl --install
   ```

2. Restart your computer.
3. Open **Ubuntu** from the Start Menu and finish the one-time Linux username/password setup.
4. Inside the Ubuntu terminal, run the same macOS/Linux command:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/prasonkc/ASTRA/main/install.sh | bash
   ```

5. Start with `astra`, then open **http://127.0.0.1:8765** in your Windows browser.

> If the browser does not open by itself under WSL, just open that URL manually.

### Installer options

| Command | What it does |
|---|---|
| `install.sh` | Install or update in `~/ASTRA`. |
| `install.sh --with-ollama` | Also install Ollama and a local model, without asking. |
| `install.sh --no-ollama` | Never prompt about local AI. |
| `install.sh --model qwen3:8b` | Choose the local model to download. |
| `install.sh --dir ~/Apps/ASTRA` | Install somewhere else. |
| `install.sh --skip-browser` | Skip the optional Chromium download. |
| `install.sh --no-launch` | Install only; don't offer to start ASTRA. |
| `install.sh --uninstall` | Remove ASTRA and all of its data. |
| `install.sh --help` | Show every option. |

If you are offline, download a source archive and install it with `bash install.sh --archive /path/to/ASTRA.tar.gz`.

---

## 2) First start: choose your AI

Start ASTRA:

```bash
astra
```

The app opens at **http://127.0.0.1:8765**. If `astra` is not found, open a new terminal or run `~/ASTRA/astra`.

Then click **⚙ Settings** in the top bar and pick one of these:

### Option A — Free local AI (private, no API key)

1. Click **⚙ Settings** → **Local (Ollama)**.
2. Click **Install & download** if you did not install a model during setup.
3. Pick a model and download it.

Recommended models:

| Model | Download | RAM needed | Good for |
|---|---|---|---|
| `qwen3:4b` | ~2.5 GB | 8 GB | Most laptops; fastest |
| `qwen3:8b` | ~5 GB | 16 GB | Better answers |
| `qwen3:14b` | ~9 GB | 24 GB+ | Best local quality |
| `llama3.2:3b` | ~2 GB | 8 GB | Very small machines |

Everything stays on your computer with this option. You can disconnect from the internet after the model is downloaded.

### Option B — Cloud AI (fastest, needs an API key)

1. Click **⚙ Settings**.
2. Choose **OpenAI**, **Anthropic (Claude)**, or **Google (Gemini)**.
3. Paste your API key and choose a model.
4. Save.

| Provider | Default model | Where to get a key |
|---|---|---|
| OpenAI | `gpt-4o-mini` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| Anthropic | `claude-3-5-sonnet-latest` | [console.anthropic.com](https://console.anthropic.com/) |
| Google Gemini | `gemini-2.0-flash` | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| Local Ollama | `qwen3:14b` | No key needed |

Your keys are saved only on your computer, in a file that only your user account can read. They are never shown back to the browser in full.

### Thinking / reasoning

Some models can show their reasoning before answering. Toggle this with **Settings → Thinking** in the web app or `/thinking on|off` in the terminal.

---

## 3) What you can do

Ask ASTRA things like:

- *"Find recent papers on photosynthesis and summarise them."*
- *"Read this PDF and make a one-page summary."* (drag the file into the chat or give its path)
- *"Create a PowerPoint about the water cycle with six slides."*
- *"Build an Excel budget with formulas."*
- *"Explain the page I'm reading."* (with the Firefox extension)
- *"Remember that I prefer APA citations."*
- *"Search my downloads for last week's assignment."*
- *"Open a new tab and search for cheap flights to Tokyo."* (with the extension)

ASTRA can also use its tools to browse the web, download files, run shell commands, read PDFs/Word/PowerPoint/Excel/CSV files, and create new documents for you.

---

## 4) The four ways to use ASTRA

### A. Web app — recommended

```bash
astra                # start + open the browser
astra --no-browser   # start only
astra --port 9000    # use a different port
```

The web app has sessions, a Settings panel, file download pills, voice mode, and a Stop button.

### B. Terminal app

```bash
astra-terminal
```

The terminal is the original ASTRA experience. It uses the same model, settings, tools, and chat history as the web app.

| Command | What it does |
|---|---|
| `/provider` | Interactive provider/model setup |
| `/provider status` | Show the active provider, model, and key source |
| `/provider local_setup` | Install Ollama and download a model |
| `/model [name]` | Show or switch the model |
| `/thinking on\|off` | Toggle reasoning output |
| `/session new` | Start a new conversation |
| `/s list` | List conversations |
| `/s switch 2` | Switch to conversation number 2 |
| `/s del 2` | Delete conversation number 2 |
| `/s clear` | Delete all conversations (asks for confirmation) |
| `/voice` | Talk to ASTRA in the terminal |
| `exit` | Quit |

### C. Voice

```bash
astra-voice              # continuous listening
astra-voice --push-to-talk
astra-voice --setup      # one-time speech model download
astra-voice --status     # what's missing?
```

You can also use **`/voice`** inside `astra-terminal`, or click the **🎙 mic button** in the web app. See [Voice setup](#5-voice-setup).

### D. Firefox extension

Connect ASTRA to your real browser so it can read the page you are on, automate tabs, click, type, and chat from the popup. See [Firefox extension](#6-firefox-extension-optional).

---

## 5) Voice setup

Voice is optional. ASTRA uses two local tools:

- **whisper.cpp** for speech-to-text
- **piper** for text-to-speech

Install the models once:

```bash
astra-voice --setup
```

This downloads whisper.cpp, a speech model (~140 MB), a piper binary, and a voice. Then:

```bash
astra-voice                 # talk hands-free (continuous listening)
astra-voice --push-to-talk  # press Enter to talk, Enter again to send
astra-voice --status        # show readiness
```

**Web app voice mode:** click **🎙** next to the message box. The browser uses your microphone and speakers; the server only does speech-to-text and text-to-speech. No extra Python packages are needed on the server.

**Terminal voice command:** type `/voice` inside `astra-terminal`. Use `Ctrl+C` to return to the prompt.

If voice doesn't hear you well in a noisy room, press **Enter** to send early, use `--push-to-talk`, or raise `ASTRA_VOICE_VAD_THRESHOLD` (for example `export ASTRA_VOICE_VAD_THRESHOLD=400`).

---

## 6) Firefox extension (optional)

1. Start ASTRA with `astra` (or `astra-terminal`).
2. In Firefox, open `about:debugging#/runtime/this-firefox`.
3. Click **Load Temporary Add-on…** and select:

   ```text
   ~/ASTRA/extension/firefox/manifest.json
   ```

4. Open any page, click the **ASTRA** toolbar button, then **Integrate ASTRA with webpages**.
5. Ask ASTRA *"What is this page about?"* or *"Open a new tab and search for …"*.
6. Use the popup's **Message ASTRA** box to chat without leaving the page, or **Voice mode** to jump into web voice mode.

The extension is temporary: Firefox removes it when it closes. Load it again with the same steps. It talks only to `http://127.0.0.1:8765` on your own machine.

Full details: [`extension/firefox/README.md`](extension/firefox/README.md).

---

## 7) Updating, backing up, uninstalling

### Update

Re-run the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/prasonkc/ASTRA/main/install.sh | bash
```

Your chats, API keys, settings, downloads, and voice models are kept.

### Back up your data

Copy these folders/files somewhere safe:

```bash
~/ASTRA/core/memory/        # conversations + long-term memory
~/ASTRA/core/config/settings.json   # provider + API keys
~/ASTRA/core/downloads/     # files ASTRA created
~/ASTRA/voice/models/       # speech models (large; optional)
```

### Uninstall

The quickest option:

```bash
curl -fsSL https://raw.githubusercontent.com/prasonkc/ASTRA/main/install.sh | bash -s -- --uninstall
```

You will be asked to confirm. This deletes ASTRA, your chats, API keys, downloads, and models. Back up first if you need anything.

#### Full uninstall script

If you prefer to see exactly what will be removed — or you installed manually — save the script below as `uninstall.sh` and run it with `bash uninstall.sh`.

It backs up your chats, settings, and generated files to `~/astra-backup-<date>` before deleting anything. Set `ASTRA_BACKUP=0` to skip the backup, or `ASTRA_HOME=/path/to/ASTRA` if you installed somewhere else.

```bash
#!/usr/bin/env bash
# ASTRA uninstaller — removes the app, launchers, and shortcuts.
set -euo pipefail

INSTALL_DIR="${ASTRA_HOME:-$HOME/ASTRA}"
BACKUP="${ASTRA_BACKUP:-1}"

# Never delete something dangerous by mistake.
case "$INSTALL_DIR" in
  ""|"/"|"$HOME")
    echo "Refusing to uninstall unsafe path: '${INSTALL_DIR}'" >&2
    exit 1
    ;;
esac

if [[ ! -d "$INSTALL_DIR" ]]; then
  echo "ASTRA is not installed at: $INSTALL_DIR"
  exit 0
fi

echo "ASTRA will be removed from: $INSTALL_DIR"
echo "This deletes your chats, API keys, downloads, and speech models."
read -r -p "Continue? [y/N] " answer
case "$answer" in
  [Yy]|[Yy][Ee][Ss]) ;;
  *) echo "Cancelled. Nothing was deleted."; exit 0 ;;
esac

if [[ "$BACKUP" == "1" ]]; then
  BACKUP_DIR="$HOME/astra-backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$BACKUP_DIR"

  # Save chats, long-term memory, settings/keys, and generated files.
  [[ -d "$INSTALL_DIR/core/memory" ]] && cp -a "$INSTALL_DIR/core/memory" "$BACKUP_DIR/"
  [[ -d "$INSTALL_DIR/core/config" ]] && cp -a "$INSTALL_DIR/core/config" "$BACKUP_DIR/"
  [[ -d "$INSTALL_DIR/core/downloads" ]] && cp -a "$INSTALL_DIR/core/downloads" "$BACKUP_DIR/"

  echo "Backup saved to: $BACKUP_DIR"
  echo "Voice models are not backed up because they are large and easy to re-download."
fi

# Remove the install folder.
rm -rf -- "$INSTALL_DIR"

# Remove the commands created by the installer.
rm -f -- "$HOME/.local/bin/astra" \
          "$HOME/.local/bin/astra-terminal" \
          "$HOME/.local/bin/astra-voice"

# Remove desktop shortcuts.
rm -f -- "$HOME/.local/share/applications/astra.desktop"
rm -f -- "$HOME/Applications/ASTRA.command"
rm -f -- "$HOME/Desktop/ASTRA.desktop"

echo "ASTRA has been removed."
echo "If you added ~/.local/bin to your PATH for ASTRA, you can remove that line"
echo "from your shell startup file (search for 'ASTRA installer')."
```

### Start ASTRA automatically (optional)

- **Linux:** copy `~/.local/share/applications/astra.desktop` into your desktop's autostart folder.
- **macOS:** add `~/Applications/ASTRA.command` to **System Settings → General → Login Items**.

---

## 8) Configuration reference

Configuration is resolved in this order (highest priority first):

1. **Environment variables**
2. **`core/config/settings.json`** (written by the Settings panel or `/provider`)
3. **Built-in defaults**

Provider names accept aliases: `local` → `ollama`, `gpt` → `openai`, `claude` → `anthropic`, `google` → `gemini`.

### `core/config/settings.json`

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

- `provider` / `model` — the active choice.
- `thinking` — show reasoning when the model supports it.
- `providers.<id>` — per-provider key, model, and base URL.
- Keys can coexist; switching providers does not delete the others.

### Common environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ASTRA_PROVIDER` | `ollama` | `ollama`, `openai`, `anthropic`, `gemini` |
| `ASTRA_MODEL` | per provider | Model for the active provider |
| `ASTRA_THINKING` | `true` | Reasoning on/off (`1/0`, `on/off`) |
| `ASTRA_OPENAI_API_KEY` / `OPENAI_API_KEY` | — | OpenAI key |
| `ASTRA_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY` | — | Anthropic key |
| `ASTRA_GEMINI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY` | — | Gemini key |
| `ASTRA_OLLAMA_HOST` / `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |
| `ASTRA_OPENAI_BASE_URL` | OpenAI default | OpenAI-compatible endpoint |
| `ASTRA_ANTHROPIC_BASE_URL` | Anthropic default | Endpoint override |
| `ASTRA_GEMINI_BASE_URL` | Gemini default | Endpoint override |
| `ASTRA_SETTINGS_PATH` | `core/config/settings.json` | Settings file location |
| `ASTRA_DB_PATH` | `core/memory/chat_history.db` | Conversation database |
| `ASTRA_VENV` | `core/.venv` | Python environment used by launchers |
| `ASTRA_PYTHON` | venv Python | Explicit Python binary |

**Important:** an environment variable always beats the saved file. If a key or model seems "stuck", check whether it is exported in your terminal (web Settings shows this as locked).

Voice has its own `ASTRA_VOICE_*` variables (binaries, models, microphone, silence detection). See [`voice/README.md`](voice/README.md) or Appendix A of [`documentation.md`](documentation.md).

### Ollama tips

```bash
ollama serve                 # start the local server
ollama list                  # show installed models
ollama pull qwen3:4b         # download a model
ollama rm qwen3:14b          # remove a model
```

ASTRA can install/start Ollama for you from **Settings → Local (Ollama) → Install & download**, or with `/provider local_setup` in the terminal.

### Optional extras

These are installed by `install.sh` automatically, but manual installs need them:

```bash
# PDF reading
core/.venv/bin/python -m pip install pdfplumber

# Browser automation
core/.venv/bin/python -m pip install playwright
core/.venv/bin/python -m playwright install chromium
```

Playwright is imported by ASTRA's tool registry, so the Python package is required for ASTRA to start; the Chromium download is only needed for browser-automation tools.

---

## 9) Where your data lives

| Data | Location | How to change it |
|---|---|---|
| Conversations | `core/memory/chat_history.db` | `ASTRA_DB_PATH` |
| Long-term memory | `core/memory/astra.db` | Constructor arg only (advanced) |
| Provider + API keys | `core/config/settings.json` | `ASTRA_SETTINGS_PATH` |
| Generated/downloaded files | `core/downloads/` | — |
| System prompt / identity | `core/config/identity.txt` | Edit the file |
| Python environment | `core/.venv/` | `ASTRA_VENV` |
| Speech models | `voice/models/` | `ASTRA_VOICE_MODELS_DIR` |

The installer and web app never store data outside the install folder except the `astra` command, desktop shortcut, and downloaded Chromium cache (`~/.cache/ms-playwright`).

---

## 10) Manual install (developers)

Use this if the one-command installer fails or you want to inspect the source.

### Quick manual install

```bash
git clone https://github.com/prasonkc/ASTRA.git
cd ASTRA
./web/astra-web
```

`./web/astra-web` creates `core/.venv`, installs `requirements.txt` and `web/requirements.txt`, checks the active provider, and serves the app on `http://127.0.0.1:8765`.

### Full manual setup

```bash
python3 -m venv core/.venv
core/.venv/bin/python -m pip install --upgrade pip
core/.venv/bin/python -m pip install -r requirements.txt -r web/requirements.txt
core/.venv/bin/python -m pip install pdfplumber playwright
core/.venv/bin/python -m playwright install chromium   # optional browser automation
```

Run the web app:

```bash
./web/astra-web
./web/astra-web --no-browser
./web/astra-web --port 9000
./start-dev.sh                  # alias for ./web/astra-web
```

Run the terminal app:

```bash
cd core
./.venv/bin/python main.py
```

Run voice:

```bash
./voice/astra-voice --setup
./voice/astra-voice
```

Verify the install without making a network call:

```bash
cd core
./.venv/bin/python -c "from ai.model import AgentModel; print(AgentModel().describe())"
```

### Requirements

- Python 3.10+ (developed on 3.14)
- macOS, Linux, or Windows with WSL
- Internet access for installation and cloud providers (not needed for local inference after models are downloaded)
- ~1 GB for the app, plus ~2–9 GB if you use a local model
- Firefox only if you want the browser extension

No Node.js, no frontend build step, no database server. The frontend is plain HTML/CSS/JS and history uses SQLite.

---

## 11) Project layout and documentation

```text
ASTRA/
├── README.md                 # this file
├── install.sh                # one-command installer
├── requirements.txt          # core Python dependencies
├── start-dev.sh              # repo-root alias for ./web/astra-web
├── core/                     # terminal app + the shared brain
│   ├── main.py               # terminal entry point
│   ├── ai/                   # agent loop, providers, settings, local setup
│   ├── controller/           # /provider, /session, /voice commands
│   ├── memory/               # SQLite chat history + long-term memory
│   ├── tools/                # web, shell, documents, browser, memory tools
│   ├── config/               # identity prompt + settings.json
│   └── downloads/            # generated files
├── web/                      # browser wrapper (FastAPI + vanilla frontend)
│   ├── astra-web             # single launcher
│   └── backend/ frontend/
├── voice/                    # optional local speech layer
│   ├── astra-voice           # single launcher
│   └── backend/
├── extension/firefox/        # ASTRA Firefox extension
└── documentation.md          # full technical reference
```

Where to read more:

| Document | What it covers |
|---|---|
| [`documentation.md`](documentation.md) | Every module, class, function, API route, env var, and design decision |
| [`web/README.md`](web/README.md) | Web wrapper, API, streaming, voice endpoints |
| [`voice/README.md`](voice/README.md) | Speech setup, commands, audio backends, troubleshooting |
| [`extension/firefox/README.md`](extension/firefox/README.md) | Extension usage and protocol |
| [`extension/firefox/ARCHITECTURE.md`](extension/firefox/ARCHITECTURE.md) | Command lifecycle, security model |
| [`core/architecture.md`](core/architecture.md) | Sessions and chat-history deep dive |

### Architecture in one paragraph

ASTRA has **one brain and several shells**. `core/` contains the agent loop (`ai/model.py`), provider adapters (`ai/providers/`), tools (`tools/`), and SQLite memory. The terminal (`core/main.py`), web app (`web/backend/`), and voice wrapper (`voice/backend/`) all import and drive that same core; they never duplicate agent logic. The core is single-threaded, so the web layer serializes operations onto one worker thread. Provider, model, keys, and thinking are shared through `ai/settings.py`, which means a change in the web Settings panel also applies in the terminal.

---

## 12) Troubleshooting

**`astra: command not found`**
Open a new terminal. Or run `~/ASTRA/astra`. To make it permanent, add this to `~/.bashrc`, `~/.zshrc`, or `~/.profile`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**`Ollama does not appear to be running`**
Start it with `ollama serve` in another terminal, or use **Settings → Local (Ollama) → Install & download**. ASTRA's status check only warns; it does not block cloud providers.

**The app opens but every reply fails**
No model is configured yet. Open **⚙ Settings** and either install a local model or paste a cloud API key. In the terminal, run `/provider`.

**My API key isn't being used**
Check `ASTRA_OPENAI_API_KEY`, `ASTRA_ANTHROPIC_API_KEY`, or `ASTRA_GEMINI_API_KEY` in your environment. Environment variables override the saved file. `/provider status` shows whether the key came from `env` or the config file.

**The model I typed isn't used**
`ASTRA_PROVIDER` or `ASTRA_MODEL` may be set in your environment. Unset it or change it, then restart ASTRA.

**Port 8765 is already in use**
Another ASTRA window is probably running. Close it, or use:

```bash
astra --port 9000
./web/astra-web --port 9000
```

**Browser does not open**
Open [http://127.0.0.1:8765](http://127.0.0.1:8765) manually. On WSL, open that URL in your Windows browser.

**`/voice` or the mic button says voice is unavailable**
Run `astra-voice --setup`, then `astra-voice --status`. Voice mode in the browser does not need an audio device on the server, but it does need the whisper/piper files.

**Voice cuts off or hears nothing**
Use `--push-to-talk`, press **Enter** to send early, or raise the silence threshold:

```bash
export ASTRA_VOICE_VAD_THRESHOLD=400
export ASTRA_VOICE_SILENCE=1.2
```

**PDF reading fails**
Install the PDF extra:

```bash
~/ASTRA/core/.venv/bin/python -m pip install pdfplumber
```

**Browser automation fails**
Install Chromium for Playwright:

```bash
~/ASTRA/core/.venv/bin/python -m playwright install chromium
```

**Linux says a virtual environment cannot be created**
Install the venv package and re-run the installer:

```bash
sudo apt install python3 python3-venv
```

**The installer downloaded but Python packages fail**
Check your internet connection and proxy settings. If you are behind a corporate proxy, set `HTTPS_PROXY`/`HTTP_PROXY` before running the installer. You can also install from a local archive with `--archive`.

**I want to start over**
Uninstall, then install again (this deletes your data):

```bash
curl -fsSL https://raw.githubusercontent.com/prasonkc/ASTRA/main/install.sh | bash -s -- --uninstall
```

**Where are my files?**
Chats: `~/ASTRA/core/memory/chat_history.db`. Generated files: `~/ASTRA/core/downloads/`. Settings and keys: `~/ASTRA/core/config/settings.json`.

If something else is wrong, check the browser's **Settings** panel diagnostics, run `astra-voice --status` for voice, and look at the fuller [troubleshooting section](documentation.md#20-troubleshooting) in the technical docs.

---

## 13) Privacy and security

- **Local by default.** With Ollama, prompts, replies, and files stay on your machine.
- **Cloud only when you choose it.** With OpenAI, Anthropic, or Gemini, requests go directly to that provider using your key. ASTRA adds no telemetry and proxies nothing.
- **Keys stay local.** Keys are stored in `core/config/settings.json` with file mode `600` (only your user can read it). The web UI only ever receives a masked form such as `sk-a…f3d9`.
- **File downloads are sandboxed.** The web server only serves files inside the ASTRA install folder; paths like `/etc/passwd` are rejected.
- **Powerful tools, trusted user.** ASTRA can run shell commands, evaluate JavaScript, and automate a browser. Only run it on a computer you control, and review what you ask it to do.
- **Firefox extension is localhost-only.** It sends page snapshots to `http://127.0.0.1:8765` and nowhere else.

---

## License

MIT — see [LICENSE](LICENSE).

Built by [Prason Kc](https://github.com/prasonkc). Contributions and bug reports are welcome on [GitHub](https://github.com/prasonkc/ASTRA).
