"""LangChain tool wrapper for validate_python_artifacts."""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class ValidatePythonArtifactsInput(BaseModel):
    paths: List[str] = Field(..., description="Python files or directories to validate.")
    recursive: bool = Field(default=True, description="Recursively validate directories.")


class ValidatePythonArtifactsTool(BaseTool):
    name: str = "validate_python_artifacts"
    description: str = (
        "Validate generated Python artifacts with py_compile, identifier checks, and sensitive-term checks."
    )
    args_schema: type[BaseModel] = ValidatePythonArtifactsInput

    def _run(self, paths: List[str], recursive: bool = True) -> str:
        try:
            from ..tools_impl.validate_python_artifacts import validate_python_artifacts_json

            return validate_python_artifacts_json(paths=paths, recursive=recursive)
        except Exception as exc:
            return f"[Error] validate_python_artifacts failed: {type(exc).__name__}: {exc}"

    async def _arun(self, paths: List[str], recursive: bool = True) -> str:
        return self._run(paths=paths, recursive=recursive)
