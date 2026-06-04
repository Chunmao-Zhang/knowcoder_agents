"""Excel 到 Python class 生成工具实现。

作用：
- 从 Excel 表结构/指标元数据生成 Python class 文件。
- 自动推断字段名、Python 类型、字段注释和简单外键关系，并可对生成文件执行 `py_compile`。
- 输出面向 `/outputs/otology_skill/...` 的可复用模型代码，而不是直接修改原始数据。

主要输入：
- `excel_path`: Excel 文件路径，可为仓库相对路径或绝对路径。
- `output_dir`: 生成 Python 文件的目标目录。
- `sheet_names`: 可选 sheet 名列表；为空时处理全部可识别 sheet。
- `field_comment_overrides`: 可选字段注释覆盖，供 skill 把大模型判断后的注释传入工具。
- `compile_check`: 是否对生成的 `.py` 文件执行编译检查。

主要输出：
- JSON/dict，包含 `table_count`、每张表的字段清单、推断关系、`generated_files` 和 `compile_results`。
"""

from __future__ import annotations

import json
import py_compile
import re
from pathlib import Path
from typing import Any

from .inspect_excel_schema import (
    clean_cell,
    class_name,
    infer_python_type,
    normalize_key,
    read_workbook,
    snake_name,
    table_name_from_rows,
    unique_name,
)
from .paths import ensure_output_dir, resolve_path


def _quote(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _metadata_header_indexes(header: list[str]) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for idx, name in enumerate(header):
        key = normalize_key(name)
        if key and key not in indexes:
            indexes[key] = idx
    return indexes


def _is_metadata_sheet(indexes: dict[str, int]) -> bool:
    return "field_name" in indexes or {"metric_name", "unit", "description"} & set(indexes)


def _truthy(value: Any) -> bool:
    return str(value).strip().upper() in {"Y", "YES", "TRUE", "1", "是", "√", "✓"}


def _source_value(row: list[str], indexes: dict[str, int], key: str) -> str:
    idx = indexes.get(key)
    if idx is None or idx >= len(row):
        return ""
    return clean_cell(row[idx])


def _semantic_comment(field_name: str, original_name: str = "", unit: str = "", description: str = "") -> str:
    desc = clean_cell(description)
    if desc and desc.lower() != "nan" and desc.lower().replace("_", " ") != field_name.replace("_", " "):
        return desc
    original = clean_cell(original_name)
    if original and original.lower() != field_name.lower():
        base = f"Source metric: {original}"
        return f"{base}; unit: {unit}" if unit else base
    if field_name == "id":
        return "Auto-incremented surrogate primary key."
    if field_name.endswith(("_id", "_rid")):
        return "Foreign reference to a related business entity."
    if field_name.endswith("_rate") or "rate" in field_name:
        return "Ratio or percentage metric used for business analysis."
    if any(token in field_name for token in ("amount", "quantity", "count", "total", "metric", "score")):
        return "Quantitative business measure used for analysis."
    if "date" in field_name or "time" in field_name:
        return "Time attribute associated with this record."
    return f"Business attribute for {field_name.replace('_', ' ')}."


def _choose_header_row(rows: list[list[str]]) -> int:
    best_idx = 0
    best_score = -1
    for idx, row in enumerate(rows[:12]):
        non_empty = [clean_cell(cell) for cell in row if clean_cell(cell)]
        if len(non_empty) < 2:
            continue
        keys = {normalize_key(cell) for cell in non_empty}
        score = len(non_empty) + 5 * len(keys & {"field_name", "metric_name", "data_type", "unit", "description"})
        if score > best_score:
            best_idx = idx
            best_score = score
    return best_idx


def _lookup_name_override(
    overrides: dict[str, str],
    *,
    table_name: str,
    sheet_name: str,
    source_field: str,
    original_name: str,
) -> str:
    if not overrides:
        return ""
    candidates = [
        original_name,
        source_field,
        f"{table_name}.{original_name}",
        f"{table_name}.{source_field}",
        f"{sheet_name}.{original_name}",
        f"{sheet_name}.{source_field}",
    ]
    normalized = {str(key).strip(): str(value).strip() for key, value in overrides.items() if str(value).strip()}
    for key in candidates:
        if key and key in normalized:
            return normalized[key]
    return ""


def _fields_from_sheet(
    sheet: dict[str, Any],
    field_name_overrides: dict[str, str] | None = None,
) -> tuple[str, str, list[dict[str, Any]]]:
    rows = sheet["rows"]
    table_name = table_name_from_rows(sheet["sheet_name"], rows)
    if not rows:
        return table_name, sheet["sheet_name"], []

    header_idx = _choose_header_row(rows)
    header = rows[header_idx]
    data_rows = rows[header_idx + 1 :]
    indexes = _metadata_header_indexes(header)
    fields: list[dict[str, Any]] = []
    used: set[str] = set()

    if _is_metadata_sheet(indexes):
        for row in data_rows:
            if not any(clean_cell(cell) for cell in row):
                continue
            source_field = _source_value(row, indexes, "field_name")
            original_name = (
                _source_value(row, indexes, "metric_name")
                or _source_value(row, indexes, "description")
                or source_field
            )
            if not source_field and not original_name:
                continue
            override_name = _lookup_name_override(
                field_name_overrides or {},
                table_name=table_name,
                sheet_name=sheet["sheet_name"],
                source_field=source_field,
                original_name=original_name,
            )
            field_name = unique_name(override_name or source_field or original_name, used, fallback=f"field_{len(fields) + 1}")
            unit = _source_value(row, indexes, "unit")
            data_type = _source_value(row, indexes, "data_type")
            description = _source_value(row, indexes, "description")
            py_type = infer_python_type([], unit=unit, data_type=data_type)
            fields.append({
                "field_name": field_name,
                "original_name": original_name,
                "python_type": py_type,
                "data_type": data_type,
                "unit": unit,
                "description": description,
                "is_primary_key": _truthy(_source_value(row, indexes, "is_primary_key")) or field_name == "id",
                "is_not_null": _truthy(_source_value(row, indexes, "is_not_null")),
                "comment": _semantic_comment(field_name, original_name=original_name, unit=unit, description=description),
            })
        return table_name, sheet["sheet_name"], fields

    for idx, original in enumerate(header):
        original = clean_cell(original) or f"column_{idx + 1}"
        samples = [row[idx] for row in data_rows if idx < len(row)]
        override_name = _lookup_name_override(
            field_name_overrides or {},
            table_name=table_name,
            sheet_name=sheet["sheet_name"],
            source_field=original,
            original_name=original,
        )
        field_name = unique_name(override_name or original, used, fallback=f"field_{idx + 1}")
        fields.append({
            "field_name": field_name,
            "original_name": original,
            "python_type": infer_python_type(samples),
            "data_type": "",
            "unit": "",
            "description": "",
            "is_primary_key": field_name == "id",
            "is_not_null": False,
            "comment": _semantic_comment(field_name, original_name=original),
        })
    return table_name, sheet["sheet_name"], fields


def _detect_relationships(tables: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    rels: dict[str, list[dict[str, str]]] = {table: [] for table in tables}
    table_names = list(tables)
    for table_name, meta in tables.items():
        for field in meta["fields"]:
            fname = field["field_name"]
            for suffix in ("_id", "_rid", "_ref", "_fk", "_key"):
                if not fname.endswith(suffix):
                    continue
                base = fname[: -len(suffix)]
                for target in table_names:
                    if target == table_name:
                        continue
                    if target == base or target.endswith(f"_{base}") or base in target:
                        rels[table_name].append({
                            "field": fname,
                            "references_table": target,
                            "references_field": "id",
                            "type": "many-to-one",
                            "confidence": "name-suffix",
                        })
                        break
    return rels


def _apply_comment_overrides(tables: dict[str, dict[str, Any]], overrides: dict[str, str]) -> None:
    """Apply skill-provided comments without making the tool call an LLM itself."""

    if not overrides:
        return
    normalized = {str(key).strip(): str(value).strip() for key, value in overrides.items() if str(value).strip()}
    for table_name, meta in tables.items():
        sheet_name = str(meta.get("sheet_name") or "")
        for field in meta.get("fields", []):
            field_name = str(field.get("field_name") or "")
            original_name = str(field.get("original_name") or "")
            candidates = [
                field_name,
                original_name,
                f"{table_name}.{field_name}",
                f"{table_name}.{original_name}",
                f"{sheet_name}.{field_name}",
                f"{sheet_name}.{original_name}",
            ]
            for key in candidates:
                if key in normalized:
                    field["comment"] = normalized[key]
                    break


def _render_dataclass(table_name: str, sheet_name: str, fields: list[dict[str, Any]]) -> str:
    cls = class_name(table_name)
    lines = [
        '"""Generated dataclass model from Excel table metadata."""',
        "",
        "from dataclasses import dataclass",
        "from typing import Optional",
        "import datetime",
        "",
        "",
        "@dataclass",
        f"class {cls}:",
        f"    \"\"\"{sheet_name} - generated business table model.\"\"\"",
        "",
    ]
    if not fields:
        lines.append("    pass")
    for field in fields:
        py_type = field["python_type"]
        if py_type == "datetime":
            py_type = "datetime.datetime"
        comment = str(field.get("comment") or "").replace("\n", " ")
        lines.append(f"    {field['field_name']}: Optional[{py_type}] = None  # {comment}")
    return "\n".join(lines) + "\n"


def _render_init(tables: dict[str, dict[str, Any]]) -> str:
    lines = []
    for table_name in tables:
        lines.append(f"from .{table_name} import {class_name(table_name)}")
    lines.append("")
    lines.append("__all__ = [")
    for table_name in tables:
        lines.append(f"    {_quote(class_name(table_name))},")
    lines.append("]")
    return "\n".join(lines) + "\n"


def generate_python_models_from_excel(
    excel_path: str,
    output_dir: str,
    sheet_names: list[str] | None = None,
    field_name_overrides: dict[str, str] | None = None,
    field_comment_overrides: dict[str, str] | None = None,
    compile_check: bool = True,
) -> dict[str, Any]:
    """Generate Python class files from an Excel workbook."""

    workbook_path = resolve_path(excel_path)
    out_dir = ensure_output_dir(output_dir)
    selected = {name for name in sheet_names or [] if name}
    sheets = read_workbook(workbook_path, max_rows_per_sheet=None)

    tables: dict[str, dict[str, Any]] = {}
    for sheet in sheets:
        if selected and sheet["sheet_name"] not in selected:
            continue
        table_name, sheet_name, fields = _fields_from_sheet(sheet, field_name_overrides=field_name_overrides or {})
        if not fields:
            continue
        original = table_name
        suffix = 2
        while table_name in tables:
            table_name = f"{original}_{suffix}"
            suffix += 1
        tables[table_name] = {"sheet_name": sheet_name, "fields": fields}

    _apply_comment_overrides(tables, field_comment_overrides or {})
    relationships = _detect_relationships(tables)
    generated_files: list[str] = []

    for table_name, meta in tables.items():
        code = _render_dataclass(table_name, meta["sheet_name"], meta["fields"])
        path = out_dir / f"{table_name}.py"
        path.write_text(code, encoding="utf-8")
        generated_files.append(str(path))

    init_path = out_dir / "__init__.py"
    init_path.write_text(_render_init(tables), encoding="utf-8")
    generated_files.append(str(init_path))

    compile_results = []
    if compile_check:
        for file_path in generated_files:
            if not file_path.endswith(".py"):
                continue
            try:
                py_compile.compile(file_path, doraise=True)
                compile_results.append({"file": file_path, "ok": True})
            except Exception as exc:
                compile_results.append({"file": file_path, "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    return {
        "excel_path": str(workbook_path),
        "output_dir": str(out_dir),
        "model_style": "python_class",
        "field_name_override_count": len(field_name_overrides or {}),
        "comment_override_count": len(field_comment_overrides or {}),
        "table_count": len(tables),
        "tables": [
            {
                "table_name": table_name,
                "class_name": class_name(table_name),
                "sheet_name": meta["sheet_name"],
                "field_count": len(meta["fields"]),
                "fields": meta["fields"],
                "relationships": relationships.get(table_name, []),
            }
            for table_name, meta in tables.items()
        ],
        "generated_files": generated_files,
        "compile_results": compile_results,
    }


def generate_python_models_from_excel_json(**kwargs: Any) -> str:
    return json.dumps(generate_python_models_from_excel(**kwargs), ensure_ascii=False, indent=2)
