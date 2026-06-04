"""ListPredicatesByEntityTool -- LangChain BaseTool wrapper for list_predicates_by_entity.

Enumerate candidate predicates (outgoing + incoming) on a single entity, ranked by BGE similarity.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class ListPredicatesByEntityInput(BaseModel):
    """Input schema for list_predicates_by_entity."""
    entity_name: str = Field(
        ...,
        description=(
            "Exact entity name string from the active scoped graph runtime, usually copied from "
            "`search_entity` output field `entity_name`."
        ),
    )
    semantic_filter: str = Field(
        default="",
        description=(
            "Optional BGE ranking hint. If omitted, the tool uses a generic relation-discovery hint "
            "for this entity."
        ),
    )
    top_k: int = Field(
        default=30, description="Number of predicates per direction (outgoing / incoming) to return; default 30, recommended <= 100."
    )


class ListPredicatesByEntityTool(BaseTool):
    """Enumerate candidate predicates (outgoing + incoming) on a single entity, ranked by BGE using semantic_filter.

    Includes reachable entity count for each predicate. Must be called before build_subgraph_schema;
    pick <= 20 predicates from the output as the predicates argument for build_subgraph_schema.
    Incoming predicates carry a .r suffix.
    """

    name: str = "list_predicates_by_entity"
    description: str = (
        "Enumerate candidate predicates (outgoing + incoming) on a single entity, ranked by BGE using semantic_filter, "
        "with reachable entity count. Must be called before build_subgraph_schema; "
        "pick <= 20 predicates from the output as the predicates argument for build_subgraph_schema. "
        "Incoming predicates carry a .r suffix."
    )
    args_schema: type[BaseModel] = ListPredicatesByEntityInput

    def _run(self, entity_name: str = "", semantic_filter: str = "", top_k: int = 30) -> str:
        try:
            from ..tools_impl.list_predicates_by_entity import list_predicates_by_entity
            return list_predicates_by_entity(
                entity_name=entity_name,
                semantic_filter=semantic_filter,
                top_k=top_k,
            )
        except Exception as e:
            return f"[Error] list_predicates_by_entity failed: {type(e).__name__}: {e}"

    async def _arun(self, entity_name: str = "", semantic_filter: str = "", top_k: int = 30) -> str:
        return self._run(
            entity_name=entity_name,
            semantic_filter=semantic_filter,
            top_k=top_k,
        )
