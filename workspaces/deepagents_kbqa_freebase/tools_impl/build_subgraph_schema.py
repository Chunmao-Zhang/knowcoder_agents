"""
kbqa_tool_build_subgraph_schema.py  —  build_subgraph_schema Tool for deepagents_kbqa
=====================================================================

功能：给定 start_mids + predicates，从 Freebase 检索 k 跳子图，
      生成 Python 类定义 (schema layer) + schema_file，供 LLM 通过 execute_code 做代码推理。

架构对齐（CoG pipeline/process.py）：
  1. 用 BGE 向量检索 top-k 相关谓词       ← CoG: evaluate_topk
  2. SPARQL 拉取命中谓词的三元组           ← CoG: recall_triplets
  3. CVT 节点自动展开（2 hop）             ← CoG: cvt_sec_hop 
  4. 构建 Ontology                        ← CoG: generate_ontology_info_ori
  5. 生成 Python 类定义                   ← CoG: generate_classes

输出格式（进入 LLM 上下文，约 3000-5000 tokens）:
  Subgraph retrieved for entity m.06w2sn5 (Justin Bieber). Found 24 triplets.
  Python class definitions for code-based reasoning:
  ========================================
  from typing import List
  class person:
      ...
  ========================================
  entities = []  # will be instantiated at execute_code time

运行时依赖：
  - Virtuoso SPARQL: http://127.0.0.1:8890/sparql
  - ChromaDB: freebase_env/db_vector_chroma_fb_v2/
  - SQLite:   freebase_env/freebase_entity_name.db
  - 关系检索模型: freebase_env/embedding_model/retriver_webqsp-cwq_relation
  - CVT list: freebase_env/fb_properties_expecting_cvt.txt
  - CVT 2hop: freebase_env/freebase-info/cvt_predicate_onehop.jsonl
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid as _uuid
from functools import wraps

def timeit(name):
    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start = time.time()
                res = await func(*args, **kwargs)
                # logger.info(f"[TIMER] {name} took {time.time() - start:.2f}s (async)")
                return res
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                start = time.time()
                res = func(*args, **kwargs)
                # logger.info(f"[TIMER] {name} took {time.time() - start:.2f}s (sync)")
                return res
            return sync_wrapper
    return decorator


import os
import re
import sqlite3
import sys
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# Cap OMP/MKL threads. Without this, each BGE `bge.encode()` defaults to using
# every CPU core (e.g. 128) for OpenMP parallelism. With _run_in_parallel firing
# N concurrent build_subgraph_schema calls, each touching BGE 4×, total OS
# threads explode to N × 128 and thrash the scheduler. Set BEFORE torch import.
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")

from loguru import logger

# ── 路径设置 ─────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
# _PROJECT_ROOT points to a workspace-managed runtime directory containing
# `freebase_env/`. It deliberately does not default to the deleted source tree.
from .paths import configure_environment

_PROJECT_ROOT = str(configure_environment())

# ══════════════════════════════════════════════════════════════════════════════
# 配置（可通过环境变量覆盖）
# ══════════════════════════════════════════════════════════════════════════════

SPARQL_ENDPOINT = os.getenv("SPARQL_ENDPOINT", "http://127.0.0.1:8890/sparql")
SPARQL_TIMEOUT = int(os.getenv("SPARQL_TIMEOUT", "60"))
MAX_TRIPLETS = int(os.getenv("KBQA_MAX_TRIPLETS", "8000"))
TRIPLET_LIMIT_PER_PRED = int(os.getenv("KBQA_TRIPLET_LIMIT", "200"))
# A3: total wall-clock cap for one build_subgraph_schema call (covers all internal SPARQL hops).
BUILD_SUBGRAPH_TIMEOUT = int(os.getenv("KBQA_BUILD_SUBGRAPH_TIMEOUT", "180"))
BUILD_SUBGRAPH_TIMEOUT_CACHE_TTL = int(os.getenv("KBQA_BUILD_SUBGRAPH_TIMEOUT_CACHE_TTL", "180"))
BUILD_SUBGRAPH_MAX_CONCURRENT = max(1, int(os.getenv("KBQA_BUILD_SUBGRAPH_MAX_CONCURRENT", "12")))
BFS_LOCAL_SPARQL_WORKERS = max(1, int(os.getenv("KBQA_BFS_LOCAL_SPARQL_WORKERS", "4")))
if os.getenv("KBQA_LOG_CONFIG", "0") == "1":
    print(
        f"[KBQA_TOOL_IMPORT] pid={os.getpid()} "
        f"SPARQL_TIMEOUT={SPARQL_TIMEOUT} (env={os.getenv('SPARQL_TIMEOUT', '<unset>')}) "
        f"BUILD_SUBGRAPH_TIMEOUT={BUILD_SUBGRAPH_TIMEOUT} (env={os.getenv('KBQA_BUILD_SUBGRAPH_TIMEOUT', '<unset>')}) "
        f"BUILD_SUBGRAPH_MAX_CONCURRENT={BUILD_SUBGRAPH_MAX_CONCURRENT} "
        f"BFS_LOCAL_SPARQL_WORKERS={BFS_LOCAL_SPARQL_WORKERS} "
        f"TIMEOUT_CACHE_TTL={BUILD_SUBGRAPH_TIMEOUT_CACHE_TTL}",
        flush=True,
    )

# ── Result LRU cache ───────────────────────────────────────────────────────
# GRPO samples N trajectories from the same prompt, so within one rollout
# step turn-K's 256-trajectory fan-out has very high collision rate on
# (start_mids, predicates, hop). Caching the final output_text skips the
# whole SPARQL+BFS+BGE+file-write pipeline on hit. Empirically (per
# scripts/benchmark_rollout_step.py): turn 2 went 254 calls × 2.67s mean →
# ~80s when ~70% of args repeat. Cap at 2048 entries (~10 MB).
_RESULT_CACHE_MAX = int(os.getenv("KBQA_BUILD_SUBGRAPH_CACHE_MAX", "2048"))
_result_cache: "OrderedDict[Tuple, str]" = OrderedDict()
_result_cache_lock = threading.Lock()
_result_cache_hits = 0
_result_cache_misses = 0
_result_inflight: Dict[Tuple, Dict[str, Any]] = {}
_result_inflight_lock = threading.Lock()
_timeout_cache: "OrderedDict[Tuple, Tuple[float, str]]" = OrderedDict()
_timeout_cache_lock = threading.Lock()
_timeout_cache_hits = 0
_timeout_cache_misses = 0


def _make_cache_key(start_mids, predicates, hop) -> Tuple:
    return (frozenset(start_mids), tuple(sorted(predicates)), int(hop))


def _result_cache_get(key: Tuple) -> Optional[str]:
    global _result_cache_hits, _result_cache_misses
    with _result_cache_lock:
        v = _result_cache.get(key)
        if v is None:
            _result_cache_misses += 1
            return None
        _result_cache.move_to_end(key)
        _result_cache_hits += 1
        return v


def _result_cache_put(key: Tuple, value: str) -> None:
    if not value or not isinstance(value, str):
        return
    with _result_cache_lock:
        _result_cache[key] = value
        _result_cache.move_to_end(key)
        while len(_result_cache) > _RESULT_CACHE_MAX:
            _result_cache.popitem(last=False)


def _timeout_cache_get(key: Tuple) -> Optional[str]:
    global _timeout_cache_hits, _timeout_cache_misses
    ttl = int(os.getenv("KBQA_BUILD_SUBGRAPH_TIMEOUT_CACHE_TTL", str(BUILD_SUBGRAPH_TIMEOUT_CACHE_TTL)))
    if ttl <= 0:
        return None
    now = time.monotonic()
    with _timeout_cache_lock:
        item = _timeout_cache.get(key)
        if item is None:
            _timeout_cache_misses += 1
            return None
        expires_at, value = item
        if now >= expires_at:
            _timeout_cache.pop(key, None)
            _timeout_cache_misses += 1
            return None
        _timeout_cache.move_to_end(key)
        _timeout_cache_hits += 1
        return value


def _timeout_cache_put(key: Tuple, value: str) -> None:
    if not value or not isinstance(value, str):
        return
    ttl = int(os.getenv("KBQA_BUILD_SUBGRAPH_TIMEOUT_CACHE_TTL", str(BUILD_SUBGRAPH_TIMEOUT_CACHE_TTL)))
    if ttl <= 0:
        return
    with _timeout_cache_lock:
        _timeout_cache[key] = (time.monotonic() + ttl, value)
        _timeout_cache.move_to_end(key)
        while len(_timeout_cache) > _RESULT_CACHE_MAX:
            _timeout_cache.popitem(last=False)


def _result_inflight_start(key: Tuple) -> Tuple[Dict[str, Any], bool]:
    with _result_inflight_lock:
        entry = _result_inflight.get(key)
        if entry is not None:
            return entry, False
        entry = {"event": threading.Event(), "value": None, "error": None}
        _result_inflight[key] = entry
        return entry, True


def _result_inflight_finish(key: Tuple, value: Optional[str] = None, error: Optional[BaseException] = None) -> None:
    with _result_inflight_lock:
        entry = _result_inflight.pop(key, None)
        if entry is None:
            return
        entry["value"] = value
        entry["error"] = error
        entry["event"].set()


def get_result_cache_stats() -> Tuple[int, int, int]:
    """Return (hits, misses, size) for telemetry; safe to call concurrently."""
    with _result_cache_lock:
        return _result_cache_hits, _result_cache_misses, len(_result_cache)


_FB_ENV = os.path.join(_PROJECT_ROOT, "freebase_env")
_INFO_DIR = os.path.join(_FB_ENV, "freebase-info")

_SQLITE_PATH = os.path.join(_FB_ENV, "freebase_entity_name.db")
_CHROMA_PATH = os.path.join(_FB_ENV, "db_vector_chroma_fb_v2")
_BGE_MODEL_PATH = os.path.join(_FB_ENV, "embedding_model", "retriver_webqsp-cwq_relation")
_CVT_LIST_PATH = os.path.join(_FB_ENV, "fb_properties_expecting_cvt.txt")
_CVT_2HOP_PATH = os.path.join(_INFO_DIR, "cvt_predicate_onehop.jsonl")
_REL2DESC_PATH = os.path.join(_INFO_DIR, "rel2desc.json")
_REL2DES_CLEANED_PATH = os.path.join(_INFO_DIR, "rel2des_cleaned.json")

# 过滤掉无意义谓词的前缀/关键词
_FILTER_PRED_PREFIXES = ("common.", "freebase.", "type.object.name")
_FILTER_PRED_KEYWORDS = ("has_no_value", "has_value", "common.topic.description")
_KEEP_PREDS = {"common.topic.image", "common.topic.type"}
_FB_NS = "http://rdf.freebase.com/ns/"


# ══════════════════════════════════════════════════════════════════════════════
# 懒加载单例：模型、ChromaDB、CVT 列表、SQLite
# ══════════════════════════════════════════════════════════════════════════════

_lock = threading.Lock()
_bge_model = None
# Global BGE encode lock: sentence-transformers single-instance is not
# thread-safe under heavy concurrency; without this lock, parallel encode()
# calls cause both correctness risk (model state mutation) and severe perf
# regression (kernel-level OMP thread thrashing).
_bge_encode_lock = threading.Lock()
_chroma_client = None
_chroma_pred_col = None
_chroma_cvt_col = None
_cvt_set: Optional[Set[str]] = None
_cvt_2hop: Optional[Dict[str, List[str]]] = None
_sqlite_conn_local = threading.local()
_rel2desc: Optional[Dict[str, List[str]]] = None
_rel2des_cleaned: Optional[Dict[str, List[str]]] = None
_rel2desc_class_re = re.compile(r"(?:head|tail) entity is '([^']+)'")


def _get_rel2desc() -> Dict[str, List[str]]:
    global _rel2desc
    if _rel2desc is None:
        with _lock:
            if _rel2desc is None:
                if os.path.exists(_REL2DESC_PATH):
                    with open(_REL2DESC_PATH, encoding="utf-8") as f:
                        _rel2desc = json.load(f)
                    logger.info(f"Loaded rel2desc: {len(_rel2desc)} entries")
                else:
                    logger.warning(f"rel2desc.json not found at {_REL2DESC_PATH}")
                    _rel2desc = {}
    return _rel2desc

def _get_rel2des_cleaned() -> Dict[str, List[str]]:
    global _rel2des_cleaned
    if _rel2des_cleaned is None:
        with _lock:
            if _rel2des_cleaned is None:
                if os.path.exists(_REL2DES_CLEANED_PATH):
                    with open(_REL2DES_CLEANED_PATH, "r", encoding="utf-8") as f:
                        _rel2des_cleaned = json.load(f)
                else:
                    _rel2des_cleaned = {}
    return _rel2des_cleaned


def _get_bge_model():
    global _bge_model
    if _bge_model is None:
        with _lock:
            if _bge_model is None:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading relation retrieval model: {_BGE_MODEL_PATH}")
                _bge_model = SentenceTransformer(_BGE_MODEL_PATH, device='cpu')
    return _bge_model


def _get_chroma():
    global _chroma_client, _chroma_pred_col, _chroma_cvt_col
    if _chroma_pred_col is None:
        with _lock:
            if _chroma_pred_col is None:
                import chromadb
                _chroma_client = chromadb.PersistentClient(path=_CHROMA_PATH)
                cols = {c.name: c for c in _chroma_client.list_collections()}
                pred_col = next((c for n, c in cols.items() if "predicate" in n and "cvt" not in n), None)
                cvt_col = next((c for n, c in cols.items() if "cvt-predicate-pair" in n), None)
                if pred_col is None:
                    raise RuntimeError("ChromaDB: predicate collection not found.")
                _chroma_pred_col = pred_col
                _chroma_cvt_col = cvt_col
    return _chroma_pred_col, _chroma_cvt_col


def prewarm_models():
    """主线程预加载所有单例，避免多线程引发的重复加载或死锁"""
    logger.info("Pre-warming models...")
    # Confirm critical env-derived timeout values actually reached this worker.
    print(
        f"[KBQA_TOOL_CONFIG] pid={os.getpid()} "
        f"SPARQL_TIMEOUT={SPARQL_TIMEOUT} "
        f"BUILD_SUBGRAPH_TIMEOUT={BUILD_SUBGRAPH_TIMEOUT} "
        f"SPARQL_MAX_WORKERS={_SPARQL_MAX_WORKERS} "
        f"SPARQL_ENDPOINT={SPARQL_ENDPOINT}",
        flush=True,
    )
    _get_bge_model()
    _get_chroma()
    _get_cvt_set()
    _get_cvt_2hop()
    _get_rel2desc()
    _get_rel2des_cleaned()


def _get_cvt_set() -> Set[str]:
    global _cvt_set
    if _cvt_set is None:
        with _lock:
            if _cvt_set is None:
                if os.path.exists(_CVT_LIST_PATH):
                    _cvt_set = set(l.strip() for l in open(_CVT_LIST_PATH) if l.strip())
                else:
                    _cvt_set = set()
    return _cvt_set


def _get_cvt_2hop() -> Dict[str, List[str]]:
    global _cvt_2hop
    if _cvt_2hop is None:
        with _lock:
            if _cvt_2hop is None:
                if os.path.exists(_CVT_2HOP_PATH):
                    _cvt_2hop = {}
                    with open(_CVT_2HOP_PATH, encoding="utf-8") as f:
                        for line in f:
                            try:
                                item = json.loads(line.strip())
                                _cvt_2hop[item["key"]] = item.get("value", [])
                            except Exception:
                                pass
                else:
                    _cvt_2hop = {}
    return _cvt_2hop


def _get_sqlite_cursor():
    if not hasattr(_sqlite_conn_local, "conn"):
        if not os.path.exists(_SQLITE_PATH):
            _sqlite_conn_local.conn = None
        else:
            _sqlite_conn_local.conn = sqlite3.connect(_SQLITE_PATH, check_same_thread=False)
    conn = _sqlite_conn_local.conn
    return conn.cursor() if conn else None


# ══════════════════════════════════════════════════════════════════════════════
# SPARQL 工具函数
# ══════════════════════════════════════════════════════════════════════════════

import concurrent.futures
import requests

# Per-process SPARQL HTTP pool. Keep it large enough for concurrent BFS calls;
# too small a pool causes Python-side queuing and tool-level timeouts. Override
# with SPARQL_MAX_WORKERS when needed.
_SPARQL_MAX_WORKERS = int(os.getenv("SPARQL_MAX_WORKERS", "30"))
_GLOBAL_SPARQL_EXECUTOR = None
_GLOBAL_SPARQL_EXECUTOR_LOCK = threading.Lock()

def _get_global_sparql_executor():
    """Lazy-init so Ray runtime_env env_vars are respected."""
    global _GLOBAL_SPARQL_EXECUTOR
    if _GLOBAL_SPARQL_EXECUTOR is None:
        with _GLOBAL_SPARQL_EXECUTOR_LOCK:
            if _GLOBAL_SPARQL_EXECUTOR is None:
                workers = int(os.getenv("SPARQL_MAX_WORKERS", str(_SPARQL_MAX_WORKERS)))
                _GLOBAL_SPARQL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
                print(f"[SPARQL_POOL_INIT] pid={os.getpid()} max_workers={workers}", flush=True)
    return _GLOBAL_SPARQL_EXECUTOR

# Per-call SPARQL executor (thread-local).  _fetch_k_hop_with_timeout sets
# this to a short-lived pool that is shut down on timeout, preventing zombie
# daemon threads from monopolising the global pool.  async_execute_sparql
# reads it to decide which pool to use.
_tl_sparql = threading.local()
_sparql_http_local = threading.local()

_BUILD_SUBGRAPH_SEMAPHORE = threading.BoundedSemaphore(BUILD_SUBGRAPH_MAX_CONCURRENT)

# fetch_relations 结果缓存（进程级，key=frozenset(mids)，热门实体只查一次 Virtuoso）
_rel_cache: dict = {}
_rel_cache_lock = threading.Lock()

def _get_sparql_http_session() -> requests.Session:
    """Thread-local HTTP session that never uses the cluster Squid proxy.

    The environment on this machine exports http_proxy/https_proxy.  requests
    honors those by default, even for 127.0.0.1, so SPARQL calls silently hit
    Squid and return 503 instead of reaching the local Virtuoso process.
    """
    sess = getattr(_sparql_http_local, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.trust_env = False
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1,
            pool_maxsize=1,
            max_retries=0,
        )
        sess.mount("http://", adapter)
        sess.mount("https://", adapter)
        _sparql_http_local.session = sess
    return sess

def execute_sparql_sync(query: str) -> list:
    """Execute one SPARQL query against Virtuoso."""
    # Read at call time so Ray runtime_env env_vars take effect even if
    # the module was imported before they were applied.
    _timeout = int(os.getenv("SPARQL_TIMEOUT", str(SPARQL_TIMEOUT)))
    try:
        _endpoint = os.getenv("SPARQL_ENDPOINT", SPARQL_ENDPOINT)
        resp = _get_sparql_http_session().post(
            _endpoint,
            data={"query": query, "format": "application/sparql-results+json"},
            headers={"Accept": "application/sparql-results+json"},
            timeout=_timeout
        )
        resp.raise_for_status()
        return resp.json().get("results", {}).get("bindings", [])
    except requests.exceptions.Timeout:
        return []
    except Exception as e:
        # logger.debug(f"Sync SPARQL error: {e}")
        return []

async def async_execute_sparql(query: str) -> list:
    loop = asyncio.get_running_loop()
    pool = getattr(_tl_sparql, 'pool', None) or _get_global_sparql_executor()
    return await loop.run_in_executor(pool, execute_sparql_sync, query)

def chunk_list(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i: i + size]

async def fetch_relations_batch(mids: list) -> dict:
    cache_key = frozenset(mids)
    with _rel_cache_lock:
        if cache_key in _rel_cache:
            return _rel_cache[cache_key]

    mids_ns = [m if m.startswith("ns:") else f"ns:{m}" for m in mids]
    values_block = " ".join(mids_ns)

    sparql = f"""
    PREFIX ns: <http://rdf.freebase.com/ns/>
    SELECT DISTINCT ?ent ?p ?dir WHERE {{
        {{
            VALUES ?ent {{ {values_block} }}
            ?ent ?p ?y .
            BIND("out" AS ?dir)
        }}
        UNION
        {{
            VALUES ?ent {{ {values_block} }}
            ?y ?p ?ent .
            BIND("in" AS ?dir)
        }}
    }}
    """
    res = await async_execute_sparql(sparql)
    entity_rel = {m.replace("ns:", ""): ([], []) for m in mids_ns}
    for row in res:
        ent = row["ent"]["value"].replace("http://rdf.freebase.com/ns/", "")
        p = row["p"]["value"].replace("http://rdf.freebase.com/ns/", "")
        d = row["dir"]["value"]
        if ent in entity_rel:
            in_list, out_list = entity_rel[ent]
            if d == "out": out_list.append(p)
            if d == "in": in_list.append(p)

    for ent in entity_rel:
        entity_rel[ent] = (list(set(entity_rel[ent][0])), list(set(entity_rel[ent][1])))

    with _rel_cache_lock:
        _rel_cache[cache_key] = entity_rel
    return entity_rel

@timeit('fetch_relations_all')
async def fetch_relations_all(mids: list, batch_size=50) -> dict:
    mids = list(set(mids))
    batches = list(chunk_list(mids, batch_size))
    
    async def _fetch_one(batch):
        return await fetch_relations_batch(batch)
    results = await asyncio.gather(*[_fetch_one(b) for b in batches])
    
    final_map = {}
    for batch_res in results:
        for ent, (in_l, out_l) in batch_res.items():
            final_map[ent] = (in_l, out_l)
    return final_map


@timeit('recall_triplets_async')
async def recall_triplets_async(entity_to_relations: dict, direction: str, batch_size=50, current_hop: int = 1):
    """Pull triplets matching `entity_to_relations` via batched SPARQL."""
    triplet_limit = int(os.getenv("KBQA_TRIPLET_LIMIT", str(TRIPLET_LIMIT_PER_PRED)))
    limit_clause = f"LIMIT {triplet_limit}" if triplet_limit > 0 else ""
    rel_to_entities = {}
    for ent, rel_list in entity_to_relations.items():
        for r in rel_list:
            rel_to_entities.setdefault(r, []).append(ent)

    tasks = []
    all_triplets = []
    
    for relation, ents in rel_to_entities.items():
        pred_uri = f"ns:{relation}"
        for batch in chunk_list(ents, batch_size):
            batch_values = " ".join([f"ns:{e}" for e in batch])

            if direction == "out":
                sparql_txt = f"""
                PREFIX ns:<http://rdf.freebase.com/ns/>
                SELECT ?left ?right WHERE {{
                    VALUES ?left {{ {batch_values} }}
                    ?left {pred_uri} ?right .
                }}
                {limit_clause}
                """
            else:
                sparql_txt = f"""
                PREFIX ns:<http://rdf.freebase.com/ns/>
                SELECT ?left ?right WHERE {{
                    VALUES ?right {{ {batch_values} }}
                    ?left {pred_uri} ?right .
                }}
                {limit_clause}
                """

            async def _task(q, r=relation, d=direction):
                bindings = await async_execute_sparql(q)
                res = []
                for row in bindings:
                    if "left" not in row or "right" not in row: continue
                    left = row["left"]["value"].replace("http://rdf.freebase.com/ns/", "")
                    right = row["right"]["value"].replace("http://rdf.freebase.com/ns/", "")
                    if d == "in":
                        res.append((right, r, left))
                    else:
                        res.append((left, r, right))
                return res
            tasks.append(asyncio.create_task(_task(sparql_txt)))

    # A6 [CRITICAL FIX]: gather ONCE after the loop, not per-relation.
    # The old code called `await asyncio.gather(*tasks)` inside the `for relation`
    # loop, which serialized N predicates into N × 1s instead of ~1s concurrent.
    # For CVT mediators with ~99 2-hop predicates this inflated 3s work to ~90s,
    # which is the real root cause of the hop=2 timeouts (SPARQL itself is fine).
    if tasks:
        results = await asyncio.gather(*tasks)
        for t in results:
            all_triplets.extend(t)
    return all_triplets


def _topk_preds_by_bge(query: str, preds: list, top_k: int) -> list:
    if not preds or not query:
        return preds[:top_k]
    try:
        bge = _get_bge_model()
        preds_clean = [p.replace('.', ' ').replace('_', ' ') for p in preds]
        # Lock-protected: see _bge_encode_lock comment for rationale.
        # Both encode calls must be inside the lock — the candidate-predicate
        # encode is the bigger one and was the main OMP-thrashing source.
        with _bge_encode_lock:
            query_emb = bge.encode([query], normalize_embeddings=True)[0]
            preds_embs = bge.encode(preds_clean, normalize_embeddings=True)
        sims = np.dot(preds_embs, query_emb)
        sorted_indices = np.argsort(sims)[::-1]
        return [preds[i] for i in sorted_indices[:top_k]]
    except Exception as e:
        logger.debug(f"BGE fallback due to error: {e}")
        return preds[:top_k]


def _run_async(coro):
    import asyncio
    import threading
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        result = [None]
        err = [None]
        def _target():
            try:
                result[0] = asyncio.run(coro)
            except Exception as ex:
                err[0] = ex
        t = threading.Thread(target=_target)
        t.start()
        t.join()
        if err[0]: raise err[0]
        return result[0]
    else:
        return asyncio.run(coro)


def _filter_preds(preds: list) -> list:
    forbidden_prefixes = ("type.", "common.", "freebase.", "kg.", "dataworld.")
    res = []
    for p in preds:
        raw_p = p.removesuffix(".r")
        if not raw_p.startswith(forbidden_prefixes) and raw_p not in _FILTER_PRED_KEYWORDS:
            res.append(p)
    return res


class _BuildSubgraphTimeoutError(Exception):
    """Raised when fetch_k_hop_triplets exceeds BUILD_SUBGRAPH_TIMEOUT."""
    pass


def _fetch_k_hop_with_timeout(*args, timeout: int = None, **kwargs):
    """Run fetch_k_hop_triplets with a total wall-clock timeout.

    Each call gets its own short-lived SPARQL thread-pool.  On timeout the
    pool is aggressively shut down (cancel_futures=True) so zombie daemon
    threads cannot monopolise the global SPARQL executor and cascade-block
    other samples' tool calls.
    """
    # Read at call time so Ray runtime_env env_vars take effect even if
    # the module was imported before they were applied.
    if timeout is None:
        timeout = int(os.getenv("KBQA_BUILD_SUBGRAPH_TIMEOUT", str(BUILD_SUBGRAPH_TIMEOUT)))
    result = [None]
    err: List[BaseException] = [None]
    done = threading.Event()
    # Per-call executor: 16 threads is enough for one BFS; the cap prevents
    # a hub entity from grabbing all Virtuoso server-threads.
    local_workers = max(1, int(os.getenv("KBQA_BFS_LOCAL_SPARQL_WORKERS", str(BFS_LOCAL_SPARQL_WORKERS))))
    local_pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=min(local_workers, int(os.getenv("SPARQL_MAX_WORKERS", str(_SPARQL_MAX_WORKERS)))),
        thread_name_prefix="sparql_bfs",
    )

    def _target():
        _tl_sparql.pool = local_pool      # async_execute_sparql picks this up
        try:
            result[0] = fetch_k_hop_triplets(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — re-raised on the main thread
            err[0] = exc
        finally:
            _tl_sparql.pool = None
            done.set()

    t = threading.Thread(target=_target, daemon=True, name="fetch_k_hop_triplets")
    t.start()
    if done.wait(timeout=timeout):
        local_pool.shutdown(wait=False)
        if err[0] is not None:
            raise err[0]
        return result[0]
    # TIMEOUT: aggressively cancel queued SPARQL tasks and reclaim threads.
    # Running HTTP requests will still finish at SPARQL_TIMEOUT (10s).
    local_pool.shutdown(wait=False, cancel_futures=True)
    raise _BuildSubgraphTimeoutError(
        f"fetch_k_hop_triplets exceeded {timeout}s"
    )


@timeit('fetch_k_hop_triplets_Total')
def fetch_k_hop_triplets(
    query: str,
    start_mid,
    loop: int,
    topk: int,
    forced_predicates: list = None,
    semantic_hint: str = "",
) -> list:
    """
    BFS 检索 k-hop 三元组。

    forced_predicates: 模型指定的谓词列表（对齐 CoG task["predicates"]  机制）。
      - 这些谓词不参与 BGE 评分，直接强制加入候选集合。
      - 确保即使 BGE 把它们排到 top-k 之外，也能被检索到。
      - 即使谓词不在当前实体的候选谓词里，也会尝试 SPARQL 查询。
        （SPARQL 对不存在的谓词返回空结果，不影响正确性。）
    """
    if isinstance(start_mid, (set, list)):
        current_entities = set(str(m) for m in start_mid if m)
    else:
        current_entities = {start_mid}
    topic_set = set(current_entities)
    
    hop_triplets = [[] for _ in range(loop)]
    is_topic_in = topic_set <= current_entities
    hit_topics = set()
    cvt_forced_next_hop = set()  # CVT 2nd-hop predicates to force at the next hop
    cvt_set = _get_cvt_set()
    cvt_2hop = _get_cvt_2hop()
    
    # A1: BFS iterates exactly `loop` hops. The model already breaks multi-hop
    # questions into multiple build_subgraph_schema calls, so the historical +2
    # CVT-fallback hops are redundant fan-out (was the dominant SPARQL cost).
    for hop in range(loop):
        if not current_entities:
            break

        # B2: When forced_predicates is supplied (100% path under the current
        # prompt workflow), SKIP fetch_relations_all entirely. Enumerating every
        # in/out predicate per hub-like entity (e.g. countries with hundreds of
        # predicates) is the real SPARQL bottleneck — and B1 already proved we
        # don't need BGE candidates anyway. Just probe forced predicates directly.
        if forced_predicates:
            base_fp_set = {fp.strip().removesuffix(".r") for fp in forced_predicates}
            if hop == 0:
                fp_set = set(base_fp_set)
            elif cvt_forced_next_hop:
                fp_set = set(cvt_forced_next_hop)
            else:
                break

            top_out_relations = set(fp_set)
            top_in_relations  = set(fp_set)

            if hop == 0:
                # hop0_all_* is no longer populated in fast path; the caller does
                # not consume them so this is safe.
                hop0_all_out = set()
                hop0_all_in = set()

            if len(top_out_relations) == 0 and hop != 0:
                break

            # Probe every forced predicate on every current entity (Virtuoso
            # returns empty bindings cheaply for predicates the entity lacks).
            entity_to_out_relations = {e: list(top_out_relations) for e in current_entities}
            entity_to_in_relations  = {e: list(top_in_relations)  for e in current_entities}
        else:
            # Legacy fallback path: no forced_predicates, must enumerate
            # candidate predicates first to feed BGE top-k selection.
            mid_relations_map = _run_async(fetch_relations_all(list(current_entities)))

            candidate_out_rels = set()
            candidate_in_rels = set()
            for v in mid_relations_map.values():
                candidate_in_rels.update(v[0])
                candidate_out_rels.update(v[1])

            if hop == 0:
                hop0_all_out = set(candidate_out_rels)
                hop0_all_in = set(candidate_in_rels)

            top_out_relations = set(_topk_preds_by_bge(query, list(candidate_out_rels), topk))
            top_in_relations  = set(_topk_preds_by_bge(query, list(candidate_in_rels),  topk))
            # Second path: rank by semantic_hint alone if it differs from query
            if query != semantic_hint and semantic_hint:
                top_out_2 = set(_topk_preds_by_bge(semantic_hint, list(candidate_out_rels), topk // 2))
                top_in_2  = set(_topk_preds_by_bge(semantic_hint, list(candidate_in_rels),  topk // 2))
                top_out_relations |= top_out_2
                top_in_relations  |= top_in_2

            if cvt_forced_next_hop:
                top_out_relations |= (cvt_forced_next_hop & candidate_out_rels)
                top_in_relations  |= (cvt_forced_next_hop & candidate_in_rels)

            if len(top_out_relations) == 0 and hop != 0:
                break

            entity_to_out_relations = {}
            entity_to_in_relations = {}
            for entity, relations in mid_relations_map.items():
                in_rels = set(relations[0])
                out_rels = set(relations[1])
                real_out = out_rels & top_out_relations
                real_in = in_rels & top_in_relations
                if real_out:
                    entity_to_out_relations[entity] = list(real_out)
                if real_in:
                    entity_to_in_relations[entity] = list(real_in)

        in_triplets = _run_async(recall_triplets_async(entity_to_in_relations, direction="in", current_hop=hop))
        out_triplets = _run_async(recall_triplets_async(entity_to_out_relations, direction="out", current_hop=hop))

        # 为入边三元组添加 .r 后缀（对齐 CoG 格式：(right, relation.r, left)）
        in_triplets_tagged = [(t[0], t[1] + ".r", t[2]) for t in in_triplets]
        hop_triplets[hop % loop].extend(list(set(in_triplets_tagged + out_triplets)))

        # 实体扩展：对齐 CoG 的选择性扩展策略
        #   hop 0, 2：展开新实体（BFS 正常扩展）
        #   hop 1, 3：不展开（减少候选集爆炸）
        #   hop 1 特殊处理：如果 topic 未被覆盖，回溯重新探索 topic entities
        #   hop > loop*2-1：兜底，始终展开（防止遗漏）
        new_entities = set()
        cvt_forced_next_hop = set()  # reset for the next hop
        if hop in (0, 2) or hop > loop * 2 - 1:
            for triplet in in_triplets_tagged + out_triplets:
                if triplet[-1].startswith(("m.", "g.")) and not triplet[1].startswith("common.topic.notable_types"):
                    new_entities.add(triplet[-1])
                    # If this relation leads to a CVT node, force its 2nd-hop predicates
                    raw_rel = triplet[1].removesuffix(".r")
                    if raw_rel in cvt_set:
                        sec_preds = cvt_2hop.get(raw_rel, [])
                        cvt_forced_next_hop.update(p for p in sec_preds
                                                  if not p.startswith(("freebase.", "type.object.")))

        current_entities = new_entities

        for t in in_triplets_tagged + out_triplets:
            hit_topics.update(topic_set & {t[0], t[-1]})

        if hit_topics == topic_set:
            is_topic_in = True

        if hop == 1:
            if is_topic_in:
                break  # 对齐 CoG：topic 全部覆盖时提前终止
            else:
                uncovered_topics = topic_set - hit_topics
                current_entities.update(uncovered_topics)
                
    flattened_triplets = []
    for lst in hop_triplets:
        for t in lst:
            if not t[0].startswith(("m.", "g.")): 
                continue
            flattened_triplets.append(t)
    return list(dict.fromkeys(flattened_triplets)), hop0_all_out, hop0_all_in


# ══════════════════════════════════════════════════════════════════════════════
# Step 4: 实体名查询（SQLite）
# ══════════════════════════════════════════════════════════════════════════════

def _get_entity_name(mid: str) -> str:
    cur = _get_sqlite_cursor()
    if cur is None: return ""
    try:
        cur.execute("SELECT name FROM entity_name WHERE mid=?", (mid,))
        row = cur.fetchone()
        return row[0] if row else ""
    except Exception:
        return ""

def _get_entity_names_bulk(mids: List[str]) -> Dict[str, str]:
    cur = _get_sqlite_cursor()
    result = {}
    if cur is None or not mids: return result
    placeholders = ",".join("?" * len(mids))
    try:
        cur.execute(f"SELECT mid, name FROM entity_name WHERE mid IN ({placeholders})", mids)
        for mid, name in cur.fetchall():
            name = name.strip('"').split('"@')[0].strip('"').strip()
            result[mid] = name
    except Exception as e:
        logger.debug(f"SQLite bulk query error: {e}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Step 5: Ontology 构建
# ══════════════════════════════════════════════════════════════════════════════

def _get_notable_type(mid_or_list) -> str:
    if not mid_or_list:
        return "Entity"
    if isinstance(mid_or_list, list):
        mid = mid_or_list[0]
    else:
        mid = mid_or_list
    if not isinstance(mid, str) or not mid.startswith(("m.", "g.")):
        return "Entity"
    
    sparql_query = f"""
    PREFIX ns: <http://rdf.freebase.com/ns/>
    SELECT ?type WHERE {{
      ns:{mid} ns:common.topic.notable_types ?type_id .
      ?type_id ns:type.object.name ?type .
      FILTER(LANG(?type) = "en")
    }} LIMIT 1
    """
    try:
        bindings = execute_sparql_sync(sparql_query)
        if bindings:
            t = bindings[0]["type"]["value"]
            name = "".join(w.capitalize() for w in t.split())
            return re.sub(r'[^A-Za-z0-9_]', '_', name)
    except Exception:
        pass
    return "Entity"

def _get_type_from_pred(pred: str, side: str) -> str:
    raw = pred.removesuffix(".r")
    rel2desc = _get_rel2desc()
    desc_list = rel2desc.get(raw)

    if desc_list:
        target_desc = desc_list[0] if side == "head" else desc_list[-1]
        m = _rel2desc_class_re.search(target_desc)
        if m:
            type_str = m.group(1)
            last_seg = type_str.split(".")[-1]
            class_name = "".join(w.capitalize() for w in last_seg.split("_"))
            return class_name.replace("-", "_") if class_name else "Entity"

    parts = raw.split(".")
    if side == "head":
        class_name = "".join(w.capitalize() for w in parts[0].split("_")).replace("-", "_") if parts else "Entity"
    else:
        class_name = "".join(w.capitalize() for w in parts[-1].split("_")).replace("-", "_") if parts else "Entity"
        
    # Prevent generating garbage classes from namespaces
    if class_name.lower() in ("base", "type", "common", "freebase", "dataworld", "kg", "user"):
        return "#NONE_HEAD"
    return class_name

@timeit('build_ontology')
def build_ontology(triplets: List[Tuple[str, str, str]], topic_mids: List[str]) -> Tuple[List, Dict, Dict]:
    all_mids = list({elem for t in triplets for elem in [t[0], t[2]] if isinstance(elem, str) and elem[:2] in ("m.", "g.")})
    mid_name_map = _get_entity_names_bulk(all_mids)
    for m in all_mids:
        if m not in mid_name_map or not mid_name_map[m]:
            mid_name_map[m] = "CVT node"

    type_relation_tuples = set()
    type_map = {}
    entity_to_type = {}
    processed = {}

    cvt_set = _get_cvt_set()
    cvt_sec_hop_keys = set(_get_cvt_2hop().keys())

    for (head, rel, tail) in triplets:
        is_reverse = rel.endswith(".r")
        raw_rel = rel.removesuffix(".r")

        if rel in processed:
            head_type = entity_to_type.get(head)
            if not head_type:
                head_type = processed[rel][0]
            tail_type = processed[rel][1]
        else:
            head_type = entity_to_type.get(head)
            if not head_type:
                if is_reverse:
                    head_type = _get_type_from_pred(raw_rel, "tail")
                else:
                    head_type = _get_type_from_pred(raw_rel, "head")
                
                if head_type == "#NONE_HEAD":
                    head_type = _get_notable_type(head)

            if is_reverse:
                tail_type = _get_type_from_pred(raw_rel, "head")
            else:
                tail_type = _get_type_from_pred(raw_rel, "tail")
                
            if tail_type == "#NONE_HEAD":
                tail_type = _get_notable_type(tail)

            # CVT-tag the side that is actually the CVT mediator node:
            #   forward `(X, cvt_entry_pred, Y)`   → Y is the CVT  → tail gets CVT suffix
            #   reverse `(Y, cvt_entry_pred.r, X)` → Y is the CVT  → head gets CVT suffix
            # Note: cvt_set == cvt_sec_hop_keys (verified: 8449 entries identical),
            # so the previous `cvt_sec_hop_keys` branch was equivalent. Tagging the
            # tail on reverse edges produced spurious empty `<EntityType>CVT` classes
            # like `ActorCVT`, `FilmCVT`, `FilmCharacterCVT` that clutter the schema
            # and may confuse the model into believing extra hops are needed.
            if raw_rel in cvt_set:
                if is_reverse:
                    if not head_type.endswith("CVT"):
                        head_type = f"{head_type}CVT"
                else:
                    if not tail_type.endswith("CVT"):
                        tail_type = f"{tail_type}CVT"

            processed[rel] = (head_type, tail_type)

        for mid, typ in [(head, head_type), (tail, tail_type)]:
            if isinstance(mid, str) and mid[:2] in ("m.", "g."):
                if typ not in type_map:
                    type_map[typ] = []
                if mid not in type_map[typ]:
                    type_map[typ].append(mid)
                entity_to_type[mid] = typ

        type_relation_tuples.add((head_type, rel, tail_type))

    return list(type_relation_tuples), type_map, mid_name_map


# ══════════════════════════════════════════════════════════════════════════════
# Step 6: 生成 Python 类定义
# ══════════════════════════════════════════════════════════════════════════════

def generate_class_code(type_relation_tuples: List, type_map: Dict, mid_name_map: Dict, topic_mids: List[str], query: str, max_entity_hint: int = 3) -> str:
    topic_set = set(topic_mids)
    classes = {}
    for head_type, rel, tail_type in type_relation_tuples:
        classes.setdefault(head_type, set()).add((rel, tail_type))

    def _rel_to_attr(rel: str) -> str:
        return rel.replace(".", "_").replace("-", "_")

    def _rank_mids(mid_list: List[str]) -> List[str]:
        topics = [m for m in mid_list if m in topic_set]
        others = [m for m in mid_list if m not in topic_set]
        return (topics + others)[:max_entity_hint]

    lines = ["from typing import List\n"]

    for cls_name, props in classes.items():
        lines.append(f"\n\nclass {cls_name}:")
        mid_list = type_map.get(cls_name, [])
        ranked = _rank_mids(mid_list)
        name_parts = []
        for m in ranked:
            n = mid_name_map.get(m, "")
            if n and n != "CVT node":
                name_parts.append(f"{n}({m})")
            else:
                name_parts.append(f"({m})")
                
        if "CVT" in cls_name:
            lines.append("    # CVT nodes, which refer to an intermediate step")
        elif name_parts:
            lines.append(f"    # entities like {', '.join(name_parts)} , etc.")
            
        lines.append("    def __init__(self, _mid: str = None,")
        seen_attrs = set()
        deduped_props = []
        for rel, tail_type in sorted(props, key=lambda x: x[0]):
            attr = _rel_to_attr(rel)
            if attr not in seen_attrs:
                seen_attrs.add(attr)
                deduped_props.append((rel, tail_type))
                
        prop_list = deduped_props
        for i, (rel, tail_type) in enumerate(prop_list):
            attr = _rel_to_attr(rel)
            comma = "," if i < len(prop_list) - 1 else "):"
            lines.append(f"                 {attr}: List['{tail_type}'] = None{comma}")
            
        if not prop_list:
            lines[-1] = lines[-1].rstrip(",") + "):"
        lines.append("        self._mid = _mid")
        
        for rel, tail_type in prop_list:
            attr = _rel_to_attr(rel)
            lines.append(f"        self.{attr} = {attr} or []")

    all_head_types = set(classes.keys())
    for cls_name, mid_list in type_map.items():
        if cls_name in all_head_types:
            continue
        lines.append(f"\n\nclass {cls_name}:")
        ranked = _rank_mids(mid_list)
        name_parts = []
        for m in ranked:
            n = mid_name_map.get(m, "")
            if n and n != "CVT node":
                name_parts.append(f"{n}({m})")
            else:
                name_parts.append(f"({m})")
        if "CVT" in cls_name:
            lines.append("    # CVT nodes, which refer to an intermediate step")
        elif name_parts:
            lines.append(f"    # entities like {', '.join(name_parts)} , etc.")
        lines.append("    def __init__(self, _mid: str = None):")
        lines.append("        self._mid = _mid")

    all_defined_types = all_head_types | set(type_map.keys())
    literal_types_seen = set()
    for _, _, tail_t in type_relation_tuples:
        if tail_t not in all_defined_types and tail_t not in literal_types_seen:
            literal_types_seen.add(tail_t)
            lines.append(f"\n\nclass {tail_t}:")
            lines.append("    # string class, which has no _mid attribute, all the _value are of String type")
            lines.append("    def __init__(self, _value: str = None):")
            lines.append("        self._value = _value")
            lines.append("    def __str__(self): return str(self._value) if self._value is not None else ''")
            lines.append("    def __repr__(self): return str(self._value) if self._value is not None else ''")
            lines.append("    def __bool__(self): return bool(self._value)")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Compact triple formatting (KnowCoder-style)
# ══════════════════════════════════════════════════════════════════════════════

def _format_compact_triples(
    triplets: List[Tuple[str, str, str]],
    mid_name_map: Dict[str, str],
    type_map: Dict[str, List[str]],
    max_lines: int = 60,
) -> List[str]:
    """
    KnowCoder 风格紧凑三元组：每个 (head_type_or_mid, predicate) 取 1 条代表性 tail。
    输入：原始三元组（含 .r 后缀的入边）
    输出：可读三元组文本，约 30~60 行。

    例：
      (?Performance(CVT), film.performance.character, "Jacob Black")
      (?Performance(CVT), film.performance.film, "The Twilight Saga: Breaking Dawn - Part 2")
      ("Logan Lerman", film.actor.film, ?Performance(CVT))
    """
    if not triplets:
        return ["# No triples retrieved."]

    # 把 mid 映射到所属 class（取第一个）
    mid_to_class: Dict[str, str] = {}
    for cls, mids in (type_map or {}).items():
        for m in mids:
            if m not in mid_to_class:
                mid_to_class[m] = cls

    def _render(node) -> str:
        if not isinstance(node, str):
            return f'"{node}"'
        if node.startswith(("m.", "g.")):
            cls = mid_to_class.get(node, "")
            name = mid_name_map.get(node, "") if mid_name_map else ""
            if name and name != "CVT node":
                return f'"{name}"'
            if cls:
                return f"?{cls}"
            return f"?{node}"
        # Literal
        return f'"{node}"'

    # Group by (head_render, predicate_collapsed) → list of tails
    seen_keys = set()
    lines: List[str] = []
    cvt_set = _get_cvt_set()
    cvt_sec_keys = set(_get_cvt_2hop().keys())

    # 简单 CVT 链折叠：若 head 是 CVT 类，并存在 ?prev → CVT → tail，则呈现为 ?p1 -> ?p2
    # 这里不做完整 chain 重建，仅按单跳呈现；CVT 链的 ?Class 已经反映在 head/tail 名称上（如 PerformanceCVT）。
    for head, rel, tail in triplets:
        raw_rel = rel.removesuffix(".r")
        is_rev = rel.endswith(".r")
        if is_rev:
            # 表示 (tail, raw_rel, head) 的反向：渲染为 (tail, raw_rel, head) 即可
            h_render = _render(tail)
            t_render = _render(head)
            pred_render = raw_rel
        else:
            h_render = _render(head)
            t_render = _render(tail)
            pred_render = raw_rel

        # CVT 链标注：如果 raw_rel 是 CVT 父谓词，标注 → 可能继续展开
        if raw_rel in cvt_set:
            pred_render = f"{pred_render}  # (leads to CVT, see CVT class predicates)"
        elif raw_rel in cvt_sec_keys:
            pred_render = f"{pred_render}  # (CVT 2nd-hop)"

        key = (h_render, raw_rel, t_render[:40])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        lines.append(f"({h_render}, {raw_rel}, {t_render})")
        if len(lines) >= max_lines:
            break

    header = [f"# Retrieved triples ({len(triplets)} total, showing {len(lines)} representative):"]
    return header + lines

# 主函数：build_subgraph_schema
# ══════════════════════════════════════════════════════════════════════════════

_INTERNAL_PREDICATE_CAP = 20


def _build_timeout_recovery_hint(
    n_mids: int,
    n_preds: int,
    hop: int,
    preds_preview: List[str],
) -> str:
    """Build the structured recovery hint emitted after a timeout.

    Emits ONLY the options that actually apply to the current regime so the
    policy cannot retry identical args.
    """
    header = (
        f"[Warning] build_subgraph_schema timed out after {BUILD_SUBGRAPH_TIMEOUT}s "
        f"with {n_mids} start_mids x {n_preds} predicates (hop={hop}, predicates={preds_preview})."
    )
    lines: List[str] = [
        header,
        "Recovery options (pick the FIRST that applies; do NOT retry with identical args):",
    ]
    step = 1
    if n_mids > 1:
        lines.append(
            f"{step}. Split start_mids: retry with 1 start_mid at a time "
            f"(current call loaded {n_mids} anchors in one BFS)."
        )
        step += 1
    if n_preds > 1:
        lines.append(
            f"{step}. Split predicates: retry with 1 predicate at a time "
            f"(current call loaded {n_preds} predicates in one BFS)."
        )
        step += 1
    if hop > 1:
        lines.append(
            f"{step}. Retry with hop=1: single BFS hop often avoids timeout "
            f"on CVT or high-fanout predicates."
        )
        step += 1
    # Final fallback — the call is already minimal (1 mid x 1 pred x hop=1
    # OR the caller has already tried the previous options); the anchor is
    # genuinely a Freebase hub on this predicate, so retrying will loop.
    lines.append(
        f"{step}. HUB fallback — if the call is already minimal (1 mid x 1 pred x hop=1), "
        f"the entity is a Freebase hub on {preds_preview}. Do NOT retry same args. Instead: "
        f"(a) pick a DIFFERENT predicate from list_predicates_by_entity with lower reachable count, or "
        f"(b) use search_entities_by_predicate(predicate=<P>, value=<constraint>) to narrow candidate "
        f"MIDs before calling build_subgraph_schema again."
    )
    return "\n".join(lines)


def _build_too_large_recovery_hint(
    n_mids: int,
    n_preds: int,
    hop: int,
    preds_preview: List[str],
    n_triplets: int,
    max_triplets: int,
) -> str:
    header = (
        f"[Warning] build_subgraph_schema result too large: {n_triplets} triplets "
        f"for {n_mids} start_mids x {n_preds} predicates "
        f"(hop={hop}, predicates={preds_preview}); max allowed is {max_triplets}."
    )
    lines: List[str] = [
        header,
        "Recovery options (pick the FIRST that applies; do NOT retry with identical args):",
    ]
    step = 1
    if n_mids > 1:
        lines.append(f"{step}. Split start_mids: retry with 1 start_mid at a time.")
        step += 1
    if n_preds > 1:
        lines.append(f"{step}. Split predicates: retry with 1 predicate at a time.")
        step += 1
    if hop > 1:
        lines.append(f"{step}. Retry with hop=1 for this high-fanout predicate.")
        step += 1
    lines.append(
        f"{step}. Pick a DIFFERENT predicate from list_predicates_by_entity with lower reachable count, "
        f"or use search_entities_by_predicate(predicate=<P>, value=<constraint>) to narrow candidate MIDs."
    )
    return "\n".join(lines)




def _invalid_predicate_reason(raw_predicates: List[str], clean_predicates: List[str]) -> Optional[str]:
    for raw in raw_predicates:
        if re.search(r"(?:\.r){2,}$", raw):
            return f"predicate `{raw}` has repeated reverse suffixes; use at most one trailing `.r`."
    max_run = max(3, int(os.getenv("KBQA_BUILD_SUBGRAPH_MAX_REPEAT_SEGMENT_RUN", "3")))
    for pred in clean_predicates:
        parts = pred.split(".")
        if "r" in parts:
            return f"predicate `{pred}` contains `.r` as an internal path segment; use only a single trailing `.r` to request reverse direction."
        run = 1
        for i in range(1, len(parts)):
            if parts[i] == parts[i - 1]:
                run += 1
                if run >= max_run:
                    return f"predicate `{pred}` repeats segment `{parts[i]}` {run} times consecutively; verify the predicate with list_predicates_by_entity."
            else:
                run = 1
    return None


def _build_invalid_predicate_hint(reason: str) -> str:
    return (
        f"[Error] Invalid build_subgraph_schema predicate: {reason} "
        f"Call list_predicates_by_entity again and pass one exact Freebase predicate. "
        f"Do NOT construct multi-hop predicate strings by concatenating relation names."
    )


def _build_too_broad_recovery_hint(n_mids: int, n_preds: int, hop: int, max_mids: int, max_preds: int) -> str:
    return (
        f"[Warning] build_subgraph_schema request too broad: {n_mids} start_mids x {n_preds} predicates "
        f"(hop={hop}); limits for hop>1 are start_mids<={max_mids} and predicates<={max_preds}. "
        f"Split start_mids/predicates into smaller calls, retry with hop=1, or narrow candidates with "
        f"search_entities_by_predicate before calling build_subgraph_schema again."
    )

def build_subgraph_schema(
    start_mids: List[str],
    predicates: List[str],
    hop: int = 2,
    run_id: Optional[str] = None,  # 内部任务标识，仅用于日志关联；不暴露给 LLM
) -> str:
    """Load a Freebase subgraph for the given entities along the predicates you select.

    对齐 docs/kbqa_tools_design.md §2.4。

    Args:
        start_mids: 锚点 MID 列表（必填）。Hop 1 用题目 topic 或 search_entities_by_predicate
            返回的 MID；Hop 2+ 用上一跳 execute_code 收集的中间 MID。
        predicates: 显式谓词清单（必填）。入边谓词以 .r 后缀传入。
        hop: BFS 扩展深度，默认 2。
        run_id: 内部任务标识，仅用于日志关联；非 LLM 可见入参。

    Returns:
        Python class schema 文本 + 末行 `# schema_file: <path>`。
        未展开 leaf 类以 `# NOT_EXPANDED:` 注释提示可进一步一跳。
    """
    _call_t0 = time.monotonic()
    _call_timeout = int(os.getenv("KBQA_BUILD_SUBGRAPH_TIMEOUT", str(BUILD_SUBGRAPH_TIMEOUT)))
    _call_deadline = _call_t0 + max(1, _call_timeout)
    clean_starts: List[str] = []
    for mid in start_mids or []:
        if not isinstance(mid, str):
            continue
        mid = re.sub(r"^(ns:|<http://rdf.freebase.com/ns/|<)", "", mid.strip()).rstrip(">")
        if mid.startswith(("m.", "g.")) and mid not in clean_starts:
            clean_starts.append(mid)

    if not clean_starts:
        return "[Error] build_subgraph_schema requires a non-empty `start_mids` list of valid Freebase MIDs."

    # ── 谓词清洗：去重 + 剥除 .r 后缀传给下游 BFS（BFS 内部会同时查 in/out）──
    clean_predicates: List[str] = []
    if predicates:
        for p in predicates:
            if isinstance(p, str) and p.strip():
                clean_predicates.append(p.strip().removesuffix(".r"))
        seen = set()
        clean_predicates = [p for p in clean_predicates if not (p in seen or seen.add(p))]

    if not clean_predicates:
        return (
            "[Error] build_subgraph_schema requires a non-empty `predicates=[...]` list. "
            "Call `list_predicates_by_entity` first to inspect candidate predicates, "
            "then pass the picked dot-notation predicates here (max 20 per call)."
        )

    # ── 内部硬编码安全 cap（不暴露给 LLM）：默认裁前 20 个，避免 SPARQL 超时 ──
    if len(clean_predicates) > _INTERNAL_PREDICATE_CAP:
        clean_predicates = clean_predicates[:_INTERNAL_PREDICATE_CAP]

    # ── BFS 起点与内部查询拼接 ──
    start = set(clean_starts)
    # print(
    #     f"[BUILD_SUBGRAPH_SCHEMA_START] pid={os.getpid()} "
    #     f"start_mids={len(clean_starts)} predicates={len(clean_predicates)} hop={hop} "
    #     f"start_preview={clean_starts[:3]} pred_preview={clean_predicates[:3]}",
    #     flush=True,
    # )
    topk = max(len(clean_predicates), 8)
    # 内部 BGE 兜底查询字符串（仅用于候选谓词排序，不作为外部入参）
    query = ", ".join(clean_predicates)
    starts_preview = ", ".join(clean_starts[:2])
    # logger.info(f"[build_subgraph_schema] start_mids={starts_preview} (n={len(clean_starts)}), topk={topk}")
    # logger.info(f"  BGE fallback query: {query!r}")

    # ── Result-cache fast-path ────────────────────────────────────────────
    # Same (start_mids, predicates, hop) seen earlier in this process? Skip
    # all SPARQL/BFS/BGE/file-write and return the cached output_text. The
    # cached text already embeds a `# schema_file: <relpath>` to a JSON file
    # written on the first call; that file persists for the whole training
    # run so execute_code can still load it.
    _cache_key = _make_cache_key(clean_starts, clean_predicates, hop)
    _invalid_reason = _invalid_predicate_reason(list(predicates or []), clean_predicates)
    if _invalid_reason is not None:
        _hint = _build_invalid_predicate_hint(_invalid_reason)
        _result_cache_put(_cache_key, _hint)
        # print(
        #     f"[BUILD_SUBGRAPH_SCHEMA_DONE] pid={os.getpid()} status=invalid_predicate "
        #     f"start_mids={len(clean_starts)} predicates={len(clean_predicates)} hop={hop} "
        #     f"call_ms={int((time.monotonic() - _call_t0) * 1000)}",
        #     flush=True,
        # )
        return _hint
    _max_hop2_starts = int(os.getenv("KBQA_BUILD_SUBGRAPH_HOP2_MAX_STARTS", "8"))
    _max_hop2_preds = int(os.getenv("KBQA_BUILD_SUBGRAPH_HOP2_MAX_PREDS", "4"))
    if hop > 1 and (len(clean_starts) > _max_hop2_starts or len(clean_predicates) > _max_hop2_preds):
        _hint = _build_too_broad_recovery_hint(
            len(clean_starts),
            len(clean_predicates),
            hop,
            _max_hop2_starts,
            _max_hop2_preds,
        )
        _result_cache_put(_cache_key, _hint)
        # print(
        #     f"[BUILD_SUBGRAPH_SCHEMA_DONE] pid={os.getpid()} status=too_broad "
        #     f"start_mids={len(clean_starts)} predicates={len(clean_predicates)} hop={hop} "
        #     f"call_ms={int((time.monotonic() - _call_t0) * 1000)}",
        #     flush=True,
        # )
        return _hint
    _cached = _result_cache_get(_cache_key)
    if _cached is not None:
        return _cached
    _timeout_cached = _timeout_cache_get(_cache_key)
    if _timeout_cached is not None:
        # print(
        #     f"[BUILD_SUBGRAPH_SCHEMA_DONE] pid={os.getpid()} status=timeout_cache_hit "
        #     f"start_mids={len(clean_starts)} predicates={len(clean_predicates)} hop={hop} "
        #     f"call_ms={int((time.monotonic() - _call_t0) * 1000)}",
        #     flush=True,
        # )
        return _timeout_cached
    _inflight_entry, _inflight_owner = _result_inflight_start(_cache_key)
    if not _inflight_owner:
        if _inflight_entry["event"].wait(timeout=max(1.0, float(_call_timeout) + 5.0)):
            _err = _inflight_entry.get("error")
            if _err is not None:
                raise _err
            _value = _inflight_entry.get("value")
            if isinstance(_value, str) and _value:
                return _value
            _cached = _result_cache_get(_cache_key)
            if _cached is not None:
                return _cached
        _hint = _build_timeout_recovery_hint(
            len(clean_starts),
            len(clean_predicates),
            hop,
            clean_predicates[:5],
        )
        _timeout_cache_put(_cache_key, _hint)
        return _hint

    def _finish(value: str) -> str:
        _result_cache_put(_cache_key, value)
        _result_inflight_finish(_cache_key, value=value)
        return value

    def _finish_timeout(value: str) -> str:
        _timeout_cache_put(_cache_key, value)
        _result_inflight_finish(_cache_key, value=value)
        return value

    def _deadline_exceeded() -> bool:
        return time.monotonic() >= _call_deadline

    def _deadline_hint() -> str:
        return _build_timeout_recovery_hint(
            len(clean_starts),
            len(clean_predicates),
            hop,
            clean_predicates[:5],
        )

    import time as _time
    _sem_t0 = _time.monotonic()
    _sem_timeout = max(0.0, _call_deadline - _time.monotonic())
    _sem_acquired = _BUILD_SUBGRAPH_SEMAPHORE.acquire(timeout=_sem_timeout)
    _queue_ms = int((_time.monotonic() - _sem_t0) * 1000)
    if not _sem_acquired:
        _hint = _deadline_hint()
        logger.warning(
            f"[build_subgraph_schema] BFS QUEUE TIMEOUT {_queue_ms / 1000.0:.1f}s  "
            f"{len(start)} start_mids x {len(clean_predicates)} preds (hop={hop}); returning warning"
        )
        # print(
        #     f"[BUILD_SUBGRAPH_SCHEMA_DONE] pid={os.getpid()} status=queue_timeout "
        #     f"start_mids={len(clean_starts)} predicates={len(clean_predicates)} hop={hop} "
        #     f"queue_ms={_queue_ms} call_ms={int((time.monotonic() - _call_t0) * 1000)}",
        #     flush=True,
        # )
        return _finish_timeout(_hint)
    _bfs_t0 = _time.monotonic()
    try:
        try:
            _remaining_timeout = max(1, int(_call_deadline - _time.monotonic()))
            triplets, hop0_all_out, hop0_all_in = _fetch_k_hop_with_timeout(
                query=query,
                start_mid=start,
                loop=hop,
                topk=topk,
                forced_predicates=clean_predicates,
                semantic_hint=query,
                timeout=_remaining_timeout,
            )
        finally:
            _BUILD_SUBGRAPH_SEMAPHORE.release()
        _bfs_dur = _time.monotonic() - _bfs_t0
        if os.getenv("KBQA_LOG_BFS_OK", "0") == "1":
            logger.info(
                f"[build_subgraph_schema] BFS OK  {_bfs_dur:.1f}s  "
                f"{len(start)} mids x {len(clean_predicates)} preds (hop={hop}) → {len(triplets)} triplets"
            )
    except _BuildSubgraphTimeoutError:
        _bfs_dur = _time.monotonic() - _bfs_t0
        n_mids = len(start)
        n_preds = len(clean_predicates)
        preds_preview = clean_predicates[:5]
        logger.warning(
            f"[build_subgraph_schema] BFS TIMEOUT {_bfs_dur:.1f}s queue={_queue_ms / 1000.0:.1f}s  "
            f"{n_mids} start_mids x {n_preds} preds (hop={hop}); returning warning"
        )
        # print(
        #     f"[BUILD_SUBGRAPH_SCHEMA_DONE] pid={os.getpid()} status=timeout "
        #     f"start_mids={len(clean_starts)} predicates={len(clean_predicates)} hop={hop} "
        #     f"queue_ms={_queue_ms} bfs_ms={int(_bfs_dur * 1000)} "
        #     f"call_ms={int((time.monotonic() - _call_t0) * 1000)}",
        #     flush=True,
        # )
        return _finish_timeout(_build_timeout_recovery_hint(n_mids, n_preds, hop, preds_preview))
    except BaseException as exc:
        _result_inflight_finish(_cache_key, error=exc)
        raise
    if _deadline_exceeded():
        return _finish_timeout(_deadline_hint())
    _max_triplets = int(os.getenv("KBQA_MAX_TRIPLETS", str(MAX_TRIPLETS)))
    if _max_triplets > 0 and len(triplets) > _max_triplets:
        logger.warning(
            f"[build_subgraph_schema] TOO LARGE {len(triplets)} triplets "
            f"{len(start)} start_mids x {len(clean_predicates)} preds "
            f"(hop={hop}, max={_max_triplets}); returning warning"
        )
        # print(
        #     f"[BUILD_SUBGRAPH_SCHEMA_DONE] pid={os.getpid()} status=too_large "
        #     f"start_mids={len(clean_starts)} predicates={len(clean_predicates)} hop={hop} "
        #     f"triplets={len(triplets)} queue_ms={_queue_ms} bfs_ms={int(_bfs_dur * 1000)} "
        #     f"call_ms={int((time.monotonic() - _call_t0) * 1000)}",
        #     flush=True,
        # )
        return _finish(_build_too_large_recovery_hint(
            len(start),
            len(clean_predicates),
            hop,
            clean_predicates[:5],
            len(triplets),
            _max_triplets,
        ))
    # logger.info(f"  Total triplets after {hop}-loop BFS: {len(triplets)}")

    if not triplets:
        preds_preview = clean_predicates[:5]
        first_pred = clean_predicates[0] if clean_predicates else "<predicate>"
        reverse_hint = first_pred[:-2] if first_pred.endswith(".r") else first_pred + ".r"
        # print(
        #     f"[BUILD_SUBGRAPH_SCHEMA_DONE] pid={os.getpid()} status=no_triplets "
        #     f"start_mids={len(clean_starts)} predicates={len(clean_predicates)} hop={hop} "
        #     f"queue_ms={_queue_ms} bfs_ms={int(_bfs_dur * 1000)} "
        #     f"call_ms={int((time.monotonic() - _call_t0) * 1000)}",
        #     flush=True,
        # )
        return _finish(
            f"[Warning] No triplets for {len(start)} mids x {preds_preview}. "
            f"Try reverse `{reverse_hint}`, verify via list_predicates_by_entity, "
            f"or pick a different predicate. Do NOT retry the same args."
        )

    all_topic_mids = clean_starts
    if _deadline_exceeded():
        return _finish_timeout(_deadline_hint())
    type_relation_tuples, type_map, mid_name_map = build_ontology(triplets, all_topic_mids)
    if _deadline_exceeded():
        return _finish_timeout(_deadline_hint())

    # generate_class_code 输出 *可执行* Python class，用于 execute_code 沙盒；
    # 此处 query 仅用于内部对 examples 排序兜底，无外部语义。
    class_code = generate_class_code(
        type_relation_tuples, type_map, mid_name_map,
        topic_mids=all_topic_mids, query=query,
    )
    if _deadline_exceeded():
        return _finish_timeout(_deadline_hint())

    # ── Save subgraph data to file for execute_code ──
    _cache_dir = os.path.join(_PROJECT_ROOT, "tools_impl", ".subgraph_cache")
    os.makedirs(_cache_dir, exist_ok=True)
    _file_id = str(_uuid.uuid4())[:8]
    subgraph_file = os.path.join(_cache_dir, f"subgraph_{_file_id}.json")
    try:
        _file_data = {
            "triplets": triplets,
            "ontology": list(type_relation_tuples),
            "type_map": type_map,
            "mid_name_map": mid_name_map,
            "class_code": class_code,
            "topic_mids": all_topic_mids,
        }
        if _deadline_exceeded():
            return _finish_timeout(_deadline_hint())
        with open(subgraph_file, "w", encoding="utf-8") as _sf:
            json.dump(_file_data, _sf, ensure_ascii=False)
        # logger.info(f"[build_subgraph_schema] Saved subgraph data to {subgraph_file}")
    except Exception as e:
        logger.warning(f"Failed to save subgraph file: {e}")
        subgraph_file = None

    # ── Build Python type stub schema for LLM (对齐 design.md §2.5) ──
    if _deadline_exceeded():
        return _finish_timeout(_deadline_hint())
    _NOISE_PRED_PREFIXES = ("user.", "dataworld.", "base.rosetta.")
    topic_set = set(all_topic_mids)

    # Collect attrs per class: cls_name -> list of (attr_name, tail_type, is_reverse)
    classes_attrs: Dict[str, List[Tuple[str, str, bool]]] = {}
    for head_type, rel, tail_type in type_relation_tuples:
        raw_rel = rel.removesuffix(".r")
        if raw_rel.startswith(_NOISE_PRED_PREFIXES):
            continue
        is_reverse = rel.endswith(".r") or rel.endswith("_r")
        attr = rel.replace(".", "_").replace("-", "_")
        classes_attrs.setdefault(head_type, []).append((attr, tail_type, is_reverse))

    all_cls = set(classes_attrs.keys()) | set(type_map.keys())
    leaf_literals = set()
    for _, _, tail_t in type_relation_tuples:
        if tail_t not in all_cls:
            leaf_literals.add(tail_t)

    schema_lines: List[str] = []

    for cls_name in sorted(all_cls):
        mid_list = type_map.get(cls_name, [])
        total_count = len(mid_list)
        is_cvt = "CVT" in cls_name
        attrs = classes_attrs.get(cls_name, [])

        # Build class comment: CVT/count/examples (topic-first 排序)
        topics_first = [m for m in mid_list if m in topic_set]
        others = [m for m in mid_list if m not in topic_set]
        ranked = (topics_first + others)[:3]
        examples = []
        for m in ranked:
            n = mid_name_map.get(m, "")
            if n and n != "CVT node":
                examples.append(f"{n}({m})")
            else:
                examples.append(m)

        comment_parts = []
        if is_cvt:
            comment_parts.append("CVT")
        comment_parts.append(f"{total_count} instances")
        # CVT 节点 mid 名义上都是 "CVT node"，e.g. 段对 LLM 无展示价值，仅非 CVT 类展示
        if examples and not is_cvt:
            comment_parts.append(f"e.g. {', '.join(examples)}")
        comment = " | ".join(comment_parts)

        schema_lines.append(f"class {cls_name}:  # {comment}")
        schema_lines.append("    _mid: str")
        for attr_name, tail_type, is_rev in sorted(attrs, key=lambda x: x[0]):
            rev_mark = "  # reverse" if is_rev else ""
            schema_lines.append(f"    {attr_name}: List['{tail_type}']{rev_mark}")
        if not attrs:
            # NOT_EXPANDED: leaf entity class with no predicates loaded.
            # Skip the marker for CVTs / topic-holders / classes without entity MIDs
            # (those legitimately have no further hops to take).
            is_topic_holder = bool(set(mid_list) & topic_set)
            has_entity_mids = any(
                isinstance(m, str) and m.startswith(("m.", "g."))
                for m in mid_list
            )
            if (not is_cvt) and (not is_topic_holder) and has_entity_mids:
                schema_lines.append(
                    "    # NOT_EXPANDED: predicates not loaded; "
                    "call build_subgraph_schema(start_mids=<these MIDs>) to expand."
                )
            else:
                schema_lines.append("    pass")
        schema_lines.append("")

    for lt in sorted(leaf_literals):
        schema_lines.append(f"class {lt}:  # literal")
        schema_lines.append("    _value: str")
        schema_lines.append("")

    # ── 严格按 design.md §2.4 输出：仅 schema + `# schema_file: <path>` ──
    # Return a path relative to the runtime root so all environments see the
    # same string form, e.g.
    #   tools/.subgraph_cache/subgraph_abc123.json
    # This eliminates the Mac-prefix vs server-prefix distribution shift that
    # caused Qwen 7B to hallucinate paths like /tmp/schema.json.
    output_lines: List[str] = list(schema_lines)
    if subgraph_file:
        try:
            _schema_file_out = os.path.relpath(subgraph_file, _PROJECT_ROOT)
        except ValueError:
            # e.g. Windows cross-drive; keep absolute as last resort.
            _schema_file_out = subgraph_file
        output_lines.append(f"# subgraph_file: {_schema_file_out}")

    if _deadline_exceeded():
        return _finish_timeout(_deadline_hint())
    output_text = "\n".join(output_lines).rstrip() + "\n"

    # ── Save schema output for inspection (本地调试便利，与 LLM 输出无关) ──
    try:
        _schema_file = os.path.join(_cache_dir, f"schema_{_file_id}.txt")
        if _deadline_exceeded():
            return _finish_timeout(_deadline_hint())
        with open(_schema_file, "w", encoding="utf-8") as _sf:
            _sf.write(output_text)
        # logger.info(f"[build_subgraph_schema] Saved schema output to {_schema_file}")
    except Exception as e:
        logger.warning(f"Failed to save schema file: {e}")

    _call_ms = int((time.monotonic() - _call_t0) * 1000)
    # print(
    #     f"[BUILD_SUBGRAPH_SCHEMA_DONE] pid={os.getpid()} "
    #     f"start_mids={len(clean_starts)} predicates={len(clean_predicates)} hop={hop} "
    #     f"status=success triplets={len(triplets)} queue_ms={_queue_ms} "
    #     f"bfs_ms={int(_bfs_dur * 1000)} call_ms={_call_ms}",
    #     flush=True,
    # )

    # ── Persist successful result to LRU cache for the rest of this rollout ──
    return _finish(output_text)
