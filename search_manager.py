"""Provider-neutral web search with the blueprint's free-first fallback order."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    provider: str


class SearchManager:
    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Try paid/configured providers first, then the no-key DDG fallback."""
        providers = []
        if os.getenv("TAVILY_API_KEY"):
            providers.append(self._tavily)
        providers.append(self._duckduckgo)
        if os.getenv("SERPER_API_KEY"):
            providers.append(self._serper)

        for provider in providers:
            try:
                results = provider(query, limit)
                if results:
                    return results
            except (OSError, ValueError, KeyError, TimeoutError):
                continue
        return []

    def _tavily(self, query: str, limit: int) -> list[SearchResult]:
        payload = json.dumps(
            {
                "api_key": os.environ["TAVILY_API_KEY"],
                "query": query,
                "search_depth": "basic",
                "max_results": limit,
                "include_answer": False,
            }
        ).encode()
        data = self._request_json(
            "https://api.tavily.com/search", payload, {"Content-Type": "application/json"}
        )
        return [
            SearchResult(item["title"], item["url"], item.get("content", ""), "tavily")
            for item in data.get("results", [])[:limit]
            if item.get("title") and item.get("url")
        ]

    def _duckduckgo(self, query: str, limit: int) -> list[SearchResult]:
        params = urllib.parse.urlencode(
            {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        )
        data = self._request_json(f"https://api.duckduckgo.com/?{params}")
        results = []
        if data.get("AbstractText"):
            results.append(
                SearchResult(
                    data.get("Heading", query),
                    data.get("AbstractURL", "https://duckduckgo.com/"),
                    data["AbstractText"],
                    "duckduckgo",
                )
            )
        for item in data.get("RelatedTopics", []):
            if len(results) >= limit:
                break
            if item.get("Text") and item.get("FirstURL"):
                results.append(SearchResult(item["Text"], item["FirstURL"], item["Text"], "duckduckgo"))
        return results

    def _serper(self, query: str, limit: int) -> list[SearchResult]:
        payload = json.dumps({"q": query, "num": limit}).encode()
        data = self._request_json(
            "https://google.serper.dev/search",
            payload,
            {"Content-Type": "application/json", "X-API-KEY": os.environ["SERPER_API_KEY"]},
        )
        return [
            SearchResult(item["title"], item["link"], item.get("snippet", ""), "serper")
            for item in data.get("organic", [])[:limit]
            if item.get("title") and item.get("link")
        ]

    def _request_json(
        self, url: str, payload: bytes | None = None, headers: dict[str, str] | None = None
    ) -> dict:
        request = urllib.request.Request(url, data=payload, headers=headers or {})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def serialise_results(results: list[SearchResult]) -> list[dict]:
    return [asdict(result) for result in results]
