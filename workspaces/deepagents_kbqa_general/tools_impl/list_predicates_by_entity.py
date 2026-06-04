"""List outgoing/incoming predicates for an entity in the active generic graph."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from loguru import logger


def _domain_of(pred: str) -> str:
    raw = pred.removesuffix(".r")
    if "." in raw:
        return raw.split(".", 1)[0]
    if "_" in raw:
        return raw.split("_", 1)[0]
    return "graph"


def _triplet_types(raw_pred: str, is_reverse: bool) -> Tuple[str, str]:
    from .build_subgraph_schema import _get_type_from_pred

    if is_reverse:
        head = _get_type_from_pred(raw_pred, "tail")
        tail = _get_type_from_pred(raw_pred, "head")
    else:
        head = _get_type_from_pred(raw_pred, "head")
        tail = _get_type_from_pred(raw_pred, "tail")
    return head or "Entity", tail or "Entity"


def _format_grouped_section(
    title: str,
    pred_counts: Dict[str, int],
    semantic_filter: str,
    top_k: int,
    is_reverse: bool,
) -> List[str]:
    lines = [f"## {title}", ""]
    if not pred_counts:
        lines.append("  (no candidates)")
        return lines

    from .build_subgraph_schema import _topk_preds_by_bge

    all_preds = list(pred_counts.keys())
    try:
        ranked = _topk_preds_by_bge(semantic_filter, all_preds, min(top_k, len(all_preds)))
    except Exception as exc:
        logger.debug(f"[list_predicates] BGE rerank failed, fall back to count desc: {exc}")
        ranked = sorted(all_preds, key=lambda p: -pred_counts.get(p, 0))[:top_k]

    grouped: Dict[str, List[str]] = defaultdict(list)
    domain_order: list[str] = []
    for pred in ranked:
        dom = _domain_of(pred)
        if dom not in grouped:
            domain_order.append(dom)
        grouped[dom].append(pred)

    for dom in domain_order:
        lines.append(f"  [{dom}]")
        for pred in grouped[dom]:
            cnt = pred_counts.get(pred, 0)
            head_type, tail_type = _triplet_types(pred, is_reverse)
            display = f"{pred}.r" if is_reverse else pred
            lines.append(f"    ({head_type}, {display}, {tail_type}) -> {cnt}")
    return lines


def list_predicates_by_entity(
    entity_name: str = "",
    semantic_filter: str = "",
    top_k: int = 30,
    run_id: Optional[str] = None,
) -> str:
    """Enumerate candidate predicates on one generic graph entity.

    Pass the exact entity name string from the active graph.
    """
    if not isinstance(entity_name, str) or not entity_name.strip():
        return "[Error] list_predicates requires a non-empty `entity_name` string copied from search_entity."
    entity_name = entity_name.strip()
    semantic_filter = semantic_filter.strip() if isinstance(semantic_filter, str) else ""
    if not semantic_filter:
        semantic_filter = f"relations connected to {entity_name}"
    top_k = max(1, min(int(top_k or 30), 100))

    try:
        from .build_subgraph_schema import _predicate_counts
        out_counts = _predicate_counts(entity_name, "out")
        in_counts = _predicate_counts(entity_name, "in")
    except Exception as exc:
        return f"[Error] list_predicates active graph unavailable: {type(exc).__name__}: {exc}"

    lines: List[str] = [
        f"[List Predicates] entity_name={entity_name!r}, semantic_filter={semantic_filter!r}",
        "",
    ]
    lines.extend(_format_grouped_section("Outgoing", out_counts, semantic_filter, top_k, is_reverse=False))
    lines.append("")
    lines.extend(_format_grouped_section("Incoming", in_counts, semantic_filter, top_k, is_reverse=True))
    if not out_counts and not in_counts:
        lines.append("")
        lines.append("No predicates found. Verify the entity_name with search_entity and ensure prepare.py activated the uploaded graph.")
    return "\n".join(lines).rstrip()
