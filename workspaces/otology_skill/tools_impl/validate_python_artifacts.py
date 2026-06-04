"""Python 产物验证工具实现。

作用：
- 对生成或重构后的 Python 文件进行质量检查。
- 检查内容包括 `py_compile`、非法 Python 标识符、以及不应出现在公开产物中的敏感词。
- 用作 Excel 生成、业务本体重构、本体合并流程的统一收尾验证工具。

主要输入：
- `paths`: Python 文件或目录路径列表，可为仓库相对路径或绝对路径。
- `recursive`: 当输入为目录时，是否递归扫描 `.py` 文件。

主要输出：
- JSON/dict，包含整体 `status`、文件数量、失败编译数量、标识符问题数量、敏感词命中数量和逐文件 `results`。
"""

from __future__ import annotations

import ast
import json
import py_compile
import re
from pathlib import Path
from typing import Any

from .paths import resolve_path


SENSITIVE_PATTERNS = [
    "Palan" + "tir",
    "palan" + "tir",
    "Foun" + "dry",
    "foun" + "dry",
    "Object" + " Type",
    "Action" + " Type",
    "Link" + " Type",
    "Object" + "Set",
    "Object" + " Set",
    "R" + "ID",
    "Enter" + "prise",
]


def _collect_files(paths: list[str], recursive: bool = True) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = resolve_path(raw)
        if path.is_file() and path.suffix == ".py":
            files.append(path)
        elif path.is_dir():
            iterator = path.rglob("*.py") if recursive else path.glob("*.py")
            files.extend(sorted(iterator))
    return sorted(dict.fromkeys(files))


def _identifier_issues(tree: ast.AST) -> list[str]:
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.isidentifier():
                issues.append(f"Invalid identifier: {node.name}")
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if not node.target.id.isidentifier():
                issues.append(f"Invalid annotated field: {node.target.id}")
    return issues


def _validate_file(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"file": str(path), "py_compile": {"ok": False}, "identifier_issues": [], "sensitive_hits": []}
    try:
        py_compile.compile(str(path), doraise=True)
        result["py_compile"] = {"ok": True}
    except Exception as exc:
        result["py_compile"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        result["identifier_issues"] = _identifier_issues(tree)
        hits = []
        for pattern in SENSITIVE_PATTERNS:
            if pattern in text:
                hits.append(pattern)
        result["sensitive_hits"] = hits
    except Exception as exc:
        result["parse_error"] = f"{type(exc).__name__}: {exc}"
    return result


def validate_python_artifacts(paths: list[str], recursive: bool = True) -> dict[str, Any]:
    """Run compile, identifier, and sensitive-term checks on Python files."""

    files = _collect_files(paths, recursive=recursive)
    results = [_validate_file(path) for path in files]
    failed_compile = [item for item in results if not item.get("py_compile", {}).get("ok")]
    identifier_issues = [
        {"file": item["file"], "issues": item["identifier_issues"]}
        for item in results
        if item.get("identifier_issues")
    ]
    sensitive_hits = [
        {"file": item["file"], "hits": item["sensitive_hits"]}
        for item in results
        if item.get("sensitive_hits")
    ]
    return {
        "status": "PASS" if not failed_compile and not identifier_issues and not sensitive_hits else "FAIL",
        "file_count": len(files),
        "failed_compile_count": len(failed_compile),
        "identifier_issue_count": sum(len(item["issues"]) for item in identifier_issues),
        "sensitive_hit_count": sum(len(item["hits"]) for item in sensitive_hits),
        "results": results,
    }


def validate_python_artifacts_json(paths: list[str], recursive: bool = True) -> str:
    return json.dumps(validate_python_artifacts(paths, recursive=recursive), ensure_ascii=False, indent=2)
