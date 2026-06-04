"""SearchPredicateTool -- LangChain BaseTool wrapper for search_predicate.

0-TE: vector-search Freebase predicate candidates by semantic similarity.
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class SearchPredicateInput(BaseModel):
    """Input schema for search_predicate."""
    semantic_filter: str = Field(
        ..., description="Natural-language description for BGE ranking -- should directly express the relational semantics in the question."
    )
    top_k: int = Field(
        default=20, description="Number of predicates to return; default 20, recommended <= 50."
    )


class SearchPredicateTool(BaseTool):
    """Vector-search Freebase predicate candidates.

    Returns top_k (predicate / description) pairs.
    Used in 0-TE subtasks to identify predicates first, then use search_entity_by_predicate to look up entity MIDs.
    """

    name: str = "search_predicate"
    description: str = (
        "Vector-search Freebase predicate candidates. Returns top_k (predicate / description) pairs. "
        "Used in 0-TE subtasks to identify predicates first, then use search_entity_by_predicate to look up entity MIDs."
    )
    args_schema: type[BaseModel] = SearchPredicateInput

    def _run(self, semantic_filter: str, top_k: int = 20) -> str:
        try:
            from ..tools_impl.search_predicate import search_predicates
            return search_predicates(semantic_filter=semantic_filter, top_k=top_k)
        except Exception as e:
            return f"[Error] search_predicate failed: {type(e).__name__}: {e}"

    async def _arun(self, semantic_filter: str, top_k: int = 20) -> str:
        return self._run(semantic_filter=semantic_filter, top_k=top_k)
