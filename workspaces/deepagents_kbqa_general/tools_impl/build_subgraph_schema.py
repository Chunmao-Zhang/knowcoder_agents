"""Build generic file-backed KBQA subgraph schemas.

This keeps the original DeepAgents KBQA tool contract: tools choose entities and
predicates, `build_subgraph_schema` materializes a typed Python schema plus a
subgraph JSON file, and `execute_code` runs reasoning code over that file. The
External KG endpoint and identifier assumptions are replaced by a local SQLite graph
store and ChromaDB/BGE vector indexes prepared by `code/prepare.py`.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid as _uuid
from collections import OrderedDict, defaultdict
from functools import wraps
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")

from loguru import logger

from .paths import REPO_ROOT, WORKSPACE_EMBEDDING_MODEL, configure_environment, get_general_env


def timeit(name):
    def decorator(func):
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return sync_wrapper
    return decorator


_RUNTIME_ROOT = configure_environment()
_GENERAL_ENV = get_general_env()
_SQLITE_PATH = _GENERAL_ENV / "graph.sqlite"
_CHROMA_PATH = _GENERAL_ENV / "db_vector_chroma_general"
_INFO_DIR = _GENERAL_ENV / "graph-info"
_REL2DESC_PATH = _INFO_DIR / "rel2desc.json"
_REL2DES_CLEANED_PATH = _INFO_DIR / "rel2des_cleaned.json"
_CVT_LIST_PATH = _GENERAL_ENV / "cvt_properties.txt"
_CVT_2HOP_PATH = _INFO_DIR / "cvt_predicate_onehop.jsonl"
_BGE_MODEL_PATH = WORKSPACE_EMBEDDING_MODEL
_LEGACY_GENERAL_BGE_MODEL_PATH = _GENERAL_ENV / "embedding_model" / "retriver_webqsp-cwq_relation"
_LEGACY_FREEBASE_BGE_MODEL_PATH = (
    REPO_ROOT
    / "data"
    / "deepagents_kbqa"
    / "runtime"
    / "freebase_env"
    / "embedding_model"
    / "retriver_webqsp-cwq_relation"
)

MAX_TRIPLETS = int(os.getenv("KBQA_MAX_TRIPLETS", "8000"))
TRIPLET_LIMIT_PER_PRED = int(os.getenv("KBQA_TRIPLET_LIMIT", "500"))
BUILD_SUBGRAPH_TIMEOUT = int(os.getenv("KBQA_BUILD_SUBGRAPH_TIMEOUT", "180"))
_INTERNAL_PREDICATE_CAP = int(os.getenv("KBQA_INTERNAL_PREDICATE_CAP", "20"))
_RESULT_CACHE_MAX = int(os.getenv("KBQA_BUILD_SUBGRAPH_CACHE_MAX", "2048"))

_lock = threading.Lock()
_bge_model = None
_bge_encode_lock = threading.Lock()
_chroma_client = None
_chroma_pred_col = None
_chroma_entity_col = None
_sqlite_conn_local = threading.local()
_rel2desc: Optional[Dict[str, List[str]]] = None
_rel2des_cleaned: Optional[Dict[str, List[str]]] = None
_cvt_set: Optional[Set[str]] = None
_cvt_2hop: Optional[Dict[str, List[str]]] = None
_rel2desc_class_re = re.compile(r"(?:head|tail) entity is '([^']+)'")
_result_cache: "OrderedDict[Tuple, str]" = OrderedDict()
_result_cache_lock = threading.Lock()


def _make_cache_key(start_entity_names, predicates, hop) -> Tuple:
    return (frozenset(start_entity_names), tuple(predicates), int(hop))


def _result_cache_get(key: Tuple) -> Optional[str]:
    with _result_cache_lock:
        value = _result_cache.get(key)
        if value is not None:
            _result_cache.move_to_end(key)
        return value


def _result_cache_put(key: Tuple, value: str) -> None:
    with _result_cache_lock:
        _result_cache[key] = value
        _result_cache.move_to_end(key)
        while len(_result_cache) > _RESULT_CACHE_MAX:
            _result_cache.popitem(last=False)


def _sanitize_attr(value: str) -> str:
    attr = re.sub(r"\W+", "_", str(value)).strip("_")
    if not attr:
        attr = "relation"
    if attr[0].isdigit():
        attr = f"rel_{attr}"
    return attr


def _sanitize_class(value: str) -> str:
    cls = re.sub(r"\W+", "_", str(value)).strip("_")
    if not cls:
        cls = "Entity"
    cls = "".join(part.capitalize() for part in cls.split("_") if part) or "Entity"
    if cls[0].isdigit():
        cls = f"Type{cls}"
    return cls


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text).lower()))


def _get_model_path() -> Path:
    if _BGE_MODEL_PATH.exists():
        return _BGE_MODEL_PATH
    if _LEGACY_GENERAL_BGE_MODEL_PATH.exists():
        return _LEGACY_GENERAL_BGE_MODEL_PATH
    return _LEGACY_FREEBASE_BGE_MODEL_PATH


def _get_bge_model():
    global _bge_model
    if _bge_model is None:
        with _lock:
            if _bge_model is None:
                from sentence_transformers import SentenceTransformer
                model_path = _get_model_path()
                if not model_path.exists():
                    raise FileNotFoundError(
                        f"BGE model not found: {model_path}. Run workspaces/deepagents_kbqa_general/code/prepare.py first."
                    )
                logger.info(f"Loading generic KBQA embedding model: {model_path}")
                _bge_model = SentenceTransformer(str(model_path), device="cpu")
    return _bge_model


def _get_conn() -> sqlite3.Connection:
    conn = getattr(_sqlite_conn_local, "conn", None)
    conn_path = getattr(_sqlite_conn_local, "path", None)
    if conn is None or conn_path != str(_SQLITE_PATH):
        if not _SQLITE_PATH.exists():
            raise FileNotFoundError(
                f"Active graph SQLite store not found at {_SQLITE_PATH}. "
                "Upload a graph in the frontend or run code/prepare.py."
            )
        conn = sqlite3.connect(str(_SQLITE_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _sqlite_conn_local.conn = conn
        _sqlite_conn_local.path = str(_SQLITE_PATH)
    return conn


def _get_sqlite_cursor():
    return _get_conn().cursor()


def _get_chroma():
    global _chroma_client, _chroma_pred_col, _chroma_entity_col
    if _chroma_pred_col is None:
        with _lock:
            if _chroma_pred_col is None:
                import chromadb
                if not _CHROMA_PATH.exists():
                    raise FileNotFoundError(
                        f"ChromaDB index not found at {_CHROMA_PATH}. Run code/prepare.py to encode entities and relations."
                    )
                _chroma_client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
                _chroma_pred_col = _chroma_client.get_collection("general_predicates")
                _chroma_entity_col = _chroma_client.get_collection("general_entities")
    return _chroma_pred_col, _chroma_entity_col


def _load_rel2desc_from_sqlite() -> Dict[str, List[str]]:
    try:
        rows = _get_conn().execute("SELECT relation, description FROM relations ORDER BY relation").fetchall()
    except Exception:
        return {}
    return {
        row["relation"]: [
            "The type of its head entity is 'Entity'.",
            "The type of its tail entity is 'Entity'.",
            row["description"] or "",
        ]
        for row in rows
    }


def _get_rel2desc() -> Dict[str, List[str]]:
    global _rel2desc
    if _rel2desc is None:
        with _lock:
            if _rel2desc is None:
                if _REL2DESC_PATH.exists():
                    _rel2desc = json.loads(_REL2DESC_PATH.read_text(encoding="utf-8"))
                else:
                    _rel2desc = _load_rel2desc_from_sqlite()
    return _rel2desc


def _get_rel2des_cleaned() -> Dict[str, List[str]]:
    global _rel2des_cleaned
    if _rel2des_cleaned is None:
        with _lock:
            if _rel2des_cleaned is None:
                if _REL2DES_CLEANED_PATH.exists():
                    _rel2des_cleaned = json.loads(_REL2DES_CLEANED_PATH.read_text(encoding="utf-8"))
                else:
                    _rel2des_cleaned = _get_rel2desc()
    return _rel2des_cleaned


def _get_cvt_set() -> Set[str]:
    global _cvt_set
    if _cvt_set is None:
        with _lock:
            if _cvt_set is None:
                if _CVT_LIST_PATH.exists():
                    _cvt_set = {line.strip() for line in _CVT_LIST_PATH.read_text(encoding="utf-8").splitlines() if line.strip()}
                else:
                    _cvt_set = set()
    return _cvt_set


def _get_cvt_2hop() -> Dict[str, List[str]]:
    global _cvt_2hop
    if _cvt_2hop is None:
        with _lock:
            if _cvt_2hop is None:
                data: Dict[str, List[str]] = {}
                if _CVT_2HOP_PATH.exists():
                    for line in _CVT_2HOP_PATH.read_text(encoding="utf-8").splitlines():
                        try:
                            item = json.loads(line)
                            key = str(item.get("key", "")).strip()
                            values = item.get("value", [])
                            if key and isinstance(values, list):
                                data[key] = [str(v) for v in values if str(v).strip()]
                        except Exception:
                            continue
                _cvt_2hop = data
    return _cvt_2hop


def prewarm_models():
    _get_bge_model()
    _get_chroma()
    _get_cvt_set()
    _get_cvt_2hop()
    _get_rel2desc()


def _cosine_rank(query: str, docs: list[str], top_k: int) -> list[int]:
    if not docs:
        return []
    import numpy as np
    bge = _get_bge_model()
    with _bge_encode_lock:
        q_emb = bge.encode([query], convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)[0]
        d_embs = bge.encode(docs, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
    scores = np.asarray(d_embs @ q_emb, dtype="float32")
    order = np.argsort(-scores)[:top_k]
    return [int(i) for i in order]


def _topk_preds_by_bge(query: str, preds: list, top_k: int) -> list:
    preds = [str(p) for p in preds if str(p)]
    if not preds:
        return []
    top_k = max(1, min(int(top_k or 10), len(preds)))
    rel2desc = _get_rel2desc()
    docs = []
    for pred in preds:
        desc = rel2desc.get(pred) or []
        docs.append(f"{pred.replace('_', ' ')}. {' '.join(str(x) for x in desc)}")
    try:
        return [preds[i] for i in _cosine_rank(query, docs, top_k)]
    except Exception as exc:
        logger.debug(f"BGE predicate rerank fallback: {exc}")
        q_tokens = set(_normalize(query).split())
        return sorted(preds, key=lambda p: -len(q_tokens & set(_normalize(p.replace('_', ' ')).split())))[:top_k]


def _query_chroma_collection(collection: Any, query: str, top_k: int) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    bge = _get_bge_model()
    with _bge_encode_lock:
        query_emb = bge.encode([query], convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)[0].tolist()
    res = collection.query(query_embeddings=[query_emb], n_results=max(1, int(top_k)))
    docs = res.get("documents", [[]])[0] or []
    metas = res.get("metadatas", [[]])[0] or []
    ids = res.get("ids", [[]])[0] or []
    return docs, metas, ids


def search_entities_by_text(query: str, top_k: int = 10, semantic_filter: str = "") -> list[dict[str, Any]]:
    query_text = query if not semantic_filter else f"{query}. {semantic_filter}"
    rows: list[dict[str, Any]] = []
    try:
        _, entity_col = _get_chroma()
        docs, metas, _ids = _query_chroma_collection(entity_col, query_text, max(top_k * 3, top_k))
        for doc, meta in zip(docs, metas):
            entity_name = str((meta or {}).get("entity_name") or (meta or {}).get("name") or "")
            if entity_name:
                rows.append({"entity_name": entity_name, "name": entity_name, "document": doc, "matched_by": "vector"})
    except Exception as exc:
        logger.debug(f"Chroma entity search fallback: {exc}")

    conn = _get_conn()
    norm = _normalize(query)
    if norm:
        for row in conn.execute(
            "SELECT name, document FROM entities WHERE name_norm = ? OR name LIKE ? ORDER BY triple_count DESC LIMIT ?",
            (norm, f"%{query}%", max(top_k * 3, top_k)),
        ):
            rows.append({"entity_name": row["name"], "name": row["name"], "document": row["document"], "matched_by": "lexical"})
    seen = set()
    deduped = []
    for row in rows:
        if row["entity_name"] in seen:
            continue
        seen.add(row["entity_name"])
        deduped.append(row)
        if len(deduped) >= top_k:
            break
    return deduped


def search_predicates_by_text(query: str, top_k: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        pred_col, _ = _get_chroma()
        docs, metas, _ids = _query_chroma_collection(pred_col, query, max(top_k * 2, top_k))
        for doc, meta in zip(docs, metas):
            pred = str((meta or {}).get("predicate") or (meta or {}).get("relation") or "")
            if pred:
                rows.append({"predicate": pred, "description": str((meta or {}).get("description") or doc or "")})
    except Exception as exc:
        logger.debug(f"Chroma predicate search fallback: {exc}")

    if not rows:
        conn = _get_conn()
        norm = _normalize(query)
        q_like = f"%{query}%"
        for row in conn.execute(
            "SELECT relation, description FROM relations WHERE relation_norm LIKE ? OR relation LIKE ? OR description LIKE ? ORDER BY triple_count DESC LIMIT ?",
            (f"%{norm}%", q_like, q_like, top_k),
        ):
            rows.append({"predicate": row["relation"], "description": row["description"]})
    seen = set()
    deduped = []
    for row in rows:
        pred = row["predicate"]
        if pred in seen:
            continue
        seen.add(pred)
        deduped.append(row)
        if len(deduped) >= top_k:
            break
    return deduped


def _get_entity_name(entity_name: str) -> str:
    return _get_entity_names_bulk([entity_name]).get(entity_name, entity_name)


def _get_entity_names_bulk(mids: List[str]) -> Dict[str, str]:
    if not mids:
        return {}
    conn = _get_conn()
    result = {str(mid): str(mid) for mid in mids}
    unique = list(dict.fromkeys(str(mid) for mid in mids if str(mid)))
    for batch_start in range(0, len(unique), 500):
        batch = unique[batch_start : batch_start + 500]
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(f"SELECT name FROM entities WHERE name IN ({placeholders})", batch).fetchall()
        for row in rows:
            result[row["name"]] = row["name"]
    return result


def _get_notable_type(mid_or_list) -> str:
    return "Entity"


def _get_type_from_pred(pred: str, side: str) -> str:
    raw = str(pred).removesuffix(".r")
    rel2desc = _get_rel2desc()
    desc_list = rel2desc.get(raw) or []
    if desc_list:
        target_desc = desc_list[0] if side == "head" else desc_list[1] if len(desc_list) > 1 else desc_list[-1]
        match = _rel2desc_class_re.search(target_desc)
        if match:
            return _sanitize_class(match.group(1))
    return "Entity"


def _predicate_counts(entity_name: str, direction: str) -> Dict[str, int]:
    conn = _get_conn()
    if direction == "out":
        rows = conn.execute(
            "SELECT relation, COUNT(DISTINCT object) AS cnt FROM triples WHERE subject = ? GROUP BY relation",
            (entity_name,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT relation, COUNT(DISTINCT subject) AS cnt FROM triples WHERE object = ? GROUP BY relation",
            (entity_name,),
        ).fetchall()
    return {row["relation"]: int(row["cnt"] or 0) for row in rows}


def local_search_entities_by_predicate(
    predicate: str,
    value: Any = None,
    semantic_filter: str = "",
    top_k: int = 50,
) -> list[dict[str, Any]]:
    pred = str(predicate).strip()
    is_reverse = pred.endswith(".r")
    raw_pred = pred.removesuffix(".r")
    conn = _get_conn()

    has_value = value is not None and (not isinstance(value, str) or value.strip())
    value_text = ""
    if has_value:
        value_text = str(value).strip()

    def _query(filter_col: str, select_col: str) -> list[dict[str, Any]]:
        params: list[Any] = [raw_pred]
        where = ["relation = ?"]
        if has_value:
            where.append(f"({filter_col} = ? OR lower({filter_col}) = lower(?) OR {filter_col} LIKE ?)")
            params.extend([value_text, value_text, f"%{value_text}%"])
        sql = f"SELECT DISTINCT {select_col} AS entity_name FROM triples WHERE {' AND '.join(where)} LIMIT ?"
        params.append(max(top_k * 5, top_k))
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

    # Primary behavior preserves the original literal-constraint lookup:
    #   p   + value -> subjects where object=value
    #   p.r + value -> objects where subject=value
    primary_filter_col = "subject" if is_reverse else "object"
    primary_select_col = "object" if is_reverse else "subject"
    rows = _query(primary_filter_col, primary_select_col)

    # Entity-grounded questions often use this tool as a traversal helper after
    # list_predicates_by_entity, e.g. directed_by.r + value=<director> -> movies.
    # If the literal-style lookup is empty, try the opposite endpoint before
    # returning "No matching entities found".
    if has_value and not rows:
        fallback_filter_col = "object" if is_reverse else "subject"
        fallback_select_col = "subject" if is_reverse else "object"
        rows = _query(fallback_filter_col, fallback_select_col)

    candidates = [str(row["entity_name"]) for row in rows if row.get("entity_name")]
    if semantic_filter and len(candidates) > 1:
        docs = []
        placeholders = ",".join("?" for _ in candidates)
        doc_rows = conn.execute(f"SELECT name, document FROM entities WHERE name IN ({placeholders})", candidates).fetchall()
        doc_map = {row["name"]: row["document"] for row in doc_rows}
        docs = [doc_map.get(entity, entity) for entity in candidates]
        try:
            order = _cosine_rank(semantic_filter, docs, len(candidates))
            candidates = [candidates[i] for i in order]
        except Exception:
            pass
    candidates = candidates[:top_k]
    return [{"entity_name": entity, "name": entity} for entity in candidates]


def _fetch_edges(entity_name: str, predicate: str, limit: int) -> list[tuple[str, str, str]]:
    conn = _get_conn()
    is_reverse = predicate.endswith(".r")
    raw_pred = predicate.removesuffix(".r")
    if is_reverse:
        rows = conn.execute(
            "SELECT subject FROM triples WHERE object = ? AND relation = ? LIMIT ?",
            (entity_name, raw_pred, limit),
        ).fetchall()
        return [(entity_name, f"{raw_pred}.r", row["subject"]) for row in rows]
    rows = conn.execute(
        "SELECT object FROM triples WHERE subject = ? AND relation = ? LIMIT ?",
        (entity_name, raw_pred, limit),
    ).fetchall()
    return [(entity_name, raw_pred, row["object"]) for row in rows]


def _fetch_k_hop(start_ids: list[str], predicates: list[str], hop: int, deadline: float) -> list[tuple[str, str, str]]:
    triplets: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    frontier = list(dict.fromkeys(start_ids))
    cvt_set = _get_cvt_set()
    cvt_2hop = _get_cvt_2hop()
    for _depth in range(max(1, int(hop or 1))):
        if time.monotonic() > deadline or len(triplets) >= MAX_TRIPLETS:
            break
        next_frontier: list[str] = []
        for entity_name in frontier:
            for pred in predicates:
                for edge in _fetch_edges(entity_name, pred, TRIPLET_LIMIT_PER_PRED):
                    if edge not in seen:
                        seen.add(edge)
                        triplets.append(edge)
                    tail = edge[2]
                    if tail not in next_frontier:
                        next_frontier.append(tail)
                    raw_pred = edge[1].removesuffix(".r")
                    if raw_pred in cvt_set:
                        for forced_pred in cvt_2hop.get(raw_pred, []):
                            for cvt_edge in _fetch_edges(tail, forced_pred, TRIPLET_LIMIT_PER_PRED):
                                if cvt_edge not in seen:
                                    seen.add(cvt_edge)
                                    triplets.append(cvt_edge)
                                if cvt_edge[2] not in next_frontier:
                                    next_frontier.append(cvt_edge[2])
                    if time.monotonic() > deadline or len(triplets) >= MAX_TRIPLETS:
                        break
                if time.monotonic() > deadline or len(triplets) >= MAX_TRIPLETS:
                    break
            if time.monotonic() > deadline or len(triplets) >= MAX_TRIPLETS:
                break
        frontier = next_frontier
        if not frontier:
            break
    return triplets[:MAX_TRIPLETS]


@timeit("build_ontology")
def build_ontology(triplets: List[Tuple[str, str, str]], topic_mids: List[str]) -> Tuple[List, Dict, Dict]:
    all_entities = list({str(elem) for t in triplets for elem in (t[0], t[2]) if elem is not None})
    mid_name_map = _get_entity_names_bulk(all_entities)
    type_relation_tuples = set()
    type_map: dict[str, list[str]] = defaultdict(list)
    entity_to_type: dict[str, str] = {}
    cvt_set = _get_cvt_set()

    for head, rel, tail in triplets:
        head = str(head)
        rel = str(rel)
        tail = str(tail)
        is_reverse = rel.endswith(".r")
        raw_rel = rel.removesuffix(".r")
        head_type = _get_type_from_pred(raw_rel, "tail" if is_reverse else "head")
        tail_type = _get_type_from_pred(raw_rel, "head" if is_reverse else "tail")
        if raw_rel in cvt_set:
            if is_reverse:
                head_type = head_type if head_type.endswith("CVT") else f"{head_type}CVT"
            else:
                tail_type = tail_type if tail_type.endswith("CVT") else f"{tail_type}CVT"
        for entity_name, typ in ((head, head_type), (tail, tail_type)):
            if entity_name not in type_map[typ]:
                type_map[typ].append(entity_name)
            entity_to_type[entity_name] = typ
        type_relation_tuples.add((head_type, rel, tail_type))

    return sorted(type_relation_tuples), dict(type_map), mid_name_map


def generate_class_code(
    type_relation_tuples: List,
    type_map: Dict,
    mid_name_map: Dict,
    topic_mids: List[str],
    query: str,
    max_entity_hint: int = 3,
) -> str:
    topic_set = set(topic_mids)
    classes: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for head_type, rel, tail_type in type_relation_tuples:
        classes[head_type].add((rel, tail_type))

    def _rank_ids(ids: List[str]) -> List[str]:
        topics = [m for m in ids if m in topic_set]
        others = [m for m in ids if m not in topic_set]
        return (topics + others)[:max_entity_hint]

    lines = ["from typing import List\n"]
    for cls_name, props in sorted(classes.items()):
        lines.append(f"\n\nclass {cls_name}:")
        ranked = _rank_ids(type_map.get(cls_name, []))
        name_parts = [f"{mid_name_map.get(m, m)}({m})" for m in ranked]
        if "CVT" in cls_name:
            lines.append("    # CVT-like mediator nodes, configured by graph metadata")
        elif name_parts:
            lines.append(f"    # entities like {', '.join(name_parts)} , etc.")
        deduped = []
        seen_attrs = set()
        for rel, tail_type in sorted(props, key=lambda item: item[0]):
            attr = _sanitize_attr(rel)
            if attr not in seen_attrs:
                seen_attrs.add(attr)
                deduped.append((rel, attr, tail_type))
        lines.append("    def __init__(self, _entity_name: str = None,")
        for idx, (_rel, attr, tail_type) in enumerate(deduped):
            comma = "," if idx < len(deduped) - 1 else ") :"
            lines.append(f"                 {attr}: List['{tail_type}'] = None{comma}")
        if not deduped:
            lines[-1] = lines[-1].rstrip(",") + ") :"
        lines.append("        self._entity_name = _entity_name")
        for _rel, attr, _tail_type in deduped:
            lines.append(f"        self.{attr} = {attr} or []")

    for cls_name, ids in sorted(type_map.items()):
        if cls_name in classes:
            continue
        lines.append(f"\n\nclass {cls_name}:")
        ranked = _rank_ids(ids)
        name_parts = [f"{mid_name_map.get(m, m)}({m})" for m in ranked]
        if "CVT" in cls_name:
            lines.append("    # CVT-like mediator nodes, configured by graph metadata")
        elif name_parts:
            lines.append(f"    # entities like {', '.join(name_parts)} , etc.")
        lines.append("    def __init__(self, _entity_name: str = None):")
        lines.append("        self._entity_name = _entity_name")
    return "\n".join(lines)


def _format_compact_triples(
    triplets: List[Tuple[str, str, str]],
    mid_name_map: Dict[str, str],
    type_map: Dict[str, List[str]],
    max_lines: int = 60,
) -> List[str]:
    lines = ["Representative triples:"]
    for head, rel, tail in triplets[:max_lines]:
        lines.append(f"  ({mid_name_map.get(str(head), str(head))}, {rel}, {mid_name_map.get(str(tail), str(tail))})")
    if len(triplets) > max_lines:
        lines.append(f"  ... {len(triplets) - max_lines} more triples omitted")
    return lines


def _format_entity_attr_presence(
    triplets: List[Tuple[str, str, str]],
    mid_name_map: Dict[str, str],
    start_entity_names: List[str],
    max_entities: int = 20,
) -> List[str]:
    """Compact table: which entities have which outgoing attributes populated."""
    head_pred_count: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    all_entity_set: Set[str] = set()
    for head, rel, tail in triplets:
        attr = _sanitize_attr(rel)
        head_pred_count[str(head)][attr] += 1
        all_entity_set.add(str(head))
        all_entity_set.add(str(tail))

    lines = [
        "",
        "Entity attribute presence (entity -> populated attrs with counts):",
        "# NOTE: *_r attrs (reverse predicates) are populated ONLY on head entities of that edge.",
        "# In execute_code, use start_entity_names as anchors; tail-only entities have NO outgoing *_r attrs.",
    ]
    shown = 0
    # Show start entities first
    ordered = list(start_entity_names)
    for ent in head_pred_count:
        if ent not in ordered:
            ordered.append(ent)
    # Also show tail-only entities (those with no outgoing attrs)
    for ent in all_entity_set:
        if ent not in ordered:
            ordered.append(ent)

    for ent in ordered:
        if shown >= max_entities:
            remaining = len(all_entity_set) - shown
            if remaining > 0:
                lines.append(f"  ... and {remaining} more entities")
            break
        name = mid_name_map.get(ent, ent)
        attrs = head_pred_count.get(ent, {})
        if attrs:
            attr_parts = [f"{a}({c})" for a, c in sorted(attrs.items())]
            lines.append(f"  {name}: {', '.join(attr_parts)}")
        else:
            lines.append(f"  {name}: (tail-only, no outgoing attrs in this subgraph)")
        shown += 1

    return lines


def _invalid_predicate_reason(original_predicates: List[str], clean_predicates: List[str]) -> Optional[str]:
    if not clean_predicates:
        return "empty predicate list"
    return None


def _build_invalid_predicate_hint(reason: str) -> str:
    return (
        f"[Error] Invalid build_subgraph_schema predicate: {reason}. "
        "Call list_predicates_by_entity again and pass exact predicates from the active graph."
    )


def build_subgraph_schema(
    start_entity_names: List[str] | None = None,
    predicates: List[str] | None = None,
    hop: int = 2,
    run_id: Optional[str] = None,
) -> str:
    """Load a generic graph subgraph and return Python class schema text.

    `start_entity_names` are exact entity name strings from the uploaded graph,
    usually copied from search_entity/search_entity_by_predicate. Incoming
    predicates use the `.r` suffix.
    """
    call_t0 = time.monotonic()
    deadline = call_t0 + max(1, int(os.getenv("KBQA_BUILD_SUBGRAPH_TIMEOUT", str(BUILD_SUBGRAPH_TIMEOUT))))
    clean_starts = []
    start_entity_names = start_entity_names or []
    for entity_name in start_entity_names:
        if isinstance(entity_name, str) and entity_name.strip() and entity_name.strip() not in clean_starts:
            clean_starts.append(entity_name.strip())
    if not clean_starts:
        return "[Error] build_subgraph_schema requires a non-empty `start_entity_names` list copied from search_entity."

    clean_predicates = []
    for pred in predicates or []:
        if isinstance(pred, str) and pred.strip() and pred.strip() not in clean_predicates:
            clean_predicates.append(pred.strip())
    if len(clean_predicates) > _INTERNAL_PREDICATE_CAP:
        clean_predicates = clean_predicates[:_INTERNAL_PREDICATE_CAP]
    invalid_reason = _invalid_predicate_reason(list(predicates or []), clean_predicates)
    if invalid_reason:
        return _build_invalid_predicate_hint(invalid_reason)

    cache_key = _make_cache_key(clean_starts, clean_predicates, hop)
    cached = _result_cache_get(cache_key)
    if cached:
        return cached

    try:
        triplets = _fetch_k_hop(clean_starts, clean_predicates, max(1, int(hop or 1)), deadline)
    except Exception as exc:
        return f"[Error] build_subgraph_schema failed to read the active graph: {type(exc).__name__}: {exc}"

    if not triplets:
        return (
            f"[Warning] No triples found for start_entity_names={clean_starts[:3]} predicates={clean_predicates[:5]}. "
            "Verify the entity names with search_entity and the predicates/directions with list_predicates_by_entity."
        )

    type_relation_tuples, type_map, mid_name_map = build_ontology(triplets, clean_starts)
    class_code = generate_class_code(
        type_relation_tuples,
        type_map,
        mid_name_map,
        topic_mids=clean_starts,
        query=", ".join(clean_predicates),
    )

    cache_dir = _RUNTIME_ROOT / "tools_impl" / ".subgraph_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fid = _uuid.uuid4().hex[:8]
    json_path = cache_dir / f"subgraph_{fid}.json"
    schema_path = cache_dir / f"schema_{fid}.txt"
    payload = {
        "triplets": triplets,
        "topic_mids": clean_starts,
        "predicates": clean_predicates,
        "hop": hop,
        "type_relation_tuples": type_relation_tuples,
        "type_map": type_map,
        "mid_name_map": mid_name_map,
        "active_graph": str(_GENERAL_ENV / "active_graph.json"),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    schema_path.write_text(class_code, encoding="utf-8")
    rel_json = json_path.relative_to(_RUNTIME_ROOT).as_posix()

    topic_names = ", ".join(mid_name_map.get(m, m) for m in clean_starts[:3])
    lines = [
        f"Subgraph retrieved for entity {topic_names}. Found {len(triplets)} triplets.",
        "Python class definitions for code-based reasoning:",
        "========================================",
        class_code,
        "========================================",
    ]
    lines.extend(_format_compact_triples(triplets, mid_name_map, type_map, max_lines=40))
    lines.extend(_format_entity_attr_presence(triplets, mid_name_map, clean_starts, max_entities=20))
    lines.append(f"# subgraph_file: {rel_json}")
    lines.append(f"# schema_file: {rel_json}")
    output = "\n".join(lines)
    _result_cache_put(cache_key, output)
    return output


# Compatibility name for older imports. Generic graphs do not use SPARQL.
def execute_sparql_sync(query: str) -> list:
    logger.debug("execute_sparql_sync is not used by deepagents_kbqa_general; returning no rows.")
    return []
