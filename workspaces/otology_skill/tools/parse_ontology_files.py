"""LangChain tool wrapper for parse_ontology_files."""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class ParseOntologyFilesInput(BaseModel):
    file_paths: List[str] = Field(..., description="Python ontology files to parse.")
    include_source: bool = Field(
        default=False,
        description="Return full class source snippets. Keep false for large uploaded cases.",
    )
    field_limit: int = Field(
        default=8,
        description="Maximum fields returned per class; use -1 for all fields.",
    )


class ParseOntologyFilesTool(BaseTool):
    name: str = "parse_ontology_files"
    description: str = (
        "Parse Python ontology files and return structured class metadata: class names, "
        "docstrings, bases, decorators, summarized fields, and methods."
    )
    args_schema: type[BaseModel] = ParseOntologyFilesInput

    def _run(self, file_paths: List[str], include_source: bool = False, field_limit: int = 8) -> str:
        try:
            from ..tools_impl.parse_ontology_files import parse_ontology_files_json

            return parse_ontology_files_json(
                file_paths=file_paths,
                include_source=include_source,
                field_limit=field_limit,
            )
        except Exception as exc:
            return f"[Error] parse_ontology_files failed: {type(exc).__name__}: {exc}"

    async def _arun(self, file_paths: List[str], include_source: bool = False, field_limit: int = 8) -> str:
        return self._run(file_paths=file_paths, include_source=include_source, field_limit=field_limit)
