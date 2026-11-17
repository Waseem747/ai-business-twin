"""Shared mapping from tabular SQL / Google Sheets results into business facts."""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, time
from typing import Any

import pandas as pd

from app.connectors.base import Fact


def _period_bounds(value: Any) -> tuple[datetime | None, datetime | None]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None
    if isinstance(value, datetime):
        start = value if value.tzinfo else value.replace(tzinfo=UTC)
        return start, start
    if isinstance(value, date):
        start = datetime.combine(value, time.min, tzinfo=UTC)
        return start, start + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Google Sheets / Excel serial date.
        if 20_000 <= float(value) <= 80_000:
            start = datetime(1899, 12, 30, tzinfo=UTC) + pd.Timedelta(days=float(value))
            return start, start + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        return None, None
    text = str(value).strip()
    if len(text) == 7 and text[4] == "-":
        try:
            start = datetime(int(text[:4]), int(text[5:]), 1, tzinfo=UTC)
            end = start + pd.offsets.MonthEnd(0) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            return start, end
        except ValueError:
            return None, None
    parsed = pd.to_datetime(text, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None, None
    start = parsed.to_pydatetime()
    end = start + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    return start, end


def _row_value(row: dict[str, Any], column: str | None) -> Any:
    if not column:
        return None
    return row.get(column)


def rows_to_facts(
    headers: list[str],
    rows: list[list[Any]],
    config: dict[str, Any],
    *,
    source_note: str = "",
) -> tuple[list[Fact], list[dict[str, Any]]]:
    mapping = config.get("mapping") or {}
    default_entity = str(config.get("default_entity") or "external")
    default_metric = str(config.get("default_metric") or "value")
    default_unit = str(config.get("default_unit") or "USD")
    value_column = mapping.get("value") or config.get("value_column") or "value"
    period_column = mapping.get("period") or config.get("period_column") or "period"
    facts: list[Fact] = []
    rejected: list[dict[str, Any]] = []

    for index, raw_row in enumerate(rows):
        if not raw_row or all(cell in (None, "") for cell in raw_row):
            continue
        row = {str(header): raw_row[position] if position < len(raw_row) else None for position, header in enumerate(headers)}
        raw_value = _row_value(row, value_column)
        value: float | None
        try:
            value = float(raw_value) if raw_value not in (None, "") else None
            if value is not None and not math.isfinite(value):
                value = None
        except (TypeError, ValueError):
            value = None
        period_start, period_end = _period_bounds(_row_value(row, period_column))
        entity = str(_row_value(row, mapping.get("entity")) or default_entity)
        metric = str(_row_value(row, mapping.get("metric")) or default_metric)
        channel = str(_row_value(row, mapping.get("channel")) or "")
        category = str(_row_value(row, mapping.get("category")) or "")
        unit = str(_row_value(row, mapping.get("unit")) or default_unit)
        currency = str(_row_value(row, mapping.get("currency")) or "USD")
        if value is None:
            rejected.append({"row": index + 2, "error": "value_missing_or_not_numeric", "column": value_column})
        if period_start is None:
            rejected.append({"row": index + 2, "error": "period_missing_or_invalid", "column": period_column})
        facts.append(
            Fact(
                entity=entity,
                metric=metric,
                period_start=period_start,
                period_end=period_end,
                value=value,
                unit=unit,
                currency=currency,
                channel=channel,
                category=category,
                payload={
                    "row": index + 2,
                    "source": source_note,
                    "raw": {header: _json_scalar(row.get(header)) for header in headers},
                },
                quality={"external": True, "mapping_version": 1},
            )
        )
    return facts, rejected


def _json_scalar(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
