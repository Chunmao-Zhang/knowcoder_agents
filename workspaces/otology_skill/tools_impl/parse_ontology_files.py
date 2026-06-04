"""Python 本体文件解析工具实现。

作用：
- 使用 AST 解析一个或多个 Python ontology 文件，抽取 class 级元数据。
- 支持 dataclass、Pydantic BaseModel、普通带注解 class、以及 `__init__` 参数式 class。
- 为后续语义对齐、合并和报告生成提供结构化输入。

主要输入：
- `file_paths`: Python 文件路径列表，可为仓库相对路径或绝对路径。
- `include_source`: 是否返回完整 class 源码片段。默认关闭，避免大 case 反复读取超大工具结果。
- `field_limit`: 每个 class 返回的字段上限。默认 8；完整字段仍可在源文件中按需读取。

主要输出：
- JSON/dict，包含 `file_count`、`class_count`、`classes` 和 `errors`。
- 每个 class 记录包含 `class_name`、`docstring`、`bases`、`decorators`、`fields`、`methods`。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from .paths import resolve_path


class OntologyParser(ast.NodeVisitor):
    """AST parser for dataclass, Pydantic, plain, and __init__-style classes."""

    def __init__(self, source_file: Path):
        self.source_file = source_file
        self.source_lines: list[str] = []
        self.classes: list[dict[str, Any]] = []

    def parse(self) -> list[dict[str, Any]]:
        content = self.source_file.read_text(encoding="utf-8")
        self.source_lines = content.splitlines()
        tree = ast.parse(content, filename=str(self.source_file))
        self.visit(tree)
        return self.classes

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        class_info = {
            "source_file": str(self.source_file),
            "class_name": node.name,
            "docstring": ast.get_docstring(node),
            "bases": [self._unparse(base) for base in node.bases],
            "decorators": [self._decorator_name(dec) for dec in node.decorator_list],
            "fields": [],
            "methods": [],
            "raw_class_src": self._source_segment(node),
        }
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                class_info["fields"].append(self._parse_annotated_field(item))
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        class_info["fields"].append({
                            "name": target.id,
                            "type": "Any",
                            "default": self._value_repr(item.value),
                            "comment": self._inline_comment(item.lineno),
                        })
            elif isinstance(item, ast.FunctionDef):
                class_info["methods"].append(item.name)
                if item.name == "__init__":
                    class_info["fields"].extend(self._parse_init_fields(item))
        self.classes.append(class_info)
        self.generic_visit(node)

    def _parse_annotated_field(self, node: ast.AnnAssign) -> dict[str, Any]:
        assert isinstance(node.target, ast.Name)
        return {
            "name": node.target.id,
            "type": self._unparse(node.annotation),
            "default": self._value_repr(node.value) if node.value is not None else None,
            "comment": self._inline_comment(node.lineno),
        }

    def _parse_init_fields(self, node: ast.FunctionDef) -> list[dict[str, Any]]:
        fields = []
        defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + list(node.args.defaults)
        for arg, default in zip(node.args.args, defaults):
            if arg.arg == "self":
                continue
            fields.append({
                "name": arg.arg,
                "type": self._unparse(arg.annotation) if arg.annotation is not None else "Any",
                "default": self._value_repr(default) if default is not None else None,
                "comment": None,
            })
        return fields

    def _unparse(self, node: ast.AST | None) -> str:
        if node is None:
            return "Any"
        try:
            return ast.unparse(node)
        except Exception:
            return "Any"

    def _decorator_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Call):
            return self._unparse(node.func)
        return self._unparse(node)

    def _value_repr(self, node: ast.AST | None) -> str | None:
        if node is None:
            return None
        try:
            return ast.unparse(node)
        except Exception:
            return "..."

    def _inline_comment(self, line_no: int) -> str | None:
        if line_no < 1 or line_no > len(self.source_lines):
            return None
        line = self.source_lines[line_no - 1]
        if "#" not in line:
            return None
        comment = line.split("#", 1)[1].strip()
        return None if comment.startswith("type:") else comment

    def _source_segment(self, node: ast.ClassDef) -> str:
        if not self.source_lines:
            return ""
        start = node.lineno - 1
        end = node.end_lineno or node.lineno
        return "\n".join(self.source_lines[start:end])


def _trim_class(cls: dict[str, Any], *, include_source: bool, field_limit: int) -> dict[str, Any]:
    item = dict(cls)
    fields = [field for field in item.get("fields", []) or [] if isinstance(field, dict)]
    item["field_count"] = len(fields)
    if field_limit >= 0 and len(fields) > field_limit:
        item["fields"] = fields[:field_limit]
        item["truncated_field_count"] = len(fields) - field_limit
    else:
        item["fields"] = fields
        item["truncated_field_count"] = 0
    if not include_source:
        item.pop("raw_class_src", None)
    return item


def parse_ontology_files(
    file_paths: list[str],
    include_source: bool = False,
    field_limit: int = 8,
) -> dict[str, Any]:
    """Parse one or more Python ontology files."""

    classes: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    resolved_files = [resolve_path(path) for path in file_paths]
    for file_path in resolved_files:
        if not file_path.exists():
            errors.append({"file": str(file_path), "error": "file not found"})
            continue
        try:
            classes.extend(OntologyParser(file_path).parse())
        except Exception as exc:
            errors.append({"file": str(file_path), "error": f"{type(exc).__name__}: {exc}"})
    return {
        "file_count": len(resolved_files),
        "class_count": len(classes),
        "classes": [
            _trim_class(cls, include_source=include_source, field_limit=field_limit)
            for cls in classes
        ],
        "errors": errors,
    }


def parse_ontology_files_json(
    file_paths: list[str],
    include_source: bool = False,
    field_limit: int = 8,
) -> str:
    return json.dumps(
        parse_ontology_files(file_paths, include_source=include_source, field_limit=field_limit),
        ensure_ascii=False,
        indent=2,
    )
