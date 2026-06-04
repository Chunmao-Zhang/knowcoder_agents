"""Find generic graph entity names that satisfy a predicate and optional value."""

from __future__ import annotations

from typing import Optional


def search_entities_by_predicate(
    predicate: str,
    semantic_filter: Optional[str] = None,
    value=None,
    top_k: int = 50,
    run_id: Optional[str] = None,
) -> str:
    """Look up entity names by predicate in the active local graph.

    Forward predicate `p` returns subjects with `(subject, p, value/anything)`.
    Reverse predicate `p.r` returns objects with `(value/anything, p, object)`.
    """
    if not isinstance(predicate, str) or not predicate.strip():
        return "[Error] search_entity_by_predicate requires a non-empty `predicate`."

    has_filter = isinstance(semantic_filter, str) and bool(semantic_filter.strip())
    has_value = value is not None and (not isinstance(value, str) or bool(value.strip()))
    if not has_filter and not has_value:
        return (
            "[Error] search_entity_by_predicate requires at least one of `semantic_filter` or `value` "
            "(otherwise the candidate set is too large to be useful)."
        )

    pred = predicate.strip()
    top_k = max(1, min(int(top_k or 50), 200))
    semantic = semantic_filter.strip() if has_filter and isinstance(semantic_filter, str) else ""

    try:
        from .build_subgraph_schema import local_search_entities_by_predicate
        rows = local_search_entities_by_predicate(pred, value=value if has_value else None, semantic_filter=semantic, top_k=top_k)
    except Exception as exc:
        return f"[Error] search_entity_by_predicate active graph unavailable: {type(exc).__name__}: {exc}"

    if not rows:
        hint = (f", value={value!r}" if has_value else "") + (f", semantic_filter={semantic!r}" if has_filter else "")
        return (
            f"[Search Entity] predicate={pred}{hint}\n"
            "No matching entities found. Try a different predicate, verify direction with list_predicates_by_entity, "
            "or relax the value/semantic constraint. Do NOT retry the same args."
        )

    lines = []
    for row in rows[:top_k]:
        entity_name = str(row.get("entity_name") or row.get("name") or "")
        display_name = str(row.get("name") or entity_name).replace('"', '\\"')
        if entity_name:
            lines.append(f'{entity_name}  "{display_name}"')
    return "\n".join(lines)
