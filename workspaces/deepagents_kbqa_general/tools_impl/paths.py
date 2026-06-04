"""Path helpers for the generic, file-backed KBQA tools."""

from __future__ import annotations

import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = PACKAGE_ROOT.parent
REPO_ROOT = PACKAGE_ROOT.parents[2]
DEFAULT_RUNTIME_ROOT = REPO_ROOT / "data" / "deepagents_kbqa_general" / "runtime"
DEFAULT_GENERAL_ENV = DEFAULT_RUNTIME_ROOT / "general_env"
WORKSPACE_EMBEDDING_MODEL = WORKSPACE_ROOT / "embedding_model" / "retriver_webqsp-cwq_relation"


def get_runtime_root() -> Path:
    """Return the directory that contains the active generic graph runtime."""

    raw = os.getenv("KBQA_RUNTIME_ROOT") or os.getenv("KBQA_PROJECT_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_RUNTIME_ROOT


def configure_environment() -> Path:
    """Set stable runtime environment defaults and return the runtime root."""

    runtime_root = get_runtime_root()
    os.environ["KBQA_RUNTIME_ROOT"] = str(runtime_root)
    os.environ["KBQA_PROJECT_ROOT"] = str(runtime_root)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    os.environ.setdefault("MKL_NUM_THREADS", "4")
    return runtime_root


def get_general_env() -> Path:
    """Return the active graph environment under the runtime root."""

    raw = os.getenv("KBQA_GENERAL_ENV")
    if raw:
        return Path(raw).expanduser().resolve()
    return get_runtime_root() / "general_env"
