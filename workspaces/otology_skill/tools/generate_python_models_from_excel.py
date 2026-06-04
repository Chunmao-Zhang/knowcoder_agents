"""LangChain tool wrapper for generate_python_models_from_excel."""

from __future__ import annotations

from typing import Dict, List

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class GeneratePythonModelsFromExcelInput(BaseModel):
    excel_path: str = Field(..., description="Path to an .xlsx workbook containing table metadata.")
    output_dir: str = Field(..., description="Directory where generated Python model files should be written.")
    sheet_names: List[str] = Field(default_factory=list, description="Optional sheet names to generate; empty means all sheets.")
    field_comment_overrides: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional comments decided by the skill/LLM before tool execution. Keys may be field_name, "
            "original_name, table.field_name, table.original_name, sheet.field_name, or sheet.original_name."
        ),
    )
    field_name_overrides: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional stable Python field names decided by the skill/LLM. Keys may be original_name, "
            "source field, table.original_name, table.source field, sheet.original_name, or sheet.source field."
        ),
    )
    compile_check: bool = Field(default=True, description="Run py_compile on generated Python files.")


class GeneratePythonModelsFromExcelTool(BaseTool):
    name: str = "generate_python_models_from_excel"
    description: str = (
        "Generate Python class files from Excel table metadata, "
        "including field comments, inferred types, simple relationship detection, and optional py_compile validation."
    )
    args_schema: type[BaseModel] = GeneratePythonModelsFromExcelInput

    def _run(
        self,
        excel_path: str,
        output_dir: str,
        sheet_names: List[str] | None = None,
        field_name_overrides: Dict[str, str] | None = None,
        field_comment_overrides: Dict[str, str] | None = None,
        compile_check: bool = True,
    ) -> str:
        try:
            from ..tools_impl.generate_python_models_from_excel import generate_python_models_from_excel_json

            return generate_python_models_from_excel_json(
                excel_path=excel_path,
                output_dir=output_dir,
                sheet_names=sheet_names or [],
                field_name_overrides=field_name_overrides or {},
                field_comment_overrides=field_comment_overrides or {},
                compile_check=compile_check,
            )
        except Exception as exc:
            return f"[Error] generate_python_models_from_excel failed: {type(exc).__name__}: {exc}"

    async def _arun(
        self,
        excel_path: str,
        output_dir: str,
        sheet_names: List[str] | None = None,
        field_name_overrides: Dict[str, str] | None = None,
        field_comment_overrides: Dict[str, str] | None = None,
        compile_check: bool = True,
    ) -> str:
        return self._run(
            excel_path=excel_path,
            output_dir=output_dir,
            sheet_names=sheet_names,
            field_name_overrides=field_name_overrides,
            field_comment_overrides=field_comment_overrides,
            compile_check=compile_check,
        )
