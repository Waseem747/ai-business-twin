"""Connector contract for every business data source.

A connector only fetches and shapes data.  Validation, normalisation,
deduplication and lineage are handled by the ingestion service so behaviour is
identical across REST, CSV, Excel and simulated sources.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Fact:
    entity: str
    metric: str
    period_start: datetime | None
    period_end: datetime | None
    value: float | None
    unit: str = "USD"
    currency: str = "USD"
    channel: str = ""
    category: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    facts: list[Fact]
    raw_payload: dict[str, Any]
    schema: dict[str, Any]
    cursor: dict[str, Any] = field(default_factory=dict)
    freshness_at: datetime | None = None
    notes: str = ""
    simulated: bool = False


class Connector(ABC):
    kind: str = "BASE"
    version: str = "1.0"
    simulated: bool = False

    def __init__(self, source_config: dict[str, Any] | None = None) -> None:
        self.config = source_config or {}

    @abstractmethod
    async def fetch(self, since: datetime | None, cursor: dict[str, Any]) -> FetchResult:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "version": self.version, "simulated": self.simulated}
