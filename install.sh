#!/usr/bin/env bash
#
# ASTRA one-command installer for macOS and Linux (including Windows + WSL).
#
#   curl -fsSL https://raw.githubusercontent.com/prasonkc/ASTRA/main/install.sh | bash
#
# What it does:
#   1. Checks for Python 3.10+ (and offers to install it if missing).
#   2. Downloads the latest ASTRA source (no git needed).
#   3. Installs it in ~/ASTRA (override with --dir or ASTRA_HOME).
#   4. Creates a private Python environment and installs dependencies.
#   5. Adds an `astra` command and, on Linux/macOS, an app shortcut.
#   6. Optionally installs Ollama and downloads a free local AI model.
#
# Your chats, settings and generated files always survive updates.
#
# Usage:
#   install.sh                     install or update
#   install.sh --with-ollama       also install Ollama + a local model
#   install.sh --no-ollama         never prompt about Ollama
#   install.sh --dir ~/Apps/ASTRA   choose a different install folder
#   install.sh --skip-browser      do not download Chromium (browser automation)
#   install.sh --uninstall         remove ASTRA and its data
#   install.sh --help              show all options
#
# Environment overrides:
#   ASTRA_HOME           install directory (default: ~/ASTRA)
#   ASTRA_BRANCH         git branch/tag to download (default: main)
#   ASTRA_ARCHIVE        install from a local .tar.gz instead of downloading
#   ASTRA_OLLAMA_MODEL   local model to pull (default: qwen3:4b)
#   ASTRA_SKIP_BROWSER   set to 1 to skip the Chromium download
#
# This script is intentionally dependency-free: it only needs bash, curl and tar.
# It never uses sudo unless it has to install a missing system package, and it
# always asks first.

set -euo pipefail

REPO_SLUG="${ASTRA_REPO_SLUG:-prasonkc/ASTRA}"
BRANCH="${ASTRA_BRANCH:-main}"
INSTALL_DIR="${ASTRA_HOME:-$HOME/ASTRA}"
ARCHIVE_PATH="${ASTRA_ARCHIVE:-}"
OLLAMA_MODEL="${ASTRA_OLLAMA_MODEL:-qwen3:4b}"
OLLAMA_MODE="ask"          # ask | yes | no
OLLAMA_EXPLICIT=0
AI_CONFIGURED=0
ASSUME_YES=0
NO_LAUNCH=0
ADD_PATH=1
WITH_BROWSER=1
UNINSTALL=0

if [[ "${ASTRA_SKIP_BROWSER:-0}" == "1" ]]; then
  WITH_BROWSER=0
fi

# ---------------------------------------------------------------------------
# Pretty output
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  C_BLUE=$'\033[94m'; C_GREEN=$'\033[92m'; C_YELLOW=$'\033[93m'; C_RED=$'\033[91m'; C_DIM=$'\033[2m'; C_RESET=$'\033[0m'
else
  C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_DIM=""; C_RESET=""
fi

log()  { printf '%s[ASTRA]%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf '%s[ASTRA]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s[ASTRA]%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
die()  { printf '%s[ASTRA]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }
dim()  { printf '%s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }

have() { command -v "$1" >/dev/null 2>&1; }

usage() {
  cat <<'USAGE'
ASTRA installer — no git or coding knowledge required.

  curl -fsSL https://raw.githubusercontent.com/prasonkc/ASTRA/main/install.sh | bash

Options:
  --dir PATH          Install to PATH instead of ~/ASTRA.
  --with-ollama       Install Ollama and download a free local AI model.
  --no-ollama         Do not install or ask about local AI.
  --model NAME        Local model to download (default: qwen3:4b).
  --skip-browser      Skip the Chromium download used by browser automation.
  --no-launch         Install only; do not offer to start ASTRA afterwards.
  --no-path           Do not add ~/.local/bin to your shell PATH.
  --branch NAME       Download a different branch or tag (default: main).
  --archive FILE      Install from a local .tar.gz file (offline install).
  -y, --yes           Answer yes to every question (unattended install).
  --uninstall         Delete ASTRA, its chats and its settings.
  -h, --help          Show this help.

Environment variables:
  ASTRA_HOME, ASTRA_BRANCH, ASTRA_ARCHIVE, ASTRA_OLLAMA_MODEL,
  ASTRA_SKIP_BROWSER=1

macOS: open Terminal with Command+Space, type "Terminal", press Enter.
Linux: open your Terminal app (often Ctrl+Alt+T).
Windows: use WSL (Ubuntu) — see the README for click-by-click steps.
USAGE
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      [[ $# -ge 2 ]] || die "--dir needs a path."
      INSTALL_DIR="$2"; shift 2 ;;
    --dir=*) INSTALL_DIR="${1#*=}"; shift ;;
    --branch)
      [[ $# -ge 2 ]] || die "--branch needs a name."
      BRANCH="$2"; shift 2 ;;
    --branch=*) BRANCH="${1#*=}"; shift ;;
    --archive)
      [[ $# -ge 2 ]] || die "--archive needs a file path."
      ARCHIVE_PATH="$2"; shift 2 ;;
    --archive=*) ARCHIVE_PATH="${1#*=}"; shift ;;
    --model)
      [[ $# -ge 2 ]] || die "--model needs a name."
      OLLAMA_MODEL="$2"; shift 2 ;;
    --model=*) OLLAMA_MODEL="${1#*=}"; shift ;;
    --with-ollama) OLLAMA_MODE="yes"; OLLAMA_EXPLICIT=1; shift ;;
    --no-ollama)   OLLAMA_MODE="no"; OLLAMA_EXPLICIT=1; shift ;;
    --skip-browser) WITH_BROWSER=0; shift ;;
    --no-launch) NO_LAUNCH=1; shift ;;
    --no-path) ADD_PATH=0; shift ;;
    -y|--yes) ASSUME_YES=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
normalize_dir() {
  local p="$1"
  if [[ "$p" == "~" ]]; then
    p="$HOME"
  elif [[ "$p" == "~/"* ]]; then
    p="$HOME/${p#~/}"
  fi
  case "$p" in
    /*) ;;
    *) p="$PWD/$p" ;;
  esac
  while [[ "$p" != "/" && "$p" == */ ]]; do
    p="${p%/}"
  done
  printf '%s\n' "$p"
}

INSTALL_DIR="$(normalize_dir "$INSTALL_DIR")"

# Never let a mistaken path turn into `rm -rf /` or `rm -rf $HOME`.
case "$INSTALL_DIR" in
  ""|"/"|"$HOME"|"."|"..") die "Refusing to use unsafe install directory: '${INSTALL_DIR}'" ;;
esac
case "$HOME/" in
  "$INSTALL_DIR"/*) die "Refusing to install into a parent of your home folder: ${INSTALL_DIR}" ;;
esac

can_prompt() {
  [[ -r /dev/tty && -w /dev/tty ]]
}

# ask "Question" "y|n" -> returns 0 for yes.
prompt_yes_no() {
  local question="$1" default="${2:-y}" answer hint
  if ! can_prompt; then
    [[ "$default" == "y" ]]
    return
  fi
  if [[ "$default" == "y" ]]; then hint="[Y/n]"; else hint="[y/N]"; fi
  printf '%s %s ' "$question" "$hint" > /dev/tty
  if ! IFS= read -r answer < /dev/tty; then
    answer=""
  fi
  answer="${answer:-$default}"
  case "$answer" in
    [Yy]|[Yy][Ee][Ss]) return 0 ;;
    *) return 1 ;;
  esac
}

run_as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  elif have sudo; then
    sudo "$@"
  else
    return 1
  fi
}

find_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if have "$candidate" && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

install_python_with_package_manager() {
  if have apt-get; then
    run_as_root apt-get update -y && run_as_root apt-get install -y python3 python3-venv python3-pip curl ca-certificates
  elif have dnf; then
    run_as_root dnf install -y python3 python3-pip python3-virtualenv curl ca-certificates
  elif have yum; then
    run_as_root yum install -y python3 python3-pip curl ca-certificates
  elif have pacman; then
    run_as_root pacman -Sy --needed --noconfirm python python-pip curl ca-certificates
  elif have zypper; then
    run_as_root zypper --non-interactive install python3 python3-pip python3-virtualenv curl ca-certificates
  elif have apk; then
    run_as_root apk add --no-cache python3 py3-pip curl ca-certificates
  else
    return 1
  fi
}

install_curl_with_package_manager() {
  if have apt-get; then
    run_as_root apt-get update -y && run_as_root apt-get install -y curl ca-certificates
  elif have dnf; then
    run_as_root dnf install -y curl ca-certificates
  elif have yum; then
    run_as_root yum install -y curl ca-certificates
  elif have pacman; then
    run_as_root pacman -Sy --needed --noconfirm curl ca-certificates
  elif have zypper; then
    run_as_root zypper --non-interactive install curl ca-certificates
  elif have apk; then
    run_as_root apk add --no-cache curl ca-certificates
  elif have brew; then
    brew install curl
  else
    return 1
  fi
}

ensure_python() {
  local python
  if python="$(find_python)"; then
    PYTHON="$python"
    return
  fi

  warn "Python 3.10 or newer is required, but it was not found."
  if [[ "$(uname -s)" == "Darwin" ]]; then
    if have brew; then
      if [[ $ASSUME_YES -eq 1 ]] || prompt_yes_no "Install Python with Homebrew now?" y; then
        brew install python || true
      fi
    else
      die "Please install Python from https://www.python.org/downloads/ and run this installer again."
    fi
  else
    if [[ $ASSUME_YES -eq 1 ]] || { can_prompt && prompt_yes_no "Install Python automatically now? (may ask for your password)" y; }; then
      install_python_with_package_manager || warn "Automatic Python install failed."
    fi
  fi

  if python="$(find_python)"; then
    PYTHON="$python"
  else
    die "Python could not be installed automatically. Install Python 3.10+ from https://www.python.org/downloads/ and run this installer again."
  fi
}

ensure_download_tools() {
  if ! have curl; then
    warn "curl is needed to download ASTRA."
    if [[ $ASSUME_YES -eq 1 ]] || { can_prompt && prompt_yes_no "Install curl automatically now?" y; }; then
      install_curl_with_package_manager || warn "Automatic curl install failed."
    fi
  fi
  have curl || die "curl is required. Install it (for example: sudo apt install curl) and try again."
  have tar || die "tar is required. Install it and try again."
}

add_to_path_if_needed() {
  [[ $ADD_PATH -eq 1 ]] || return 0
  case ":${PATH}:" in
    *":$HOME/.local/bin:"*) return 0 ;;
  esac

  # If ~/.local/bin is not on PATH, add it to the shell startup files that
  # already exist. We never replace a file and never add the block twice.
  local marker="# >>> ASTRA installer: add ~/.local/bin to PATH >>>"
  local line='export PATH="$HOME/.local/bin:$PATH"'
  local rc found=0
  for rc in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc"; do
    [[ -f "$rc" ]] || continue
    found=1
    if grep -qF "$marker" "$rc" 2>/dev/null; then
      continue
    fi
    printf '\n%s\n%s\n# <<< ASTRA installer <<<\n' "$marker" "$line" >> "$rc" || true
  done
  if [[ $found -eq 0 ]]; then
    printf '%s\n%s\n' "$marker" "$line" >> "$HOME/.profile" 2>/dev/null || true
  fi
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------
uninstall_astra() {
  if [[ ! -d "$INSTALL_DIR" ]]; then
    warn "Nothing to uninstall: ${INSTALL_DIR} does not exist."
    return 0
  fi
  warn "This will permanently delete ASTRA and everything in:"
  warn "  ${INSTALL_DIR}"
  warn "That includes your chats, saved API keys and generated files."
  if [[ $ASSUME_YES -ne 1 ]]; then
    prompt_yes_no "Delete it permanently?" n || { log "Cancelled. Nothing was deleted."; return 0; }
  fi
  rm -rf -- "$INSTALL_DIR"
  rm -f -- "$HOME/.local/bin/astra" "$HOME/.local/bin/astra-terminal" "$HOME/.local/bin/astra-voice" 2>/dev/null || true
  rm -f -- "$HOME/.local/share/applications/astra.desktop" 2>/dev/null || true
  rm -f -- "$HOME/Applications/ASTRA.command" 2>/dev/null || true
  ok "ASTRA has been removed."
  dim "You can also remove the PATH line added to your shell startup file (search for 'ASTRA installer')."
}

if [[ $UNINSTALL -eq 1 ]]; then
  uninstall_astra
  exit 0
fi

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
printf '\n'
printf '%s\n' "${C_BLUE}  █████╗ ███████╗████████╗██████╗  █████╗${C_RESET}"
printf '%s\n' "${C_BLUE} ██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔══██╗${C_RESET}"
printf '%s\n' "${C_BLUE} ███████║███████╗   ██║   ██████╔╝███████║${C_RESET}"
printf '%s\n' "${C_BLUE} ██╔══██║╚════██║   ██║   ██╔══██╗██╔══██║${C_RESET}"
printf '%s\n' "${C_BLUE} ██║  ██║███████║   ██║   ██║  ██║██║  ██║${C_RESET}"
printf '%s\n' "${C_BLUE} ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝${C_RESET}"
printf '\n'
log "Installing ASTRA to ${INSTALL_DIR}"
dim  "No git, GitHub or coding knowledge needed. This takes a few minutes."
printf '\n'

ensure_download_tools
ensure_python

EXISTING=0
if [[ -f "$INSTALL_DIR/web/astra-web" && -f "$INSTALL_DIR/core/main.py" ]]; then
  EXISTING=1
elif [[ -d "$INSTALL_DIR" ]] && [[ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null || true)" ]]; then
  die "The folder ${INSTALL_DIR} already exists and does not look like an ASTRA install.
Choose another folder with:  --dir ~/ASTRA2"
fi

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/astra-install.XXXXXX")"
cleanup() { rm -rf -- "$TMP_DIR"; }
trap cleanup EXIT INT TERM

SRC_DIR=""
EXTRACT_DIR="${TMP_DIR}/extracted"
TARBALL="${TMP_DIR}/astra.tar.gz"
mkdir -p "$EXTRACT_DIR"

if [[ -n "$ARCHIVE_PATH" ]]; then
  [[ -f "$ARCHIVE_PATH" ]] || die "Archive not found: ${ARCHIVE_PATH}"
  log "Using local archive: ${ARCHIVE_PATH}"
  cp -- "$ARCHIVE_PATH" "$TARBALL"
else
  URL="https://codeload.github.com/${REPO_SLUG}/tar.gz/refs/heads/${BRANCH}"
  log "Downloading ASTRA (${BRANCH})…"
  if ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 --progress-bar "$URL" -o "$TARBALL"; then
    die "Download failed. Check your internet connection and try again.
If you are behind a proxy, see the manual install section in the README."
  fi
fi

log "Unpacking…"
tar -xzf "$TARBALL" -C "$EXTRACT_DIR" 2>/dev/null \
  || die "The downloaded file could not be unpacked. It may be incomplete; please try again."

# GitHub tarballs contain a single top-level folder (ASTRA-main/); archives
# created with `git archive` put the files at the root. Support both.
if [[ -f "${EXTRACT_DIR}/web/astra-web" ]]; then
  SRC_DIR="$EXTRACT_DIR"
else
  for candidate in "$EXTRACT_DIR"/*; do
    if [[ -d "$candidate" && -f "$candidate/web/astra-web" ]]; then
      SRC_DIR="$candidate"
      break
    fi
  done
fi

[[ -n "$SRC_DIR" && -f "$SRC_DIR/core/main.py" ]] \
  || die "The downloaded archive does not look like ASTRA. Please try again or use a release archive."

# Keep a settings file safe even if it ever appears in a future archive.
SETTINGS_BACKUP=""
if [[ -f "$INSTALL_DIR/core/config/settings.json" ]]; then
  SETTINGS_BACKUP="${TMP_DIR}/settings.json"
  cp -p -- "$INSTALL_DIR/core/config/settings.json" "$SETTINGS_BACKUP"
fi

mkdir -p "$INSTALL_DIR"
if [[ $EXISTING -eq 1 ]]; then
  log "Updating the existing installation (your chats and settings are kept)…"
fi
cp -a -- "$SRC_DIR/." "$INSTALL_DIR/"

if [[ -n "$SETTINGS_BACKUP" ]]; then
  cp -p -- "$SETTINGS_BACKUP" "$INSTALL_DIR/core/config/settings.json"
fi

chmod +x "$INSTALL_DIR/web/astra-web" "$INSTALL_DIR/voice/astra-voice" "$INSTALL_DIR/start-dev.sh" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Python environment
# ---------------------------------------------------------------------------
VENV_DIR="${ASTRA_VENV:-${INSTALL_DIR}/core/.venv}"
PYBIN="${VENV_DIR}/bin/python"

if [[ -x "$PYBIN" ]] && ! "$PYBIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  warn "The existing Python environment is too old or broken; recreating it."
  rm -rf -- "$VENV_DIR"
fi

if [[ ! -x "$PYBIN" ]]; then
  log "Creating a private Python environment…"
  if ! "$PYTHON" -m venv "$VENV_DIR"; then
    warn "Could not create the Python environment."
    if [[ "$(uname -s)" == "Linux" ]] && { [[ $ASSUME_YES -eq 1 ]] || { can_prompt && prompt_yes_no "Install the missing Python venv support?" y; }; }; then
      install_python_with_package_manager || true
    fi
    "$PYTHON" -m venv "$VENV_DIR" \
      || die "Could not create a virtual environment.
On Debian/Ubuntu run:  sudo apt install python3-venv
Then run this installer again."
  fi
fi

log "Installing Python packages (this can take a few minutes)…"
"$PYBIN" -m pip install --upgrade pip --disable-pip-version-check --quiet
"$PYBIN" -m pip install --disable-pip-version-check -r "$INSTALL_DIR/requirements.txt" \
  || die "Could not install ASTRA's core packages. Check your internet connection and try again."
"$PYBIN" -m pip install --disable-pip-version-check -r "$INSTALL_DIR/web/requirements.txt" \
  || die "Could not install the web packages. Check your internet connection and try again."

# PDF reading is a core feature but is not declared in requirements.txt upstream.
"$PYBIN" -m pip install --disable-pip-version-check pdfplumber --quiet \
  || warn "PDF reading support could not be installed. Other features still work."

# playwright is imported by the tool registry, so it must be present for ASTRA
# to start; the browser binary is only needed for browser-automation tools.
if ! "$PYBIN" -m pip install --disable-pip-version-check playwright --quiet; then
  warn "Playwright could not be installed. ASTRA may fail to start; please report this."
fi

if [[ $WITH_BROWSER -eq 1 ]]; then
  log "Downloading a private Chromium for browser automation (~150 MB, optional)…"
  if ! "$PYBIN" -m playwright install chromium; then
    warn "Chromium could not be downloaded. Everything except browser automation still works."
  fi
fi

# ---------------------------------------------------------------------------
# Launchers and shortcuts
# ---------------------------------------------------------------------------
log "Creating launchers…"

cat > "$INSTALL_DIR/astra" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="${DIR}/${SOURCE}"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
exec "${DIR}/web/astra-web" "$@"
LAUNCHER

cat > "$INSTALL_DIR/astra-terminal" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="${DIR}/${SOURCE}"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
cd "${DIR}/core"
exec "${DIR}/core/.venv/bin/python" main.py "$@"
LAUNCHER

cat > "$INSTALL_DIR/astra-voice" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="${DIR}/${SOURCE}"
done
DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
exec "${DIR}/voice/astra-voice" "$@"
LAUNCHER

chmod +x "$INSTALL_DIR/astra" "$INSTALL_DIR/astra-terminal" "$INSTALL_DIR/astra-voice"

mkdir -p "$HOME/.local/bin"
ln -sfn "$INSTALL_DIR/astra" "$HOME/.local/bin/astra"
ln -sfn "$INSTALL_DIR/astra-terminal" "$HOME/.local/bin/astra-terminal"
ln -sfn "$INSTALL_DIR/astra-voice" "$HOME/.local/bin/astra-voice"
add_to_path_if_needed

if [[ "$(uname -s)" == "Linux" ]]; then
  APP_DIR="$HOME/.local/share/applications"
  mkdir -p "$APP_DIR"
  cat > "$APP_DIR/astra.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=ASTRA
Comment=AI academic assistant
Exec="${INSTALL_DIR}/astra"
Icon=${INSTALL_DIR}/web/frontend/favicon.svg
Terminal=false
Categories=Education;Utility;
StartupNotify=true
DESKTOP
  chmod +x "$APP_DIR/astra.desktop" 2>/dev/null || true
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  mkdir -p "$HOME/Applications"
  cat > "$HOME/Applications/ASTRA.command" <<MACAPP
#!/bin/bash
exec "${INSTALL_DIR}/astra"
MACAPP
  chmod +x "$HOME/Applications/ASTRA.command"
fi

# ---------------------------------------------------------------------------
# Optional: local AI
# ---------------------------------------------------------------------------
ollama_running() {
  curl -fsS --max-time 3 "http://localhost:11434/api/tags" >/dev/null 2>&1
}

first_ollama_model() {
  local tags
  tags="$(curl -fsS --max-time 3 "http://localhost:11434/api/tags" 2>/dev/null || true)"
  [[ -n "$tags" ]] || return 1
  printf '%s' "$tags" | "$PYBIN" -c '
import json, sys
try:
    data = json.load(sys.stdin)
    models = data.get("models") or []
    if models:
        print(models[0].get("name") or models[0].get("model") or "")
except Exception:
    pass
' 2>/dev/null | head -n 1
}

set_ollama_active() {
  local model="$1"
  if ! (
    cd "$INSTALL_DIR" && "$PYBIN" - "$model" <<'PY'
import sys
sys.path.insert(0, "core")
from ai.settings import get_settings
settings = get_settings()
settings.set_active("ollama", sys.argv[1])
print(f"[ASTRA] Active model: ollama / {sys.argv[1]}")
PY
  ); then
    warn "ASTRA is installed, but the model could not be saved in Settings."
  else
    AI_CONFIGURED=1
  fi
}

install_ollama_and_model() {
  log "Setting up free local AI with Ollama…"
  if ! have ollama; then
    if [[ "$(uname -s)" == "Darwin" ]]; then
      if have brew; then
        log "Installing Ollama with Homebrew…"
        brew install ollama || { warn "Ollama install failed. You can install it later from https://ollama.com/download"; return 1; }
      else
        warn "Homebrew is not installed. Install Ollama from https://ollama.com/download, then run:"
        warn "  ollama pull ${OLLAMA_MODEL}"
        return 1
      fi
    else
      log "Installing Ollama (this may ask for your password)…"
      if ! curl -fsSL https://ollama.com/install.sh | sh; then
        warn "Ollama install failed. You can install it later from https://ollama.com/download"
        return 1
      fi
    fi
  fi

  if ! ollama_running; then
    log "Starting Ollama…"
    nohup ollama serve >"$HOME/.astra-ollama.log" 2>&1 &
    local i=0
    while [[ $i -lt 30 ]]; do
      sleep 1
      if ollama_running; then break; fi
      i=$((i + 1))
    done
  fi

  if ! ollama_running; then
    warn "Ollama is installed but did not start. Open a new terminal and run: ollama serve"
    return 1
  fi

  log "Downloading the ${OLLAMA_MODEL} model (about 2–3 GB; this is the slow part)…"
  if ! ollama pull "$OLLAMA_MODEL"; then
    warn "The model download failed. Start ASTRA and use Settings → Local (Ollama) to retry."
    return 1
  fi

  set_ollama_active "$OLLAMA_MODEL"
  ok "Free local AI is ready (${OLLAMA_MODEL})."
}

FRESH=0
if [[ ! -f "$INSTALL_DIR/core/config/settings.json" ]]; then
  FRESH=1
fi

if [[ "$OLLAMA_MODE" == "ask" ]]; then
  if [[ $FRESH -eq 1 && $EXISTING -eq 0 ]]; then
    if can_prompt; then
      printf '\n' > /dev/tty
      printf 'ASTRA needs an AI model. You can either:\n' > /dev/tty
      printf '  1. Run a free model on this computer (private, no API key, ~2–3 GB download)\n' > /dev/tty
      printf '  2. Use a cloud API key from OpenAI, Anthropic or Google (set up in the app)\n\n' > /dev/tty
      if prompt_yes_no "Set up the free local model now?" y; then
        OLLAMA_MODE="yes"
      else
        OLLAMA_MODE="no"
      fi
    else
      OLLAMA_MODE="no"
    fi
  else
    OLLAMA_MODE="no"
  fi
fi

if [[ "$OLLAMA_MODE" == "yes" ]]; then
  install_ollama_and_model || true
elif [[ $FRESH -eq 1 && $OLLAMA_EXPLICIT -eq 0 ]]; then
  # If the user already has Ollama running, adopt the first installed model so
  # ASTRA works immediately instead of showing an empty setup screen.
  if ollama_running; then
    EXISTING_MODEL="$(first_ollama_model || true)"
    if [[ -n "$EXISTING_MODEL" ]]; then
      set_ollama_active "$EXISTING_MODEL"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
printf '\n'
ok "ASTRA is installed and ready."
printf '\n'
printf '  %sStart ASTRA:%s      astra\n' "$C_GREEN" "$C_RESET"
printf '  %sIf that fails:%s     %s/astra\n' "$C_GREEN" "$C_RESET" "$INSTALL_DIR"
printf '  %sTerminal mode:%s    astra-terminal\n' "$C_GREEN" "$C_RESET"
printf '  %sVoice mode:%s       astra-voice        (first run: astra-voice --setup)\n' "$C_GREEN" "$C_RESET"
printf '  %sInstall folder:%s   %s\n' "$C_GREEN" "$C_RESET" "$INSTALL_DIR"
printf '\n'
dim "The app opens at http://127.0.0.1:8765"
dim "First time? Click the ⚙ Settings button in the app to choose your AI."
dim "Update later by re-running the same install command; your data is kept."
dim "Uninstall with: curl -fsSL https://raw.githubusercontent.com/${REPO_SLUG}/main/install.sh | bash -s -- --uninstall"
printf '\n'

if [[ $FRESH -eq 1 && $AI_CONFIGURED -eq 0 ]]; then
  warn "No AI model is configured yet. In the app, open Settings (⚙) and either:"
  warn "  • choose Local (Ollama) → Install & download, or"
  warn "  • paste an API key for OpenAI, Anthropic or Google."
  printf '\n'
fi

if [[ $NO_LAUNCH -eq 0 ]] && can_prompt && prompt_yes_no "Start ASTRA now?" y; then
  exec "$INSTALL_DIR/astra"
fi
