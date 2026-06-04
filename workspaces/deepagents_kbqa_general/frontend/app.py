#!/usr/bin/env python3
"""Code On Graph Agent frontend.

Run from the repository root:
    PYTHONPATH=. python3 workspaces/deepagents_kbqa_general/frontend/app.py
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
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
from workspaces.deepagents_kbqa_general.code.graph_runtime import (
    activate_graph_scope,
    delete_graph,
    import_uploaded_graph,
    list_graphs,
    read_active_scope,
    summarize_graph,
)


AGENT_ID = "deepagents_kbqa_general"
UI_BRAND = "Code On Graph Agent"
THREAD_PREFIX = "kbqa-ui"
STATIC_DIR = Path(__file__).resolve().parent / "static"
SESSION_DIR = ROOT / "outputs" / "deepagents_kbqa_general" / "frontend_sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

# Hardcoded fallback requested for local frontend launch.
HARDCODED_SILICONFLOW_API_KEY = "sk-jrbbpcqrcszeayxawoblajrquctswwofkjwtlnoiqdavkfyx"
if HARDCODED_SILICONFLOW_API_KEY and not os.environ.get("SILICONFLOW_API_KEY"):
    os.environ["SILICONFLOW_API_KEY"] = HARDCODED_SILICONFLOW_API_KEY

CONFIG_PATH = Path(os.environ.get("HARNESS_CONFIG", ROOT / "harness.json")).expanduser()
CONFIG = load_config(CONFIG_PATH)
REGISTRY = AgentRegistry(CONFIG)
AGENT_CFG = REGISTRY.get(AGENT_ID)
EXECUTOR = ThreadPoolExecutor(max_workers=3)
GRAPH_SCOPE_THREAD_LOCK = threading.Lock()
FRONTEND_SCRIPT = Path(__file__).resolve()
RUN_IDLE_TIMEOUT_SECONDS = int(os.environ.get("KBQA_AGENT_IDLE_TIMEOUT_SECONDS", "180"))
RUN_HARD_TIMEOUT_SECONDS = int(os.environ.get("KBQA_AGENT_HARD_TIMEOUT_SECONDS", "900"))
GRAPH_LOCK_TIMEOUT_SECONDS = int(os.environ.get("KBQA_GRAPH_LOCK_TIMEOUT_SECONDS", "45"))
SESSION_EVENT_LIMIT = int(os.environ.get("KBQA_SESSION_EVENT_LIMIT", "120"))


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
    """Keep chat files small while preserving user/assistant turns."""

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


def read_general_stats() -> dict[str, Any]:
    manifest = ROOT / "data" / "deepagents_kbqa_general" / "runtime" / "general_env" / "active_graph.json"
    if not manifest.exists():
        return {}
    try:
        data = read_json(manifest)
    except Exception:
        return {}
    return {
        "entity_count": data.get("entity_count"),
        "relation_count": data.get("relation_count"),
        "triple_count": data.get("triple_count"),
        "graph_count": data.get("graph_count"),
        "graph_catalog": data.get("graph_catalog", {}),
        "generated_at": data.get("generated_at"),
    }


def read_general_relation_types() -> dict[str, str]:
    manifest = ROOT / "data" / "deepagents_kbqa_general" / "runtime" / "general_env" / "active_graph.json"
    if not manifest.exists():
        return {}
    try:
        data = read_json(manifest)
    except Exception:
        return {}
    relation_types = data.get("relation_types", {})
    return relation_types if isinstance(relation_types, dict) else {}

def project_metadata() -> dict[str, Any]:
    skills_dir = ROOT / "workspaces" / "deepagents_kbqa_general" / "skills"
    skills = sorted(path.name for path in skills_dir.iterdir() if path.is_dir()) if skills_dir.exists() else []
    relations = read_general_relation_types()
    relation_cards = [
        {"source": "Entity", "predicate": rel, "target": "Entity", "type": rel_type}
        for rel, rel_type in list(relations.items())[:24]
    ]
    return {
        "workspace": str(ROOT / "workspaces" / "deepagents_kbqa_general"),
        "tools": [
            "search_entity",
            "search_predicate",
            "list_predicates_by_entity",
            "search_entity_by_predicate",
            "build_subgraph_schema",
            "execute_code",
        ],
        "skills": skills,
        "dataset": read_general_stats(),
        "graph_schema": {
            "title": "Generic File-Backed Knowledge Graph",
            "subtitle": "Uploaded TXT, JSON, or XLSX triples are prepared into SQLite + ChromaDB for KBQA.",
            "nodes": [
                {"id": "entity", "label": "Entity", "description": "Any subject or object in the uploaded triples."},
                {"id": "predicate", "label": "Predicate", "description": "Relations encoded by prepare.py for semantic search."},
                {"id": "subgraph", "label": "Subgraph", "description": "Tool-selected local evidence serialized as a schema file."},
                {"id": "answer", "label": "Boxed Answer", "description": "Final normalized names emitted as \\boxed{[...]}."},
            ],
            "relations": relation_cards,
            "pipeline": [
                {"label": "Entity Link", "detail": "search_entity maps text mentions to exact entity names in the active graph."},
                {"label": "Predicate Probe", "detail": "search_predicate and list_predicates_by_entity identify candidate relations."},
                {"label": "Subgraph Schema", "detail": "build_subgraph_schema materializes a class-like graph view."},
                {"label": "Code Reasoning", "detail": "execute_code filters paths and formats boxed answers."},
            ],
        },
        "runtime": str(ROOT / "data" / "deepagents_kbqa_general" / "runtime" / "general_env"),
        "smoke_tests": [
            "workspaces/deepagents_kbqa_general/code/prepare.py",
            "workspaces/deepagents_kbqa_general/code/e2e_smoke.py",
            "workspaces/deepagents_kbqa_general/code/metaqa_graph_import_smoke.py",
            "workspaces/deepagents_kbqa_general/code/metaqa_entity_search_smoke.py",
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
    if AGENT_ID == "deepagents_kbqa_general":
        data["graph_runtime"] = read_general_stats()
        data["graph_catalog"] = list_graphs(limit=100)
        data["graph_scope"] = read_active_scope()
    return data


@app.get("/api/graphs/imports")
async def list_graph_imports():
    return {"imports": list_graphs(limit=100)}


@app.get("/api/graphs/summary")
async def graph_summary(graph_id: str = ""):
    try:
        return summarize_graph(graph_id or None)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/graphs/imports")
async def import_graph(
    file: UploadFile = File(...),
    dataset_name: str = Form(default=""),
):
    raw_content = await file.read()

    def import_graph_thread() -> dict[str, Any]:
        with GRAPH_SCOPE_THREAD_LOCK:
            return import_uploaded_graph(
                file.filename or "uploaded_graph.txt",
                raw_content,
                dataset_name,
            )

    try:
        report = await asyncio.to_thread(import_graph_thread)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "import": report}


@app.delete("/api/graphs/imports/{graph_id}")
async def delete_graph_import(graph_id: str):
    def delete_graph_thread() -> dict[str, Any]:
        with GRAPH_SCOPE_THREAD_LOCK:
            return delete_graph(graph_id)

    try:
        report = await asyncio.to_thread(delete_graph_thread)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, **report}


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
                    str(payload.get("graph_id", "") or ""),
                )
            elif payload.get("type") == "history":
                await websocket.send_text(
                    json.dumps({"type": "history", "session": STORE.get(session["id"])}, ensure_ascii=False)
                )
    except WebSocketDisconnect:
        return


async def handle_chat(websocket: WebSocket, session_id: str, content: str, graph_id: str = "") -> None:
    content = content.strip()
    if not content:
        return

    session = STORE.get(session_id)
    user_message = ui_message("user", content, graph_id=graph_id)
    session["messages"].append(user_message)
    user_count = sum(1 for item in session["messages"] if item.get("role") == "user")
    if user_count == 1:
        session["title"] = content[:42] + ("..." if len(content) > 42 else "")
    STORE.save(session)

    await websocket.send_text(json.dumps({"type": "message", "message": user_message}, ensure_ascii=False))

    ctx = RuntimeContext(agent_id=AGENT_ID, harness_root=".", max_steps=AGENT_CFG.max_steps)
    lifecycle = RunLifecycle(ctx)
    lifecycle.start()
    os.environ["HARNESS_ROOT"] = str(ROOT)
    os.environ["HARNESS_AGENT_ID"] = AGENT_ID
    os.environ["HARNESS_RUN_DIR"] = str(Path(ctx.run_dir).resolve())

    stream_id = f"assistant-{ctx.run_id}"
    await websocket.send_text(
        json.dumps(
            {
                "type": "run_start",
                "run_id": ctx.run_id,
                "stream_id": stream_id,
                "run_dir": str(ctx.run_dir),
                "model": AGENT_CFG.model.model_id,
                "graph_id": graph_id,
            },
            ensure_ascii=False,
        )
    )

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def emit(event: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def run_agent_thread() -> None:
        lock_acquired = False
        try:
            if GRAPH_SCOPE_THREAD_LOCK.locked():
                emit(
                    {
                        "type": "graph_wait",
                        "message": "Waiting for another graph scope activation to finish.",
                    }
                )
            lock_acquired = GRAPH_SCOPE_THREAD_LOCK.acquire(timeout=GRAPH_LOCK_TIMEOUT_SECONDS)
            if not lock_acquired:
                raise TimeoutError(
                    f"Another graph run is still activating after {GRAPH_LOCK_TIMEOUT_SECONDS}s. "
                    "Restart the frontend if an older run is stuck."
                )
            try:
                scope = activate_graph_scope(graph_id)
            finally:
                GRAPH_SCOPE_THREAD_LOCK.release()
                lock_acquired = False
            emit({"type": "graph_scope", "scope": scope})
            if os.environ.get("FRONTEND_MOCK_AGENT") == "1":
                result = run_mock_agent(content, emit)
            else:
                result = run_streaming_agent(content, session["thread_id"], str(ctx.run_dir), emit)
            emit({"type": "_done", "result": result})
        except Exception as exc:  # noqa: BLE001 - streamed to UI as a user-facing error.
            emit({"type": "_error", "error": f"{type(exc).__name__}: {exc}"})
        finally:
            if lock_acquired:
                GRAPH_SCOPE_THREAD_LOCK.release()

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
                        "Try a narrower question or restart the frontend if a prior run is stuck."
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
                            "model_message_id": event.get("message_id", ""),
                            "replace": bool(event.get("replace")),
                        },
                        ensure_ascii=False,
                    )
                )
                continue

            session = STORE.get(session_id)

            if event["type"] == "_done":
                result_state = event.get("result", {}) or {}
                final_content = extract_final_content(result_state) or streamed_text
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

            event_message = event_to_message(event)
            session["messages"].append(event_message)
            STORE.save(session)
            await websocket.send_text(json.dumps({"type": "event", "message": event_message}, ensure_ascii=False))

        if future.done():
            try:
                await future
            except Exception as exc:  # noqa: BLE001 - already surfaced to the UI when possible.
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
        emit({"type": "assistant_delta", "agent": AGENT_ID, "content": chunk + " ", "message_id": "mock-final", "replace": False})
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
    replace_next_model_delta = True

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
                message_id = "|".join(
                    part
                    for part in [
                        str(getattr(chunk, "id", "") or ""),
                        repr(namespace),
                        str(meta.get("langgraph_step") or ""),
                        str(meta.get("checkpoint_ns") or ""),
                        str(meta.get("langgraph_node") or "model"),
                        str(meta.get("run_id") or ""),
                    ]
                    if part
                )
                emit(
                    {
                        "type": "assistant_delta",
                        "agent": meta.get("lc_agent_name") or meta.get("name") or AGENT_ID,
                        "content": text,
                        "message_id": message_id,
                        "replace": replace_next_model_delta,
                    }
                )
                replace_next_model_delta = False
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
            # A completed graph message (AI/tool) means any future model token is
            # a fresh model turn. This is more reliable than provider-specific
            # chunk ids, especially for reasoning_content streams.
            if getattr(msg, "type", "") in {"ai", "tool"}:
                replace_next_model_delta = True

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
        content = content_to_text(getattr(msg, "content", ""))
        if content:
            emit({"type": "model_output", "agent": agent, "content": content, "message_id": msg_id})
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
    if event_type == "graph_scope":
        scope = event.get("scope", {}) or {}
        label = scope.get("graph_name") or "All graphs"
        mode = scope.get("mode") or "all"
        return ui_message(
            "event",
            compact(scope, 2000),
            kind="graph_scope",
            title=f"Graph Scope · {label} ({mode})",
            agent=AGENT_ID,
        )
    if event_type == "graph_wait":
        return ui_message(
            "event",
            event.get("message", "Waiting for graph runtime."),
            kind="graph_wait",
            title="Graph Runtime Queue",
            agent=AGENT_ID,
        )
    if event_type == "model_output":
        return ui_message(
            "event",
            event["content"],
            kind="model_output",
            title="Model output",
            agent=event.get("agent") or AGENT_ID,
            model_message_id=event.get("message_id", ""),
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


def port_listener_pids(port: int) -> list[int]:
    """Return local listener PIDs for a TCP port using the macOS/Linux lsof tool."""

    try:
        result = subprocess.run(
            ["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    for line in result.stdout.splitlines():
        try:
            pids.append(int(line.strip()))
        except ValueError:
            continue
    return pids


def process_command(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def is_stale_frontend_process(pid: int) -> bool:
    if pid == os.getpid():
        return False
    command = process_command(pid)
    script_path = str(FRONTEND_SCRIPT)
    relative_script = "workspaces/deepagents_kbqa_general/frontend/app.py"
    return script_path in command or relative_script in command


def wait_until_port_free(port: int, timeout_seconds: float = 4.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not port_listener_pids(port):
            return True
        time.sleep(0.15)
    return not port_listener_pids(port)


def stop_stale_frontend_processes(port: int) -> None:
    pids = port_listener_pids(port)
    if not pids:
        return

    stale_pids = [pid for pid in pids if is_stale_frontend_process(pid)]
    foreign_pids = [pid for pid in pids if pid not in stale_pids]
    if foreign_pids:
        details = "; ".join(f"{pid}: {process_command(pid) or 'unknown command'}" for pid in foreign_pids)
        raise RuntimeError(
            f"Port {port} is occupied by a non-Code-On-Graph process. "
            f"Stop it manually or set KBQA_UI_PORT/PORT to another value. Occupiers: {details}"
        )

    for pid in stale_pids:
        print(f"Stopping stale Code On Graph Agent process on port {port}: PID {pid}", flush=True)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue

    if wait_until_port_free(port):
        return

    for pid in stale_pids:
        try:
            print(f"Force stopping stale Code On Graph Agent process: PID {pid}", flush=True)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue

    if not wait_until_port_free(port, timeout_seconds=2.0):
        raise RuntimeError(f"Port {port} is still occupied after stopping stale frontend processes.")


def main() -> None:
    import uvicorn

    port = int(os.environ.get("KBQA_UI_PORT", os.environ.get("PORT", "50003")))
    if os.environ.get("KBQA_UI_KILL_STALE", "1") != "0":
        stop_stale_frontend_processes(port)
    print("\nCode On Graph Agent", flush=True)
    print(f"  http://0.0.0.0:{port}", flush=True)
    print(f"  sessions: {SESSION_DIR}\n", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
