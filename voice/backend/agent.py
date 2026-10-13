"""Bridge between the voice loop and the ASTRA agent.

The voice wrapper is a *frontend*, exactly like ``web/``: it embeds the core and
lets the agent run. Rather than duplicate the core's thread-affine bookkeeping
(SQLite connections, tool runtimes), it reuses
:class:`web.backend.astra_service.AstraService`, which already serialises every
core operation onto one worker thread. The result is one shared brain, three
shells (terminal, web, voice).

Turns are streamed so the transcript can be printed live; the collected text is
what gets spoken.
"""
from __future__ import annotations

import sys
from typing import Callable, Dict, List, Optional

from .config import REPO_DIR


class AgentError(RuntimeError):
    """Raised when the ASTRA core cannot be initialised."""


def _load_service_class():
    """Import ``AstraService`` from the web wrapper (adds the repo to ``sys.path``)."""
    if str(REPO_DIR) not in sys.path:
        sys.path.insert(0, str(REPO_DIR))
    from web.backend.astra_service import AstraService  # noqa: E402

    return AstraService


class VoiceAgent:
    """A thin, voice-friendly facade over one ASTRA conversation."""

    def __init__(self, service=None, model_name: Optional[str] = None):
        if service is None:
            try:
                service = _load_service_class()(model_name)
            except Exception as exc:  # noqa: BLE001 - surface a clear message
                raise AgentError(f"Could not start the ASTRA core: {exc}") from exc
        self.service = service
        self.session_id: Optional[str] = None

    def ask(
        self,
        prompt: str,
        on_delta: Optional[Callable[[str], None]] = None,
        on_tool: Optional[Callable[[str], None]] = None,
    ) -> Dict:
        """Run one turn; return ``{reply, error, session_id, tools}``.

        ``on_delta`` is called with each streamed content fragment and
        ``on_tool`` with each tool name the model invokes.
        """
        parts: List[str] = []
        tools: List[str] = []
        error: Optional[str] = None

        for event in self.service.stream_chat(prompt):
            etype = event.get("type")
            if etype == "content":
                delta = event.get("delta") or ""
                if delta:
                    parts.append(delta)
                    if on_delta:
                        on_delta(delta)
            elif etype == "session":
                self.session_id = event.get("session_id")
            elif etype == "tool_call":
                name = event.get("name") or "tool"
                tools.append(name)
                if on_tool:
                    on_tool(name)
            elif etype == "error":
                error = event.get("message")

        return {
            "reply": "".join(parts).strip(),
            "error": error,
            "session_id": self.session_id,
            "tools": tools,
        }

    def describe(self) -> Dict:
        """Provider/model/session summary, when the core can provide one."""
        try:
            return self.service.model.describe()
        except Exception:
            return {"provider": getattr(self.service, "provider_name", None),
                    "model": getattr(self.service, "model_name", None)}

    def close(self) -> None:
        try:
            self.service.close()
        except Exception:
            pass
