"""
Excel (XLSX) tool for ASTRA - create, read, edit, and format spreadsheets.

Built on openpyxl. The tool is stateless: every operation takes the target
``path``, opens the workbook, applies the change, and saves it back. Relative
paths are resolved against ``working_dir`` (defaults to the cwd).

All methods return a dict containing at least ``success`` and, on failure,
``error``.
"""
import csv
import os
import re
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries

    XLSX_AVAILABLE = True
    XLSX_IMPORT_ERROR = ""
except ImportError as e:  # pragma: no cover - dependency is declared in requirements.txt
    XLSX_AVAILABLE = False
    XLSX_IMPORT_ERROR = str(e)


class ExcelTool:
    def __init__(self, working_dir: Optional[str] = None, max_rows: int = 5000):
        """
        Initialize Excel tool.

        Args:
            working_dir: Base directory for relative paths (default: cwd)
            max_rows: Default maximum rows returned by read operations
        """
        self.working_dir = working_dir or os.getcwd()
        self.max_rows = max_rows

        self.functions = {
            "excel_create": self.create,
            "excel_read": self.read,
            "excel_info": self.info,
            "excel_write": self.write_cell,
            "excel_write_rows": self.write_rows,
            "excel_format": self.format,
            "excel_formula": self.set_formula,
            "excel_find": self.find,
            "excel_stats": self.stats,
            "excel_add_sheet": self.add_sheet,
            "excel_delete_sheet": self.delete_sheet,
            "excel_to_csv": self.to_csv,
            "csv_to_excel": self.csv_to_excel,
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
        if not XLSX_AVAILABLE:
            detail = f" ({XLSX_IMPORT_ERROR})" if XLSX_IMPORT_ERROR else ""
            return {
                "success": False,
                "error": f"openpyxl not installed. Run: pip install openpyxl{detail}",
            }
        return None

    def _load(self, path: str, data_only: bool = False) -> Any:
        """Load a workbook, raising ValueError if it cannot be found."""
        resolved = self._resolve(path)
        if not resolved.exists():
            raise ValueError(f"File not found: {resolved}")
        if not resolved.is_file():
            raise ValueError(f"Not a file: {resolved}")
        return load_workbook(str(resolved), data_only=data_only)

    def _load_or_create(self, path: str) -> Any:
        """Load a workbook, creating a new one if the file does not exist."""
        resolved = self._resolve(path)
        if resolved.exists():
            return load_workbook(str(resolved))
        return Workbook()

    @staticmethod
    def _sheet(wb: Any, name: Optional[str]):
        if name:
            if name not in wb.sheetnames:
                raise ValueError(
                    f"Sheet not found: {name} (available: {', '.join(wb.sheetnames)})"
                )
            return wb[name]
        return wb.active

    @staticmethod
    def _parse_cell(cell_ref: str) -> Any:
        """Parse a cell reference like 'B3' into (row, column) integers."""
        match = re.fullmatch(r"\s*([A-Za-z]+)(\d+)\s*", str(cell_ref))
        if not match:
            raise ValueError(f"Invalid cell reference: {cell_ref}")
        col = column_index_from_string(match.group(1).upper())
        row = int(match.group(2))
        if row < 1:
            raise ValueError(f"Invalid row in cell reference: {cell_ref}")
        return row, col

    @staticmethod
    def _cell_value(value: Any) -> Any:
        """Auto-detect numbers and booleans from string input."""
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        text = str(value).strip()
        if text == "":
            return ""
        lowered = text.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if re.fullmatch(r"[+-]?\d+", text) and not re.fullmatch(r"[+-]?0\d+", text):
            try:
                return int(text)
            except ValueError:
                return value
        try:
            return float(text)
        except ValueError:
            return value

    @staticmethod
    def _hex(color: str) -> str:
        return str(color).strip().lstrip("#").upper()

    @staticmethod
    def _jsonable(value: Any) -> Any:
        """Convert openpyxl cell values to JSON-friendly types."""
        if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
            return value.isoformat()
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    # ------------------------------------------------------------------ #
    # Workbook lifecycle / reading
    # ------------------------------------------------------------------ #
    def create(
        self,
        path: str,
        sheets: Optional[List[str]] = None,
        headers: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new Excel (.xlsx) spreadsheet."""
        err = self._unavailable()
        if err:
            return err
        try:
            if not path or not str(path).strip():
                return {"success": False, "error": "A path is required."}

            resolved = self._resolve(path)
            wb = Workbook()

            if sheets:
                first = wb.active
                first.title = str(sheets[0])
                for name in sheets[1:]:
                    wb.create_sheet(str(name))

            if headers:
                ws = wb.active
                ws.append(list(headers))
                for cell in ws[1]:
                    cell.font = Font(bold=True)

            self._save(wb, resolved)
            return {
                "success": True,
                "path": str(resolved),
                "sheets": wb.sheetnames,
                "message": f"Created workbook at {resolved}",
            }
        except Exception as e:
            return {"success": False, "error": f"Create failed: {e}"}

    def read(
        self,
        path: str,
        sheet: Optional[str] = None,
        cell_range: Optional[str] = None,
        max_rows: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Read rows from a spreadsheet."""
        err = self._unavailable()
        if err:
            return err
        try:
            wb = self._load(path, data_only=False)
            resolved = self._resolve(path)
            ws = self._sheet(wb, sheet)

            limit = max_rows if max_rows is not None else self.max_rows
            rows: List[List[Any]] = []

            if cell_range:
                for row in ws[cell_range]:
                    if limit is not None and len(rows) >= limit:
                        break
                    rows.append([self._jsonable(c.value) for c in row])
            else:
                for row in ws.iter_rows(values_only=True):
                    if limit is not None and len(rows) >= limit:
                        break
                    rows.append([self._jsonable(v) for v in row])
                # Trim fully-empty trailing rows
                while rows and all(v in ("", None) for v in rows[-1]):
                    rows.pop()

            wb.close()
            col_count = max((len(r) for r in rows), default=0)
            return {
                "success": True,
                "path": str(resolved),
                "sheet": ws.title,
                "rows": rows,
                "row_count": len(rows),
                "col_count": col_count,
            }
        except Exception as e:
            return {"success": False, "error": f"Read failed: {e}"}

    def info(self, path: str) -> Dict[str, Any]:
        """Get workbook metadata: sheets, dimensions, cell counts."""
        err = self._unavailable()
        if err:
            return err
        try:
            wb = self._load(path)
            resolved = self._resolve(path)

            sheets = []
            for name in wb.sheetnames:
                ws = wb[name]
                sheets.append({
                    "name": name,
                    "max_row": ws.max_row,
                    "max_column": ws.max_column,
                    "dimensions": ws.dimensions,
                    "cell_count": (ws.max_row or 0) * (ws.max_column or 0),
                })

            props = wb.properties
            wb.close()
            return {
                "success": True,
                "path": str(resolved),
                "sheet_count": len(sheets),
                "sheets": sheets,
                "title": props.title,
                "creator": props.creator,
                "size_bytes": resolved.stat().st_size if resolved.exists() else 0,
            }
        except Exception as e:
            return {"success": False, "error": f"Info failed: {e}"}

    # ------------------------------------------------------------------ #
    # Writing
    # ------------------------------------------------------------------ #
    def write_cell(
        self,
        path: str,
        cell: str,
        value: Any,
        sheet: Optional[str] = None,
        create_file: bool = True,
    ) -> Dict[str, Any]:
        """Write a single value to a cell (e.g. 'B3')."""
        err = self._unavailable()
        if err:
            return err
        try:
            resolved = self._resolve(path)
            if not resolved.exists():
                if not create_file:
                    return {"success": False, "error": f"File not found: {resolved}"}
                wb = Workbook()
            else:
                wb = load_workbook(str(resolved))

            ws = self._sheet(wb, sheet)
            self._parse_cell(cell)  # validate
            ws[cell] = self._cell_value(value)

            self._save(wb, resolved)
            return {
                "success": True,
                "path": str(resolved),
                "sheet": ws.title,
                "cell": cell,
                "value": self._jsonable(ws[cell].value),
            }
        except Exception as e:
            return {"success": False, "error": f"Write failed: {e}"}

    def write_rows(
        self,
        path: str,
        rows: List[List[Any]],
        start_cell: str = "A1",
        sheet: Optional[str] = None,
        header: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Write a block of rows starting at a cell."""
        err = self._unavailable()
        if err:
            return err
        if not rows or not isinstance(rows, list):
            return {"success": False, "error": "'rows' must be a non-empty list."}
        try:
            resolved = self._resolve(path)
            wb = load_workbook(str(resolved)) if resolved.exists() else Workbook()
            ws = self._sheet(wb, sheet)

            start_row, start_col = self._parse_cell(start_cell)
            written = 0
            current_row = start_row

            if header:
                for j, value in enumerate(header):
                    cell = ws.cell(row=current_row, column=start_col + j,
                                   value=self._cell_value(value))
                    cell.font = Font(bold=True)
                current_row += 1

            max_cols = 0
            for row in rows:
                if not isinstance(row, list):
                    continue
                for j, value in enumerate(row):
                    ws.cell(row=current_row, column=start_col + j,
                            value=self._cell_value(value))
                max_cols = max(max_cols, len(row))
                current_row += 1
                written += 1

            self._save(wb, resolved)
            return {
                "success": True,
                "path": str(resolved),
                "sheet": ws.title,
                "rows_written": written,
                "cols_written": max_cols,
                "start_cell": start_cell,
            }
        except Exception as e:
            return {"success": False, "error": f"Write rows failed: {e}"}

    def set_formula(
        self, path: str, cell: str, formula: str, sheet: Optional[str] = None
    ) -> Dict[str, Any]:
        """Set a formula in a cell, e.g. '=SUM(A1:A10)'."""
        err = self._unavailable()
        if err:
            return err
        try:
            resolved = self._resolve(path)
            if not resolved.exists():
                return {"success": False, "error": f"File not found: {resolved}"}
            wb = load_workbook(str(resolved))
            ws = self._sheet(wb, sheet)

            self._parse_cell(cell)  # validate
            expression = str(formula)
            if not expression.startswith("="):
                expression = "=" + expression
            ws[cell] = expression

            self._save(wb, resolved)
            return {"success": True, "path": str(resolved), "cell": cell,
                    "formula": expression}
        except Exception as e:
            return {"success": False, "error": f"Set formula failed: {e}"}

    # ------------------------------------------------------------------ #
    # Formatting
    # ------------------------------------------------------------------ #
    def format(
        self,
        path: str,
        cell_range: str,
        sheet: Optional[str] = None,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        font_color: Optional[str] = None,
        fill: Optional[str] = None,
        align: Optional[str] = None,
        font_size: Optional[float] = None,
        number_format: Optional[str] = None,
        column_width: Optional[float] = None,
        wrap: Optional[bool] = None,
        border: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Format a cell range (bold, colors, widths, number formats)."""
        err = self._unavailable()
        if err:
            return err
        try:
            wb = self._load(path)
            resolved = self._resolve(path)
            ws = self._sheet(wb, sheet)

            min_col, min_row, max_col, max_row = range_boundaries(cell_range)

            # Horizontal alignment / wrapping
            horizontal = None
            wrap_text = wrap
            if align:
                key = str(align).strip().lower()
                if key == "wrap":
                    wrap_text = True
                elif key in ("left", "center", "right", "justify"):
                    horizontal = key
                else:
                    raise ValueError(
                        f"Invalid alignment '{align}'. "
                        "Use left, center, right, justify or wrap."
                    )

            font_kwargs: Dict[str, Any] = {}
            if bold is not None:
                font_kwargs["bold"] = bold
            if italic is not None:
                font_kwargs["italic"] = italic
            if font_color:
                font_kwargs["color"] = self._hex(font_color)
            if font_size is not None:
                font_kwargs["size"] = float(font_size)

            fill_obj = PatternFill(fill_type="solid", fgColor=self._hex(fill)) if fill else None
            thin = Side(style="thin")
            border_obj = Border(left=thin, right=thin, top=thin, bottom=thin) if border else None

            formatted = 0
            for row in ws.iter_rows(
                min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col
            ):
                for cell in row:
                    if font_kwargs:
                        cell.font = Font(**{**self._font_attrs(cell), **font_kwargs})
                    if fill_obj is not None:
                        cell.fill = fill_obj
                    if horizontal or wrap_text is not None:
                        cell.alignment = Alignment(
                            horizontal=horizontal
                            if horizontal is not None
                            else (cell.alignment.horizontal),
                            vertical=cell.alignment.vertical,
                            wrap_text=wrap_text
                            if wrap_text is not None
                            else cell.alignment.wrap_text,
                        )
                    if number_format:
                        cell.number_format = number_format
                    if border_obj is not None:
                        cell.border = border_obj
                    formatted += 1

            if column_width:
                for col in range(min_col, max_col + 1):
                    ws.column_dimensions[get_column_letter(col)].width = float(column_width)

            self._save(wb, resolved)
            return {
                "success": True,
                "path": str(resolved),
                "sheet": ws.title,
                "range": cell_range,
                "cells_formatted": formatted,
            }
        except Exception as e:
            return {"success": False, "error": f"Format failed: {e}"}

    @staticmethod
    def _font_attrs(cell: Any) -> Dict[str, Any]:
        """Capture the existing font attributes of a cell so they are preserved."""
        font = cell.font
        attrs: Dict[str, Any] = {}
        if font.bold is not None:
            attrs["bold"] = font.bold
        if font.italic is not None:
            attrs["italic"] = font.italic
        if font.underline is not None:
            attrs["underline"] = font.underline
        if font.size is not None:
            attrs["size"] = font.size
        if font.name is not None:
            attrs["name"] = font.name
        try:
            if font.color is not None and font.color.type == "rgb":
                attrs["color"] = font.color.rgb
        except Exception:
            pass
        return attrs

    # ------------------------------------------------------------------ #
    # Querying / analysis
    # ------------------------------------------------------------------ #
    def find(
        self,
        path: str,
        query: str,
        sheet: Optional[str] = None,
        max_results: int = 100,
    ) -> Dict[str, Any]:
        """Search for a value across a sheet."""
        err = self._unavailable()
        if err:
            return err
        try:
            wb = self._load(path, data_only=True)
            resolved = self._resolve(path)
            ws = self._sheet(wb, sheet)

            needle = str(query).lower()
            results: List[Dict[str, Any]] = []
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is None:
                        continue
                    if needle in str(cell.value).lower():
                        results.append({
                            "cell": cell.coordinate,
                            "row": cell.row,
                            "column": get_column_letter(cell.column),
                            "value": self._jsonable(cell.value),
                        })
                        if len(results) >= max_results:
                            break
                if len(results) >= max_results:
                    break

            wb.close()
            return {
                "success": True,
                "path": str(resolved),
                "sheet": ws.title,
                "query": query,
                "results": results,
                "count": len(results),
            }
        except Exception as e:
            return {"success": False, "error": f"Find failed: {e}"}

    def stats(
        self,
        path: str,
        column: str,
        sheet: Optional[str] = None,
        header: bool = True,
    ) -> Dict[str, Any]:
        """Compute count/sum/min/max/average for a numeric column."""
        err = self._unavailable()
        if err:
            return err
        try:
            wb = self._load(path, data_only=True)
            resolved = self._resolve(path)
            ws = self._sheet(wb, sheet)

            col_index = column_index_from_string(str(column).strip().upper())
            values: List[float] = []
            start = 2 if header else 1
            for row in range(start, (ws.max_row or 0) + 1):
                value = ws.cell(row=row, column=col_index).value
                if isinstance(value, bool) or value is None:
                    continue
                if isinstance(value, (int, float)):
                    values.append(float(value))
                elif isinstance(value, str):
                    try:
                        values.append(float(value.strip()))
                    except ValueError:
                        continue

            wb.close()
            count = len(values)
            return {
                "success": True,
                "path": str(resolved),
                "sheet": ws.title,
                "column": str(column).upper(),
                "count": count,
                "sum": sum(values) if values else 0,
                "min": min(values) if values else None,
                "max": max(values) if values else None,
                "average": (sum(values) / count) if count else None,
            }
        except Exception as e:
            return {"success": False, "error": f"Stats failed: {e}"}

    # ------------------------------------------------------------------ #
    # Sheet management / conversion
    # ------------------------------------------------------------------ #
    def add_sheet(self, path: str, name: str) -> Dict[str, Any]:
        """Add a new sheet to a workbook."""
        err = self._unavailable()
        if err:
            return err
        try:
            if not name or not str(name).strip():
                return {"success": False, "error": "A sheet name is required."}
            wb = self._load(path)
            resolved = self._resolve(path)

            if name in wb.sheetnames:
                return {"success": False, "error": f"Sheet already exists: {name}"}

            wb.create_sheet(str(name))
            self._save(wb, resolved)
            return {"success": True, "path": str(resolved), "sheets": wb.sheetnames}
        except Exception as e:
            return {"success": False, "error": f"Add sheet failed: {e}"}

    def delete_sheet(self, path: str, name: str) -> Dict[str, Any]:
        """Delete a sheet from a workbook."""
        err = self._unavailable()
        if err:
            return err
        try:
            wb = self._load(path)
            resolved = self._resolve(path)

            if name not in wb.sheetnames:
                return {"success": False, "error": f"Sheet not found: {name}"}
            if len(wb.sheetnames) <= 1:
                return {
                    "success": False,
                    "error": "Cannot delete the only sheet in a workbook.",
                }

            del wb[name]
            self._save(wb, resolved)
            return {"success": True, "path": str(resolved), "sheets": wb.sheetnames}
        except Exception as e:
            return {"success": False, "error": f"Delete sheet failed: {e}"}

    def to_csv(
        self,
        path: str,
        out_path: Optional[str] = None,
        sheet: Optional[str] = None,
        delimiter: str = ",",
    ) -> Dict[str, Any]:
        """Export a spreadsheet sheet to CSV."""
        err = self._unavailable()
        if err:
            return err
        try:
            wb = self._load(path, data_only=True)
            resolved = self._resolve(path)
            ws = self._sheet(wb, sheet)

            if out_path:
                target = self._resolve(out_path)
            else:
                target = resolved.with_suffix(".csv")

            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=delimiter or ",")
                for row in ws.iter_rows(values_only=True):
                    writer.writerow(["" if v is None else self._jsonable(v) for v in row])

            wb.close()
            return {"success": True, "path": str(resolved), "out_path": str(target)}
        except Exception as e:
            return {"success": False, "error": f"To CSV failed: {e}"}

    def csv_to_excel(
        self,
        csv_path: str,
        out_path: Optional[str] = None,
        sheet: str = "Sheet1",
        delimiter: str = ",",
        header: bool = True,
    ) -> Dict[str, Any]:
        """Convert a CSV file into an Excel workbook."""
        err = self._unavailable()
        if err:
            return err
        try:
            source = self._resolve(csv_path)
            if not source.exists():
                return {"success": False, "error": f"CSV file not found: {source}"}

            target = self._resolve(out_path) if out_path else source.with_suffix(".xlsx")

            wb = Workbook()
            ws = wb.active
            ws.title = str(sheet or "Sheet1")

            with open(source, "r", newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f, delimiter=delimiter or ",")
                for r, row in enumerate(reader, start=1):
                    for c, value in enumerate(row, start=1):
                        ws.cell(row=r, column=c, value=self._cell_value(value))
                    if header and r == 1:
                        for cell in ws[1]:
                            cell.font = Font(bold=True)

            self._save(wb, target)
            return {"success": True, "path": str(target), "sheet": ws.title}
        except Exception as e:
            return {"success": False, "error": f"CSV to Excel failed: {e}"}

    # ------------------------------------------------------------------ #
    # Internal save
    # ------------------------------------------------------------------ #
    @staticmethod
    def _save(wb: Any, resolved: Path) -> None:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(resolved))

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
                "excel_create",
                "Create a new Excel (.xlsx) spreadsheet",
                {
                    "path": prop("string", "Output file path ending in .xlsx"),
                    "sheets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of sheet names to create",
                    },
                    "headers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional header row for the first sheet (bold)",
                    },
                },
                ["path"],
            ),
            self._schema(
                "excel_read",
                "Read rows from a spreadsheet",
                {
                    "path": prop("string", "Path to .xlsx file"),
                    "sheet": prop("string", "Sheet name (default: active sheet)"),
                    "cell_range": prop("string", "A1 range like 'A1:D20'"),
                    "max_rows": prop("integer", "Maximum rows to return"),
                },
                ["path"],
            ),
            self._schema(
                "excel_info",
                "Get workbook metadata: sheets, dimensions, cell counts",
                {"path": prop("string", "Path to .xlsx file")},
                ["path"],
            ),
            self._schema(
                "excel_write",
                "Write a single value to a cell (e.g. 'B3')",
                {
                    "path": prop("string", "Path to .xlsx file (created if missing)"),
                    "cell": prop("string", "Cell reference like 'B3'"),
                    "value": prop("string", "Value to write (numbers/booleans are auto-detected)"),
                    "sheet": prop("string", "Sheet name (default: active sheet)"),
                    "create_file": prop("boolean", "Create the file if missing (default true)", default=True),
                },
                ["path", "cell", "value"],
            ),
            self._schema(
                "excel_write_rows",
                "Write a block of rows starting at a cell",
                {
                    "path": prop("string", "Path to .xlsx file (created if missing)"),
                    "rows": {
                        "type": "array",
                        "items": {"type": "array"},
                        "description": "Rows of values (numbers/strings/booleans)",
                    },
                    "start_cell": prop("string", "Top-left cell, default 'A1'", default="A1"),
                    "sheet": prop("string", "Sheet name (default: active sheet)"),
                    "header": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional header row (bold) written above the data",
                    },
                },
                ["path", "rows"],
            ),
            self._schema(
                "excel_format",
                "Format a cell range (bold, colors, widths, number formats)",
                {
                    "path": prop("string", "Path to .xlsx file"),
                    "cell_range": prop("string", "Range like 'A1:D10' or single cell 'A1'"),
                    "sheet": prop("string", "Sheet name (default: active sheet)"),
                    "bold": prop("boolean", "Bold text"),
                    "italic": prop("boolean", "Italic text"),
                    "font_color": prop("string", "Hex color like 'FF0000' or '#FF0000'"),
                    "fill": prop("string", "Background color, Hex color like 'FF0000' or '#FF0000'"),
                    "align": prop(
                        "string", "Alignment",
                        enum=["left", "center", "right", "justify", "wrap"],
                    ),
                    "font_size": prop("number", "Font size in points"),
                    "number_format": prop("string", "Excel format e.g. '#,##0.00', '0.00%', 'yyyy-mm-dd'"),
                    "column_width": prop("number", "Column width for the range"),
                    "wrap": prop("boolean", "Enable text wrapping"),
                    "border": prop("boolean", "Add thin borders"),
                },
                ["path", "cell_range"],
            ),
            self._schema(
                "excel_formula",
                "Set a formula in a cell, e.g. '=SUM(A1:A10)'",
                {
                    "path": prop("string", "Path to .xlsx file"),
                    "cell": prop("string", "Cell reference like 'E1'"),
                    "formula": prop("string", "Formula, '=' optional"),
                    "sheet": prop("string", "Sheet name (default: active sheet)"),
                },
                ["path", "cell", "formula"],
            ),
            self._schema(
                "excel_find",
                "Search for a value across a sheet",
                {
                    "path": prop("string", "Path to .xlsx file"),
                    "query": prop("string", "Text to search for"),
                    "sheet": prop("string", "Sheet name (default: active sheet)"),
                    "max_results": prop("integer", "Maximum results", default=100),
                },
                ["path", "query"],
            ),
            self._schema(
                "excel_stats",
                "Compute count/sum/min/max/average for a numeric column",
                {
                    "path": prop("string", "Path to .xlsx file"),
                    "column": prop("string", "Column letter like 'B'"),
                    "sheet": prop("string", "Sheet name (default: active sheet)"),
                    "header": prop("boolean", "First row is a header (skip it)", default=True),
                },
                ["path", "column"],
            ),
            self._schema(
                "excel_add_sheet",
                "Add a new sheet to a workbook",
                {
                    "path": prop("string", "Path to .xlsx file"),
                    "name": prop("string", "New sheet name"),
                },
                ["path", "name"],
            ),
            self._schema(
                "excel_delete_sheet",
                "Delete a sheet from a workbook",
                {
                    "path": prop("string", "Path to .xlsx file"),
                    "name": prop("string", "Sheet name to delete"),
                },
                ["path", "name"],
            ),
            self._schema(
                "excel_to_csv",
                "Export a spreadsheet sheet to CSV",
                {
                    "path": prop("string", "Path to .xlsx file"),
                    "out_path": prop("string", "Output CSV path (default: same name .csv)"),
                    "sheet": prop("string", "Sheet name (default: active sheet)"),
                    "delimiter": prop("string", "Delimiter, default ','", default=","),
                },
                ["path"],
            ),
            self._schema(
                "csv_to_excel",
                "Convert a CSV file into an Excel workbook",
                {
                    "csv_path": prop("string", "Path to the CSV file"),
                    "out_path": prop("string", "Output .xlsx path (default: same name .xlsx)"),
                    "sheet": prop("string", "Sheet name", default="Sheet1"),
                    "delimiter": prop("string", "Delimiter, default ','", default=","),
                    "header": prop("boolean", "First row is a header (bold)", default=True),
                },
                ["csv_path"],
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
