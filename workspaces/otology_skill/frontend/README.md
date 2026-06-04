# Excel To Ontology Agent

Project-specific frontend for the `otology_skill` agent. The interface is organized around the workbook-to-ontology workflow: upload Excel cases, inspect prepared Python models, and ask for business ontology code.

```bash
PYTHONPATH=. python3 workspaces/otology_skill/frontend/app.py
```

Open `http://127.0.0.1:8091`.

Set `SILICONFLOW_API_KEY` in your shell before launch for real LLM runs. Use
`FRONTEND_MOCK_AGENT=1` for local UI/API testing without network calls.

Features:

- Project-specific chat interface for ontology modeling workflows.
- Excel case upload panel: upload one or more `.xlsx`/`.xlsm` workbooks, name the case, attach a business question, and prepare first-pass Python models.
- Case selector: choose an uploaded case so the next chat run receives prepared model paths, schema summaries, and output directory context.
- Persistent sessions stored in `outputs/otology_skill/frontend_sessions/`.
- Project metadata exposes both workflow skills and callable tools, keeping the tool/skill boundary visible in the UI.
- Conversation history modal, new conversation flow, and multi-turn thread IDs.
- Floating Case Workspace / Case Management panel customized for ontology modeling, generated artifacts, and validation.
- Frontend-level WebSocket token streaming from LangGraph message chunks without modifying harness code.

Uploaded raw files are stored in `data/otology_skill/cases/`; generated case artifacts are stored in `outputs/otology_skill/cases/<case_id>/`.

Case import smoke test:

```bash
PYTHONPATH=. python3 workspaces/otology_skill/code/case_frontend_smoke.py
```
