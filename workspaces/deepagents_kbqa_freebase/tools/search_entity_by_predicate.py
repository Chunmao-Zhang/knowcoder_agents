"""SearchEntityByPredicateTool -- LangChain BaseTool wrapper for search_entity_by_predicate.

Look up entity MIDs by predicate (with optional literal value constraint).
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class SearchEntityByPredicateInput(BaseModel):
    """Input schema for search_entity_by_predicate."""
    predicate: str = Field(
        ..., description="Freebase predicate in dot-notation (e.g. 'architecture.structure.floors')."
    )
    semantic_filter: str = Field(
        default="", description="BGE ranking hint -- used to highlight the most relevant entities in a large candidate set."
    )
    value: Any = Field(
        default=None,
        description="Optional literal value constraint (int / float / str / date). When omitted, returns all entities matching the predicate.",
    )
    top_k: int = Field(
        default=50, description="Number of entities to return; default 50, recommended <= 200."
    )


class SearchEntityByPredicateTool(BaseTool):
    """Look up entity MIDs by predicate.

    Given a predicate (from search_predicate) + optional literal value constraint
    + semantic_filter ranking hint, returns (mid, name) pairs.
    The returned MIDs serve as start_mids for build_subgraph_schema.
    """

    name: str = "search_entity_by_predicate"
    description: str = (
        "Look up entity MIDs by predicate. Given a predicate (from search_predicate) + optional literal value constraint "
        "+ semantic_filter ranking hint, returns (mid, name) pairs. The returned MIDs serve as start_mids for build_subgraph_schema."
    )
    args_schema: type[BaseModel] = SearchEntityByPredicateInput

    def _run(
        self,
        predicate: str,
        semantic_filter: str = "",
        value: Any = None,
        top_k: int = 50,
    ) -> str:
        try:
            from ..tools_impl.search_entity_by_predicate import search_entities_by_predicate
            return search_entities_by_predicate(
                predicate=predicate,
                semantic_filter=semantic_filter or None,
                value=value,
                top_k=top_k,
            )
        except Exception as e:
            return f"[Error] search_entity_by_predicate failed: {type(e).__name__}: {e}"

    async def _arun(
        self,
        predicate: str,
        semantic_filter: str = "",
        value: Any = None,
        top_k: int = 50,
    ) -> str:
        return self._run(
            predicate=predicate,
            semantic_filter=semantic_filter,
            value=value,
            top_k=top_k,
        )
