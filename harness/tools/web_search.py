"""web_search 工具

通用网页搜索，调用 Serper API。
"""

from __future__ import annotations

import json
import os

import httpx
from langchain_core.tools import tool


@tool
def web_search(query: str, num_results: int = 5) -> str:
    """Search the web and return top results with title, link, and snippet.

    Args:
        query: Search query string.
        num_results: Number of results to return (default 5).
    """
    api_key = os.environ.get("SERPER_API_KEY", "")
    if not api_key:
        return json.dumps({"error": "SERPER_API_KEY not set"}, ensure_ascii=False)

    payload = {"q": query, "num": num_results}
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}

    try:
        resp = httpx.post(
            "https://google.serper.dev/search",
            json=payload,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return json.dumps({"error": f"Search failed: {e}"}, ensure_ascii=False)

    data = resp.json()
    organic = data.get("organic", [])[:num_results]
    results = [
        {
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        }
        for item in organic
    ]
    return json.dumps({"query": query, "results": results}, ensure_ascii=False)
