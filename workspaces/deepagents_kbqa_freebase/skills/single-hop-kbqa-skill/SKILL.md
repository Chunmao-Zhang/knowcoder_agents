---
name: single-hop-kbqa-skill
description: Use when the question already names a topic entity AND a SINGLE Freebase predicate hop reaches the answer.
---

# Workflow

1. `list_predicates_by_entity(entity_mid=<topic>, semantic_filter=<question>)` — scan candidates.
2. Pick up to 5 predicates whose `TailType` matches the asked answer type. Skip 0-count rows.
3. `build_subgraph_schema(start_mids=<topic MIDs>, predicates=[<picks>])`.
4. **CVT escalation**: if the tail class is `# CVT`, this is NOT single-hop — call `list_predicates_by_entity` on a representative CVT MID, re-call `build_subgraph_schema` with BOTH predicates, use the NEW schema_file.
5. `execute_code` — traverse `entities_by_mid[<topic>].<attr>` and write tails into `result_dict['detailed_results']`.

If the question asks ≥ 2 attributes of the same topic, pick BOTH predicates in one `build_subgraph_schema` and emit both in one `execute_code`.

# Todo Template

Use `write_todos` to plan steps. `start_mids` repeats the topic MIDs.

```
<think>
Single hop: <topic> -> <expected predicate> -> <answer type>; CVT=no.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: list_predicates_by_entity on m.xxx", "status": "in_progress"},
  {"content": "step 2: build_subgraph_schema with selected predicates", "status": "pending"},
  {"content": "step 3: execute_code to extract answers", "status": "pending"}
])

Then immediately call list_predicates_by_entity in the same turn.

# Example

Question: `who directed the film Inception?`
Topic entities: `Inception(m.0bbm7r5)`

```
<think>
Single hop: Inception -> directed_by -> Person; CVT=no.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: list predicates on Inception", "status": "in_progress"},
  {"content": "step 2: build subgraph with directed_by", "status": "pending"},
  {"content": "step 3: execute_code to emit director", "status": "pending"}
])
→ list_predicates_by_entity(entity_mid="m.0bbm7r5", semantic_filter="director of the film", top_k=20)

Result: `(Film, film.film.directed_by, Person) -> 1`, `(Film, film.film.starring, Performance) -> 19`...
Pick `film.film.directed_by` — TailType=Person matches. Skip `starring` (TailType=Performance is CVT).

```
<think>
Todo progress: completed=[1], current=2, skipped=[]
Subtask: step 2 — build subgraph with film.film.directed_by.
Reason: TailType=Person; single-hop, no CVT.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: list predicates on Inception", "status": "completed"},
  {"content": "step 2: build subgraph with directed_by", "status": "in_progress"},
  {"content": "step 3: execute_code to emit director", "status": "pending"}
])
→ build_subgraph_schema(start_mids=["m.0bbm7r5"], predicates=["film.film.directed_by"])

Result: `Film.film_film_directed_by: List['Person']`; schema_file=`...subgraph_aaabbccd.json`.

```
<think>
Todo progress: completed=[1,2], current=3, skipped=[]
Subtask: step 3 — execute_code to get director name.
Reason: traverse film_film_directed_by; schema_file=...subgraph_aaabbccd.json.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: list predicates on Inception", "status": "completed"},
  {"content": "step 2: build subgraph with directed_by", "status": "completed"},
  {"content": "step 3: execute_code to emit director", "status": "in_progress"}
])
→ execute_code(schema_file="...subgraph_aaabbccd.json", code_lines=[...])

```python
film = entities_by_mid.get('m.0bbm7r5')
for d in getattr(film, 'film_film_directed_by', []):
    nm = mid_name_map.get(d._mid, get_name(d))
    if nm: result_dict['detailed_results'][d._mid] = {'_name': nm}
```

Final: `\boxed{["Christopher Nolan"]}`
