"""BuildSubgraphSchemaTool -- LangChain BaseTool wrapper for build_subgraph_schema.

Load a generic file-backed graph subgraph and return Python class schema + subgraph_file path.
"""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class BuildSubgraphSchemaInput(BaseModel):
    """Input schema for build_subgraph_schema."""
    start_entity_names: List[str] = Field(
        ...,
        description=(
            "Anchor entity name list. Each value must be an exact entity_name string from search_entity, "
            "search_entity_by_predicate, or a previous execute_code result."
        ),
    )
    predicates: List[str] = Field(
        ...,
        description=(
            "Explicit predicate list (required, selected from list_predicates_by_entity output, max 20). "
            "Incoming predicates use .r suffix."
        ),
    )
    hop: int = Field(
        default=2, description="BFS expansion depth; default 2."
    )


class BuildSubgraphSchemaTool(BaseTool):
    """Load a generic graph subgraph, return Python class schema text + subgraph_file path.

    REQUIRED FLOW: call list_predicates_by_entity first to get candidate predicates, then call this tool
    with predicates=[<selected list>] (max 20). To expand further hops, use intermediate entity names
    collected by the previous execute_code as start_entity_names.
    The subgraph_file path must be passed to execute_code.
    """

    name: str = "build_subgraph_schema"
    description: str = (
        "Load a generic file-backed graph subgraph, return Python class schema text + `# subgraph_file: <path>`. "
        "REQUIRED FLOW: call list_predicates_by_entity first to get candidate predicates, then call this tool "
        "with predicates=[<selected list>] (max 20). To expand further hops, use intermediate entity names "
        "collected by the previous execute_code as start_entity_names. "
        "The subgraph_file path must be passed to execute_code."
    )
    args_schema: type[BaseModel] = BuildSubgraphSchemaInput

    def _run(
        self,
        predicates: List[str],
        start_entity_names: List[str] | None = None,
        hop: int = 2,
    ) -> str:
        try:
            from ..tools_impl.build_subgraph_schema import build_subgraph_schema
            return build_subgraph_schema(
                start_entity_names=start_entity_names or [],
                predicates=predicates,
                hop=hop,
            )
        except Exception as e:
            return f"[Error] build_subgraph_schema failed: {type(e).__name__}: {e}"

    async def _arun(
        self,
        predicates: List[str],
        start_entity_names: List[str] | None = None,
        hop: int = 2,
    ) -> str:
        return self._run(start_entity_names=start_entity_names, predicates=predicates, hop=hop)
