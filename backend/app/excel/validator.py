"""Compare generated Python with an Excel-compatible calculation engine.

Uses the `formulas` package as an independent calculation engine.  If the
engine cannot calculate the workbook, validation fails safe and requires human
review; no conversion is ever reported as validated without executed tests.
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.core.sandbox import run_sandboxed


def _extract_scalar(value: Any) -> Any:
    try:
        for _ in range(6):
            if hasattr(value, "value") and not isinstance(value, (list, tuple)):
                candidate = value.value
                if candidate is not value:
                    value = candidate
                    continue
            if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
                value = value.tolist()
                continue
            if isinstance(value, (list, tuple)):
                if not value:
                    return None
                value = value[0]
                continue
            break
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return None
    except Exception:  # noqa: BLE001
        return None


def _normalise_key(key: str) -> tuple[str, str] | None:
    match = re.match(r"'\[(.+?)\](.*)'!(.+)", key)
    if not match:
        return None
    return match.group(2).upper(), match.group(3).upper()


class ExcelComparator:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.workbook = load_workbook(self.path, data_only=False)
        self.model = None
        self.keymap: dict[str, str] = {}
        self.namekeys: dict[str, str] = {}

    def _load_engine(self) -> None:
        import formulas  # imported lazily so the API can boot without optional load

        self.model = formulas.ExcelModel().loads(str(self.path)).finish()
        for key in self.model.dsp.data_nodes:
            normalised = _normalise_key(key)
            if not normalised:
                continue
            sheet, coord = normalised
            if sheet:
                self.keymap[f"{sheet}!{coord}"] = key
            else:
                self.namekeys[coord] = key

    def calculate_excel(self, overrides: dict[str, Any]) -> dict[str, Any]:
        if self.model is None:
            self._load_engine()
        inputs: dict[str, Any] = {}
        for cell_key, value in overrides.items():
            key = self.keymap.get(cell_key.upper())
            if key is not None:
                inputs[key] = value
        # Pin defined names. Names pointing at overridden cells receive the new
        # value; other names retain their workbook constant to avoid stale-name bugs.
        for name, target in self._defined_name_map.items():
            key = self.namekeys.get(name.upper())
            if key is None:
                continue
            if target in overrides:
                inputs[key] = overrides[target]
            else:
                inputs[key] = self._current_value(target, name)
        solution = self.model.calculate(inputs=inputs) if inputs else self.model.calculate()
        outputs: dict[str, Any] = {}
        for cell_key in self.requested_cells:
            key = self.keymap.get(cell_key.upper())
            if key is None:
                outputs[cell_key] = {"found": False, "value": None, "raw": None}
                continue
            value = _extract_scalar(solution.get(key))
            outputs[cell_key] = {"found": True, "value": value, "raw": value}
        return outputs

    @property
    def _defined_name_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for name, definition in self.workbook.defined_names.items():
            if getattr(definition, "localSheetId", None) is not None:
                continue
            target = str(definition.attr_text).replace("$", "")
            if ":" in target:
                continue
            if "!" in target:
                sheet, _, coord = target.rpartition("!")
                cell_key = f"{sheet.strip(chr(39))}!{coord}"
            else:
                cell_key = f"{self.workbook.sheetnames[0]}!{target}"
            mapping[name] = cell_key
        return mapping

    def _current_value(self, cell_key: str, name: str | None = None) -> Any:
        sheet, _, coord = cell_key.partition("!")
        try:
            value = self.workbook[sheet][coord].value
            if isinstance(value, str) and value.startswith("="):
                return 0
            return value
        except Exception:  # noqa: BLE001
            return 0

    requested_cells: list[str] = []


def _default_datasets(inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = {item["alias"]: item["value"] for item in inputs}
    datasets = [
        {"name": "baseline", "description": "Workbook values as supplied", "inputs": dict(base)},
        {
            "name": "margin_stress",
            "description": "Revenue -7%, COGS +6%, marketing +3%",
            "inputs": {
                **base,
                "revenue_current": round(float(base.get("revenue_current") or 0) * 0.93, 2),
                "cogs_current": round(float(base.get("cogs_current") or 0) * 1.06, 2),
                "marketing_current": round(float(base.get("marketing_current") or 0) * 1.03, 2),
            },
        },
        {
            "name": "upside",
            "description": "Revenue +5%, COGS -4%",
            "inputs": {
                **base,
                "revenue_current": round(float(base.get("revenue_current") or 0) * 1.05, 2),
                "cogs_current": round(float(base.get("cogs_current") or 0) * 0.96, 2),
            },
        },
        {
            "name": "zero_revenue_guard",
            "description": "Revenue set to zero to exercise IF and IFERROR guards",
            "inputs": {**base, "revenue_current": 0},
        },
    ]
    # Only override aliases that actually exist in this workbook.
    known = set(base)
    for dataset in datasets:
        dataset["inputs"] = {key: value for key, value in dataset["inputs"].items() if key in known}
    return datasets


def validate_conversion(
    path: str | Path,
    inspection: dict[str, Any],
    generated: dict[str, Any],
    *,
    tolerance_abs: float = 0.01,
    tolerance_rel: float = 0.0001,
    datasets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    outputs = generated["outputs"]
    if not outputs:
        return {
            "status": "NO_OUTPUTS",
            "passed": False,
            "message": "No translatable output cells were identified; conversion cannot be validated.",
            "comparisons": [],
            "datasets": [],
        }
    datasets = datasets or _default_datasets(generated["inputs"])
    comparator = ExcelComparator(path)
    comparator.requested_cells = [output["cell"] for output in outputs]
    comparison_results: list[dict[str, Any]] = []
    dataset_summaries: list[dict[str, Any]] = []
    engine_error: str | None = None
    try:
        comparator._load_engine()
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ENGINE_ERROR",
            "passed": False,
            "message": f"Excel calculation engine could not load the workbook: {type(exc).__name__}: {exc}",
            "comparisons": [],
            "datasets": [],
        }

    for dataset in datasets:
        inputs = dataset["inputs"]
        excel_inputs: dict[str, Any] = {}
        for input_meta in generated["inputs"]:
            alias = input_meta["alias"]
            if alias in inputs:
                excel_inputs[input_meta["cell"]] = inputs[alias]
        try:
            excel_values = comparator.calculate_excel(excel_inputs)
        except Exception as exc:  # noqa: BLE001
            engine_error = f"{type(exc).__name__}: {exc}"
            dataset_summaries.append(
                {
                    "name": dataset["name"],
                    "status": "ENGINE_ERROR",
                    "error": engine_error,
                    "passed": 0,
                    "failed": 0,
                }
            )
            continue
        generated_run = run_sandboxed(generated["code"], "calculate", inputs)
        if not generated_run.ok:
            dataset_summaries.append(
                {
                    "name": dataset["name"],
                    "status": "PYTHON_ERROR",
                    "error": generated_run.error,
                    "passed": 0,
                    "failed": len(outputs),
                }
            )
            continue
        counterpart = generated_run.result or {}
        passed = 0
        failed = 0
        for output in outputs:
            cell = output["cell"]
            expected_info = excel_values.get(cell, {})
            expected = expected_info.get("value")
            actual = counterpart.get(output["key"])
            if isinstance(expected, str) and expected.startswith("#"):
                status = "EXCEL_ERROR"
                difference = None
            elif expected is None and actual is None:
                status = "PASS"
                difference = 0.0
            elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
                difference = abs(float(actual) - float(expected))
                allowed = tolerance_abs + tolerance_rel * abs(float(expected))
                status = "PASS" if difference <= allowed else "MISMATCH"
            elif expected == actual:
                status = "PASS"
                difference = 0.0
            else:
                status = "MISMATCH"
                difference = None
            if status == "PASS":
                passed += 1
            else:
                failed += 1
            comparison_results.append(
                {
                    "dataset": dataset["name"],
                    "output": output["key"],
                    "label": output["label"],
                    "cell": cell,
                    "formula": output["formula"],
                    "excel_value": expected,
                    "python_value": actual,
                    "difference": round(difference, 6) if difference is not None else None,
                    "status": status,
                }
            )
        dataset_summaries.append(
            {
                "name": dataset["name"],
                "description": dataset["description"],
                "status": "PASS" if failed == 0 else "FAIL",
                "passed": passed,
                "failed": failed,
                "inputs": inputs,
                "duration_ms": None,
            }
        )

    total_passed = sum(1 for item in comparison_results if item["status"] == "PASS")
    total = len(comparison_results)
    failed_dataset_names = [item["name"] for item in dataset_summaries if item["status"] != "PASS"]
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    if engine_error or total == 0:
        status = "ENGINE_ERROR" if engine_error else "NO_COMPARISONS"
        passed = False
        message = engine_error or "No comparisons executed."
    elif total_passed == total:
        status = "VALIDATED"
        passed = True
        message = f"All {total} output comparisons passed across {len(dataset_summaries)} datasets within tolerance."
    else:
        status = "FAILED"
        passed = False
        message = f"{total - total_passed} of {total} comparisons failed. Conversion requires correction or human review."
    for summary in dataset_summaries:
        summary["duration_ms"] = duration_ms / max(1, len(dataset_summaries))
    return {
        "status": status,
        "passed": passed,
        "message": message,
        "tolerance": {"absolute": tolerance_abs, "relative": tolerance_rel},
        "compared_outputs": len(outputs),
        "datasets": dataset_summaries,
        "comparisons": comparison_results,
        "mismatches": [item for item in comparison_results if item["status"] != "PASS"][:30],
        "failed_datasets": failed_dataset_names,
        "duration_ms": duration_ms,
        "engine": "formulas==1.3.4",
        "executed_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
    }
