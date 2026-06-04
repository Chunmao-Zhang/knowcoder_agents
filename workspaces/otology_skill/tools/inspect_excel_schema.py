"""LangChain tool wrapper for inspect_excel_schema."""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class InspectExcelSchemaInput(BaseModel):
    excel_path: str = Field(..., description="Path to an .xlsx workbook to inspect.")
    sheet_names: List[str] = Field(default_factory=list, description="Optional sheet names to inspect; empty means all sheets.")
    max_rows: int = Field(default=30, description="Maximum rows to sample per sheet.")
    max_samples: int = Field(default=5, description="Maximum sample values per inferred column.")


class InspectExcelSchemaTool(BaseTool):
    name: str = "inspect_excel_schema"
    description: str = (
        "Inspect an Excel workbook and infer sheet names, table candidates, header rows, "
        "columns, Python field names, types, and sample values."
    )
    args_schema: type[BaseModel] = InspectExcelSchemaInput

    def _run(self, excel_path: str, sheet_names: List[str] | None = None, max_rows: int = 30, max_samples: int = 5) -> str:
        try:
            from ..tools_impl.inspect_excel_schema import inspect_excel_schema_json

            return inspect_excel_schema_json(
                excel_path=excel_path,
                sheet_names=sheet_names or [],
                max_rows=max_rows,
                max_samples=max_samples,
            )
        except Exception as exc:
            return f"[Error] inspect_excel_schema failed: {type(exc).__name__}: {exc}"

    async def _arun(self, excel_path: str, sheet_names: List[str] | None = None, max_rows: int = 30, max_samples: int = 5) -> str:
        return self._run(excel_path=excel_path, sheet_names=sheet_names, max_rows=max_rows, max_samples=max_samples)
