"""Excel 结构检查工具实现。

作用：
- 读取 `.xlsx` 工作簿，识别 sheet、表名候选、表头行、字段名、字段类型和样例值。
- 不依赖 `openpyxl`，直接用标准库解析 Excel zip/XML，适合在轻量环境中运行。

主要输入：
- `excel_path`: Excel 文件路径，可为仓库相对路径或绝对路径。
- `sheet_names`: 可选 sheet 名列表；为空时检查全部 sheet。
- `max_rows`: 每个 sheet 最多采样多少行。
- `max_samples`: 每列最多返回多少个样例值。

主要输出：
- JSON/dict，包含 `sheet_count`、`inspected_sheet_count` 和每个 sheet 的
  `table_name_candidate`、`class_name_candidate`、`header_row_index`、`columns`、`sample_rows`。
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .paths import DATA_ROOT, resolve_path


MAIN_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
OFFICE_REL_NS = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}

# Default generation preserves uploaded business names. Add explicit reusable
# translations in data/otology_skill/config/term_map.json when a project wants them.
TERM_MAP: dict[str, str] = {}
_TERM_MAP_CACHE: dict[str, str] | None = None

PY_RESERVED = {
    "False",
    "None",
    "True",
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
}


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def active_term_map() -> dict[str, str]:
    """Return optional user-provided business term mappings."""

    global _TERM_MAP_CACHE
    if _TERM_MAP_CACHE is not None:
        return _TERM_MAP_CACHE
    merged = dict(TERM_MAP)
    custom_path = DATA_ROOT / "config" / "term_map.json"
    if custom_path.exists():
        try:
            raw = json.loads(custom_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key, value in raw.items():
                    key_text = clean_cell(key)
                    value_text = clean_cell(value)
                    if key_text and value_text:
                        merged[key_text] = value_text
        except Exception:
            pass
    _TERM_MAP_CACHE = merged
    return merged


def column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper() or "A"
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return value - 1


def normalize_key(value: str) -> str:
    text = str(value).strip().lower()
    mapped = {
        "指标字段": "metric_name",
        "字段名": "field_name",
        "字段名称": "field_name",
        "列名": "field_name",
        "属性名": "field_name",
        "英文字段名": "field_name",
        "字段英文名": "field_name",
        "数据类型": "data_type",
        "字段类型": "data_type",
        "类型": "data_type",
        "单位": "unit",
        "说明": "description",
        "备注": "description",
        "描述": "description",
        "注释": "description",
        "表名": "table_name",
        "英文表名": "table_name",
        "是否主键": "is_primary_key",
        "主键": "is_primary_key",
        "是否非空": "is_not_null",
        "非空": "is_not_null",
    }.get(text)
    if mapped:
        return mapped
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text)).strip("_")


def snake_name(value: str, fallback: str = "field") -> str:
    text = clean_cell(value)
    for cn, en in sorted(active_term_map().items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(cn, f"_{en}_")
    name = re.sub(r"_+", "_", re.sub(r"\W+", "_", text, flags=re.UNICODE)).strip("_")
    if not name:
        name = fallback
    if not name.isidentifier():
        name = f"{fallback}_{name}"
    if not name.isidentifier():
        name = fallback
    if name in PY_RESERVED:
        name = f"{name}_field"
    return name


def class_name(value: str, fallback: str = "GeneratedModel") -> str:
    snake = snake_name(value, fallback="model")
    cls = "".join(part.capitalize() for part in snake.split("_") if part)
    if not cls:
        cls = fallback
    if not cls.isidentifier():
        cls = f"Model{cls}"
    return cls


def infer_python_type(values: list[str], unit: str = "", data_type: str = "") -> str:
    raw_type = normalize_key(data_type)
    if raw_type in {"int", "integer", "bigint", "smallint"} or "整数" in data_type:
        return "int"
    if raw_type in {"float", "double", "decimal", "numeric"} or "小数" in data_type or "浮点" in data_type:
        return "float"
    if raw_type in {"date", "datetime", "timestamp"} or "日期" in data_type or "时间" in data_type:
        return "datetime"
    if unit in {"%", "万元", "元", "户", "个", "GB", "TB"}:
        return "float"

    sample = [clean_cell(v) for v in values if clean_cell(v)]
    if not sample:
        return "str"
    numeric = 0
    integer = 0
    for item in sample[:30]:
        try:
            num = float(item.replace(",", ""))
        except ValueError:
            continue
        numeric += 1
        if num.is_integer():
            integer += 1
    if numeric >= max(1, len(sample[:30]) // 2):
        return "int" if integer == numeric else "float"
    return "str"


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for si in root.findall("m:si", MAIN_NS):
        values.append("".join(t.text or "" for t in si.findall(".//m:t", MAIN_NS)))
    return values


def _sheet_targets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    names = zf.namelist()
    if "xl/workbook.xml" not in names:
        return [
            (Path(name).stem, name)
            for name in sorted(names)
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        ]

    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rel_map: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in names:
        rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        for rel in rel_root.findall("r:Relationship", REL_NS):
            rid = rel.attrib.get("Id", "")
            target = rel.attrib.get("Target", "")
            if rid and target:
                rel_map[rid] = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall(".//m:sheets/m:sheet", MAIN_NS):
        name = sheet.attrib.get("name", "Sheet")
        rid = sheet.attrib.get(f"{{{OFFICE_REL_NS['r']}}}id", "")
        target = rel_map.get(rid)
        if target and target in names:
            sheets.append((name, target))
    if sheets:
        return sheets
    return [
        (Path(name).stem, name)
        for name in sorted(names)
        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
    ]


def _read_sheet_rows(zf: zipfile.ZipFile, sheet_path: str, shared: list[str], max_rows: int | None = None) -> list[list[str]]:
    root = ET.fromstring(zf.read(sheet_path))
    rows: list[list[str]] = []
    for row in root.findall(".//m:sheetData/m:row", MAIN_NS):
        values: dict[int, str] = {}
        for cell in row.findall("m:c", MAIN_NS):
            idx = column_index(cell.attrib.get("r", "A1"))
            cell_type = cell.attrib.get("t", "")
            value = ""
            if cell_type == "inlineStr":
                value = "".join(t.text or "" for t in cell.findall(".//m:t", MAIN_NS))
            else:
                v = cell.find("m:v", MAIN_NS)
                if v is not None and v.text is not None:
                    value = v.text
                    if cell_type == "s":
                        try:
                            value = shared[int(value)]
                        except Exception:
                            pass
            values[idx] = clean_cell(value)
        if values:
            rows.append([values.get(i, "") for i in range(max(values) + 1)])
        if max_rows is not None and len(rows) >= max_rows:
            break
    return rows


def read_workbook(path: str | Path, max_rows_per_sheet: int | None = None) -> list[dict[str, Any]]:
    """Read an XLSX workbook using only the standard library."""

    workbook_path = resolve_path(path)
    if not workbook_path.exists():
        raise FileNotFoundError(f"Excel file not found: {workbook_path}")
    with zipfile.ZipFile(workbook_path) as zf:
        shared = _read_shared_strings(zf)
        sheets = []
        for name, target in _sheet_targets(zf):
            sheets.append({
                "sheet_name": name,
                "sheet_path": target,
                "rows": _read_sheet_rows(zf, target, shared, max_rows=max_rows_per_sheet),
            })
    return sheets


def table_name_from_rows(sheet_name: str, rows: list[list[str]]) -> str:
    for row in rows[:5]:
        if not row:
            continue
        first = clean_cell(row[0])
        if first.startswith("表标识"):
            _, _, value = first.partition(":")
            value = value or first.partition("：")[2]
            if clean_cell(value):
                return snake_name(value, fallback="table")
    return snake_name(sheet_name, fallback="table")


def choose_header_row(rows: list[list[str]]) -> int:
    best_idx = 0
    best_score = -1
    for idx, row in enumerate(rows[:12]):
        non_empty = [clean_cell(cell) for cell in row if clean_cell(cell)]
        if len(non_empty) < 2:
            continue
        normalized = {normalize_key(cell) for cell in non_empty}
        score = len(non_empty)
        score += 5 * len(normalized & {"field_name", "metric_name", "data_type", "unit", "description"})
        if score > best_score:
            best_idx = idx
            best_score = score
    return best_idx


def unique_name(name: str, used: set[str], fallback: str = "field") -> str:
    candidate = snake_name(name, fallback=fallback)
    base = candidate
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def inspect_sheet(sheet: dict[str, Any], max_samples: int = 5) -> dict[str, Any]:
    rows = sheet["rows"]
    header_idx = choose_header_row(rows) if rows else 0
    header = rows[header_idx] if rows else []
    data_rows = rows[header_idx + 1 :] if rows else []
    used: set[str] = set()
    columns = []
    for idx, original in enumerate(header):
        original = clean_cell(original) or f"column_{idx + 1}"
        sample_values = [row[idx] for row in data_rows if idx < len(row) and clean_cell(row[idx])][:max_samples]
        columns.append({
            "index": idx + 1,
            "original_name": original,
            "normalized_key": normalize_key(original),
            "field_name": unique_name(original, used, fallback=f"field_{idx + 1}"),
            "python_type": infer_python_type(sample_values),
            "sample_values": sample_values,
        })
    table_name = table_name_from_rows(sheet["sheet_name"], rows)
    return {
        "sheet_name": sheet["sheet_name"],
        "table_name_candidate": table_name,
        "class_name_candidate": class_name(table_name),
        "header_row_index": header_idx + 1,
        "headers": header,
        "columns": columns,
        "sample_rows": rows[: max(0, min(len(rows), 8))],
    }


def inspect_excel_schema(
    excel_path: str,
    sheet_names: list[str] | None = None,
    max_rows: int = 30,
    max_samples: int = 5,
) -> dict[str, Any]:
    """Inspect workbook sheets and infer column/schema metadata."""

    workbook_path = resolve_path(excel_path)
    selected = {name for name in sheet_names or [] if name}
    sheets = read_workbook(workbook_path, max_rows_per_sheet=max(1, int(max_rows or 30)))
    inspected = []
    for sheet in sheets:
        if selected and sheet["sheet_name"] not in selected:
            continue
        inspected.append(inspect_sheet(sheet, max_samples=max(1, int(max_samples or 5))))
    return {
        "excel_path": str(workbook_path),
        "sheet_count": len(sheets),
        "inspected_sheet_count": len(inspected),
        "sheets": inspected,
    }


def inspect_excel_schema_json(**kwargs: Any) -> str:
    return json.dumps(inspect_excel_schema(**kwargs), ensure_ascii=False, indent=2)
