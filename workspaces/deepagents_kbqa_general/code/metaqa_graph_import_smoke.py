#!/usr/bin/env python3
"""Smoke test KBQA General graph-import processing.

This exercises the same backend helper used by `/api/graphs/imports`: uploaded
`subject|relation|object` text is appended to the shared graph ledger, tagged
with graph UUID/name metadata, and converted to full/scoped runtime artifacts.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspaces.deepagents_kbqa_general.code.graph_runtime import import_uploaded_graph


SAMPLE = """\
Before the Rain|starred_actors|Grégoire Colin
Before the Rain|directed_by|Milcho Manchevski
Before the Rain|release_year|1994
"""


def main() -> int:
    report = import_uploaded_graph(
        filename="smoke_graph.txt",
        raw_content=SAMPLE.encode("utf-8"),
        graph_name="frontend-import-smoke",
    )
    processed_dir = Path(report["processed_dir"])
    required = [
        "entity2id.tsv",
        "relation2id.tsv",
        "triples_named.tsv",
        "triples_encoded.tsv",
        "train2id.txt",
        "manifest.json",
        "graph/manifest.tsv",
    ]
    missing = [rel for rel in required if not (processed_dir / rel).exists()]
    if missing:
        raise AssertionError(f"missing generated files: {missing}")
    stats = report["stats"]
    if stats["triple_count"] != 3 or stats["relation_count"] != 3:
        raise AssertionError(f"unexpected stats: {stats}")

    if not report.get("id") or "-" not in report["id"]:
        raise AssertionError(f"expected UUID graph id, got: {report.get('id')}")

    print("KBQA General graph import smoke: PASS")
    print(f"id: {report['id']}")
    print(f"raw: {report['raw_path']}")
    print(f"processed: {report['processed_dir']}")
    print(f"stats: {stats['entity_count']} entities · {stats['relation_count']} relations · {stats['triple_count']} triples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
