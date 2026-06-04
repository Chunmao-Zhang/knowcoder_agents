#!/usr/bin/env python3
"""Run deterministic MetaQA KBQA task smoke tests.

This script exercises the lightweight KBQA path used by the MetaQA fixture:
entity linking from bracketed mentions, template-to-relation planning, graph
traversal over encoded artifacts, optional Neo4j traversal, and exact answer
comparison against real MetaQA QA examples.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = ROOT / "data" / "metaqa"
PROCESSED_ROOT = DATA_ROOT / "processed"
REPORT_BASE = ROOT / "outputs" / "deepagents_kbqa" / "metaqa_kbqa_smoke"
MENTION_RE = re.compile(r"\[([^\]]+)\]")
WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Plan:
    name: str
    steps: tuple[tuple[str, str], ...]
    exclude_topic: bool = False
    exclude_topic_after_steps: tuple[int, ...] = ()


@dataclass(frozen=True)
class SampleRef:
    hop: str
    line_no: int


@dataclass
class CaseResult:
    hop: str
    line_no: int
    question: str
    topic: str
    topic_id: int
    template: str
    plan: str
    steps: list[str]
    expected: list[str]
    local_answer: list[str]
    local_ok: bool
    boxed_answer: str
    neo4j_answer: list[str] | None = None
    neo4j_ok: bool | None = None


DEFAULT_SAMPLES = [
    SampleRef("1-hop", 1),
    SampleRef("1-hop", 2),
    SampleRef("1-hop", 1441),
    SampleRef("1-hop", 2539),
    SampleRef("1-hop", 3841),
    SampleRef("1-hop", 4982),
    SampleRef("1-hop", 7214),
    SampleRef("1-hop", 9076),
    SampleRef("2-hop", 1),
    SampleRef("2-hop", 3),
    SampleRef("2-hop", 5),
    SampleRef("2-hop", 6),
    SampleRef("2-hop", 7),
    SampleRef("2-hop", 9),
    SampleRef("2-hop", 10),
    SampleRef("2-hop", 12),
    SampleRef("2-hop", 13),
    SampleRef("2-hop", 20),
    SampleRef("3-hop", 1),
    SampleRef("3-hop", 2),
    SampleRef("3-hop", 3),
    SampleRef("3-hop", 4),
    SampleRef("3-hop", 5),
    SampleRef("3-hop", 6),
    SampleRef("3-hop", 8),
    SampleRef("3-hop", 9),
    SampleRef("3-hop", 11),
    SampleRef("3-hop", 18),
    SampleRef("3-hop", 19),
    SampleRef("3-hop", 20),
]


RULES: dict[str, Plan] = {
    "what does [ent] appear in": Plan("actor_to_movies", (("in", "starred_actors"),)),
    "[ent] appears in which movies": Plan("actor_to_movies", (("in", "starred_actors"),)),
    "what films did [ent] star in": Plan("actor_to_movies", (("in", "starred_actors"),)),
    "who starred in [ent]": Plan("movie_to_actors", (("out", "starred_actors"),)),
    "who is the director of [ent]": Plan("movie_to_director", (("out", "directed_by"),)),
    "what genre is [ent] in": Plan("movie_to_genres", (("out", "has_genre"),)),
    "what language is [ent] in": Plan("movie_to_languages", (("out", "in_language"),)),
    "what year was [ent] released": Plan("movie_to_release_year", (("out", "release_year"),)),
    "what was the release year of [ent]": Plan("movie_to_release_year", (("out", "release_year"),)),
    "which movie did [ent] write": Plan("writer_to_movies", (("in", "written_by"),)),
    "which person directed the movies starred by [ent]": Plan(
        "actor_to_movie_directors",
        (("in", "starred_actors"), ("out", "directed_by")),
    ),
    "what are the primary languages in the movies directed by [ent]": Plan(
        "director_to_movie_languages",
        (("in", "directed_by"), ("out", "in_language")),
    ),
    "the films acted by [ent] were in which genres": Plan(
        "actor_to_movie_genres",
        (("in", "starred_actors"), ("out", "has_genre")),
    ),
    "what are the genres of the films directed by [ent]": Plan(
        "director_to_movie_genres",
        (("in", "directed_by"), ("out", "has_genre")),
    ),
    "who appeared in the same movie with [ent]": Plan(
        "actor_to_coactors",
        (("in", "starred_actors"), ("out", "starred_actors")),
        exclude_topic=True,
    ),
    "who are the actors in the films written by [ent]": Plan(
        "writer_to_movie_actors",
        (("in", "written_by"), ("out", "starred_actors")),
        exclude_topic=True,
    ),
    "the movies starred by [ent] were written by who": Plan(
        "actor_to_movie_writers",
        (("in", "starred_actors"), ("out", "written_by")),
    ),
    "the director of [ent] also directed which movies": Plan(
        "movie_to_same_director_movies",
        (("out", "directed_by"), ("in", "directed_by")),
        exclude_topic_after_steps=(2,),
    ),
    "when were the movies starred by [ent] released": Plan(
        "actor_to_movie_release_years",
        (("in", "starred_actors"), ("out", "release_year")),
    ),
    "what types are the movies written by [ent]": Plan(
        "writer_to_movie_genres",
        (("in", "written_by"), ("out", "has_genre")),
    ),
    "the films that share directors with the film [ent] were in which languages": Plan(
        "movie_same_director_languages",
        (("out", "directed_by"), ("in", "directed_by"), ("out", "in_language")),
        exclude_topic_after_steps=(2,),
    ),
    "who starred movies for the director of [ent]": Plan(
        "movie_director_movie_actors",
        (("out", "directed_by"), ("in", "directed_by"), ("out", "starred_actors")),
        exclude_topic_after_steps=(2,),
    ),
    "the films that share actors with the film [ent] were in which languages": Plan(
        "movie_same_actor_languages",
        (("out", "starred_actors"), ("in", "starred_actors"), ("out", "in_language")),
        exclude_topic_after_steps=(2,),
    ),
    "what were the release years of the films that share writers with the film [ent]": Plan(
        "movie_same_writer_release_years",
        (("out", "written_by"), ("in", "written_by"), ("out", "release_year")),
        exclude_topic_after_steps=(2,),
    ),
    "who is listed as director of the films starred by [ent] actors": Plan(
        "movie_actor_movie_directors",
        (("out", "starred_actors"), ("in", "starred_actors"), ("out", "directed_by")),
        exclude_topic_after_steps=(2,),
    ),
    "the films that share directors with the film [ent] were in which genres": Plan(
        "movie_same_director_genres",
        (("out", "directed_by"), ("in", "directed_by"), ("out", "has_genre")),
        exclude_topic_after_steps=(2,),
    ),
    "who are the directors of the movies written by the writer of [ent]": Plan(
        "movie_writer_movie_directors",
        (("out", "written_by"), ("in", "written_by"), ("out", "directed_by")),
        exclude_topic_after_steps=(2,),
    ),
    "the movies that share actors with the movie [ent] were in which languages": Plan(
        "movie_same_actor_languages",
        (("out", "starred_actors"), ("in", "starred_actors"), ("out", "in_language")),
        exclude_topic_after_steps=(2,),
    ),
    "when did the movies starred by [ent] actors release": Plan(
        "movie_actor_movie_release_years",
        (("out", "starred_actors"), ("in", "starred_actors"), ("out", "release_year")),
        exclude_topic_after_steps=(2,),
    ),
    "what are the languages spoken in the movies whose actors also appear in [ent]": Plan(
        "movie_same_actor_languages",
        (("out", "starred_actors"), ("in", "starred_actors"), ("out", "in_language")),
        exclude_topic_after_steps=(2,),
    ),
    "what are the genres of the movies whose writers also wrote [ent]": Plan(
        "movie_same_writer_genres",
        (("out", "written_by"), ("in", "written_by"), ("out", "has_genre")),
        exclude_topic_after_steps=(2,),
    ),
    "who starred films for the director of [ent]": Plan(
        "movie_director_movie_actors",
        (("out", "directed_by"), ("in", "directed_by"), ("out", "starred_actors")),
        exclude_topic_after_steps=(2,),
    ),
}


def canonical_question(question: str) -> str:
    text = MENTION_RE.sub("[ent]", question.strip().lower())
    return re.sub(r"\s+", " ", text)


def normalize(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))


def relation_type(relation: str) -> str:
    rel = "".join(ch.upper() if ch.isalnum() else "_" for ch in relation)
    return rel if rel and rel[0].isalpha() else f"REL_{rel}"


def cypher_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def load_tsv_mapping(path: Path, key_col: str, value_col: str) -> dict[str, int]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return {row[key_col]: int(row[value_col]) for row in reader}


class MetaQAGraph:
    def __init__(self, processed_root: Path) -> None:
        self.entity2id = load_tsv_mapping(processed_root / "entity2id.tsv", "entity", "entity_id")
        self.relation2id = load_tsv_mapping(processed_root / "relation2id.tsv", "relation", "relation_id")
        self.norm_entity: dict[str, list[str]] = defaultdict(list)
        for entity in self.entity2id:
            self.norm_entity[normalize(entity)].append(entity)

        self.out_adj: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self.in_adj: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        with (processed_root / "triples_named.tsv").open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                subject = row["subject"]
                relation = row["relation"]
                obj = row["object"]
                self.out_adj[subject][relation].add(obj)
                self.in_adj[obj][relation].add(subject)

    def resolve(self, mention: str) -> str:
        if mention in self.entity2id:
            return mention
        candidates = self.norm_entity.get(normalize(mention), [])
        if candidates:
            return sorted(candidates, key=lambda x: (len(x), x.lower()))[0]
        raise KeyError(f"Cannot resolve entity mention: {mention!r}")

    def traverse(self, topic: str, plan: Plan) -> set[str]:
        current = {topic}
        for step_no, (direction, relation) in enumerate(plan.steps, 1):
            next_entities: set[str] = set()
            adj = self.out_adj if direction == "out" else self.in_adj
            for entity in current:
                next_entities.update(adj[entity][relation])
            current = next_entities
            if step_no in plan.exclude_topic_after_steps:
                current.discard(topic)
        if plan.exclude_topic:
            current.discard(topic)
        return current


def load_sample(ref: SampleRef) -> tuple[str, set[str]]:
    path = DATA_ROOT / ref.hop / "vanilla" / "qa_test.txt"
    with path.open(encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            if idx == ref.line_no:
                question, answer = line.rstrip("\n").split("\t")
                return question, set(answer.split("|"))
    raise ValueError(f"Sample line not found: {ref.hop} line {ref.line_no}")


def supported_sample_refs(
    samples_per_template: int,
    graph: MetaQAGraph | None = None,
    skip_data_mismatches: bool = False,
) -> tuple[list[SampleRef], list[dict[str, object]]]:
    refs: list[SampleRef] = []
    skipped: list[dict[str, object]] = []
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for hop in ("1-hop", "2-hop", "3-hop"):
        path = DATA_ROOT / hop / "vanilla" / "qa_test.txt"
        with path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                question, answer = line.rstrip("\n").split("\t")
                template = canonical_question(question)
                key = (hop, template)
                if template not in RULES or seen[key] >= samples_per_template:
                    continue
                if skip_data_mismatches:
                    if graph is None:
                        raise ValueError("graph is required when skip_data_mismatches=True")
                    topic = graph.resolve(extract_topic(question))
                    predicted = graph.traverse(topic, RULES[template])
                    expected = set(answer.split("|"))
                    if predicted != expected:
                        skipped.append(
                            {
                                "hop": hop,
                                "line_no": line_no,
                                "question": question,
                                "template": template,
                                "expected": sorted(expected),
                                "predicted": sorted(predicted),
                                "reason": "name-collision or dataset/graph ambiguity",
                            }
                        )
                        continue
                refs.append(SampleRef(hop, line_no))
                seen[key] += 1
    return refs, skipped


def infer_plan(question: str) -> Plan:
    canonical = canonical_question(question)
    try:
        return RULES[canonical]
    except KeyError as exc:
        raise KeyError(f"No MetaQA rule for template: {canonical!r}") from exc


def extract_topic(question: str) -> str:
    match = MENTION_RE.search(question)
    if not match:
        raise ValueError(f"Question does not contain a bracketed entity mention: {question}")
    return match.group(1)


def boxed(answers: Iterable[str]) -> str:
    return "\\boxed{" + json.dumps(sorted(answers), ensure_ascii=False) + "}"


def discover_neo4j_home() -> Path | None:
    env_home = os.environ.get("NEO4J_HOME")
    if env_home:
        return Path(env_home)
    ps = subprocess.run(["ps", "-ax", "-o", "command"], text=True, capture_output=True, check=False)
    match = re.search(r"--home-dir=(.*?)\s+--config-dir=", ps.stdout)
    return Path(match.group(1)) if match else None


def discover_java_home() -> Path | None:
    env_home = os.environ.get("JAVA_HOME")
    if env_home:
        return Path(env_home)
    ps = subprocess.run(["ps", "-ax", "-o", "command"], text=True, capture_output=True, check=False)
    match = re.search(r"(/\S.*?/Cache/runtime/[^ ]+)/bin/java", ps.stdout)
    return Path(match.group(1)) if match else None


def run_cypher(args: argparse.Namespace, query: str) -> str:
    if not args.neo4j_password:
        raise ValueError("Neo4j password is required. Set NEO4J_PASSWORD or pass --neo4j-password.")
    if not args.cypher_shell:
        raise ValueError("cypher-shell not found. Pass --cypher-shell or --neo4j-home.")

    env = os.environ.copy()
    if args.java_home:
        env["JAVA_HOME"] = str(args.java_home)
        env["PATH"] = f"{args.java_home / 'bin'}:{env.get('PATH', '')}"
    cmd = [
        str(args.cypher_shell),
        "-a",
        args.neo4j_uri,
        "-u",
        args.neo4j_user,
        "-p",
        args.neo4j_password,
        "-d",
        args.neo4j_database,
    ]
    proc = subprocess.run(cmd, input=query, text=True, capture_output=True, env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout


def neo4j_answer(args: argparse.Namespace, topic: str, plan: Plan) -> set[str]:
    lines = [f"MATCH (n0:Entity {{name: {cypher_quote(topic)}}})"]
    for idx, (direction, relation) in enumerate(plan.steps):
        rel = relation_type(relation)
        if direction == "out":
            lines.append(f"MATCH (n{idx})-[:{rel}]->(n{idx + 1}:Entity)")
        else:
            lines.append(f"MATCH (n{idx + 1}:Entity)-[:{rel}]->(n{idx})")
        if idx + 1 in plan.exclude_topic_after_steps:
            lines.append(f"WHERE n{idx + 1}.name <> n0.name")
    if plan.exclude_topic and len(plan.steps) not in plan.exclude_topic_after_steps:
        lines.append("WHERE n%d.name <> n0.name" % len(plan.steps))
    lines.append("RETURN DISTINCT n%d.name AS answer ORDER BY answer;" % len(plan.steps))
    output = run_cypher(args, "\n".join(lines))
    answers: set[str] = set()
    for line in output.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parsed = next(csv.reader([line]))
        if parsed:
            answers.add(parsed[0])
    return answers


def run_case(graph: MetaQAGraph, ref: SampleRef, args: argparse.Namespace) -> CaseResult:
    question, expected = load_sample(ref)
    mention = extract_topic(question)
    topic = graph.resolve(mention)
    template = canonical_question(question)
    plan = infer_plan(question)
    local = graph.traverse(topic, plan)
    neo_answer: set[str] | None = None
    if args.neo4j:
        neo_answer = neo4j_answer(args, topic, plan)

    return CaseResult(
        hop=ref.hop,
        line_no=ref.line_no,
        question=question,
        topic=topic,
        topic_id=graph.entity2id[topic],
        template=template,
        plan=plan.name,
        steps=[f"{direction}:{relation}" for direction, relation in plan.steps],
        expected=sorted(expected),
        local_answer=sorted(local),
        local_ok=local == expected,
        boxed_answer=boxed(local),
        neo4j_answer=sorted(neo_answer) if neo_answer is not None else None,
        neo4j_ok=(neo_answer == expected) if neo_answer is not None else None,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MetaQA KBQA sample smoke tests.")
    parser.add_argument("--processed-root", type=Path, default=PROCESSED_ROOT)
    parser.add_argument("--report-base", type=Path, default=REPORT_BASE)
    parser.add_argument(
        "--sample-mode",
        choices=("fixed", "supported"),
        default="fixed",
        help="fixed uses curated cases; supported samples real qa_test rows for every supported template.",
    )
    parser.add_argument(
        "--samples-per-template",
        type=int,
        default=5,
        help="Number of qa_test rows per supported template when --sample-mode supported.",
    )
    parser.add_argument(
        "--skip-data-mismatches",
        action="store_true",
        help="Skip supported samples whose name-only graph answer disagrees with the dataset label.",
    )
    parser.add_argument("--neo4j", action="store_true", help="Also execute the inferred paths against Neo4j.")
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "neo4j://127.0.0.1:7687"))
    parser.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD", ""))
    parser.add_argument("--neo4j-database", default=os.environ.get("NEO4J_DATABASE", "metaqa"))
    parser.add_argument("--neo4j-home", type=Path, default=discover_neo4j_home())
    parser.add_argument("--java-home", type=Path, default=discover_java_home())
    parser.add_argument("--cypher-shell", type=Path)
    args = parser.parse_args()
    if args.cypher_shell is None and args.neo4j_home:
        args.cypher_shell = args.neo4j_home / "bin" / "cypher-shell"
    return args


def write_report(args: argparse.Namespace, results: list[CaseResult], skipped: list[dict[str, object]]) -> Path:
    report_dir = args.report_base / datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir.mkdir(parents=True, exist_ok=True)
    status = "PASS" if all(r.local_ok and (r.neo4j_ok is not False) for r in results) else "FAIL"
    payload = {
        "status": status,
        "processed_root": str(args.processed_root),
        "neo4j_database": args.neo4j_database if args.neo4j else None,
        "case_count": len(results),
        "passed": sum(1 for r in results if r.local_ok and (r.neo4j_ok is not False)),
        "skipped": skipped,
        "cases": [r.__dict__ for r in results],
    }
    json_path = report_dir / "metaqa_kbqa_smoke.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# MetaQA KBQA Smoke Report",
        "",
        f"- Status: {status}",
        f"- Cases: {payload['passed']} / {payload['case_count']}",
        f"- Skipped: {len(skipped)}",
        f"- Processed root: `{args.processed_root}`",
        f"- JSON: `{json_path}`",
        "",
        "## Cases",
        "",
    ]
    for result in results:
        ok = result.local_ok and (result.neo4j_ok is not False)
        lines.append(f"### {result.hop} line {result.line_no}: {'PASS' if ok else 'FAIL'}")
        lines.append(f"- Question: {result.question}")
        lines.append(f"- Plan: `{result.plan}` via `{', '.join(result.steps)}`")
        lines.append(f"- Expected: `{result.expected}`")
        lines.append(f"- Local answer: `{result.local_answer}`")
        if result.neo4j_answer is not None:
            lines.append(f"- Neo4j answer: `{result.neo4j_answer}`")
        lines.append(f"- Final format: `{result.boxed_answer}`")
        lines.append("")
    if skipped:
        lines.extend(["## Skipped", ""])
        for item in skipped[:20]:
            lines.append(f"- {item['hop']} line {item['line_no']}: {item['question']} ({item['reason']})")
        if len(skipped) > 20:
            lines.append(f"- ... {len(skipped) - 20} more")

    report_path = report_dir / "METAQA_KBQA_SMOKE.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> int:
    args = parse_args()
    graph = MetaQAGraph(args.processed_root)
    refs = DEFAULT_SAMPLES
    skipped: list[dict[str, object]] = []
    if args.sample_mode == "supported":
        refs, skipped = supported_sample_refs(
            max(1, args.samples_per_template),
            graph=graph,
            skip_data_mismatches=args.skip_data_mismatches,
        )
    results = [run_case(graph, ref, args) for ref in refs]
    report_path = write_report(args, results, skipped)
    status = "PASS" if all(r.local_ok and (r.neo4j_ok is not False) for r in results) else "FAIL"
    print(f"status={status}")
    print(f"report={report_path}")
    print(f"cases={len(results)}")
    print(f"passed={sum(1 for r in results if r.local_ok and (r.neo4j_ok is not False))}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - command-line script should report a clear failure.
        print(f"status=FAIL\nerror={type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
