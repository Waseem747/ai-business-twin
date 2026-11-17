"""Generic REST connector with pagination, rate limiting and retries.

Configuration example::

    {
      "base_url": "https://api.example.com",
      "auth_env": "EXAMPLE_API_TOKEN",
      "pagination": {"type": "page", "page_param": "page", "size_param": "per_page", "size": 100},
      "records_path": "data",
      "mapping": {
         "period": "occurred_at",
         "value": "amount",
         "entity": "revenue",
         "metric": "revenue",
         "channel": "channel"
      }
    }

No credentials are stored in the connector config; tokens are read from the
environment (or the encrypted credential store in a later phase).
"""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.connectors.base import Connector, Fact, FetchResult


class RestConnector(Connector):
    kind = "REST"
    version = "1.0"

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "ai-business-twin/0.1"}
        auth_env = self.config.get("auth_env")
        if auth_env and os.getenv(auth_env):
            headers["Authorization"] = f"Bearer {os.getenv(auth_env)}"
        headers.update(self.config.get("headers") or {})
        return headers

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError,)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _request(self, client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await client.get(url, params=params)
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "2"))
            await asyncio.sleep(min(retry_after, 10))
            raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        response.raise_for_status()
        return response.json()

    async def fetch(self, since: datetime | None, cursor: dict[str, Any]) -> FetchResult:
        base_url = (self.config.get("base_url") or "").rstrip("/")
        if not base_url:
            raise ValueError("REST connector requires config.base_url")
        endpoint = self.config.get("path", "")
        mapping = self.config.get("mapping") or {}
        pagination = self.config.get("pagination") or {"type": "none"}
        records_path = self.config.get("records_path", "")
        page = int(cursor.get("page", 1))
        page_size = int(pagination.get("size", 100))
        max_pages = int(self.config.get("max_pages", 20))
        facts: list[Fact] = []
        raw_pages: list[Any] = []
        started = datetime.now(UTC)

        async with httpx.AsyncClient(base_url=base_url, headers=self._auth_headers(), timeout=20) as client:
            while page <= max_pages:
                params: dict[str, Any] = dict(self.config.get("params") or {})
                if since:
                    params.setdefault(self.config.get("since_param", "updated_since"), since.isoformat())
                if pagination.get("type") == "page":
                    params[pagination.get("page_param", "page")] = page
                    params[pagination.get("size_param", "per_page")] = page_size
                elif pagination.get("type") == "offset":
                    params[pagination.get("offset_param", "offset")] = (page - 1) * page_size
                    params[pagination.get("limit_param", "limit")] = page_size
                elif pagination.get("type") == "cursor" and cursor.get("next_cursor"):
                    params["cursor"] = cursor["next_cursor"]

                payload = await self._request(client, endpoint, params)
                raw_pages.append(payload)
                records = payload
                for key in records_path.split("."):
                    if key:
                        records = records.get(key, []) if isinstance(records, dict) else []
                if not isinstance(records, list):
                    records = []
                for record in records:
                    fact = self._map_record(record, mapping)
                    if fact:
                        facts.append(fact)
                if not records or pagination.get("type") == "none":
                    break
                if len(records) < page_size:
                    break
                if pagination.get("type") == "cursor":
                    next_cursor = payload.get("next_cursor") if isinstance(payload, dict) else None
                    if not next_cursor:
                        break
                    cursor["next_cursor"] = next_cursor
                page += 1
                await asyncio.sleep(float(self.config.get("request_interval_seconds", 0.2)))

        now = datetime.now(UTC)
        return FetchResult(
            facts=facts,
            raw_payload={"pages": raw_pages, "fetched_at": now.isoformat(), "endpoint": endpoint},
            schema={"record_count": len(facts), "mapping": mapping},
            cursor={"page": page, **({"next_cursor": cursor["next_cursor"]} if cursor.get("next_cursor") else {})},
            freshness_at=now,
            notes="Live REST retrieval",
        )

    def _map_record(self, record: dict[str, Any], mapping: dict[str, Any]) -> Fact | None:
        def pick(field: str | None) -> Any:
            return record.get(field) if field else None

        try:
            value = float(pick(mapping.get("value", "value")))
        except (TypeError, ValueError):
            return None
        period = pick(mapping.get("period", "period"))
        period_start = None
        if period:
            try:
                period_start = datetime.fromisoformat(str(period).replace("Z", "+00:00"))
            except ValueError:
                period_start = None
        return Fact(
            entity=str(mapping.get("entity") or record.get("entity") or "unknown"),
            metric=str(mapping.get("metric") or record.get("metric") or "value"),
            period_start=period_start,
            period_end=period_start,
            value=value,
            unit=str(mapping.get("unit") or record.get("unit") or "USD"),
            channel=str(pick(mapping.get("channel")) or ""),
            category=str(pick(mapping.get("category")) or ""),
            payload={"source_record": record},
            quality={"live": True},
        )


class GraphQLConnector(Connector):
    kind = "GRAPHQL"
    version = "1.0"

    async def fetch(self, since: datetime | None, cursor: dict[str, Any]) -> FetchResult:
        base_url = self.config.get("base_url")
        query = self.config.get("query")
        if not base_url or not query:
            raise ValueError("GraphQL connector requires base_url and query")
        headers = {"Content-Type": "application/json"}
        auth_env = self.config.get("auth_env")
        if auth_env and os.getenv(auth_env):
            headers["Authorization"] = f"Bearer {os.getenv(auth_env)}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                base_url,
                json={"query": query, "variables": self.config.get("variables") or {}},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        return FetchResult(
            facts=[],
            raw_payload=payload,
            schema={"graphql": True},
            freshness_at=datetime.now(UTC),
            notes="GraphQL payload retrieved; field mapping required before facts are created",
        )
