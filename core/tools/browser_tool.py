"""
Browser tool for ASTRA - provides interactive web browsing capabilities.
Supports navigation, link following, form filling, content extraction, and search.
"""
import re
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

from utils.colors import warning, error


class BrowserTool:
    def __init__(self, 
                 timeout: int = 30,
                 user_agent: str = "ASTRA/1.0 (Academic Assistant)",
                 max_content_length: int = 500_000,
                 history_limit: int = 50):
        """
        Initialize browser tool.
        
        Args:
            timeout: Request timeout in seconds
            user_agent: User agent string
            max_content_length: Max characters of page content kept per page
            history_limit: Maximum navigation history entries kept
        """
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_content_length = max_content_length
        self.history_limit = history_limit

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

        # Navigation state
        self.current_url: Optional[str] = None
        self.current_title: Optional[str] = None
        self.current_html: str = ""
        self.soup: Optional[BeautifulSoup] = None
        self.back_stack: List[str] = []
        self.pending_fields: Dict[str, Any] = {}

        self.functions = {
            "browser_open": self.open,
            "browser_back": self.back,
            "browser_text": self.text,
            "browser_links": self.links,
            "browser_click": self.click,
            "browser_extract": self.extract,
            "browser_forms": self.forms,
            "browser_fill": self.fill,
            "browser_submit": self.submit,
            "browser_search": self.search,
            "browser_status": self.status,
        }

    def _normalize_url(self, url: str) -> str:
        """Normalize URL by adding scheme if missing."""
        url = (url or "").strip()
        if not urlparse(url).scheme:
            url = "https://" + url
        return url

    def _load(self, url: str, method: str = "GET",
              data: Optional[Dict[str, Any]] = None,
              push_history: bool = True) -> Dict[str, Any]:
        """Fetch a URL, update state, parse page."""
        url = self._normalize_url(url)
        try:
            if method.upper() == "POST":
                response = self.session.post(url, data=data, timeout=self.timeout)
            else:
                if data:
                    response = self.session.get(url, params=data, timeout=self.timeout)
                else:
                    response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()

            # Remember where we came from (for back navigation)
            if push_history and self.current_url and self.current_url != url:
                self.back_stack.append(self.current_url)
                if len(self.back_stack) > self.history_limit:
                    self.back_stack = self.back_stack[-self.history_limit:]

            html = response.text[: self.max_content_length * 3]
            self.current_url = response.url
            self.current_html = html
            self.soup = BeautifulSoup(html, "html.parser")
            self.current_title = self.soup.title.get_text(strip=True) if self.soup.title else None
            self.pending_fields = {}

            # strip noisy elements for text extraction later
            return {
                "success": True,
                "url": response.url,
                "status_code": response.status_code,
                "title": self.current_title,
                "content_type": response.headers.get("Content-Type", ""),
            }
        except requests.exceptions.Timeout:
            return {"success": False, "error": f"Request timed out after {self.timeout}s", "url": url}
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            return {"success": False, "error": f"HTTP {status} error", "url": url}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"Request failed: {e}", "url": url}
        except Exception as e:
            return {"success": False, "error": f"Navigation error: {e}", "url": url}

    def _require_page(self) -> Optional[str]:
        """Check if a page is loaded, return error message if not."""
        if self.soup is None or not self.current_url:
            return "No page loaded. Use browser_open first."
        return None

    def _clean_soup(self) -> BeautifulSoup:
        """Return a copy of the page soup with scripts/styles removed."""
        soup = BeautifulSoup(self.current_html, "html.parser")
        for elem in soup(["script", "style", "noscript", "template"]):
            elem.decompose()
        return soup

    # ------------------------------------------------------------ operations

    def open(self, url: str) -> Dict[str, Any]:
        """Navigate to a URL."""
        if not url or not url.strip():
            return {"success": False, "error": "URL cannot be empty"}
        result = self._load(url)
        if not result["success"]:
            return result

        links = len(self.soup.find_all("a", href=True)) if self.soup else 0
        preview = self.text(max_length=400).get("text", "")
        result.update({
            "links_found": links,
            "preview": preview,
        })
        return result

    def back(self) -> Dict[str, Any]:
        """Go back to the previous page in navigation history."""
        if not self.back_stack:
            return {"success": False, "error": "No previous page in history"}
        url = self.back_stack.pop()
        return self._load(url, push_history=False)

    def status(self) -> Dict[str, Any]:
        """Get current browsing state."""
        return {
            "success": True,
            "url": self.current_url,
            "title": self.current_title,
            "history_depth": len(self.back_stack),
            "page_loaded": self.soup is not None,
        }

    def text(self, max_length: int = 5000) -> Dict[str, Any]:
        """Extract the visible text of the current page."""
        require = self._require_page()
        if require:
            return {"success": False, "error": require}
        try:
            soup = self._clean_soup()
            for elem in soup(["nav", "header", "footer", "aside"]):
                elem.decompose()
            content = soup.get_text(separator="\n", strip=True)
            # collapse blank lines
            content = re.sub(r"\n{3,}", "\n\n", content)
            return {
                "success": True,
                "url": self.current_url,
                "title": self.current_title,
                "text": content[:max_length],
                "truncated": len(content) > max_length,
                "total_length": len(content),
            }
        except Exception as e:
            return {"success": False, "error": f"Text extraction failed: {e}"}

    def links(self, filter_text: Optional[str] = None,
              limit: int = 50) -> Dict[str, Any]:
        """List links on the current page (optionally filtered by text)."""
        require = self._require_page()
        if require:
            return {"success": False, "error": require}

        results = []
        seen = set()
        for a in self.soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            absolute = urljoin(self.current_url, href)
            label = a.get_text(" ", strip=True)
            if filter_text and filter_text.lower() not in label.lower() \
                    and filter_text.lower() not in absolute.lower():
                continue
            key = (label, absolute)
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "index": len(results),
                "text": label[:200],
                "url": absolute,
            })
            if len(results) >= limit:
                break

        return {"success": True, "url": self.current_url,
                "count": len(results), "links": results}

    def click(self, target: str) -> Dict[str, Any]:
        """
        Follow a link on the current page by index (from browser_links),
        link text, or URL substring.
        """
        require = self._require_page()
        if require:
            return {"success": False, "error": require}

        target = (target or "").strip()
        if not target:
            return {"success": False, "error": "Target cannot be empty"}

        chosen_url = None
        # numeric index?
        if target.isdigit():
            links = self.links(limit=1000).get("links", [])
            idx = int(target)
            matches = [l for l in links if l["index"] == idx]
            if matches:
                chosen_url = matches[0]["url"]
        else:
            # exact-ish text match first
            for a in self.soup.find_all("a", href=True):
                label = a.get_text(" ", strip=True)
                if label and (label.lower() == target.lower() or target.lower() in label.lower()):
                    chosen_url = urljoin(self.current_url, a["href"].strip())
                    break
            if chosen_url is None:
                # url substring match
                for a in self.soup.find_all("a", href=True):
                    absolute = urljoin(self.current_url, a["href"].strip())
                    if target.lower() in absolute.lower():
                        chosen_url = absolute
                        break

        if chosen_url is None:
            return {"success": False, "error": f"No link found matching '{target}'"}

        return self._load(chosen_url)

    def extract(self, selector: str, limit: int = 50,
                attribute: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract data from the current page using a CSS selector.

        Args:
            selector: CSS selector (e.g. "h2 a", "div.content p")
            limit: Maximum matches
            attribute: Return this attribute instead of text (e.g. "href", "src")
        """
        require = self._require_page()
        if require:
            return {"success": False, "error": require}
        try:
            elements = self.soup.select(selector)
            values = []
            for elem in elements[:limit]:
                if attribute:
                    values.append(elem.get(attribute))
                else:
                    values.append(elem.get_text(" ", strip=True))
            return {"success": True, "url": self.current_url, "selector": selector,
                    "count": len(values), "values": values}
        except Exception as e:
            return {"success": False, "error": f"Extraction failed: {e}"}

    def forms(self) -> Dict[str, Any]:
        """Describe the forms and input fields on the current page."""
        require = self._require_page()
        if require:
            return {"success": False, "error": require}

        forms = []
        for form in self.soup.find_all("form"):
            fields = []
            for inp in form.find_all(["input", "textarea", "select"]):
                name = inp.get("name") or inp.get("id")
                if not name:
                    continue
                ftype = inp.name
                if inp.name == "input":
                    ftype = inp.get("type", "text")
                entry = {
                    "name": name,
                    "type": ftype,
                    "value": inp.get("value", ""),
                    "required": inp.has_attr("required"),
                }
                if inp.name == "select":
                    entry["options"] = [
                        opt.get("value", opt.get_text(strip=True))
                        for opt in inp.find_all("option")
                    ]
                fields.append(entry)

            forms.append({
                "index": len(forms),
                "action": urljoin(self.current_url, form.get("action") or self.current_url),
                "method": (form.get("method") or "get").upper(),
                "fields": fields,
            })

        return {"success": True, "url": self.current_url,
                "count": len(forms), "forms": forms}

    def fill(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        Store field values for the next form submission.
        fields: {"username": "alice", "q": "search term"}
        """
        require = self._require_page()
        if require:
            return {"success": False, "error": require}
        if not isinstance(fields, dict) or not fields:
            return {"success": False, "error": "fields must be a non-empty object"}
        self.pending_fields.update(fields)
        return {"success": True, "stored": len(self.pending_fields),
                "fields": list(self.pending_fields.keys())}

    def submit(self, form_index: int = 0,
               fields: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Submit a form on the current page (optionally providing field values).

        Args:
            form_index: Which form to submit (from browser_forms)
            fields: Field name -> value mapping
        """
        require = self._require_page()
        if require:
            return {"success": False, "error": require}

        form_list = self.soup.find_all("form")
        if not form_list:
            return {"success": False, "error": "No forms on this page"}
        if form_index < 0 or form_index >= len(form_list):
            return {"success": False, "error": f"form_index out of range (0-{len(form_list) - 1})"}

        form = form_list[form_index]
        action = urljoin(self.current_url, form.get("action") or self.current_url)
        method = (form.get("method") or "get").upper()

        values: Dict[str, Any] = {}
        # start with default values from the form
        for inp in form.find_all(["input", "textarea", "select"]):
            name = inp.get("name") or inp.get("id")
            if not name:
                continue
            if inp.name == "select":
                selected = inp.find("option", selected=True) or inp.find("option")
                values[name] = selected.get("value", selected.get_text(strip=True)) if selected else ""
            elif inp.name == "textarea":
                values[name] = inp.get_text()
            else:
                values[name] = inp.get("value", "") or ""
        # apply stored + provided values
        values.update(self.pending_fields or {})
        if fields:
            values.update(fields)

        # drop submit/button controls
        values = {k: v for k, v in values.items()
                  if not str(v).lower() in ("submit", "button")}

        self.pending_fields = {}
        return self._load(action, method=method, data=values)

    def search(self, query: str, max_results: int = 10) -> Dict[str, Any]:
        """Search the web (DuckDuckGo) and load the results page."""
        if not query or not query.strip():
            return {"success": False, "error": "Query cannot be empty"}
        try:
            response = self.session.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query.strip()},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"Search failed: {e}"}

        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        for result in soup.select("div.result"):
            title_elem = result.select_one("a.result__a")
            snippet_elem = result.select_one(".result__snippet")
            if not title_elem:
                continue
            link = title_elem.get("href", "")
            if link.startswith("//duckduckgo.com/l/?uddg="):
                qs = parse_qs(urlparse(link).query)
                if "uddg" in qs:
                    link = unquote(qs["uddg"][0])
            results.append({
                "title": title_elem.get_text(strip=True),
                "url": link,
                "snippet": snippet_elem.get_text(strip=True) if snippet_elem else "",
            })
            if len(results) >= max_results:
                break

        # load the results page in the browser so the user can click through
        self.back_stack.append(self.current_url) if self.current_url else None
        self.current_url = "https://duckduckgo.com/?q=" + requests.utils.quote(query)
        self.current_html = response.text
        self.soup = BeautifulSoup(response.text, "html.parser")
        self.current_title = f"Search: {query}"

        return {"success": True, "query": query,
                "count": len(results), "results": results}

    # --------------------------------------------------------------- schemas

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for function calling."""
        def prop(t: str, d: str, **extra):
            p = {"type": t, "description": d}
            p.update(extra)
            return p

        return [
            self._schema("browser_open", "Navigate the browser to a URL",
                         {"url": prop("string", "URL or domain to open")}, ["url"]),
            self._schema("browser_back", "Go back to the previous page", {}, []),
            self._schema("browser_status", "Show current URL, title and history depth", {}, []),
            self._schema("browser_text", "Get the visible text of the current page",
                         {"max_length": prop("integer", "Maximum characters to return", default=5000)},
                         []),
            self._schema("browser_links", "List links on the current page",
                         {"filter_text": prop("string", "Only links whose text or URL contains this"),
                          "limit": prop("integer", "Maximum links to return", default=50)},
                         []),
            self._schema("browser_click", "Follow a link on the current page by index, text, or URL",
                         {"target": prop("string", "Link index (e.g. '3'), link text, or URL fragment")},
                         ["target"]),
            self._schema("browser_extract", "Extract elements from the current page using a CSS selector",
                         {"selector": prop("string", "CSS selector, e.g. 'h2 a' or 'table td'"),
                          "limit": prop("integer", "Maximum matches", default=50),
                          "attribute": prop("string", "Return this attribute instead of text, e.g. 'href'")},
                         ["selector"]),
            self._schema("browser_forms", "List the forms and fields on the current page", {}, []),
            self._schema("browser_fill", "Store values for the next form submission",
                         {"fields": {"type": "object",
                                     "description": "Field name -> value mapping",
                                     "additionalProperties": True}},
                         ["fields"]),
            self._schema("browser_submit", "Submit a form on the current page",
                         {"form_index": prop("integer", "Form to submit (from browser_forms)", default=0),
                          "fields": {"type": "object",
                                     "description": "Field name -> value mapping",
                                     "additionalProperties": True}},
                         []),
            self._schema("browser_search", "Search the web with DuckDuckGo and load the results page",
                         {"query": prop("string", "Search query"),
                          "max_results": prop("integer", "Maximum results", default=10)},
                         ["query"]),
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