"""路径工具实现。

作用：
- 为 `otology_skill` workspace 的工具统一解析仓库根目录、数据目录和输出目录。
- 将用户传入的相对路径稳定解析为仓库根目录下的绝对路径，避免工具各自拼路径导致不一致。

主要输入：
- `path`: 用户提供的文件或目录路径，可为绝对路径、`~` 路径或仓库相对路径。

主要输出：
- `resolve_path` 返回绝对 `Path`。
- `ensure_output_dir` 创建并返回输出目录 `Path`。
"""

from __future__ import annotations

from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = WORKSPACE_ROOT.parents[1]
DATA_ROOT = REPO_ROOT / "data" / "otology_skill"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "otology_skill"


def resolve_path(path: str | Path) -> Path:
    """Resolve a user-provided path relative to the repository root."""

    value = Path(path).expanduser()
    if not value.is_absolute():
        value = REPO_ROOT / value
    return value.resolve()


def ensure_output_dir(path: str | Path) -> Path:
    """Create and return an output directory."""

    output_dir = resolve_path(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir
