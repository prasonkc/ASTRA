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

from ai.ollama import OllamaModel  # noqa: E402
from memory.chat_history import ChatHistory  # noqa: E402


DEFAULT_MODEL = os.environ.get("ASTRA_MODEL", "qwen3:14b")
MAX_RESULT_CHARS = 20_000


def _build_model(model_name: str) -> "OllamaModel":
    """Construct the core model on the caller thread (the core worker)."""
    # Resume the most recent conversation instead of spawning a fresh empty
    # session on every server start.
    latest = _latest_session_id()
    if latest:
        return OllamaModel(model_name, session_id=latest)
    return OllamaModel(model_name)


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

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or DEFAULT_MODEL
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="astra-core")
        # Construct the model on the worker thread so every tool/DB connection
        # is created and used by that same thread, mirroring the terminal.
        self.model = self._executor.submit(_build_model, self.model_name).result()

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