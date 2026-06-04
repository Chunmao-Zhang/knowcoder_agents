"""BuildSubgraphSchemaTool -- LangChain BaseTool wrapper for build_subgraph_schema.

Load a Freebase subgraph and return Python class schema + subgraph_file path.
"""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class BuildSubgraphSchemaInput(BaseModel):
    """Input schema for build_subgraph_schema."""
    start_mids: List[str] = Field(
        ...,
        description=(
            "Anchor MID list. Hop 1 uses topic entities or MIDs from search_entity_by_predicate; "
            "Hop 2+ uses intermediate MIDs collected by the previous execute_code call."
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
    """Load a Freebase subgraph, return Python class schema text + subgraph_file path.

    REQUIRED FLOW: call list_predicates_by_entity first to get candidate predicates, then call this tool
    with predicates=[<selected list>] (max 20). To expand further hops, use intermediate MIDs
    collected by the previous execute_code as start_mids.
    The subgraph_file path must be passed to execute_code.
    """

    name: str = "build_subgraph_schema"
    description: str = (
        "Load a Freebase subgraph, return Python class schema text + `# subgraph_file: <path>`. "
        "REQUIRED FLOW: call list_predicates_by_entity first to get candidate predicates, then call this tool "
        "with predicates=[<selected list>] (max 20). To expand further hops, use intermediate MIDs "
        "collected by the previous execute_code as start_mids. "
        "The subgraph_file path must be passed to execute_code."
    )
    args_schema: type[BaseModel] = BuildSubgraphSchemaInput

    def _run(
        self,
        start_mids: List[str],
        predicates: List[str],
        hop: int = 2,
    ) -> str:
        try:
            from ..tools_impl.build_subgraph_schema import build_subgraph_schema
            return build_subgraph_schema(
                start_mids=start_mids,
                predicates=predicates,
                hop=hop,
            )
        except Exception as e:
            return f"[Error] build_subgraph_schema failed: {type(e).__name__}: {e}"

    async def _arun(
        self,
        start_mids: List[str],
        predicates: List[str],
        hop: int = 2,
    ) -> str:
        return self._run(start_mids=start_mids, predicates=predicates, hop=hop)
