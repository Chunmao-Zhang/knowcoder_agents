"""
kbqa_tool_search_entity.py - search_entity Tool for deepagents_kbqa
====================================================================

功能：给定一个谓词，查找满足该谓词的具体头实体 MID。

典型使用场景：
  Q: "which buildings have 10 floors?"
  -> search_entity(predicate="architecture.structure.floors", value=10)
  -> m.0bn8q1  "Hotel Andaluz"
     m.064qz5  "Azadi Cinema Complex"
     m.07hvw_  "Ellicott Square Building"

设计要点（对齐 docs/kbqa_tools_design.md §2.2）：
  1. 必须至少提供 `semantic_filter` 或 `value` 之一，否则拒绝查询。
  2. SPARQL 直查 Virtuoso：?x ns:<predicate> "value" 或 ?x ns:<predicate> ?v
  3. 自动尝试多种 datatype（int / float / string / date）
  4. semantic_filter 提供时，对候选用 BGE 按 `name + description` 排序
  5. 输出仅为文本，每行 `mid  "name"`，无文件输出

输出格式（严格对齐 design.md §2.2，仅候选行，无 header）：
  m.0bn8q1  "Hotel Andaluz"
  m.064qz5  "Azadi Cinema Complex"
  m.07hvw_  "Ellicott Square Building"
"""

from __future__ import annotations

import os
import re
import sys
from typing import List, Optional

from loguru import logger

_HERE = os.path.dirname(os.path.abspath(__file__))


def _strip_ns(uri_or_name: str) -> str:
    if not isinstance(uri_or_name, str):
        return ""
    s = uri_or_name.strip()
    # Strip various wrappings: angle brackets, ns: prefix, full http URI
    s = re.sub(r"^<", "", s).rstrip(">")
    s = re.sub(r"^(ns:|http://rdf\.freebase\.com/ns/)", "", s)
    return s


_MID_VALUE_RE = re.compile(r"^[mg]\.[0-9a-z_]+$")


def _quote_value_variants(value) -> List[str]:
    """
    返回多种数据类型的 SPARQL 值字面量候选，按常见性排序：
      - MID (ns:<mid> URI 形式，用于实体引用型谓词，如 people.person.profession)
      - int (gYear / xsd:int / xsd:integer)
      - float (xsd:float / xsd:double / xsd:decimal)
      - date (xsd:date / xsd:dateTime)
      - string (plain literal & lang-tagged)

    MID URI 情况：
      - 当 value 是形如 `m.xxx` / `g.xxx` 的字符串时，Freebase 将其存为 URI
        `ns:m.xxx` 而非字面量。返回 `["ns:m.xxx"]`（一条即可），_build_sparql
        会把它直接拼到 `?x ns:<pred> ns:<mid>` 位置，不加引号。
    """
    if value is None:
        return []

    variants: List[str] = []

    if isinstance(value, bool):
        variants.append(f'"{str(value).lower()}"^^xsd:boolean')
        return variants

    # MID 优先：字符串看起来像 m.xxx / g.xxx（或其 ns:/<URI> 包装形式） → 走 URI 分支
    if isinstance(value, str):
        mid_candidate = _strip_ns(value)
        if _MID_VALUE_RE.match(mid_candidate):
            return [f"ns:{mid_candidate}"]

    if isinstance(value, int):
        v = str(value)
        variants += [
            f'"{v}"^^xsd:integer',
            f'"{v}"^^xsd:int',
            f'"{v}.0"^^xsd:float',
            f'"{v}.0"^^xsd:double',
            f'"{v}"^^xsd:gYear',
            f'"{v}"',
        ]
        return variants

    if isinstance(value, float):
        v_str = repr(value)
        variants += [
            f'"{v_str}"^^xsd:float',
            f'"{v_str}"^^xsd:double',
            f'"{v_str}"^^xsd:decimal',
        ]
        if value.is_integer():
            iv = str(int(value))
            variants += [
                f'"{iv}"^^xsd:integer',
                f'"{iv}"^^xsd:int',
            ]
        variants.append(f'"{v_str}"')
        return variants

    s = str(value).strip()
    # 自动检测数字
    try:
        iv = int(s)
        variants += _quote_value_variants(iv)
    except ValueError:
        pass
    try:
        fv = float(s)  # noqa: F841
        if not s.lstrip("-").isdigit():
            variants += [
                f'"{s}"^^xsd:float',
                f'"{s}"^^xsd:double',
                f'"{s}"^^xsd:decimal',
            ]
    except ValueError:
        pass

    # 日期格式 (YYYY-MM-DD or YYYY)
    if re.fullmatch(r"\d{4}", s):
        variants.append(f'"{s}"^^xsd:gYear')
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        variants.append(f'"{s}"^^xsd:date')
        variants.append(f'"{s}T00:00:00"^^xsd:dateTime')
    if re.fullmatch(r"\d{4}-\d{2}", s):
        variants.append(f'"{s}"^^xsd:gYearMonth')

    # 字符串字面量
    safe = s.replace('"', '\\"')
    variants.append(f'"{safe}"@en')
    variants.append(f'"{safe}"')

    # 去重保留顺序
    seen = set()
    out = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _build_sparql(predicate: str, value, top_k: int, with_description: bool = False) -> str:
    """Build SPARQL to fetch candidate MIDs that satisfy the predicate.

    Args:
        predicate: dot-notation Freebase predicate (incoming '.r' suffix is stripped).
        value: optional literal; when provided, builds a UNION over datatype variants.
        top_k: row limit.
        with_description: if True, also OPTIONAL-pull common.topic.description for BGE rerank.
    """
    pred = _strip_ns(predicate).removesuffix(".r")
    parts = ["PREFIX ns: <http://rdf.freebase.com/ns/>"]
    if with_description:
        parts.append("SELECT DISTINCT ?x ?n ?d WHERE {")
    else:
        parts.append("SELECT DISTINCT ?x ?n WHERE {")

    if value is not None:
        variants = _quote_value_variants(value)
        if variants:
            union_blocks = []
            for v in variants[:4]:
                union_blocks.append(f"  {{ ?x ns:{pred} {v} . }}")
            parts.append(" UNION ".join(union_blocks))
        else:
            parts.append(f"  ?x ns:{pred} ?v .")
    else:
        parts.append(f"  ?x ns:{pred} ?v .")

    parts.append('  OPTIONAL { ?x ns:type.object.name ?n . FILTER (LANG(?n) = "en") }')
    if with_description:
        parts.append('  OPTIONAL { ?x ns:common.topic.description ?d . FILTER (LANG(?d) = "en") }')
    parts.append("}")
    parts.append(f"LIMIT {top_k}")
    return "\n".join(parts)


def _execute_sparql(sparql: str) -> List[dict]:
    """复用 build_subgraph_schema 的同步 SPARQL 执行函数。"""
    try:
        from .build_subgraph_schema import execute_sparql_sync
        return execute_sparql_sync(sparql)
    except Exception as e:
        logger.debug(f"[search_entity] SPARQL exec failed: {e}")
        return []


def _bge_rerank(semantic_filter: str, texts: List[str]) -> List[int]:
    """BGE encode `semantic_filter` and `texts`; return indices sorted by descending similarity.

    Falls back to identity ordering when BGE is unavailable.
    """
    if not texts:
        return []
    try:
        from .build_subgraph_schema import _get_bge_model, _bge_encode_lock
        bge = _get_bge_model()
        # Serialize BGE encode to avoid OMP thread thrashing under parallel
        # tool execution; see _bge_encode_lock comment in build_subgraph_schema.
        with _bge_encode_lock:
            q_emb = bge.encode([semantic_filter], normalize_embeddings=True)[0]
            cand_embs = bge.encode(texts, normalize_embeddings=True)
        scores = (cand_embs @ q_emb).tolist()
        return sorted(range(len(scores)), key=lambda i: -scores[i])
    except Exception as e:
        logger.debug(f"[search_entity] BGE rerank failed: {e}")
        return list(range(len(texts)))


def search_entities_by_predicate(
    predicate: str,
    semantic_filter: Optional[str] = None,
    value=None,
    top_k: int = 50,
    run_id: Optional[str] = None,  # 内部任务标识，仅用于日志关联；不暴露给 LLM
) -> str:
    """根据谓词反查实体 MID（对齐 docs/kbqa_tools_design.md §2.2）。

    Args:
        predicate: 谓词 dot-notation，如 "architecture.structure.floors"（必填）。
        semantic_filter: 自然语言描述（可选）；提供时按 `name + description`
            与 semantic_filter 的 BGE 相似度重排候选。
        value: 字面量值（int / float / str / date 字符串，可选）；提供时按值精确过滤，
            自动尝试多种 datatype（integer / float / gYear / date / 字符串）。
        top_k: 返回前 K 条候选，默认 50，上限 200。
        run_id: 内部任务标识，仅用于日志关联；非 LLM 可见入参。

    Constraint:
        必须至少提供 `semantic_filter` 或 `value` 之一（否则拒绝查询）。

    Returns:
        多行文本：每行一个候选 `mid  "name"`，name 取自 `type.object.name`
        （CVT 节点可能空名）。无文件输出。
    """
    if not isinstance(predicate, str) or not predicate.strip():
        return "[Error] search_entity requires a non-empty `predicate`."

    has_filter = isinstance(semantic_filter, str) and bool(semantic_filter.strip())
    has_value = value is not None and (not isinstance(value, str) or bool(value.strip()))
    if not has_filter and not has_value:
        return (
            "[Error] search_entity requires at least one of `semantic_filter` or `value` "
            "(otherwise the candidate set is too large to be useful)."
        )

    if has_filter:
        semantic_filter = semantic_filter.strip()

    predicate = _strip_ns(predicate).removesuffix(".r")
    top_k = max(1, min(int(top_k or 50), 200))

    # 有 semantic_filter 时多拉一些以便 rerank（上限 500）
    fetch_k = min(max(top_k * 3, top_k + 30), 500) if has_filter else top_k

    sparql = _build_sparql(
        predicate,
        value if has_value else None,
        fetch_k,
        with_description=has_filter,
    )
    rows = _execute_sparql(sparql)
    if not rows and has_value and has_filter:
        # value 数据类型可能不匹配；fall back 到仅语义排序
        sparql_no_val = _build_sparql(predicate, None, fetch_k, with_description=True)
        rows = _execute_sparql(sparql_no_val)

    if not rows:
        hint = (
            f", value={value!r}" if has_value else ""
        ) + (
            f", semantic_filter={semantic_filter!r}" if has_filter else ""
        )
        value_hint = (
            " If the question contains an exact date/number/unit value, call this tool with that "
            "exact `value` rather than only semantic_filter."
            if not has_value
            else ""
        )
        cvt_hint = (
            " Do not use CVT-internal predicates with the original topic MID as `value`; first reach "
            "the CVT/entity via build_subgraph_schema and execute_code, then continue from returned MIDs."
        )
        return (
            f"[Search Entity] predicate={predicate}{hint}\n"
            f"No matching entities found. Try a different predicate, verify direction with "
            f"list_predicates_by_entity, or relax the constraints.{value_hint}{cvt_hint} "
            f"Do NOT retry the same args."
        )

    name_map: dict = {}
    desc_map: dict = {}
    seen_mids: List[str] = []
    seen_set = set()
    for row in rows:
        x_uri = row.get("x", {}).get("value", "")
        x = _strip_ns(x_uri)
        if not x or not x.startswith(("m.", "g.")):
            continue
        if x not in seen_set:
            seen_set.add(x)
            seen_mids.append(x)
        n_val = row.get("n", {}).get("value", "")
        if n_val and x not in name_map:
            name_map[x] = n_val
        d_val = row.get("d", {}).get("value", "")
        if d_val and x not in desc_map:
            desc_map[x] = d_val

    # SQLite 兜底取实体名
    try:
        from .build_subgraph_schema import _get_entity_names_bulk
        miss = [m for m in seen_mids if not name_map.get(m)]
        if miss:
            sqlite_names = _get_entity_names_bulk(miss)
            for m, n in sqlite_names.items():
                if n:
                    name_map[m] = n
    except Exception:
        pass

    # BGE 重排序（当 semantic_filter 提供且候选多于 1 个）
    if has_filter and len(seen_mids) > 1:
        texts = []
        for mid in seen_mids:
            nm = name_map.get(mid, "")
            ds = desc_map.get(mid, "")
            if nm and ds:
                texts.append(f"{nm}. {ds}")
            elif nm:
                texts.append(nm)
            elif ds:
                texts.append(ds)
            else:
                texts.append(mid)
        order = _bge_rerank(semantic_filter, texts)
        seen_mids = [seen_mids[i] for i in order]

    # 截断到 top_k
    seen_mids = seen_mids[:top_k]

    # 严格对齐 design.md §2.2：输出仅为 `mid  "name"` 行
    lines = []
    for mid in seen_mids:
        nm = name_map.get(mid, "")
        nm_safe = nm.replace('"', '\\"') if nm else ""
        lines.append(f'{mid}  "{nm_safe}"')
    return "\n".join(lines)
