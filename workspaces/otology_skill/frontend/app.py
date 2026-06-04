#!/usr/bin/env python3
"""Excel To Ontology Agent frontend.

Run from the repository root:
    PYTHONPATH=. python3 workspaces/otology_skill/frontend/app.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from harness.agents.agent_loop import _load_prompt, _resolve_path, build_agent
from harness.agents.registry import AgentRegistry
from harness.config import load_config
from harness.export.sft_recorder import record_run
from harness.runtime import RunLifecycle, RuntimeContext
from workspaces.otology_skill.code.case_runtime import (
    add_case_input,
    build_case_prompt,
    delete_case,
    delete_case_input,
    get_case,
    import_excel_case,
    list_cases,
    record_case_process_event,
    update_case_input,
)


AGENT_ID = "otology_skill"
UI_BRAND = "Excel To Ontology Agent"
THREAD_PREFIX = "otology-ui"
STATIC_DIR = Path(__file__).resolve().parent / "static"
SESSION_DIR = ROOT / "outputs" / "otology_skill" / "frontend_sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_ROOT = (ROOT / "outputs" / "otology_skill").resolve()
WORKSPACE_DOWNLOAD_ROOT = (ROOT / "workspaces" / "otology_skill" / "outputs" / "otology_skill").resolve()
DOWNLOAD_ROOTS = [
    DOWNLOAD_ROOT,
]
ARTIFACT_EXTENSIONS = r"(?:py|md|json|txt|csv|xlsx|xlsm|log)"
ARTIFACT_PATH_PATTERN = re.compile(
    rf"(?:"
    rf"(?:[A-Za-z]:)?/[^\s<>\"'`)\\\]]*?/(?:workspaces/otology_skill/)?outputs/otology_skill"
    rf"|/?(?:workspaces/otology_skill/)?outputs/otology_skill"
    rf")/[^\s<>\"'`)\\\]]+\.{ARTIFACT_EXTENSIONS}"
)

CONFIG_PATH = Path(os.environ.get("HARNESS_CONFIG", ROOT / "harness.json")).expanduser()
CONFIG = load_config(CONFIG_PATH)
REGISTRY = AgentRegistry(CONFIG)
AGENT_CFG = REGISTRY.get(AGENT_ID)
EXECUTOR = ThreadPoolExecutor(max_workers=3)
RUN_IDLE_TIMEOUT_SECONDS = int(os.environ.get("OTOLOGY_AGENT_IDLE_TIMEOUT_SECONDS", "180"))
RUN_HARD_TIMEOUT_SECONDS = int(os.environ.get("OTOLOGY_AGENT_HARD_TIMEOUT_SECONDS", "900"))
SESSION_EVENT_LIMIT = int(os.environ.get("OTOLOGY_SESSION_EVENT_LIMIT", "90"))


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def session_path(session_id: str) -> Path:
    safe = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid session id")
    return SESSION_DIR / f"{safe}.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def prune_session_events(session: dict[str, Any], limit: int = SESSION_EVENT_LIMIT) -> None:
    """Keep chat history readable by trimming older tool-event noise."""

    if limit <= 0:
        return
    messages = list(session.get("messages", []) or [])
    event_indexes = [
        index
        for index, message in enumerate(messages)
        if isinstance(message, dict) and message.get("role") == "event"
    ]
    if len(event_indexes) <= limit:
        return
    keep = set(event_indexes[-limit:])
    session["messages"] = [
        message
        for index, message in enumerate(messages)
        if not (isinstance(message, dict) and message.get("role") == "event") or index in keep
    ]



def project_metadata() -> dict[str, Any]:
    skills_dir = ROOT / "workspaces" / "otology_skill" / "skills"
    tools_dir = ROOT / "workspaces" / "otology_skill" / "tools"
    skills = sorted(path.name for path in skills_dir.iterdir() if path.is_dir()) if skills_dir.exists() else []
    tools = sorted(path.stem for path in tools_dir.glob("*.py") if not path.name.startswith("_")) if tools_dir.exists() else []
    return {
        "workspace": str(ROOT / "workspaces" / "otology_skill"),
        "skills": skills,
        "tools": tools,
        "tool_skill_boundary": "Skills own workflow/decisions; tools own parameterized parsing, generation, merging, rendering, and validation.",
        "ontology_schema": {
            "title": "Excel To Ontology Workflow",
            "subtitle": "A workbook-first pipeline for turning raw tables into validated business ontology code.",
            "nodes": [
                {"id": "tables", "label": "Raw Tables", "description": "Excel sheets and original business columns."},
                {"id": "field_models", "label": "Field Models", "description": "Stable Python fields with source-column comments."},
                {"id": "entities", "label": "Business Entities", "description": "Domain concepts, interfaces, relations, and operations."},
                {"id": "merged", "label": "Merged Ontology", "description": "Unified classes with alignment decisions and reports."},
                {"id": "validation", "label": "Validation", "description": "py_compile, naming checks, and generated artifact review."},
            ],
            "relations": [
                {"source": "Raw Tables", "predicate": "inspect_and_generate", "target": "Field Models", "skill": "excel-to-python-class", "tools": ["inspect_excel_schema", "generate_python_models_from_excel"]},
                {"source": "Field Models", "predicate": "semantic_refactor", "target": "Business Entities", "skill": "business-ontology-refactor", "tools": ["parse_ontology_files", "validate_python_artifacts"]},
                {"source": "Business Entities", "predicate": "align_and_merge", "target": "Merged Ontology", "skill": "ontology-merge", "tools": ["parse_ontology_files", "merge_ontology_classes", "render_merged_ontology"]},
                {"source": "Merged Ontology", "predicate": "compile_and_report", "target": "Validation", "skill": "ontology-merge", "tools": ["validate_python_artifacts"]},
            ],
            "artifacts": [
                {"name": "generated_models.py", "description": "Python classes created from tables."},
                {"name": "business_ontology/*.py", "description": "Question-specific entity, interface, relationship, and operation code."},
                {"name": "business_ontology/DESIGN.md", "description": "Business ontology design summary, assumptions, and core relationships."},
                {"name": "merged_ontology.py", "description": "Final unified ontology module for multi-domain merges."},
                {"name": "alignment_report.md", "description": "Entity, field, relation, and semantic alignment report."},
                {"name": "validation.log", "description": "py_compile and naming-rule evidence."},
            ],
        },
        "data_dirs": [
            "data/otology_skill/raw/tables",
            "data/otology_skill/cases",
        ],
        "output_dir": "outputs/otology_skill",
        "case_catalog": list_cases(limit=50),
        "smoke_tests": [
            "workspaces/otology_skill/code/e2e_smoke.py",
            "workspaces/otology_skill/code/case_frontend_smoke.py",
        ],
    }


class SessionStore:
    def create(self) -> dict[str, Any]:
        session_id = uuid4().hex[:12]
        session = {
            "id": session_id,
            "title": "New conversation",
            "agent_id": AGENT_ID,
            "agent_name": UI_BRAND,
            "thread_id": f"{THREAD_PREFIX}-{session_id}",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "messages": [],
        }
        self.save(session)
        return session

    def list(self) -> list[dict[str, Any]]:
        sessions = []
        for path in SESSION_DIR.glob("*.json"):
            try:
                item = read_json(path)
            except Exception:
                continue
            sessions.append(
                {
                    "id": item["id"],
                    "title": item.get("title") or "New conversation",
                    "agent_id": item.get("agent_id", AGENT_ID),
                    "agent_name": item.get("agent_name", UI_BRAND),
                    "created_at": item.get("created_at", ""),
                    "updated_at": item.get("updated_at", ""),
                    "message_count": len(item.get("messages", [])),
                }
            )
        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)

    def get(self, session_id: str) -> dict[str, Any]:
        path = session_path(session_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Session not found")
        return read_json(path)

    def save(self, session: dict[str, Any]) -> None:
        prune_session_events(session)
        session["updated_at"] = now_iso()
        write_json(session_path(session["id"]), session)

    def delete(self, session_id: str) -> None:
        path = session_path(session_id)
        if path.exists():
            path.unlink()


STORE = SessionStore()
app = FastAPI(title=UI_BRAND, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def no_cache_frontend_assets(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/")
async def index():
    return FileResponse(
        STATIC_DIR / "index.html",
        media_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/api/health")
async def health():
    data = {
        "ok": True,
        "agent_id": AGENT_ID,
        "agent_name": UI_BRAND,
        "model": AGENT_CFG.model.model_id,
        "max_steps": AGENT_CFG.max_steps,
        "api_key_present": bool((AGENT_CFG.model and AGENT_CFG.model.api_key) or os.environ.get("SILICONFLOW_API_KEY")),
        "sessions_dir": str(SESSION_DIR),
        "project": project_metadata(),
        "streaming": {
            "mode": "frontend-token-stream",
            "harness_modified": False,
            "description": "The frontend app streams LangGraph message chunks over WebSocket without changing harness code.",
        },
    }
    data["case_catalog"] = list_cases(limit=50)
    return data


@app.get("/api/cases/imports")
async def list_case_imports():
    return {"imports": list_cases(limit=100)}


def parse_questions_json(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="questions_json must be a JSON array of strings.") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="questions_json must be a JSON array of strings.")
    return [str(item).strip() for item in parsed if str(item).strip()]


@app.post("/api/cases/imports")
async def import_case(
    files: list[UploadFile] = File(...),
    case_name: str = Form(default=""),
    question: str = Form(default=""),
    questions_json: str = Form(default=""),
):
    uploads: list[tuple[str, bytes]] = []
    for file in files:
        uploads.append((file.filename or "uploaded.xlsx", await file.read()))
    try:
        questions = parse_questions_json(questions_json)
        report = await asyncio.to_thread(import_excel_case, uploads, case_name, question, questions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "import": report}


@app.delete("/api/cases/imports/{case_id}")
async def delete_case_import(case_id: str):
    try:
        report = await asyncio.to_thread(delete_case, case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, **report}


@app.get("/api/cases/{case_id}")
async def get_case_detail(case_id: str):
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")
    return {"case": case}


@app.post("/api/cases/{case_id}/inputs")
async def create_case_input(case_id: str, payload: dict[str, Any]):
    try:
        entry, case = add_case_input(
            case_id,
            str(payload.get("input_type") or "note"),
            str(payload.get("label") or ""),
            str(payload.get("content") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "input": entry, "case": case}


@app.patch("/api/cases/{case_id}/inputs/{input_id}")
async def patch_case_input(case_id: str, input_id: str, payload: dict[str, Any]):
    try:
        entry, case = update_case_input(
            case_id,
            input_id,
            str(payload.get("input_type")) if "input_type" in payload else None,
            str(payload.get("label")) if "label" in payload else None,
            str(payload.get("content")) if "content" in payload else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "input": entry, "case": case}


@app.delete("/api/cases/{case_id}/inputs/{input_id}")
async def remove_case_input(case_id: str, input_id: str):
    try:
        case = delete_case_input(case_id, input_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "case": case}


def normalize_download_path_text(path: str) -> str:
    raw = unquote(str(path or "")).strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Missing file path.")
    if raw.startswith("file://"):
        raw = raw[7:]
    return raw.strip(" \t\r\n`\"'<>").rstrip(".,;:)]}`\"'>").replace("\\", "/")


def download_candidate_from_text(path: str) -> Path:
    raw = normalize_download_path_text(path)
    output_prefix = "outputs/otology_skill/"
    workspace_prefix = "workspaces/otology_skill/outputs/otology_skill/"
    if raw.startswith("/" + output_prefix):
        return DOWNLOAD_ROOT / raw[len("/" + output_prefix):]
    if raw.startswith(output_prefix):
        return DOWNLOAD_ROOT / raw[len(output_prefix):]
    if raw.startswith("/" + workspace_prefix):
        return DOWNLOAD_ROOT / raw[len("/" + workspace_prefix):]
    if raw.startswith(workspace_prefix):
        return DOWNLOAD_ROOT / raw[len(workspace_prefix):]

    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        try:
            workspace_relative = candidate.resolve().relative_to(WORKSPACE_DOWNLOAD_ROOT)
            return DOWNLOAD_ROOT / workspace_relative
        except ValueError:
            return candidate
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate


def resolve_download_path(path: str) -> Path:
    candidate = download_candidate_from_text(path)
    try:
        resolved = candidate.resolve()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid file path.") from exc
    allowed = False
    for root in DOWNLOAD_ROOTS:
        try:
            resolved.relative_to(root)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise HTTPException(status_code=403, detail="Only generated otology outputs can be downloaded.")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Generated file not found.")
    if resolved.name == "__init__.py":
        raise HTTPException(status_code=404, detail="This internal package file is hidden from the user view.")
    return resolved


def display_file_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


@app.get("/api/files/download")
async def download_generated_file(path: str = Query(..., description="Repo-relative generated output path.")):
    file_path = resolve_download_path(path)
    return FileResponse(str(file_path), filename=file_path.name)


@app.get("/api/files/preview")
async def preview_generated_file(
    path: str = Query(..., description="Repo-relative generated output path."),
    limit: int = Query(default=80000, ge=1000, le=200000),
):
    file_path = resolve_download_path(path)
    if file_path.suffix.lower() not in {".py", ".md", ".json", ".txt", ".log", ".yaml", ".yml"}:
        raise HTTPException(status_code=400, detail="Preview supports text generated artifacts only.")
    text = file_path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": display_file_path(file_path),
        "name": file_path.name,
        "content": text[:limit],
        "truncated": len(text) > limit,
        "size": len(text),
    }


@app.get("/api/sessions")
async def list_sessions():
    return {"sessions": STORE.list()}


@app.post("/api/sessions")
async def create_session():
    return {"session": STORE.create()}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    return {"session": STORE.get(session_id)}


@app.patch("/api/sessions/{session_id}")
async def update_session(session_id: str, payload: dict[str, Any]):
    session = STORE.get(session_id)
    title = str(payload.get("title", "")).strip()
    if title:
        session["title"] = title[:80]
        STORE.save(session)
    return {"session": session}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    STORE.delete(session_id)
    return {"ok": True}


def ui_message(role: str, content: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "id": uuid4().hex[:10],
        "role": role,
        "content": content,
        "timestamp": now_iso(),
        **extra,
    }


def compact(value: Any, limit: int = 4000) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, indent=2)
    return text if len(text) <= limit else text[:limit] + "\n... [truncated]"


def content_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(value)


def parse_jsonish(text: str) -> Any | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, flags=re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            return None
    return None


def merge_trace_payload(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    merged_classes = []
    for cls in data.get("merged_classes", []) or []:
        if not isinstance(cls, dict):
            continue
        merged_classes.append(
            {
                "class_name": cls.get("class_name"),
                "original_names": cls.get("original_names") or cls.get("merge_tokens") or [],
                "source_files": cls.get("source_files") or ([cls.get("source_file")] if cls.get("source_file") else []),
                "field_count": len(cls.get("fields") or []),
            }
        )
    return {
        "tool": "merge_ontology_classes",
        "input_class_count": data.get("input_class_count"),
        "merged_class_count": data.get("merged_class_count"),
        "merge_group_count": data.get("merge_group_count"),
        "conflict_count": data.get("conflict_count"),
        "merged_classes": merged_classes[:40],
        "conflicts": (data.get("conflicts") or [])[:20],
    }


def process_trace_from_final_text(text: str) -> dict[str, Any] | None:
    match = re.search(r"PROCESS_TRACE_JSON\s*:?\s*```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return {"label": "PROCESS_TRACE_JSON", "trace": parsed}


def artifact_paths_from_text(text: str) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in ARTIFACT_PATH_PATTERN.findall(str(text or "")):
        try:
            resolved = resolve_download_path(match)
        except HTTPException:
            continue
        if str(resolved) in seen:
            continue
        seen.add(str(resolved))
        artifacts.append({"path": str(resolved.relative_to(ROOT)), "name": resolved.name})
    return artifacts


def persist_case_process_from_event(case_id: str, event: dict[str, Any], run_id: str = "") -> None:
    if not case_id or event.get("type") != "tool_event":
        return
    tool = str(event.get("tool") or "")
    if tool != "merge_ontology_classes":
        return
    payload = merge_trace_payload(parse_jsonish(str(event.get("output") or "")))
    if not payload:
        return
    try:
        record_case_process_event(case_id, "merge", payload, source=tool, run_id=run_id)
    except Exception:
        pass


def persist_case_process_from_final(case_id: str, text: str, run_id: str = "") -> None:
    if not case_id:
        return
    payload = process_trace_from_final_text(text)
    if payload:
        try:
            record_case_process_event(case_id, "model_process_trace", payload, source="assistant_final", run_id=run_id)
        except Exception:
            pass
    artifacts = artifact_paths_from_text(text)
    if artifacts:
        try:
            record_case_process_event(
                case_id,
                "model_artifacts",
                {"artifacts": artifacts},
                source="assistant_final",
                run_id=run_id,
            )
        except Exception:
            pass


def persist_case_question(case_id: str, question: str, run_id: str = "") -> None:
    if not case_id:
        return
    try:
        record_case_process_event(
            case_id,
            "user_question",
            {"question": str(question or "")[:12000]},
            source="frontend_chat",
            run_id=run_id,
        )
    except Exception:
        pass


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        session = STORE.get(session_id)
    except HTTPException:
        session = STORE.create()

    await websocket.send_text(json.dumps({"type": "history", "session": session}, ensure_ascii=False))

    try:
        while True:
            raw = await websocket.receive_text()
            payload = json.loads(raw)
            if payload.get("type") == "chat":
                await handle_chat(
                    websocket,
                    session["id"],
                    str(payload.get("content", "")),
                    str(payload.get("case_id", "") or ""),
                )
            elif payload.get("type") == "history":
                await websocket.send_text(
                    json.dumps({"type": "history", "session": STORE.get(session["id"])}, ensure_ascii=False)
                )
    except WebSocketDisconnect:
        return


async def handle_chat(websocket: WebSocket, session_id: str, content: str, case_id: str = "") -> None:
    content = content.strip()
    if not content:
        return

    session = STORE.get(session_id)
    case_id = str(case_id or "").strip()
    user_message = ui_message("user", content, case_id=case_id)
    session["messages"].append(user_message)
    user_count = sum(1 for item in session["messages"] if item.get("role") == "user")
    if user_count == 1:
        session["title"] = content[:42] + ("..." if len(content) > 42 else "")
    STORE.save(session)

    await websocket.send_text(json.dumps({"type": "message", "message": user_message}, ensure_ascii=False))

    agent_content = content
    case_context: dict[str, Any] | None = None
    if case_id:
        try:
            case_context, agent_content = build_case_prompt(case_id, content)
        except ValueError as exc:
            error_message = ui_message("system", str(exc), tone="error")
            session["messages"].append(error_message)
            STORE.save(session)
            await websocket.send_text(json.dumps({"type": "error", "message": error_message}, ensure_ascii=False))
            return

    ctx = RuntimeContext(agent_id=AGENT_ID, harness_root=".", max_steps=AGENT_CFG.max_steps)
    lifecycle = RunLifecycle(ctx)
    lifecycle.start()
    os.environ["HARNESS_ROOT"] = str(ROOT)
    os.environ["HARNESS_AGENT_ID"] = AGENT_ID
    os.environ["HARNESS_RUN_DIR"] = str(Path(ctx.run_dir).resolve())
    persist_case_question(case_id, content, ctx.run_id)

    stream_id = f"assistant-{ctx.run_id}"
    await websocket.send_text(
        json.dumps(
            {
                "type": "run_start",
                "run_id": ctx.run_id,
                "stream_id": stream_id,
                "run_dir": str(ctx.run_dir),
                "model": AGENT_CFG.model.model_id,
                "case_id": case_id,
            },
            ensure_ascii=False,
        )
    )

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def emit(event: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def run_agent_thread() -> None:
        try:
            if case_context:
                emit({"type": "case_context", "case": case_context})
            if os.environ.get("FRONTEND_MOCK_AGENT") == "1":
                result = run_mock_agent(content, emit)
            else:
                result = run_streaming_agent(agent_content, session["thread_id"], str(ctx.run_dir), emit)
            emit({"type": "_done", "result": result})
        except Exception as exc:  # noqa: BLE001 - streamed to UI as a user-facing error.
            emit({"type": "_error", "error": f"{type(exc).__name__}: {exc}"})

    future = loop.run_in_executor(EXECUTOR, run_agent_thread)
    final_content = ""
    streamed_text = ""
    result_state: dict[str, Any] = {}
    run_started_at = time.monotonic()
    last_event_at = run_started_at
    future_done_at: float | None = None
    run_error: str | None = None

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                now = time.monotonic()
                if future.done():
                    if future_done_at is None:
                        future_done_at = now
                        await asyncio.sleep(0)
                        continue
                    if now - future_done_at <= 10:
                        await asyncio.sleep(0)
                        continue
                    run_error = "Agent thread ended without returning a final response."
                elif RUN_HARD_TIMEOUT_SECONDS and now - run_started_at > RUN_HARD_TIMEOUT_SECONDS:
                    run_error = (
                        f"Agent run exceeded {RUN_HARD_TIMEOUT_SECONDS}s and was stopped. "
                        "Try a narrower question or fewer selected files."
                    )
                elif RUN_IDLE_TIMEOUT_SECONDS and now - last_event_at > RUN_IDLE_TIMEOUT_SECONDS:
                    run_error = (
                        f"Agent produced no updates for {RUN_IDLE_TIMEOUT_SECONDS}s and was stopped. "
                        "This usually means the model/provider stalled after a tool call."
                    )
                if not run_error:
                    continue
                session = STORE.get(session_id)
                error_message = ui_message("system", run_error, tone="error")
                session["messages"].append(error_message)
                STORE.save(session)
                await websocket.send_text(json.dumps({"type": "error", "message": error_message}, ensure_ascii=False))
                future.cancel()
                break

            last_event_at = time.monotonic()

            if event["type"] == "assistant_delta":
                delta = event.get("content", "")
                streamed_text += delta
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "assistant_delta",
                            "id": stream_id,
                            "delta": delta,
                            "agent": event.get("agent") or AGENT_ID,
                        },
                        ensure_ascii=False,
                    )
                )
                continue

            session = STORE.get(session_id)

            if event["type"] == "_done":
                result_state = event.get("result", {}) or {}
                final_content = extract_final_content(result_state) or streamed_text
                persist_case_process_from_final(case_id, final_content, ctx.run_id)
                if final_content:
                    assistant_message = ui_message("assistant", final_content, id=stream_id, agent=AGENT_ID)
                    session["messages"].append(assistant_message)
                    STORE.save(session)
                    await websocket.send_text(
                        json.dumps({"type": "assistant_final", "message": assistant_message}, ensure_ascii=False)
                    )
                break

            if event["type"] == "_error":
                run_error = event["error"]
                error_message = ui_message("system", event["error"], tone="error")
                session["messages"].append(error_message)
                STORE.save(session)
                await websocket.send_text(json.dumps({"type": "error", "message": error_message}, ensure_ascii=False))
                break

            persist_case_process_from_event(case_id, event, ctx.run_id)
            event_message = event_to_message(event)
            session["messages"].append(event_message)
            STORE.save(session)
            await websocket.send_text(json.dumps({"type": "event", "message": event_message}, ensure_ascii=False))

        if future.done():
            try:
                await future
            except Exception as exc:  # noqa: BLE001 - already surfaced as a UI error when possible.
                if not run_error:
                    run_error = f"{type(exc).__name__}: {exc}"
        else:
            future.cancel()
    finally:
        try:
            workspace_dir = str(_resolve_path(AGENT_CFG.workspace, str(ROOT)))
            system_prompt = _load_prompt(AGENT_CFG, workspace_dir, str(ROOT))
            output_path = ctx.run_dir / "messages.jsonl"
            if isinstance(result_state, dict) and result_state.get("messages"):
                record_run(
                    result_state["messages"],
                    output_path,
                    metadata={"run_id": ctx.run_id, "agent_id": AGENT_ID, "ui_session_id": session_id},
                    system_prompt=system_prompt,
                )
        except Exception:
            pass

        ctx.step()
        lifecycle.update_step()
        lifecycle.finish(run_error)
        try:
            await websocket.send_text(json.dumps({"type": "run_done", "run_id": ctx.run_id}, ensure_ascii=False))
        except Exception:
            pass


def run_mock_agent(message: str, emit) -> dict[str, Any]:
    emit({"type": "tool_call", "agent": AGENT_ID, "tool": "mock_runtime", "args": {"message": message}})
    time.sleep(0.05)
    emit({"type": "tool_event", "event": "tool_end", "agent": AGENT_ID, "tool": "mock_runtime", "output": "Mock tool completed."})
    final = f"Mock streaming response from {AGENT_ID}. Your message was: {message}"
    for chunk in final.split(" "):
        emit({"type": "assistant_delta", "agent": AGENT_ID, "content": chunk + " "})
        time.sleep(0.01)
    return {"final_content": final}


def run_streaming_agent(message: str, thread_id: str, run_dir: str, emit) -> dict[str, Any]:
    os.environ["HARNESS_ROOT"] = str(ROOT)
    os.environ["HARNESS_AGENT_ID"] = AGENT_ID
    os.environ["HARNESS_RUN_DIR"] = str(Path(run_dir).resolve())

    agent = build_agent(AGENT_CFG, ".", registry=REGISTRY)
    config = {"configurable": {"thread_id": thread_id or "default"}}
    last_values: dict[str, Any] = {}
    root_prev_count: int | None = None
    seen_message_ids: set[str] = set()

    for item in agent.stream(
        {"messages": [HumanMessage(content=message)]},
        config=config,
        stream_mode=["messages", "values"],
        subgraphs=True,
    ):
        if not isinstance(item, tuple) or len(item) != 3:
            continue
        namespace, mode, data = item
        is_root = namespace == ()

        if mode == "messages":
            chunk, meta = data
            if meta.get("langgraph_node") != "model":
                continue
            text = content_to_text(getattr(chunk, "content", ""))
            if text:
                emit({"type": "assistant_delta", "agent": meta.get("lc_agent_name") or meta.get("name") or AGENT_ID, "content": text})
            continue

        if mode != "values" or not isinstance(data, dict):
            continue

        messages = data.get("messages", []) or []
        if is_root:
            last_values = data
            if root_prev_count is None:
                root_prev_count = len(messages)
                for msg in messages:
                    msg_id = getattr(msg, "id", "")
                    if msg_id:
                        seen_message_ids.add(msg_id)
                continue
            new_messages = messages[root_prev_count:]
            root_prev_count = len(messages)
        else:
            new_messages = messages

        for msg in new_messages:
            process_stream_message(msg, seen_message_ids, emit)

    if not last_values.get("messages"):
        try:
            state = agent.get_state(config)
            if state:
                last_values = dict(state.values)
        except Exception:
            pass
    return last_values if last_values else {"messages": []}


def process_stream_message(msg: Any, seen_message_ids: set[str], emit) -> None:
    msg_id = getattr(msg, "id", "") or f"{getattr(msg, 'type', 'msg')}:{hash(content_to_text(getattr(msg, 'content', '')))}"
    if msg_id in seen_message_ids:
        return
    seen_message_ids.add(msg_id)

    msg_type = getattr(msg, "type", "")
    agent = getattr(msg, "name", "") or AGENT_ID
    if msg_type == "ai":
        for call in getattr(msg, "tool_calls", None) or []:
            emit(
                {
                    "type": "tool_call",
                    "agent": agent,
                    "tool": call.get("name", "unknown"),
                    "args": call.get("args", {}),
                    "call_id": call.get("id", ""),
                }
            )
        content = content_to_text(getattr(msg, "content", ""))
        if content:
            emit({"type": "model_output", "agent": agent, "content": content})
    elif msg_type == "tool":
        emit(
            {
                "type": "tool_event",
                "event": "tool_end",
                "agent": agent,
                "tool": getattr(msg, "name", "tool") or "tool",
                "output": content_to_text(getattr(msg, "content", ""))[:5000],
            }
        )


def extract_final_content(result_state: dict[str, Any]) -> str:
    if result_state.get("final_content"):
        return str(result_state["final_content"])
    messages = result_state.get("messages", []) if isinstance(result_state, dict) else []
    for msg in reversed(messages):
        if getattr(msg, "type", "") == "ai":
            content = content_to_text(getattr(msg, "content", ""))
            if content:
                return content
    return ""


def event_to_message(event: dict[str, Any]) -> dict[str, Any]:
    event_type = event["type"]
    if event_type == "case_context":
        case = event.get("case", {}) or {}
        stats = case.get("stats") or {}
        return ui_message(
            "event",
            compact(
                {
                    "case_id": case.get("id"),
                    "case_name": case.get("name"),
                    "question": case.get("question"),
                    "output_dir": case.get("output_dir"),
                    "prepared_root": case.get("prepared_root"),
                    "stats": stats,
                },
                3000,
            ),
            kind="case_context",
            title=f"Excel Case · {case.get('name') or case.get('id') or 'selected'}",
            agent=AGENT_ID,
        )
    if event_type == "model_output":
        return ui_message(
            "event",
            event["content"],
            kind="model_output",
            title="Model output",
            agent=event.get("agent") or AGENT_ID,
        )
    if event_type == "tool_call":
        return ui_message(
            "event",
            compact(event.get("args", {}), 3000),
            kind="tool_call",
            title=f"Calling {event.get('tool', 'tool')}",
            agent=event.get("agent") or AGENT_ID,
            tool=event.get("tool", ""),
        )
    if event_type == "tool_event":
        label = event.get("event", "tool_event")
        output = event.get("output", event.get("input", ""))
        return ui_message(
            "event",
            compact(output, 5000),
            kind=label,
            title=f"{label.replace('_', ' ').title()} · {event.get('tool') or event.get('agent') or 'tool'}",
            agent=event.get("agent") or AGENT_ID,
            tool=event.get("tool", ""),
        )
    return ui_message("event", compact(event), kind=event_type, title=event_type)


def main() -> None:
    import uvicorn

    port = int(os.environ.get("OTOLOGY_UI_PORT", os.environ.get("PORT", "50004")))
    print(f"\n{UI_BRAND}")
    print(f"  http://0.0.0.0:{port}")
    print(f"  sessions: {SESSION_DIR}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
