"""The ``browser_context`` tool.

Exposes the web page the user is currently viewing in their Firefox browser to
the ASTRA agent. The data is pushed to astra-web by the ASTRA browser extension
(see ``extension/firefox``) and parked in :mod:`browser_bridge`; this tool simply
reads the latest snapshot so the model can explain the page or make decisions
based on it.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from browser_bridge import get_context

# Keep tool results (which get written into the conversation history) bounded.
MAX_HTML_CHARS = 50_000
MAX_TEXT_CHARS = 20_000

_FIELDS = ["text", "html", "selection", "url", "title", "mouse", "all"]


class BrowserContextTool:
    """Reads the latest page snapshot sent by the ASTRA browser extension."""

    def __init__(self):
        self.functions = {
            "browser_context": self.context,
        }

    def context(self, field: str = "all") -> Dict[str, Any]:
        """Return information about the page the user is currently viewing."""
        field = (field or "all").strip().lower()
        if field not in _FIELDS:
            field = "all"

        stored = get_context()
        if not stored:
            return {
                "available": False,
                "message": (
                    "No browser context available. The user must have the ASTRA "
                    "browser extension installed and click 'Integrate ASTRA with "
                    "webpages' on the page they want help with."
                ),
            }

        result: Dict[str, Any] = {
            "available": True,
            "url": stored.get("url"),
            "title": stored.get("title"),
            "age_seconds": round(time.time() - stored.get("received_at", time.time()), 1),
        }

        want = _FIELDS[:-1] if field == "all" else [field]

        if "selection" in want:
            result["selection"] = stored.get("selection") or ""

        if "mouse" in want:
            result["mouse"] = stored.get("mouse")

        if "text" in want:
            text = stored.get("text") or ""
            result["text"] = _clip(text, MAX_TEXT_CHARS)
            result["text_length"] = len(text)

        if "html" in want:
            html = stored.get("html") or ""
            result["html"] = _clip(html, MAX_HTML_CHARS)
            result["html_length"] = len(html)

        return result

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "browser_context",
                    "description": (
                        "Read the web page the user is currently viewing in their "
                        "Firefox browser (URL, title, page text, HTML, selected text, "
                        "mouse position). Use this to explain, summarise or answer "
                        "questions about the page on screen, or to base a decision on "
                        "what the user is looking at. Requires the user to have the "
                        "ASTRA browser extension active on that page."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "field": {
                                "type": "string",
                                "enum": _FIELDS,
                                "description": (
                                    "Which part of the page to read. 'text' is the "
                                    "visible text (best for explaining a page), "
                                    "'html' is the raw markup, 'selection' is the "
                                    "text the user highlighted, 'mouse' is the "
                                    "pointer position, 'all' returns everything."
                                ),
                            }
                        },
                        "required": [],
                    },
                },
            }
        ]


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… (truncated)"
