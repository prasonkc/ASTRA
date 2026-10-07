"""
Playwright Browser Tool for ASTRA - provides visible browser automation using Playwright.
Supports opening visible browser windows, navigation, interaction, and full JS execution.
"""
import asyncio
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from utils.colors import warning, error


class PlaywrightBrowserTool:
    def __init__(self, 
                 headless: bool = False,  # Default to visible browser
                 timeout: int = 30000,
                 viewport: Dict[str, int] = None,
                 user_agent: str = "ASTRA/1.0 (Academic Assistant; Playwright)"):
        """
        Initialize Playwright browser tool.
        
        Args:
            headless: Run browser in headless mode (False = visible)
            timeout: Default timeout in milliseconds
            viewport: Browser viewport size {"width": 1280, "height": 720}
            user_agent: User agent string
        """
        self.headless = headless
        self.timeout = timeout
        self.viewport = viewport or {"width": 1280, "height": 720}
        self.user_agent = user_agent
        
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._initialized = False
        
        self.functions = {
            "playwright_open": self.open,
            "playwright_close": self.close_browser,
            "playwright_navigate": self.navigate,
            "playwright_click": self.click,
            "playwright_type": self.type_text,
            "playwright_fill": self.fill,
            "playwright_select": self.select_option,
            "playwright_wait": self.wait_for_selector,
            "playwright_extract": self.extract,
            "playwright_screenshot": self.screenshot,
            "playwright_pdf": self.save_pdf,
            "playwright_eval": self.evaluate,
            "playwright_scroll": self.scroll,
            "playwright_hover": self.hover,
            "playwright_press": self.press_key,
            "playwright_get_text": self.get_text,
            "playwright_get_html": self.get_html,
            "playwright_get_url": self.get_url,
            "playwright_get_title": self.get_title,
            "playwright_go_back": self.go_back,
            "playwright_go_forward": self.go_forward,
            "playwright_reload": self.reload,
            "playwright_new_tab": self.new_tab,
            "playwright_switch_tab": self.switch_tab,
            "playwright_close_tab": self.close_tab,
        }

    async def _ensure_initialized(self):
        """Lazy initialization of Playwright browser."""
        if self._initialized:
            return
        
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ]
            )
            self._context = await self._browser.new_context(
                viewport=self.viewport,
                user_agent=self.user_agent,
                ignore_https_errors=True,
            )
            self._page = await self._context.new_page()
            self._page.set_default_timeout(self.timeout)
            self._initialized = True
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Playwright: {e}")

    def _run_async(self, coro):
        """Run async coroutine in sync context."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    # ------------------------------------------------------------ Operations

    def open(self, url: str = None) -> Dict[str, Any]:
        """Open a visible browser window and optionally navigate to URL."""
        try:
            self._run_async(self._ensure_initialized())
            
            if url:
                result = self._run_async(self._page.goto(url, wait_until="networkidle"))
                return {
                    "success": True,
                    "url": self._page.url,
                    "title": self._run_async(self._page.title()),
                }
            else:
                return {
                    "success": True,
                    "message": "Browser opened. Use playwright_navigate to go to a URL.",
                    "url": self._page.url if self._page else "about:blank"
                }
        except Exception as e:
            return {"success": False, "error": f"Open failed: {e}"}

    def close_browser(self) -> Dict[str, Any]:
        """Close the browser and cleanup."""
        try:
            if self._page:
                self._run_async(self._page.close())
            if self._context:
                self._run_async(self._context.close())
            if self._browser:
                self._run_async(self._browser.close())
            if self._playwright:
                self._run_async(self._playwright.stop())
            self._initialized = False
            return {"success": True, "message": "Browser closed"}
        except Exception as e:
            return {"success": False, "error": f"Close failed: {e}"}

    def navigate(self, url: str, wait_until: str = "networkidle") -> Dict[str, Any]:
        """Navigate to a URL."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.goto(url, wait_until=wait_until))
            return {
                "success": True,
                "url": self._page.url,
                "title": self._run_async(self._page.title()),
            }
        except Exception as e:
            return {"success": False, "error": f"Navigation failed: {e}"}

    def click(self, selector: str, button: str = "left", count: int = 1) -> Dict[str, Any]:
        """Click an element."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.click(selector, button=button, click_count=count))
            return {"success": True, "message": f"Clicked {selector}"}
        except Exception as e:
            return {"success": False, "error": f"Click failed: {e}"}

    def type_text(self, selector: str, text: str, delay: int = 0) -> Dict[str, Any]:
        """Type text into an element."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.type(selector, text, delay=delay))
            return {"success": True, "message": f"Typed into {selector}"}
        except Exception as e:
            return {"success": False, "error": f"Type failed: {e}"}

    def fill(self, selector: str, value: str) -> Dict[str, Any]:
        """Fill an input field."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.fill(selector, value))
            return {"success": True, "message": f"Filled {selector}"}
        except Exception as e:
            return {"success": False, "error": f"Fill failed: {e}"}

    def select_option(self, selector: str, value: str) -> Dict[str, Any]:
        """Select an option in a dropdown."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.select_option(selector, value=value))
            return {"success": True, "message": f"Selected {value} in {selector}"}
        except Exception as e:
            return {"success": False, "error": f"Select failed: {e}"}

    def wait_for_selector(self, selector: str, state: str = "visible", timeout: int = None) -> Dict[str, Any]:
        """Wait for an element to appear."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.wait_for_selector(selector, state=state, timeout=timeout or self.timeout))
            return {"success": True, "message": f"Element {selector} is {state}"}
        except Exception as e:
            return {"success": False, "error": f"Wait failed: {e}"}

    def extract(self, selector: str, attribute: str = None) -> Dict[str, Any]:
        """Extract text or attribute from elements."""
        try:
            self._run_async(self._ensure_initialized())
            elements = self._run_async(self._page.query_selector_all(selector))
            values = []
            for el in elements:
                if attribute:
                    val = self._run_async(el.get_attribute(attribute))
                else:
                    val = self._run_async(el.text_content())
                values.append(val)
            return {"success": True, "count": len(values), "values": values}
        except Exception as e:
            return {"success": False, "error": f"Extract failed: {e}"}

    def screenshot(self, path: str = "screenshot.png", full_page: bool = False) -> Dict[str, Any]:
        """Take a screenshot."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.screenshot(path=path, full_page=full_page))
            return {"success": True, "path": path, "message": f"Screenshot saved to {path}"}
        except Exception as e:
            return {"success": False, "error": f"Screenshot failed: {e}"}

    def save_pdf(self, path: str = "page.pdf") -> Dict[str, Any]:
        """Save page as PDF."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.pdf(path=path))
            return {"success": True, "path": path, "message": f"PDF saved to {path}"}
        except Exception as e:
            return {"success": False, "error": f"PDF failed: {e}"}

    def evaluate(self, script: str) -> Dict[str, Any]:
        """Execute JavaScript in the page context."""
        try:
            self._run_async(self._ensure_initialized())
            result = self._run_async(self._page.evaluate(script))
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": f"Eval failed: {e}"}

    def scroll(self, x: int = 0, y: int = 0) -> Dict[str, Any]:
        """Scroll the page."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.evaluate(f"window.scrollBy({x}, {y})"))
            return {"success": True, "message": f"Scrolled by ({x}, {y})"}
        except Exception as e:
            return {"success": False, "error": f"Scroll failed: {e}"}

    def hover(self, selector: str) -> Dict[str, Any]:
        """Hover over an element."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.hover(selector))
            return {"success": True, "message": f"Hovered {selector}"}
        except Exception as e:
            return {"success": False, "error": f"Hover failed: {e}"}

    def press_key(self, key: str) -> Dict[str, Any]:
        """Press a keyboard key."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.keyboard.press(key))
            return {"success": True, "message": f"Pressed {key}"}
        except Exception as e:
            return {"success": False, "error": f"Key press failed: {e}"}

    def get_text(self, selector: str = "body") -> Dict[str, Any]:
        """Get visible text content."""
        try:
            self._run_async(self._ensure_initialized())
            text = self._run_async(self._page.locator(selector).inner_text())
            return {"success": True, "text": text}
        except Exception as e:
            return {"success": False, "error": f"Get text failed: {e}"}

    def get_html(self, selector: str = "html") -> Dict[str, Any]:
        """Get HTML content."""
        try:
            self._run_async(self._ensure_initialized())
            html = self._run_async(self._page.locator(selector).inner_html())
            return {"success": True, "html": html}
        except Exception as e:
            return {"success": False, "error": f"Get HTML failed: {e}"}

    def get_url(self) -> Dict[str, Any]:
        """Get current URL."""
        try:
            self._run_async(self._ensure_initialized())
            return {"success": True, "url": self._page.url}
        except Exception as e:
            return {"success": False, "error": f"Get URL failed: {e}"}

    def get_title(self) -> Dict[str, Any]:
        """Get page title."""
        try:
            self._run_async(self._ensure_initialized())
            title = self._run_async(self._page.title())
            return {"success": True, "title": title}
        except Exception as e:
            return {"success": False, "error": f"Get title failed: {e}"}

    def go_back(self) -> Dict[str, Any]:
        """Navigate back in history."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.go_back())
            return {"success": True, "url": self._page.url}
        except Exception as e:
            return {"success": False, "error": f"Go back failed: {e}"}

    def go_forward(self) -> Dict[str, Any]:
        """Navigate forward in history."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.go_forward())
            return {"success": True, "url": self._page.url}
        except Exception as e:
            return {"success": False, "error": f"Go forward failed: {e}"}

    def reload(self) -> Dict[str, Any]:
        """Reload the current page."""
        try:
            self._run_async(self._ensure_initialized())
            self._run_async(self._page.reload(wait_until="networkidle"))
            return {"success": True, "url": self._page.url}
        except Exception as e:
            return {"success": False, "error": f"Reload failed: {e}"}

    def new_tab(self, url: str = None) -> Dict[str, Any]:
        """Open a new tab."""
        try:
            self._run_async(self._ensure_initialized())
            new_page = self._run_async(self._context.new_page())
            self._page = new_page
            if url:
                self._run_async(self._page.goto(url, wait_until="networkidle"))
            return {"success": True, "url": self._page.url}
        except Exception as e:
            return {"success": False, "error": f"New tab failed: {e}"}

    def switch_tab(self, index: int) -> Dict[str, Any]:
        """Switch to a tab by index."""
        try:
            self._run_async(self._ensure_initialized())
            pages = self._context.pages
            if 0 <= index < len(pages):
                self._page = pages[index]
                self._run_async(self._page.bring_to_front())
                return {"success": True, "url": self._page.url}
            return {"success": False, "error": f"Tab index {index} out of range"}
        except Exception as e:
            return {"success": False, "error": f"Switch tab failed: {e}"}

    def close_tab(self, index: int = None) -> Dict[str, Any]:
        """Close a tab."""
        try:
            self._run_async(self._ensure_initialized())
            pages = self._context.pages
            if index is None:
                idx = pages.index(self._page)
            else:
                idx = index
            if 0 <= idx < len(pages):
                page_to_close = pages[idx]
                self._run_async(page_to_close.close())
                if page_to_close == self._page and pages:
                    self._page = pages[0] if idx == 0 else pages[idx - 1]
                return {"success": True, "message": f"Closed tab {idx}"}
            return {"success": False, "error": "Invalid tab index"}
        except Exception as e:
            return {"success": False, "error": f"Close tab failed: {e}"}

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for function calling."""
        def prop(t: str, d: str, **extra):
            p = {"type": t, "description": d}
            p.update(extra)
            return p

        return [
            self._schema("playwright_open", "Open a VISIBLE browser window (Chromium) and optionally navigate to URL. Use this when you need to SEE the browser, interact with JavaScript, take screenshots, or automate a real browser.",
                         {"url": prop("string", "URL to navigate to (optional)")}, []),
            self._schema("playwright_close", "Close the Playwright browser completely", {}, []),
            self._schema("playwright_navigate", "Navigate to a URL in the Playwright browser",
                         {"url": prop("string", "URL to navigate to"),
                          "wait_until": prop("string", "Wait condition", enum=["load", "domcontentloaded", "networkidle"], default="networkidle")},
                         ["url"]),
            self._schema("playwright_click", "Click an element in the Playwright browser",
                         {"selector": prop("string", "CSS selector"),
                          "button": prop("string", "Mouse button", enum=["left", "right", "middle"], default="left"),
                          "count": prop("integer", "Click count", default=1)},
                         ["selector"]),
            self._schema("playwright_type", "Type text into an element in the Playwright browser",
                         {"selector": prop("string", "CSS selector"),
                          "text": prop("string", "Text to type"),
                          "delay": prop("integer", "Delay between keystrokes (ms)", default=0)},
                         ["selector", "text"]),
            self._schema("playwright_fill", "Fill an input field in the Playwright browser",
                         {"selector": prop("string", "CSS selector"),
                          "value": prop("string", "Value to fill")},
                         ["selector", "value"]),
            self._schema("playwright_select", "Select an option in a dropdown in the Playwright browser",
                         {"selector": prop("string", "CSS selector"),
                          "value": prop("string", "Value to select")},
                         ["selector", "value"]),
            self._schema("playwright_wait", "Wait for an element to appear in the Playwright browser",
                         {"selector": prop("string", "CSS selector"),
                          "state": prop("string", "Wait state", enum=["attached", "detached", "visible", "hidden"], default="visible"),
                          "timeout": prop("integer", "Timeout in milliseconds")},
                         ["selector"]),
            self._schema("playwright_extract", "Extract text or attribute from elements in the Playwright browser",
                         {"selector": prop("string", "CSS selector"),
                          "attribute": prop("string", "Attribute to extract (optional, default: text)")},
                         ["selector"]),
            self._schema("playwright_screenshot", "Take a screenshot of the Playwright browser window",
                         {"path": prop("string", "Save path", default="screenshot.png"),
                          "full_page": prop("boolean", "Capture full page", default=False)},
                         []),
            self._schema("playwright_pdf", "Save page as PDF from the Playwright browser",
                         {"path": prop("string", "Save path", default="page.pdf")},
                         []),
            self._schema("playwright_eval", "Execute JavaScript in the Playwright browser page context",
                         {"script": prop("string", "JavaScript code to execute")},
                         ["script"]),
            self._schema("playwright_scroll", "Scroll the page in the Playwright browser",
                         {"x": prop("integer", "Horizontal scroll", default=0),
                          "y": prop("integer", "Vertical scroll", default=0)},
                         []),
            self._schema("playwright_hover", "Hover over an element in the Playwright browser",
                         {"selector": prop("string", "CSS selector")},
                         ["selector"]),
            self._schema("playwright_press", "Press a keyboard key in the Playwright browser",
                         {"key": prop("string", "Key to press (e.g., Enter, Tab, Escape, ArrowDown)")},
                         ["key"]),
            self._schema("playwright_get_text", "Get visible text content from the Playwright browser",
                         {"selector": prop("string", "CSS selector", default="body")},
                         []),
            self._schema("playwright_get_html", "Get HTML content from the Playwright browser",
                         {"selector": prop("string", "CSS selector", default="html")},
                         []),
            self._schema("playwright_get_url", "Get current URL from the Playwright browser", {}, []),
            self._schema("playwright_get_title", "Get page title from the Playwright browser", {}, []),
            self._schema("playwright_go_back", "Navigate back in history in the Playwright browser", {}, []),
            self._schema("playwright_go_forward", "Navigate forward in history in the Playwright browser", {}, []),
            self._schema("playwright_reload", "Reload the current page in the Playwright browser", {}, []),
            self._schema("playwright_new_tab", "Open a new tab in the Playwright browser",
                         {"url": prop("string", "URL to open in new tab (optional)")},
                         []),
            self._schema("playwright_switch_tab", "Switch to a tab by index in the Playwright browser",
                         {"index": prop("integer", "Tab index (0-based)")},
                         ["index"]),
            self._schema("playwright_close_tab", "Close a tab in the Playwright browser",
                         {"index": prop("integer", "Tab index (optional, default: current)")},
                         []),
        ]

    @staticmethod
    def _schema(name: str, description: str, properties: Dict[str, Any],
                required: List[str]) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }