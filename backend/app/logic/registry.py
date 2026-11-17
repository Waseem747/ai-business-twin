"""Business rule registry: versioning, testing, approval and execution."""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.sandbox import run_sandboxed, run_tests
from app.domain.enums import RuleStatus
from app.domain.models import BusinessRule, RuleExecution, RuleVersion
from app.logic.expressions import FormulaError, evaluate_formula
from app.logic.seed_rules import SEED_RULES


class RuleRegistry:
    async def seed(self, session: AsyncSession, business_id: str | None) -> list[BusinessRule]:
        existing_result = await session.execute(
            select(BusinessRule.key).where(BusinessRule.business_id == business_id)
        )
        existing = set(existing_result.scalars().all())
        created: list[BusinessRule] = []
        for spec in SEED_RULES:
            if spec["key"] in existing:
                continue
            rule = BusinessRule(
                business_id=business_id,
                key=spec["key"],
                name=spec["name"],
                description=spec["description"],
                category=spec["category"],
                source="PYTHON",
                code=spec["code"],
                input_schema=spec["input_schema"],
                output_schema=spec["output_schema"],
                version=1,
                dependencies=[],
                execution_frequency=spec["frequency"],
                tests=spec["tests"],
                status=RuleStatus.ACTIVE,
                approved_by="platform",
                excel_lineage={},
            )
            session.add(rule)
            await session.flush()
            session.add(
                RuleVersion(
                    rule_id=rule.id,
                    version=1,
                    code=rule.code,
                    tests=rule.tests,
                    status=RuleStatus.ACTIVE,
                    changed_by="platform",
                    changelog="Seeded platform rule",
                )
            )
            created.append(rule)
        await session.flush()
        return created

    async def list_rules(self, session: AsyncSession, business_id: str) -> list[BusinessRule]:
        result = await session.execute(
            select(BusinessRule)
            .where(BusinessRule.business_id == business_id)
            .order_by(BusinessRule.category, BusinessRule.name)
        )
        return list(result.scalars().all())

    async def get(self, session: AsyncSession, rule_id: str, business_id: str) -> BusinessRule:
        rule = await session.get(BusinessRule, rule_id)
        if not rule or rule.business_id != business_id:
            raise NotFoundError("Business rule not found")
        return rule

    async def get_active(self, session: AsyncSession, business_id: str, key: str) -> BusinessRule | None:
        result = await session.execute(
            select(BusinessRule).where(
                BusinessRule.business_id == business_id,
                BusinessRule.key == key,
                BusinessRule.status == RuleStatus.ACTIVE,
            )
        )
        return result.scalar_one_or_none()

    async def versions(self, session: AsyncSession, rule_id: str) -> list[RuleVersion]:
        result = await session.execute(
            select(RuleVersion).where(RuleVersion.rule_id == rule_id).order_by(desc(RuleVersion.version))
        )
        return list(result.scalars().all())

    async def activate_version(
        self, session: AsyncSession, rule: BusinessRule, version_id: str, actor: str
    ) -> BusinessRule:
        version = await session.get(RuleVersion, version_id)
        if not version or version.rule_id != rule.id:
            raise NotFoundError("Rule version not found")
        tests = run_tests(version.code, "calculate", version.tests or [])
        failed = [t for t in tests if not t["passed"]]
        if failed:
            raise ValidationError(
                "Version cannot be activated: tests failed",
                details={"tests": tests},
            )
        rule.code = version.code
        rule.tests = version.tests
        rule.version = version.version
        rule.status = RuleStatus.ACTIVE
        rule.approved_by = actor
        version.status = RuleStatus.ACTIVE
        version.changed_by = actor
        for other in await self.versions(session, rule.id):
            if other.id != version.id and other.status == RuleStatus.ACTIVE:
                other.status = RuleStatus.RETIRED
        await session.flush()
        return rule

    async def create_draft_version(
        self,
        session: AsyncSession,
        rule: BusinessRule,
        code: str,
        tests: list[dict[str, Any]],
        changelog: str,
        changed_by: str,
        description: str | None = None,
    ) -> RuleVersion:
        max_version = (
            await session.execute(select(func.max(RuleVersion.version)).where(RuleVersion.rule_id == rule.id))
        ).scalar() or 0
        tests = tests or rule.tests
        results = run_tests(code, "calculate", tests)
        status = RuleStatus.TESTING if all(t["passed"] for t in results) else RuleStatus.DRAFT
        version = RuleVersion(
            rule_id=rule.id,
            version=max_version + 1,
            code=code,
            tests=tests,
            status=status,
            changed_by=changed_by,
            changelog=changelog,
        )
        if description is not None:
            rule.description = description
        session.add(version)
        await session.flush()
        return version

    async def execute(
        self,
        session: AsyncSession,
        rule: BusinessRule,
        inputs: dict[str, Any],
        *,
        business_id: str | None = None,
        actor: str = "system",
        require_active: bool = True,
        persist: bool = True,
    ) -> dict[str, Any]:
        if require_active and rule.status != RuleStatus.ACTIVE:
            raise ConflictError(f"Rule '{rule.name}' is not approved for production execution")
        started = time.perf_counter()
        outputs: dict[str, Any] = {}
        error: str | None = None
        status = "SUCCEEDED"
        sandboxed = True
        try:
            if rule.source == "FORMULA":
                expression = rule.code.strip()
                outputs = {"result": evaluate_formula(expression, inputs)}
                sandboxed = False
            elif rule.source == "SQL":
                raise ValidationError("SQL rules require an approved read-only analytics connection and are disabled in this deployment")
            else:
                result = run_sandboxed(rule.code, "calculate", inputs)
                if not result.ok:
                    raise ValidationError(f"Rule execution failed: {result.error}")
                outputs = result.result or {}
        except (ValidationError, ConflictError):
            raise
        except FormulaError as exc:
            error = f"FormulaError: {exc}"
        except Exception as exc:  # noqa: BLE001 - record and surface
            error = f"{type(exc).__name__}: {exc}"
        if error:
            status = "FAILED"
        duration_ms = (time.perf_counter() - started) * 1000
        if persist:
            execution = RuleExecution(
                rule_id=rule.id,
                rule_key=rule.key,
                rule_version=rule.version,
                business_id=business_id,
                inputs=inputs,
                outputs=outputs,
                status=status,
                duration_ms=round(duration_ms, 1),
                error=error,
                trace={"actor": actor, "source": rule.source, "sandboxed": sandboxed},
                sandboxed=sandboxed,
            )
            session.add(execution)
            await session.flush()
        if error:
            raise ValidationError(f"Rule '{rule.key}' failed: {error}")
        return outputs

    async def execute_key(
        self,
        session: AsyncSession,
        business_id: str,
        key: str,
        inputs: dict[str, Any],
        *,
        actor: str = "system",
        persist: bool = True,
    ) -> dict[str, Any]:
        rule = await self.get_active(session, business_id, key)
        if not rule:
            raise NotFoundError(f"Active rule '{key}' not found")
        return await self.execute(session, rule, inputs, business_id=business_id, actor=actor, persist=persist)

    async def test_rule(
        self, session: AsyncSession, rule: BusinessRule, code: str | None = None, tests: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        return {"results": run_tests(code or rule.code, "calculate", tests or rule.tests or [])}

    async def executions(
        self, session: AsyncSession, business_id: str, limit: int = 50, rule_key: str | None = None
    ) -> list[RuleExecution]:
        query = select(RuleExecution).where(RuleExecution.business_id == business_id)
        if rule_key:
            query = query.where(RuleExecution.rule_key == rule_key)
        result = await session.execute(query.order_by(desc(RuleExecution.created_at)).limit(limit))
        return list(result.scalars().all())


rule_registry = RuleRegistry()
