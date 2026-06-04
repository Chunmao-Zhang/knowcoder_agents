"""
kbqa_tool_search_predicates.py — search_predicates Tool for deepagents_kbqa
=========================================================================

功能：基于自然语言语义描述，从 Freebase 全量谓词向量库中检索 top-K 相关谓词。

设计目标（解决 0-TE 题）：
  - 当题目没有 topic entity 时（如“哪些建筑有10层楼”），无法直接调用 build_subgraph_schema。
  - 此工具不依赖具体实体，纯粹基于 BGE + ChromaDB 在 ~21K Freebase 谓词中做语义检索。
  - 输出每个候选谓词的 (predicate, description) 文本对，description 已自然语言嵌入 head/tail 实体类型。
  - 拿到候选谓词后，配合 search_entities_by_predicate(predicate=..., value=...) 或 build_subgraph_schema 进一步检索。

文件驱动设计：
  - 工具不依赖任何 session 全局状态。
  - 输出仅为文本，不写入任何文件（与 docs/kbqa_tools_design.md §2.1 对齐）。

复用现有基础设施：
  - _get_chroma() → predicate-local 集合 (~20K predicates)
  - _get_bge_model() → BGE 向量编码（不用 ChromaDB 内置 MiniLM）
  - _get_rel2desc() → 谓词描述词典，提供 head/tail 类型完整自然语言短语

输出格式（每个候选两行 + 空行分隔）：
  [Search Predicate] semantic_filter: 'floors of building', top 20 candidates:

  predicate   : architecture.building.floors
  description : "...The type of its head entity is 'architecture.building' (...). The type of its tail entity is 'type.int' (...)."

  predicate   : architecture.structure.floors
  description : "..."
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))


def _normalize_chroma_doc(doc: str) -> str:
    """
    ChromaDB 中谓词存储为空格分隔 token，例如：
      'base . architecture2 . building _ floor . floor _ name'
    需要还原为标准点分谓词：
      'base.architecture2.building_floor.floor_name'
    """
    # 先处理点分隔符两侧空格
    s = doc.replace(" . ", ".").replace(" .", ".").replace(". ", ".")
    # 再处理下划线两侧空格
    s = s.replace(" _ ", "_").replace(" _", "_").replace("_ ", "_")
    # 兜底：去除任何残留空白
    s = "".join(s.split())
    return s


def search_predicates(
    semantic_filter: str,
    top_k: int = 20,
    run_id: Optional[str] = None,  # 内部任务标识，仅用于日志关联；不暴露给 LLM
) -> str:
    """向量检索 Freebase 全量谓词（对齐 docs/kbqa_tools_design.md §2.1）。

    Args:
        semantic_filter: 自然语言描述（必需），描述要查找的关系语义。
        top_k: 返回前 K 个谓词，默认 20，上限 50。
        run_id: 内部任务标识，仅用于日志关联；非 LLM 可见入参。

    Returns:
        多行文本：每个候选谓词以两行展示
        `predicate   : <pred>` / `description : <desc>`，用空行分隔。无文件输出。
    """
    if not isinstance(semantic_filter, str) or not semantic_filter.strip():
        return "[Error] search_predicates requires a non-empty `semantic_filter`."

    semantic_filter = semantic_filter.strip()
    top_k = max(1, min(int(top_k or 20), 50))

    try:
        from .build_subgraph_schema import _get_chroma, _get_bge_model, _get_rel2desc, _bge_encode_lock
    except Exception as e:
        return f"[Error] search_predicates cannot load dependencies: {e}"

    try:
        pred_col, _ = _get_chroma()
    except Exception as e:
        return f"[Error] search_predicates ChromaDB unavailable: {e}"

    try:
        bge = _get_bge_model()
        # Serialize BGE encode to avoid OMP thread thrashing under parallel
        # tool execution; see _bge_encode_lock comment in build_subgraph_schema.
        with _bge_encode_lock:
            query_emb = bge.encode([semantic_filter], normalize_embeddings=True)[0].tolist()
    except Exception as e:
        return f"[Error] search_predicates BGE encoding failed: {e}"

    fetch_n = max(top_k * 2, top_k + 10)
    try:
        res = pred_col.query(query_embeddings=[query_emb], n_results=fetch_n)
        raw_docs = res.get("documents", [[]])[0]
    except Exception as e:
        return f"[Error] search_predicates ChromaDB query failed: {e}"

    _NOISE_PREFIXES = ("type.", "common.", "freebase.", "kg.", "dataworld.", "user.", "base.rosetta.")
    seen = set()
    candidates: List[str] = []
    for doc in raw_docs:
        pred = _normalize_chroma_doc(doc)
        if not pred or pred in seen:
            continue
        if pred.startswith(_NOISE_PREFIXES):
            continue
        if pred in ("type.object.name", "common.topic.description"):
            continue
        seen.add(pred)
        candidates.append(pred)

    if not candidates:
        return f"[Search Predicate] No predicates found for '{semantic_filter}'."

    candidates = candidates[:top_k]
    rel2desc = _get_rel2desc()

    lines: List[str] = [
        f"[Search Predicate] semantic_filter: '{semantic_filter}', top {len(candidates)} candidates:",
        "",
    ]
    for pred in candidates:
        desc_list = rel2desc.get(pred) or []
        if len(desc_list) >= 2:
            description = f"{desc_list[0]} {desc_list[1]}"
        elif len(desc_list) == 1:
            description = desc_list[0]
        else:
            description = "(no description available)"
        lines.append(f"predicate   : {pred}")
        lines.append(f"description : {description}")
        lines.append("")

    return "\n".join(lines).rstrip()
