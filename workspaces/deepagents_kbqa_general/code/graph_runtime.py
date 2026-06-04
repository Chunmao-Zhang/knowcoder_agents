"""Graph import and scope activation helpers for KBQA General.

Uploads are kept in a single graph ledger. The QA tools still read the normal
`runtime/general_env` directory; this module prepares that directory before a run
as either the full ledger or a derived single-graph scope.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .prepare import (
    DATA_ROOT,
    DEFAULT_RUNTIME_ROOT,
    build_prepared_kg_from_records,
    detect_format,
    generated_files,
    load_triples,
    write_processed_artifacts,
)


GRAPH_ROOT = DATA_ROOT / "graphs"
IMPORTS_DIR = GRAPH_ROOT / "imports"
REGISTRY_PATH = GRAPH_ROOT / "graph_registry.json"
LEDGER_PATH = GRAPH_ROOT / "all_triples.jsonl"
PROCESSED_ROOT = DATA_ROOT / "processed"
FULL_PROCESSED_DIR = PROCESSED_ROOT / "full"
SCOPE_PROCESSED_ROOT = PROCESSED_ROOT / "graph_scopes"
FULL_ENV_NAME = "full_env"
ACTIVE_ENV_NAME = "general_env"
SCOPE_ENV_PREFIX = "graph_scopes"
ACTIVE_SCOPE_PATH = DEFAULT_RUNTIME_ROOT / ACTIVE_ENV_NAME / "active_scope.json"
MAX_GRAPH_UPLOAD_BYTES = 64 * 1024 * 1024
SUPPORTED_SUFFIXES = {".txt", ".tsv", ".csv", ".kg", ".json", ".jsonl", ".ndjson", ".xlsx", ".xlsm"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slugify(value: str, fallback: str = "graph") -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-_").lower()
    return slug[:64] or fallback


def _safe_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower() or ".txt"
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Supported graph uploads: TXT/TSV/CSV, JSON/JSONL, XLSX.")
    return suffix


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
    data = read_json(REGISTRY_PATH, {"version": 1, "graphs": []})
    graphs = data.get("graphs") if isinstance(data, dict) else []
    return {"version": 1, "updated_at": data.get("updated_at") if isinstance(data, dict) else "", "graphs": graphs or []}


def write_registry(graphs: list[dict[str, Any]]) -> None:
    write_json_atomic(REGISTRY_PATH, {"version": 1, "updated_at": now_iso(), "graphs": graphs})


def list_graphs(limit: int | None = None) -> list[dict[str, Any]]:
    graphs = list(read_registry().get("graphs", []))
    graphs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return graphs[:limit] if limit else graphs


def get_graph(graph_id: str) -> dict[str, Any] | None:
    graph_id = str(graph_id or "").strip()
    if not graph_id:
        return None
    for item in read_registry().get("graphs", []):
        if item.get("id") == graph_id:
            return item
    return None


def iter_ledger_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not LEDGER_PATH.exists():
        return records
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def write_ledger_records(records: list[dict[str, Any]]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER_PATH.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(LEDGER_PATH)


def graph_records(graph_id: str | None = None) -> list[dict[str, Any]]:
    graph_id = str(graph_id or "").strip()
    records = iter_ledger_records()
    if not graph_id:
        return records
    if not get_graph(graph_id):
        raise ValueError(f"Unknown graph id: {graph_id}")
    return [record for record in records if record.get("graph_id") == graph_id]


def build_dense_subgraph(
    records: list[dict[str, Any]],
    node_counts: Counter[str],
    node_out_counts: Counter[str],
    node_in_counts: Counter[str],
    relation_counts: Counter[str],
    node_limit: int = 15,
    edge_limit: int = 32,
) -> dict[str, Any]:
    """Pick a compact, high-density connected subgraph for SVG rendering."""

    pair_relations: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    adjacency: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        subject = str(record.get("subject") or "")
        relation = str(record.get("relation") or "")
        obj = str(record.get("object") or "")
        if not subject or not relation or not obj:
            continue
        pair_relations[(subject, obj)][relation] += 1
        adjacency[subject][obj] += 1
        adjacency[obj][subject] += 1

    if not pair_relations:
        return {
            "nodes": [],
            "edges": [],
            "summary": {"node_count": 0, "edge_count": 0, "density": 0, "focus_node": ""},
        }

    neighbor_cache: dict[str, list[str]] = {}

    def ranked_neighbors(node: str) -> list[str]:
        if node not in neighbor_cache:
            neighbors = adjacency.get(node, Counter())
            neighbor_cache[node] = [
                name
                for name, _ in sorted(
                    neighbors.items(),
                    key=lambda item: (item[1], node_counts[item[0]], item[0]),
                    reverse=True,
                )[:360]
            ]
        return neighbor_cache[node]

    def internal_edge_weight(selected: set[str]) -> int:
        return sum(
            sum(relations.values())
            for (source, target), relations in pair_relations.items()
            if source in selected and target in selected
        )

    def grow_from(seed: str) -> list[str]:
        selected = [seed]
        selected_set = {seed}
        while len(selected) < node_limit:
            candidates: set[str] = set()
            for node in selected:
                candidates.update(ranked_neighbors(node))
            candidates.difference_update(selected_set)
            if not candidates:
                break

            best_node = ""
            best_score = -1.0
            for candidate in candidates:
                links_to_selected = sum(adjacency[candidate].get(node, 0) for node in selected_set)
                if links_to_selected <= 0:
                    continue
                # Prioritize added internal edges first, then favor graph-significant nodes.
                score = (
                    links_to_selected * 10000
                    + min(node_counts[candidate], 5000) * 3
                    + node_out_counts[candidate] * 2
                    + node_in_counts[candidate]
                )
                if score > best_score:
                    best_node = candidate
                    best_score = score

            if not best_node:
                break
            selected.append(best_node)
            selected_set.add(best_node)
        return selected

    best_nodes: list[str] = []
    best_score = -1.0
    seeds = [name for name, _ in node_counts.most_common(80)]
    for seed in seeds:
        selected = grow_from(seed)
        selected_set = set(selected)
        edge_weight = internal_edge_weight(selected_set)
        possible_edges = max(1, len(selected_set) * (len(selected_set) - 1))
        density = edge_weight / possible_edges
        degree_sum = sum(node_counts[node] for node in selected_set)
        score = edge_weight * 10000 + density * 2500 + degree_sum
        if score > best_score:
            best_nodes = selected
            best_score = score

    if not best_nodes:
        best_nodes = [name for name, _ in node_counts.most_common(node_limit)]

    selected_set = set(best_nodes)
    best_nodes = sorted(
        best_nodes,
        key=lambda node: (
            sum(adjacency[node].get(other, 0) for other in selected_set if other != node),
            node_counts[node],
            node_out_counts[node],
            node,
        ),
        reverse=True,
    )
    edge_rows: list[dict[str, Any]] = []
    for (source, target), relations in pair_relations.items():
        if source not in selected_set or target not in selected_set:
            continue
        relation, relation_pair_count = relations.most_common(1)[0]
        edge_rows.append(
            {
                "source": source,
                "target": target,
                "relation": relation,
                "relations": [
                    {"name": rel, "count": count}
                    for rel, count in relations.most_common(4)
                ],
                "weight": sum(relations.values()),
                "support": relation_counts.get(relation, 0),
                "label": relation if len(relations) == 1 else f"{relation} +{len(relations) - 1}",
                "pair_count": relation_pair_count,
            }
        )

    edge_rows.sort(
        key=lambda edge: (
            edge["weight"],
            edge["support"],
            node_counts[edge["source"]] + node_counts[edge["target"]],
            edge["source"],
            edge["target"],
        ),
        reverse=True,
    )
    edges = edge_rows[:edge_limit]
    visible_nodes = selected_set
    if edges:
        visible_nodes = {edge["source"] for edge in edges} | {edge["target"] for edge in edges}
        visible_nodes.update(best_nodes[: min(len(best_nodes), node_limit)])

    ordered_nodes = [
        node for node in best_nodes if node in visible_nodes
    ] + [
        node
        for node in sorted(visible_nodes, key=lambda item: (node_counts[item], item), reverse=True)
        if node not in best_nodes
    ]
    ordered_nodes = ordered_nodes[:node_limit]
    ordered_node_set = set(ordered_nodes)
    edges = [
        edge
        for edge in edges
        if edge["source"] in ordered_node_set and edge["target"] in ordered_node_set
    ]
    edge_weight = sum(edge["weight"] for edge in edges)
    possible_edges = max(1, len(ordered_nodes) * (len(ordered_nodes) - 1))

    nodes = [
        {
            "id": name,
            "label": name,
            "rank": index + 1,
            "weight": node_counts.get(name, 0),
            "out": node_out_counts.get(name, 0),
            "in": node_in_counts.get(name, 0),
            "role": "focus" if index == 0 else "core" if index < 7 else "neighbor",
        }
        for index, name in enumerate(ordered_nodes)
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "density": round(edge_weight / possible_edges, 4),
            "focus_node": ordered_nodes[0] if ordered_nodes else "",
            "selection": "top15_dense_connected_scope",
        },
    }


def summarize_graph(graph_id: str | None = None, sample_limit: int = 10, top_limit: int = 10) -> dict[str, Any]:
    """Return lightweight graph samples and frequency summaries for the UI."""

    graph_id = str(graph_id or "").strip()
    graph = get_graph(graph_id) if graph_id else None
    if graph_id and not graph:
        raise ValueError(f"Unknown graph id: {graph_id}")

    records = graph_records(graph_id)
    node_counts: Counter[str] = Counter()
    node_out_counts: Counter[str] = Counter()
    node_in_counts: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()
    relation_examples: dict[str, dict[str, str]] = {}
    sample_nodes: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()

    for record in records:
        subject = str(record.get("subject") or "")
        relation = str(record.get("relation") or "")
        obj = str(record.get("object") or "")
        if not subject or not relation or not obj:
            continue

        node_counts.update([subject, obj])
        node_out_counts[subject] += 1
        node_in_counts[obj] += 1
        relation_counts[relation] += 1
        relation_examples.setdefault(
            relation,
            {"subject": subject, "relation": relation, "object": obj},
        )

        for node in (subject, obj):
            if node not in seen_nodes and len(sample_nodes) < sample_limit:
                seen_nodes.add(node)
                sample_nodes.append({"name": node, "role": "entity"})

    sample_relations = [
        {
            "name": relation,
            "count": count,
            "example": relation_examples.get(relation, {}),
        }
        for relation, count in relation_counts.most_common(sample_limit)
    ]
    sample_triples = [
        {
            "subject": str(record.get("subject") or ""),
            "relation": str(record.get("relation") or ""),
            "object": str(record.get("object") or ""),
            "graph_id": str(record.get("graph_id") or ""),
            "graph_name": str(record.get("graph_name") or ""),
        }
        for record in records[:sample_limit]
    ]
    top_nodes = [
        {
            "name": name,
            "count": count,
            "out": node_out_counts.get(name, 0),
            "in": node_in_counts.get(name, 0),
        }
        for name, count in node_counts.most_common(top_limit)
    ]
    top_relations = [
        {
            "name": relation,
            "count": count,
            "example": relation_examples.get(relation, {}),
        }
        for relation, count in relation_counts.most_common(top_limit)
    ]

    return {
        "scope": {
            "mode": "single" if graph_id else "all",
            "graph_id": graph_id,
            "graph_name": (graph or {}).get("name") or "All graphs",
        },
        "stats": {
            "entity_count": len(node_counts),
            "relation_count": len(relation_counts),
            "triple_count": sum(relation_counts.values()),
            "graph_count": 1 if graph_id and records else len({record.get("graph_id") for record in records if record.get("graph_id")}),
        },
        "sample_nodes": sample_nodes,
        "sample_relations": sample_relations,
        "sample_triples": sample_triples,
        "top_nodes": top_nodes,
        "top_relations": top_relations,
        "dense_subgraph": build_dense_subgraph(
            records,
            node_counts,
            node_out_counts,
            node_in_counts,
            relation_counts,
        ),
    }


def write_source_snapshot(records: list[dict[str, Any]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    source_path = out_dir / "source_triples.jsonl"
    with source_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return source_path


def _stats_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_count": metadata.get("entity_count"),
        "relation_count": metadata.get("relation_count"),
        "triple_count": metadata.get("triple_count"),
        "graph_count": metadata.get("graph_count"),
        "generated_at": metadata.get("generated_at"),
    }


def _runtime_env(env_name: str) -> Path:
    return DEFAULT_RUNTIME_ROOT / env_name


def build_runtime_from_records(
    records: list[dict[str, Any]],
    out_dir: Path,
    runtime_env_name: str,
    build_vector_index: bool = True,
) -> dict[str, Any]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    kg = build_prepared_kg_from_records(records, source_format="jsonl")
    source_path = write_source_snapshot(records, out_dir)
    return write_processed_artifacts(
        kg,
        source_path,
        out_dir,
        runtime_root=DEFAULT_RUNTIME_ROOT,
        activate=True,
        build_vector_index=build_vector_index,
        runtime_env_name=runtime_env_name,
    )


def rebuild_full_runtime(build_vector_index: bool = True) -> dict[str, Any]:
    records = iter_ledger_records()
    if not records:
        raise ValueError("No uploaded graph records found. Upload a graph first.")
    return build_runtime_from_records(records, FULL_PROCESSED_DIR, FULL_ENV_NAME, build_vector_index=build_vector_index)


def ensure_full_runtime() -> Path:
    env = _runtime_env(FULL_ENV_NAME)
    if not (env / "active_graph.json").exists():
        rebuild_full_runtime()
    return env


def build_scope_runtime(graph_id: str, build_vector_index: bool = True, force: bool = False) -> Path:
    graph = get_graph(graph_id)
    if not graph:
        raise ValueError(f"Unknown graph id: {graph_id}")
    safe_id = slugify(graph_id, "graph")
    env_name = f"{SCOPE_ENV_PREFIX}/{safe_id}"
    env = _runtime_env(env_name)
    if force or not (env / "active_graph.json").exists():
        records = [record for record in iter_ledger_records() if record.get("graph_id") == graph_id]
        if not records:
            raise ValueError(f"No triples found for graph id: {graph_id}")
        build_runtime_from_records(records, SCOPE_PROCESSED_ROOT / safe_id, env_name, build_vector_index=build_vector_index)
    return env


def reset_tool_runtime_caches(runtime_env: Path | None = None) -> None:
    module = sys.modules.get("workspaces.deepagents_kbqa_general.tools_impl.build_subgraph_schema")
    if module is None:
        return
    if runtime_env is not None:
        info_dir = runtime_env / "graph-info"
        updates = {
            "_GENERAL_ENV": runtime_env,
            "_SQLITE_PATH": runtime_env / "graph.sqlite",
            "_CHROMA_PATH": runtime_env / "db_vector_chroma_general",
            "_INFO_DIR": info_dir,
            "_REL2DESC_PATH": info_dir / "rel2desc.json",
            "_REL2DES_CLEANED_PATH": info_dir / "rel2des_cleaned.json",
            "_CVT_LIST_PATH": runtime_env / "cvt_properties.txt",
            "_CVT_2HOP_PATH": info_dir / "cvt_predicate_onehop.jsonl",
            "_LEGACY_GENERAL_BGE_MODEL_PATH": runtime_env / "embedding_model" / "retriver_webqsp-cwq_relation",
        }
        for name, value in updates.items():
            if hasattr(module, name):
                setattr(module, name, value)
    conn_local = getattr(module, "_sqlite_conn_local", None)
    conn = getattr(conn_local, "conn", None) if conn_local is not None else None
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    if conn_local is not None:
        for attr in ("conn", "path"):
            if hasattr(conn_local, attr):
                try:
                    delattr(conn_local, attr)
                except Exception:
                    pass
    for name in (
        "_chroma_client",
        "_chroma_pred_col",
        "_chroma_entity_col",
        "_rel2desc",
        "_rel2des_cleaned",
        "_cvt_set",
        "_cvt_2hop",
    ):
        if hasattr(module, name):
            setattr(module, name, None)
    cache = getattr(module, "_result_cache", None)
    if cache is not None:
        try:
            cache.clear()
        except Exception:
            pass


def copy_runtime_env(src_env: Path, dst_env: Path) -> None:
    if not src_env.exists():
        raise FileNotFoundError(f"Runtime scope not found: {src_env}")
    dst_env.parent.mkdir(parents=True, exist_ok=True)
    tmp_env = dst_env.parent / f".{dst_env.name}.tmp"
    if tmp_env.exists():
        shutil.rmtree(tmp_env)
    shutil.copytree(src_env, tmp_env)
    if dst_env.exists():
        shutil.rmtree(dst_env)
    tmp_env.replace(dst_env)


def active_scope_metadata(graph_id: str | None = None) -> dict[str, Any]:
    if graph_id:
        graph = get_graph(graph_id)
        if not graph:
            raise ValueError(f"Unknown graph id: {graph_id}")
        return {
            "mode": "single",
            "graph_id": graph["id"],
            "graph_name": graph.get("name") or graph["id"],
            "activated_at": now_iso(),
        }
    return {
        "mode": "all",
        "graph_id": "",
        "graph_name": "All graphs",
        "activated_at": now_iso(),
    }


def activate_graph_scope(graph_id: str | None = None) -> dict[str, Any]:
    graph_id = str(graph_id or "").strip()
    if graph_id:
        src_env = build_scope_runtime(graph_id)
    else:
        src_env = ensure_full_runtime()
    active_env = _runtime_env(ACTIVE_ENV_NAME)
    os.environ["KBQA_GENERAL_ENV"] = str(src_env)
    reset_tool_runtime_caches(src_env)
    copy_runtime_env(src_env, active_env)
    scope = active_scope_metadata(graph_id or None)
    scope["runtime_env"] = str(active_env)
    scope["tool_runtime_env"] = str(src_env)
    write_json_atomic(ACTIVE_SCOPE_PATH, scope)
    reset_tool_runtime_caches(src_env)
    return scope


def read_active_scope() -> dict[str, Any]:
    return read_json(ACTIVE_SCOPE_PATH, {"mode": "all", "graph_id": "", "graph_name": "All graphs"})


def import_uploaded_graph(filename: str, raw_content: bytes, graph_name: str = "") -> dict[str, Any]:
    if len(raw_content) > MAX_GRAPH_UPLOAD_BYTES:
        raise ValueError(f"Upload exceeds {MAX_GRAPH_UPLOAD_BYTES // (1024 * 1024)}MB limit")

    suffix = _safe_suffix(filename)
    graph_id = str(uuid4())
    display_name = (graph_name or "").strip() or Path(filename or "graph").stem or f"Graph {graph_id[:8]}"
    graph_dir = IMPORTS_DIR / graph_id
    graph_dir.mkdir(parents=True, exist_ok=True)
    raw_path = graph_dir / f"source{suffix}"
    raw_path.write_bytes(raw_content)

    fmt = detect_format(raw_path)
    loaded = load_triples(raw_path, fmt)
    records = [
        {
            "graph_id": graph_id,
            "graph_name": display_name,
            "subject": subject,
            "relation": relation,
            "object": obj,
        }
        for subject, relation, obj in loaded.triples
    ]

    all_records = iter_ledger_records()
    all_records.extend(records)
    write_ledger_records(all_records)

    graph_stats = {
        "entity_count": len({item["subject"] for item in records} | {item["object"] for item in records}),
        "relation_count": len({item["relation"] for item in records}),
        "triple_count": len(records),
    }
    graph_entry = {
        "id": graph_id,
        "name": display_name,
        "created_at": now_iso(),
        "source_filename": filename,
        "raw_path": str(raw_path),
        "format": fmt,
        "stats": graph_stats,
    }
    graphs = [item for item in read_registry().get("graphs", []) if item.get("id") != graph_id]
    graphs.append(graph_entry)
    write_registry(graphs)

    full_metadata = rebuild_full_runtime()
    activate_graph_scope(None)
    graph_entry["full_runtime_stats"] = _stats_from_metadata(full_metadata)
    graph_entry["processed_dir"] = str(FULL_PROCESSED_DIR)
    graph_entry["files"] = generated_files(FULL_PROCESSED_DIR)
    graph_entry["active_graph_updated"] = True
    graph_entry["note"] = (
        "Graph triples were appended to the shared graph ledger. Default QA uses the full graph; "
        "the frontend graph selector activates a derived single-graph runtime before tool calls."
    )
    graphs = [item if item.get("id") != graph_id else graph_entry for item in read_registry().get("graphs", [])]
    write_registry(graphs)
    return graph_entry


def delete_graph(graph_id: str) -> dict[str, Any]:
    """Delete one uploaded graph and rebuild the active all-graphs runtime."""

    graph_id = str(graph_id or "").strip()
    graph = get_graph(graph_id)
    if not graph:
        raise ValueError(f"Unknown graph id: {graph_id}")

    records = iter_ledger_records()
    remaining = [record for record in records if record.get("graph_id") != graph_id]
    removed_triples = len(records) - len(remaining)
    write_ledger_records(remaining)
    write_registry([item for item in read_registry().get("graphs", []) if item.get("id") != graph_id])

    safe_id = slugify(graph_id, "graph")
    for path in (
        IMPORTS_DIR / graph_id,
        SCOPE_PROCESSED_ROOT / safe_id,
        _runtime_env(f"{SCOPE_ENV_PREFIX}/{safe_id}"),
    ):
        if path.exists():
            shutil.rmtree(path)

    if remaining:
        # Deletion should return quickly in the UI. Rebuilding Chroma for a
        # 100k+ triple ledger can take minutes, while SQLite/graph files are
        # enough for the catalog and lexical tool fallbacks after deletion.
        full_metadata = rebuild_full_runtime(build_vector_index=False)
        scope = activate_graph_scope(None)
        stats = _stats_from_metadata(full_metadata)
    else:
        for path in (FULL_PROCESSED_DIR, _runtime_env(FULL_ENV_NAME), _runtime_env(ACTIVE_ENV_NAME)):
            if path.exists():
                shutil.rmtree(path)
        active_env = _runtime_env(ACTIVE_ENV_NAME)
        active_env.mkdir(parents=True, exist_ok=True)
        scope = active_scope_metadata(None)
        scope["runtime_env"] = str(active_env)
        scope["tool_runtime_env"] = ""
        write_json_atomic(ACTIVE_SCOPE_PATH, scope)
        reset_tool_runtime_caches(active_env)
        stats = {"entity_count": 0, "relation_count": 0, "triple_count": 0, "graph_count": 0}

    return {
        "deleted": {
            "id": graph_id,
            "name": graph.get("name") or graph_id,
            "triple_count": removed_triples,
        },
        "remaining_graphs": len(list_graphs()),
        "graph_runtime": stats,
        "graph_scope": scope,
    }
