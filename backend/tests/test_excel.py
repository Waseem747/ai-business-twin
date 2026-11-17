"""Excel inspection, translation and Excel-engine comparison tests."""
from __future__ import annotations

from app.core.sandbox import run_sandboxed
from app.excel.codegen import generate_python
from app.excel.inspector import inspect_workbook
from app.excel.validator import validate_conversion


def test_workbook_inspection_detects_structure_formulas_and_cycles(demo_workbook_path):
    inspection = inspect_workbook(demo_workbook_path)
    assert inspection["filename"] == "Northwind_Margin_Model.xlsx"
    assert inspection["formula_count"] >= 20
    assert any(item["name"] == "RevenueTarget" for item in inspection["named_ranges"])
    assert inspection["dependency_graph"]["cycles"]
    assert inspection["dependency_graph"]["cross_sheet_references"] > 0
    assert any(item["function"] == "HLOOKUP" for item in inspection["unsupported"])
    assert inspection["output_cells"]
    assert all(input_item["alias"] for input_item in inspection["input_aliases"])


def test_generated_python_is_sandbox_safe_and_reproduces_base_values(demo_workbook_path):
    inspection = inspect_workbook(demo_workbook_path)
    generated = generate_python(inspection)
    inputs = {item["alias"]: item["value"] for item in inspection["input_aliases"]}
    result = run_sandboxed(generated["code"], "calculate", inputs)
    assert result.ok, result.error
    assert round(result.result["gross_margin"], 2) == 31.19
    assert result.result["net_profit"] == 6400
    assert result.result["online_revenue"] == 125540
    assert result.result["wholesale_commission"] == 0.08
    assert result.result["_status"] == "OK"


def test_missing_inputs_are_reported_not_zeroed(demo_workbook_path):
    inspection = inspect_workbook(demo_workbook_path)
    generated = generate_python(inspection)
    result = run_sandboxed(generated["code"], "calculate", {})
    assert result.ok
    assert result.result["_status"] == "MISSING_INPUTS"
    assert result.result["_missing"]


def test_conversion_validates_against_excel_engine(demo_workbook_path):
    inspection = inspect_workbook(demo_workbook_path)
    generated = generate_python(inspection)
    validation = validate_conversion(demo_workbook_path, inspection, generated)
    assert validation["passed"], validation["message"]
    assert validation["status"] == "VALIDATED"
    assert len(validation["datasets"]) == 4
    assert all(dataset["status"] == "PASS" for dataset in validation["datasets"])
    assert validation["mismatches"] == []
