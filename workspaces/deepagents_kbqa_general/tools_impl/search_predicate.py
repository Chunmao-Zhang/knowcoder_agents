"""Vector search over predicates in the active generic graph."""

from __future__ import annotations

from typing import List, Optional


def search_predicates(
    semantic_filter: str,
    top_k: int = 20,
    run_id: Optional[str] = None,
) -> str:
    """Search relation predicates by natural-language semantics using Chroma/BGE."""
    if not isinstance(semantic_filter, str) or not semantic_filter.strip():
        return "[Error] search_predicates requires a non-empty `semantic_filter`."

    semantic_filter = semantic_filter.strip()
    top_k = max(1, min(int(top_k or 20), 50))

    try:
        from .build_subgraph_schema import _get_rel2desc, search_predicates_by_text
        candidates = search_predicates_by_text(semantic_filter, top_k=top_k)
        rel2desc = _get_rel2desc()
    except Exception as exc:
        return f"[Error] search_predicates active graph unavailable: {type(exc).__name__}: {exc}"

    if not candidates:
        return f"[Search Predicate] No predicates found for '{semantic_filter}'."

    lines: List[str] = [
        f"[Search Predicate] semantic_filter: '{semantic_filter}', top {len(candidates)} candidates:",
        "",
    ]
    for item in candidates:
        pred = str(item.get("predicate") or "")
        desc_list = rel2desc.get(pred) or []
        description = str(item.get("description") or " ".join(str(x) for x in desc_list) or "(no description available)")
        lines.append(f"predicate   : {pred}")
        lines.append(f"description : {description}")
        lines.append("")
    return "\n".join(lines).rstrip()
