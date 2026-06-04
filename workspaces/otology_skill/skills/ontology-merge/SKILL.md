---
name: ontology-merge
description: |
  Merges Python ontology class definitions across multiple directories/files. Use this skill whenever the user wants to:
  - Merge, align, or deduplicate ontology classes from multiple *_ontology.py files
  - Perform semantic alignment of Python class definitions (e.g. "Person" vs "Human", "人" vs "人类")
  - Combine fields from duplicate or semantically equivalent classes, with foreign key annotations
  - Produce a unified merged_ontology.py and/or a Markdown alignment report
  Trigger even when the user says "合并本体", "类对齐", "字段合并", "ontology merge", "semantic alignment of classes", or describes reconciling Python models from multiple sources.
---

# Ontology Merge Skill

将多个已经存在的 Python ontology 文件进行语义对齐、字段整合和统一输出。只要用户要求“统一”“整合”“对齐”“去重”“公共实体”“保留独立”“多个候选 schema”“历史 ontology 合并”，即使没有直接说“merge”，也应优先使用本 skill。

## Key Features

1. **Exact name matches** → automatic merge with field consolidation
2. **Semantic alignment** → AI-assisted with user confirmation for each suggestion
3. **Field conflict resolution** → user decides on type conflicts
4. **FK detection** → identifies foreign keys from comments and naming patterns
5. **Business context awareness** → reads .md files in directories for domain understanding
6. **Preserves original style** → maintains dataclass/Pydantic/plain class format

## Tool Boundary

本 skill 负责语义判断、合并候选解释和用户确认；确定性的解析、合并、渲染、验证必须交给工具完成：

- `parse_ontology_files` 解析 `*_ontology.py` 文件中的 class metadata。
- `merge_ontology_classes` 合并同名或已确认的语义等价类，并报告字段冲突。
- `render_merged_ontology` 写出 `merged_ontology.py` 和 `alignment_report.md`。
- `validate_python_artifacts` 验证生成的 Python artifact。

不要用手写 Python 文件替代 `merge_ontology_classes` / `render_merged_ontology`。如果任务属于 merge 场景，最终 trace 中必须能看到 merge 工具链被使用；如果因需要用户确认、工具失败或输入不足而不能继续，明确输出待确认的 merge groups 或未完成步骤，不要伪造合并结果，也不要把手写文件称为已完成 merge 产物。

Do not put user-confirmation logic inside tools. Propose semantic merge groups
in the skill response, wait for user approval, then pass approved groups to
`merge_ontology_classes`.

---

## Complete Workflow

### Step 1: Discover Files

Recursively find all `*_ontology.py` files in specified directories:

```bash
find <dir1> [<dir2> ...] -type f -name "*_ontology.py" | sort
```

**Error handling**: If any directory doesn't exist, stop and report error.

For frontend Excel cases, the usual source directory is:

```text
outputs/otology_skill/cases/<case_id>/business_ontology/
```

Use repo-relative paths in shell commands and final answers.

### Step 2: Read Business Context

Before parsing, scan for `.md` files in the same directories to understand business relationships:

```bash
find <dir1> [<dir2> ...] -type f -name "*.md" | head -20
```

Read these files to understand:
- Business entities and their relationships
- Domain-specific terminology (e.g., 订户/用户/客户 distinctions)
- Known foreign key relationships

Store this context for semantic alignment and FK detection.

### Step 3: Parse Ontology Files

Parse each file using `parse_ontology_files(file_paths=[...])`.
For large uploaded cases, keep the default summarized output; only set `include_source=true` for a small number of files when full source is truly needed.

**Output format**:
```json
[
  {
    "source_file": "path/to/file.py",
    "class_name": "Person",
    "docstring": "Represents a human individual",
    "bases": ["BaseEntity"],
    "decorators": ["dataclass"],
    "fields": [
      {"name": "name", "type": "str", "default": null, "comment": "Full name"},
      {"name": "user_id", "type": "int", "default": null, "comment": "FK to User"}
    ],
    "field_count": 2,
    "truncated_field_count": 0
  }
]
```

**Error handling**: If parsing fails (syntax error, encoding issue), stop immediately and report the problematic file.

See `references/parsing_notes.md` for supported class styles.

### Step 4: Exact Name Grouping

Group classes by exact name match (case-sensitive, since Python is case-sensitive):

```python
{
  "Person": [class1, class2],
  "User": [class3],
  "用户": [class4, class5]
}
```

Classes with identical names are **automatic merge candidates**.

### Step 5: Semantic Alignment (User-Confirmed)

For classes without exact name matches, perform AI-assisted semantic alignment:

1. **Prepare alignment input**: Format remaining classes with their metadata
2. **Call semantic alignment**: Use the prompt from `references/semantic_align_prompt.md`
3. **Present suggestions to user**: For each suggested merge group, show:
   - Class names being merged
   - Their docstrings
   - Field comparison (side-by-side)
   - Rationale for why they might be the same
4. **Get user confirmation**: Ask user to approve/reject each suggestion
5. **Apply approved merges**: Only merge groups that user confirms

**Example user interaction**:
```
I found these classes that might be semantically equivalent:

Group 1: Person, Human, 人
- Person (from domain_ontology.py): "Represents a human individual"
  Fields: name (str), age (int), email (str)
  
- Human (from user_ontology.py): "A human being in the system"
  Fields: full_name (str), birth_year (int), contact_email (str)
  
- 人 (from chinese_ontology.py): "人类个体"
  Fields: 姓名 (str), 年龄 (int)

Rationale: All three represent human individuals with similar demographic fields.

Should I merge these? (yes/no/skip)
```

### Step 6: Merge Class Groups

For each approved merge group, call `merge_ontology_classes(classes_json=<parse output>, merge_groups=<approved groups>)`.

**Merge rules**:

1. **Class name**: Choose longest/most descriptive, or one with best docstring
2. **Docstring**: Concatenate unique descriptions with source attribution
3. **Decorators**: Union of all decorators (e.g., if any has @dataclass, keep it)
4. **Base classes**: Union of all bases; if conflicts, add comment
5. **Fields**:
   - Same name + same type → merge, combine comments
   - Same name + different type → **CONFLICT - ask user to choose**
   - Unique fields → include with source annotation

**Field conflict resolution**:
```
Field conflict detected: 'age'

Variant 1 (from domain_ontology.py):
  age: int = 0  # Age in years

Variant 2 (from user_ontology.py):
  age: str  # Age as string for flexibility

Which version should I keep? (1/2/both)
```

**FK annotation**:
- Check field comments for FK indicators (FK, 外键, foreign key)
- Check naming patterns: `_id`, `_rid`, `_ref`, `_fk`, `_key`
- Cross-reference with business context from .md files
- Annotate detected FKs: `user_id: int  # FK -> User (from: domain_ontology.py)`

**Output**:
```json
{
  "merged_classes": [...],
  "conflicts": [
    {
      "field_name": "age",
      "variants": [...]
    }
  ]
}
```

### Step 7: Generate Outputs

#### A) Create output directory

```bash
mkdir -p merged_ontology
```

For frontend Excel cases, do not create a standalone `merged_ontology/` outside the case. Use the case output directory instead:

```text
outputs/otology_skill/cases/<case_id>/business_ontology/
```

#### B) Render merged classes to Python

Call `render_merged_ontology(merged_classes_json=<merge output>, output_dir=<output dir>)`. For frontend cases, `<output dir>` is `outputs/otology_skill/cases/<case_id>/business_ontology/`.

**Rendering preserves**:
- Original class style (dataclass/Pydantic/plain)
- All comments and annotations
- Source file attribution
- FK annotations

#### C) Generate Markdown alignment report

Create `merged_ontology/alignment_report.md` with:

1. **Summary Statistics**
   - Total files scanned
   - Total classes found
   - Classes merged (exact + semantic)
   - Classes passed through unchanged
   - Field conflicts resolved

2. **Exact Merges Table**
   | Original Names | Source Files | Merged Name |
   |----------------|--------------|-------------|
   | Person, Person | file1.py, file2.py | Person |

3. **Semantic Merges Table**
   | Original Names | Source Files | Merged Name | Rationale |
   |----------------|--------------|-------------|-----------|
   | Person, Human, 人 | file1.py, file2.py, file3.py | Person | All represent human individuals |

4. **Field Conflicts Resolved**
   - List each conflict and user's resolution

5. **Foreign Key Relationships Detected**
   - Table of FK fields and their target classes

6. **Unchanged Classes**
   - List of classes with no duplicates

7. **Field Source Tracking**
   - For each merged class, show which fields came from which source

### Step 8: Present to User

1. Display summary statistics
2. Show alignment report (key sections)
3. Confirm the actual output location. For frontend cases, this must be `outputs/otology_skill/cases/<case_id>/business_ontology/merged_ontology.py`
4. Ask if user wants to review any specific merges

For this workspace, write merged case outputs under:

```text
outputs/otology_skill/cases/<case_id>/business_ontology/merged_ontology.py
outputs/otology_skill/cases/<case_id>/business_ontology/alignment_report.md
```

Final answers must use the project section titles `## 产出总结`, `## 业务本体设计`, `## 输出文件`, `## 核心关系`, `## 验证结果与假设`, followed by a compact `PROCESS_TRACE_JSON` fenced JSON block. This block is machine-readable data for the frontend process graph; keep the user-facing sections natural and do not explain the JSON itself. The trace must include `workflow_steps`, `source_to_target`, `artifact_paths`, and `validation`. `workflow_steps` must show `parse_ontology_files`, `merge_ontology_classes`, `render_merged_ontology`, and `validate_python_artifacts` with status and evidence paths.

---

## Supported Class Styles

```python
# 1. dataclass
@dataclass
class Person:
    name: str
    age: int = 0

# 2. Pydantic BaseModel
class Person(BaseModel):
    name: str
    age: int = Field(default=0, description="Age in years")

# 3. Plain class with annotations
class Person:
    """A human being."""
    name: str
    age: int
    
# 4. Class with __init__
class Person:
    def __init__(self, name: str, age: int):
        self.name = name
        self.age = age

# 5. Mixed Chinese/English
class 用户:
    """业务用户"""
    用户ID: str  # User ID
    姓名: str  # Name
    phone_number: str  # 电话号码
```

---

## Edge Cases & Error Handling

1. **Parsing failures**: Stop immediately, report file and error
2. **Circular FK**: Annotate both directions, don't try to resolve
3. **Import-only classes**: Pass through, note in report
4. **Conflicting bases**: List all, add comment, let user decide
5. **Duplicate files**: Warn user, process only first occurrence
6. **Empty classes**: Pass through with warning
7. **Very large files** (>10K lines): Warn about performance

---

## Domain Adaptation Notes

When processing uploaded business ontologies, infer terminology from the case
manifest, workbook headers, prepared class comments, and the user's question
rather than assuming a fixed industry:

1. **Common entity synonyms**:
   - Compare local labels such as 用户 / 客户 / 会员 or order/customer/product variants.
   - Treat domain-specific aliases as hypotheses until supported by fields or context.

2. **Typical relationships**:
   - Infer entity links from FK-style fields, source comments, and nearby workbook tables.
   - Keep subtype, lifecycle-state, and transaction relationships separate unless the case context says otherwise.

3. **FK patterns**:
   - Check generic suffixes such as `_id`, `_rid`, `_ref`, `_fk`, and `_key`.
   - Use uploaded schema context to choose the target class; do not hardcode a target domain.

---

## Reference Files

- `references/parsing_notes.md` — AST parsing details and edge cases
- `references/semantic_align_prompt.md` — Prompt template for semantic alignment
- Workspace tools `parse_ontology_files`, `merge_ontology_classes`, `render_merged_ontology`, and `validate_python_artifacts` are the active execution path.