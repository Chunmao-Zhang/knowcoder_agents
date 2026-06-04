#!/usr/bin/env python3
"""Prepare a generic file-backed KBQA graph runtime.

The script accepts TXT, JSON/JSONL, and XLSX triples, writes deterministic graph
artifacts, builds a SQLite graph store, and encodes both entities and relations
into a ChromaDB vector database with the same sentence-transformer model used by
`deepagents_kbqa`.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT / "workspaces" / "deepagents_kbqa_general"
DATA_ROOT = ROOT / "data" / "deepagents_kbqa_general"
DEFAULT_KB = DATA_ROOT / "graphs" / "active" / "raw" / "kb.txt"
DEFAULT_OUT = DATA_ROOT / "processed"
DEFAULT_RUNTIME_ROOT = DATA_ROOT / "runtime"
DEFAULT_REPORT_BASE = ROOT / "outputs" / "deepagents_kbqa_general" / "prepare"
WORKSPACE_EMBEDDING_MODEL = WORKSPACE / "embedding_model" / "retriver_webqsp-cwq_relation"
LEGACY_GENERAL_EMBEDDING_MODEL = (
    DEFAULT_RUNTIME_ROOT / "general_env" / "embedding_model" / "retriver_webqsp-cwq_relation"
)
LEGACY_FREEBASE_EMBEDDING_MODEL = (
    ROOT
    / "data"
    / "deepagents_kbqa"
    / "runtime"
    / "freebase_env"
    / "embedding_model"
    / "retriver_webqsp-cwq_relation"
)
WORD_RE = re.compile(r"[a-z0-9]+")
CELL_REF_RE = re.compile(r"([A-Z]+)(\d+)")


@dataclass(frozen=True)
class Triple:
    triple_id: int
    subject: str
    relation: str
    obj: str
    graph_id: str = "default"
    graph_name: str = "Default Graph"


@dataclass
class PreparedKG:
    triples: list[Triple]
    entities: list[str]
    relations: list[str]
    entity2id: dict[str, int]
    relation2id: dict[str, int]
    relation_types: dict[str, str]
    relation_descriptions: dict[str, str]
    entity_documents: dict[str, str]
    relation_documents: dict[str, str]
    entity_graphs: dict[str, dict[str, str]]
    relation_graphs: dict[str, dict[str, str]]
    graph_catalog: dict[str, str]
    cvt_relations: set[str] = field(default_factory=set)
    source_format: str = "txt"


@dataclass
class LoadedTriples:
    triples: list[tuple[str, str, str]]
    cvt_relations: set[str] = field(default_factory=set)
    relation_descriptions: dict[str, str] = field(default_factory=dict)


def normalize(text: str) -> str:
    return " ".join(WORD_RE.findall(str(text).lower()))


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def relation_type(relation: str) -> str:
    rel = "".join(ch.upper() if ch.isalnum() else "_" for ch in relation).strip("_")
    rel = re.sub(r"_+", "_", rel)
    return rel if rel and rel[0].isalpha() else f"REL_{rel or 'EDGE'}"


def relation_to_file_stem(relation: str) -> str:
    stem = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in relation).strip("_")
    stem = re.sub(r"_+", "_", stem)
    digest = hashlib.sha1(relation.encode("utf-8")).hexdigest()[:8]
    return f"{stem[:48] or 'relation'}_{digest}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_format(path: Path, explicit: str = "auto") -> str:
    if explicit and explicit != "auto":
        return explicit.lower()
    suffix = path.suffix.lower()
    if suffix in {".json", ".jsonl", ".ndjson"}:
        return "json"
    if suffix in {".xlsx", ".xlsm"}:
        return "excel"
    if suffix in {".txt", ".tsv", ".csv", ".kg"}:
        return "txt"
    return "txt"


def parse_triple_mapping(item: dict[str, Any]) -> tuple[str, str, str] | None:
    subject = item.get("subject", item.get("head", item.get("source", item.get("s"))))
    relation = item.get("relation", item.get("predicate", item.get("edge", item.get("p"))))
    obj = item.get("object", item.get("tail", item.get("target", item.get("o"))))
    parts = [clean_cell(subject), clean_cell(relation), clean_cell(obj)]
    return tuple(parts) if all(parts) else None  # type: ignore[return-value]


def parse_txt(path: Path) -> LoadedTriples:
    triples: list[tuple[str, str, str]] = []
    with path.open(encoding="utf-8-sig") as f:
        for line_no, raw_line in enumerate(f, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("{"):
                item = json.loads(line)
                triple = parse_triple_mapping(item) if isinstance(item, dict) else None
            else:
                delimiter = "|" if "|" in line else "\t" if "\t" in line else ","
                parts = [clean_cell(part) for part in line.split(delimiter, 2)]
                triple = tuple(parts) if len(parts) == 3 and all(parts) else None
            if triple is None:
                raise ValueError(f"Bad triple line {line_no}: expected subject|relation|object")
            triples.append(triple)
    return LoadedTriples(triples=triples)


def parse_json(path: Path) -> LoadedTriples:
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return LoadedTriples(triples=[])

    def parse_payload(payload: Any) -> LoadedTriples:
        cvt_relations: set[str] = set()
        relation_descriptions: dict[str, str] = {}
        rows: Any = payload
        if isinstance(payload, dict):
            rows = payload.get("triples", payload.get("edges", payload.get("data", [])))
            cvt_raw = payload.get("cvt_relations", payload.get("cvt_predicates", []))
            if isinstance(cvt_raw, list):
                cvt_relations = {clean_cell(x) for x in cvt_raw if clean_cell(x)}
            meta_raw = payload.get("relation_descriptions", payload.get("relations", {}))
            if isinstance(meta_raw, dict):
                for rel, desc in meta_raw.items():
                    rel_name = clean_cell(rel)
                    if rel_name:
                        if isinstance(desc, dict):
                            relation_descriptions[rel_name] = clean_cell(
                                desc.get("description", desc.get("label", rel_name))
                            )
                            if desc.get("cvt") is True:
                                cvt_relations.add(rel_name)
                        else:
                            relation_descriptions[rel_name] = clean_cell(desc)
        triples: list[tuple[str, str, str]] = []
        if not isinstance(rows, list):
            raise ValueError("JSON graph must be a list or an object with a `triples` list")
        for idx, item in enumerate(rows, 1):
            triple: tuple[str, str, str] | None = None
            if isinstance(item, dict):
                triple = parse_triple_mapping(item)
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                parts = [clean_cell(item[0]), clean_cell(item[1]), clean_cell(item[2])]
                triple = tuple(parts) if all(parts) else None  # type: ignore[assignment]
            if triple is None:
                raise ValueError(f"Bad JSON triple #{idx}: expected subject/relation/object")
            triples.append(triple)
        return LoadedTriples(triples=triples, cvt_relations=cvt_relations, relation_descriptions=relation_descriptions)

    try:
        return parse_payload(json.loads(text))
    except json.JSONDecodeError:
        triples: list[tuple[str, str, str]] = []
        for line_no, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            item = json.loads(line)
            triple = parse_triple_mapping(item) if isinstance(item, dict) else None
            if triple is None:
                raise ValueError(f"Bad JSONL triple line {line_no}: expected object with subject/relation/object")
            triples.append(triple)
        return LoadedTriples(triples=triples)


def column_index(cell_ref: str) -> int:
    match = CELL_REF_RE.match(cell_ref)
    letters = match.group(1) if match else cell_ref
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return value - 1


def read_xlsx_rows(path: Path) -> list[list[str]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.findall(".//m:t", ns)))
        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in zf.namelist():
            sheet_name = next((n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")), "")
        if not sheet_name:
            raise ValueError("No worksheet found in Excel file")
        root = ET.fromstring(zf.read(sheet_name))
        rows: list[list[str]] = []
        for row in root.findall(".//m:sheetData/m:row", ns):
            values: dict[int, str] = {}
            for cell in row.findall("m:c", ns):
                ref = cell.attrib.get("r", "A1")
                idx = column_index(ref)
                cell_type = cell.attrib.get("t", "")
                value = ""
                if cell_type == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall(".//m:t", ns))
                else:
                    v = cell.find("m:v", ns)
                    if v is not None and v.text is not None:
                        value = v.text
                        if cell_type == "s":
                            try:
                                value = shared[int(value)]
                            except Exception:
                                pass
                values[idx] = clean_cell(value)
            if values:
                max_idx = max(values)
                rows.append([values.get(i, "") for i in range(max_idx + 1)])
        return rows


def parse_excel(path: Path) -> LoadedTriples:
    rows = read_xlsx_rows(path)
    if not rows:
        return LoadedTriples(triples=[])
    header = [normalize(cell).replace(" ", "_") for cell in rows[0]]
    aliases = {
        "subject": {"subject", "head", "source", "s", "from"},
        "relation": {"relation", "predicate", "edge", "p", "rel"},
        "object": {"object", "tail", "target", "o", "to"},
    }
    indexes: dict[str, int] = {}
    for field_name, names in aliases.items():
        for idx, name in enumerate(header):
            if name in names:
                indexes[field_name] = idx
                break
    start_row = 1 if len(indexes) == 3 else 0
    if len(indexes) != 3:
        indexes = {"subject": 0, "relation": 1, "object": 2}
    triples: list[tuple[str, str, str]] = []
    for row_no, row in enumerate(rows[start_row:], start_row + 1):
        try:
            parts = [
                clean_cell(row[indexes["subject"]]),
                clean_cell(row[indexes["relation"]]),
                clean_cell(row[indexes["object"]]),
            ]
        except IndexError:
            continue
        if not any(parts):
            continue
        if not all(parts):
            raise ValueError(f"Bad Excel row {row_no}: subject, relation, and object are required")
        triples.append(tuple(parts))  # type: ignore[arg-type]
    return LoadedTriples(triples=triples)


def load_triples(path: Path, fmt: str = "auto") -> LoadedTriples:
    fmt = detect_format(path, fmt)
    if fmt == "json":
        loaded = parse_json(path)
    elif fmt in {"excel", "xlsx"}:
        loaded = parse_excel(path)
        fmt = "excel"
    elif fmt == "txt":
        loaded = parse_txt(path)
    else:
        raise ValueError(f"Unsupported graph format: {fmt}")
    if not loaded.triples:
        raise ValueError("No triples found in graph file")
    loaded.triples = list(dict.fromkeys(loaded.triples))
    return loaded


def _clean_graph_id(value: str) -> str:
    cleaned = clean_cell(value)
    return cleaned or "default"


def _clean_graph_name(value: str, graph_id: str) -> str:
    cleaned = clean_cell(value)
    return cleaned or graph_id or "Default Graph"


def build_prepared_kg(
    loaded: LoadedTriples,
    source_format: str,
    graph_id: str = "default",
    graph_name: str = "Default Graph",
) -> PreparedKG:
    gid = _clean_graph_id(graph_id)
    gname = _clean_graph_name(graph_name, gid)
    records = (
        {
            "subject": s,
            "relation": p,
            "object": o,
            "graph_id": gid,
            "graph_name": gname,
        }
        for s, p, o in loaded.triples
    )
    return build_prepared_kg_from_records(records, source_format, loaded.cvt_relations, loaded.relation_descriptions)


def build_prepared_kg_from_records(
    records: Iterable[dict[str, Any]],
    source_format: str = "jsonl",
    cvt_relations: set[str] | None = None,
    relation_descriptions: dict[str, str] | None = None,
) -> PreparedKG:
    triples: list[Triple] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in records:
        subject = clean_cell(record.get("subject", record.get("head", record.get("source", record.get("s")))))
        relation = clean_cell(record.get("relation", record.get("predicate", record.get("edge", record.get("p")))))
        obj = clean_cell(record.get("object", record.get("tail", record.get("target", record.get("o")))))
        gid = _clean_graph_id(str(record.get("graph_id") or record.get("graph_uuid") or "default"))
        gname = _clean_graph_name(str(record.get("graph_name") or record.get("name") or gid), gid)
        if not (subject and relation and obj):
            continue
        key = (subject, relation, obj, gid)
        if key in seen:
            continue
        seen.add(key)
        triples.append(Triple(len(triples) + 1, subject, relation, obj, gid, gname))
    if not triples:
        raise ValueError("No triples found in graph records")

    entities: set[str] = set()
    relations: set[str] = set()
    triple_counts: dict[str, int] = defaultdict(int)
    contexts: dict[str, list[str]] = defaultdict(list)
    relation_pairs: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"heads": set(), "tails": set()})
    relation_counts: dict[str, int] = defaultdict(int)
    entity_graphs: dict[str, dict[str, str]] = defaultdict(dict)
    relation_graphs: dict[str, dict[str, str]] = defaultdict(dict)
    graph_catalog: dict[str, str] = {}

    for t in triples:
        entities.update((t.subject, t.obj))
        relations.add(t.relation)
        graph_catalog[t.graph_id] = t.graph_name
        entity_graphs[t.subject][t.graph_id] = t.graph_name
        entity_graphs[t.obj][t.graph_id] = t.graph_name
        relation_graphs[t.relation][t.graph_id] = t.graph_name
        triple_counts[t.subject] += 1
        triple_counts[t.obj] += 1
        relation_counts[t.relation] += 1
        relation_pairs[t.relation]["heads"].add(t.subject)
        relation_pairs[t.relation]["tails"].add(t.obj)
        if len(contexts[t.subject]) < 16:
            contexts[t.subject].append(f"{t.relation} {t.obj}")
        if len(contexts[t.obj]) < 16:
            contexts[t.obj].append(f"incoming {t.relation} {t.subject}")

    entity_list = sorted(entities, key=lambda x: (x.lower(), x))
    relation_list = sorted(relations, key=lambda x: (x.lower(), x))
    entity2id = {entity: idx for idx, entity in enumerate(entity_list)}
    relation2id = {relation: idx for idx, relation in enumerate(relation_list)}
    relation_types = {relation: relation_type(relation) for relation in relation_list}

    entity_documents = {
        entity: f"{entity}. " + "; ".join(contexts.get(entity, []))
        for entity in entity_list
    }
    relation_documents: dict[str, str] = {}
    relation_descs: dict[str, str] = {}
    custom_relation_descriptions = relation_descriptions or {}
    for relation in relation_list:
        custom_desc = custom_relation_descriptions.get(relation, "")
        examples = []
        for t in triples:
            if t.relation == relation:
                examples.append(f"{t.subject} -> {t.obj}")
            if len(examples) >= 4:
                break
        desc = custom_desc or (
            f"Relation `{relation}` connects generic graph entities. "
            f"It appears in {relation_counts[relation]} triples."
        )
        relation_descs[relation] = desc
        relation_documents[relation] = f"{relation.replace('_', ' ')}. {desc} Examples: {'; '.join(examples)}"

    return PreparedKG(
        triples=triples,
        entities=entity_list,
        relations=relation_list,
        entity2id=entity2id,
        relation2id=relation2id,
        relation_types=relation_types,
        relation_descriptions=relation_descs,
        entity_documents=entity_documents,
        relation_documents=relation_documents,
        entity_graphs={entity: dict(entity_graphs.get(entity, {})) for entity in entity_list},
        relation_graphs={relation: dict(relation_graphs.get(relation, {})) for relation in relation_list},
        graph_catalog=dict(sorted(graph_catalog.items(), key=lambda item: (item[1].lower(), item[0]))),
        cvt_relations=set(cvt_relations or set()),
        source_format=source_format,
    )


def load_kg(
    kb_path: Path,
    fmt: str = "auto",
    graph_id: str = "default",
    graph_name: str = "Default Graph",
) -> PreparedKG:
    if not kb_path.exists():
        raise FileNotFoundError(f"Graph file not found: {kb_path}")
    resolved_fmt = detect_format(kb_path, fmt)
    loaded = load_triples(kb_path, resolved_fmt)
    return build_prepared_kg(loaded, resolved_fmt, graph_id=graph_id, graph_name=graph_name)


def write_tsv(path: Path, rows: Iterable[Iterable[object]], header: Iterable[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(list(header))
        writer.writerows(rows)


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def ensure_embedding_model(runtime_env: Path | None = None) -> Path:
    """Return the workspace-local embedding model used by KBQA General.

    `runtime_env` is accepted for backward compatibility; model weights now live
    in the workspace so graph runtimes only contain graph-specific artifacts.
    """

    if WORKSPACE_EMBEDDING_MODEL.exists():
        return WORKSPACE_EMBEDDING_MODEL
    for source_model in (LEGACY_GENERAL_EMBEDDING_MODEL, LEGACY_FREEBASE_EMBEDDING_MODEL):
        if source_model.exists():
            WORKSPACE_EMBEDDING_MODEL.parent.mkdir(parents=True, exist_ok=True)
            tmp = WORKSPACE_EMBEDDING_MODEL.with_name(WORKSPACE_EMBEDDING_MODEL.name + ".tmp")
            if tmp.exists():
                shutil.rmtree(tmp)
            shutil.copytree(source_model, tmp)
            tmp.replace(WORKSPACE_EMBEDDING_MODEL)
            return WORKSPACE_EMBEDDING_MODEL
    else:
        raise FileNotFoundError(
            "Embedding model not found. Expected workspace model at "
            f"{WORKSPACE_EMBEDDING_MODEL}; copy it there or pass --skip-vector-index."
        )


def write_processed_artifacts(
    kg: PreparedKG,
    kb_path: Path,
    out_dir: Path,
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    activate: bool = True,
    build_vector_index: bool = True,
    runtime_env_name: str = "general_env",
) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    graph_dir = out_dir / "graph"
    if graph_dir.exists():
        shutil.rmtree(graph_dir)
    graph_dir.mkdir(parents=True, exist_ok=True)

    write_tsv(
        out_dir / "entity2id.tsv",
        (
            (
                e,
                kg.entity2id[e],
                json.dumps(sorted(kg.entity_graphs.get(e, {}).keys()), ensure_ascii=False),
                json.dumps([kg.entity_graphs.get(e, {})[gid] for gid in sorted(kg.entity_graphs.get(e, {}))], ensure_ascii=False),
            )
            for e in kg.entities
        ),
        ("entity", "entity_id", "graph_ids", "graph_names"),
    )
    write_tsv(
        out_dir / "id2entity.tsv",
        (
            (
                kg.entity2id[e],
                e,
                json.dumps(sorted(kg.entity_graphs.get(e, {}).keys()), ensure_ascii=False),
                json.dumps([kg.entity_graphs.get(e, {})[gid] for gid in sorted(kg.entity_graphs.get(e, {}))], ensure_ascii=False),
            )
            for e in kg.entities
        ),
        ("entity_id", "entity", "graph_ids", "graph_names"),
    )
    write_tsv(
        out_dir / "relation2id.tsv",
        (
            (
                r,
                kg.relation2id[r],
                kg.relation_types[r],
                kg.relation_descriptions.get(r, ""),
                json.dumps(sorted(kg.relation_graphs.get(r, {}).keys()), ensure_ascii=False),
                json.dumps([kg.relation_graphs.get(r, {})[gid] for gid in sorted(kg.relation_graphs.get(r, {}))], ensure_ascii=False),
            )
            for r in kg.relations
        ),
        ("relation", "relation_id", "type", "description", "graph_ids", "graph_names"),
    )
    write_tsv(
        out_dir / "id2relation.tsv",
        (
            (
                kg.relation2id[r],
                r,
                kg.relation_types[r],
                kg.relation_descriptions.get(r, ""),
                json.dumps(sorted(kg.relation_graphs.get(r, {}).keys()), ensure_ascii=False),
                json.dumps([kg.relation_graphs.get(r, {})[gid] for gid in sorted(kg.relation_graphs.get(r, {}))], ensure_ascii=False),
            )
            for r in kg.relations
        ),
        ("relation_id", "relation", "type", "description", "graph_ids", "graph_names"),
    )
    write_tsv(
        out_dir / "triples_named.tsv",
        ((t.triple_id, t.subject, t.relation, t.obj, t.graph_id, t.graph_name) for t in kg.triples),
        ("triple_id", "subject", "relation", "object", "graph_id", "graph_name"),
    )
    write_tsv(
        out_dir / "triples_encoded.tsv",
        ((t.triple_id, kg.entity2id[t.subject], kg.relation2id[t.relation], kg.entity2id[t.obj]) for t in kg.triples),
        ("triple_id", "head_id", "relation_id", "tail_id"),
    )
    with (out_dir / "train2id.txt").open("w", encoding="utf-8") as f:
        f.write(f"{len(kg.triples)}\n")
        for t in kg.triples:
            f.write(f"{kg.entity2id[t.subject]} {kg.entity2id[t.obj]} {kg.relation2id[t.relation]}\n")

    by_relation: dict[str, list[Triple]] = defaultdict(list)
    for triple in kg.triples:
        by_relation[triple.relation].append(triple)
    with (graph_dir / "manifest.tsv").open("w", encoding="utf-8") as f:
        f.write("relation\trelation_id\ttype\tcount\tfile\n")
        for relation in kg.relations:
            stem = relation_to_file_stem(relation)
            file_name = f"rel_{stem}.csv"
            f.write(f"{relation}\t{kg.relation2id[relation]}\t{kg.relation_types[relation]}\t{len(by_relation[relation])}\tgraph/{file_name}\n")
            with (graph_dir / file_name).open("w", encoding="utf-8", newline="") as rel_f:
                writer = csv.writer(rel_f)
                writer.writerow(["triple_id", "subject", "object", "relation_id", "graph_id", "graph_name"])
                for t in by_relation[relation]:
                    writer.writerow([t.triple_id, t.subject, t.obj, kg.relation2id[relation], t.graph_id, t.graph_name])

    runtime_env = runtime_root / runtime_env_name
    runtime_info: dict[str, object] = {}
    if activate:
        runtime_env.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kb_path, runtime_env / "kb.txt")
        sqlite_path = runtime_env / "graph.sqlite"
        build_sqlite_store(kg, sqlite_path)
        info_dir = runtime_env / "graph-info"
        write_graph_info(kg, info_dir)
        model_path = None
        vector_status: dict[str, object]
        if build_vector_index:
            model_path = ensure_embedding_model(runtime_env)
            vector_status = build_chroma_indexes(kg, runtime_env / "db_vector_chroma_general", model_path)
        else:
            vector_status = {"enabled": False, "reason": "--skip-vector-index"}
        runtime_info = {
            "runtime_root": str(runtime_root),
            "runtime_env": str(runtime_env),
            "runtime_env_name": runtime_env_name,
            "sqlite_path": str(sqlite_path),
            "chroma_path": str(runtime_env / "db_vector_chroma_general"),
            "embedding_model": str(model_path or WORKSPACE_EMBEDDING_MODEL),
            "vector_index": vector_status,
        }

    metadata = {
        "source_kb": str(kb_path),
        "source_format": kg.source_format,
        "source_sha256": file_sha256(kb_path),
        "entity_count": len(kg.entities),
        "relation_count": len(kg.relations),
        "triple_count": len(kg.triples),
        "graph_count": len(kg.graph_catalog),
        "graph_catalog": kg.graph_catalog,
        "processed_dir": str(out_dir),
        "relation_types": kg.relation_types,
        "cvt_relations": sorted(kg.cvt_relations),
        "runtime": runtime_info,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json_atomic(out_dir / "manifest.json", metadata)
    if activate:
        write_json_atomic(runtime_env / "active_graph.json", metadata)
    return metadata


def build_sqlite_store(kg: PreparedKG, sqlite_path: Path) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = sqlite_path.with_suffix(".tmp.sqlite")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(str(tmp))
    try:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE entities (
                entity_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                name_norm TEXT NOT NULL,
                document TEXT NOT NULL,
                graph_ids TEXT NOT NULL,
                graph_names TEXT NOT NULL,
                triple_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE relations (
                relation_id INTEGER PRIMARY KEY,
                relation TEXT NOT NULL UNIQUE,
                relation_norm TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                description TEXT NOT NULL,
                document TEXT NOT NULL,
                graph_ids TEXT NOT NULL,
                graph_names TEXT NOT NULL,
                is_cvt INTEGER NOT NULL DEFAULT 0,
                triple_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE triples (
                triple_id INTEGER PRIMARY KEY,
                subject TEXT NOT NULL,
                relation TEXT NOT NULL,
                object TEXT NOT NULL,
                subject_id INTEGER NOT NULL,
                relation_id INTEGER NOT NULL,
                object_id INTEGER NOT NULL,
                graph_id TEXT NOT NULL,
                graph_name TEXT NOT NULL
            );
            CREATE TABLE graph_catalog (
                graph_id TEXT PRIMARY KEY,
                graph_name TEXT NOT NULL,
                triple_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX idx_entities_norm ON entities(name_norm);
            CREATE INDEX idx_entities_name ON entities(name);
            CREATE INDEX idx_relations_norm ON relations(relation_norm);
            CREATE INDEX idx_triples_subject_relation ON triples(subject, relation);
            CREATE INDEX idx_triples_object_relation ON triples(object, relation);
            CREATE INDEX idx_triples_relation_subject ON triples(relation, subject);
            CREATE INDEX idx_triples_graph_id ON triples(graph_id);
            """
        )
        triple_counts: dict[str, int] = defaultdict(int)
        relation_counts: dict[str, int] = defaultdict(int)
        graph_counts: dict[str, int] = defaultdict(int)
        for t in kg.triples:
            triple_counts[t.subject] += 1
            triple_counts[t.obj] += 1
            relation_counts[t.relation] += 1
            graph_counts[t.graph_id] += 1
        conn.executemany(
            """
            INSERT INTO entities(entity_id, name, name_norm, document, graph_ids, graph_names, triple_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    kg.entity2id[e],
                    e,
                    normalize(e),
                    kg.entity_documents.get(e, e),
                    json.dumps(sorted(kg.entity_graphs.get(e, {}).keys()), ensure_ascii=False),
                    json.dumps([kg.entity_graphs.get(e, {})[gid] for gid in sorted(kg.entity_graphs.get(e, {}))], ensure_ascii=False),
                    triple_counts.get(e, 0),
                )
                for e in kg.entities
            ),
        )
        conn.executemany(
            """
            INSERT INTO relations(
                relation_id, relation, relation_norm, relation_type, description, document,
                graph_ids, graph_names, is_cvt, triple_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    kg.relation2id[r],
                    r,
                    normalize(r.replace("_", " ")),
                    kg.relation_types[r],
                    kg.relation_descriptions.get(r, ""),
                    kg.relation_documents.get(r, r),
                    json.dumps(sorted(kg.relation_graphs.get(r, {}).keys()), ensure_ascii=False),
                    json.dumps([kg.relation_graphs.get(r, {})[gid] for gid in sorted(kg.relation_graphs.get(r, {}))], ensure_ascii=False),
                    1 if r in kg.cvt_relations else 0,
                    relation_counts.get(r, 0),
                )
                for r in kg.relations
            ),
        )
        conn.executemany(
            """
            INSERT INTO triples(
                triple_id, subject, relation, object, subject_id, relation_id, object_id, graph_id, graph_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    t.triple_id,
                    t.subject,
                    t.relation,
                    t.obj,
                    kg.entity2id[t.subject],
                    kg.relation2id[t.relation],
                    kg.entity2id[t.obj],
                    t.graph_id,
                    t.graph_name,
                )
                for t in kg.triples
            ),
        )
        conn.executemany(
            "INSERT INTO graph_catalog(graph_id, graph_name, triple_count) VALUES (?, ?, ?)",
            ((gid, name, graph_counts.get(gid, 0)) for gid, name in kg.graph_catalog.items()),
        )
        conn.commit()
    finally:
        conn.close()
    tmp.replace(sqlite_path)


def write_graph_info(kg: PreparedKG, info_dir: Path) -> None:
    info_dir.mkdir(parents=True, exist_ok=True)
    rel2desc = {
        rel: [
            "The type of its head entity is 'Entity'.",
            "The type of its tail entity is 'Entity'.",
            kg.relation_descriptions.get(rel, ""),
        ]
        for rel in kg.relations
    }
    write_json_atomic(info_dir / "rel2desc.json", rel2desc)
    write_json_atomic(info_dir / "rel2des_cleaned.json", rel2desc)
    write_json_atomic(info_dir / "graph_catalog.json", kg.graph_catalog)
    write_json_atomic(info_dir / "predicate_freq.json", {rel: 0 for rel in kg.relations})
    (info_dir / "relations_ordered.txt").write_text("\n".join(kg.relations) + "\n", encoding="utf-8")
    (info_dir / "cvt_predicate_onehop.jsonl").write_text("", encoding="utf-8")
    (info_dir.parent / "cvt_properties.txt").write_text("\n".join(sorted(kg.cvt_relations)) + ("\n" if kg.cvt_relations else ""), encoding="utf-8")


def batched(items: list[Any], size: int) -> Iterable[list[Any]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def build_chroma_indexes(kg: PreparedKG, chroma_path: Path, model_path: Path) -> dict[str, object]:
    import chromadb
    import numpy as np
    from sentence_transformers import SentenceTransformer

    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    for name in ("general_entities", "general_predicates"):
        try:
            client.delete_collection(name)
        except Exception:
            pass
    entity_col = client.get_or_create_collection("general_entities", metadata={"hnsw:space": "cosine"})
    pred_col = client.get_or_create_collection("general_predicates", metadata={"hnsw:space": "cosine"})

    model = SentenceTransformer(str(model_path), device="cpu")

    entity_docs = [kg.entity_documents[e] for e in kg.entities]
    entity_embeddings = model.encode(
        entity_docs,
        batch_size=64,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    ) if entity_docs else np.zeros((0, 1), dtype="float32")
    for batch_indices in batched(list(range(len(kg.entities))), 1000):
        entity_col.add(
            ids=[f"entity-{i}" for i in batch_indices],
            documents=[entity_docs[i] for i in batch_indices],
            embeddings=[entity_embeddings[i].astype("float32").tolist() for i in batch_indices],
            metadatas=[
                {
                    "entity_name": kg.entities[i],
                    "name": kg.entities[i],
                    "graph_ids": json.dumps(sorted(kg.entity_graphs.get(kg.entities[i], {}).keys()), ensure_ascii=False),
                    "graph_names": json.dumps(
                        [
                            kg.entity_graphs.get(kg.entities[i], {})[gid]
                            for gid in sorted(kg.entity_graphs.get(kg.entities[i], {}))
                        ],
                        ensure_ascii=False,
                    ),
                    "triple_count": int(kg.entity_documents.get(kg.entities[i], "").count(";")),
                }
                for i in batch_indices
            ],
        )

    rel_docs = [kg.relation_documents[r] for r in kg.relations]
    rel_embeddings = model.encode(
        rel_docs,
        batch_size=64,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    ) if rel_docs else np.zeros((0, 1), dtype="float32")
    for batch_indices in batched(list(range(len(kg.relations))), 1000):
        pred_col.add(
            ids=[f"predicate-{i}" for i in batch_indices],
            documents=[rel_docs[i] for i in batch_indices],
            embeddings=[rel_embeddings[i].astype("float32").tolist() for i in batch_indices],
            metadatas=[
                {
                    "predicate": kg.relations[i],
                    "relation": kg.relations[i],
                    "description": kg.relation_descriptions.get(kg.relations[i], ""),
                    "graph_ids": json.dumps(sorted(kg.relation_graphs.get(kg.relations[i], {}).keys()), ensure_ascii=False),
                    "graph_names": json.dumps(
                        [
                            kg.relation_graphs.get(kg.relations[i], {})[gid]
                            for gid in sorted(kg.relation_graphs.get(kg.relations[i], {}))
                        ],
                        ensure_ascii=False,
                    ),
                    "triple_count": sum(1 for t in kg.triples if t.relation == kg.relations[i]),
                }
                for i in batch_indices
            ],
        )
    return {
        "enabled": True,
        "entity_collection": "general_entities",
        "predicate_collection": "general_predicates",
        "entity_count": len(kg.entities),
        "relation_count": len(kg.relations),
        "path": str(chroma_path),
    }


def local_kbqa_smoke(kg: PreparedKG) -> list[dict[str, object]]:
    if not kg.triples:
        return []
    out_adj: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for t in kg.triples:
        out_adj[t.subject][t.relation].add(t.obj)
    first = kg.triples[0]
    answers = sorted(out_adj[first.subject][first.relation])
    return [{"name": "first_triple_forward_lookup", "ok": first.obj in answers, "answers": answers[:10]}]


def generated_files(out_dir: Path) -> list[str]:
    return sorted(path.relative_to(out_dir).as_posix() for path in out_dir.rglob("*") if path.is_file())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare generic graph KBQA data and vector indexes.")
    parser.add_argument("--kb", type=Path, default=DEFAULT_KB, help="TXT/JSON/JSONL/XLSX graph triples file.")
    parser.add_argument("--format", choices=["auto", "txt", "json", "excel", "xlsx"], default="auto")
    parser.add_argument("--graph-id", default="default", help="Graph UUID attached to all triples from this input.")
    parser.add_argument("--graph-name", default="Default Graph", help="Human-readable graph name attached to this input.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--runtime-env-name", default="general_env")
    parser.add_argument("--report-base", type=Path, default=DEFAULT_REPORT_BASE)
    parser.add_argument("--skip-vector-index", action="store_true", help="Build SQLite/artifacts but skip Chroma/BGE encoding.")
    parser.add_argument("--no-activate", action="store_true", help="Do not replace the active runtime graph.")
    parser.add_argument("--verify", action="store_true", help="Run a local file-backed smoke check.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kg = load_kg(args.kb, args.format, graph_id=args.graph_id, graph_name=args.graph_name)
    metadata = write_processed_artifacts(
        kg,
        args.kb,
        args.out_dir,
        runtime_root=args.runtime_root,
        activate=not args.no_activate,
        build_vector_index=not args.skip_vector_index,
        runtime_env_name=args.runtime_env_name,
    )
    local_smoke = local_kbqa_smoke(kg) if args.verify else []

    report_dir = args.report_base / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "PASS",
        "metadata": metadata,
        "local_kbqa_smoke": local_smoke,
        "files": generated_files(args.out_dir),
    }
    report_path = report_dir / "prepare_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("status=PASS")
    print(f"processed_dir={args.out_dir}")
    print(f"runtime_env={metadata.get('runtime', {}).get('runtime_env', '')}")
    print(f"report={report_path}")
    print(f"entities={len(kg.entities)}")
    print(f"relations={len(kg.relations)}")
    print(f"triples={len(kg.triples)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"status=FAIL\nerror={type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
