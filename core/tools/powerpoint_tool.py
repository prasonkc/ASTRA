"""
PowerPoint (PPTX) tool for ASTRA - create, read, edit, and format presentations.

Built on python-pptx. The tool is stateless: every operation takes the target
``path``, opens the presentation, applies the change, and saves it back.
Relative paths are resolved against ``working_dir`` (defaults to the cwd).
Positions and sizes are expressed in inches.

All methods return a dict containing at least ``success`` and, on failure,
``error``.
"""
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    PPTX_AVAILABLE = True
    PPTX_IMPORT_ERROR = ""
except ImportError as e:  # pragma: no cover - dependency is declared in requirements.txt
    PPTX_AVAILABLE = False
    PPTX_IMPORT_ERROR = str(e)


# Logical layout name -> index in the default python-pptx template
_LAYOUT_INDEX = {
    "title": 0,
    "title_content": 1,
    "section_header": 2,
    "two_content": 3,
    "blank": 6,
}

_ALIGNMENTS = {
    "left": PP_ALIGN.LEFT if PPTX_AVAILABLE else None,
    "center": PP_ALIGN.CENTER if PPTX_AVAILABLE else None,
    "right": PP_ALIGN.RIGHT if PPTX_AVAILABLE else None,
    "justify": PP_ALIGN.JUSTIFY if PPTX_AVAILABLE else None,
}


class PowerPointTool:
    def __init__(self, working_dir: Optional[str] = None):
        """
        Initialize PowerPoint tool.

        Args:
            working_dir: Base directory for relative paths (default: cwd)
        """
        self.working_dir = working_dir or os.getcwd()

        self.functions = {
            "ppt_create": self.create,
            "ppt_read": self.read,
            "ppt_info": self.info,
            "ppt_add_slide": self.add_slide,
            "ppt_add_text": self.add_text,
            "ppt_add_bullets": self.add_bullets,
            "ppt_add_table": self.add_table,
            "ppt_add_image": self.add_image,
            "ppt_format": self.format,
            "ppt_delete_slide": self.delete_slide,
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
        if not PPTX_AVAILABLE:
            detail = f" ({PPTX_IMPORT_ERROR})" if PPTX_IMPORT_ERROR else ""
            return {
                "success": False,
                "error": f"python-pptx not installed. Run: pip install python-pptx{detail}",
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
        size: Optional[float] = None,
        bold: Optional[bool] = None,
        color: Optional[str] = None,
    ) -> None:
        if size is not None:
            try:
                run.font.size = Pt(float(size))
            except (TypeError, ValueError):
                pass
        if bold is not None:
            run.font.bold = bool(bold)
        rgb = PowerPointTool._parse_color(color)
        if rgb is not None:
            run.font.color.rgb = rgb

    @staticmethod
    def _apply_alignment(paragraph: Any, align: Optional[str]) -> None:
        if not align:
            return
        key = str(align).strip().lower()
        if key not in _ALIGNMENTS:
            raise ValueError(
                f"Invalid alignment '{align}'. Use left, center, right or justify."
            )
        paragraph.alignment = _ALIGNMENTS[key]

    def _pick_layout(self, prs: Any, kind: str):
        """Pick a slide layout from the default template by logical name."""
        idx = _LAYOUT_INDEX.get(str(kind).strip().lower(), 1)
        layouts = prs.slide_layouts
        if idx >= len(layouts):
            idx = min(1, len(layouts) - 1)
        return layouts[idx]

    @staticmethod
    def _content_placeholder(slide: Any):
        """Return the body/content placeholder of a slide, if any."""
        for shape in slide.placeholders:
            if shape.placeholder_format.idx == 1:
                return shape
        return None

    @staticmethod
    def _slide_text(slide: Any) -> List[Dict[str, Any]]:
        """Extract text (per shape) from a slide."""
        parts: List[Dict[str, Any]] = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append({"name": shape.name, "text": shape.text_frame.text})
        return parts

    def _load(self, path: str) -> Any:
        """Load a presentation, raising ValueError if it cannot be found."""
        resolved = self._resolve(path)
        if not resolved.exists():
            raise ValueError(f"File not found: {resolved}")
        if not resolved.is_file():
            raise ValueError(f"Not a file: {resolved}")
        return Presentation(str(resolved))

    @staticmethod
    def _save(prs: Any, resolved: Path) -> None:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(resolved))

    @staticmethod
    def _slide_at(prs: Any, slide_index: int):
        slides = list(prs.slides)
        if slide_index < 0 or slide_index >= len(slides):
            raise ValueError(
                f"Slide index out of range: {slide_index} "
                f"(presentation has {len(slides)} slides)."
            )
        return slides[slide_index]

    # ------------------------------------------------------------------ #
    # Presentation lifecycle / reading
    # ------------------------------------------------------------------ #
    def create(
        self,
        path: str,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        author: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new PowerPoint (.pptx) presentation."""
        err = self._unavailable()
        if err:
            return err
        try:
            if not path or not str(path).strip():
                return {"success": False, "error": "A path is required."}

            resolved = self._resolve(path)
            prs = Presentation()

            if title or subtitle:
                slide = prs.slides.add_slide(prs.slide_layouts[0])
                if title and slide.shapes.title is not None:
                    slide.shapes.title.text = title
                # Subtitle placeholder (idx 1) on the Title Slide layout
                subtitle_ph = None
                for ph in slide.placeholders:
                    if ph.placeholder_format.idx == 1:
                        subtitle_ph = ph
                        break
                if subtitle and subtitle_ph is not None:
                    subtitle_ph.text = subtitle

            if title:
                prs.core_properties.title = title
            if author:
                prs.core_properties.author = author

            self._save(prs, resolved)
            return {
                "success": True,
                "path": str(resolved),
                "slides": len(prs.slides),
                "message": f"Created presentation at {resolved}",
            }
        except Exception as e:
            return {"success": False, "error": f"Create failed: {e}"}

    def read(self, path: str) -> Dict[str, Any]:
        """Read all slides and their text from a presentation."""
        err = self._unavailable()
        if err:
            return err
        try:
            prs = self._load(path)
            resolved = self._resolve(path)

            slides = []
            for i, slide in enumerate(prs.slides):
                slides.append({"index": i, "texts": self._slide_text(slide)})

            return {
                "success": True,
                "path": str(resolved),
                "slides": slides,
                "slide_count": len(slides),
            }
        except Exception as e:
            return {"success": False, "error": f"Read failed: {e}"}

    def info(self, path: str) -> Dict[str, Any]:
        """Get metadata and stats of a presentation."""
        err = self._unavailable()
        if err:
            return err
        try:
            prs = self._load(path)
            resolved = self._resolve(path)

            return {
                "success": True,
                "path": str(resolved),
                "slide_count": len(prs.slides),
                "width_inches": round(prs.slide_width.inches, 2),
                "height_inches": round(prs.slide_height.inches, 2),
                "title": prs.core_properties.title,
                "author": prs.core_properties.author,
                "size_bytes": resolved.stat().st_size if resolved.exists() else 0,
            }
        except Exception as e:
            return {"success": False, "error": f"Info failed: {e}"}

    # ------------------------------------------------------------------ #
    # Content authoring
    # ------------------------------------------------------------------ #
    def add_slide(
        self,
        path: str,
        title: Optional[str] = None,
        bullets: Optional[List[str]] = None,
        layout: str = "title_content",
    ) -> Dict[str, Any]:
        """Add a new slide to a presentation."""
        err = self._unavailable()
        if err:
            return err
        try:
            prs = self._load(path)
            resolved = self._resolve(path)

            slide = prs.slides.add_slide(self._pick_layout(prs, layout))

            if title and slide.shapes.title is not None:
                slide.shapes.title.text = title

            if bullets:
                body = self._content_placeholder(slide)
                if body is None:
                    body = slide.shapes.add_textbox(
                        Inches(0.7), Inches(1.5), Inches(8.6), Inches(4.0)
                    )
                tf = body.text_frame
                tf.clear()
                for i, bullet in enumerate(bullets):
                    paragraph = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    paragraph.text = str(bullet)
                    paragraph.level = 0

            self._save(prs, resolved)
            return {
                "success": True,
                "path": str(resolved),
                "slide_index": len(prs.slides) - 1,
            }
        except Exception as e:
            return {"success": False, "error": f"Add slide failed: {e}"}

    def add_text(
        self,
        path: str,
        slide_index: int,
        text: str,
        left: float = 0.7,
        top: float = 0.7,
        width: float = 8.6,
        height: float = 1.5,
        size: Optional[float] = None,
        bold: bool = False,
        color: Optional[str] = None,
        align: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a text box to a slide (inches)."""
        err = self._unavailable()
        if err:
            return err
        try:
            prs = self._load(path)
            resolved = self._resolve(path)
            slide = self._slide_at(prs, slide_index)

            box = slide.shapes.add_textbox(
                Inches(float(left)), Inches(float(top)),
                Inches(float(width)), Inches(float(height)),
            )
            tf = box.text_frame
            tf.word_wrap = True
            paragraph = tf.paragraphs[0]
            paragraph.text = text or ""
            run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
            self._apply_run_style(run, size, bold, color)
            self._apply_alignment(paragraph, align)

            self._save(prs, resolved)
            return {"success": True, "path": str(resolved)}
        except Exception as e:
            return {"success": False, "error": f"Add text failed: {e}"}

    def add_bullets(
        self, path: str, slide_index: int, bullets: List[str]
    ) -> Dict[str, Any]:
        """Set a bullet list on a slide."""
        err = self._unavailable()
        if err:
            return err
        if not bullets or not isinstance(bullets, list):
            return {"success": False, "error": "'bullets' must be a non-empty list."}
        try:
            prs = self._load(path)
            resolved = self._resolve(path)
            slide = self._slide_at(prs, slide_index)

            body = self._content_placeholder(slide)
            if body is None:
                body = slide.shapes.add_textbox(
                    Inches(0.7), Inches(1.5), Inches(8.6), Inches(4.0)
                )
            tf = body.text_frame
            tf.clear()
            for i, bullet in enumerate(bullets):
                paragraph = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                paragraph.text = str(bullet)
                paragraph.level = 0

            self._save(prs, resolved)
            return {"success": True, "path": str(resolved), "count": len(bullets)}
        except Exception as e:
            return {"success": False, "error": f"Add bullets failed: {e}"}

    def add_table(
        self,
        path: str,
        slide_index: int,
        data: List[List[Any]],
        left: float = 0.7,
        top: float = 2.0,
        width: float = 8.6,
        height: float = 3.5,
    ) -> Dict[str, Any]:
        """Add a table to a slide (inches)."""
        err = self._unavailable()
        if err:
            return err
        if not data or not isinstance(data, list):
            return {"success": False, "error": "'data' must be a non-empty list."}
        try:
            prs = self._load(path)
            resolved = self._resolve(path)
            slide = self._slide_at(prs, slide_index)

            rows = len(data)
            cols = max((len(r) for r in data if isinstance(r, list)), default=0)
            if cols == 0:
                return {"success": False, "error": "Each row must be a list of values."}

            shape = slide.shapes.add_table(
                rows, cols,
                Inches(float(left)), Inches(float(top)),
                Inches(float(width)), Inches(float(height)),
            )
            table = shape.table
            for r, row in enumerate(data):
                for c in range(cols):
                    value = row[c] if isinstance(row, list) and c < len(row) else ""
                    table.cell(r, c).text = "" if value is None else str(value)

            self._save(prs, resolved)
            return {"success": True, "path": str(resolved), "rows": rows, "cols": cols}
        except Exception as e:
            return {"success": False, "error": f"Add table failed: {e}"}

    def add_image(
        self,
        path: str,
        slide_index: int,
        image_path: str,
        left: float = 1.0,
        top: float = 1.5,
        width: Optional[float] = None,
        height: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Add an image to a slide (inches)."""
        err = self._unavailable()
        if err:
            return err
        try:
            prs = self._load(path)
            resolved = self._resolve(path)
            slide = self._slide_at(prs, slide_index)

            image = Path(image_path).expanduser()
            if not image.is_absolute():
                image = Path(self.working_dir) / image
            image = image.resolve()
            if not image.exists():
                return {"success": False, "error": f"Image not found: {image}"}

            kwargs: Dict[str, Any] = {}
            if width:
                kwargs["width"] = Inches(float(width))
            if height:
                kwargs["height"] = Inches(float(height))

            slide.shapes.add_picture(
                str(image), Inches(float(left)), Inches(float(top)), **kwargs
            )

            self._save(prs, resolved)
            return {"success": True, "path": str(resolved), "image": str(image)}
        except Exception as e:
            return {"success": False, "error": f"Add image failed: {e}"}

    # ------------------------------------------------------------------ #
    # Editing / formatting
    # ------------------------------------------------------------------ #
    def format(
        self,
        path: str,
        slide_index: int,
        size: Optional[float] = None,
        bold: Optional[bool] = None,
        color: Optional[str] = None,
        align: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Format all text on a slide (size, bold, color, alignment)."""
        err = self._unavailable()
        if err:
            return err
        try:
            prs = self._load(path)
            resolved = self._resolve(path)
            slide = self._slide_at(prs, slide_index)

            runs_formatted = 0
            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                for paragraph in shape.text_frame.paragraphs:
                    if align is not None:
                        self._apply_alignment(paragraph, align)
                    for run in paragraph.runs:
                        self._apply_run_style(run, size, bold, color)
                        runs_formatted += 1

            self._save(prs, resolved)
            return {
                "success": True,
                "path": str(resolved),
                "runs_formatted": runs_formatted,
            }
        except Exception as e:
            return {"success": False, "error": f"Format failed: {e}"}

    def delete_slide(self, path: str, slide_index: int) -> Dict[str, Any]:
        """Delete a slide by index."""
        err = self._unavailable()
        if err:
            return err
        try:
            prs = self._load(path)
            resolved = self._resolve(path)

            sld_id_lst = prs.slides._sldIdLst
            slides = list(sld_id_lst)
            if slide_index < 0 or slide_index >= len(slides):
                return {
                    "success": False,
                    "error": f"Slide index out of range: {slide_index} "
                             f"(presentation has {len(slides)} slides).",
                }

            sld_id_lst.remove(slides[slide_index])
            self._save(prs, resolved)
            return {"success": True, "path": str(resolved), "deleted_index": slide_index}
        except Exception as e:
            return {"success": False, "error": f"Delete slide failed: {e}"}

    # ------------------------------------------------------------------ #
    # Tool schema
    # ------------------------------------------------------------------ #
    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for function calling."""
        def prop(t: str, d: str, **extra: Any) -> Dict[str, Any]:
            p: Dict[str, Any] = {"type": t, "description": d}
            p.update(extra)
            return p

        align_prop = prop(
            "string", "Alignment",
            enum=["left", "center", "right", "justify"],
        )

        return [
            self._schema(
                "ppt_create",
                "Create a new PowerPoint (.pptx) presentation",
                {
                    "path": prop("string", "Output file path ending in .pptx"),
                    "title": prop("string", "Optional title slide heading"),
                    "subtitle": prop("string", "Optional subtitle for the title slide"),
                    "author": prop("string", "Optional author metadata"),
                },
                ["path"],
            ),
            self._schema(
                "ppt_read",
                "Read all slides and their text from a presentation",
                {"path": prop("string", "Path to .pptx file")},
                ["path"],
            ),
            self._schema(
                "ppt_info",
                "Get metadata and stats of a presentation",
                {"path": prop("string", "Path to .pptx file")},
                ["path"],
            ),
            self._schema(
                "ppt_add_slide",
                "Add a new slide to a presentation",
                {
                    "path": prop("string", "Path to .pptx file"),
                    "title": prop("string", "Slide title"),
                    "bullets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of strings",
                    },
                    "layout": prop(
                        "string", "Slide layout",
                        enum=["title", "title_content", "two_content", "section_header", "blank"],
                        default="title_content",
                    ),
                },
                ["path"],
            ),
            self._schema(
                "ppt_add_text",
                "Add a text box to a slide (inches)",
                {
                    "path": prop("string", "Path to .pptx file"),
                    "slide_index": prop("integer", "Target slide (0-based)"),
                    "text": prop("string", "Text to add"),
                    "left": prop("number", "Left position in inches", default=0.7),
                    "top": prop("number", "Top position in inches", default=0.7),
                    "width": prop("number", "Width in inches", default=8.6),
                    "height": prop("number", "Height in inches", default=1.5),
                    "size": prop("number", "Font size in points"),
                    "bold": prop("boolean", "Bold text", default=False),
                    "color": prop("string", "Hex color like '#FF0000' or 'FF0000'"),
                    "align": align_prop,
                },
                ["path", "slide_index", "text"],
            ),
            self._schema(
                "ppt_add_bullets",
                "Set a bullet list on a slide",
                {
                    "path": prop("string", "Path to .pptx file"),
                    "slide_index": prop("integer", "Target slide (0-based)"),
                    "bullets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of strings",
                    },
                },
                ["path", "slide_index", "bullets"],
            ),
            self._schema(
                "ppt_add_table",
                "Add a table to a slide (inches)",
                {
                    "path": prop("string", "Path to .pptx file"),
                    "slide_index": prop("integer", "Target slide (0-based)"),
                    "data": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}},
                        "description": "Rows of cell values",
                    },
                    "left": prop("number", "Left position in inches", default=0.7),
                    "top": prop("number", "Top position in inches", default=2.0),
                    "width": prop("number", "Width in inches", default=8.6),
                    "height": prop("number", "Height in inches", default=3.5),
                },
                ["path", "slide_index", "data"],
            ),
            self._schema(
                "ppt_add_image",
                "Add an image to a slide (inches)",
                {
                    "path": prop("string", "Path to .pptx file"),
                    "slide_index": prop("integer", "Target slide (0-based)"),
                    "image_path": prop("string", "Path to the image file"),
                    "left": prop("number", "Left position in inches", default=1.0),
                    "top": prop("number", "Top position in inches", default=1.5),
                    "width": prop("number", "Width in inches"),
                    "height": prop("number", "Height in inches"),
                },
                ["path", "slide_index", "image_path"],
            ),
            self._schema(
                "ppt_format",
                "Format all text on a slide (size, bold, color, alignment)",
                {
                    "path": prop("string", "Path to .pptx file"),
                    "slide_index": prop("integer", "Target slide (0-based)"),
                    "size": prop("number", "Font size in points"),
                    "bold": prop("boolean", "Bold text"),
                    "color": prop("string", "Hex color like '#FF0000' or 'FF0000'"),
                    "align": align_prop,
                },
                ["path", "slide_index"],
            ),
            self._schema(
                "ppt_delete_slide",
                "Delete a slide by index",
                {
                    "path": prop("string", "Path to .pptx file"),
                    "slide_index": prop("integer", "Slide index to delete"),
                },
                ["path", "slide_index"],
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
