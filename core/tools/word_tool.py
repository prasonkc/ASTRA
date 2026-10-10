"""
Word (DOCX) tool for ASTRA - create, read, edit, and format Word documents.

Built on python-docx. The tool is stateless: every operation takes the target
``path``, opens the document, applies the change, and saves it back. Relative
paths are resolved against ``working_dir`` (defaults to the current directory).

All methods return a dict containing at least ``success`` and, on failure,
``error``.
"""
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    DOCX_AVAILABLE = True
except ImportError:  # pragma: no cover - dependency is declared in requirements.txt
    DOCX_AVAILABLE = False


class WordTool:
    def __init__(self, working_dir: Optional[str] = None):
        """
        Initialize Word tool.

        Args:
            working_dir: Base directory for relative paths (default: cwd)
        """
        self.working_dir = working_dir or os.getcwd()

        self.functions = {
            "word_create": self.create,
            "word_read": self.read,
            "word_info": self.info,
            "word_add_heading": self.add_heading,
            "word_add_paragraph": self.add_paragraph,
            "word_add_bullet": self.add_bullet,
            "word_add_table": self.add_table,
            "word_format": self.format,
            "word_replace": self.replace,
            "word_delete_paragraph": self.delete_paragraph,
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _resolve(self, path: str) -> Path:
        """Resolve a path relative to the working directory."""
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(self.working_dir) / p
        return p.resolve()

    def _unavailable(self) -> Optional[Dict[str, Any]]:
        if not DOCX_AVAILABLE:
            return {
                "success": False,
                "error": "python-docx not installed. Run: pip install python-docx",
            }
        return None

    @staticmethod
    def _parse_color(color: Optional[str]) -> Optional[Any]:
        if not color:
            return None
        value = str(color).strip().lstrip("#")
        try:
            return RGBColor.from_string(value.upper())
        except Exception:
            return None

    @staticmethod
    def _apply_run_style(
        run: Any,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        underline: Optional[bool] = None,
        font: Optional[str] = None,
        size: Optional[float] = None,
        color: Optional[str] = None,
    ) -> None:
        if bold is not None:
            run.bold = bool(bold)
        if italic is not None:
            run.italic = bool(italic)
        if underline is not None:
            run.underline = bool(underline)
        if font:
            run.font.name = str(font)
        if size is not None:
            try:
                run.font.size = Pt(float(size))
            except (TypeError, ValueError):
                pass
        rgb = WordTool._parse_color(color)
        if rgb is not None:
            run.font.color.rgb = rgb

    @staticmethod
    def _apply_alignment(paragraph: Any, align: Optional[str]) -> None:
        if not align:
            return
        mapping = {
            "left": WD_ALIGN_PARAGRAPH.LEFT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        }
        key = str(align).strip().lower()
        if key not in mapping:
            raise ValueError(
                f"Invalid alignment '{align}'. Use left, center, right or justify."
            )
        paragraph.alignment = mapping[key]

    def _load(self, path: str) -> Any:
        """Load a document, raising ValueError if it cannot be found."""
        resolved = self._resolve(path)
        if not resolved.exists():
            raise ValueError(f"File not found: {resolved}")
        if not resolved.is_file():
            raise ValueError(f"Not a file: {resolved}")
        return Document(str(resolved))

    @staticmethod
    def _save(doc: Any, resolved: Path) -> None:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(resolved))

    @staticmethod
    def _matches(
        paragraph: Any,
        find: Optional[str],
        index: Optional[int],
        paragraph_index: int,
    ) -> bool:
        """Return True when a paragraph satisfies all provided criteria."""
        if find is not None and index is not None:
            return paragraph_index == index and find in paragraph.text
        if index is not None:
            return paragraph_index == index
        if find is not None:
            return find in paragraph.text
        return False

    @staticmethod
    def _replace_in_paragraph(
        paragraph: Any, old: str, new: str, limit: Optional[int] = None
    ) -> int:
        """Replace text in a paragraph. Returns number of replacements made."""
        count = 0

        # Preferred: replace inside individual runs (preserves formatting).
        for run in paragraph.runs:
            if limit is not None and count >= limit:
                break
            if old in run.text:
                occurrences = run.text.count(old)
                if limit is not None:
                    occurrences = min(occurrences, limit - count)
                run.text = run.text.replace(old, new, occurrences)
                count += occurrences

        if count or old not in paragraph.text:
            return count

        # Fallback: the match spans multiple runs. Collapse into the first run.
        runs = paragraph.runs
        if not runs:
            return 0
        occurrences = paragraph.text.count(old)
        if limit is not None:
            occurrences = min(occurrences, limit)
        runs[0].text = paragraph.text.replace(old, new, occurrences)
        for run in runs[1:]:
            run.text = ""
        return occurrences

    # ------------------------------------------------------------------ #
    # Document lifecycle / reading
    # ------------------------------------------------------------------ #
    def create(
        self,
        path: str,
        title: Optional[str] = None,
        content: Optional[Any] = None,
        author: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new Word document.

        Args:
            path: Output .docx path
            title: Optional title (added as a Title/Heading)
            content: Optional paragraph text or list of paragraph strings
            author: Optional author metadata
        """
        err = self._unavailable()
        if err:
            return err
        try:
            if not path or not str(path).strip():
                return {"success": False, "error": "A path is required."}

            resolved = self._resolve(path)
            doc = Document()

            if title:
                doc.core_properties.title = title
                doc.add_heading(title, level=0)
            if author:
                doc.core_properties.author = author

            if content:
                items = content if isinstance(content, list) else [content]
                for item in items:
                    doc.add_paragraph(str(item))

            self._save(doc, resolved)
            return {
                "success": True,
                "path": str(resolved),
                "paragraphs": len(doc.paragraphs),
                "message": f"Created document at {resolved}",
            }
        except Exception as e:
            return {"success": False, "error": f"Create failed: {e}"}

    def read(self, path: str) -> Dict[str, Any]:
        """Read a .docx file: paragraphs (with style info) and tables."""
        err = self._unavailable()
        if err:
            return err
        try:
            doc = self._load(path)
            resolved = self._resolve(path)

            paragraphs = []
            for i, p in enumerate(doc.paragraphs):
                paragraphs.append({
                    "index": i,
                    "text": p.text,
                    "style": p.style.name if p.style is not None else None,
                })

            tables = []
            for table in doc.tables:
                rows = []
                for row in table.rows:
                    rows.append([cell.text for cell in row.cells])
                tables.append(rows)

            return {
                "success": True,
                "path": str(resolved),
                "paragraphs": paragraphs,
                "tables": tables,
                "paragraph_count": len(paragraphs),
                "table_count": len(tables),
            }
        except Exception as e:
            return {"success": False, "error": f"Read failed: {e}"}

    def info(self, path: str) -> Dict[str, Any]:
        """Get metadata and statistics about a .docx file."""
        err = self._unavailable()
        if err:
            return err
        try:
            doc = self._load(path)
            resolved = self._resolve(path)

            non_empty = [p for p in doc.paragraphs if p.text.strip()]
            word_count = sum(len(p.text.split()) for p in doc.paragraphs)

            return {
                "success": True,
                "path": str(resolved),
                "paragraph_count": len(doc.paragraphs),
                "non_empty_paragraphs": len(non_empty),
                "word_count": word_count,
                "table_count": len(doc.tables),
                "section_count": len(doc.sections),
                "title": doc.core_properties.title,
                "author": doc.core_properties.author,
                "size_bytes": resolved.stat().st_size if resolved.exists() else 0,
            }
        except Exception as e:
            return {"success": False, "error": f"Info failed: {e}"}

    # ------------------------------------------------------------------ #
    # Content authoring
    # ------------------------------------------------------------------ #
    def add_heading(self, path: str, text: str, level: int = 1) -> Dict[str, Any]:
        """Append a heading to a document."""
        err = self._unavailable()
        if err:
            return err
        try:
            doc = self._load(path)
            resolved = self._resolve(path)

            doc.add_heading(text or "", level=int(level))
            self._save(doc, resolved)
            return {"success": True, "path": str(resolved), "level": int(level)}
        except Exception as e:
            return {"success": False, "error": f"Add heading failed: {e}"}

    def add_paragraph(
        self,
        path: str,
        text: str,
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
        font: Optional[str] = None,
        size: Optional[float] = None,
        color: Optional[str] = None,
        align: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append a formatted paragraph to a document."""
        err = self._unavailable()
        if err:
            return err
        try:
            doc = self._load(path)
            resolved = self._resolve(path)

            paragraph = doc.add_paragraph()
            run = paragraph.add_run(text or "")
            self._apply_run_style(run, bold, italic, underline, font, size, color)
            self._apply_alignment(paragraph, align)

            self._save(doc, resolved)
            return {"success": True, "path": str(resolved)}
        except Exception as e:
            return {"success": False, "error": f"Add paragraph failed: {e}"}

    def add_bullet(self, path: str, text: str) -> Dict[str, Any]:
        """Append a bullet list item."""
        err = self._unavailable()
        if err:
            return err
        try:
            doc = self._load(path)
            resolved = self._resolve(path)

            doc.add_paragraph(text or "", style="List Bullet")
            self._save(doc, resolved)
            return {"success": True, "path": str(resolved)}
        except Exception as e:
            return {"success": False, "error": f"Add bullet failed: {e}"}

    def add_table(
        self, path: str, data: List[List[Any]], header: bool = True
    ) -> Dict[str, Any]:
        """
        Append a table to a document.

        Args:
            path: Document path
            data: List of rows, each row a list of cell values
            header: Style the first row as a header row
        """
        err = self._unavailable()
        if err:
            return err
        if not data or not isinstance(data, list):
            return {"success": False, "error": "'data' must be a non-empty list."}
        try:
            doc = self._load(path)
            resolved = self._resolve(path)

            rows = len(data)
            cols = max((len(r) for r in data if isinstance(r, list)), default=0)
            if cols == 0:
                return {"success": False, "error": "Each row must be a list of values."}

            table = doc.add_table(rows=rows, cols=cols)
            try:
                table.style = "Table Grid"
            except Exception:
                pass

            for r, row in enumerate(data):
                for c in range(cols):
                    value = row[c] if isinstance(row, list) and c < len(row) else ""
                    cell = table.cell(r, c)
                    cell.text = "" if value is None else str(value)
                    if header and r == 0:
                        for p in cell.paragraphs:
                            for run in p.runs:
                                run.bold = True

            self._save(doc, resolved)
            return {"success": True, "path": str(resolved), "rows": rows, "cols": cols}
        except Exception as e:
            return {"success": False, "error": f"Add table failed: {e}"}

    # ------------------------------------------------------------------ #
    # Editing / formatting
    # ------------------------------------------------------------------ #
    def format(
        self,
        path: str,
        find: Optional[str] = None,
        index: Optional[int] = None,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        underline: Optional[bool] = None,
        font: Optional[str] = None,
        size: Optional[float] = None,
        color: Optional[str] = None,
        align: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Format existing paragraphs. Target them by text match (find)
        or by paragraph index (index). At least one of find/index is required.
        """
        err = self._unavailable()
        if err:
            return err
        if find is None and index is None:
            return {
                "success": False,
                "error": "At least one of 'find' or 'index' is required.",
            }
        try:
            doc = self._load(path)
            resolved = self._resolve(path)

            formatted = 0
            for i, paragraph in enumerate(doc.paragraphs):
                if not self._matches(paragraph, find, index, i):
                    continue
                for run in paragraph.runs:
                    self._apply_run_style(
                        run, bold, italic, underline, font, size, color
                    )
                self._apply_alignment(paragraph, align)
                formatted += 1

            if formatted == 0:
                return {"success": False, "error": "No matching paragraphs found."}

            self._save(doc, resolved)
            return {"success": True, "path": str(resolved), "formatted": formatted}
        except Exception as e:
            return {"success": False, "error": f"Format failed: {e}"}

    def replace(
        self,
        path: str,
        old: str,
        new: str,
        replace_all: bool = True,
    ) -> Dict[str, Any]:
        """Find and replace text throughout a document."""
        err = self._unavailable()
        if err:
            return err
        if not old:
            return {"success": False, "error": "'old' must not be empty."}
        try:
            doc = self._load(path)
            resolved = self._resolve(path)

            limit = None if replace_all else 1
            replacements = 0
            for paragraph in doc.paragraphs:
                remaining = None if limit is None else limit - replacements
                if remaining is not None and remaining <= 0:
                    break
                replacements += self._replace_in_paragraph(
                    paragraph, old, new or "", remaining
                )

            if replacements:
                self._save(doc, resolved)
            return {
                "success": True,
                "path": str(resolved),
                "replacements": replacements,
            }
        except Exception as e:
            return {"success": False, "error": f"Replace failed: {e}"}

    def delete_paragraph(self, path: str, index: int) -> Dict[str, Any]:
        """Delete the paragraph at the given index."""
        err = self._unavailable()
        if err:
            return err
        try:
            doc = self._load(path)
            resolved = self._resolve(path)

            paragraphs = doc.paragraphs
            if index < 0 or index >= len(paragraphs):
                return {
                    "success": False,
                    "error": f"Paragraph index out of range: {index} "
                             f"(document has {len(paragraphs)} paragraphs).",
                }

            element = paragraphs[index]._element
            element.getparent().remove(element)
            self._save(doc, resolved)
            return {"success": True, "path": str(resolved), "deleted_index": index}
        except Exception as e:
            return {"success": False, "error": f"Delete paragraph failed: {e}"}

    # ------------------------------------------------------------------ #
    # Tool schema
    # ------------------------------------------------------------------ #
    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for function calling."""
        def prop(t: str, d: str, **extra: Any) -> Dict[str, Any]:
            p: Dict[str, Any] = {"type": t, "description": d}
            p.update(extra)
            return p

        return [
            self._schema(
                "word_create",
                "Create a new Word (.docx) document",
                {
                    "path": prop("string", "Output file path ending in .docx"),
                    "title": prop("string", "Optional title heading"),
                    "content": prop("string", "Optional paragraph text (or a list of strings)"),
                    "author": prop("string", "Optional author metadata"),
                },
                ["path"],
            ),
            self._schema(
                "word_read",
                "Read paragraphs and tables from a Word document",
                {"path": prop("string", "Path to .docx file")},
                ["path"],
            ),
            self._schema(
                "word_info",
                "Get metadata and stats of a Word document",
                {"path": prop("string", "Path to .docx file")},
                ["path"],
            ),
            self._schema(
                "word_add_heading",
                "Append a heading to a Word document",
                {
                    "path": prop("string", "Path to .docx file"),
                    "text": prop("string", "Heading text"),
                    "level": prop("integer", "Heading level 0-9 (0 = document title)", default=1),
                },
                ["path", "text"],
            ),
            self._schema(
                "word_add_paragraph",
                "Append a formatted paragraph to a Word document",
                {
                    "path": prop("string", "Path to .docx file"),
                    "text": prop("string", "Paragraph text"),
                    "bold": prop("boolean", "Bold text", default=False),
                    "italic": prop("boolean", "Italic text", default=False),
                    "underline": prop("boolean", "Underline text", default=False),
                    "font": prop("string", "Font name, e.g. 'Calibri'"),
                    "size": prop("number", "Font size in points"),
                    "color": prop("string", "Hex color like '#FF0000' or 'FF0000'"),
                    "align": prop(
                        "string", "Alignment",
                        enum=["left", "center", "right", "justify"],
                    ),
                },
                ["path", "text"],
            ),
            self._schema(
                "word_add_bullet",
                "Append a bullet list item to a Word document",
                {
                    "path": prop("string", "Path to .docx file"),
                    "text": prop("string", "Bullet text"),
                },
                ["path", "text"],
            ),
            self._schema(
                "word_add_table",
                "Append a table to a Word document",
                {
                    "path": prop("string", "Path to .docx file"),
                    "data": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}},
                        "description": "Rows of cell values",
                    },
                    "header": prop("boolean", "Style first row as header", default=True),
                },
                ["path", "data"],
            ),
            self._schema(
                "word_format",
                "Format paragraphs in a Word document (bold, font, color, alignment...)",
                {
                    "path": prop("string", "Path to .docx file"),
                    "find": prop("string", "Target paragraphs containing this text"),
                    "index": prop("integer", "Target paragraph by index"),
                    "bold": prop("boolean", "Bold"),
                    "italic": prop("boolean", "Italic"),
                    "underline": prop("boolean", "Underline"),
                    "font": prop("string", "Font name"),
                    "size": prop("number", "Font size in points"),
                    "color": prop("string", "Hex color like '#FF0000' or 'FF0000'"),
                    "align": prop(
                        "string", "Alignment",
                        enum=["left", "center", "right", "justify"],
                    ),
                },
                ["path"],
            ),
            self._schema(
                "word_replace",
                "Find and replace text in a Word document",
                {
                    "path": prop("string", "Path to .docx file"),
                    "old": prop("string", "Text to find"),
                    "new": prop("string", "Replacement text"),
                    "replace_all": prop("boolean", "Replace all occurrences", default=True),
                },
                ["path", "old", "new"],
            ),
            self._schema(
                "word_delete_paragraph",
                "Delete a paragraph by index",
                {
                    "path": prop("string", "Path to .docx file"),
                    "index": prop("integer", "Paragraph index"),
                },
                ["path", "index"],
            ),
        ]

    @staticmethod
    def _schema(
        name: str, description: str, properties: Dict[str, Any], required: List[str]
    ) -> Dict[str, Any]:
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
