"""本体类合并工具实现。

作用：
- 合并 `parse_ontology_files` 产出的 class 元数据，整合同名或已确认语义等价的类。
- 合并字段、docstring、base class、decorator，并检测字段类型冲突和外键命名模式。
- 注意：语义等价判断和用户确认属于 skill，本工具只执行已给定的合并分组。

主要输入：
- `classes_json`: 解析后的 class JSON，可为 `parse_ontology_files` 的输出或 class 列表。
- `merge_groups`: 已确认的合并分组，每组可用 class 名或 `source_file::class_name` 标识。
- `include_unmerged`: 是否把未参与合并的类原样带入输出。
- `auto_merge_exact_names`: 是否自动合并完全同名的类。

主要输出：
- JSON/dict，包含 `merged_classes`、`conflicts`、`merged_class_count`、`conflict_count` 等统计信息。
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any


def _load_classes(classes_json: str) -> list[dict[str, Any]]:
    data = json.loads(classes_json)
    if isinstance(data, dict):
        classes = data.get("classes", [])
    else:
        classes = data
    if not isinstance(classes, list):
        raise ValueError("classes_json must contain a list or an object with a `classes` list.")
    return [item for item in classes if isinstance(item, dict)]


def _class_key(cls: dict[str, Any]) -> str:
    return f"{cls.get('source_file', '')}::{cls.get('class_name', '')}"


def _select_classes(classes: list[dict[str, Any]], tokens: list[str]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for token in tokens:
        for cls in classes:
            key = _class_key(cls)
            if token in {str(cls.get("class_name", "")), key} and key not in seen:
                selected.append(cls)
                seen.add(key)
    return selected


def _choose_class_name(classes: list[dict[str, Any]]) -> str:
    with_doc = [cls for cls in classes if cls.get("docstring")]
    pool = with_doc or classes
    return max(pool, key=lambda cls: len(str(cls.get("class_name", "")))).get("class_name", "MergedOntology")


def _merge_unique_lists(classes: list[dict[str, Any]], key: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for cls in classes:
        for item in cls.get(key, []) or []:
            text = str(item)
            if text and text not in seen:
                result.append(text)
                seen.add(text)
    return result


def _merge_docstrings(classes: list[dict[str, Any]]) -> str:
    parts = []
    seen: set[str] = set()
    for cls in classes:
        doc = str(cls.get("docstring") or "").strip()
        if not doc or doc in seen:
            continue
        seen.add(doc)
        source = cls.get("source_file", "")
        parts.append(f"{doc}\n(from: {source})" if source else doc)
    return "\n\n".join(parts)


def _annotate_fk(field: dict[str, Any]) -> dict[str, Any]:
    name = str(field.get("name") or "")
    comment = str(field.get("comment") or "")
    if "FK" in comment or "foreign key" in comment.lower() or "外键" in comment:
        return field
    for suffix in ("_id", "_rid", "_ref", "_fk", "_key"):
        if name.endswith(suffix):
            target = "".join(part.capitalize() for part in name[: -len(suffix)].split("_") if part)
            if target:
                note = f"FK -> {target}"
                field["comment"] = f"{comment}; {note}" if comment else note
            break
    return field


def _merge_comments(variants: list[dict[str, Any]]) -> str:
    comments = []
    seen: set[str] = set()
    for variant in variants:
        comment = str(variant.get("comment") or "").strip()
        if not comment or comment in seen:
            continue
        seen.add(comment)
        source = variant.get("_source_file", "")
        comments.append(f"{comment} (from: {source})" if source else comment)
    return " | ".join(comments)


def _merge_fields(classes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cls in classes:
        for field in cls.get("fields", []) or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            item = dict(field)
            item["_source_file"] = cls.get("source_file")
            item["_source_class"] = cls.get("class_name")
            grouped[str(field["name"])].append(item)

    merged_fields: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for name, variants in grouped.items():
        types = {str(item.get("type") or "Any") for item in variants}
        merged = dict(variants[0])
        merged.pop("_source_file", None)
        merged.pop("_source_class", None)
        merged["comment"] = _merge_comments(variants) or merged.get("comment")
        if len(types) > 1:
            conflicts.append({
                "field_name": name,
                "variants": [
                    {
                        "type": item.get("type"),
                        "default": item.get("default"),
                        "comment": item.get("comment"),
                        "source_file": item.get("_source_file"),
                        "source_class": item.get("_source_class"),
                    }
                    for item in variants
                ],
            })
            merged["comment"] = f"CONFLICT: multiple types - {', '.join(sorted(types))}"
        merged_fields.append(_annotate_fk(merged))
    return merged_fields, conflicts


def _merge_group(classes: list[dict[str, Any]], original_tokens: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fields, conflicts = _merge_fields(classes)
    return {
        "class_name": _choose_class_name(classes),
        "docstring": _merge_docstrings(classes),
        "bases": _merge_unique_lists(classes, "bases"),
        "decorators": _merge_unique_lists(classes, "decorators"),
        "fields": fields,
        "methods": _merge_unique_lists(classes, "methods"),
        "source_files": [str(cls.get("source_file")) for cls in classes if cls.get("source_file")],
        "original_names": [str(cls.get("class_name")) for cls in classes if cls.get("class_name")],
        "merge_tokens": original_tokens,
    }, conflicts


def _exact_name_groups(classes: list[dict[str, Any]]) -> list[list[str]]:
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cls in classes:
        by_name[str(cls.get("class_name", ""))].append(cls)
    return [[name] for name, items in sorted(by_name.items()) if name and len(items) > 1]


def merge_ontology_classes(
    classes_json: str,
    merge_groups: list[list[str]] | None = None,
    include_unmerged: bool = True,
    auto_merge_exact_names: bool = True,
) -> dict[str, Any]:
    """Merge parsed classes using approved groups from the skill workflow."""

    classes = _load_classes(classes_json)
    groups = list(merge_groups or [])
    if auto_merge_exact_names:
        existing = {tuple(group) for group in groups}
        for group in _exact_name_groups(classes):
            if tuple(group) not in existing:
                groups.append(group)

    merged_classes: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for group in groups:
        selected = _select_classes(classes, group)
        if not selected:
            continue
        for cls in selected:
            consumed.add(_class_key(cls))
        merged, group_conflicts = _merge_group(selected, group)
        merged_classes.append(merged)
        conflicts.extend(group_conflicts)

    if include_unmerged:
        for cls in classes:
            if _class_key(cls) not in consumed:
                merged_classes.append(dict(cls))

    return {
        "input_class_count": len(classes),
        "merged_class_count": len(merged_classes),
        "merge_group_count": len(groups),
        "conflict_count": len(conflicts),
        "merged_classes": merged_classes,
        "conflicts": conflicts,
    }


def merge_ontology_classes_json(**kwargs: Any) -> str:
    return json.dumps(merge_ontology_classes(**kwargs), ensure_ascii=False, indent=2)
