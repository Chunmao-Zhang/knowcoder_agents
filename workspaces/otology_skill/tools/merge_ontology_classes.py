"""LangChain tool wrapper for merge_ontology_classes."""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class MergeOntologyClassesInput(BaseModel):
    classes_json: str = Field(..., description="JSON from parse_ontology_files, or a JSON list of parsed classes.")
    merge_groups: List[List[str]] = Field(
        default_factory=list,
        description=(
            "Approved merge groups. Each item is a list of class names or source_file::class_name keys. "
            "Semantic groups must be confirmed by the user before calling this tool."
        ),
    )
    include_unmerged: bool = Field(default=True, description="Include classes not referenced by merge_groups in the output.")
    auto_merge_exact_names: bool = Field(default=True, description="Automatically merge duplicate exact class names.")


class MergeOntologyClassesTool(BaseTool):
    name: str = "merge_ontology_classes"
    description: str = (
        "Merge parsed ontology class metadata after the skill has decided/confirmed alignment groups. "
        "Returns merged_classes JSON plus field conflicts."
    )
    args_schema: type[BaseModel] = MergeOntologyClassesInput

    def _run(
        self,
        classes_json: str,
        merge_groups: List[List[str]] | None = None,
        include_unmerged: bool = True,
        auto_merge_exact_names: bool = True,
    ) -> str:
        try:
            from ..tools_impl.merge_ontology_classes import merge_ontology_classes_json

            return merge_ontology_classes_json(
                classes_json=classes_json,
                merge_groups=merge_groups or [],
                include_unmerged=include_unmerged,
                auto_merge_exact_names=auto_merge_exact_names,
            )
        except Exception as exc:
            return f"[Error] merge_ontology_classes failed: {type(exc).__name__}: {exc}"

    async def _arun(
        self,
        classes_json: str,
        merge_groups: List[List[str]] | None = None,
        include_unmerged: bool = True,
        auto_merge_exact_names: bool = True,
    ) -> str:
        return self._run(
            classes_json=classes_json,
            merge_groups=merge_groups,
            include_unmerged=include_unmerged,
            auto_merge_exact_names=auto_merge_exact_names,
        )
