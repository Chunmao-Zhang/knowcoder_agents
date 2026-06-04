import json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
with open(ROOT / "outputs/otology_skill/cases/revenue_anomaly_explanation/business_ontology/revenue_anomaly_ontology.py") as f:
    text = f.read()
# Extract JSON from PROCESS_TRACE_JSON block
pattern = r'PROCESS_TRACE_JSON\s*```json\s*(.*?)\s*```'
match = re.search(pattern, text, re.DOTALL)
if match:
    data = json.loads(match.group(1))
    print('JSON valid')
    print(f'workflow_steps: {len(data["workflow_steps"])}')
    print(f'source_to_target: {len(data["source_to_target"])}')
    print(f'artifact_paths: {len(data["artifact_paths"])}')
    for k, v in data.get('validation', {}).items():
        print(f'  validation.{k}: {v}')
else:
    # Try to find the exact text
    if 'PROCESS_TRACE_JSON' in text:
        print('Found PROCESS_TRACE_JSON but pattern mismatch')
    else:
        print('PROCESS_TRACE_JSON not found')
