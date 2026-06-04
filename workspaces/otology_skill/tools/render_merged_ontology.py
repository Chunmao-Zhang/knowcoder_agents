"""LangChain tool wrapper for render_merged_ontology."""

from __future__ import annotations

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class RenderMergedOntologyInput(BaseModel):
    merged_classes_json: str = Field(..., description="JSON from merge_ontology_classes, or a JSON list of merged classes.")
    output_dir: str = Field(..., description="Output directory for merged_ontology.py and alignment_report.md.")
    python_filename: str = Field(default="merged_ontology.py", description="Python output filename.")
    report_filename: str = Field(default="alignment_report.md", description="Markdown report output filename.")
    compile_check: bool = Field(default=True, description="Run py_compile on the rendered Python file.")


class RenderMergedOntologyTool(BaseTool):
    name: str = "render_merged_ontology"
    description: str = (
        "Render merged ontology metadata into a Python ontology module and Markdown alignment report."
    )
    args_schema: type[BaseModel] = RenderMergedOntologyInput

    def _run(
        self,
        merged_classes_json: str,
        output_dir: str,
        python_filename: str = "merged_ontology.py",
        report_filename: str = "alignment_report.md",
        compile_check: bool = True,
    ) -> str:
        try:
            from ..tools_impl.render_merged_ontology import render_merged_ontology_json

            return render_merged_ontology_json(
                merged_classes_json=merged_classes_json,
                output_dir=output_dir,
                python_filename=python_filename,
                report_filename=report_filename,
                compile_check=compile_check,
            )
        except Exception as exc:
            return f"[Error] render_merged_ontology failed: {type(exc).__name__}: {exc}"

    async def _arun(
        self,
        merged_classes_json: str,
        output_dir: str,
        python_filename: str = "merged_ontology.py",
        report_filename: str = "alignment_report.md",
        compile_check: bool = True,
    ) -> str:
        return self._run(
            merged_classes_json=merged_classes_json,
            output_dir=output_dir,
            python_filename=python_filename,
            report_filename=report_filename,
            compile_check=compile_check,
        )
