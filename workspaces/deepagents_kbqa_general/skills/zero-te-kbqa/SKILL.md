---
name: zero-te-kbqa
description: Use when no topic entity_name can be grounded and the question asks globally which entities satisfy a predicate, value, aggregate, or ranking condition.
---

# Zero-Topic-Entity KBQA

Use this skill only when there is truly no topic entity name to ground. If the question mentions a person, object, organization, place, product, movie, or other concrete entity phrase, call `search_entity` first and then use single-hop or multi-hop.

## Tool Names

Use direct harness tool calls: `search_predicate`, `search_entity_by_predicate`, `list_predicates_by_entity`, `build_subgraph_schema`, `execute_code`.

## Workflow

1. `search_predicate(semantic_filter=<relation semantics>, top_k=20)` to find candidate predicates in the active scoped graph runtime.
2. If the question includes a literal/entity value constraint, call `search_entity_by_predicate(predicate=<predicate>, value=<exact value>, semantic_filter=<question>, top_k=50)`.
3. Copy returned entity names exactly.
4. If more hops or constraints are needed, call `list_predicates_by_entity(entity_name=<representative entity_name>, semantic_filter=<next relation>)` and then `build_subgraph_schema(start_entity_names=[...], predicates=[...])`.
5. Use `execute_code` for filtering, aggregation, sorting, and final answer formatting.

## Output Discipline

- Use the term `entity_name` consistently for graph entities.
- Final answer format: `\boxed{["answer name"]}`.
- Count answers are strings, for example `\boxed{["7"]}`.
