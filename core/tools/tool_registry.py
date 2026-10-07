"""
Tool Registry - manages tool discovery, categorization, and filtering.
Provides relevant tools to the model based on query context.
"""
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
import re

# Import available tool classes
from tools.memory_tool import MemoryTool
from tools.shell_tool import ShellTool
from tools.web_tool import WebTool
from tools.browser_tool import BrowserTool
from tools.playwright_tool import PlaywrightBrowserTool
from tools.file_reader_tool import FileReaderTool


@dataclass
class ToolCategory:
    """Represents a category of related tools."""
    name: str
    description: str
    keywords: List[str]
    tools: List[str] = field(default_factory=list)
    always_include: bool = False  # Always include these tools (e.g., memory)


class ToolRegistry:
    """
    Registry for all available tools with intelligent filtering.
    
    Categorizes tools and selects relevant subsets based on user queries
    to avoid overwhelming the model with too many tool schemas.
    """
    
    # Maximum tools to provide to model at once
    MAX_TOOLS = 20
    
    def __init__(self):
        self.tools: Dict[str, Any] = {}
        self.categories: Dict[str, ToolCategory] = {}
        self.tool_to_category: Dict[str, str] = {}
        self._register_all_tools()
    
    def _register_all_tools(self):
        """Register all available tool instances and their categories."""
        
        # Create tool instances (only for tools that exist)
        self.tools = {
            "memory": MemoryTool(),
            "shell": ShellTool(),
            "web": WebTool(),
            "browser": BrowserTool(),      # HTTP-based headless browser
            "playwright": PlaywrightBrowserTool(headless=False),  # Visible Playwright browser
            "file_reader": FileReaderTool(),  # File reading (PDF, DOCX, PPTX, XLSX, CSV, JSON, etc.)
        }
        
        # Define categories
        self.categories = {
            "core": ToolCategory(
                name="core",
                description="Essential tools always available",
                keywords=["remember", "search", "forget", "recall"],
                tools=["memory_remember", "memory_search", "memory_forget"],
                always_include=True
            ),
            "shell": ToolCategory(
                name="shell",
                description="Shell command execution",
                keywords=["shell", "command", "exec", "bash", "terminal", "run", "execute"],
                tools=["shell_exec", "shell_read", "shell_write", "shell_list", "shell_glob", "shell_exists"]
            ),
            "web_search": ToolCategory(
                name="web_search",
                description="Web search and content fetching (HTTP-based)",
                keywords=["search", "web", "internet", "google", "duckduckgo", "fetch", "download", "crawl", "find files"],
                tools=["web_search", "web_fetch", "web_download", "web_crawl", "web_find_files"]
            ),
            "browser": ToolCategory(
                name="browser",
                description="Interactive web browsing (HTTP-based headless)",
                keywords=["browser", "browse", "navigate", "click", "form", "fill", "submit", "extract", "links", "back", "open", "visit"],
                tools=[
                    "browser_open", "browser_back", "browser_status", "browser_text",
                    "browser_links", "browser_click", "browser_extract", "browser_forms",
                    "browser_fill", "browser_submit", "browser_search"
                ]
            ),
            "playwright": ToolCategory(
                name="playwright",
                description="Visible browser automation with full JavaScript support (Playwright)",
                keywords=["playwright", "visible", "chrome", "chromium", "javascript", "js", "screenshot", "pdf", "automation", "visible browser", "real browser"],
                tools=[
                    "playwright_open", "playwright_close", "playwright_navigate", "playwright_click", "playwright_type", "playwright_fill",
                    "playwright_select", "playwright_wait", "playwright_extract", "playwright_screenshot", "playwright_pdf",
                    "playwright_eval", "playwright_scroll", "playwright_hover", "playwright_press", "playwright_get_text",
                    "playwright_get_html", "playwright_get_url", "playwright_get_title", "playwright_go_back",
                    "playwright_go_forward", "playwright_reload", "playwright_new_tab", "playwright_switch_tab",
                    "playwright_close_tab"
                ]
            ),
            "file_reader": ToolCategory(
                name="file_reader",
                description="Read and extract content from various file formats (PDF, DOCX, PPTX, XLSX, CSV, JSON, TXT, MD, etc.)",
                keywords=["file", "read", "pdf", "docx", "pptx", "xlsx", "csv", "json", "txt", "document", "spreadsheet", "presentation", "spreadsheet", "excel", "powerpoint", "word", "text", "markdown"],
                tools=[
                    "file_read", "file_read_pdf", "file_read_docx", "file_read_pptx", "file_read_xlsx",
                    "file_read_csv", "file_read_json", "file_read_text", "file_list", "file_info"
                ]
            ),
        }
        
        # Build tool -> category mapping
        for cat_name, cat in self.categories.items():
            for tool_name in cat.tools:
                self.tool_to_category[tool_name] = cat_name
    
    def get_all_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get all tool schemas from all tools."""
        schemas = []
        for tool in self.tools.values():
            schemas.extend(tool.get_tools())
        return schemas
    
    def get_all_functions(self) -> Dict[str, Any]:
        """Get all function implementations from all tools."""
        functions = {}
        for tool in self.tools.values():
            functions.update(tool.functions)
        return functions
    
    def get_tool_category(self, tool_name: str) -> Optional[str]:
        """Get the category for a tool."""
        return self.tool_to_category.get(tool_name)
    
    def get_categories_for_query(self, query: str) -> List[str]:
        """
        Determine relevant tool categories based on user query.
        
        Args:
            query: User's input text
            
        Returns:
            List of category names, ordered by relevance
        """
        query_lower = query.lower()
        category_scores = {}
        
        for cat_name, cat in self.categories.items():
            if cat.always_include:
                category_scores[cat_name] = float('inf')
                continue
            
            score = 0
            for keyword in cat.keywords:
                # Count keyword occurrences
                score += query_lower.count(keyword.lower())
            
            if score > 0:
                category_scores[cat_name] = score
        
        # Sort by score (highest first)
        sorted_categories = sorted(
            category_scores.keys(), 
            key=lambda c: category_scores[c], 
            reverse=True
        )
        
        # Always include core
        if "core" in sorted_categories:
            sorted_categories.remove("core")
        return ["core"] + sorted_categories
    
    def get_filtered_schemas(self, query: str, max_tools: int = None) -> List[Dict[str, Any]]:
        """
        Get filtered tool schemas relevant to the query.
        
        Args:
            query: User's input text
            max_tools: Maximum tools to return (default: self.MAX_TOOLS)
            
        Returns:
            List of tool schemas for relevant tools
        """
        if max_tools is None:
            max_tools = self.MAX_TOOLS
        
        # Get all schemas with their tool names
        all_schemas = []
        for tool in self.tools.values():
            for schema in tool.get_tools():
                tool_name = schema["function"]["name"]
                cat = self.get_tool_category(tool_name)
                all_schemas.append((tool_name, cat, schema))
        
        # Determine relevant categories
        relevant_categories = self.get_categories_for_query(query)
        
        # Filter and prioritize schemas
        # 1. Always include core tools
        # 2. Include tools from relevant categories in order
        # 3. Fill remaining slots with other tools
        
        selected = []
        remaining_slots = max_tools
        
        # Add core tools first
        for tool_name, cat, schema in all_schemas:
            if cat == "core" and remaining_slots > 0:
                selected.append(schema)
                remaining_slots -= 1
        
        # Add tools from relevant categories
        for cat_name in relevant_categories:
            if cat_name == "core":
                continue
            if remaining_slots <= 0:
                break
            
            for tool_name, cat, schema in all_schemas:
                if cat == cat_name and remaining_slots > 0:
                    selected.append(schema)
                    remaining_slots -= 1
        
        # Fill remaining with other tools if needed
        if remaining_slots > 0:
            used_names = {s["function"]["name"] for s in selected}
            # Priority order for fallback tools (most generally useful first)
            fallback_priority = ["shell", "web_search", "browser", "playwright"]
            
            for fallback_cat in fallback_priority:
                if remaining_slots <= 0:
                    break
                for tool_name, cat, schema in all_schemas:
                    if cat == fallback_cat and tool_name not in used_names and remaining_slots > 0:
                        selected.append(schema)
                        used_names.add(tool_name)
                        remaining_slots -= 1
            
            # Any remaining tools
            if remaining_slots > 0:
                for tool_name, cat, schema in all_schemas:
                    if tool_name not in used_names and remaining_slots > 0:
                        selected.append(schema)
                        remaining_slots -= 1
        
        return selected
    
    def get_filtered_functions(self, query: str) -> Dict[str, Any]:
        """Get filtered function implementations for relevant tools."""
        schemas = self.get_filtered_schemas(query)
        tool_names = {s["function"]["name"] for s in schemas}
        
        functions = {}
        for tool in self.tools.values():
            for name, func in tool.functions.items():
                if name in tool_names:
                    functions[name] = func
        return functions


# Global registry instance
_tool_registry: Optional[ToolRegistry] = None

def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry instance."""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry