"""Path helpers for the harness-managed KBQA tools."""

from __future__ import annotations

import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[2]
DEFAULT_RUNTIME_ROOT = REPO_ROOT / "data" / "deepagents_kbqa" / "runtime"


def get_runtime_root() -> Path:
    """Return the directory that contains `freebase_env/` and KBQA caches."""

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
