"""Read-only SQL database connector.

Supports PostgreSQL (asyncpg), MySQL (asyncmy) and SQLite (aiosqlite) through
SQLAlchemy async URLs. Credentials are resolved from an environment variable,
not stored in source configuration. Production should use a read-only database
role and a secret manager.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.connectors.base import Connector, Fact, FetchResult
from app.connectors.tabular_mapping import rows_to_facts

FORBIDDEN_SQL = re.compile(
    r"(?i)\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|merge|copy|call|vacuum|attach|detach|pragma|execute)\b"
)


def validate_read_query(query: str) -> str:
    cleaned = " ".join((query or "").split()).strip().rstrip(";")
    if not cleaned:
        raise ValueError("SQL query is required")
    if ";" in cleaned:
        raise ValueError("Only a single read-only SQL statement is allowed")
    if not re.match(r"(?is)^(select|with)\b", cleaned):
        raise ValueError("Only SELECT / WITH read-only queries are allowed")
    if FORBIDDEN_SQL.search(cleaned):
        raise ValueError("Query contains a forbidden write or administrative keyword")
    return cleaned


def _async_url(raw: str) -> str:
    url = raw.strip()
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    elif url.startswith("mysql://"):
        url = "mysql+asyncmy://" + url[len("mysql://") :]
    elif url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite://"):
        url = "sqlite+aiosqlite://" + url[len("sqlite://") :]
    return url


class SqlDatabaseConnector(Connector):
    kind = "SQL_DATABASE"
    version = "1.0"

    async def fetch(self, since: datetime | None, cursor: dict[str, Any]) -> FetchResult:
        timeout = float(self.config.get("timeout_seconds", 30))
        return await asyncio.wait_for(self._fetch(since), timeout=timeout)

    async def _fetch(self, since: datetime | None) -> FetchResult:
        query = validate_read_query(str(self.config.get("query") or ""))
        connection_env = self.config.get("connection_env")
        if connection_env:
            raw_url = os.getenv(str(connection_env))
            if not raw_url:
                raise ValueError(
                    f"Environment variable '{connection_env}' is not configured. "
                    "Set it in the backend environment or secret manager."
                )
        else:
            raw_url = self.config.get("connection_url")
            if not (self.config.get("demo") and raw_url and str(raw_url).startswith("sqlite+aiosqlite://")):
                raise ValueError("A connection_env secret reference is required for SQL sources")
        max_rows = int(self.config.get("max_rows", 1000))
        if not 1 <= max_rows <= 10_000:
            raise ValueError("max_rows must be between 1 and 10000")
        engine = create_async_engine(_async_url(str(raw_url)), pool_pre_ping=True)
        started = datetime.now(UTC)
        try:
            async with engine.connect() as connection:
                dialect = engine.dialect.name
                if dialect == "sqlite":
                    await connection.execute(text("PRAGMA query_only=ON"))
                    result = await connection.execute(text(query))
                    columns = [str(column) for column in result.keys()]
                    rows = result.mappings().fetchmany(max_rows + 1)
                    await connection.rollback()
                else:
                    transaction = await connection.begin()
                    if dialect in {"postgresql", "mysql"}:
                        await connection.execute(text("SET TRANSACTION READ ONLY"))
                    result = await connection.execute(text(query))
                    columns = [str(column) for column in result.keys()]
                    rows = result.mappings().fetchmany(max_rows + 1)
                    await transaction.rollback()
        finally:
            await engine.dispose()
        if len(rows) > max_rows:
            raise ValueError(f"Query returned more than the {max_rows} row safety limit")
        row_dicts = [dict(row) for row in rows]
        if not row_dicts and self.config.get("demo"):
            return FetchResult(
                facts=[],
                raw_payload={"query": query, "rows": [], "row_count": 0},
                schema={"columns": columns, "row_count": 0},
                freshness_at=datetime.now(UTC),
                notes="Read-only SQL query returned no rows.",
            )
        facts, rejected = rows_to_facts(columns, [[row[column] for column in columns] for row in row_dicts], self.config, source_note="sql")
        return FetchResult(
            facts=facts,
            raw_payload={
                "executed_at": started.isoformat(),
                "query_hash": __import__("hashlib").sha256(query.encode()).hexdigest(),
                "columns": columns,
                "row_count": len(row_dicts),
                "rows": self._raw_rows(columns, row_dicts),
                "mapping_rejections": rejected[:50],
            },
            schema={"columns": columns, "row_count": len(row_dicts), "read_only": True, "dialect": engine.dialect.name},
            cursor={"last_run": started.isoformat()},
            freshness_at=datetime.now(UTC),
            notes="Read-only SQL database query executed with a read-only transaction.",
        )

    def _raw_rows(self, columns: list[str], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from app.connectors.tabular_mapping import _json_scalar

        return [{column: _json_scalar(row.get(column)) for column in columns} for row in rows[:500]]
