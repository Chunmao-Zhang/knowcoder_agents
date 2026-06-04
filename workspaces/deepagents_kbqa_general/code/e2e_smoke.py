#!/usr/bin/env python3
"""End-to-end smoke test for the Code On Graph Agent workspace."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = ROOT / "workspaces" / "deepagents_kbqa_general"
RUNTIME_ROOT = ROOT / "data" / "deepagents_kbqa_general" / "runtime"
OUT_BASE = ROOT / "outputs" / "deepagents_kbqa_general" / "e2e_smoke"

EXPECTED_TOOLS = [
    "search_entity",
    "search_predicate",
    "list_predicates_by_entity",
    "search_entity_by_predicate",
    "build_subgraph_schema",
    "execute_code",
]

SAMPLE_GRAPH = """\
Before the Rain|starred_actors|Grégoire Colin
Before the Rain|directed_by|Milcho Manchevski
Before the Rain|release_year|1994
"""


@dataclass
class StepResult:
    name: str
    ok: bool
    duration_sec: float
    preview: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _preview(value: Any, limit: int = 1400) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "\n... [truncated]"


def _run_step(name: str, func: Callable[[], tuple[str, dict[str, Any]]]) -> StepResult:
    start = time.monotonic()
    try:
        preview, metadata = func()
        return StepResult(
            name=name,
            ok=True,
            duration_sec=round(time.monotonic() - start, 3),
            preview=_preview(preview),
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001 - report all smoke failures uniformly
        return StepResult(
            name=name,
            ok=False,
            duration_sec=round(time.monotonic() - start, 3),
            error=f"{type(exc).__name__}: {exc}",
        )


def _prepare_env() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.environ["KBQA_RUNTIME_ROOT"] = str(RUNTIME_ROOT)
    os.environ["KBQA_PROJECT_ROOT"] = str(RUNTIME_ROOT)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    os.environ.setdefault("MKL_NUM_THREADS", "4")

    from workspaces.deepagents_kbqa_general.tools_impl.paths import configure_environment

    configure_environment()


def _tool_catalog() -> dict[str, Any]:
    from harness.agents.registry import AgentRegistry
    from harness.config import load_config
    from harness.tools.registry import get_tools_for_agent

    cfg = load_config(ROOT / "harness.json")
    registry = AgentRegistry(cfg)
    agent = registry.get("deepagents_kbqa_general")
    tools = get_tools_for_agent(
        agent,
        workspace_dir=str(ROOT / agent.workspace),
        harness_root=str(ROOT),
    )
    return {tool.name: tool for tool in tools}


def _assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label} missing expected text: {needle!r}\n{text}")


def _registry_tools() -> tuple[str, dict[str, Any]]:
    tools = _tool_catalog()
    missing = [name for name in EXPECTED_TOOLS if name not in tools]
    if missing:
        raise AssertionError(f"deepagents_kbqa_general missing tools: {missing}")

    from harness.agents.registry import AgentRegistry
    from harness.config import load_config
    from harness.tools.registry import get_tools_for_agent

    cfg = load_config(ROOT / "harness.json")
    registry = AgentRegistry(cfg)
    otology_agent = registry.get("otology_skill")
    otology_tools = {
        tool.name
        for tool in get_tools_for_agent(
            otology_agent,
            workspace_dir=str(ROOT / otology_agent.workspace),
            harness_root=str(ROOT),
        )
    }
    leaked = [name for name in EXPECTED_TOOLS if name in otology_tools]
    if leaked:
        raise AssertionError(f"otology_skill should not expose KBQA tools: {leaked}")

    metadata = {
        "deepagents_kbqa_general": sorted(tools),
        "otology_skill": sorted(otology_tools),
    }
    return json.dumps(metadata, ensure_ascii=False), {"tool_count": len(tools), "tools": sorted(tools)}


def _ensure_active_graph_runtime() -> tuple[str, dict[str, Any]]:
    from workspaces.deepagents_kbqa_general.code.graph_runtime import (
        activate_graph_scope,
        import_uploaded_graph,
        list_graphs,
        summarize_graph,
    )

    imported = None
    if not list_graphs():
        imported = import_uploaded_graph(
            filename="e2e_smoke_graph.txt",
            raw_content=SAMPLE_GRAPH.encode("utf-8"),
            graph_name="e2e-smoke-graph",
        )
    scope = activate_graph_scope(None)
    summary = summarize_graph()
    stats = summary.get("stats") or {}
    if int(stats.get("triple_count") or 0) <= 0:
        raise AssertionError(f"active graph has no triples: {stats}")
    preview = {
        "scope": scope,
        "stats": stats,
        "imported": imported,
    }
    return json.dumps(preview, ensure_ascii=False, indent=2), {"stats": stats, "imported": bool(imported)}


def _search_entity_exact() -> tuple[str, dict[str, Any]]:
    output = _tool_catalog()["search_entity"]._run("Before the Rain", top_k=3)
    _assert_contains(output, "entity_name : Before the Rain", "search_entity exact")
    _assert_contains(output, "matched_by  : exact", "search_entity exact")
    return output, {"query": "Before the Rain"}


def _search_entity_vector() -> tuple[str, dict[str, Any]]:
    output = _tool_catalog()["search_entity"]._run(
        "actor named Gregoire Colin in the movie graph",
        top_k=5,
        semantic_filter="movie actor",
    )
    _assert_contains(output, "entity_name : Grégoire Colin", "search_entity vector")
    _assert_contains(output, "matched_by  : vector", "search_entity vector")
    return output, {"query": "actor named Gregoire Colin in the movie graph"}


def _search_predicate() -> tuple[str, dict[str, Any]]:
    output = _tool_catalog()["search_predicate"]._run("movie release year", top_k=5)
    _assert_contains(output, "predicate   : release_year", "search_predicate")
    return output, {"semantic_filter": "movie release year"}


def _search_entity_by_predicate() -> tuple[str, dict[str, Any]]:
    output = _tool_catalog()["search_entity_by_predicate"]._run(
        predicate="directed_by",
        value="Milcho Manchevski",
        top_k=5,
    )
    _assert_contains(output, "Before the Rain", "search_entity_by_predicate")
    return output, {"predicate": "directed_by", "value": "Milcho Manchevski"}


def _list_predicates() -> tuple[str, dict[str, Any]]:
    output = _tool_catalog()["list_predicates_by_entity"]._run(
        entity_name="Before the Rain",
        semantic_filter="movie release date director actor",
        top_k=10,
    )
    _assert_contains(output, "release_year", "list_predicates_by_entity")
    _assert_contains(output, "directed_by", "list_predicates_by_entity")
    return output, {"entity_name": "Before the Rain"}


def _build_and_execute() -> tuple[str, dict[str, Any]]:
    tools = _tool_catalog()
    schema = tools["build_subgraph_schema"]._run(
        start_entity_names=["Before the Rain"],
        predicates=["release_year", "directed_by", "starred_actors"],
        hop=1,
    )
    match = re.search(r"# subgraph_file:\s*(\S+)", schema)
    if not match:
        raise AssertionError(f"build_subgraph_schema did not return # subgraph_file\n{schema}")
    subgraph_file = match.group(1)
    answer = tools["execute_code"]._run(
        code_lines=[
            "years = set()",
            "for entity in entities:",
            "    for value in getattr(entity, 'release_year', []):",
            "        years.add(str(getattr(value, '_value', get_name(value))))",
            "result_dict['direct_results'] = sorted(years)",
        ],
        subgraph_file=subgraph_file,
    )
    _assert_contains(answer, 'ANSWER: ["1994"]', "execute_code")
    return schema + "\n\n" + answer, {"subgraph_file": subgraph_file}


def _write_report(out_dir: Path, results: list[StepResult], quick: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "e2e_results.json"
    report_path = out_dir / "E2E_REPORT.md"
    serializable = {
        "status": "PASS" if all(step.ok for step in results) else "FAIL",
        "quick": quick,
        "workspace_root": str(WORKSPACE_ROOT),
        "runtime_root": str(RUNTIME_ROOT),
        "steps": [step.__dict__ for step in results],
    }
    json_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Code On Graph Agent E2E Smoke Report",
        "",
        f"- Status: {serializable['status']}",
        f"- Quick mode: {quick}",
        f"- Workspace root: `{WORKSPACE_ROOT}`",
        f"- Runtime root: `{RUNTIME_ROOT}`",
        f"- JSON results: `{json_path}`",
        "",
        "## Steps",
        "",
    ]
    for step in results:
        status = "PASS" if step.ok else "FAIL"
        lines.append(f"### {step.name}: {status}")
        lines.append(f"- Duration: {step.duration_sec}s")
        if step.metadata:
            lines.append(f"- Metadata: `{json.dumps(step.metadata, ensure_ascii=False)}`")
        if step.error:
            lines.append(f"- Error: `{step.error}`")
        if step.preview:
            lines.extend(["", "```text", step.preview, "```"])
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Code On Graph Agent smoke test.")
    parser.add_argument("--quick", action="store_true", help="Skip vector-only semantic search checks.")
    args = parser.parse_args()

    _prepare_env()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_BASE / run_id
    checks: list[tuple[str, Callable[[], tuple[str, dict[str, Any]]]]] = [
        ("workspace_tool_registry", _registry_tools),
        ("active_graph_runtime", _ensure_active_graph_runtime),
        ("search_entity_exact", _search_entity_exact),
        ("list_predicates_by_entity", _list_predicates),
        ("build_subgraph_and_execute_code", _build_and_execute),
    ]
    if not args.quick:
        checks[3:3] = [
            ("search_entity_vector", _search_entity_vector),
            ("search_predicate", _search_predicate),
            ("search_entity_by_predicate", _search_entity_by_predicate),
        ]

    results: list[StepResult] = []
    for name, func in checks:
        result = _run_step(name, func)
        results.append(result)
        if not result.ok:
            break

    report_path = _write_report(out_dir, results, args.quick)
    status = "PASS" if all(step.ok for step in results) else "FAIL"
    print(f"status={status}")
    print(f"output_dir={out_dir}")
    print(f"report={report_path}")
    print(f"steps={len(results)}")
    print(f"passed={sum(1 for step in results if step.ok)}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
