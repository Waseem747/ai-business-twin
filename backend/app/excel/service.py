"""Excel conversion workflow service: inspect, translate, validate, approve, activate."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.errors import ConflictError, NotFoundError
from app.core.sandbox import run_tests
from app.core.utils import sanitize_json, utcnow
from app.domain.models import Business, BusinessEvent, BusinessRule, ExcelConversion, RuleVersion
from app.excel.codegen import generate_python
from app.excel.inspector import inspect_workbook, slugify
from app.excel.validator import validate_conversion
from app.config import settings


class ExcelConversionService:
    async def save_upload(self, content: bytes, filename: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)
        if not safe.lower().endswith((".xlsx", ".xlsm")):
            raise ConflictError("Only .xlsx or .xlsm workbooks are supported")
        if len(content) > 25 * 1024 * 1024:
            raise ConflictError("Workbook exceeds the 25 MB upload limit")
        digest = hashlib.sha256(content).hexdigest()[:16]
        folder = settings.storage_path / "uploads"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{digest}_{safe}"
        path.write_bytes(content)
        return path

    async def create(
        self, session: AsyncSession, business: Business, path: Path, filename: str
    ) -> ExcelConversion:
        conversion = ExcelConversion(
            business_id=business.id,
            filename=filename,
            storage_path=str(path),
            status="UPLOADED",
        )
        session.add(conversion)
        await session.flush()
        await write_audit(
            session,
            tenant_id=business.tenant_id,
            business_id=business.id,
            actor="system",
            actor_type="SYSTEM",
            action="EXCEL_UPLOADED",
            entity_type="excel_conversion",
            entity_id=conversion.id,
            after={"filename": filename, "bytes": path.stat().st_size},
        )
        return conversion

    async def inspect_and_translate(self, session: AsyncSession, conversion: ExcelConversion) -> dict[str, Any]:
        if conversion.status not in {"UPLOADED", "FAILED", "REQUIRES_REVIEW"}:
            raise ConflictError(f"Conversion cannot be processed from status {conversion.status}")
        try:
            inspection = inspect_workbook(conversion.storage_path)
            generated = generate_python(inspection, header=f"Conversion {conversion.id}")
        except Exception as exc:  # noqa: BLE001
            conversion.status = "FAILED"
            conversion.error = f"Workbook inspection failed: {type(exc).__name__}: {exc}"
            await session.flush()
            raise
        conversion.workbook_meta = sanitize_json({
            "sheets": inspection["sheets"],
            "named_ranges": inspection["named_ranges"],
            "dependency_summary": {
                "formula_count": inspection["formula_count"],
                "constant_count": inspection["constant_count"],
                "cycles": inspection["dependency_graph"]["cycles"],
                "blocked": inspection["dependency_graph"]["blocked"],
                "cross_sheet_edges": inspection["dependency_graph"]["cross_sheet_edges"],
                "cross_sheet_references": inspection["dependency_graph"].get("cross_sheet_references", 0),
                "has_pivot_tables": inspection["has_pivot_tables"],
                "external_references": inspection["external_references"],
            },
            "inputs": generated["inputs"],
            "outputs": generated["outputs"],
            "warnings": generated["warnings"],
            "supported_function_count": inspection["supported_function_count"],
        })
        conversion.dependency_graph = sanitize_json(inspection["dependency_graph"])
        conversion.formulas = sanitize_json(inspection["formulas"])
        conversion.unsupported = sanitize_json(inspection["unsupported"])
        conversion.generated_code = generated["code"]
        conversion.validation = {
            "status": "NOT_RUN",
            "generation": {
                "generated_formula_count": generated["generated_formula_count"],
                "excluded_formula_count": generated["excluded_formula_count"],
                "warnings": generated["warnings"],
                "required_inputs": generated["required_inputs"],
                "blocked_outputs": generated["blocked_outputs"],
            },
        }
        conversion.status = "TRANSLATED"
        conversion.error = None
        await session.flush()
        session.add(
            BusinessEvent(
                business_id=conversion.business_id,
                event_type="EXCEL_TRANSLATED",
                title=f"Workbook translated: {conversion.filename}",
                detail=f"{inspection['formula_count']} formulas inspected; {generated['generated_formula_count']} translated; {len(inspection['unsupported'])} unsupported.",
                severity="INFO" if not inspection["unsupported"] else "MEDIUM",
                actor="excel-conversion-engine",
                related_type="excel_conversion",
                related_id=conversion.id,
            )
        )
        await session.flush()
        return {"inspection": inspection, "generated": generated}

    async def validate(self, session: AsyncSession, conversion: ExcelConversion) -> dict[str, Any]:
        if not conversion.generated_code:
            raise ConflictError("Conversion has no generated code to validate")
        inspection = {
            "filename": conversion.filename,
            "formula_count": len(conversion.formulas),
            "constants": {},
            "input_aliases": conversion.workbook_meta.get("inputs", []),
            "output_cells": conversion.workbook_meta.get("outputs", []),
            "has_cycles": bool((conversion.workbook_meta.get("dependency_summary") or {}).get("cycles")),
            "unsupported": conversion.unsupported,
            "external_references": (conversion.workbook_meta.get("dependency_summary") or {}).get("external_references") or [],
            "dependency_graph": conversion.dependency_graph,
        }
        generated = {
            "code": conversion.generated_code,
            "outputs": conversion.workbook_meta.get("outputs", []),
            "inputs": conversion.workbook_meta.get("inputs", []),
        }
        try:
            validation = validate_conversion(conversion.storage_path, inspection, generated)
        except Exception as exc:  # noqa: BLE001
            validation = {
                "status": "ENGINE_ERROR",
                "passed": False,
                "message": f"Validation could not execute: {type(exc).__name__}: {exc}",
                "comparisons": [],
                "datasets": [],
            }
        validation["generation"] = (conversion.validation or {}).get("generation", {})
        conversion.validation = sanitize_json(validation)
        conversion.status = "AWAITING_APPROVAL" if validation.get("passed") else "REQUIRES_REVIEW"
        await session.flush()
        report_path = await self.write_document(session, conversion, inspection, validation)
        conversion.report_path = str(report_path)
        await session.flush()
        session.add(
            BusinessEvent(
                business_id=conversion.business_id,
                event_type="EXCEL_VALIDATED",
                title=f"Workbook validation {validation.get('status')}: {conversion.filename}",
                detail=validation.get("message", ""),
                severity="INFO" if validation.get("passed") else "HIGH",
                actor="excel-conversion-engine",
                related_type="excel_conversion",
                related_id=conversion.id,
            )
        )
        await session.flush()
        return validation

    async def write_document(
        self, session: AsyncSession, conversion: ExcelConversion, inspection: dict[str, Any], validation: dict[str, Any]
    ) -> Path:
        meta = conversion.workbook_meta or {}
        lines = [
            f"# Business Logic Conversion Document",
            "",
            f"**Workbook:** `{conversion.filename}`  ",
            f"**Conversion:** `{conversion.id}`  ",
            f"**Generated:** {utcnow().isoformat()}  ",
            f"**Status:** {conversion.status}",
            "",
            "> This document was generated by the AI Business Twin Excel Logic Conversion Engine. "
            "The converted logic must be approved before production activation. Excel remains the semantic source until approval.",
            "",
            "## 1. Workbook structure",
            "",
            "| Sheet | Dimensions | Formulas | Tables | Pivot tables |",
            "| --- | --- | --- | --- | --- |",
        ]
        for sheet in inspection.get("sheets", []):
            lines.append(
                f"| {sheet['name']} | {sheet['dimensions']} | {sheet['formula_count']} | {len(sheet['tables'])} | {sheet['pivots']} |"
            )
        lines.extend(["", "## 2. Named ranges", ""])
        if inspection.get("named_ranges"):
            for item in inspection["named_ranges"]:
                lines.append(f"- `{item['name']}` → `{item['target']}`")
        else:
            lines.append("- None")
        lines.extend(["", "## 3. Inputs", "", "| Alias | Label | Cell | Required |", "| --- | --- | --- | --- |"])
        for item in meta.get("inputs", []):
            lines.append(f"| `{item['alias']}` | {item['label']} | `{item['cell']}` | {item['required']} |")
        lines.extend(["", "## 4. Outputs and formula translations", "", "| Output | Label | Cell | Formula |", "| --- | --- | --- | --- |"])
        for output in meta.get("outputs", []):
            formula = str(output.get("formula", "")).replace("|", "\\|")
            lines.append(f"| `{output['key']}` | {output['label']} | `{output['cell']}` | `{formula}` |")
        lines.extend(
            [
                "",
                "## 5. Dependency and safety analysis",
                "",
                f"- Formula cells inspected: **{inspection.get('formula_count', len(conversion.formulas))}**",
                f"- Cross-sheet edges: **{(conversion.workbook_meta.get('dependency_summary') or {}).get('cross_sheet_edges', 0)}**",
                f"- Circular references: **{'; '.join(cycle[0] + ' -> ...' for cycle in (conversion.dependency_graph or {}).get('cycles', [])) or 'none'}**",
                f"- Unsupported formulas: **{len(conversion.unsupported)}**",
                f"- External workbook dependencies: **{', '.join((conversion.workbook_meta.get('dependency_summary') or {}).get('external_references', [])) or 'none'}**",
            ]
        )
        if conversion.unsupported:
            lines.extend(["", "### Unsupported formulas requiring review", "", "| Cell | Function | Reason |", "| --- | --- | --- |"])
            for item in conversion.unsupported:
                lines.append(f"| `{item['cell']}` | `{item.get('function') or ''}` | {item['reason']} |")
        lines.extend(["", "## 6. Validation against Excel engine", ""])
        lines.append(f"- Status: **{validation.get('status')}**")
        lines.append(f"- Engine: `{validation.get('engine', 'n/a')}`")
        lines.append(f"- Tolerance: {validation.get('tolerance', {})}")
        lines.append(f"- {validation.get('message', '')}")
        lines.extend(["", "| Dataset | Status | Passed | Failed |", "| --- | --- | --- | --- |"])
        for dataset in validation.get("datasets", []):
            lines.append(f"| {dataset['name']} | {dataset['status']} | {dataset['passed']} | {dataset['failed']} |")
        if validation.get("mismatches"):
            lines.extend(["", "### Mismatches", "", "| Dataset | Output | Excel | Python | Difference |", "| --- | --- | --- | --- | --- |"])
            for item in validation["mismatches"]:
                lines.append(
                    f"| {item['dataset']} | `{item['output']}` | {item.get('excel_value')} | {item.get('python_value')} | {item.get('difference')} |"
                )
        lines.extend(
            [
                "",
                "## 7. Generated Python logic",
                "",
                "```python",
                conversion.generated_code[:30000],
                "```",
                "",
                "## 8. Limitations",
                "",
                "- The converter supports a defined deterministic subset of Excel functions. Unsupported functions are excluded and listed.",
                "- Circular references and their dependents are excluded from generated logic.",
                "- Formula semantics are validated within the recorded tolerance; results outside tolerance require review.",
                "- Pivot tables are not executed as logic; their source data and formulas must be modelled explicitly.",
                "- Human approval is mandatory before the generated rule is activated.",
            ]
        )
        folder = settings.storage_path / "conversions" / conversion.id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "business_logic_document.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        (folder / "validation.json").write_text(json.dumps(validation, indent=2, default=str), encoding="utf-8")
        (folder / "generated_rule.py").write_text(conversion.generated_code, encoding="utf-8")
        return path

    async def activate(
        self, session: AsyncSession, business: Business, conversion: ExcelConversion, actor: str
    ) -> BusinessRule:
        if conversion.status not in {"AWAITING_APPROVAL"}:
            raise ConflictError(f"Conversion is not awaiting approval (status {conversion.status})")
        validation = conversion.validation or {}
        if not validation.get("passed"):
            raise ConflictError("Conversion validation has not passed; activation is blocked")
        tests = []
        comparisons = validation.get("comparisons") or []
        by_dataset: dict[str, dict[str, Any]] = {}
        for item in comparisons:
            if item["status"] != "PASS":
                continue
            dataset = by_dataset.setdefault(item["dataset"], {"name": item["dataset"], "inputs": {}, "expected": {}})
            if isinstance(item.get("excel_value"), (int, float)):
                dataset["expected"][item["output"]] = item["excel_value"]
        dataset_inputs = {item["name"]: item.get("inputs", {}) for item in validation.get("datasets", [])}
        for name, dataset in by_dataset.items():
            dataset["inputs"] = dataset_inputs.get(name, {})
            if dataset["expected"]:
                tests.append(dataset)
        results = run_tests(conversion.generated_code, "calculate", tests)
        if any(not item["passed"] for item in results):
            raise ConflictError("Generated rule failed its regression tests and cannot be activated")
        key = f"excel_{slugify(Path(conversion.filename).stem)}_{conversion.id[-6:]}"
        rule = BusinessRule(
            business_id=business.id,
            key=key,
            name=f"Excel logic: {Path(conversion.filename).stem}",
            description=(
                f"Approved conversion of {conversion.filename}. "
                f"Validation {validation.get('status')} across {len(validation.get('datasets', []))} datasets. "
                "Cell-level lineage is retained in the conversion record."
            ),
            category="excel_import",
            source="EXCEL",
            code=conversion.generated_code,
            input_schema={
                item["alias"]: "number" for item in (conversion.workbook_meta or {}).get("inputs", [])
            },
            output_schema={
                item["key"]: "number" for item in (conversion.workbook_meta or {}).get("outputs", [])
            },
            version=1,
            dependencies=[],
            execution_frequency="ON_DEMAND",
            tests=tests,
            status="ACTIVE",
            approved_by=actor,
            approved_at=utcnow(),
            excel_lineage={
                "conversion_id": conversion.id,
                "filename": conversion.filename,
                "workbook_meta": conversion.workbook_meta,
                "dependency_graph": conversion.dependency_graph,
                "validation_summary": {
                    "status": validation.get("status"),
                    "message": validation.get("message"),
                    "datasets": validation.get("datasets"),
                },
                "unsupported": conversion.unsupported,
                "report_path": conversion.report_path,
            },
        )
        session.add(rule)
        await session.flush()
        session.add(
            RuleVersion(
                rule_id=rule.id,
                version=1,
                code=rule.code,
                tests=tests,
                status="ACTIVE",
                changed_by=actor,
                changelog=f"Activated from Excel conversion {conversion.id}",
            )
        )
        conversion.rule_id = rule.id
        conversion.status = "ACTIVATED"
        conversion.approved_by = actor
        conversion.approved_at = utcnow()
        await session.flush()
        session.add(
            BusinessEvent(
                business_id=business.id,
                event_type="EXCEL_ACTIVATED",
                title=f"Excel logic activated: {rule.name}",
                detail=f"Rule {rule.key} v{rule.version} activated after validation and human approval by {actor}.",
                severity="INFO",
                actor=actor,
                related_type="business_rule",
                related_id=rule.id,
            )
        )
        await write_audit(
            session,
            tenant_id=business.tenant_id,
            business_id=business.id,
            actor=actor,
            action="EXCEL_CONVERSION_ACTIVATED",
            entity_type="business_rule",
            entity_id=rule.id,
            after={"conversion_id": conversion.id, "key": rule.key, "validation": validation.get("status")},
        )
        await session.flush()
        return rule

    async def get(self, session: AsyncSession, conversion_id: str, business_id: str) -> ExcelConversion:
        conversion = await session.get(ExcelConversion, conversion_id)
        if not conversion or conversion.business_id != business_id:
            raise NotFoundError("Excel conversion not found")
        return conversion

    async def list(self, session: AsyncSession, business_id: str, limit: int = 30) -> list[ExcelConversion]:
        result = await session.execute(
            select(ExcelConversion)
            .where(ExcelConversion.business_id == business_id)
            .order_by(desc(ExcelConversion.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())


excel_service = ExcelConversionService()
