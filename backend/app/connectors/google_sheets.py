"""Google Sheets connector.

Auth modes:
1. Service account JSON in an environment variable (private spreadsheets).
2. Google Sheets API key from an environment variable (public spreadsheets).
3. Public CSV export for link-shared/published sheets (no credentials).

The connector only reads. No write scope is requested.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.connectors.base import Connector, FetchResult
from app.connectors.tabular_mapping import rows_to_facts

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"


def parse_spreadsheet_id(value: str) -> str:
    text = (value or "").strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", text)
    if match:
        return match.group(1)
    if re.match(r"^[a-zA-Z0-9-_]{20,}$", text):
        return text
    raise ValueError("A valid Google spreadsheet URL or ID is required")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class GoogleSheetsConnector(Connector):
    kind = "GOOGLE_SHEETS"
    version = "1.0"

    async def fetch(self, since: datetime | None, cursor: dict[str, Any]) -> FetchResult:
        timeout = float(self.config.get("timeout_seconds", 30))
        result = await self._fetch_values()
        headers, rows, auth_mode = result
        facts, rejected = rows_to_facts(headers, rows, self.config, source_note="google_sheets")
        now = datetime.now(UTC)
        return FetchResult(
            facts=facts,
            raw_payload={
                "spreadsheet_id": self.spreadsheet_id,
                "range": self.range,
                "auth_mode": auth_mode,
                "row_count": len(rows),
                "headers": headers,
                "rows": [dict(zip(headers, row)) for row in rows[:500]],
                "mapping_rejections": rejected[:50],
            },
            schema={"columns": headers, "row_count": len(rows), "auth_mode": auth_mode},
            cursor={"fetched_at": now.isoformat()},
            freshness_at=now,
            notes=f"Google Sheets read via {auth_mode}. Read-only scope.",
        )

    @property
    def spreadsheet_id(self) -> str:
        return parse_spreadsheet_id(str(self.config.get("spreadsheet_id") or self.config.get("spreadsheet_url") or ""))

    @property
    def range(self) -> str:
        return str(self.config.get("range") or self.config.get("sheet_name") or "")

    async def _fetch_values(self) -> tuple[list[str], list[list[Any]], str]:
        service_account_env = self.config.get("service_account_env") or "GOOGLE_SERVICE_ACCOUNT_JSON"
        api_key_env = self.config.get("api_key_env") or "GOOGLE_SHEETS_API_KEY"
        service_account_raw = os.getenv(str(service_account_env)) if service_account_env else None
        api_key = os.getenv(str(api_key_env)) if api_key_env else None
        if service_account_raw:
            rows = await self._fetch_with_service_account(service_account_raw)
            auth_mode = "service_account"
        elif api_key:
            rows = await self._fetch_with_api_key(api_key)
            auth_mode = "api_key"
        else:
            rows = await self._fetch_public_csv()
            auth_mode = "public_csv_export"
        if not rows:
            raise ValueError("Google Sheet returned no rows")
        headers = [str(cell) if cell is not None else f"column_{index + 1}" for index, cell in enumerate(rows[0])]
        return headers, [list(row) for row in rows[1:]], auth_mode

    def _api_range(self) -> str:
        return self.range or "A:Z"

    async def _fetch_with_api_key(self, api_key: str) -> list[list[Any]]:
        url = f"{SHEETS_API}/{self.spreadsheet_id}/values/{quote(self._api_range(), safe='!')}"
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                url,
                params={"majorDimension": "ROWS", "valueRenderOption": "UNFORMATTED_VALUE", "key": api_key},
            )
            if response.status_code != 200:
                raise ValueError(f"Google Sheets API returned HTTP {response.status_code}: {response.text[:300]}")
            return response.json().get("values", [])

    async def _fetch_with_service_account(self, raw: str) -> list[list[Any]]:
        credentials = self._load_service_account(raw)
        token = await self._service_account_token(credentials)
        url = f"{SHEETS_API}/{self.spreadsheet_id}/values/{quote(self._api_range(), safe='!')}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                url,
                params={"majorDimension": "ROWS", "valueRenderOption": "UNFORMATTED_VALUE"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code != 200:
                raise ValueError(f"Google Sheets API returned HTTP {response.status_code} for service-account access")
            return response.json().get("values", [])

    def _load_service_account(self, raw: str) -> dict[str, Any]:
        text = raw.strip()
        if not text.startswith("{"):
            if os.path.exists(text):
                with open(text, encoding="utf-8") as handle:
                    text = handle.read()
            else:
                raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON must be JSON or a readable file path")
        return json.loads(text)

    async def _service_account_token(self, credentials: dict[str, Any]) -> str:
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iss": credentials["client_email"],
            "scope": SHEETS_SCOPE,
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        }
        signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}.{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"
        private_key = serialization.load_pem_private_key(credentials["private_key"].encode(), password=None)
        signature = private_key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        assertion = f"{signing_input}.{_b64url(signature)}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                TOKEN_URL,
                data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
            )
            if response.status_code != 200:
                raise ValueError(f"Google service-account token exchange failed (HTTP {response.status_code})")
            return response.json()["access_token"]

    async def _fetch_public_csv(self) -> list[list[Any]]:
        params: dict[str, str] = {"tqx": "out:csv"}
        sheet_name = self.config.get("sheet_name")
        gid = self.config.get("gid")
        if sheet_name:
            params["sheet"] = str(sheet_name)
        elif gid is not None:
            params["gid"] = str(gid)
        url = f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}/gviz/tq"
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                raise ValueError(
                    "Google Sheet is not publicly readable. Configure GOOGLE_SHEETS_API_KEY or "
                    "GOOGLE_SERVICE_ACCOUNT_JSON for private access."
                )
            text = response.text
        if text.lstrip().startswith("<"):
            raise ValueError("Google returned an HTML page instead of CSV; the sheet is not published/link-shared")
        reader = csv.reader(io.StringIO(text))
        return [row for row in reader]
