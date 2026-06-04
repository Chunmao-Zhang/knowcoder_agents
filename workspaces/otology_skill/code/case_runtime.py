"""Uploaded Excel case management for the Otology frontend.

This module is intentionally a thin wrapper around the existing otology tools:
uploads are persisted as named cases, then the current Excel inspection/model
generation/validation pipeline prepares first-pass Python classes. The core
agent workflow still decides how to refactor those classes into a business
ontology for the user's question.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from workspaces.otology_skill.tools_impl.generate_python_models_from_excel import (
    generate_python_models_from_excel,
)
from workspaces.otology_skill.tools_impl.inspect_excel_schema import inspect_excel_schema
from workspaces.otology_skill.tools_impl.paths import DATA_ROOT, OUTPUT_ROOT, REPO_ROOT
from workspaces.otology_skill.tools_impl.validate_python_artifacts import validate_python_artifacts


CASE_ROOT = DATA_ROOT / "cases"
REGISTRY_PATH = CASE_ROOT / "case_registry.json"
OUTPUT_CASE_ROOT = OUTPUT_ROOT / "cases"
SUPPORTED_EXCEL_SUFFIXES = {".xlsx", ".xlsm"}
MAX_CASE_UPLOAD_BYTES = 64 * 1024 * 1024


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slugify(value: str, fallback: str = "case") -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value).strip()).strip("-_").lower()
    return slug[:80] or fallback


def agent_visible_path(value: str | Path | None) -> str:
    """Return repo-relative paths for agent tools while keeping manifests absolute."""

    if not value:
        return ""
    path = Path(str(value)).expanduser()
    try:
        resolved = path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()
        return resolved.relative_to(REPO_ROOT).as_posix()
    except Exception:
        return str(value)


def _safe_filename(filename: str, used: set[str]) -> str:
    original = Path(filename or "uploaded.xlsx")
    suffix = original.suffix.lower()
    if suffix not in SUPPORTED_EXCEL_SUFFIXES:
        raise ValueError("Supported uploads: .xlsx or .xlsm Excel workbooks.")
    stem = slugify(original.stem, "workbook")
    candidate = f"{stem}{suffix}"
    index = 2
    while candidate in used:
        candidate = f"{stem}-{index}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_registry() -> dict[str, Any]:
    data = read_json(REGISTRY_PATH, {"version": 1, "cases": []})
    cases = data.get("cases") if isinstance(data, dict) else []
    return {"version": 1, "updated_at": data.get("updated_at") if isinstance(data, dict) else "", "cases": cases or []}


def write_registry(cases: list[dict[str, Any]]) -> None:
    write_json_atomic(REGISTRY_PATH, {"version": 1, "updated_at": now_iso(), "cases": cases})


def list_cases(limit: int | None = None) -> list[dict[str, Any]]:
    cases = list(read_registry().get("cases", []))
    cases.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return cases[:limit] if limit else cases


def get_case(case_id: str) -> dict[str, Any] | None:
    case_id = str(case_id or "").strip()
    if not case_id:
        return None
    for item in read_registry().get("cases", []):
        if item.get("id") == case_id:
            manifest = read_json(Path(str(item.get("manifest_path") or "")), None)
            return enrich_case_manifest(manifest) if isinstance(manifest, dict) else item
    return None


def _column_preview(sheet: dict[str, Any], limit: int = 12) -> list[dict[str, str]]:
    columns = []
    for col in (sheet.get("columns") or [])[:limit]:
        if not isinstance(col, dict):
            continue
        columns.append(
            {
                "original_name": str(col.get("original_name") or ""),
                "field_name": str(col.get("field_name") or ""),
                "python_type": str(col.get("python_type") or ""),
            }
        )
    return columns


def _workbook_summary(inspection: dict[str, Any]) -> list[dict[str, Any]]:
    summary = []
    for sheet in inspection.get("sheets", []) or []:
        if not isinstance(sheet, dict):
            continue
        summary.append(
            {
                "sheet_name": sheet.get("sheet_name"),
                "table_name_candidate": sheet.get("table_name_candidate"),
                "class_name_candidate": sheet.get("class_name_candidate"),
                "header_row_index": sheet.get("header_row_index"),
                "column_count": len(sheet.get("columns") or []),
                "columns": _column_preview(sheet),
            }
        )
    return summary


def _case_stats(files: list[dict[str, Any]]) -> dict[str, int]:
    sheet_count = 0
    table_count = 0
    field_count = 0
    generated_file_count = 0
    failed_compile_count = 0
    for item in files:
        inspection = item.get("inspection") or {}
        generation = item.get("generation") or {}
        validation = item.get("validation") or {}
        sheet_count += int(inspection.get("inspected_sheet_count") or 0)
        table_count += int(generation.get("table_count") or 0)
        field_count += sum(int(table.get("field_count") or 0) for table in generation.get("tables", []) or [])
        generated_file_count += len(generation.get("generated_files") or [])
        failed_compile_count += int(validation.get("failed_compile_count") or 0)
    return {
        "workbook_count": len(files),
        "sheet_count": sheet_count,
        "table_count": table_count,
        "field_count": field_count,
        "generated_file_count": generated_file_count,
        "failed_compile_count": failed_compile_count,
    }


def _generated_file_for_table(generation: dict[str, Any], table_name: str) -> str:
    for path in generation.get("generated_files", []) or []:
        if Path(str(path)).stem == table_name:
            return str(path)
    return ""


def _field_preview(fields: list[dict[str, Any]], limit: int = 10) -> list[dict[str, str]]:
    preview = []
    for field in fields[:limit]:
        if not isinstance(field, dict):
            continue
        preview.append(
            {
                "field_name": str(field.get("field_name") or field.get("name") or ""),
                "original_name": str(field.get("original_name") or ""),
                "python_type": str(field.get("python_type") or field.get("type") or ""),
                "comment": str(field.get("comment") or ""),
            }
        )
    return preview


def _sheet_preview(item: dict[str, Any], table: dict[str, Any]) -> dict[str, Any]:
    inspection = item.get("inspection") or {}
    for sheet in inspection.get("sheets", []) or []:
        if not isinstance(sheet, dict):
            continue
        if (
            sheet.get("sheet_name") == table.get("sheet_name")
            or sheet.get("table_name_candidate") == table.get("table_name")
            or sheet.get("class_name_candidate") == table.get("class_name")
        ):
            return {
                "headers": sheet.get("headers") or [],
                "sample_rows": (sheet.get("sample_rows") or [])[:12],
                "header_row_index": sheet.get("header_row_index"),
            }
    return {"headers": [], "sample_rows": [], "header_row_index": None}


def _extraction_map(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in files:
        generation = item.get("generation") or {}
        for table in generation.get("tables", []) or []:
            if not isinstance(table, dict):
                continue
            table_name = str(table.get("table_name") or "")
            rows.append(
                {
                    "source_filename": item.get("source_filename") or item.get("stored_filename"),
                    "stored_filename": item.get("stored_filename"),
                    "raw_path": item.get("raw_path"),
                    "sheet_name": table.get("sheet_name"),
                    "table_name": table_name,
                    "class_name": table.get("class_name"),
                    "field_count": table.get("field_count") or len(table.get("fields") or []),
                    "fields": _field_preview(table.get("fields") or []),
                    "relationships": table.get("relationships") or [],
                    "preview": _sheet_preview(item, table),
                    "generated_file": _generated_file_for_table(generation, table_name),
                    "prepared_dir": item.get("prepared_dir"),
                }
            )
    return rows


def _merge_events(case: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    for event in case.get("process_events", []) or []:
        if not isinstance(event, dict):
            continue
        if event.get("event_type") in {"merge", "model_process_trace"}:
            events.append(event)
    return events


def _question_events(case: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    for event in case.get("process_events", []) or []:
        if not isinstance(event, dict):
            continue
        if event.get("event_type") == "user_question":
            events.append(event)
    return events


def _short_text(value: str, limit: int = 72) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: max(limit - 1, 1)] + "…"


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path)


def _output_path(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(OUTPUT_ROOT.resolve())
    except Exception:
        return text
    return _repo_relative(resolved)


def _is_hidden_artifact_path(value: str) -> bool:
    return Path(str(value or "").strip()).name == "__init__.py"


def _artifact_entry(value: str) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(OUTPUT_ROOT.resolve())
    except Exception:
        return None
    if not resolved.is_file():
        return None
    if _is_hidden_artifact_path(resolved.name):
        return None
    suffix = resolved.suffix.lower().lstrip(".") or "file"
    return {
        "name": resolved.name,
        "path": _repo_relative(resolved),
        "kind": "python" if suffix == "py" else suffix,
        "extension": suffix,
    }


def _business_artifacts(case: dict[str, Any]) -> list[dict[str, Any]]:
    paths: list[str] = []
    output_dir = Path(str(case.get("output_dir") or ""))
    business_dir = output_dir / "business_ontology"
    if business_dir.exists():
        for path in sorted(business_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".py", ".md", ".json", ".txt", ".log"}:
                paths.append(str(path))
    for event in case.get("process_events", []) or []:
        if not isinstance(event, dict) or event.get("event_type") != "model_artifacts":
            continue
        payload = event.get("payload") or {}
        for item in payload.get("artifacts", []) or []:
            paths.append(str(item.get("path") if isinstance(item, dict) else item))

    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        entry = _artifact_entry(path)
        if not entry or entry["path"] in seen:
            continue
        seen.add(entry["path"])
        artifacts.append(entry)
    return artifacts


def _trace_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") or {}
    trace = payload.get("trace") if isinstance(payload, dict) else None
    if isinstance(trace, dict):
        return trace
    return payload if isinstance(payload, dict) else {}


def _class_artifact_for_target(target_class: str, artifacts: list[dict[str, Any]]) -> str:
    target = str(target_class or "").strip()
    python_paths = [item.get("path", "") for item in artifacts if item.get("extension") == "py"]
    if not python_paths:
        return ""
    if target:
        pattern = re.compile(rf"\bclass\s+{re.escape(target)}\b")
        for path in python_paths:
            candidate = REPO_ROOT / path
            try:
                if pattern.search(candidate.read_text(encoding="utf-8", errors="replace")):
                    return path
            except Exception:
                continue
    return python_paths[0]


def _schema_lookup_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if Path(text).suffix.lower() in {".xlsx", ".xlsm", ".py"}:
        text = Path(text).stem
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def _artifact_process_trace(artifact: dict[str, Any]) -> dict[str, Any] | None:
    if artifact.get("extension") != "py":
        return None
    path = REPO_ROOT / str(artifact.get("path") or "")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    assignment_match = re.search(r"PROCESS_TRACE_JSON\s*=\s*(?:\"\"\"|''')\s*(.*?)\s*(?:\"\"\"|''')", text, flags=re.S)
    if assignment_match:
        payload = assignment_match.group(1).strip()
        if payload.startswith("```"):
            payload = re.sub(r"^```(?:json)?\s*", "", payload, flags=re.I)
            payload = re.sub(r"\s*```$", "", payload)
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    patterns = [
        r"PROCESS_TRACE_JSON\s*=\s*(?:\"\"\"|''')\s*```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```\s*(?:\"\"\"|''')",
        r"PROCESS_TRACE_JSON\s*:?\s*```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.S)
        if not match:
            continue
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _question_context_classes(
    question: str,
    extraction: list[dict[str, Any]],
    field_count_by_class: dict[str, int],
    *,
    limit: int = 8,
) -> list[tuple[str, int]]:
    text = str(question or "").lower()
    tokens = {token for token in re.findall(r"[a-z0-9_]{3,}", text) if token}
    scored: list[tuple[str, int, int]] = []
    for item in extraction:
        class_name = str(item.get("class_name") or item.get("table_name") or "").strip()
        if not class_name:
            continue
        candidates = [
            class_name,
            item.get("table_name"),
            item.get("sheet_name"),
            item.get("source_filename"),
            *[
                value
                for field in item.get("fields", []) or []
                for value in (field.get("field_name"), field.get("original_name"), field.get("comment"))
            ],
        ]
        score = 0
        for candidate in candidates:
            value = str(candidate or "").strip().lower()
            if not value:
                continue
            if value in text:
                score += 6
            score += sum(2 for token in tokens if token in value or value in token)
        if score:
            scored.append((class_name, field_count_by_class.get(class_name, 1), score))

    if not scored:
        return sorted(field_count_by_class.items(), key=lambda item: item[1], reverse=True)[:limit]

    deduped: dict[str, tuple[int, int]] = {}
    for class_name, field_count, score in scored:
        current = deduped.get(class_name)
        if not current or score > current[1]:
            deduped[class_name] = (field_count, score)
    return [
        (class_name, field_count)
        for class_name, (field_count, _score) in sorted(
            deduped.items(),
            key=lambda item: (item[1][1], item[1][0]),
            reverse=True,
        )[:limit]
    ]


def _sankey_view(
    case: dict[str, Any],
    extraction: list[dict[str, Any]],
    merge_events: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    question_events: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    links: dict[tuple[str, str, str], dict[str, Any]] = {}
    schema_nodes: dict[str, str] = {}
    schema_lookup: dict[str, str] = {}
    target_nodes: dict[str, str] = {}
    field_count_by_class: dict[str, int] = {}
    workbook_sheets: dict[str, list[dict[str, Any]]] = {}

    def add_node(node_id: str, label: str, kind: str, stage: str, meta: dict[str, Any] | None = None) -> None:
        current = nodes.setdefault(
            node_id,
            {"id": node_id, "label": label, "kind": kind, "stage": stage, "meta": {}},
        )
        current["label"] = current.get("label") or label
        current["kind"] = current.get("kind") or kind
        current["stage"] = current.get("stage") or stage
        if meta:
            current.setdefault("meta", {}).update({key: value for key, value in meta.items() if value not in (None, "")})

    def add_link(source: str, target: str, value: int, label: str, meta: dict[str, Any] | None = None) -> None:
        if source not in nodes or target not in nodes:
            return
        key = (source, target, label)
        item = links.setdefault(
            key,
            {"source": source, "target": target, "value": 0, "label": label, "meta": {}},
        )
        item["value"] += max(int(value or 0), 1)
        if meta:
            item.setdefault("meta", {}).update({key: value for key, value in meta.items() if value not in (None, "")})

    def register_schema_alias(value: Any, schema_id: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        schema_nodes[text] = schema_id
        key = _schema_lookup_key(text)
        if key:
            schema_lookup.setdefault(key, schema_id)

    def schema_id_for_source(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        if text in schema_nodes:
            return schema_nodes[text]
        key = _schema_lookup_key(text)
        if not key:
            return None
        if key in schema_lookup:
            return schema_lookup[key]
        for alias_key, schema_id in schema_lookup.items():
            if len(alias_key) >= 6 and len(key) >= 6 and (alias_key in key or key in alias_key):
                return schema_id
        return None

    def latest_question_text() -> str:
        for event in reversed(question_events):
            payload = event.get("payload") if isinstance(event, dict) else {}
            question = payload.get("question") if isinstance(payload, dict) else ""
            if question:
                return str(question)
        return ""

    def artifact_schema_matches(artifact: dict[str, Any]) -> list[str]:
        if artifact.get("extension") != "py":
            return []
        path = REPO_ROOT / str(artifact.get("path") or "")
        try:
            haystack = _schema_lookup_key(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return []
        matches: list[str] = []
        seen: set[str] = set()
        for item in extraction:
            source = str(item.get("source_filename") or item.get("stored_filename") or "")
            aliases = [
                source,
                Path(source).stem if source else "",
                item.get("table_name"),
                item.get("class_name"),
            ]
            for alias in aliases:
                key = _schema_lookup_key(alias)
                if not key or key in {"sheet1", "sheet"} or len(key) < 6:
                    continue
                schema_id = schema_id_for_source(alias)
                if schema_id and schema_id not in seen and key in haystack:
                    seen.add(schema_id)
                    matches.append(schema_id)
                    break
        return matches

    def add_target_mapping(
        source_values: list[Any],
        target_class: str,
        *,
        label: str,
        event: dict[str, Any],
        meta: dict[str, Any] | None = None,
        value: int = 1,
    ) -> None:
        target_class = str(target_class or "").strip()
        if not target_class:
            return
        target_id = target_nodes.setdefault(target_class, f"target::{target_class}")
        add_node(
            target_id,
            target_class,
            "merged_class",
            "merged",
            {
                "target_class": target_class,
                "path": _class_artifact_for_target(target_class, artifacts),
                **(meta or {}),
            },
        )
        for source in source_values:
            source_text = str(source or "").strip()
            if not source_text:
                continue
            schema_id = schema_id_for_source(source_text) or f"schema::{source_text}"
            if schema_id not in nodes:
                add_node(schema_id, source_text, "raw_schema", "schema", {"class_name": source_text})
            add_link(schema_id, target_id, value, label, {"run_id": event.get("run_id")})

    for item in extraction:
        source = str(item.get("source_filename") or item.get("stored_filename") or "Workbook")
        sheet = str(item.get("sheet_name") or item.get("table_name") or "Sheet")
        class_name = str(item.get("class_name") or sheet)
        field_count = int(item.get("field_count") or len(item.get("fields") or []) or 1)
        workbook_id = f"workbook::{source}"
        schema_id = f"schema::{source}::{sheet}"
        register_schema_alias(class_name, schema_id)
        register_schema_alias(item.get("table_name"), schema_id)
        register_schema_alias(source, schema_id)
        register_schema_alias(Path(source).stem, schema_id)
        register_schema_alias(sheet, schema_id)
        field_count_by_class[class_name] = field_count
        add_node(
            workbook_id,
            source,
            "workbook",
            "workbook",
            {
                "source_filename": source,
                "stored_filename": item.get("stored_filename"),
                "raw_path": item.get("raw_path"),
            },
        )
        add_node(
            schema_id,
            str(item.get("table_name") or sheet),
            "raw_schema",
            "schema",
            {
                "source_filename": source,
                "sheet_name": sheet,
                "table_name": item.get("table_name"),
                "class_name": class_name,
                "raw_path": item.get("raw_path"),
                "field_count": field_count,
                "fields": item.get("fields") or [],
                "preview": item.get("preview") or {},
            },
        )
        workbook_sheets.setdefault(workbook_id, []).append(
            {
                "class_name": class_name,
                "table_name": item.get("table_name"),
                "sheet_name": sheet,
                "field_count": field_count,
                "fields": item.get("fields") or [],
                "preview": item.get("preview") or {},
            }
        )
        add_link(workbook_id, schema_id, field_count, "contains", {"field_count": field_count})

    for workbook_id, sheets in workbook_sheets.items():
        if workbook_id in nodes:
            nodes[workbook_id].setdefault("meta", {})["sheets"] = sheets

    artifact_trace_events = []
    for artifact in artifacts:
        trace = _artifact_process_trace(artifact)
        if trace:
            artifact_trace_events.append(
                {
                    "event_type": "artifact_process_trace",
                    "payload": {"trace": trace},
                    "source": "artifact",
                    "run_id": "",
                }
            )

    for event in [*merge_events, *artifact_trace_events]:
        trace = _trace_payload(event)
        for mapping in trace.get("merge_events", []) or []:
            if not isinstance(mapping, dict):
                continue
            target_class = str(
                mapping.get("target_class")
                or mapping.get("target_entity")
                or mapping.get("target")
                or ""
            ).strip()
            source_values = []
            for key in ("source_classes", "source_sheets", "sources"):
                values = mapping.get(key)
                if isinstance(values, list):
                    source_values.extend(values)
            for key in ("source_class", "source_sheet", "source"):
                if mapping.get(key):
                    source_values.append(mapping.get(key))
            value = len(mapping.get("key_fields") or mapping.get("merged_fields") or []) or 1
            add_target_mapping(
                source_values,
                target_class,
                label=str(mapping.get("action") or mapping.get("decision") or "maps_to"),
                event=event,
                value=value,
                meta={
                    "decision": mapping.get("action") or mapping.get("decision"),
                    "source_classes": mapping.get("source_classes") or [],
                    "source_sheets": mapping.get("source_sheets") or [],
                    "merged_fields": mapping.get("merged_fields") or mapping.get("key_fields") or [],
                    "conflicts": mapping.get("conflicts") or [],
                    "assumptions": mapping.get("assumptions") or [],
                    "reason": mapping.get("rationale") or mapping.get("reason"),
                },
            )

        for item in trace.get("keep_separate", []) or []:
            if not isinstance(item, dict):
                continue
            target_class = str(item.get("entity") or item.get("target_class") or "").strip()
            source_values = []
            if item.get("source"):
                source_values.append(item.get("source"))
            if isinstance(item.get("source_classes"), list):
                source_values.extend(item.get("source_classes"))
            add_target_mapping(
                source_values,
                target_class,
                label="kept_separate",
                event=event,
                meta={"reason": item.get("rationale") or item.get("reason")},
            )

        for mapping in trace.get("source_to_target", []) or []:
            if not isinstance(mapping, dict):
                continue
            source_class = str(mapping.get("source_class") or "").strip()
            target_class = str(mapping.get("target_class") or "").strip()
            if not source_class or not target_class:
                continue
            schema_id = schema_id_for_source(source_class) or f"schema::{source_class}"
            if schema_id not in nodes:
                add_node(schema_id, source_class, "raw_schema", "schema", {"class_name": source_class})
            target_id = target_nodes.setdefault(target_class, f"target::{target_class}")
            add_node(
                target_id,
                target_class,
                "merged_class",
                "merged",
                {
                    "target_class": target_class,
                    "decision": mapping.get("decision"),
                    "source_class": source_class,
                    "merged_fields": mapping.get("merged_fields") or [],
                    "conflicts": mapping.get("conflicts") or [],
                    "assumptions": mapping.get("assumptions") or [],
                    "path": _class_artifact_for_target(target_class, artifacts),
                },
            )
            value = len(mapping.get("merged_fields") or []) or field_count_by_class.get(source_class, 1)
            add_link(schema_id, target_id, value, str(mapping.get("decision") or "maps_to"), {"run_id": event.get("run_id")})

        for merged in trace.get("merged_classes", []) or trace.get("classes", []) or []:
            if not isinstance(merged, dict):
                continue
            target_class = str(merged.get("class_name") or merged.get("target_class") or "").strip()
            if not target_class:
                continue
            target_id = target_nodes.setdefault(target_class, f"target::{target_class}")
            add_node(
                target_id,
                target_class,
                "merged_class",
                "merged",
                {
                    "target_class": target_class,
                    "source_classes": merged.get("original_names") or merged.get("source_classes") or merged.get("merge_tokens") or [],
                    "field_count": merged.get("field_count"),
                    "path": _class_artifact_for_target(target_class, artifacts),
                },
            )
            for source_class in merged.get("original_names") or merged.get("source_classes") or merged.get("merge_tokens") or []:
                schema_id = schema_id_for_source(source_class) or f"schema::{source_class}"
                if schema_id not in nodes:
                    add_node(schema_id, str(source_class), "raw_schema", "schema", {"class_name": source_class})
                add_link(schema_id, target_id, int(merged.get("field_count") or 1), "merged_into", {"run_id": event.get("run_id")})

        for aggregate in trace.get("aggregate_design", []) or []:
            if not isinstance(aggregate, dict):
                continue
            aggregate_class = str(aggregate.get("target_class") or "").strip()
            if not aggregate_class:
                continue
            aggregate_id = target_nodes.setdefault(aggregate_class, f"target::{aggregate_class}")
            add_node(
                aggregate_id,
                aggregate_class,
                "merged_class",
                "merged",
                {
                    "target_class": aggregate_class,
                    "decision": aggregate.get("decision"),
                    "reason": aggregate.get("reason"),
                    "sources": aggregate.get("sources") or [],
                    "path": _class_artifact_for_target(aggregate_class, artifacts),
                },
            )
            for source in aggregate.get("sources") or []:
                source_id = target_nodes.get(str(source)) or schema_id_for_source(source) or f"target::{source}"
                if source_id not in nodes:
                    add_node(source_id, str(source), "merged_class", "merged", {"target_class": str(source)})
                add_link(source_id, aggregate_id, 1, str(aggregate.get("decision") or "composes"), {"run_id": event.get("run_id")})

    python_artifacts = [artifact for artifact in artifacts if artifact.get("extension") == "py"]
    for artifact in python_artifacts:
        if artifact.get("extension") != "py":
            continue
        artifact_id = f"final::{artifact.get('path')}"
        add_node(
            artifact_id,
            artifact.get("name") or "Final schema file",
            "final_schema_file",
            "final",
            {"path": artifact.get("path"), "extension": artifact.get("extension"), "kind": artifact.get("kind")},
        )
        linked = False
        for target_id, target in list(nodes.items()):
            if target.get("kind") == "merged_class" and target.get("meta", {}).get("path") == artifact.get("path"):
                add_link(target_id, artifact_id, 1, "written_to", {"path": artifact.get("path")})
                linked = True
        if not linked and len(python_artifacts) == 1 and target_nodes:
            for target_id in target_nodes.values():
                add_link(target_id, artifact_id, 1, "written_to", {"path": artifact.get("path")})
                linked = True
        if not linked:
            for schema_id in artifact_schema_matches(artifact):
                field_count = int(nodes.get(schema_id, {}).get("meta", {}).get("field_count") or 1)
                add_link(schema_id, artifact_id, field_count, "referenced_by", {"path": artifact.get("path")})
                linked = True
        if not linked and not target_nodes and len(python_artifacts) == 1:
            for class_name, field_count in _question_context_classes(
                latest_question_text(),
                extraction,
                field_count_by_class,
            ):
                schema_id = schema_id_for_source(class_name)
                if schema_id:
                    add_link(schema_id, artifact_id, field_count, "question_context", {"path": artifact.get("path")})
                    linked = True

    return {
        "nodes": list(nodes.values()),
        "links": list(links.values()),
        "stats": {
            "node_count": len(nodes),
            "link_count": len(links),
            "artifact_count": len(artifacts),
            "question_count": len(question_events),
        },
    }


def summarize_case_process(case: dict[str, Any]) -> dict[str, Any]:
    """Build a frontend-friendly pipeline view from manifest and recorded events."""

    stats = case.get("stats") or _case_stats(case.get("files", []) or [])
    extraction = _extraction_map(case.get("files", []) or [])
    merge_events = _merge_events(case)
    question_events = _question_events(case)
    artifacts = _business_artifacts(case)
    failed_compile_count = int(stats.get("failed_compile_count") or 0)
    stages = [
        {
            "id": "upload",
            "label": "Workbook intake",
            "status": "complete" if stats.get("workbook_count") else "waiting",
            "count": int(stats.get("workbook_count") or 0),
            "description": "Raw Excel files are stored as immutable case inputs.",
        },
        {
            "id": "inspect",
            "label": "Sheet inspection",
            "status": "complete" if stats.get("sheet_count") else "waiting",
            "count": int(stats.get("sheet_count") or 0),
            "description": "Headers, columns, sample values, and candidate class names are detected.",
        },
        {
            "id": "generate",
            "label": "Python class extraction",
            "status": "complete" if extraction else "waiting",
            "count": len(extraction),
            "description": "Each usable sheet is converted into a first-pass Python class.",
        },
        {
            "id": "questions",
            "label": "Question runs",
            "status": "active" if question_events else "waiting",
            "count": len(question_events),
            "description": "Each selected-case chat question is persisted so the Sankey map can update during the run.",
        },
        {
            "id": "merge",
            "label": "Ontology merge",
            "status": "complete" if merge_events else "waiting",
            "count": len(merge_events),
            "description": "Runtime merge events are captured from tool output or structured model traces.",
        },
        {
            "id": "validation",
            "label": "Validation",
            "status": "attention" if failed_compile_count else "complete",
            "count": failed_compile_count,
            "description": "Generated Python artifacts are compiled and surfaced for follow-up.",
        },
    ]
    return {
        "stages": stages,
        "extraction_map": extraction,
        "merge_events": merge_events,
        "question_events": question_events,
        "artifacts": artifacts,
        "sankey": _sankey_view(case, extraction, merge_events, artifacts, question_events),
        "validation": {
            "failed_compile_count": failed_compile_count,
            "generated_file_count": int(stats.get("generated_file_count") or 0),
        },
    }


def enrich_case_manifest(case: dict[str, Any]) -> dict[str, Any]:
    case.setdefault("user_inputs", [])
    case.setdefault("process_events", [])
    case["process"] = summarize_case_process(case)
    return case


def _registry_entry_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    files = manifest.get("files", []) or []
    process = summarize_case_process(manifest)
    return {
        "id": manifest["id"],
        "name": manifest["name"],
        "created_at": manifest["created_at"],
        "updated_at": manifest.get("updated_at", ""),
        "question": manifest.get("question", ""),
        "questions": manifest.get("questions", []),
        "model_style": manifest.get("model_style", "python_class"),
        "manifest_path": str(manifest.get("manifest_path") or ""),
        "raw_dir": str(manifest.get("raw_dir") or ""),
        "output_dir": str(manifest.get("output_dir") or ""),
        "prepared_root": str(manifest.get("prepared_root") or ""),
        "stats": manifest.get("stats") or _case_stats(files),
        "user_input_count": len(manifest.get("user_inputs", []) or []),
        "process_counts": {
            "extraction_count": len(process.get("extraction_map") or []),
            "merge_event_count": len(process.get("merge_events") or []),
        },
        "files": [
            {
                "source_filename": item.get("source_filename"),
                "raw_path": item.get("raw_path"),
                "prepared_dir": item.get("prepared_dir"),
                "sheet_count": (item.get("inspection") or {}).get("inspected_sheet_count"),
            }
            for item in files
        ],
    }


def save_case_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = enrich_case_manifest(manifest)
    manifest["updated_at"] = now_iso()
    manifest_path = Path(str(manifest.get("manifest_path") or CASE_ROOT / str(manifest["id"]) / "case_manifest.json"))
    manifest["manifest_path"] = str(manifest_path)
    write_json_atomic(manifest_path, manifest)
    cases = [item for item in read_registry().get("cases", []) if item.get("id") != manifest.get("id")]
    cases.append(_registry_entry_from_manifest(manifest))
    write_registry(cases)
    return manifest


def _normalize_case_input(input_type: str, label: str, content: str) -> tuple[str, str, str]:
    kind = slugify(input_type or "note", "note").replace("-", "_")
    allowed = {"note", "requirement", "mapping", "rule", "data_issue", "business_term", "other"}
    if kind not in allowed:
        kind = "other"
    label_text = str(label or "").strip()[:120] or "Untitled input"
    content_text = str(content or "").strip()
    if not content_text:
        raise ValueError("Input content cannot be empty.")
    if len(content_text) > 12000:
        raise ValueError("Input content is too long; keep it under 12000 characters.")
    return kind, label_text, content_text


def add_case_input(case_id: str, input_type: str, label: str, content: str) -> tuple[dict[str, Any], dict[str, Any]]:
    case = get_case(case_id)
    if not case:
        raise ValueError(f"Unknown uploaded Excel case id: {case_id}")
    kind, label_text, content_text = _normalize_case_input(input_type, label, content)
    now = now_iso()
    entry = {
        "id": uuid4().hex[:12],
        "input_type": kind,
        "label": label_text,
        "content": content_text,
        "created_at": now,
        "updated_at": now,
    }
    case.setdefault("user_inputs", []).append(entry)
    return entry, save_case_manifest(case)


def update_case_input(
    case_id: str,
    input_id: str,
    input_type: str | None = None,
    label: str | None = None,
    content: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    case = get_case(case_id)
    if not case:
        raise ValueError(f"Unknown uploaded Excel case id: {case_id}")
    for entry in case.setdefault("user_inputs", []):
        if entry.get("id") != input_id:
            continue
        kind, label_text, content_text = _normalize_case_input(
            input_type if input_type is not None else entry.get("input_type", "note"),
            label if label is not None else entry.get("label", ""),
            content if content is not None else entry.get("content", ""),
        )
        entry.update({"input_type": kind, "label": label_text, "content": content_text, "updated_at": now_iso()})
        return entry, save_case_manifest(case)
    raise ValueError(f"Unknown case input id: {input_id}")


def delete_case_input(case_id: str, input_id: str) -> dict[str, Any]:
    case = get_case(case_id)
    if not case:
        raise ValueError(f"Unknown uploaded Excel case id: {case_id}")
    original = len(case.get("user_inputs", []) or [])
    case["user_inputs"] = [entry for entry in case.get("user_inputs", []) or [] if entry.get("id") != input_id]
    if len(case["user_inputs"]) == original:
        raise ValueError(f"Unknown case input id: {input_id}")
    return save_case_manifest(case)


def _safe_remove_tree(path_value: str, allowed_roots: list[Path]) -> bool:
    path_text = str(path_value or "").strip()
    if not path_text:
        return False
    try:
        path = Path(path_text).resolve()
    except Exception:
        return False
    allowed = False
    for root in allowed_roots:
        try:
            path.relative_to(root.resolve())
            allowed = True
            break
        except ValueError:
            continue
    if not allowed or not path.exists() or not path.is_dir():
        return False
    shutil.rmtree(path)
    return True


def delete_case(case_id: str) -> dict[str, Any]:
    """Delete one uploaded Excel case, its raw uploads, and generated outputs."""

    case_id = str(case_id or "").strip()
    case = get_case(case_id)
    if not case:
        raise ValueError(f"Unknown uploaded Excel case id: {case_id}")

    cases = [item for item in read_registry().get("cases", []) if item.get("id") != case_id]
    write_registry(cases)

    removed_paths: list[str] = []
    allowed_roots = [CASE_ROOT, OUTPUT_CASE_ROOT]
    for key in ("raw_dir", "output_dir"):
        path_value = str(case.get(key) or "")
        if _safe_remove_tree(path_value, allowed_roots):
            removed_paths.append(path_value)

    manifest_path = Path(str(case.get("manifest_path") or CASE_ROOT / case_id / "case_manifest.json"))
    case_dir = manifest_path.parent if manifest_path.name else CASE_ROOT / case_id
    if _safe_remove_tree(str(case_dir), [CASE_ROOT]):
        removed_paths.append(str(case_dir))

    return {
        "deleted": {
            "id": case_id,
            "name": case.get("name") or case_id,
            "removed_paths": removed_paths,
        },
        "remaining_cases": len(cases),
    }


def _compact_payload(value: Any, limit: int = 32000) -> Any:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= limit:
        return value
    return {"truncated": True, "preview": text[:limit]}


def record_case_process_event(
    case_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str = "runtime",
    run_id: str = "",
) -> dict[str, Any]:
    case = get_case(case_id)
    if not case:
        raise ValueError(f"Unknown uploaded Excel case id: {case_id}")
    event = {
        "id": uuid4().hex[:12],
        "event_type": slugify(event_type, "event").replace("-", "_"),
        "source": source,
        "run_id": str(run_id or ""),
        "created_at": now_iso(),
        "payload": _compact_payload(payload),
    }
    events = list(case.get("process_events", []) or [])
    events.append(event)
    case["process_events"] = events[-100:]
    return save_case_manifest(case)


def _normalize_questions(question: str = "", questions: list[str] | None = None) -> list[str]:
    items: list[str] = []
    for item in questions or []:
        text = str(item or "").strip()
        if text:
            items.append(text)
    fallback = str(question or "").strip()
    if fallback and not items:
        items.append(fallback)
    return items


def _format_questions(questions: list[str]) -> str:
    if not questions:
        return ""
    if len(questions) == 1:
        return questions[0]
    return "\n".join(f"{index + 1}. {question}" for index, question in enumerate(questions))


def import_excel_case(
    uploads: list[tuple[str, bytes]],
    case_name: str = "",
    question: str = "",
    questions: list[str] | None = None,
) -> dict[str, Any]:
    """Persist uploaded Excel workbooks and prepare first-pass Python models."""

    if not uploads:
        raise ValueError("Please upload at least one Excel workbook.")

    total_bytes = sum(len(content) for _filename, content in uploads)
    if total_bytes > MAX_CASE_UPLOAD_BYTES:
        raise ValueError(f"Upload exceeds {MAX_CASE_UPLOAD_BYTES // (1024 * 1024)}MB limit.")

    case_id = str(uuid4())
    first_name = Path(uploads[0][0] or "uploaded.xlsx").stem
    display_name = (case_name or "").strip() or first_name or f"Case {case_id[:8]}"
    case_dir = CASE_ROOT / case_id
    raw_dir = case_dir / "raw"
    output_dir = OUTPUT_CASE_ROOT / case_id
    prepared_root = output_dir / "prepared_models"
    raw_dir.mkdir(parents=True, exist_ok=True)
    prepared_root.mkdir(parents=True, exist_ok=True)

    used_names: set[str] = set()
    files: list[dict[str, Any]] = []
    for filename, content in uploads:
        safe_name = _safe_filename(filename, used_names)
        raw_path = raw_dir / safe_name
        raw_path.write_bytes(content)
        inspection = inspect_excel_schema(str(raw_path), max_rows=50, max_samples=5)
        model_dir = prepared_root / slugify(Path(safe_name).stem, "workbook")
        generation = generate_python_models_from_excel(
            excel_path=str(raw_path),
            output_dir=str(model_dir),
            compile_check=True,
        )
        validation = validate_python_artifacts([str(model_dir)], recursive=True)
        files.append(
            {
                "source_filename": filename,
                "stored_filename": safe_name,
                "raw_path": str(raw_path),
                "prepared_dir": str(model_dir),
                "inspection": inspection,
                "schema_summary": _workbook_summary(inspection),
                "generation": generation,
                "validation": validation,
            }
        )

    normalized_questions = _normalize_questions(question, questions)
    manifest = {
        "id": case_id,
        "name": display_name,
        "created_at": now_iso(),
        "question": _format_questions(normalized_questions),
        "questions": normalized_questions,
        "model_style": "python_class",
        "raw_dir": str(raw_dir),
        "output_dir": str(output_dir),
        "prepared_root": str(prepared_root),
        "files": files,
        "stats": _case_stats(files),
        "user_inputs": [],
        "process_events": [],
    }
    manifest_path = case_dir / "case_manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    return save_case_manifest(manifest)


def _format_case_file_context(item: dict[str, Any]) -> list[str]:
    lines = [
        f"- source: {item.get('source_filename')} ({agent_visible_path(item.get('raw_path'))})",
        f"  prepared_models: {agent_visible_path(item.get('prepared_dir'))}",
    ]
    for sheet in item.get("schema_summary", []) or []:
        columns = sheet.get("columns") or []
        column_text = ", ".join(
            f"{col.get('original_name')} -> {col.get('field_name')}:{col.get('python_type')}"
            for col in columns[:10]
        )
        if len(columns) > 10:
            column_text += f", ... +{len(columns) - 10} more"
        lines.append(
            "  sheet: "
            f"{sheet.get('sheet_name')} | table={sheet.get('table_name_candidate')} "
            f"| class={sheet.get('class_name_candidate')} | columns={column_text}"
        )
    generation = item.get("generation") or {}
    generated = generation.get("generated_files") or []
    if generated:
        lines.append("  generated_files:")
        lines.extend(f"    - {agent_visible_path(path)}" for path in generated[:16])
        if len(generated) > 16:
            lines.append(f"    - ... +{len(generated) - 16} more")
    return lines


def build_case_prompt(case_id: str, user_question: str) -> tuple[dict[str, Any], str]:
    """Return the selected case and an augmented prompt for the agent."""

    case = get_case(case_id)
    if not case:
        raise ValueError(f"Unknown uploaded Excel case id: {case_id}")
    case_questions = _normalize_questions(case.get("question") or "", case.get("questions") or [])
    lines = [
        "你正在处理一个前端上传的 Excel 业务本体 case。",
        "请按 otology 工作流执行：已有 prepared class 时，不要重新生成基础 class；先用 parse_ontology_files 解析相关 prepared Python class，再围绕用户问题设计业务本体。",
        "SOUL.md 中的工作流是强制执行契约，不是建议；不能跳步骤，不能用大量 read_file 或手写脚本替代必需工具。",
        "业务本体重构时，prepared model 的结构化解析必须先由 parse_ontology_files 完成；read_file 只能在之后补充查看少量上下文。",
        "如果用户要求统一、合并、对齐、去重多个已有本体文件，必须走 ontology-merge 工作流：parse_ontology_files -> merge_ontology_classes -> render_merged_ontology -> validate_python_artifacts。",
        "如果必需工具失败或未执行，必须把工作流标记为 INCOMPLETE 并说明缺失步骤，不要声称产物已完成。",
        "不要修改上传的原始 Excel。最终本体产物写入当前 case 的 output_dir/business_ontology/。",
        "路径规则：Otology case 的路径规则优先于通用 /workspaces/... 工具提示；工具调用、写入和最终 Markdown 链接都使用下面展示的仓库相对路径。",
        "不要把输出路径改写成 /Users/...、/outputs/... 或 workspaces/otology_skill/outputs/...；业务产物必须直接写到 outputs/otology_skill/cases/<case_id>/business_ontology/。",
        "过程记录规则：每次生成、重构或合并本体时，在 Python artifact 中写入合法 JSON 字符串常量 PROCESS_TRACE_JSON，并在最终回答最后追加同名 fenced JSON block。",
        "PROCESS_TRACE_JSON 是给前端画过程图的机器数据，正文仍然用自然语言说明；JSON 只要求包含 workflow_steps, source_to_target, artifact_paths, validation。",
        "不要输出“口径提示”“冲突提示”“容易混淆的指标”等独立章节；PROCESS_TRACE_JSON 也不需要 keep_separate 或 conflicts 字段。",
        "",
        f"Case id: {case.get('id')}",
        f"Case name: {case.get('name')}",
        f"Case output dir: {agent_visible_path(case.get('output_dir'))}",
        f"Prepared model root: {agent_visible_path(case.get('prepared_root'))}",
        "上传时的问题 / 上下文：",
        *([f"{index + 1}. {question}" for index, question in enumerate(case_questions)] or ["(none)"]),
        f"Stats: {json.dumps(case.get('stats') or {}, ensure_ascii=False)}",
        "",
        "用户补充的 case 信息：",
    ]
    for entry in case.get("user_inputs", []) or []:
        lines.append(
            f"- [{entry.get('input_type') or 'note'}] {entry.get('label') or 'input'}: "
            f"{str(entry.get('content') or '').strip()[:1000]}"
        )
    if not case.get("user_inputs"):
        lines.append("- (none)")
    lines.extend(
        [
            "",
            "已上传工作簿和 prepared class 文件：",
        ]
    )
    for item in case.get("files", []) or []:
        lines.extend(_format_case_file_context(item))
    if len(case_questions) > 1:
        lines.extend(
            [
                "",
                "多问题模式：",
                "- 把上传时的多个问题视为同一个 case 下的相关建模目标。",
                "- 如果这些问题属于同一业务域，优先生成能覆盖所有问题的统一 schema / business ontology。",
                "- 如果某个问题需要专门视图，在 business_ontology/ 下创建命名清晰的 operation、interface 或分问题模块。",
                "- 最终回答要说明每个问题分别由哪些实体、关系、操作和输出文件覆盖。",
            ]
        )
    lines.extend(
        [
            "",
            "期望产出：",
            f"- 在 {agent_visible_path(case.get('output_dir'))}/business_ontology/ 生成或说明业务本体产物。",
            "- 实体、接口和操作方法命名应从上传数据和用户问题中抽象，不要绑定无关平台或外部产品名。",
            "- 最终回答必须包含这些原文标题：## 产出总结, ## 业务本体设计, ## 输出文件, ## 核心关系, ## 验证结果与假设。",
            "- 在 ## 输出文件 中，用仓库相对路径写 Markdown 链接，方便前端渲染下载按钮。",
            "- 不要给标题加编号，例如不要写 ## 1. 产出总结。",
            "- 这些章节之后追加 PROCESS_TRACE_JSON 和 fenced json block；保持紧凑、合法、可解析，并在 workflow_steps 里记录实际完成的工具链。",
            "- 如果问题信息不足，先写明假设并生成保守第一版本体，不要默认阻塞等待。",
            "",
            "本轮用户问题：",
            user_question,
        ]
    )
    return case, "\n".join(lines)
