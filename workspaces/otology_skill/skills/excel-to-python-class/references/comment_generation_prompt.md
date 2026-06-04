# Field Comment Generation Prompt

Use this reference when metadata descriptions are missing, trivial, or too terse
and the user wants business-aware comments.

The LLM decision stays in the `excel-to-python-class` skill. The
`generate_python_models_from_excel` tool does not call an LLM; pass final
comments through `field_comment_overrides`.

## Prompt Template

You are generating concise, production-grade comments for Python data model
fields.

Context:

- Industry/domain: `{industry_context}`
- Table name: `{table_name}`
- Sheet name: `{sheet_name}`
- Field name: `{field_name}`
- Original column/metric name: `{original_name}`
- Unit: `{unit}`
- Existing description: `{description}`
- Sample values: `{sample_values}`

Requirements:

1. Explain the field's business meaning, not just its name.
2. Keep the comment one sentence unless the field is a complex metric.
3. If it is a ratio, rate, amount, count, or progress metric, describe what it measures.
4. If it is an identifier or relationship field, mention the referenced business entity if known.
5. Avoid vendor-specific product names and confidential platform terms.
6. Return only the final comment text.

After generating comments, call:

```text
generate_python_models_from_excel(
  excel_path=<path>,
  output_dir=<outputs/otology_skill/...>,
  field_comment_overrides={
    "<table_name>.<field_name>": "<final comment>"
  }
)
```
