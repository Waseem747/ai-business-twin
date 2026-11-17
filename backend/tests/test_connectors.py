"""SQL and Google Sheets connector tests, including read-only enforcement."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from app.connectors.google_sheets import GoogleSheetsConnector, parse_spreadsheet_id
from app.connectors.sql_database import SqlDatabaseConnector, validate_read_query


@pytest.fixture()
def sql_source(tmp_path, monkeypatch):
    path = tmp_path / "analytics.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE campaign (period TEXT, channel TEXT, metric TEXT, value REAL)")
    connection.executemany(
        "INSERT INTO campaign VALUES (?, ?, ?, ?)",
        [
            ("2026-09", "Paid search", "paid_search_spend", 12000),
            ("2026-10", "Paid search", "paid_search_spend", 13500),
            ("2026-10", "Email", "email_revenue", 22000),
        ],
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("TWIN_TEST_SQL_URL", f"sqlite+aiosqlite:///{path.as_posix()}")
    return {
        "connection_env": "TWIN_TEST_SQL_URL",
        "query": "SELECT period, channel, metric, value FROM campaign ORDER BY period",
        "max_rows": 100,
        "default_entity": "marketing",
        "mapping": {
            "entity": "",
            "metric": "metric",
            "period": "period",
            "value": "value",
            "channel": "channel",
            "category": "",
        },
    }


async def test_sql_connector_reads_real_database(sql_source):
    connector = SqlDatabaseConnector(sql_source)
    result = await connector.fetch(None, {})
    assert len(result.facts) == 3
    assert result.facts[0].metric == "paid_search_spend"
    assert result.facts[0].period_start is not None
    assert result.facts[-1].channel == "Email"
    assert result.schema["read_only"] is True
    assert result.schema["dialect"] == "sqlite"


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM campaign",
        "SELECT * FROM campaign; DROP TABLE campaign",
        "UPDATE campaign SET value = 0",
        "PRAGMA table_info(campaign)",
        "WITH x AS (DELETE FROM campaign RETURNING *) SELECT * FROM x",
    ],
)
def test_sql_connector_rejects_write_queries(query):
    with pytest.raises(ValueError):
        validate_read_query(query)


async def test_google_sheet_connector_maps_rows_without_network(monkeypatch):
    connector = GoogleSheetsConnector(
        {
            "spreadsheet_id": "1AbCdEfGhIjKlMnOpQrStUvWxYz",
            "range": "Campaign!A1:D10",
            "default_entity": "marketing",
            "default_metric": "paid_search_revenue",
            "mapping": {
                "period": "Month",
                "value": "Revenue",
                "channel": "Channel",
                "entity": "",
                "metric": "",
                "category": "Category",
            },
        }
    )

    async def fake_values():
        return (
            ["Month", "Channel", "Revenue", "Category"],
            [
                ["2026-09", "Paid search", 48000, "acquisition"],
                ["2026-10", "Paid search", 52000, "acquisition"],
            ],
            "service_account",
        )

    monkeypatch.setattr(connector, "_fetch_values", fake_values)
    result = await connector.fetch(None, {})
    assert len(result.facts) == 2
    assert result.facts[0].value == 48000
    assert result.facts[1].metric == "paid_search_revenue"
    assert result.facts[1].period_start.month == 10
    assert result.schema["auth_mode"] == "service_account"


def test_google_sheet_url_parsing_and_rejection():
    sheet_id = "1AbCdEfGhIjKlMnOpQrStUvWxYz"
    assert parse_spreadsheet_id(f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid=0") == sheet_id
    assert parse_spreadsheet_id(sheet_id) == sheet_id
    with pytest.raises(ValueError):
        parse_spreadsheet_id("not a sheet")


async def test_connector_api_test_and_source_creation(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    path = tmp_path / "api_source.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE metrics (period TEXT, channel TEXT, metric TEXT, value REAL)")
    connection.executemany(
        "INSERT INTO metrics VALUES (?, ?, ?, ?)",
        [("2026-09", "Online", "api_test_metric", 1200), ("2026-10", "Online", "api_test_metric", 1400)],
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("TWIN_TEST_API_SQL_URL", f"sqlite+aiosqlite:///{path.as_posix()}")
    config = {
        "connection_env": "TWIN_TEST_API_SQL_URL",
        "query": "SELECT period, channel, metric, value FROM metrics ORDER BY period",
        "default_entity": "api_test",
        "mapping": {
            "entity": "",
            "metric": "metric",
            "period": "period",
            "value": "value",
            "channel": "channel",
            "category": "",
        },
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/auth/login",
            json={"email": "analyst@northwind.demo", "password": "TwinDemo!2026"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        tested = await client.post(
            "/api/integrations/connectors/test",
            headers=headers,
            json={"kind": "SQL_DATABASE", "config": config},
        )
        assert tested.status_code == 200, tested.text
        assert tested.json()["fact_count"] == 2
        assert tested.json()["sample"][0]["metric"] == "api_test_metric"

        created = await client.post(
            "/api/integrations/sources",
            headers=headers,
            json={"name": "API-created SQL source", "kind": "SQL_DATABASE", "config": config, "sync_now": True},
        )
        assert created.status_code == 200, created.text
        assert created.json()["run"]["status"] == "SUCCEEDED"
        assert created.json()["run"]["records_ingested"] == 2

        rejected = await client.post(
            "/api/integrations/sources",
            headers=headers,
            json={
                "name": "Leaky source",
                "kind": "SQL_DATABASE",
                "config": {**config, "password": "plain-text-should-not-be-accepted"},
            },
        )
        assert rejected.status_code == 422
        assert "secret" in rejected.json()["detail"].lower()
