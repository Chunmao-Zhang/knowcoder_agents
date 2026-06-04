"""
kbqa_tool_list_predicates.py - 谓词探针（lightweight predicate probe）
==============================================================

设计目标（对齐 docs/kbqa_tools_design.md §2.3）：
  - 枚举单个实体 (entity_mid) 上所有 Freebase 谓词（出边 + 入边）。
  - 根据 semantic_filter 用 BGE 排序。
  - 每个谓词附带 reachable entity count；count=0 被过滤。
  - 输出为两段 ## Outgoing 与 ## Incoming，每段按 Freebase domain 分组。
  - ## Incoming 谓词自动带 .r 后缀（作为方向标记），调用
    build_subgraph_schema 时保留 .r，它会被自动折叠为锚点类的 reverse 属性。
  - 输出仅为文本，不写任何文件。

输入（对齐 design.md §2.3）：
  - entity_mid: str                 单个目标 MID（必填）
  - semantic_filter: str            BGE 排序提示（必填）
  - top_k: int = 30                 每个方向最多返回的谓词数（上限 100）

输出格式（含 head/tail 类型三元组 + 出现频率 count）：
  ## Outgoing

    [film]
      (Film, film.film.directed_by, Person) -> 1
      (Film, film.film.starring, Performance) -> 19

  ## Incoming

    [film]
      (Film, film.performance.film.r, Performance) -> 19

  说明：
    - `(head, predicate, tail)` 三元组描述这条边连接的类（head / tail 取自
      rel2desc）。`## Incoming` 段的谓词带 `.r` 后缀，此时 head 是锚点实体
      所属的类（即原始谓词的 tail 侧），tail 是另一端的类（原始谓词的 head 侧）。
    - `-> N` 为该谓词在锚点实体上的 reachable entity count（N>=1）；
      count=0 记录已被过滤。
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from loguru import logger

_HERE = os.path.dirname(os.path.abspath(__file__))


# 与 build_subgraph_schema 共享的噪声谓词前缀（不在候选集中展示）
_NOISE_PREFIXES = (
    "type.",
    "common.",
    "freebase.",
    "kg.",
    "dataworld.",
    "user.",
    "base.rosetta.",
    "imdb.",
)


def _domain_of(pred: str) -> str:
    """从谓词中提取一级 domain（用于分组）。"""
    raw = pred.removesuffix(".r")
    parts = raw.split(".")
    return parts[0] if parts else "other"


def _build_count_sparql(mids: List[str], direction: str) -> str:
    """
    生成单条 GROUP BY SPARQL，一次性拿到所有谓词的 reachable count。
    direction: "out" → ?s ?p ?o, "in" → ?o ?p ?s
    """
    values_block = " ".join(f"ns:{mid}" for mid in mids)
    if direction == "out":
        body = "?s ?p ?o ."
    else:
        body = "?o ?p ?s ."
    return f"""PREFIX ns: <http://rdf.freebase.com/ns/>
SELECT ?p (COUNT(DISTINCT ?o) AS ?cnt) WHERE {{
  VALUES ?s {{ {values_block} }}
  {body}
}}
GROUP BY ?p"""


def _strip_pred_uri(uri: str) -> str:
    """ns:URI -> dot-notated predicate."""
    if not isinstance(uri, str):
        return ""
    s = uri.strip()
    s = s.lstrip("<").rstrip(">")
    if s.startswith("http://rdf.freebase.com/ns/"):
        s = s[len("http://rdf.freebase.com/ns/"):]
    if s.startswith("ns:"):
        s = s[3:]
    return s


def _query_pred_counts(mids: List[str], direction: str) -> Dict[str, int]:
    """
    返回 {predicate: reachable_count}，已过滤噪声前缀。
    """
    from .build_subgraph_schema import execute_sparql_sync

    sparql = _build_count_sparql(mids, direction)
    rows = execute_sparql_sync(sparql)
    counts: Dict[str, int] = {}
    for row in rows:
        pred = _strip_pred_uri(row.get("p", {}).get("value", ""))
        cnt_raw = row.get("cnt", {}).get("value", "0")
        try:
            cnt = int(cnt_raw)
        except (TypeError, ValueError):
            cnt = 0
        if not pred or pred.startswith(_NOISE_PREFIXES):
            continue
        counts[pred] = cnt
    return counts


def _triplet_types(raw_pred: str, is_reverse: bool) -> Tuple[str, str]:
    """返回 (head_type, tail_type)，用于三元组展示。

    - Outgoing（is_reverse=False）：锚点实体是原始谓词的 head；tail 是另一端。
    - Incoming（is_reverse=True）：谓词带 `.r`，锚点实体是原始谓词的 tail；
      展示时把锚点作为 head，另一端作为 tail（与 build_subgraph_schema
      reverse 折叠逻辑一致）。
    """
    from .build_subgraph_schema import _get_type_from_pred

    if is_reverse:
        head = _get_type_from_pred(raw_pred, "tail")
        tail = _get_type_from_pred(raw_pred, "head")
    else:
        head = _get_type_from_pred(raw_pred, "head")
        tail = _get_type_from_pred(raw_pred, "tail")

    if head == "#NONE_HEAD":
        head = "Entity"
    if tail == "#NONE_HEAD":
        tail = "Entity"
    return head, tail


def _format_grouped_section(
    title: str,
    pred_counts: Dict[str, int],
    semantic_filter: str,
    top_k: int,
    is_reverse: bool,
) -> List[str]:
    """输出一节 (## Outgoing 或 ## Incoming)，按 BGE 排序后按 domain 分组。

    对齐 design.md §2.3（增强版）：
      - 标题仅为 `## <title>`（不带汇总信息）。
      - is_reverse=True 时谓词加 .r 后缀。
      - 每行格式：`(HeadType, predicate, TailType) -> count`。
      - 调用者已预先过滤 count=0 的谓词。
    """
    lines = [f"## {title}", ""]
    if not pred_counts:
        lines.append("  (no candidates)")
        return lines

    # BGE 排序：用 semantic_filter 给所有 predicate 排序
    from .build_subgraph_schema import _topk_preds_by_bge

    all_preds = list(pred_counts.keys())
    total_n = len(all_preds)

    try:
        ranked = _topk_preds_by_bge(semantic_filter, all_preds, min(top_k, total_n))
    except Exception as exc:
        logger.debug(f"[list_predicates] BGE rerank failed, fall back to count desc: {exc}")
        ranked = sorted(all_preds, key=lambda p: -pred_counts.get(p, 0))[:top_k]

    # 按 domain 分组（保留排序顺序）
    seen_domain: Dict[str, List[str]] = defaultdict(list)
    domain_order: List[str] = []
    for pred in ranked:
        dom = _domain_of(pred)
        if dom not in seen_domain:
            domain_order.append(dom)
        seen_domain[dom].append(pred)

    for dom in domain_order:
        lines.append(f"  [{dom}]")
        for pred in seen_domain[dom]:
            cnt = pred_counts.get(pred, 0)
            head_type, tail_type = _triplet_types(pred, is_reverse)
            display = f"{pred}.r" if is_reverse else pred
            lines.append(f"    ({head_type}, {display}, {tail_type}) -> {cnt}")
    return lines


def list_predicates_by_entity(
    entity_mid: str,
    semantic_filter: str,
    top_k: int = 30,
    run_id: Optional[str] = None,  # 内部任务标识，仅用于日志关联；不暴露给 LLM
) -> str:
    """枚举单个实体上的候选谓词（对齐 docs/kbqa_tools_design.md §2.3）。

    Args:
        entity_mid: 单个目标 MID（必填）。
        semantic_filter: 描述目标谓词的自然语言（必填）；驱动 BGE 对候选谓词排序。
        top_k: 每个方向最多返回的谓词数，默认 30，上限 100。
        run_id: 内部任务标识，仅用于日志关联；非 LLM 可见入参。

    Returns:
        多行文本：两段 ## Outgoing 与 ## Incoming，每段按 Freebase domain 分组；
        每行格式 `(HeadType, predicate, TailType) -> count`。
        ## Incoming 段谓词带 .r 后缀；count=0 记录被过滤。无文件输出。
    """
    if not isinstance(entity_mid, str) or not entity_mid.strip():
        return "[Error] list_predicates requires a non-empty `entity_mid` string."
    if not isinstance(semantic_filter, str) or not semantic_filter.strip():
        return "[Error] list_predicates requires a non-empty `semantic_filter` string."

    entity_mid = entity_mid.strip()
    semantic_filter = semantic_filter.strip()
    top_k = max(1, min(int(top_k or 30), 100))

    # 始终查询两个方向。
    out_counts: Dict[str, int] = {}
    in_counts: Dict[str, int] = {}
    try:
        out_counts = _query_pred_counts([entity_mid], "out")
    except Exception as exc:
        logger.warning(f"[list_predicates] out-direction SPARQL failed: {exc}")
    try:
        in_counts = _query_pred_counts([entity_mid], "in")
    except Exception as exc:
        logger.warning(f"[list_predicates] in-direction SPARQL failed: {exc}")

    # 过滤 count=0 的记录（design.md §2.3 要求）
    out_counts = {p: c for p, c in out_counts.items() if c > 0}
    in_counts = {p: c for p, c in in_counts.items() if c > 0}

    if not out_counts and not in_counts:
        # Do NOT recommend `search_predicates` as a blanket fallback here; global
        # candidates often point the wrong direction for topic-entity questions.
        return (
            f"[list_predicates] No predicates found on {entity_mid}. "
            f"Try ONE other representative MID (if from a previous hop), "
            f"or rewrite `semantic_filter` more simply (if this IS the topic entity), "
            f"or call build_subgraph_schema with a verified predicate. "
            f"Do NOT fall back to search_predicates as a blanket strategy — "
            f"its global candidates often point the wrong direction."
        )

    body_lines: List[str] = []
    body_lines.extend(
        _format_grouped_section(
            "Outgoing",
            out_counts,
            semantic_filter,
            top_k,
            is_reverse=False,
        )
    )
    body_lines.append("")
    body_lines.extend(
        _format_grouped_section(
            "Incoming",
            in_counts,
            semantic_filter,
            top_k,
            is_reverse=True,
        )
    )

    return "\n".join(body_lines).rstrip()
