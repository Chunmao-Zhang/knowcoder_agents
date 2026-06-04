# Tool / Skill Boundary

This workspace separates executable capabilities from reasoning workflows.

## Tools

Tools are parameterized, repeatable actions with structured inputs and outputs.
They handle file I/O, parsing, generation, merging, rendering, and validation.

Active workspace-local tools:

- `inspect_excel_schema` — inspect `.xlsx` workbooks and infer sheet/table/column metadata.
- `generate_python_models_from_excel` — generate Python class files from Excel table metadata.
- `parse_ontology_files` — parse Python ontology classes into structured JSON metadata.
- `merge_ontology_classes` — merge parsed class metadata after alignment groups have been approved.
- `render_merged_ontology` — write `merged_ontology.py` and `alignment_report.md`.
- `validate_python_artifacts` — run `py_compile`, identifier checks, and sensitive-term checks.

## Skills

Skills are LLM workflows. They decide when and how to use tools, apply modeling
principles, request user confirmation where needed, and explain assumptions.

- `excel-to-python-class` chooses Excel parsing/generation options and explains field assumptions.
- `business-ontology-refactor` performs business-question clarification and ontology design.
- `ontology-merge` proposes semantic alignments, gets confirmation, then calls merge/render tools.

## References

Reference files are modeling knowledge, templates, examples, and prompts. They
are not execution entry points.

## Tests

Smoke tests under `code/` validate workflows and generated artifacts; they are
not exposed as tools.
