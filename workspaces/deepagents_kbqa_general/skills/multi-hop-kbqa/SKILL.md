---
name: multi-hop-kbqa
description: Use when the question names or implies a topic entity_name but answering requires two or more graph hops, reverse edges, exclusions, or chained constraints.
---

# Multi-Hop KBQA

Use this skill when:

- A topic entity name is known, or an entity mention can be resolved with `search_entity`.
- The answer requires two or more predicates.
- The first hop lands on a mediator/intermediate entity.
- The question applies date, type, count, intersection, exclusion, or comparison constraints.

## Tool Names

Use direct harness tool calls: `search_entity`, `list_predicates_by_entity`, `build_subgraph_schema`, `execute_code`.

## Entity Name Rule

Every subject/object string in the uploaded triples is an `entity_name`. Copy exact strings from tool output and use that term consistently.

## Per-Hop Workflow

Resolve the topic entity first when the question gives only a name/mention or related phrase:

1. `search_entity(query=<shortest likely entity phrase>, top_k=5)`.
2. Select the exact `entity_name` that best matches the question context.

For each hop:

1. `list_predicates_by_entity(entity_name=<anchor entity_name>, semantic_filter=<subtask>)`.
2. Select predicates by direction and answer type first, then wording, then lower fanout.
3. `build_subgraph_schema(start_entity_names=[<anchor entity_name>], predicates=[<picks>], hop=1)`.
4. `execute_code`:
   - Intermediate hop: collect next-hop entity names into `result_dict['direct_results']`.
   - Final hop: emit final answer names into `result_dict['direct_results']` or `detailed_results`.

The next hop's `start_entity_names` come from the previous `execute_code` result.

## Anchor Rule for execute_code

In `execute_code`, **only use the most recent `build_subgraph_schema`'s `start_entity_names` as traversal anchors**. Entities that appear only as tails in the subgraph have **no outgoing attributes** — accessing their `*_r` attrs returns empty lists.

Correct pattern (start entities are actors):
```python
for actor in entities:
    for movie in actor.starred_actors_r:
        result_dict['direct_results'].append(movie._entity_name)
```

Wrong pattern (seed movie was NOT a start entity):
```python
seed = entities_by_name['Some Movie']
actors = seed.starred_actors_r  # EMPTY — seed is tail-only in actor-rooted subgraph
```

If you need to traverse from a different anchor, call `build_subgraph_schema` again with that entity as `start_entity_names`.

## Predicate Disambiguation

Pick predicates in this order:

1. Direction matches the question.
2. Surface wording matches the question.
3. Answer type or examples match the requested answer.
4. Reachable count is a warning signal, not the main decision.

Final answer format:

```text
\boxed{["answer name 1", "answer name 2"]}
```
