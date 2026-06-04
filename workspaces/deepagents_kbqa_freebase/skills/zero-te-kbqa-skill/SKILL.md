---
name: zero-te-kbqa-skill
description: Use when the question has NO concrete topic entity — it describes a value or property and asks which entities match.
---

# Workflow

1. `search_predicates(semantic_filter=<relation>)` — pick the row whose description declares head/tail types matching the asked answer type.
2. `search_entities_by_predicate(predicate=<picked>, ...)`:
    - Value-anchored (question gives literal `L`): pass `value=L`. Supports MIDs (`m.xxx`/`g.xxx`) for entity-valued predicates.
    - Aggregate/no-literal ("smallest/largest/earliest/latest"): pass `semantic_filter=<description>` to enumerate candidates.
3. (If needed) `build_subgraph_schema` + `execute_code` — aggregate/filter/sort and emit answers.

If step-2 returns intermediate entities or CVT tail, insert `list_predicates_by_entity` on a representative MID between steps 2 and 3.

# Skip vs Mandatory for steps 3+4

- **Skip**: value-anchored lookups where step-2 rows are already final answer entities → box names directly.
- **Mandatory**: aggregate questions (need literal values to sort), CVT tail, or extra hop needed.

# Todo Template

Use `write_todos` to plan steps. All steps have no topic MID (0-TE).

```
<think>
Predicate ~ "<keyword>"; filter value=<v>; tail=<type>; CVT=<yes/no>.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: search_predicates for relation", "status": "in_progress"},
  {"content": "step 2: search_entities_by_predicate", "status": "pending"},
  {"content": "step 3: build_subgraph_schema (if needed)", "status": "pending"},
  {"content": "step 4: execute_code (if needed)", "status": "pending"}
])

Then immediately call search_predicates.

# Example — value-anchored

Question: `which buildings have 10 floors?` (no topic entity)

```
<think>
Predicate ~ "floors of a building"; filter value=10; tail=int; CVT=no.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: find predicate for floors", "status": "in_progress"},
  {"content": "step 2: entities with floors=10", "status": "pending"},
  {"content": "step 3: build subgraph + verify", "status": "pending"},
  {"content": "step 4: emit names", "status": "pending"}
])
→ search_predicates(semantic_filter="floors of a building", top_k=10)

Result: `architecture.building.floors`, tail=`type.int`.

```
<think>
Todo progress: completed=[1], current=2, skipped=[]
Subtask: step 2 — fetch entities where floors=10.
Reason: tail is int, value-anchored; rows return mid+name directly.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: find predicate for floors", "status": "completed"},
  {"content": "step 2: entities with floors=10", "status": "in_progress"},
  {"content": "step 3: build subgraph + verify", "status": "pending"},
  {"content": "step 4: emit names", "status": "pending"}
])
→ search_entities_by_predicate(predicate="architecture.building.floors", value=10, top_k=50)

Result: `m.0bn8q1 "Hotel Andaluz"`, `m.064qz5 "Azadi Cinema Complex"`, `m.07hvw_ "Ellicott Square Building"`.

```
<think>
Todo progress: completed=[1,2], current=3, skipped=[]
Subtask: step 3+4 — verify entities are not CVTs before boxing.
Reason: defensive check via schema+code.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: find predicate for floors", "status": "completed"},
  {"content": "step 2: entities with floors=10", "status": "completed"},
  {"content": "step 3: build subgraph + verify", "status": "in_progress"},
  {"content": "step 4: emit names", "status": "in_progress"}
])
→ build_subgraph_schema(start_mids=["m.0bn8q1","m.064qz5","m.07hvw_"], predicates=["architecture.building.floors"])
→ execute_code(schema_file="...subgraph_aaabbccd.json", code_lines=[...])

Final: `\boxed{["Hotel Andaluz", "Azadi Cinema Complex", "Ellicott Square Building"]}`

# Example — aggregate

Question: `what unit has the smallest time in seconds?` (no topic entity)

```
<think>
Predicate ~ "time unit seconds"; filter value=min; tail=float; CVT=no.
</think>
```
→ write_todos(todos=[
  {"content": "step 1: search_predicates for time unit seconds", "status": "in_progress"},
  {"content": "step 2: search_entities_by_predicate for time units", "status": "pending"},
  {"content": "step 3: build_subgraph_schema", "status": "pending"},
  {"content": "step 4: execute_code with min() to find smallest", "status": "pending"}
])
→ search_predicates(semantic_filter="time unit value in seconds")

Result: `measurement_unit.time_unit.time_in_seconds`, tail=`type.float`.

Steps 2-4 (condensed): retrieve unit MIDs → build schema → execute_code with `min()` logic:

```python
best = None; best_mid = None
for e in entities:
    for v in getattr(e, 'measurement_unit_time_unit_time_in_seconds', []):
        try: x = float(v._value)
        except: continue
        if best is None or x < best: best, best_mid = x, e._mid
if best_mid: result_dict['detailed_results'][best_mid] = {'_name': mid_name_map.get(best_mid, '')}
```

Final: `\boxed{["Planck time"]}`
