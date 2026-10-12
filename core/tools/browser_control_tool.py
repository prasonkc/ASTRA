"""The ``ext_*`` browser-automation tools.

These tools drive the **user's own Firefox browser** through the ASTRA browser
extension (``extension/firefox``). They are the "hands" of the agent: instead of
ASTRA's headless browsers, the user watches every action happen in the tab they
have open.

Every call is a round-trip through :mod:`browser_bridge`:

    tool ─enqueue─▶ queue ──GET /api/browser/commands──▶ extension (Firefox)
      ▲                                                     │ execute
      └────────────── tool returns ──POST result◀───────────┘

The extension must be installed, switched on ("Integrate ASTRA with webpages")
and a page open in the active tab; otherwise calls time out with an explanatory
message.
"""
from __future__ import annotations

from typing import Any, Dict, List

from browser_bridge import enqueue_command

# How long a single browser action may take before we give up.
COMMAND_TIMEOUT = 60.0


class BrowserControlTool:
    """Automates the user's Firefox browser via the ASTRA extension."""

    def __init__(self):
        self.functions = {
            "ext_open_tab": self.open_tab,
            "ext_list_tabs": self.list_tabs,
            "ext_switch_tab": self.switch_tab,
            "ext_close_tab": self.close_tab,
            "ext_navigate": self.navigate,
            "ext_search": self.search,
            "ext_click": self.click,
            "ext_type": self.type_text,
            "ext_press_key": self.press_key,
            "ext_scroll": self.scroll,
            "ext_eval_js": self.eval_js,
            "ext_read_page": self.read_page,
        }

    # ---- proxying helpers -------------------------------------------------
    def _run(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return enqueue_command(name, arguments, timeout=COMMAND_TIMEOUT)

    # ---- tab management ---------------------------------------------------
    def open_tab(self, url: str = "") -> Dict[str, Any]:
        """Open a new tab in the user's browser, optionally at ``url``."""
        return self._run("ext_open_tab", {"url": url or ""})

    def list_tabs(self) -> Dict[str, Any]:
        """List the user's open tabs (index, title, url, active flag)."""
        return self._run("ext_list_tabs", {})

    def switch_tab(self, target: Any = None) -> Dict[str, Any]:
        """Switch to a tab by zero-based index or by URL/title substring."""
        return self._run("ext_switch_tab", {"target": target})

    def close_tab(self) -> Dict[str, Any]:
        """Close the active tab."""
        return self._run("ext_close_tab", {})

    # ---- navigation -------------------------------------------------------
    def navigate(self, url: str) -> Dict[str, Any]:
        """Navigate the active tab to ``url`` and wait for the page to load."""
        return self._run("ext_navigate", {"url": url})

    def search(self, query: str, engine: str = "google") -> Dict[str, Any]:
        """Search ``query`` on ``engine`` (google|duckduckgo|bing) in the active
        tab and return the resulting page's visible text."""
        return self._run("ext_search", {"query": query, "engine": engine or "google"})

    # ---- page interaction ------------------------------------------------
    def click(self, selector: str = "", text: str = "") -> Dict[str, Any]:
        """Click an element in the active tab by CSS ``selector`` or by visible
        ``text``."""
        return self._run("ext_click", {"selector": selector or "", "text": text or ""})

    def type_text(self, text: str, selector: str = "") -> Dict[str, Any]:
        """Type ``text`` into the focused field, or the field matching
        ``selector``, in the active tab."""
        return self._run("ext_type", {"text": text, "selector": selector or ""})

    def press_key(self, key: str) -> Dict[str, Any]:
        """Press a keyboard key in the active tab (e.g. Enter, Tab, Escape, ArrowDown)."""
        return self._run("ext_press_key", {"key": key or ""})

    def scroll(self, direction: str = "down", amount: int = 600) -> Dict[str, Any]:
        """Scroll the active tab ("down"|"up"|"top"|"bottom")."""
        return self._run("ext_scroll", {"direction": direction or "down", "amount": int(amount or 0)})

    def eval_js(self, expression: str) -> Dict[str, Any]:
        """Evaluate a JavaScript expression in the active tab and return the value.

        Runs in the extension's content-script scope: DOM access works, but page
        scripts' private variables are not visible.
        """
        return self._run("ext_eval_js", {"expression": expression or ""})

    def read_page(self, part: str = "text") -> Dict[str, Any]:
        """Read the active tab. ``part``: text|html|url|title|selection|all."""
        return self._run("ext_read_page", {"part": part or "text"})

    # ---- schemas ----------------------------------------------------------
    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            self._schema(
                "ext_open_tab",
                "Open a new tab in the user's Firefox browser, optionally at a URL. "
                "The new tab becomes active. Use this (not ext_navigate) when the user "
                "wants a fresh tab.",
                {"url": ("string", "URL to open (optional)", False)},
            ),
            self._schema(
                "ext_list_tabs",
                "List the user's open tabs with their index, title and URL so you can "
                "decide which tab to act on.",
                {},
            ),
            self._schema(
                "ext_switch_tab",
                "Make a specific tab active. Pass the zero-based tab index, or a "
                "substring of its URL or title.",
                {"target": ("string", "Tab index as a number, or URL/title substring", True)},
            ),
            self._schema(
                "ext_close_tab",
                "Close the active tab in the user's browser.",
                {},
            ),
            self._schema(
                "ext_navigate",
                "Navigate the active tab to a URL and wait for the page to load.",
                {"url": ("string", "Full URL (https://…) to navigate to", True)},
            ),
            self._schema(
                "ext_search",
                "Run a web search in the user's browser and return the results page's "
                "visible text. Engines: google (default), duckduckgo, bing.",
                {
                    "query": ("string", "Search query", True),
                    "engine": ("string", "Search engine: google, duckduckgo or bing", False),
                },
            ),
            self._schema(
                "ext_click",
                "Click an element in the active tab, by CSS selector or by its visible "
                "text (exact or substring).",
                {
                    "selector": ("string", "CSS selector of the element to click", False),
                    "text": ("string", "Visible text of the element to click", False),
                },
            ),
            self._schema(
                "ext_type",
                "Type text into a field in the active tab. Fills the focused field by "
                "default, or the field matching the CSS selector.",
                {
                    "text": ("string", "Text to type", True),
                    "selector": ("string", "CSS selector of the input (optional)", False),
                },
            ),
            self._schema(
                "ext_press_key",
                "Press a keyboard key in the active tab. Useful after typing, e.g. Enter "
                "to submit a search. Keys: Enter, Tab, Escape, ArrowUp/Down, Backspace…",
                {"key": ("string", "Key name to press", True)},
            ),
            self._schema(
                "ext_scroll",
                "Scroll the active tab: 'down', 'up', 'top' or 'bottom'.",
                {
                    "direction": ("string", "down (default), up, top or bottom", False),
                    "amount": ("integer", "Pixels to scroll for down/up (default 600)", False),
                },
            ),
            self._schema(
                "ext_eval_js",
                "Evaluate a JavaScript expression in the active tab and return its value. "
                "DOM manipulations work; page-private variables are not accessible.",
                {"expression": ("string", "JavaScript expression that evaluates to a value", True)},
            ),
            self._schema(
                "ext_read_page",
                "Read the current state of the active tab: visible text (default), raw "
                "HTML, URL, title, or the user's text selection. Best used after "
                "ext_search/ext_navigate to inspect the result.",
                {
                    "part": ("string", "text (default), html, url, title, selection or all", False),
                },
            ),
        ]

    @staticmethod
    def _schema(name: str, description: str, properties: Dict[str, tuple]) -> Dict[str, Any]:
        props: Dict[str, Any] = {}
        required: List[str] = []
        for prop_name, (ptype, pdesc, is_required) in properties.items():
            props[prop_name] = {"type": ptype, "description": pdesc}
            if is_required:
                required.append(prop_name)
        if not required:
            required = []
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }