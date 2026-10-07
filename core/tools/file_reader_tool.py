"""
File Reading Tool for ASTRA - provides ability to read various document formats.
Supports PDF, DOCX, PPTX, XLSX, CSV, JSON, TXT, MD, and more.
"""
import os
import json
import csv
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from utils.colors import warning, error


class FileReaderTool:
    def __init__(self, max_file_size: int = 50 * 1024 * 1024):  # 50MB default
        """
        Initialize file reader tool.
        
        Args:
            max_file_size: Maximum file size to read (bytes)
        """
        self.max_file_size = max_file_size
        
        self.functions = {
            "file_read": self.read_file,
            "file_read_pdf": self.read_pdf,
            "file_read_docx": self.read_docx,
            "file_read_pptx": self.read_pptx,
            "file_read_xlsx": self.read_xlsx,
            "file_read_csv": self.read_csv,
            "file_read_json": self.read_json,
            "file_read_text": self.read_text,
            "file_list": self.list_files,
            "file_info": self.get_file_info,
        }

    def _check_file(self, path: str) -> Optional[Dict[str, Any]]:
        """Validate file exists and is within size limit."""
        try:
            file_path = Path(path).resolve()
            if not file_path.exists():
                return {"success": False, "error": f"File not found: {path}"}
            if not file_path.is_file():
                return {"success": False, "error": f"Not a file: {path}"}
            
            size = file_path.stat().st_size
            if size > self.max_file_size:
                return {"success": False, "error": f"File too large: {size} bytes (max {self.max_file_size})"}
            
            return None
        except Exception as e:
            return {"success": False, "error": f"File check failed: {e}"}

    def read_file(self, path: str) -> Dict[str, Any]:
        """
        Read any supported file automatically based on extension.
        
        Args:
            path: Path to file
            
        Returns:
            Dict with success, content, file_type, metadata
        """
        error_result = self._check_file(path)
        if error_result:
            return error_result
        
        ext = Path(path).suffix.lower()
        
        try:
            if ext == '.pdf':
                return self.read_pdf(path)
            elif ext == '.docx':
                return self.read_docx(path)
            elif ext == '.pptx':
                return self.read_pptx(path)
            elif ext == '.xlsx':
                return self.read_xlsx(path)
            elif ext == '.csv':
                return self.read_csv(path)
            elif ext == '.json':
                return self.read_json(path)
            elif ext in ['.txt', '.md', '.py', '.js', '.html', '.css', '.xml', '.yaml', '.yml']:
                return self.read_text(path)
            else:
                # Try as text
                return self.read_text(path)
        except Exception as e:
            return {"success": False, "error": f"Read failed: {e}"}

    def read_pdf(self, path: str) -> Dict[str, Any]:
        """Read PDF file and extract text."""
        error_result = self._check_file(path)
        if error_result:
            return error_result
        
        try:
            import pdfplumber
            text_parts = []
            metadata = {}
            
            with pdfplumber.open(path) as pdf:
                metadata = {
                    "pages": len(pdf.pages),
                    "metadata": pdf.metadata or {}
                }
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        text_parts.append(f"--- Page {i+1} ---\n{text}")
            
            return {
                "success": True,
                "content": "\n\n".join(text_parts),
                "file_type": "pdf",
                "metadata": metadata
            }
        except ImportError:
            return {"success": False, "error": "pdfplumber not installed. Run: pip install pdfplumber"}
        except Exception as e:
            return {"success": False, "error": f"PDF read failed: {e}"}

    def read_docx(self, path: str) -> Dict[str, Any]:
        """Read DOCX file and extract text."""
        error_result = self._check_file(path)
        if error_result:
            return error_result
        
        try:
            from docx import Document
            doc = Document(path)
            
            text_parts = []
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)
            
            # Also extract tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(cell.text for cell in row.cells)
                    if row_text.strip():
                        text_parts.append(row_text)
            
            return {
                "success": True,
                "content": "\n\n".join(text_parts),
                "file_type": "docx",
                "metadata": {
                    "paragraphs": len(doc.paragraphs),
                    "tables": len(doc.tables)
                }
            }
        except ImportError:
            return {"success": False, "error": "python-docx not installed. Run: pip install python-docx"}
        except Exception as e:
            return {"success": False, "error": f"DOCX read failed: {e}"}

    def read_pptx(self, path: str) -> Dict[str, Any]:
        """Read PPTX file and extract text."""
        error_result = self._check_file(path)
        if error_result:
            return error_result
        
        try:
            from pptx import Presentation
            prs = Presentation(path)
            
            text_parts = []
            for i, slide in enumerate(prs.slides):
                slide_text = [f"--- Slide {i+1} ---"]
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            if para.text.strip():
                                slide_text.append(para.text)
                    if shape.has_table:
                        for row in shape.table.rows:
                            row_text = " | ".join(cell.text for cell in row.cells)
                            if row_text.strip():
                                slide_text.append(row_text)
                text_parts.append("\n".join(slide_text))
            
            return {
                "success": True,
                "content": "\n\n".join(text_parts),
                "file_type": "pptx",
                "metadata": {
                    "slides": len(prs.slides)
                }
            }
        except ImportError:
            return {"success": False, "error": "python-pptx not installed. Run: pip install python-pptx"}
        except Exception as e:
            return {"success": False, "error": f"PPTX read failed: {e}"}

    def read_xlsx(self, path: str, sheet_name: Optional[str] = None, max_rows: int = 1000) -> Dict[str, Any]:
        """Read XLSX file and extract data."""
        error_result = self._check_file(path)
        if error_result:
            return error_result
        
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            
            sheets_data = {}
            if sheet_name:
                sheets = [wb[sheet_name]] if sheet_name in wb.sheetnames else []
            else:
                sheets = [wb[s] for s in wb.sheetnames[:5]]  # Limit to first 5 sheets
            
            for ws in sheets:
                rows = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= max_rows:
                        break
                    # Convert None to empty string
                    row_data = [str(v) if v is not None else "" for v in row]
                    if any(cell.strip() for cell in row_data):
                        rows.append(row_data)
                
                if rows:
                    sheets_data[ws.title] = {
                        "rows": rows,
                        "row_count": len(rows),
                        "col_count": len(rows[0]) if rows else 0
                    }
            
            wb.close()
            
            return {
                "success": True,
                "content": json.dumps(sheets_data, indent=2),
                "file_type": "xlsx",
                "metadata": {
                    "sheets": list(sheets_data.keys())
                }
            }
        except ImportError:
            return {"success": False, "error": "openpyxl not installed. Run: pip install openpyxl"}
        except Exception as e:
            return {"success": False, "error": f"XLSX read failed: {e}"}

    def read_csv(self, path: str, delimiter: str = ",", max_rows: int = 1000) -> Dict[str, Any]:
        """Read CSV file."""
        error_result = self._check_file(path)
        if error_result:
            return error_result
        
        try:
            rows = []
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter=delimiter)
                for i, row in enumerate(reader):
                    if i >= max_rows:
                        break
                    rows.append(row)
            
            return {
                "success": True,
                "content": json.dumps(rows, indent=2),
                "file_type": "csv",
                "metadata": {
                    "rows": len(rows),
                    "cols": len(rows[0]) if rows else 0
                }
            }
        except Exception as e:
            return {"success": False, "error": f"CSV read failed: {e}"}

    def read_json(self, path: str) -> Dict[str, Any]:
        """Read JSON file."""
        error_result = self._check_file(path)
        if error_result:
            return error_result
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return {
                "success": True,
                "content": json.dumps(data, indent=2),
                "file_type": "json",
                "metadata": {
                    "type": type(data).__name__,
                    "keys": list(data.keys()) if isinstance(data, dict) else None
                }
            }
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON: {e}"}
        except Exception as e:
            return {"success": False, "error": f"JSON read failed: {e}"}

    def read_text(self, path: str, encoding: str = "utf-8") -> Dict[str, Any]:
        """Read plain text file."""
        error_result = self._check_file(path)
        if error_result:
            return error_result
        
        try:
            with open(path, 'r', encoding=encoding) as f:
                content = f.read()
            
            return {
                "success": True,
                "content": content,
                "file_type": "text",
                "metadata": {
                    "size": len(content),
                    "lines": content.count('\n') + 1
                }
            }
        except UnicodeDecodeError:
            # Try with different encoding
            try:
                with open(path, 'r', encoding='latin-1') as f:
                    content = f.read()
                return {
                    "success": True,
                    "content": content,
                    "file_type": "text",
                    "metadata": {"encoding": "latin-1"}
                }
            except Exception as e:
                return {"success": False, "error": f"Text read failed: {e}"}
        except Exception as e:
            return {"success": False, "error": f"Text read failed: {e}"}

    def list_files(self, directory: str = ".", pattern: str = "*", recursive: bool = False) -> Dict[str, Any]:
        """List files in a directory."""
        try:
            dir_path = Path(directory).resolve()
            if not dir_path.exists():
                return {"success": False, "error": f"Directory not found: {directory}"}
            if not dir_path.is_dir():
                return {"success": False, "error": f"Not a directory: {directory}"}
            
            files = []
            if recursive:
                matches = dir_path.rglob(pattern)
            else:
                matches = dir_path.glob(pattern)
            
            for f in matches:
                if f.is_file():
                    stat = f.stat()
                    files.append({
                        "name": f.name,
                        "path": str(f),
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "extension": f.suffix
                    })
            
            return {
                "success": True,
                "files": files,
                "count": len(files)
            }
        except Exception as e:
            return {"success": False, "error": f"List failed: {e}"}

    def get_file_info(self, path: str) -> Dict[str, Any]:
        """Get file metadata without reading content."""
        try:
            file_path = Path(path).resolve()
            if not file_path.exists():
                return {"success": False, "error": f"File not found: {path}"}
            
            stat = file_path.stat()
            return {
                "success": True,
                "path": str(file_path),
                "name": file_path.name,
                "size": stat.st_size,
                "extension": file_path.suffix,
                "modified": stat.st_mtime,
                "created": stat.st_ctime,
                "is_file": file_path.is_file(),
                "is_dir": file_path.is_dir()
            }
        except Exception as e:
            return {"success": False, "error": f"Info failed: {e}"}

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for function calling."""
        def prop(t: str, d: str, **extra):
            p = {"type": t, "description": d}
            p.update(extra)
            return p

        return [
            self._schema("file_read", "Read any supported file (PDF, DOCX, PPTX, XLSX, CSV, JSON, TXT, MD, etc.) automatically by extension",
                         {"path": prop("string", "Path to file")}, ["path"]),
            self._schema("file_read_pdf", "Read PDF file and extract text",
                         {"path": prop("string", "Path to PDF file")}, ["path"]),
            self._schema("file_read_docx", "Read DOCX file and extract text",
                         {"path": prop("string", "Path to DOCX file")}, ["path"]),
            self._schema("file_read_pptx", "Read PPTX file and extract text",
                         {"path": prop("string", "Path to PPTX file")}, ["path"]),
            self._schema("file_read_xlsx", "Read XLSX file and extract data",
                         {"path": prop("string", "Path to XLSX file"),
                          "sheet_name": prop("string", "Specific sheet name (optional)"),
                          "max_rows": prop("integer", "Maximum rows to read", default=1000)},
                         ["path"]),
            self._schema("file_read_csv", "Read CSV file",
                         {"path": prop("string", "Path to CSV file"),
                          "delimiter": prop("string", "Delimiter character", default=","),
                          "max_rows": prop("integer", "Maximum rows to read", default=1000)},
                         ["path"]),
            self._schema("file_read_json", "Read JSON file",
                         {"path": prop("string", "Path to JSON file")}, ["path"]),
            self._schema("file_read_text", "Read plain text file (TXT, MD, PY, etc.)",
                         {"path": prop("string", "Path to text file"),
                          "encoding": prop("string", "Text encoding", default="utf-8")},
                         ["path"]),
            self._schema("file_list", "List files in a directory",
                         {"directory": prop("string", "Directory path", default="."),
                          "pattern": prop("string", "Glob pattern", default="*"),
                          "recursive": prop("boolean", "Search recursively", default=False)},
                         []),
            self._schema("file_info", "Get file metadata without reading content",
                         {"path": prop("string", "Path to file")}, ["path"]),
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