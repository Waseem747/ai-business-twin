"""CSV and Excel ingestion connector.

Reads tabular files with an explicit column mapping.  Raw bytes are retained
separately by the ingestion service; this connector only parses.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.connectors.base import Connector, Fact, FetchResult


class TabularConnector(Connector):
    kind = "TABULAR"
    version = "1.0"

    async def fetch(self, since: datetime | None, cursor: dict[str, Any]) -> FetchResult:
        path = Path(self.config.get("path", ""))
        if not path.exists():
            raise FileNotFoundError(f"Upload not found: {path.name}")
        mapping = self.config.get("mapping") or {}
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            frame = pd.read_excel(path, sheet_name=self.config.get("sheet", 0))
        elif path.suffix.lower() == ".csv":
            frame = pd.read_csv(path)
        else:
            raise ValueError("Only .csv, .xlsx and .xlsm files are supported")

        facts: list[Fact] = []
        errors: list[dict[str, Any]] = []
        for index, row in frame.iterrows():
            try:
                value = float(row[mapping.get("value", "value")])
            except (KeyError, TypeError, ValueError):
                errors.append({"row": int(index) + 2, "error": "value is missing or not numeric"})
                continue
            period_raw = row.get(mapping.get("period", "period"))
            period = None
            if period_raw is not None and not pd.isna(period_raw):
                try:
                    period = pd.to_datetime(period_raw, utc=True).to_pydatetime()
                except Exception:  # noqa: BLE001
                    errors.append({"row": int(index) + 2, "error": "period is invalid"})
                    continue
            facts.append(
                Fact(
                    entity=str(row.get(mapping.get("entity", "entity"), self.config.get("default_entity", "unknown")) or self.config.get("default_entity", "unknown")),
                    metric=str(row.get(mapping.get("metric", "metric"), self.config.get("default_metric", "value")) or self.config.get("default_metric", "value")),
                    period_start=period,
                    period_end=period,
                    value=value,
                    unit=str(row.get(mapping.get("unit", "unit"), "USD") or "USD"),
                    channel=str(row.get(mapping.get("channel", "channel"), "") or ""),
                    category=str(row.get(mapping.get("category", "category"), "") or ""),
                    payload={"row": int(index) + 2, "source_file": path.name},
                    quality={"uploaded": True},
                )
            )
        return FetchResult(
            facts=facts,
            raw_payload={"file": path.name, "rows": len(frame), "columns": list(frame.columns), "errors": errors[:50]},
            schema={"columns": [str(column) for column in frame.columns], "rows": len(frame)},
            cursor={},
            freshness_at=datetime.now(UTC),
            notes=f"Uploaded tabular file {path.name}",
        )
