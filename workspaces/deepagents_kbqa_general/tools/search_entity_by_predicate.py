"""SearchEntityByPredicateTool -- LangChain BaseTool wrapper for search_entity_by_predicate.

Look up entity names by predicate (with optional value constraint).
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class SearchEntityByPredicateInput(BaseModel):
    """Input schema for search_entity_by_predicate."""
    predicate: str = Field(
        ...,
        description=(
            "Predicate from the active graph. Incoming predicates may use the .r suffix. "
            "For entity-grounded traversal, prefer predicates exactly as shown by list_predicates_by_entity."
        ),
    )
    semantic_filter: str = Field(
        default="", description="BGE ranking hint -- used to highlight the most relevant entities in a large candidate set."
    )
    value: Any = Field(
        default=None,
        description=(
            "Optional value/entity constraint. The tool first applies the original literal-style constraint, "
            "then falls back to graph traversal from this value if no rows match."
        ),
    )
    top_k: int = Field(
        default=50, description="Number of entities to return; default 50, recommended <= 200."
    )


class SearchEntityByPredicateTool(BaseTool):
    """Look up entity names by predicate.

    Given a predicate (from search_predicate) + optional literal value constraint
    + semantic_filter ranking hint, returns (entity_name, display_name) pairs.
    The returned entity names are copied into build_subgraph_schema's start_entity_names argument.
    """

    name: str = "search_entity_by_predicate"
    description: str = (
        "Look up entity names by predicate. Given a predicate (from search_predicate/list_predicates_by_entity) "
        "+ optional value/entity constraint + semantic_filter ranking hint, returns (entity_name, display_name) pairs. "
        "If value is an entity and the first lookup is empty, the tool also tries the opposite endpoint as traversal. "
        "Copy the returned entity_name strings into build_subgraph_schema."
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
