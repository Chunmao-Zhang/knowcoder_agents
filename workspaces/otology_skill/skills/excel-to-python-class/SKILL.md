---
name: excel-to-python-class
description: >
  把 Excel 表结构、字段清单或元数据表转换为 Python class 定义。当用户要求“Excel 转 class”、
  “根据表结构生成 Python 模型”、“字段表生成 schema”、“准备 prepared models”时使用本 skill。
  如果前端上传 case 已经完成 prepared class 生成，除非用户明确要求重新准备，否则不要再次使用本 skill。
---

# Excel → Python Class Converter

本 skill 只负责从 Excel 结构生成第一版稳定的 Python 字段模型；如果用户已经在问业务实体、指标口径、业务本体、合并对齐，请切换到 `business-ontology-refactor` 或 `ontology-merge`。

## 适用边界

使用本 skill 的场景：

- 用户上传或指定 Excel，希望把每个 sheet / metadata table 变成 Python class。
- 当前 case 还没有 `prepared_models`，需要先生成基础字段模型。
- 用户明确要求重新检查 Excel、重新生成 prepared class 或修正基础字段命名。

不要使用本 skill 的场景：

- case manifest 已经给出 `prepared_models` / `generated_files`，用户只是问业务本体、指标口径、实体关系或操作方法。
- 用户要求统一、合并、去重多个已有 ontology 文件。
- 只需要读取少量字段解释；这时应由后续 skill 通过 `parse_ontology_files` 或必要时 `inspect_excel_schema` 补充判断。

## Tool Boundary

本 skill 负责判断 Excel 生成范围、关系识别和最终说明；工具负责可重复的检查、生成和验证。不要用手写脚本替代已有工具。

- Use `inspect_excel_schema` first to inspect sheets, header rows, table-name candidates, fields, inferred types, and sample values.
- Use `generate_python_models_from_excel` to write Python class files into `outputs/otology_skill/...`.
- Use `validate_python_artifacts` after generation to verify `py_compile`, identifiers, and sensitive-term checks.
- These three tools are mandatory and ordered for Excel preparation: `inspect_excel_schema` → `generate_python_models_from_excel` → `validate_python_artifacts`. If any step fails, report the workflow as incomplete instead of hand-writing replacement files.
- Keep business assumptions, relationship caveats, and output explanation in the skill response.
- For unfamiliar business domains, preserve uploaded field names by default and only sanitize them into valid Python identifiers. If the user explicitly wants stable English names, pass them through `generate_python_models_from_excel(field_name_overrides={...})`.
- Custom reusable Chinese/domain term mappings can still be added in `data/otology_skill/config/term_map.json`, but do not create them unless the user asks for translation.
- If business-aware LLM comments are needed, use `references/comment_generation_prompt.md` in the skill, then pass the final comments to `generate_python_models_from_excel(field_comment_overrides={...})`. The tool must not call an LLM by itself.
- 前端 case 的 prepared models 应写入 `outputs/otology_skill/cases/<case_id>/prepared_models/`；不要写入 `workspaces/otology_skill/outputs/...`。
- 工具参数和最终链接使用仓库相对路径，例如 `data/otology_skill/...`、`outputs/otology_skill/...`，不要在最终回答中暴露 `/Users/...` 绝对路径。

## Core Challenge: Relationship Detection

The hardest part of this task is **inferring foreign keys and relationships** across tables when they are not explicitly declared. Use the strategies in `references/relationship_detection.md` to identify them before generating code.

## 工作流

### Step 1：检查 Excel 结构

Call `inspect_excel_schema(excel_path=<path>, max_rows=30)` and review the returned sheet/table/column metadata.

Identify for each sheet/table:
- **Table name** (from sheet name or a dedicated column)
- **Field name column** (e.g., `field_name`, `column_name`, `字段名`)
- **Data type column** (e.g., `type`, `data_type`, `数据类型`)
- **Constraint column** (e.g., `constraint`, `primary_key`, `nullable`, `约束`)
- **Description column** (e.g., `description`, `comment`, `备注`)

If metadata role headers are in Chinese, normalize only those role labels (for example `字段名` → `field_name`) — see `references/chinese_column_map.md`. Do not translate business field names by default.

### Step 2：识别表间关系

Read `references/relationship_detection.md` **before** generating any code.

Key signals to look for:
1. Fields ending in `_id` or `Id` that match another table's primary key
2. Fields named exactly as another table name (singular or plural)
3. Fields with descriptions mentioning another table name
4. Shared field names with identical types across tables (potential join keys)

Build a relationship map:
```python
relationships = {
    "TableA": [
        {"field": "user_id", "references": "User", "ref_field": "id", "type": "many-to-one"}
    ]
}
```

### Step 3：准备注释

Before writing any class, prepare two layers of comments from the Excel metadata:

#### 3a. Class-level docstring
- Source: the table's own description/comment column (e.g., `表注释`, `table_comment`, `description`), or the sheet name.
- Format: a concise one-line description of what the table represents.
- If no description exists, infer from the table name itself (e.g., `order_item` → "Records each line-item belonging to an order").
- **Must not simply repeat the class name** (e.g., do not write `"""User"""` for class `User`).

#### 3b. Field-level inline comments
For every field/column:
1. First look for the field's description in the metadata (description / comment / 备注 column).
2. If found, use that text (translated to English if in Chinese, or kept bilingual).
3. If not found, write a brief semantic comment based on domain knowledge of the field name.
4. **The comment must add meaning beyond the variable name itself** — never write `# user_id` as the comment for `user_id`.
5. For FK fields, always append ` — FK → ParentTable.pk` to make the relationship explicit.
6. Use an inline `# ...` comment on the same field line.

#### Comment Quality Rules

**Core principle: a comment that copies the variable name is worse than no comment — it creates noise with no signal.**

Before writing any comment, ask: *"Does this tell the reader something they couldn't already infer from the name alone?"* If the answer is no, rewrite it.

**Filtering trivial descriptions from metadata**

Descriptions from the Excel metadata must be discarded (and replaced with domain-knowledge inference) if they:
- Are identical to the field name after stripping case/underscores/spaces (e.g. `user_id` → desc `"userId"` → discard)
- Are a Chinese transliteration that adds no new information (e.g. field `status`, desc `"状态"` → discard; field `price`, desc `"价格"` → discard)
- Are shorter than 4 characters and subsumed by the field name

**Domain-knowledge inference rules by pattern**

When the metadata description is absent or trivial, use these rules in priority order:

| Field pattern | Inferred comment |
|---|---|
| `id` (exact) | `Auto-incremented surrogate primary key; never exposed in business logic` |
| `*_id` | `Foreign reference to the primary key of the '{entity}' entity` |
| `created_at` / `create_time` / `gmt_create` | `UTC timestamp recorded automatically when the row is first inserted` |
| `updated_at` / `update_time` / `gmt_modified` | `UTC timestamp refreshed on every UPDATE; used for optimistic locking` |
| `is_deleted` / `del_flag` | `Soft-delete marker: 1 = logically removed; physical rows are retained for audit` |
| `is_*` | `Boolean indicator: true when the {attr} condition holds for this record` |
| `status` (exact) | `Lifecycle state (e.g. draft/active/closed); see enum docs for valid values` |
| `*_status` | `Current processing state of the {entity}; see enum docs` |
| `*_name` | `Human-readable display name for the {entity}` |
| `*_code` | `Unique alphanumeric code assigned to identify the {entity}` |
| `*_type` | `Classification type for the {entity}; drives conditional business rules` |
| `*_date` | `Calendar date on which the {entity} event occurs or is scheduled` |
| `password` / `pwd` | `Hashed password (bcrypt/argon2); NEVER store or log in plain text` |
| `email` | `Email address used for login, notifications, and correspondence` |
| `phone` / `mobile` | `Contact phone number; stored without formatting (digits only)` |
| `*_url` / `*_link` | `Fully-qualified URL pointing to the {entity} resource` |
| `remark` / `note` / `memo` | `Free-text field for operational notes or remarks added by staff` |
| `sort` / `seq` / `priority` | `Explicit sort weight; lower value means higher position in listings` |
| `version` / `ver` | `Optimistic-lock version counter; incremented on each UPDATE` |

For fields not matching any pattern above, use: `Stores the {readable field name} associated with this record` — which at minimum is grammatically distinct from the bare variable name.

| ❌ Bad | ✅ Good |
|--------|---------|
| `comment="user_id"` | `comment="Foreign reference to the primary key of the 'user' entity"` |
| `comment="状态"` (when field is `status`) | `comment="Lifecycle state (e.g. draft/active/closed); see enum docs"` |
| `comment="价格"` (when field is `price`) | `comment="Per-unit monetary amount in the system's base currency"` |
| `comment="name"` | `comment="Primary human-readable display name of this entity"` |
| `# created_at` | `# UTC timestamp recorded automatically when the row is first inserted` |

### Step 4：生成 Python class

Use `generate_python_models_from_excel(excel_path=<path>, output_dir=<outputs/otology_skill/...>)` for the actual file generation. If the frontend has already uploaded a case, use the prepared model paths from that case manifest instead of asking the user to repeat file paths.
See `references/dataclass_template.md` for full template — every class includes a docstring and every field carries an inline `# comment`.

Key rules:
- Use `Optional[RelatedClass]` for FK references
- Add `related_id: int` field alongside `related: Optional[RelatedClass] = None`
- Add comments indicating FK relationship

### Step 5：类型映射

Map source types to Python types:

| Source Type | Python Type |
|-------------|-------------|
| int / integer / INT / 整数 | `int` |
| varchar / string / str / 字符串 | `str` |
| text / TEXT / 文本 | `str` |
| float / double / decimal / 浮点 | `float` |
| bool / boolean / 布尔 | `bool` |
| date / DATE / 日期 | `datetime.date` |
| datetime / timestamp / 时间戳 | `datetime.datetime` |
| json / JSON / JSONB | `dict` |

### Step 6：输出和验证

- Write one `.py` file per table, named `{table_name_snake_case}.py`
- Write a `models/__init__.py` that imports all classes
- Optionally write a `models/relationships_summary.md` documenting detected relationships
- 调用 `validate_python_artifacts` 验证生成目录；验证失败时先修正，再回复用户。
- 最终回答说明 Excel 来源、生成文件、关系识别结果和验证状态；如果只是 prepared class 生成，不需要输出业务本体用的 `PROCESS_TRACE_JSON`。

## Output File Structure

```
models/
├── __init__.py          # imports all models
├── user.py              # class User
├── order.py             # class Order — FK fields documented inline
├── product.py           # class Product
└── relationships_summary.md
```

## Quality Checklist

- [ ] Every table has a primary key field
- [ ] All FK fields are documented in inline comments
- [ ] Type mapping covers all source types (unknown types → `str` with a comment)
- [ ] Snake_case used for all Python identifiers
- [ ] `models/__init__.py` imports all generated classes
- [ ] **Every class has a docstring** describing what the table represents (not just the class name)
- [ ] **Every field has a `# ...` comment** that adds semantic meaning beyond the variable name
- [ ] FK field comments explicitly state the referenced table and column (e.g., `— FK → User.id`)
- [ ] No comment is a verbatim repeat of the variable name

## Reference Files

- `references/relationship_detection.md` — Detailed heuristics for finding FK relationships
- `references/dataclass_template.md` — Dataclass code template
- `references/chinese_column_map.md` — Chinese metadata column name mappings
