"""
ASTRA service layer.

This is a *thin* wrapper around the standalone ASTRA core. It deliberately does
not reimplement any agent logic: it imports the same modules the terminal app
uses (``ai.ollama``, ``memory.chat_history``) and exposes them through a small,
streaming-friendly API for the web frontend.

Two important design decisions:

1. The core resolves several paths relative to its own directory
   (``./memory/*.db``, ``./config/identity.txt``, ``./downloads``), so this
   module makes the core directory the process working directory and puts it on
   ``sys.path`` before importing anything from it.

2. The terminal app is single-threaded, and several core components (SQLite
   connections, the Playwright event loop, etc.) are *thread-affine*. To keep
   the web wrapper byte-for-byte identical in behaviour, every core operation is
   executed on one persistent worker thread. Requests are answered through
   ``concurrent.futures`` futures; chat turns are streamed through a per-turn
   queue bridged from that worker to the HTTP response.
"""
from __future__ import annotations

import itertools
import os
import queue
import sys
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

# --- Locate the repository and wire up the standalone core -------------------
WEB_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = WEB_DIR.parent
CORE_DIR = REPO_DIR / "core"
FRONTEND_DIR = WEB_DIR / "frontend"

if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

# The core uses CWD-relative paths; run it exactly like the terminal app does.
os.chdir(CORE_DIR)

from ai import local_setup  # noqa: E402
from ai import settings as settings_module  # noqa: E402
from ai.model import AgentModel  # noqa: E402
from memory.chat_history import ChatHistory  # noqa: E402
import browser_bridge  # noqa: E402  (core is on sys.path)


MAX_RESULT_CHARS = 20_000


def set_browser_context(data: dict) -> dict:
    """Store the latest page snapshot sent by the ASTRA browser extension."""
    return browser_bridge.set_context(data)


def get_browser_context():
    """Return the latest page snapshot, or ``None`` if none arrived yet."""
    return browser_bridge.get_context()


def clear_browser_context() -> None:
    """Forget the stored page snapshot."""
    browser_bridge.clear_context()


def command_poll_payload() -> dict:
    """Next queued browser command for the extension, or ``command: None``."""
    return browser_bridge.command_poll_payload()


def submit_command_result(command_id: int, ok: bool, result=None, error: str = None) -> bool:
    """Record the extension's result and wake the waiting tool."""
    return browser_bridge.submit_command_result(
        command_id, ok=bool(ok), result=result, error=error
    )


def run_browser_message(message: str) -> dict:
    """Run one chat turn for the ASTRA Firefox extension popup.

    The actual work happens in the handler registered by
    :func:`register_browser_message_handler` (the running ``AstraService``), so
    the popup shares the conversation the web UI is using.
    """
    return browser_bridge.run_message(message)


def register_browser_message_handler() -> None:
    """Tell the browser bridge how to run a chat turn in this process."""
    browser_bridge.set_message_handler(get_service().run_message)


def _build_model(model_name: Optional[str] = None, provider: Optional[str] = None) -> "AgentModel":
    """Construct the core model on the caller thread (the core worker).

    ``model_name``/``provider`` override the configured defaults; when omitted
    they are resolved from :mod:`ai.settings` (environment + settings file).
    """
    # Resume the most recent conversation instead of spawning a fresh empty
    # session on every server start.
    latest = _latest_session_id()
    if latest:
        return AgentModel(model_name, session_id=latest, provider=provider)
    return AgentModel(model_name, provider=provider)


def _latest_session_id() -> Optional[str]:
    """Return the most recent session id, if any, without creating one."""
    try:
        history = ChatHistory()
    except Exception:
        return None
    try:
        return history.get_latest_session_id()
    finally:
        history.close()


def _truncate(text, limit: int = MAX_RESULT_CHARS) -> str:
    text = "" if text is None else str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… (truncated)"


class AstraService:
    """
    Serialized access to a single ASTRA core instance.

    All core operations run on one dedicated worker thread so the model, its
    tools and its databases behave exactly as they do in the terminal app.
    Client requests are additionally guarded by an RLock so a long chat turn
    cannot interleave with a session mutation.
    """

    def __init__(self, model_name: Optional[str] = None, provider: Optional[str] = None):
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="astra-core")
        # Construct the model on the worker thread so every tool/DB connection
        # is created and used by that same thread, mirroring the terminal.
        self.model = self._executor.submit(_build_model, model_name, provider).result()
        self.model_name = self.model.model_name
        self.provider_name = self.model.provider_name

    # ---- helpers ------------------------------------------------------------
    def _call(self, operation, *args):
        """Run a core operation on the worker thread and block for the result."""
        with self._lock:
            return self._executor.submit(operation, *args).result()

    # Core operations below run ON the worker thread (bound to self.model).

    def _recover_session_if_missing(self) -> None:
        """If the core's in-memory session no longer exists on disk (someone
        cleared the database or deleted the session from another client), fall
        back to the most recent session — or start a fresh one — instead of
        silently keeping a dead session_id. Without this, all subsequent writes
        fail with "Session not found" and conversations appear to vanish.
        """
        try:
            if not self.model.chat_history.session_exists(self.model.session_id):
                if not self.model.resume_last_session():
                    self.model.new_session()
        except Exception:
            pass

    def _op_current_session(self) -> str:
        self._recover_session_if_missing()
        return self.model.session_id

    def _op_list_sessions(self, limit: int) -> List[Dict]:
        return self.model.list_sessions_with_preview(limit)

    def _op_create_session(self, title: Optional[str]) -> str:
        session_id = self.model.new_session()
        if title:
            try:
                self.model.chat_history.update_session_title(session_id, title)
            except Exception:
                pass
        return session_id

    def _op_switch_session(self, session_id: str) -> bool:
        return self.model.switch_session(session_id)

    def _op_delete_session(self, session_id: str) -> bool:
        was_current = session_id == self.model.session_id
        deleted = self.model.delete_session(session_id)
        if deleted and was_current:
            # Fall back to the next most recent session, or a fresh one.
            if not self.model.resume_last_session():
                self.model.new_session()
        return deleted

    def _op_get_messages(self, session_id: str, limit: int) -> List[Dict]:
        if not self.model.chat_history.session_exists(session_id):
            return []
        history = self.model.chat_history.get_history(session_id, limit=limit)
        return [m for m in history if m.get("role") != "system"]

    def _op_close(self) -> None:
        try:
            self.model.close()
        except Exception:
            pass

    def _op_set_provider(self, provider, model, api_key, base_url, thinking=None) -> Dict:
        """Persist the selected provider/model (and key/url) and swap the backend."""
        settings = settings_module.get_settings()
        provider = settings_module.normalize_provider(provider)
        if api_key is not None:
            settings.set_api_key(provider, api_key)
        if base_url is not None:
            settings.set_base_url(provider, base_url)
        if thinking is not None:
            settings.set_thinking(thinking)
        settings.set_active(provider, model)
        resolved = settings.active_model(provider)
        snapshot = self.model.reconfigure(provider, resolved)
        self.model_name = snapshot["model"]
        self.provider_name = snapshot["provider"]
        return snapshot

    # ---- public, decision-free proxy methods ---------------------------------
    def current_session(self) -> str:
        return self._call(self._op_current_session)

    def list_sessions(self, limit: int = 50) -> List[Dict]:
        return self._call(self._op_list_sessions, limit)

    def create_session(self, title: Optional[str] = None) -> str:
        return self._call(self._op_create_session, title)

    def switch_session(self, session_id: str) -> bool:
        return self._call(self._op_switch_session, session_id)

    def delete_session(self, session_id: str) -> bool:
        return self._call(self._op_delete_session, session_id)

    def get_messages(self, session_id: str, limit: int = 200) -> List[Dict]:
        return self._call(self._op_get_messages, session_id, limit)

    def close(self) -> None:
        try:
            self._call(self._op_close)
        finally:
            self._executor.shutdown(wait=True)

    # ---- provider / model configuration -------------------------------------
    def get_config(self) -> Dict:
        """Snapshot of the provider configuration (API keys masked).

        Deliberately avoids the core worker so the settings panel stays
        responsive even while a long reply is streaming.
        """
        settings = settings_module.get_settings()
        public = settings.to_public()
        try:
            public["live"] = self.model.describe()
        except Exception:
            public["live"] = {"provider": self.provider_name, "model": self.model_name}
        try:
            public["ollama"] = local_setup.local_status(settings.base_url("ollama"))
        except Exception as exc:
            public["ollama"] = {
                "installed": False,
                "running": False,
                "models": [],
                "recommended": local_setup.RECOMMENDED_MODELS,
                "error": str(exc),
            }
        return public

    def set_provider(
        self,
        provider: str,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        thinking: Optional[bool] = None,
    ) -> Dict:
        """Persist and activate a provider/model. Runs on the core worker."""
        return self._call(self._op_set_provider, provider, model, api_key, base_url, thinking)

    def set_thinking(self, enabled: bool) -> bool:
        """Toggle thinking for the active model and return the effective value.

        Writes straight to settings (which has its own lock) instead of going
        through the core worker, so it stays responsive even while a long reply
        is streaming — the agent loop reads the flag on its next model call.
        """
        settings = settings_module.get_settings()
        settings.set_thinking(enabled)
        return settings.thinking()

    def local_status(self) -> Dict:
        settings = settings_module.get_settings()
        return local_setup.local_status(settings.base_url("ollama"))

    def list_local_models(self) -> List[Dict]:
        settings = settings_module.get_settings()
        return local_setup.list_local_models(settings.base_url("ollama"))

    def stream_local_setup(self, model: str, install: bool = True):
        """Yield events while installing Ollama (optional) and pulling a model.

        This runs off the core worker thread (it only talks to the Ollama HTTP
        API), so it can stream download progress without blocking chat — except
        for the final activation, which is marshalled onto the worker.
        """
        events: "queue.Queue" = queue.Queue()

        def progress(text: str) -> None:
            events.put({"type": "progress", "message": str(text)})

        def run() -> None:
            try:
                settings = settings_module.get_settings()
                host = settings.base_url("ollama")
                if install:
                    ok = local_setup.install_and_pull(model, progress, host)
                else:
                    ok = local_setup.start_ollama_server(progress, host) and \
                        local_setup.pull_model(model, progress, host)
                events.put({"type": "result", "ok": bool(ok), "model": model})
                if ok:
                    events.put({"type": "config", "config": self.set_provider("ollama", model)})
            except Exception as exc:
                events.put({"type": "error", "message": str(exc)})
            finally:
                events.put(None)

        threading.Thread(target=run, name="astra-local-setup", daemon=True).start()
        while True:
            item = events.get()
            if item is None:
                break
            yield item

    # ---- chat ---------------------------------------------------------------
    def stream_chat(self, prompt: str, session_id: Optional[str] = None):
        """
        Yield JSON-serializable event dicts for one chat turn.

        This is a blocking generator intended to be consumed by the streaming
        HTTP endpoint. Events: ``session``, ``thinking``, ``content``,
        ``tool_call``, ``tool_result``, ``error`` and ``done``.
        """
        with self._lock:
            events: "queue.Queue" = queue.Queue()
            stop_event = threading.Event()

            # Run the entire turn on the persistent core worker thread.
            self._executor.submit(
                self._op_chat_turn, prompt, session_id, events, stop_event
            )

            try:
                while True:
                    item = events.get()
                    if item is None:
                        break
                    yield item
            finally:
                # Reached when the client disconnects/aborts mid-stream.
                stop_event.set()

    def run_message(self, prompt: str) -> Dict:
        """Run one chat turn for the browser extension and return its reply text.

        Reuses :meth:`stream_chat`, so the extension popup shares one
        conversation (session, history, provider) with the web UI and is
        naturally serialized with web chat turns by the same lock.
        """
        content_parts: List[str] = []
        error_text: Optional[str] = None
        session_id: Optional[str] = None

        for event in self.stream_chat(prompt):
            etype = event.get("type")
            if etype == "content":
                content_parts.append(event.get("delta") or "")
            elif etype == "session":
                session_id = event.get("session_id")
            elif etype == "error":
                error_text = event.get("message")

        return {
            "reply": "".join(content_parts).strip(),
            "session_id": session_id,
            "error": error_text,
        }

    def _op_chat_turn(self, prompt, session_id, events, stop_event) -> None:
        """Execute one chat turn on the core worker thread."""
        counter = itertools.count(1)
        pending_calls: deque = deque()

        def on_event(event: dict) -> None:
            etype = event.get("type")
            if etype == "tool_call":
                call_id = next(counter)
                pending_calls.append(call_id)
                events.put({
                    "type": "tool_call",
                    "id": call_id,
                    "name": event.get("name") or "tool",
                    "arguments": event.get("arguments") or {},
                })
            elif etype == "tool_result":
                call_id = pending_calls.popleft() if pending_calls else None
                events.put({
                    "type": "tool_result",
                    "id": call_id,
                    "name": event.get("name") or "tool",
                    "success": bool(event.get("success", True)),
                    "result": _truncate(event.get("result", "")),
                })

        try:
            # The browser may be pointing at a session that no longer exists
            # on disk (deleted via the UI, or by the terminal app's /clear).
            # Recover first so this turn persists instead of silently failing.
            self._recover_session_if_missing()

            if session_id and session_id != self.model.session_id:
                if not self.model.switch_session(session_id):
                    # The requested session is gone too → fall back to the
                    # newest session (or a fresh one) rather than dropping
                    # the reply on the floor.
                    if not self.model.resume_last_session():
                        self.model.new_session()

            active_id = self.model.session_id

            # Give brand-new conversations a useful title from the first prompt.
            try:
                if self.model.chat_history.get_message_count(active_id) <= 1:
                    title = prompt.strip().splitlines()[0][:60]
                    if title:
                        self.model.chat_history.update_session_title(active_id, title)
            except Exception:
                pass

            events.put({"type": "session", "session_id": active_id})

            generator = self.model.generate(prompt, on_event=on_event)
            for chunk in generator:
                if stop_event.is_set():
                    break
                message = getattr(chunk, "message", None)
                if message is None:
                    continue
                thinking = getattr(message, "thinking", None)
                content = getattr(message, "content", None)
                if thinking:
                    events.put({"type": "thinking", "delta": thinking})
                if content:
                    events.put({"type": "content", "delta": content})

            events.put({"type": "done", "session_id": active_id})
        except Exception as exc:  # keep the stream alive for the client
            events.put({"type": "error", "message": str(exc)})
        finally:
            events.put(None)


# --- process-wide singleton --------------------------------------------------
_service: Optional[AstraService] = None
_service_lock = threading.Lock()


def get_service() -> AstraService:
    global _service
    with _service_lock:
        if _service is None:
            _service = AstraService()
        return _service