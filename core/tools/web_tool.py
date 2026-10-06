"""
Web tool for ASTRA - provides web access capabilities including search, 
content fetching, file downloading, and crawling.
"""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import os
import mimetypes
from pathlib import Path
from typing import Dict, Any, List, Optional
import time
import re
from utils.colors import warning, error


class WebTool:
    def __init__(self, 
                 timeout: int = 30,
                 max_redirects: int = 5,
                 user_agent: str = "ASTRA/1.0 (Academic Assistant)",
                 download_dir: str = "./downloads",
                 max_file_size: int = 50 * 1024 * 1024):  # 50MB default
        """
        Initialize web tool.
        
        Args:
            timeout: Request timeout in seconds
            max_redirects: Maximum redirects to follow
            user_agent: User agent string
            download_dir: Directory for downloaded files
            max_file_size: Maximum file size to download (bytes)
        """
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.user_agent = user_agent
        self.download_dir = Path(download_dir)
        self.max_file_size = max_file_size
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self.session.max_redirects = max_redirects
        
        # Create download directory
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        self.functions = {
            "web_search": self.search,
            "web_fetch": self.fetch,
            "web_download": self.download,
            "web_crawl": self.crawl,
            "web_find_files": self.find_files,
        }

    def _get_content_type(self, response: requests.Response) -> str:
        """Extract content type from response."""
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
        return content_type.lower()

    def _is_html(self, response: requests.Response) -> bool:
        """Check if response is HTML."""
        ct = self._get_content_type(response)
        return ct in ("text/html", "application/xhtml+xml")

    def _is_text(self, response: requests.Response) -> bool:
        """Check if response is text-based."""
        ct = self._get_content_type(response)
        return ct.startswith("text/") or ct in (
            "application/json", "application/xml", "application/javascript",
            "application/x-yaml", "application/yaml"
        )

    def search(self, query: str, max_results: int = 10, 
               search_engine: str = "duckduckgo") -> Dict[str, Any]:
        """
        Search the web for a query.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            search_engine: Search engine to use ("duckduckgo", "bing", "google")
        
        Returns:
            Dict with success, results list, query
        """
        if not query or not query.strip():
            return {"success": False, "error": "Query cannot be empty", "results": []}
        
        try:
            if search_engine == "duckduckgo":
                return self._search_duckduckgo(query.strip(), max_results)
            else:
                return {"success": False, "error": f"Search engine '{search_engine}' not implemented", "results": []}
        except Exception as e:
            return {"success": False, "error": f"Search failed: {str(e)}", "results": []}

    def _search_duckduckgo(self, query: str, max_results: int) -> Dict[str, Any]:
        """Search using DuckDuckGo HTML."""
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query}
        
        response = self.session.post(url, data=params, timeout=self.timeout)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        
        # DuckDuckGo result selectors
        for result in soup.select(".result__snippet, .result__url, .result__title"):
            # Parse result containers
            container = result.find_parent(class_="result")
            if not container:
                continue
            
            title_elem = container.select_one(".result__title a, .result__snippet a")
            snippet_elem = container.select_one(".result__snippet")
            url_elem = container.select_one(".result__url")
            
            if title_elem:
                title = title_elem.get_text(strip=True)
                link = title_elem.get("href", "")
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                display_url = url_elem.get_text(strip=True) if url_elem else ""
                
                # Clean up DuckDuckGo redirect URLs
                if link.startswith("//duckduckgo.com/l/?uddg="):
                    parsed = urlparse(link)
                    qs = parse_qs(parsed.query)
                    if "uddg" in qs:
                        link = qs["uddg"][0]
                
                results.append({
                    "title": title,
                    "url": link,
                    "snippet": snippet,
                    "display_url": display_url
                })
                
                if len(results) >= max_results:
                    break
        
        return {
            "success": True,
            "query": query,
            "results": results,
            "count": len(results)
        }

    def fetch(self, url: str, max_length: int = 100000) -> Dict[str, Any]:
        """
        Fetch content from a URL.
        
        Args:
            url: URL to fetch
            max_length: Maximum content length to return
        
        Returns:
            Dict with success, content, content_type, url, metadata
        """
        if not url or not url.strip():
            return {"success": False, "error": "URL cannot be empty"}
        
        url = url.strip()
        
        # Add scheme if missing
        if not urlparse(url).scheme:
            url = "https://" + url
        
        try:
            response = self.session.get(url, timeout=self.timeout, stream=True)
            response.raise_for_status()
            
            content_type = self._get_content_type(response)
            content_length = int(response.headers.get("Content-Length", 0))
            
            # Check size limit
            if content_length > max_length and content_length > 0:
                return {
                    "success": False,
                    "error": f"Content too large: {content_length} bytes (max {max_length})",
                    "content_type": content_type,
                    "url": url
                }
            
            content = response.text[:max_length]
            
            metadata = {
                "status_code": response.status_code,
                "content_type": content_type,
                "content_length": content_length,
                "encoding": response.encoding,
                "headers": dict(response.headers)
            }
            
            # If HTML, also extract structured data
            if self._is_html(response):
                soup = BeautifulSoup(content, "html.parser")
                
                # Extract metadata
                metadata["title"] = soup.title.string if soup.title else None
                metadata["description"] = None
                meta_desc = soup.find("meta", attrs={"name": "description"}) or \
                           soup.find("meta", attrs={"property": "og:description"})
                if meta_desc:
                    metadata["description"] = meta_desc.get("content")
                
                # Extract main text content
                # Remove script/style elements
                for elem in soup(["script", "style", "nav", "footer", "header"]):
                    elem.decompose()
                
                text = soup.get_text(separator="\n", strip=True)
                metadata["text_content"] = text[:max_length]
                
                # Extract links
                links = []
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    full_url = urljoin(url, href)
                    links.append({
                        "url": full_url,
                        "text": a.get_text(strip=True)[:200]
                    })
                metadata["links"] = links[:100]  # Limit links
            
            return {
                "success": True,
                "url": url,
                "content": content,
                "content_type": content_type,
                "metadata": metadata
            }
            
        except requests.exceptions.Timeout:
            return {"success": False, "error": f"Request timed out after {self.timeout}s", "url": url}
        except requests.exceptions.TooManyRedirects:
            return {"success": False, "error": "Too many redirects", "url": url}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"Request failed: {str(e)}", "url": url}
        except Exception as e:
            return {"success": False, "error": f"Fetch failed: {str(e)}", "url": url}

    def download(self, url: str, filename: Optional[str] = None,
                 overwrite: bool = False) -> Dict[str, Any]:
        """
        Download a file from a URL.
        
        Args:
            url: URL to download
            filename: Local filename (optional, auto-detected from URL/headers)
            overwrite: Overwrite existing file
        
        Returns:
            Dict with success, path, size, content_type, url
        """
        if not url or not url.strip():
            return {"success": False, "error": "URL cannot be empty"}
        
        url = url.strip()
        if not urlparse(url).scheme:
            url = "https://" + url
        
        try:
            # HEAD request to check headers first
            head = self.session.head(url, timeout=self.timeout, allow_redirects=True)
            head.raise_for_status()
            
            content_length = int(head.headers.get("Content-Length", 0))
            if content_length > self.max_file_size:
                return {
                    "success": False,
                    "error": f"File too large: {content_length} bytes (max {self.max_file_size})",
                    "url": url
                }
            
            # Determine filename
            if not filename:
                # Try Content-Disposition header
                cd = head.headers.get("Content-Disposition", "")
                if "filename=" in cd:
                    filename = cd.split("filename=")[1].strip('"\'')
                else:
                    # Extract from URL
                    parsed = urlparse(url)
                    filename = os.path.basename(parsed.path)
                    if not filename:
                        # Guess from content type
                        ext = mimetypes.guess_extension(head.headers.get("Content-Type", "").split(";")[0].strip())
                        filename = f"download{ext or '.bin'}"
            
            filepath = self.download_dir / filename
            
            if filepath.exists() and not overwrite:
                return {
                    "success": False,
                    "error": f"File already exists: {filepath}",
                    "path": str(filepath)
                }
            
            # Stream download
            response = self.session.get(url, timeout=self.timeout, stream=True)
            response.raise_for_status()
            
            downloaded = 0
            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        downloaded += len(chunk)
                        if downloaded > self.max_file_size:
                            f.close()
                            filepath.unlink(missing_ok=True)
                            return {
                                "success": False,
                                "error": f"File size exceeds limit during download",
                                "url": url
                            }
                        f.write(chunk)
            
            return {
                "success": True,
                "path": str(filepath),
                "filename": filename,
                "size": downloaded,
                "content_type": head.headers.get("Content-Type"),
                "url": url
            }
            
        except requests.exceptions.Timeout:
            return {"success": False, "error": f"Download timed out after {self.timeout}s", "url": url}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"Download failed: {str(e)}", "url": url}
        except Exception as e:
            return {"success": False, "error": f"Download error: {str(e)}", "url": url}

    def crawl(self, url: str, max_depth: int = 2, max_pages: int = 20,
              same_domain: bool = True, follow_patterns: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Crawl a website starting from a URL.
        
        Args:
            url: Starting URL
            max_depth: Maximum crawl depth
            max_pages: Maximum pages to crawl
            same_domain: Only follow links on same domain
            follow_patterns: Regex patterns for URLs to follow (optional)
        
        Returns:
            Dict with success, pages list, stats
        """
        if not url or not url.strip():
            return {"success": False, "error": "URL cannot be empty", "pages": []}
        
        url = url.strip()
        if not urlparse(url).scheme:
            url = "https://" + url
        
        base_domain = urlparse(url).netloc
        visited = set()
        to_visit = [(url, 0)]
        pages = []
        
        patterns = [re.compile(p) for p in follow_patterns] if follow_patterns else None
        
        try:
            while to_visit and len(pages) < max_pages:
                current_url, depth = to_visit.pop(0)
                
                if current_url in visited:
                    continue
                if depth > max_depth:
                    continue
                
                # Check domain restriction
                if same_domain:
                    current_domain = urlparse(current_url).netloc
                    if current_domain != base_domain:
                        continue
                
                # Check patterns
                if patterns:
                    if not any(p.search(current_url) for p in patterns):
                        continue
                
                visited.add(current_url)
                
                # Fetch page
                result = self.fetch(current_url)
                if not result["success"]:
                    pages.append({
                        "url": current_url,
                        "depth": depth,
                        "error": result["error"]
                    })
                    continue
                
                metadata = result.get("metadata", {})
                pages.append({
                    "url": current_url,
                    "depth": depth,
                    "title": metadata.get("title"),
                    "content_type": result.get("content_type"),
                    "text_preview": metadata.get("text_content", "")[:500],
                    "links_count": len(metadata.get("links", [])),
                    "status_code": metadata.get("status_code")
                })
                
                # Queue links for crawling
                if depth < max_depth:
                    for link in metadata.get("links", []):
                        link_url = link["url"]
                        if link_url not in visited:
                            to_visit.append((link_url, depth + 1))
                
                # Be polite
                time.sleep(0.5)
            
            return {
                "success": True,
                "start_url": url,
                "pages": pages,
                "stats": {
                    "pages_crawled": len(pages),
                    "max_depth_reached": max(p["depth"] for p in pages) if pages else 0,
                    "errors": sum(1 for p in pages if "error" in p)
                }
            }
            
        except Exception as e:
            return {"success": False, "error": f"Crawl failed: {str(e)}", "pages": pages}

    def find_files(self, url: str, extensions: Optional[List[str]] = None,
                   max_depth: int = 2, max_files: int = 50) -> Dict[str, Any]:
        """
        Find downloadable files on a website.
        
        Args:
            url: Starting URL to search
            extensions: File extensions to look for (e.g., [".pdf", ".doc", ".zip"])
            max_depth: Maximum crawl depth
            max_files: Maximum files to find
        
        Returns:
            Dict with success, files list
        """
        if not extensions:
            extensions = [".pdf", ".doc", ".docx", ".xls", ".xlsx", 
                         ".ppt", ".pptx", ".zip", ".tar", ".gz", 
                         ".txt", ".csv", ".json", ".xml"]
        
        ext_set = set(e.lower() if e.startswith(".") else "." + e.lower() for e in extensions)
        
        # Crawl with file-finding focus
        crawl_result = self.crawl(
            url, 
            max_depth=max_depth, 
            max_pages=max_files * 2,  # Crawl more pages to find files
            follow_patterns=[r".*\.(?:" + "|".join(e[1:] for e in ext_set) + r")$"]
        )
        
        if not crawl_result["success"]:
            return crawl_result
        
        files = []
        for page in crawl_result["pages"]:
            if "error" in page:
                continue
            
            # Re-fetch to get links (could optimize)
            fetch_result = self.fetch(page["url"])
            if not fetch_result["success"]:
                continue
            
            for link in fetch_result.get("metadata", {}).get("links", []):
                link_url = link["url"]
                parsed = urlparse(link_url)
                path = parsed.path.lower()
                
                # Check if link matches target extensions
                for ext in ext_set:
                    if path.endswith(ext):
                        files.append({
                            "url": link_url,
                            "extension": ext,
                            "source_page": page["url"],
                            "link_text": link.get("text", ""),
                            "filename": os.path.basename(parsed.path)
                        })
                        break
                
                if len(files) >= max_files:
                    break
            
            if len(files) >= max_files:
                break
        
        # Deduplicate by URL
        seen = set()
        unique_files = []
        for f in files:
            if f["url"] not in seen:
                seen.add(f["url"])
                unique_files.append(f)
        
        return {
            "success": True,
            "start_url": url,
            "extensions_searched": list(ext_set),
            "files": unique_files[:max_files],
            "count": len(unique_files)
        }

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for function calling."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for information using DuckDuckGo",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query"
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum results to return",
                                "default": 10
                            },
                            "search_engine": {
                                "type": "string",
                                "description": "Search engine to use",
                                "enum": ["duckduckgo"],
                                "default": "duckduckgo"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": "Fetch content from a URL (HTML, text, JSON, etc.)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "URL to fetch"
                            },
                            "max_length": {
                                "type": "integer",
                                "description": "Maximum content length",
                                "default": 100000
                            }
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_download",
                    "description": "Download a file from a URL to local storage",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "URL of file to download"
                            },
                            "filename": {
                                "type": "string",
                                "description": "Local filename (optional, auto-detected)"
                            },
                            "overwrite": {
                                "type": "boolean",
                                "description": "Overwrite existing file",
                                "default": False
                            }
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_crawl",
                    "description": "Crawl a website starting from a URL",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "Starting URL"
                            },
                            "max_depth": {
                                "type": "integer",
                                "description": "Maximum crawl depth",
                                "default": 2
                            },
                            "max_pages": {
                                "type": "integer",
                                "description": "Maximum pages to crawl",
                                "default": 20
                            },
                            "same_domain": {
                                "type": "boolean",
                                "description": "Only follow same domain links",
                                "default": True
                            },
                            "follow_patterns": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Regex patterns for URLs to follow"
                            }
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_find_files",
                    "description": "Find downloadable files on a website by extension",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "Starting URL to search"
                            },
                            "extensions": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "File extensions to find (e.g., ['.pdf', '.doc'])"
                            },
                            "max_depth": {
                                "type": "integer",
                                "description": "Maximum crawl depth",
                                "default": 2
                            },
                            "max_files": {
                                "type": "integer",
                                "description": "Maximum files to find",
                                "default": 50
                            }
                        },
                        "required": ["url"]
                    }
                }
            }
        ]