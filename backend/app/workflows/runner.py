"""Workflow runner: starts LangGraph workflows, persists state, handles interrupts/resume."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command
from sqlalchemy import select

from app.core.utils import new_id, sanitize_json, utcnow
from app.db import session_scope
from app.domain.models import Business, WorkflowRun, WorkflowStep
from app.workflows.checkpointer import get_checkpointer
from app.workflows.graphs import GRAPH_BUILDERS

logger = logging.getLogger("business_twin.workflows")


def _json_safe(value: Any) -> Any:
    return sanitize_json(json.loads(json.dumps(value, default=str)))


class WorkflowRunner:
    def __init__(self) -> None:
        self._graphs: dict[str, Any] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._active: set[str] = set()

    async def _graph(self, workflow: str) -> Any:
        if workflow not in self._graphs:
            builder = GRAPH_BUILDERS.get(workflow)
            if not builder:
                raise ValueError(f"Unknown workflow '{workflow}'")
            checkpointer = await get_checkpointer()
            self._graphs[workflow] = builder().compile(checkpointer=checkpointer)
        return self._graphs[workflow]

    async def start(
        self,
        session: Any,
        *,
        business: Business,
        workflow: str,
        inputs: dict[str, Any],
        actor: str,
        trigger: str = "MANUAL",
    ) -> WorkflowRun:
        run_id = new_id("wf")
        run = WorkflowRun(
            id=run_id,
            business_id=business.id,
            workflow=workflow,
            status="RUNNING",
            thread_id=run_id,
            trigger=trigger,
            state={},
            started_at=utcnow(),
            initiated_by=actor,
        )
        session.add(run)
        await session.flush()
        # The run row must be visible to the background task's fresh session.
        await session.commit()
        initial_state = {
            **inputs,
            "run_id": run_id,
            "business_id": business.id,
            "workflow": workflow,
            "actor": actor,
            "trigger": trigger,
            "completed_nodes": inputs.get("completed_nodes", []),
        }
        self._tasks[run_id] = asyncio.create_task(self._execute(run_id, initial_state))
        return run

    async def resume(self, run_id: str, payload: dict[str, Any]) -> None:
        if run_id in self._active:
            raise ValueError("Workflow is already running")
        self._tasks[run_id] = asyncio.create_task(self._execute(run_id, None, resume=payload))

    async def wait(self, run_id: str, timeout: float = 120.0) -> None:
        task = self._tasks.get(run_id)
        if task:
            await asyncio.wait_for(task, timeout=timeout)

    async def _execute(self, run_id: str, initial_state: dict[str, Any] | None, resume: Any = None) -> None:
        self._active.add(run_id)
        try:
            async with session_scope() as session:
                run = await session.get(WorkflowRun, run_id)
                if not run:
                    raise ValueError("Workflow run not found")
                workflow = run.workflow
                thread_id = run.thread_id
                run.status = "RUNNING"
                run.error = None
            graph = await self._graph(workflow)
            config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 80}
            stream_input: Any = Command(resume=resume) if resume is not None else initial_state
            interrupted: dict[str, Any] | None = None
            async for chunk in graph.astream(stream_input, config=config, stream_mode="updates"):
                if isinstance(chunk, dict) and "__interrupt__" in chunk:
                    interrupts = chunk["__interrupt__"]
                    if interrupts:
                        raw = interrupts[0]
                        interrupted = getattr(raw, "value", raw)
                await self._sync_state(run_id, graph, config, interrupted is not None)
            final_snapshot = await graph.aget_state(config)
            values = _json_safe(final_snapshot.values)
            status = values.get("status")
            async with session_scope() as session:
                run = await session.get(WorkflowRun, run_id)
                if interrupted:
                    interrupt_type = (interrupted or {}).get("type", "approval")
                    run.status = (
                        "WAITING_HUMAN_REVIEW" if interrupt_type == "audit_escalation" else "WAITING_APPROVAL"
                    )
                    if interrupt_type == "excel_conversion_approval":
                        run.summary = f"Excel conversion approval required: {interrupted.get('filename', '')}"
                    else:
                        run.summary = f"Human approval required: {interrupted.get('title', '')}"
                    run.state = values
                elif status == "FAILED" or values.get("errors"):
                    run.status = "FAILED"
                    run.error = "; ".join(values.get("errors") or []) or "Workflow reported failure"
                    run.finished_at = utcnow()
                    run.state = values
                    run.summary = values.get("summary", run.error)
                else:
                    run.status = "COMPLETED"
                    run.finished_at = utcnow()
                    run.state = values
                    run.summary = values.get("summary") or "Workflow completed."
                await session.flush()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Workflow %s failed", run_id)
            async with session_scope() as session:
                run = await session.get(WorkflowRun, run_id)
                if run:
                    run.status = "FAILED"
                    run.error = f"{type(exc).__name__}: {exc}"[:2000]
                    run.finished_at = utcnow()
                    run.summary = "Workflow failed; see error."
                    session.add(
                        WorkflowStep(
                            run_id=run.id,
                            node="runner",
                            status="FAILED",
                            summary=run.error,
                            payload={},
                            finished_at=utcnow(),
                        )
                    )
                    await session.flush()
        finally:
            self._active.discard(run_id)

    async def _sync_state(self, run_id: str, graph: Any, config: dict[str, Any], interrupted: bool) -> None:
        snapshot = await graph.aget_state(config)
        values = _json_safe(snapshot.values)
        async with session_scope() as session:
            run = await session.get(WorkflowRun, run_id)
            if not run:
                return
            run.state = values
            run.summary = values.get("summary", run.summary or "")
            if interrupted:
                run.status = "WAITING_APPROVAL"
            elif snapshot.next:
                run.status = "RUNNING"
            await session.flush()

    async def list_runs(self, session: Any, business_id: str, workflow: str | None = None, limit: int = 50) -> list[WorkflowRun]:
        query = select(WorkflowRun).where(WorkflowRun.business_id == business_id)
        if workflow:
            query = query.where(WorkflowRun.workflow == workflow)
        result = await session.execute(query.order_by(WorkflowRun.started_at.desc()).limit(limit))
        return list(result.scalars().all())

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()


workflow_runner = WorkflowRunner()
