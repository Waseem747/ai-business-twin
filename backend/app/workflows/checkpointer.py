"""Durable LangGraph checkpointing.

Uses AsyncSqliteSaver by default. In PostgreSQL deployments the checkpoint
volume can be swapped for langgraph-checkpoint-postgres without changing graph
code. If the durable saver cannot be opened the runner falls back to an
in-memory saver and logs a visible warning (never silently).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("business_twin.checkpoints")
_saver: Any = None
_context_manager: Any = None
_durable = False


async def get_checkpointer() -> Any:
    global _saver, _context_manager, _durable
    if _saver is not None:
        return _saver
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        Path(settings.checkpoint_db).parent.mkdir(parents=True, exist_ok=True)
        _context_manager = AsyncSqliteSaver.from_conn_string(settings.checkpoint_db)
        _saver = await _context_manager.__aenter__()
        _durable = True
    except Exception as exc:  # noqa: BLE001
        from langgraph.checkpoint.memory import MemorySaver

        logger.warning("Durable checkpoint saver unavailable; using MemorySaver: %s", exc)
        _saver = MemorySaver()
        _durable = False
    return _saver


async def close_checkpointer() -> None:
    global _saver, _context_manager
    if _context_manager is not None:
        await _context_manager.__aexit__(None, None, None)
    _saver = None
    _context_manager = None


def checkpoint_is_durable() -> bool:
    return _durable
