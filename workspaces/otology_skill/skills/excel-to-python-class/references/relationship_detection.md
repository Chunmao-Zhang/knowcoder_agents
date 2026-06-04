# Relationship Detection Heuristics

## Goal
Infer foreign key and relational dependencies between tables **without explicit FK declarations**.

---

## Heuristic 1: `_id` / `Id` Field Naming Pattern

**Most reliable signal.**

If a field is named `{X}_id` or `{X}Id`, check if table `X` (or its plural/singular variant) exists.

```python
def detect_fk_by_name(field_name, all_table_names):
    """Returns referenced table name or None."""
    candidates = []
    # snake_case: user_id → User
    if field_name.endswith('_id'):
        base = field_name[:-3]  # strip _id
        candidates.append(base)
        candidates.append(base + 's')   # plural
        candidates.append(base[:-1])    # de-plural (items → item)
    # camelCase: userId → User
    if field_name.endswith('Id'):
        base = field_name[:-2]
        candidates.append(base.lower())
    for c in candidates:
        for t in all_table_names:
            if t.lower() == c.lower():
                return t
    return None
```

---

## Heuristic 2: Shared Field Name + Type Across Tables

If two tables share a field with the **same name and compatible type**, they may be joinable.

Rules:
- Both fields must be non-nullable
- At least one should be a primary key candidate
- Flag as a **potential join key** (not necessarily a FK)

Example: `report_date DATE` in both `daily_metrics` and `summary_report` → join on `report_date`.

---

## Heuristic 3: Description / Comment Field Contains Table Name

Scan the description column for mentions of other table names.

```python
import re

def detect_fk_from_description(description, all_table_names):
    if not description:
        return None
    for table in all_table_names:
        pattern = re.compile(rf'\b{re.escape(table)}\b', re.IGNORECASE)
        if pattern.search(description):
            return table
    return None
```

Example description: "关联到用户表的用户ID" → references table `用户` / `user`.

---

## Heuristic 4: Explicit Constraint Column

If the metadata has a `constraint` or `reference` column, parse it:

| Constraint value | Meaning |
|-----------------|---------|
| `FK(user.id)` | Foreign key to user.id |
| `references user(id)` | Foreign key to user.id |
| `外键` | Foreign key (no target specified — use Heuristic 1) |
| `PK` / `PRIMARY KEY` | Primary key |
| `NOT NULL` | Non-nullable |
| `UNIQUE` | Unique constraint |

---

## Heuristic 5: Code/ID Fields with Matching Lookup Tables

Common patterns in Chinese enterprise systems:

| Field pattern | Likely references |
|--------------|------------------|
| `org_code`, `机构代码` | organization / 机构 table |
| `dept_id`, `部门ID` | department / 部门 table |
| `user_id`, `用户ID` | user / 用户 table |
| `indicator_id`, `指标ID` | indicator / 指标 table |
| `region_code`, `地区代码` | region / 地区 table |
| `product_code`, `产品代码` | product / 产品 table |

---

## Building the Relationship Map

After running all heuristics, build a unified map:

```python
relationship_map = {
    "Order": [
        {
            "field": "user_id",
            "references_table": "User",
            "references_field": "id",
            "relationship_type": "many-to-one",   # Order → User
            "back_populates": "orders",
            "confidence": "high",   # from _id pattern
        }
    ],
    "OrderItem": [
        {
            "field": "order_id",
            "references_table": "Order",
            "references_field": "id",
            "relationship_type": "many-to-one",
            "back_populates": "items",
            "confidence": "high",
        },
        {
            "field": "product_id",
            "references_table": "Product",
            "references_field": "id",
            "relationship_type": "many-to-one",
            "back_populates": "order_items",
            "confidence": "high",
        }
    ]
}
```

Relationship types:
- `many-to-one`: child table has FK to parent (most common)
- `one-to-one`: FK + UNIQUE constraint
- `many-to-many`: junction table with two FKs (generate association table)

---

## Circular Reference Handling

If A references B and B references A:
1. Use `lazy='select'` on one side
2. Use `Optional` typing on both sides
3. Add a comment: `# Circular reference — verify schema design`
