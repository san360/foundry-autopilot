"""Minimal async Azure AI Search query client (Entra ID bearer tokens only, no API keys)."""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

SEARCH_RESOURCE = "https://search.azure.com"
API_VERSION = "2024-07-01"
SEMANTIC_CONFIGURATION = "default"
SELECT_FIELDS = "id,question,answer,client,industry,bid_name,bid_year,section,source_doc,owner,last_reviewed,tags"


class SearchError(Exception):
    def __init__(self, status: int, message: str, code: str = "search_error") -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class SearchAccessDenied(SearchError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(status, message, code="access_denied")


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        message = (body.get("error") or {}).get("message") or response.text
    except ValueError:
        message = response.text
    return str(message or response.reason_phrase)[:300]


class SearchClient:
    def __init__(self, endpoint: str, *, http: Optional[httpx.AsyncClient] = None, timeout: float = 20.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self._http = http
        self._timeout = timeout

    async def search(
        self,
        index: str,
        query: str,
        token: str,
        *,
        top: int = 5,
        semantic: bool = True,
    ) -> list[dict[str, Any]]:
        """Run a query against one index. Raises SearchAccessDenied on 401/403."""
        url = f"{self.endpoint}/indexes/{quote(index, safe='')}/docs/search?api-version={API_VERSION}"
        body: dict[str, Any] = {"search": query, "top": top, "select": SELECT_FIELDS, "count": False}
        if semantic:
            body.update({"queryType": "semantic", "semanticConfiguration": SEMANTIC_CONFIGURATION})
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = await self._post(url, body, headers)
        if response.status_code == 400 and semantic and "semantic" in response.text.lower():
            logger.info("Semantic ranking unavailable on index %s; falling back to keyword search", index)
            body = {k: v for k, v in body.items() if k not in ("queryType", "semanticConfiguration")}
            response = await self._post(url, body, headers)
        if response.status_code in (401, 403):
            raise SearchAccessDenied(response.status_code, _error_message(response))
        if response.status_code == 404:
            raise SearchError(404, f"Index '{index}' was not found.", code="not_found")
        if response.status_code >= 400:
            raise SearchError(response.status_code, _error_message(response))
        results = []
        for doc in (response.json().get("value") or []):
            item = {k: v for k, v in doc.items() if not k.startswith("@")}
            score = doc.get("@search.rerankerScore", doc.get("@search.score"))
            if score is not None:
                item["relevance"] = round(float(score), 3)
            results.append(item)
        return results

    async def _post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        if self._http is not None:
            return await self._http.post(url, json=body, headers=headers)
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            return await http.post(url, json=body, headers=headers)
