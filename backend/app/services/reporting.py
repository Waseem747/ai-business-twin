"""Management reporting: daily summary, exception report and decision report.

Reports separate measured actuals, deterministic calculations, AI
interpretation, simulated projections and executed actions. PDF, Excel and CSV
artifacts are written to the storage volume and linked from the report record.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.model_gateway import model_gateway
from app.config import settings
from app.core.utils import utcnow
from app.domain.models import (
    ActionVerification,
    AgentExecution,
    Alert,
    Approval,
    Business,
    BusinessAction,
    Decision,
    MetricSnapshot,
    Report,
)

NAVY = colors.HexColor("#0F2742")
BLUE = colors.HexColor("#1D5FA8")
LIGHT = colors.HexColor("#EAF1F8")
GREY = colors.HexColor("#6B7785")
RED = colors.HexColor("#B3261E")
AMBER = colors.HexColor("#B26A00")


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _pdf_styles() -> dict[str, Any]:
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="TwinTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TwinH2",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=NAVY,
            spaceBefore=12,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TwinBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#243447"),
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TwinSmall",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=GREY,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TwinBanner",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=colors.white,
            backColor=NAVY,
            borderPadding=4,
            spaceAfter=10,
        )
    )
    return styles


def _table(data: list[list[str]], widths: list[float] | None = None) -> Table:
    table = Table(data, colWidths=widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEADING", (0, 0), (-1, -1), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D3DF")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


class ReportingService:
    def _storage(self, report_id: str) -> Path:
        path = settings.storage_path / "reports" / report_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def _collect_context(
        self, session: AsyncSession, business: Business, snapshot: MetricSnapshot
    ) -> dict[str, Any]:
        alerts = (
            await session.execute(
                select(Alert).where(Alert.business_id == business.id).order_by(desc(Alert.last_seen)).limit(25)
            )
        ).scalars().all()
        decisions = (
            await session.execute(
                select(Decision).where(Decision.business_id == business.id).order_by(desc(Decision.created_at)).limit(15)
            )
        ).scalars().all()
        actions = (
            await session.execute(
                select(BusinessAction)
                .where(BusinessAction.business_id == business.id)
                .order_by(desc(BusinessAction.created_at))
                .limit(15)
            )
        ).scalars().all()
        approvals = (
            await session.execute(
                select(Approval).where(Approval.business_id == business.id, Approval.status == "PENDING").limit(20)
            )
        ).scalars().all()
        agents = (
            await session.execute(
                select(AgentExecution)
                .where(AgentExecution.business_id == business.id)
                .order_by(desc(AgentExecution.created_at))
                .limit(40)
            )
        ).scalars().all()
        verifications = (
            await session.execute(
                select(ActionVerification)
                .where(ActionVerification.action_id.in_([action.id for action in actions]))
                .order_by(desc(ActionVerification.created_at))
                .limit(20)
            )
        ).scalars().all() if actions else []
        return {
            "alerts": alerts,
            "decisions": decisions,
            "actions": actions,
            "approvals": approvals,
            "agents": agents,
            "verifications": verifications,
        }

    def _content(self, business: Business, snapshot: MetricSnapshot, context: dict[str, Any]) -> dict[str, Any]:
        payload = snapshot.payload
        latest = payload.get("latest", {})
        exceptions = [
            {
                "severity": alert.severity,
                "title": alert.title,
                "detail": alert.detail,
                "status": alert.status,
                "area": alert.area,
                "occurrences": alert.occurrences,
                "evidence": alert.evidence,
            }
            for alert in context["alerts"]
            if alert.status != "RESOLVED"
        ]
        decisions = [
            {
                "id": decision.id,
                "title": decision.title,
                "status": decision.status,
                "risk": decision.risk_level,
                "expected_impact": decision.expected_financial_impact,
                "confidence": decision.confidence,
                "requires_approval": decision.requires_approval,
                "simulated": True,
            }
            for decision in context["decisions"]
        ]
        actions = []
        for action in context["actions"]:
            verification = next((item for item in context["verifications"] if item.action_id == action.id), None)
            actions.append(
                {
                    "id": action.id,
                    "type": action.action_type,
                    "status": action.status,
                    "system": action.target_system,
                    "executed_at": action.executed_at.isoformat() if action.executed_at else None,
                    "simulated": action.simulated,
                    "verification": verification.status if verification else None,
                    "business_impact": verification.business_impact if verification else None,
                }
            )
        measured = {
            "period": latest.get("label"),
            "revenue": latest.get("revenue"),
            "gross_profit": latest.get("gross_profit"),
            "gross_margin_pct": latest.get("gross_margin_pct"),
            "operating_expenses": latest.get("operating_expenses"),
            "net_profit": latest.get("net_profit"),
            "net_margin_pct": latest.get("net_margin_pct"),
            "cash_balance": latest.get("cash_balance"),
            "cash_runway_months": latest.get("cash_runway_months"),
            "inventory_days": latest.get("inventory_days"),
            "churn_rate_pct": latest.get("churn_rate_pct"),
        }
        return {
            "as_of": snapshot.as_of.isoformat(),
            "business": {"name": business.name, "industry": business.industry, "currency": business.currency, "demo": business.is_demo},
            "measured_actuals": measured,
            "deterministic_metrics": payload.get("kpis", []),
            "health": payload.get("health", {}),
            "executive_summary": payload.get("summary", ""),
            "exceptions": exceptions,
            "decisions": decisions,
            "actions": actions,
            "pending_approvals": [
                {"id": approval.id, "decision_id": approval.decision_id, "status": approval.status, "requested_at": approval.requested_at.isoformat()}
                for approval in context["approvals"]
            ],
            "data_quality": payload.get("data_quality", {}),
            "agent_activity": [
                {
                    "agent": execution.agent_key,
                    "status": execution.status,
                    "summary": execution.summary,
                    "at": execution.created_at.isoformat(),
                    "model_provider": execution.model_provider,
                }
                for execution in context["agents"][:15]
            ],
            "provenance": {
                "snapshot_id": snapshot.id,
                "report_engine": "reporting-agent-v1",
                "simulated_actions": all(action.simulated for action in context["actions"]) if context["actions"] else None,
                "notice": "Measured actuals are separated from AI interpretation and simulated projections.",
            },
        }

    async def generate_daily(
        self, session: AsyncSession, business: Business, snapshot: MetricSnapshot, *, actor: str = "reporting-agent"
    ) -> Report:
        context = await self._collect_context(session, business, snapshot)
        content = self._content(business, snapshot, context)
        narrative = await model_gateway.narrate(
            "report_narrative",
            content,
            deterministic_text=content["executive_summary"],
        )
        content["ai_interpretation"] = {
            "text": narrative.text,
            "provider": narrative.provider,
            "model": narrative.model,
            "fallback_reason": narrative.fallback_reason,
            "label": "AI interpretation" if narrative.provider != "deterministic" else "Deterministic narrative",
        }
        report = Report(
            business_id=business.id,
            report_type="DAILY_SUMMARY",
            title=f"Daily Executive Summary - {content['measured_actuals'].get('period') or snapshot.as_of.date()}",
            period_start=None,
            period_end=snapshot.as_of,
            status="READY",
            content=content,
            generated_by=actor,
        )
        session.add(report)
        await session.flush()
        files = await self._write_artifacts(report, content, exception_only=False)
        report.files = files
        await session.flush()
        return report

    async def generate_exception(
        self, session: AsyncSession, business: Business, snapshot: MetricSnapshot, *, actor: str = "reporting-agent"
    ) -> Report:
        context = await self._collect_context(session, business, snapshot)
        content = self._content(business, snapshot, context)
        content["title"] = "Daily Exception Report"
        content["summary"] = (
            f"{len(content['exceptions'])} open exception(s). "
            + ("Critical exceptions require immediate management action." if any(item["severity"] == "CRITICAL" for item in content["exceptions"]) else "No critical exceptions are recorded.")
        )
        report = Report(
            business_id=business.id,
            report_type="EXCEPTION",
            title=f"Daily Exception Report - {snapshot.as_of.date()}",
            period_end=snapshot.as_of,
            status="READY",
            content=content,
            generated_by=actor,
        )
        session.add(report)
        await session.flush()
        files = await self._write_artifacts(report, content, exception_only=True)
        report.files = files
        await session.flush()
        return report

    async def generate_decision_report(
        self, session: AsyncSession, business: Business, decision: Decision
    ) -> Report:
        action = (
            await session.execute(
                select(BusinessAction).where(BusinessAction.decision_id == decision.id).order_by(desc(BusinessAction.created_at)).limit(1)
            )
        ).scalar_one_or_none()
        verification = None
        if action:
            verification = (
                await session.execute(
                    select(ActionVerification).where(ActionVerification.action_id == action.id).order_by(desc(ActionVerification.created_at)).limit(1)
                )
            ).scalar_one_or_none()
        content = {
            "decision_id": decision.id,
            "question": {"what_happened": decision.issue, "why": [item for item in decision.evidence if item.get("type") == "ANOMALY"]},
            "recommendation": {
                "title": decision.title,
                "objective": decision.objective,
                "rationale": decision.rationale,
                "expected_financial_impact": decision.expected_financial_impact,
                "confidence": decision.confidence,
                "risk_level": decision.risk_level,
                "requires_approval": decision.requires_approval,
                "chosen": decision.chosen,
                "alternatives": decision.alternatives,
            },
            "validation": {
                "audit_rounds": decision.audit_rounds,
                "status": decision.status,
            },
            "execution": (
                {
                    "action_id": action.id,
                    "type": action.action_type,
                    "status": action.status,
                    "simulated": action.simulated,
                    "external_id": action.external_id,
                    "executed_at": action.executed_at.isoformat() if action.executed_at else None,
                }
                if action
                else None
            ),
            "verification": (
                {
                    "status": verification.status,
                    "differences": verification.differences,
                    "business_impact": verification.business_impact,
                    "notes": verification.notes,
                }
                if verification
                else None
            ),
            "separation_notice": "Projected impact is SIMULATED. Execution verification confirms operational state only until a measured follow-up window exists.",
        }
        report = Report(
            business_id=business.id,
            report_type="DECISION",
            title=f"Decision Report - {decision.title}",
            period_end=utcnow(),
            status="READY",
            content=content,
            generated_by="reporting-agent",
        )
        session.add(report)
        await session.flush()
        report.files = await self._write_artifacts(report, content, exception_only=False)
        await session.flush()
        return report

    async def _write_artifacts(self, report: Report, content: dict[str, Any], *, exception_only: bool) -> dict[str, str]:
        folder = self._storage(report.id)
        pdf_path = folder / f"{report.report_type.lower()}.pdf"
        xlsx_path = folder / f"{report.report_type.lower()}.xlsx"
        csv_path = folder / f"{report.report_type.lower()}.csv"
        self._write_pdf(pdf_path, content, exception_only)
        self._write_excel(xlsx_path, content, exception_only)
        self._write_csv(csv_path, content)
        return {"pdf": str(pdf_path), "xlsx": str(xlsx_path), "csv": str(csv_path)}

    def _write_pdf(self, path: Path, content: dict[str, Any], exception_only: bool) -> None:
        styles = _pdf_styles()
        doc = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=18 * mm,
            bottomMargin=16 * mm,
            title="AI Business Twin Report",
            author="AI Business Twin",
        )
        story: list[Any] = []
        business = content.get("business", {})
        title = "Daily Exception Report" if exception_only else "Daily Executive Summary"
        story.append(Paragraph(title, styles["TwinTitle"]))
        story.append(
            Paragraph(
                f"{business.get('name', 'Business')} &nbsp;|&nbsp; Generated {utcnow().strftime('%d %b %Y %H:%M UTC')} &nbsp;|&nbsp; Data as of {content.get('measured_actuals', {}).get('period', 'n/a')}",
                styles["TwinSmall"],
            )
        )
        story.append(Spacer(1, 4))
        story.append(
            Paragraph(
                "MEASURED RESULTS AND SIMULATED PROJECTIONS ARE SEPARATE &nbsp;&bull;&nbsp; AI INTERPRETATION IS LABELLED",
                styles["TwinBanner"],
            )
        )

        if exception_only:
            story.append(Paragraph("Open exceptions", styles["TwinH2"]))
            rows = [["Severity", "Exception", "Status", "Area", "Occurrences"]]
            for item in content.get("exceptions", []):
                rows.append([item["severity"], item["title"], item["status"], item["area"], str(item["occurrences"])])
            if len(rows) == 1:
                rows.append(["INFO", "No open exceptions recorded", "-", "-", "0"])
            story.append(_table(rows, widths=[20 * mm, 88 * mm, 24 * mm, 24 * mm, 20 * mm]))
            story.append(Paragraph("Exception detail", styles["TwinH2"]))
            for item in content.get("exceptions", [])[:8]:
                story.append(Paragraph(f"<b>{item['severity']} - {item['title']}</b>", styles["TwinBody"]))
                story.append(Paragraph(item["detail"], styles["TwinSmall"]))
            story.append(PageBreak())
        else:
            story.append(Paragraph("Executive summary", styles["TwinH2"]))
            story.append(Paragraph(content.get("executive_summary", ""), styles["TwinBody"]))
            interpretation = content.get("ai_interpretation") or {}
            if interpretation.get("text") and interpretation.get("text") != content.get("executive_summary"):
                story.append(Paragraph(f"<i>{interpretation.get('label', 'Interpretation')}:</i>", styles["TwinSmall"]))
                story.append(Paragraph(interpretation["text"].replace("\n", "<br/>"), styles["TwinBody"]))

            story.append(Paragraph("Measured actuals", styles["TwinH2"]))
            actuals = content.get("measured_actuals", {})
            rows = [
                ["Metric", "Actual", "Source"],
                ["Revenue", _money(actuals.get("revenue")), "Validated POS observations"],
                ["Gross profit", _money(actuals.get("gross_profit")), "Deterministic calculation"],
                ["Gross margin", _pct(actuals.get("gross_margin_pct")), "Deterministic calculation"],
                ["Operating expenses", _money(actuals.get("operating_expenses")), "Validated ERP observations"],
                ["Net profit", _money(actuals.get("net_profit")), "Deterministic calculation"],
                ["Cash balance", _money(actuals.get("cash_balance")), "Validated ERP observations"],
                ["Cash runway", f"{actuals.get('cash_runway_months') or 'n/a'} months", "Deterministic calculation"],
            ]
            story.append(_table(rows, widths=[50 * mm, 55 * mm, 65 * mm]))

            story.append(Paragraph("Business health", styles["TwinH2"]))
            health = content.get("health", {})
            story.append(Paragraph(f"Health score <b>{health.get('score', 'n/a')}/100</b> (grade {health.get('grade', 'n/a')}).", styles["TwinBody"]))
            factors = health.get("factors", [])
            if factors:
                story.append(_table([["Factor", "Score", "Value"]] + [[f["label"], str(f["score"]), str(f["value"])] for f in factors], widths=[60 * mm, 30 * mm, 50 * mm]))

            story.append(Paragraph("Open exceptions", styles["TwinH2"]))
            rows = [["Severity", "Exception", "Area"]]
            for item in content.get("exceptions", [])[:8]:
                rows.append([item["severity"], item["title"], item["area"]])
            if len(rows) == 1:
                rows.append(["INFO", "No open exceptions", "-"])
            story.append(_table(rows, widths=[22 * mm, 120 * mm, 28 * mm]))

            story.append(Paragraph("Pending decisions and approvals", styles["TwinH2"]))
            rows = [["Decision", "Status", "Projected impact", "Approval"]]
            for item in content.get("decisions", [])[:6]:
                rows.append([item["title"][:70], item["status"], _money(item["expected_impact"]), "Required" if item["requires_approval"] else "Automatic"])
            if len(rows) == 1:
                rows.append(["No decisions recorded", "-", "-", "-"])
            story.append(_table(rows, widths=[88 * mm, 28 * mm, 28 * mm, 26 * mm]))
            story.append(PageBreak())

            story.append(Paragraph("Executed actions and verification", styles["TwinH2"]))
            rows = [["Action", "Status", "System", "Verified", "Simulated"]]
            for item in content.get("actions", [])[:8]:
                rows.append([item["type"].replace("_", " ").title(), item["status"], item["system"], item.get("verification") or "PENDING", "YES" if item["simulated"] else "NO"])
            if len(rows) == 1:
                rows.append(["No actions executed", "-", "-", "-", "-"])
            story.append(_table(rows, widths=[58 * mm, 28 * mm, 30 * mm, 26 * mm, 18 * mm]))
            story.append(Paragraph(
                "Verification confirms the operational state of the simulated ERP record. It does not convert the projected financial impact into a measured result.",
                styles["TwinSmall"],
            ))

            story.append(Paragraph("Data quality and provenance", styles["TwinH2"]))
            quality = content.get("data_quality", {})
            story.append(Paragraph(
                f"Completeness {quality.get('completeness_pct', 'n/a')}%. "
                f"Stale sources: {', '.join(quality.get('stale_sources') or []) or 'none'}. "
                f"Snapshot {content.get('provenance', {}).get('snapshot_id', '')}. "
                + ("DEMO DATA: data sources are simulated and labelled." if business.get("demo") else ""),
                styles["TwinBody"],
            ))

        def footer(canvas, doc):  # noqa: ANN001
            canvas.saveState()
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(GREY)
            canvas.drawString(16 * mm, 9 * mm, "AI Business Twin - generated management report - measured, simulated and interpreted information are separated")
            canvas.drawRightString(194 * mm, 9 * mm, f"Page {doc.page}")
            canvas.restoreState()

        doc.build(story, onFirstPage=footer, onLaterPages=footer)

    def _write_excel(self, path: Path, content: dict[str, Any], exception_only: bool) -> None:
        wb = Workbook()
        ws = wb.active
        ws.title = "Summary"
        ws.column_dimensions["A"].width = 32
        ws.column_dimensions["B"].width = 80
        ws["A1"] = "AI Business Twin - Daily Exception Report" if exception_only else "AI Business Twin - Daily Executive Summary"
        ws["A1"].font = Font(bold=True, size=16, color="0F2742")
        ws["A3"] = "Business"
        ws["B3"] = content.get("business", {}).get("name")
        ws["A4"] = "Data period"
        ws["B4"] = content.get("measured_actuals", {}).get("period")
        ws["A5"] = "Generated"
        ws["B5"] = utcnow().isoformat()
        ws["A6"] = "Notice"
        ws["B6"] = content.get("provenance", {}).get("notice")
        row = 8
        ws.cell(row=row, column=1, value="Measured actuals").font = Font(bold=True, color="1D5FA8")
        row += 1
        for key, value in content.get("measured_actuals", {}).items():
            ws.cell(row=row, column=1, value=key.replace("_", " ").title())
            ws.cell(row=row, column=2, value=value)
            row += 1
        row += 1
        ws.cell(row=row, column=1, value="AI interpretation").font = Font(bold=True, color="1D5FA8")
        ws.cell(row=row + 1, column=1, value=content.get("ai_interpretation", {}).get("label", "Deterministic narrative"))
        ws.cell(row=row + 1, column=2, value=content.get("ai_interpretation", {}).get("text", content.get("executive_summary")))
        ws.cell(row=row + 1, column=2).alignment = Alignment(wrap_text=True, vertical="top")

        def sheet(name: str, headers: list[str], rows: list[list[Any]]) -> None:
            target = wb.create_sheet(name)
            target.append(headers)
            for cell in target[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="0F2742")
            for row_data in rows:
                target.append(row_data)
            for index, header in enumerate(headers, start=1):
                target.column_dimensions[chr(64 + index)].width = max(14, min(60, len(header) + 18))

        sheet(
            "Exceptions",
            ["Severity", "Title", "Status", "Area", "Occurrences", "Detail"],
            [[item["severity"], item["title"], item["status"], item["area"], item["occurrences"], item["detail"]] for item in content.get("exceptions", [])],
        )
        sheet(
            "Decisions",
            ["Title", "Status", "Risk", "Projected impact (simulated)", "Confidence", "Approval required"],
            [[item["title"], item["status"], item["risk"], item["expected_impact"], item["confidence"], item["requires_approval"]] for item in content.get("decisions", [])],
        )
        sheet(
            "Actions",
            ["Type", "Status", "System", "Simulated", "Executed at", "Verification"],
            [[item["type"], item["status"], item["system"], item["simulated"], item["executed_at"], item.get("verification")] for item in content.get("actions", [])],
        )
        sheet(
            "AgentActivity",
            ["Agent", "Status", "Summary", "Model"],
            [[item["agent"], item["status"], item["summary"], item["model_provider"]] for item in content.get("agent_activity", [])],
        )
        sheet(
            "DataQuality",
            ["Field", "Value"],
            [[key, str(value)[:500]] for key, value in content.get("data_quality", {}).items()],
        )
        wb.save(path)

    def _write_csv(self, path: Path, content: dict[str, Any]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["section", "key", "value", "classification"])
            for key, value in content.get("measured_actuals", {}).items():
                writer.writerow(["measured_actual", key, value, "MEASURED"])
            for item in content.get("exceptions", []):
                writer.writerow(["exception", item["title"], item["detail"], "OBSERVED"])
            for item in content.get("decisions", []):
                writer.writerow(["decision", item["title"], item["expected_impact"], "SIMULATED/PROPOSED"])
            for item in content.get("actions", []):
                writer.writerow(["action", item["type"], item["status"], "EXECUTED_ACTION"])

    async def list_reports(self, session: AsyncSession, business_id: str, report_type: str | None = None, limit: int = 30) -> list[Report]:
        query = select(Report).where(Report.business_id == business_id)
        if report_type:
            query = query.where(Report.report_type == report_type)
        result = await session.execute(query.order_by(desc(Report.created_at)).limit(limit))
        return list(result.scalars().all())


reporting_service = ReportingService()
