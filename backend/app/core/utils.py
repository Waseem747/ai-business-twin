"""Small cross-cutting utilities: identifiers, time, hashing."""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import UTC, date, datetime
from typing import Any


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def json_dumps(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True)


def fingerprint(*parts: Any) -> str:
    return hashlib.sha256(json_dumps(parts).encode()).hexdigest()[:32]


def content_hash(value: Any) -> str:
    return hashlib.sha256(json_dumps(value).encode()).hexdigest()


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def money(value: float | None) -> dict[str, Any]:
    return {"value": round(value, 2) if value is not None else None, "currency": "USD"}


def pct(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def sanitize_json(value: Any) -> Any:
    """Recursively convert third-party numeric/array/date objects into JSON-safe values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_json(item) for item in value]
    if hasattr(value, "tolist"):
        try:
            return sanitize_json(value.tolist())
        except Exception:  # noqa: BLE001
            pass
    if hasattr(value, "item"):
        try:
            return sanitize_json(value.item())
        except Exception:  # noqa: BLE001
            pass
    return str(value)
