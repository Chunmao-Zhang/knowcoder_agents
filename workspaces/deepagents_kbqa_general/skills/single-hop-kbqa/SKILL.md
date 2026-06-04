---
name: single-hop-kbqa
description: Use when the question names or implies a topic entity_name and one graph predicate reaches the answer.
---

# Single-Hop KBQA

Use this skill when:

- The question provides or implies one topic entity name from the active scoped graph runtime.
- The answer is reachable by one predicate from that topic entity.
- A missing bracket or missing numeric identifier does not make this zero-TE; search the entity name first.

## Tool Names

Use direct harness tool calls: `search_entity`, `list_predicates_by_entity`, `build_subgraph_schema`, `execute_code`.

## Entity Name Rule

An `entity_name` is the exact subject/object string in the uploaded triples. Copy it exactly from `search_entity` output and use that term consistently.

## Workflow

1. If only an entity mention or related phrase is given, call `search_entity(query=<shortest likely entity phrase>, top_k=5)`. Select the canonical `entity_name` string.
2. `list_predicates_by_entity(entity_name=<topic entity_name>, semantic_filter=<question>, top_k=20)` to inspect outgoing and incoming predicates.
3. Pick up to five predicates whose direction and wording match the asked answer type. Skip zero-count rows.
4. `build_subgraph_schema(start_entity_names=[<topic entity_name>], predicates=[<picks>], hop=1)`.
5. `execute_code` to traverse `entities_by_name[<topic entity_name>].<attr>` and write final names into `result_dict['direct_results']` or keyed details into `result_dict['detailed_results']`.

## Extraction Pattern

```python
topic = entities_by_name.get("Alice")
for ans in getattr(topic, "works_at", []):
    name = get_name(ans) or getattr(ans, "_name", "")
    if name:
        result_dict["direct_results"].append(name)
```

Final answer format:

```text
\boxed{["answer name"]}
```
