"""Entity search for the generic file-backed KBQA graph."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from .build_subgraph_schema import _get_conn, search_entities_by_text

_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Candidate:
    entity_name: str
    name: str
    score: float
    matched_by: str
    evidence: str = ""


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text))
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(_WORD_RE.findall(ascii_text.lower()))


def _format_candidates(candidates: list[Candidate]) -> str:
    if not candidates:
        return "[search_entity] No entity candidates found in the active graph. Run prepare.py or upload a graph first."
    lines: list[str] = []
    for cand in candidates:
        lines.append(f"entity_name : {cand.entity_name}")
        lines.append(f"display_name: {cand.name}")
        lines.append(f"score       : {cand.score:.3f}")
        lines.append(f"matched_by  : {cand.matched_by}")
        if cand.evidence:
            lines.append(f"evidence  : {cand.evidence}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _dedupe_rank(candidates: list[Candidate], top_k: int) -> list[Candidate]:
    best: dict[str, Candidate] = {}
    for cand in candidates:
        prev = best.get(cand.entity_name)
        if prev is None or cand.score > prev.score:
            best[cand.entity_name] = cand
    ranked = sorted(best.values(), key=lambda c: (-c.score, c.name.lower(), c.entity_name))
    return ranked[: max(1, min(int(top_k or 10), 50))]


def _sqlite_entity_candidates(query: str, top_k: int) -> list[Candidate]:
    conn = _get_conn()
    norm_q = _normalize(query)
    rows: list[sqlite3.Row] = []
    if norm_q:
        rows.extend(conn.execute(
            "SELECT name, document, triple_count FROM entities WHERE name_norm = ? ORDER BY triple_count DESC LIMIT ?",
            (norm_q, top_k * 3),
        ).fetchall())
    if len(rows) < top_k:
        rows.extend(conn.execute(
            "SELECT name, document, triple_count FROM entities WHERE name LIKE ? ORDER BY triple_count DESC LIMIT ?",
            (f"{query}%", top_k * 3),
        ).fetchall())
    if len(rows) < top_k:
        rows.extend(conn.execute(
            "SELECT name, document, triple_count FROM entities WHERE name LIKE ? ORDER BY triple_count DESC LIMIT ?",
            (f"%{query}%", top_k * 5),
        ).fetchall())

    candidates: list[Candidate] = []
    for row in rows:
        name = row["name"]
        norm_name = _normalize(name)
        if norm_q and norm_q == norm_name:
            matched_by, score = "exact", 1.0
        elif norm_q and norm_name.startswith(norm_q):
            matched_by, score = "prefix", 0.92
        elif norm_q and norm_q in norm_name:
            matched_by, score = "substring", 0.82
        else:
            matched_by = "fuzzy"
            score = SequenceMatcher(None, norm_q, norm_name).ratio() * 0.75 if norm_q else 0.5
            if score < 0.45:
                continue
        candidates.append(Candidate(name, name, score, matched_by, f"appears in {row['triple_count']} triples"))
    return candidates


def _vector_entity_candidates(query: str, top_k: int, semantic_filter: str = "") -> list[Candidate]:
    rows = search_entities_by_text(query, top_k=top_k, semantic_filter=semantic_filter)
    candidates: list[Candidate] = []
    for idx, row in enumerate(rows):
        entity_name = str(row.get("entity_name") or row.get("name") or "")
        if not entity_name:
            continue
        candidates.append(
            Candidate(
                entity_name=entity_name,
                name=str(row.get("name") or entity_name),
                score=max(0.1, 0.88 - idx * 0.02),
                matched_by=str(row.get("matched_by") or "vector"),
                evidence=str(row.get("document") or "")[:180],
            )
        )
    return candidates


def _search_general(query: str, top_k: int, semantic_filter: str = "") -> list[Candidate]:
    lexical = _sqlite_entity_candidates(query, top_k)
    if lexical and lexical[0].score >= 1.0:
        return _dedupe_rank(lexical, top_k)
    vector = _vector_entity_candidates(query, top_k, semantic_filter=semantic_filter)
    return _dedupe_rank(lexical + vector, top_k)


def search_entity(
    query: str,
    top_k: int = 10,
    semantic_filter: str = "",
    type_filter: str = "",
) -> str:
    """Search canonical entities in the active generic graph by mention/label."""
    if not isinstance(query, str) or not query.strip():
        return "[Error] search_entity requires a non-empty `query` string."

    try:
        candidates = _search_general(query.strip(), max(1, min(int(top_k or 10), 50)), semantic_filter=semantic_filter)
    except Exception as exc:
        return f"[Error] search_entity active graph unavailable: {type(exc).__name__}: {exc}"
    return _format_candidates(candidates)
