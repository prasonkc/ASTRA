"""Shared in-memory bridge between ASTRA core and the ASTRA Firefox extension.

Three channels are bridged here, all between the ASTRA process (terminal app or
web wrapper) and the browser extension:

1. **Page context** — the extension *pushes* snapshots of the page the user is
   viewing (URL, title, HTML, visible text, selected text, mouse position). The
   HTTP layer writes here; the ``browser_context`` tool reads here.

2. **Command queue** — the core *pushes* commands (``ext_*`` tools) that the
   extension *pulls* and executes in the user's browser, then posts the result
   back. Because a browser extension cannot accept inbound connections, this is
   a poll-based reverse channel:

       tool ──enqueue──▶ queue ──GET /api/browser/commands──▶ extension
         ▲                                                            │
         └─────────────── result/condition ──POST .../result◀───────┘

3. **Chat messages** — the extension popup *posts* a message to the running
   agent and shows the reply. The frontend registers a handler
   (:func:`set_message_handler`); ``POST /api/browser/message`` calls
   :func:`run_message`, which invokes it.

Everything is in-memory and lock/condition guarded because the HTTP handlers
(asyncio threadpool or the stdlib bridge thread) and the core worker thread run
on different threads.
"""
from __future__ import annotations

import itertools
import threading
import time
from typing import Any, Callable, Dict, Optional

# --------------------------------------------------------------------------
# Channel 1: page context
# --------------------------------------------------------------------------

_lock = threading.Lock()
_context: Optional[Dict[str, Any]] = None


def set_context(data: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a (possibly partial) browser snapshot into the stored one.

    Merging lets the extension post large fields (HTML, text) only when the page
    changes and tiny fields (mouse position) frequently, without the small
    updates wiping the large ones.
    """
    global _context
    with _lock:
        stored = dict(_context) if _context is not None else {}
        for key, value in (data or {}).items():
            if value is not None:
                stored[key] = value
        stored["received_at"] = time.time()
        _context = stored
        return dict(stored)


def get_context() -> Optional[Dict[str, Any]]:
    """Return the latest browser snapshot, or ``None`` if nothing arrived yet."""
    with _lock:
        return dict(_context) if _context is not None else None


def clear_context() -> None:
    """Forget the stored snapshot (used when the extension disconnects)."""
    global _context
    with _lock:
        _context = None


# --------------------------------------------------------------------------
# Channel 2: command queue (core -> extension -> core)
# --------------------------------------------------------------------------
#
# A command lifecycle:
#   "pending"  enqueued by a tool, waiting for the extension to claim it
#   "claimed"  handed out via GET /api/browser/commands, executing in the browser
#   "done"     result posted back           (ok=True)
#   "error"    result posted back or timeout (ok=False)
#
# The enqueuing thread blocks on a condition until the extension posts the
# result, so tool calls read like normal function calls.

_cmd_lock = threading.Lock()
_cmd_cond = threading.Condition(_cmd_lock)
_command_ids = itertools.count(1)
_commands: Dict[int, Dict[str, Any]] = {}

DEFAULT_COMMAND_TIMEOUT = 60.0  # seconds a tool waits for the extension
COMMAND_TTL = 120.0  # seconds before an unclaimed command is dropped


def enqueue_command(
    name: str, arguments: Optional[Dict[str, Any]] = None, timeout: float = DEFAULT_COMMAND_TIMEOUT
) -> Dict[str, Any]:
    """Queue ``name(arguments)`` for the extension and wait for the result.

    Returns a dict describing the outcome::

        {"id", "name", "success": bool, "result": Any | None, "error": str | None}

    Blocks up to ``timeout`` seconds. On timeout the command is marked ``error``
    with a message telling the model what to check.
    """
    command_id = next(_command_ids)
    command: Dict[str, Any] = {
        "id": command_id,
        "name": name,
        "arguments": dict(arguments or {}),
        "status": "pending",
        "result": None,
        "error": None,
        "created_at": time.time(),
    }

    with _cmd_cond:
        _prune_stale_commands()
        _commands[command_id] = command

        deadline = time.time() + timeout
        while command["status"] in ("pending", "claimed"):
            remaining = deadline - time.time()
            if remaining <= 0:
                command["status"] = "error"
                command["error"] = (
                    "Timed out waiting for the browser extension to run "
                    f"'{name}'. Make sure the ASTRA Firefox extension is loaded "
                    "and 'Integrate ASTRA with webpages' is switched on, and that "
                    "the page you want to automate is the active tab."
                )
                break
            _cmd_cond.wait(remaining)

        outcome = {
            "id": command_id,
            "name": name,
            "success": command["status"] == "done",
            "result": command["result"],
            "error": command["error"],
        }
        _commands.pop(command_id, None)  # keep memory bounded; result already returned
        return outcome


def next_command() -> Optional[Dict[str, Any]]:
    """Return the oldest unclaimed command for the extension, or ``None``.

    The command is marked ``claimed`` so a second poll never receives it again.
    """
    with _cmd_cond:
        for command_id in sorted(_commands):
            command = _commands[command_id]
            if command["status"] == "pending":
                command["status"] = "claimed"
                command["claimed_at"] = time.time()
                return {
                    "id": command_id,
                    "name": command["name"],
                    "arguments": command["arguments"],
                }
        return None


def submit_command_result(
    command_id: int, ok: bool, result: Any = None, error: Optional[str] = None
) -> bool:
    """Record the extension's outcome for a claimed command.

    Returns ``True`` when the command was still being waited on, ``False`` when
    it is unknown (already finished, pruned, or never existed).
    """
    with _cmd_cond:
        command = _commands.get(command_id)
        if command is None:
            return False
        if command["status"] not in ("pending", "claimed"):
            return False
        command["status"] = "done" if ok else "error"
        command["result"] = result
        command["error"] = error
        command["finished_at"] = time.time()
        _cmd_cond.notify_all()
        return True


def command_count() -> int:
    """Number of commands currently in the queue (for debugging)."""
    with _cmd_cond:
        return len(_commands)


def _prune_stale_commands() -> None:
    """Drop commands older than ``COMMAND_TTL`` so the queue cannot grow forever."""
    now = time.time()
    for command_id in list(_commands):
        if now - _commands[command_id]["created_at"] > COMMAND_TTL:
            _commands.pop(command_id, None)


def command_poll_payload() -> Dict[str, Any]:
    """Payload for ``GET /api/browser/commands`` (HTTP layer helper)."""
    command = next_command()
    return {"command": command}


# --------------------------------------------------------------------------
# Channel 3: chat messages (extension popup -> ASTRA agent -> extension)
# --------------------------------------------------------------------------
# The extension popup can send a chat message straight to the running ASTRA
# agent and show the reply. Unlike the command queue (core -> extension), this
# flows the other way: the frontend owns the agent, so it *registers* a handler
# that runs one turn; the shared HTTP route simply calls :func:`run_message`
# and the handler does the work on whatever thread/worker that frontend uses.
#
#   popup ──POST /api/browser/message──▶ run_message ──▶ handler ──▶ agent
#                              reply ◀──────────────────────────────┘

_message_lock = threading.Lock()
_message_handler: Optional[Callable[[str], Dict[str, Any]]] = None


def set_message_handler(handler: Optional[Callable[[str], Dict[str, Any]]]) -> None:
    """Register the callable that runs one chat turn for the extension.

    The handler receives the raw message text and returns a dict like
    ``{"reply": str, "session_id": str | None, "error": str | None}``.
    """
    global _message_handler
    with _message_lock:
        _message_handler = handler


def clear_message_handler() -> None:
    """Forget the chat handler (used on shutdown)."""
    set_message_handler(None)


def run_message(message: str) -> Dict[str, Any]:
    """Run one chat turn for the extension and return a JSON-ready result.

    Never raises: an empty message, a missing agent, or an agent error all come
    back as ``{"ok": False, "error": "..."}`` so the HTTP layers stay trivial.
    """
    text = (message or "").strip()
    if not text:
        return {"ok": False, "reply": "", "error": "Message cannot be empty", "session_id": None}

    with _message_lock:
        handler = _message_handler

    if handler is None:
        return {
            "ok": False,
            "reply": "",
            "error": "ASTRA chat is not available yet. Make sure ASTRA is running.",
            "session_id": None,
        }

    try:
        outcome = handler(text)
    except Exception as exc:  # keep the bridge alive for the extension
        return {"ok": False, "reply": "", "error": f"ASTRA failed to respond: {exc}", "session_id": None}

    if isinstance(outcome, dict):
        reply = str(outcome.get("reply") or "").strip()
        error = outcome.get("error")
        session_id = outcome.get("session_id")
    else:
        reply = str(outcome or "").strip()
        error = None
        session_id = None

    ok = bool(reply) and not error
    return {"ok": ok, "reply": reply, "error": error, "session_id": session_id}
