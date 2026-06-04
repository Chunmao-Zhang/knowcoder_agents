"""SearchEntityTool -- entity linking/search for KBQA topic mentions."""

from __future__ import annotations

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class SearchEntityInput(BaseModel):
    """Input schema for search_entity."""

    query: str = Field(
        ...,
        description=(
            "Natural-language entity mention, title, label, short descriptive phrase, "
            "or exact entity name string from the active scoped graph runtime."
        ),
    )
    top_k: int = Field(default=10, description="Number of candidates to return; default 10.")
    semantic_filter: str = Field(
        default="",
        description="Optional context appended to the entity vector query for semantic reranking.",
    )
    type_filter: str = Field(
        default="",
        description="Optional type hint reserved for future typed entity linking.",
    )


class SearchEntityTool(BaseTool):
    """Search canonical KG entities by mention before predicate exploration."""

    name: str = "search_entity"
    description: str = (
        "Search canonical KG entities by a natural-language mention/title/entity name. "
        "Use this first when a question names an entity but does not provide the exact graph entity name. "
        "Exact matching is tried first, then vector similarity over prepared entity documents. "
        "Returns entity_name, display_name, score, matched_by, and evidence."
    )
    args_schema: type[BaseModel] = SearchEntityInput

    def _run(
        self,
        query: str,
        top_k: int = 10,
        semantic_filter: str = "",
        type_filter: str = "",
    ) -> str:
        try:
            from ..tools_impl.search_entity import search_entity

            return search_entity(
                query=query,
                top_k=top_k,
                semantic_filter=semantic_filter,
                type_filter=type_filter,
            )
        except Exception as e:
            return f"[Error] search_entity failed: {type(e).__name__}: {e}"

    async def _arun(
        self,
        query: str,
        top_k: int = 10,
        semantic_filter: str = "",
        type_filter: str = "",
    ) -> str:
        return self._run(
            query=query,
            top_k=top_k,
            semantic_filter=semantic_filter,
            type_filter=type_filter,
        )
