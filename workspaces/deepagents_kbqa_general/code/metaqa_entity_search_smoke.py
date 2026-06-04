#!/usr/bin/env python3
"""Smoke test generic graph entity grounding.

Checks two required paths:
- exact/normalized exact entity-name matching;
- vector search over encoded generic graph entity documents when exact matching fails.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspaces.deepagents_kbqa_general.code.graph_runtime import activate_graph_scope, import_uploaded_graph, list_graphs
from workspaces.deepagents_kbqa_general.tools_impl.paths import DEFAULT_GENERAL_ENV
from workspaces.deepagents_kbqa_general.tools_impl.search_entity import search_entity


SAMPLE_GRAPH = """\
Before the Rain|starred_actors|Grégoire Colin
Before the Rain|directed_by|Milcho Manchevski
Before the Rain|release_year|1994
"""


def parse_candidates(output: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for block in output.strip().split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
        if fields:
            candidates.append(fields)
    return candidates


def run_case(name: str, query: str, expected: str, expected_match: set[str], top_k: int) -> dict[str, object]:
    output = search_entity(query=query, top_k=top_k)
    candidates = parse_candidates(output)
    if not candidates:
        raise AssertionError(f"{name}: no candidates returned\n{output}")

    first = candidates[0]
    entity = first.get("entity_name") or first.get("entity_id", "")
    matched_by = first.get("matched_by", "")
    if entity != expected:
        raise AssertionError(
            f"{name}: top entity mismatch, expected {expected!r}, got {entity!r}\n{output}"
        )
    if matched_by not in expected_match:
        raise AssertionError(
            f"{name}: expected match mode in {sorted(expected_match)}, got {matched_by!r}\n{output}"
        )
    return {
        "name": name,
        "query": query,
        "top_entity": entity,
        "matched_by": matched_by,
        "score": first.get("score", ""),
    }


def ensure_runtime() -> None:
    if not list_graphs():
        import_uploaded_graph(
            filename="entity_search_smoke_graph.txt",
            raw_content=SAMPLE_GRAPH.encode("utf-8"),
            graph_name="entity-search-smoke-graph",
        )
    activate_graph_scope(None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test generic graph exact and vector entity search.")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    ensure_runtime()
    results = [
        run_case(
            name="exact",
            query="Grégoire Colin",
            expected="Grégoire Colin",
            expected_match={"exact", "normalized_exact"},
            top_k=args.top_k,
        ),
        run_case(
            name="vector_phrase",
            query="actor named Gregoire Colin in the movie graph",
            expected="Grégoire Colin",
            expected_match={"vector"},
            top_k=args.top_k,
        ),
    ]

    print("KBQA General entity search smoke: PASS")
    print(f"runtime_env: {DEFAULT_GENERAL_ENV}")
    print(f"vector_index: {DEFAULT_GENERAL_ENV / 'db_vector_chroma_general'}")
    for item in results:
        print(
            f"- {item['name']}: {item['top_entity']} "
            f"via {item['matched_by']} score={item['score']} query={item['query']!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
