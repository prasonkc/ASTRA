"""Helpers for the "local setup" flow.

This module drives the out-of-the-box local experience: detect/install the
Ollama runtime, start its server, list the models already on the machine and
pull new ones. It is shared by the terminal ``/provider`` command and the web
settings panel, and only ever runs when the user explicitly asks for it.

Every long-running step accepts a ``progress`` callback ``(text: str) -> None``
so callers can stream output to a terminal or an HTTP response.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests

Progress = Optional[Callable[[str], None]]

DEFAULT_HOST = "http://localhost:11434"

# A small, curated set of models that are known to work well with ASTRA's
# tool-calling loop. Ollama has no "list the whole registry" API, so instead of
# pretending to enumerate everything we offer good defaults and let users type
# any tag they like.
RECOMMENDED_MODELS: List[Dict[str, str]] = [
    {"name": "qwen3:14b", "size": "~9 GB", "description": "Best all-rounder; strong reasoning and tools (default)."},
    {"name": "qwen3:8b", "size": "~5 GB", "description": "Lighter Qwen3; good balance of speed and quality."},
    {"name": "qwen3:4b", "size": "~2.6 GB", "description": "Fast and small; great on laptops."},
    {"name": "llama3.2:3b", "size": "~2 GB", "description": "Very light general model from Meta."},
    {"name": "llama3.1:8b", "size": "~4.7 GB", "description": "Solid general-purpose 8B model."},
    {"name": "gemma3:4b", "size": "~3.3 GB", "description": "Google's compact open model."},
    {"name": "mistral:7b", "size": "~4.1 GB", "description": "Classic fast 7B instruct model."},
    {"name": "deepseek-r1:8b", "size": "~4.9 GB", "description": "Reasoning-focused distilled model."},
]


def _emit(progress: Progress, text: str) -> None:
    if progress:
        try:
            progress(text)
        except Exception:
            pass


def host_url(host: Optional[str] = None) -> str:
    host = host or os.environ.get("ASTRA_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
    if not host.startswith("http"):
        host = f"http://{host}"
    return host.rstrip("/")


# --- detection ---------------------------------------------------------------
def is_ollama_installed() -> bool:
    if shutil.which("ollama"):
        return True
    # Common non-PATH install locations.
    candidates = [
        Path.home() / ".ollama" / "bin" / "ollama",
        Path("/usr/local/bin/ollama"),
        Path("/opt/homebrew/bin/ollama"),
    ]
    return any(c.exists() for c in candidates)


def ollama_version() -> Optional[str]:
    exe = shutil.which("ollama")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15)
        return (out.stdout or out.stderr).strip() or None
    except Exception:
        return None


def is_ollama_running(host: Optional[str] = None, timeout: float = 2.0) -> bool:
    try:
        resp = requests.get(f"{host_url(host)}/api/version", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def list_local_models(host: Optional[str] = None) -> List[Dict[str, object]]:
    """Return the models already present on the local Ollama server."""
    try:
        resp = requests.get(f"{host_url(host)}/api/tags", timeout=5)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []
    models = []
    for item in data.get("models", []) or []:
        name = item.get("name") or item.get("model") or ""
        size = item.get("size") or 0
        models.append({
            "name": name,
            "size": size,
            "size_human": _human_size(size),
            "modified_at": item.get("modified_at"),
        })
    return models


def _human_size(num: Optional[float]) -> str:
    if not num:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num)
    for unit in units:
        if value < 1000 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1000
    return ""


# --- installation ------------------------------------------------------------
def install_ollama(progress: Progress = None) -> bool:
    """Best-effort installation of the Ollama runtime for the current OS."""
    system = platform.system().lower()
    _emit(progress, f"Installing Ollama on {platform.system()}…")

    if system == "linux":
        if not shutil.which("curl"):
            _emit(progress, "curl is required to install Ollama automatically.")
            _emit(progress, "Install curl, or install Ollama manually: https://ollama.com/download")
            return False
        cmd = "curl -fsSL https://ollama.com/install.sh | sh"
    elif system == "darwin":
        if shutil.which("brew"):
            cmd = "brew install ollama"
        else:
            _emit(progress, "Homebrew not found. Download Ollama from https://ollama.com/download")
            return False
    elif system == "windows":
        if shutil.which("winget"):
            cmd = "winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements"
        else:
            _emit(progress, "winget not found. Download Ollama from https://ollama.com/download")
            return False
    else:
        _emit(progress, f"Automatic install is not supported on {platform.system()}.")
        _emit(progress, "Please install Ollama manually: https://ollama.com/download")
        return False

    return _run_streaming(cmd, progress) and is_ollama_installed()


def _run_streaming(cmd: str, progress: Progress = None, timeout: Optional[int] = None) -> bool:
    """Run a shell command, streaming combined output line by line."""
    _emit(progress, f"$ {cmd}")
    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as exc:
        _emit(progress, f"Failed to start command: {exc}")
        return False

    start = time.time()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            _emit(progress, line.rstrip())
            if timeout and time.time() - start > timeout:
                proc.kill()
                _emit(progress, "Timed out.")
                return False
    except Exception as exc:
        _emit(progress, f"Error while running command: {exc}")
    finally:
        proc.wait()
    return proc.returncode == 0


def start_ollama_server(progress: Progress = None, host: Optional[str] = None, wait: float = 20.0) -> bool:
    """Ensure the Ollama server is running (start ``ollama serve`` if needed)."""
    if is_ollama_running(host):
        return True
    exe = shutil.which("ollama")
    if not exe:
        _emit(progress, "Ollama is not installed.")
        return False
    _emit(progress, "Starting the Ollama server…")
    try:
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        _emit(progress, f"Could not start 'ollama serve': {exc}")
        return False
    deadline = time.time() + wait
    while time.time() < deadline:
        if is_ollama_running(host):
            _emit(progress, "Ollama server is up.")
            return True
        time.sleep(0.5)
    _emit(progress, "Ollama server did not become ready in time.")
    return False


# --- pulling models ----------------------------------------------------------
def pull_model(model: str, progress: Progress = None, host: Optional[str] = None) -> bool:
    """Pull a model, streaming download progress."""
    if not model:
        return False
    if not start_ollama_server(progress, host):
        return False

    _emit(progress, f"Pulling '{model}'…")
    try:
        resp = requests.post(
            f"{host_url(host)}/api/pull",
            json={"name": model, "stream": True},
            stream=True,
            timeout=3600,
        )
    except Exception as exc:
        _emit(progress, f"Could not start download: {exc}")
        return False

    if resp.status_code != 200:
        _emit(progress, f"Download failed ({resp.status_code}): {resp.text[:200]}")
        return False

    last_status = None
    try:
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event.get("error"):
                _emit(progress, f"Error: {event['error']}")
                return False
            status = event.get("status") or ""
            total = event.get("total")
            completed = event.get("completed")
            if total and completed is not None:
                pct = (completed / total) * 100 if total else 0
                line = f"{status} {pct:5.1f}% ({_human_size(completed)}/{_human_size(total)})"
            else:
                line = status
            if line and line != last_status:
                _emit(progress, line)
                last_status = line
    except Exception as exc:
        _emit(progress, f"Error while downloading: {exc}")
        return False
    finally:
        resp.close()

    _emit(progress, f"'{model}' is ready.")
    return True


def install_and_pull(model: str, progress: Progress = None, host: Optional[str] = None) -> bool:
    """Full out-of-the-box flow: install Ollama if needed, start it, pull model."""
    if not is_ollama_installed():
        if not install_ollama(progress):
            return False
    if not start_ollama_server(progress, host):
        return False
    return pull_model(model, progress, host)


def local_status(host: Optional[str] = None) -> Dict[str, object]:
    """A JSON-serializable snapshot for the web UI / CLI."""
    installed = is_ollama_installed()
    running = is_ollama_running(host)
    models = list_local_models(host) if running else []
    return {
        "installed": installed,
        "running": running,
        "version": ollama_version(),
        "host": host_url(host),
        "models": models,
        "recommended": RECOMMENDED_MODELS,
    }
