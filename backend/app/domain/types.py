"""Timezone-aware datetime type that normalises SQLite storage.

SQLite has no native timezone support; SQLAlchemy otherwise returns naive
datetimes and breaks comparisons with UTC-aware timestamps. This type stores
UTC in the database and always returns timezone-aware UTC values.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(timezone=True)

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            value = value.astimezone(UTC)
            if dialect.name == "sqlite":
                return value.replace(tzinfo=None)
            return value
        return value

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        if isinstance(value, datetime):
            return value.astimezone(UTC)
        return value
