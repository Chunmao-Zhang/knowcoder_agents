---
name: multi-hop-kbqa-skill
description: Use when the question names a topic entity but answering requires >=2 predicate hops, a CVT mediator, or a chained intermediate entity.
---

# Workflow — Per-hop loop

For each hop (1, 2, ...):

1. `list_predicates_by_entity(entity_mid=<anchor>, semantic_filter=<sub-task>)` — never reuse hop-1 predicates on hop-2 anchors.
2. `build_subgraph_schema(start_mids=<this hop's anchors>, predicates=[<picks>])` — each hop writes its OWN schema_file.
3. `execute_code(schema_file=<this hop's path>, ...)`:
    - Intermediate hop: collect next-hop MIDs into `result_dict['direct_results']`.
    - Final hop: emit answers into `result_dict['detailed_results']`.

Next hop's `start_mids` = intermediate MIDs from previous `execute_code`.

# CVT Handling — filter, then follow

Apply constraints ON the CVT BEFORE stepping through its outgoing edge. Filtering after will over-count.

```python
for cvt in entities_by_mid[topic].people_person_employment_history:
    title = next(iter(getattr(cvt, 'business_employment_tenure_title', [])), None)
    if title and 'CEO' in (mid_name_map.get(title._mid) or ''):
        for c in getattr(cvt, 'business_employment_tenure_company', []):
            ...  # c is the real answer
```

Date-range CVTs use ISO-8601 strings; `str` comparison is correct.

# Predicate Disambiguation

Pick by (in order):
1. `TailType` matches asked answer type (e.g. `Person` vs `Ethnicity`, `Film` vs `Performance`).
2. Surface wording: `who/person` → `people.person.*`; `country/region` → `location.*`; `film/movie` → `film.*`.
3. Specificity: prefer the more specific subtype.

Reachable count alone is NOT decisive.

# Todo Template

Use `write_todos` to plan steps. Hop-1 subtasks reference topic MIDs; later hops reference intermediate MIDs from previous steps.

```
<think>
Hop 1: <topic> -> <relation> -> <CVT/intermediate>. Hop 2: <intermediate> -> <relation> -> <answer>; filter <constraint>.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: list_predicates hop-1 on topic", "status": "in_progress"},
  {"content": "step 2: build_subgraph hop-1", "status": "pending"},
  {"content": "step 3: execute_code hop-1, collect intermediate MIDs", "status": "pending"},
  {"content": "step 4: list_predicates hop-2 on intermediate", "status": "pending"},
  {"content": "step 5: build_subgraph hop-2", "status": "pending"},
  {"content": "step 6: execute_code hop-2, emit answer", "status": "pending"}
])

Then immediately call the first KBQA tool.

# Example

Question: `which films acted by Logan Lerman were released after 2004-01-22?`
Topic entities: `Logan Lerman(m.04f1s6)`

```
<think>
Hop 1: actor -> Performance(CVT) -> Film. Hop 2: film -> initial_release_date, filter > 2004-01-22.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: hop-1 predicates on actor", "status": "in_progress"},
  {"content": "step 2: build hop-1 (actor->film)", "status": "pending"},
  {"content": "step 3: collect Film MIDs", "status": "pending"},
  {"content": "step 4: hop-2 predicates on Film", "status": "pending"},
  {"content": "step 5: build hop-2 (film->date)", "status": "pending"},
  {"content": "step 6: filter dates, emit names", "status": "pending"}
])
→ list_predicates_by_entity(entity_mid="m.04f1s6", semantic_filter="movies acted", top_k=20)

Result: `(Person, film.actor.film, Performance) -> 21` — pick it (CVT tail, traverse in code).

**Step 2:**
```
<think>
Todo progress: completed=[1], current=2, skipped=[]
Subtask: step 2 — build hop-1 subgraph (actor -> CVT -> Film).
Reason: film.actor.film + film.performance.film walks Person->CVT->Film.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: hop-1 predicates on actor", "status": "completed"},
  {"content": "step 2: build hop-1 (actor->film)", "status": "in_progress"},
  {"content": "step 3: collect Film MIDs", "status": "pending"},
  {"content": "step 4: hop-2 predicates on Film", "status": "pending"},
  {"content": "step 5: build hop-2 (film->date)", "status": "pending"},
  {"content": "step 6: filter dates, emit names", "status": "pending"}
])
→ build_subgraph_schema(start_mids=["m.04f1s6"], predicates=["film.actor.film","film.performance.film"])

**Step 3:**
```
<think>
Todo progress: completed=[1,2], current=3, skipped=[]
Subtask: step 3 — collect Film MIDs through CVT.
Reason: traverse film_actor_film -> film_performance_film.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: hop-1 predicates on actor", "status": "completed"},
  {"content": "step 2: build hop-1 (actor->film)", "status": "completed"},
  {"content": "step 3: collect Film MIDs", "status": "in_progress"},
  {"content": "step 4: hop-2 predicates on Film", "status": "pending"},
  {"content": "step 5: build hop-2 (film->date)", "status": "pending"},
  {"content": "step 6: filter dates, emit names", "status": "pending"}
])
→ execute_code(schema_file="...subgraph_11111111.json", code_lines=[...])

```python
film_mids = []
for cvt in getattr(entities_by_mid.get('m.04f1s6'), 'film_actor_film', []):
    for f in getattr(cvt, 'film_performance_film', []):
        if f._mid not in film_mids: film_mids.append(f._mid)
result_dict['direct_results'] = film_mids
```

Result: 22 Film MIDs.

**Steps 4-5:** list predicates on a Film MID → `film.film.initial_release_date` (TailType=Datetime) → build hop-2 schema. (Each step calls `write_todos` to update status before the KBQA tool.)

**Step 6:**
```
<think>
Todo progress: completed=[1,2,3,4,5], current=6, skipped=[]
Subtask: step 6 — filter by date > 2004-01-22, emit names.
Reason: ISO-8601 string compare on film_film_initial_release_date.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: hop-1 predicates on actor", "status": "completed"},
  {"content": "step 2: build hop-1 (actor->film)", "status": "completed"},
  {"content": "step 3: collect Film MIDs", "status": "completed"},
  {"content": "step 4: hop-2 predicates on Film", "status": "completed"},
  {"content": "step 5: build hop-2 (film->date)", "status": "completed"},
  {"content": "step 6: filter dates, emit names", "status": "in_progress"}
])
→ execute_code(schema_file="...subgraph_22222222.json", code_lines=[...])

```python
for f in entities:
    if not isinstance(f, Film): continue
    for d in getattr(f, 'film_film_initial_release_date', []):
        if d._value and str(d._value) > '2004-01-22':
            nm = mid_name_map.get(f._mid, get_name(f))
            if nm: result_dict['detailed_results'][f._mid] = {'_name': nm}
            break
```

Final: `\boxed{["The Number 23", "Fury", "Percy Jackson & the Olympians: The Lightning Thief", ...]}`
