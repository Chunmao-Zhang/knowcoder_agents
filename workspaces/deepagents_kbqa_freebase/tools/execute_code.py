"""ExecuteCodeTool -- LangChain BaseTool wrapper for execute_code.

Execute Python in a sandbox, loading schema from build_subgraph_schema's subgraph_file.
"""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class ExecuteCodeInput(BaseModel):
    """Input schema for execute_code."""
    code_lines: List[str] = Field(
        ..., description="One Python statement per list element; joined with newlines and executed at runtime."
    )
    subgraph_file: str = Field(
        ..., description="The `# subgraph_file: <path>` path returned by build_subgraph_schema."
    )


class ExecuteCodeTool(BaseTool):
    """Execute Python in a sandbox, loading Python classes from build_subgraph_schema's subgraph_file.

    Sandbox preloads: entities / entities_by_mid / mid_name_map / get_name(entity) / result_dict.
    On success returns 'ANSWER: [...]'; on error returns [Error] / [CODE_HINT].
    """

    name: str = "execute_code"
    description: str = (
        "Execute Python in a sandbox, loading Python classes from build_subgraph_schema's subgraph_file. "
        "Sandbox preloads: entities / entities_by_mid / mid_name_map / get_name(entity) / result_dict. "
        "On success returns 'ANSWER: [...]'; on error returns [Error] / [CODE_HINT]."
    )
    args_schema: type[BaseModel] = ExecuteCodeInput

    def _run(self, code_lines: List[str], subgraph_file: str) -> str:
        try:
            from ..tools_impl.execute_code import execute_code
            return execute_code(code_lines=code_lines, schema_file=subgraph_file)
        except Exception as e:
            return f"[Error] execute_code failed: {type(e).__name__}: {e}"

    async def _arun(self, code_lines: List[str], subgraph_file: str) -> str:
        return self._run(code_lines=code_lines, subgraph_file=subgraph_file)
