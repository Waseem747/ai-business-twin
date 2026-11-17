"""Test bootstrap. Environment is configured before application imports."""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix="twin-tests-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(TEST_ROOT / 'test.db').as_posix()}"
os.environ["CHECKPOINT_DB"] = str(TEST_ROOT / "checkpoints.sqlite")
os.environ["STORAGE_DIR"] = str(TEST_ROOT / "storage")
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["DEMO_AUTO_BOOTSTRAP"] = "false"
os.environ["LLM_PROVIDER"] = "deterministic"
os.environ["JWT_SECRET"] = "test-secret-only-not-for-production-123456"
os.environ["APP_ENV"] = "test"

import pytest  # noqa: E402

from app.db import engine, init_db, session_scope  # noqa: E402
from app.services.seed import ensure_demo_environment  # noqa: E402
from app.workflows.checkpointer import close_checkpointer  # noqa: E402
from app.workflows.runner import workflow_runner  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def prepared_database():
    await init_db()
    async with session_scope() as session:
        await ensure_demo_environment(session)
    yield
    await workflow_runner.shutdown()
    await close_checkpointer()
    await engine.dispose()
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


@pytest.fixture()
async def business():
    from sqlalchemy import select

    from app.domain.models import Business

    async with session_scope() as session:
        return (await session.execute(select(Business))).scalars().first()


@pytest.fixture()
def demo_workbook_path() -> Path:
    path = Path(__file__).resolve().parents[1] / "data" / "demo" / "Northwind_Margin_Model.xlsx"
    assert path.exists(), "Demo workbook missing; run scripts/build_demo_workbook.py"
    return path


@pytest.fixture()
async def session():
    async with session_scope() as db:
        yield db
