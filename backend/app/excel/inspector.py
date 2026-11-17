"""Workbook inspection: structure, formulas, dependencies, cycles, inputs/outputs."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.excel.formulas import (
    FormulaTokenizer,
    UnsupportedFormula,
    VOLATILE_FUNCTIONS,
    expand_range_keys,
    extract_formula_metadata,
    translate_formula,
)

LOOKUP_SHEET_HINTS = ("rate", "lookup", "reference", "input", "transaction", "instruction", "readme", "assumption")
INPUT_SHEET_HINTS = ("input", "assumption", "driver")


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def _label_for(ws: Worksheet, row: int, column: int) -> str:
    for col in range(column - 1, 0, -1):
        value = ws.cell(row=row, column=col).value
        if isinstance(value, str) and value.strip() and not value.startswith("="):
            return value.strip()[:100]
    for above in range(1, 4):
        if row - above < 1:
            break
        value = ws.cell(row=row - above, column=column).value
        if isinstance(value, str) and value.strip() and not value.startswith("="):
            return value.strip()[:100]
    return ""


def _extract_refs_fallback(formula: str, current_sheet: str, defined_names: dict[str, str]) -> list[str]:
    text = re.sub(r'"[^"]*"', "", formula)
    refs: set[str] = set()
    sheet_pattern = re.compile(
        r"(?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_.]*))!\$?([A-Za-z]{1,3})\$?(\d+)(?::\$?([A-Za-z]{1,3})\$?(\d+))?"
    )
    for match in sheet_pattern.finditer(text):
        sheet = (match.group(1) or match.group(2) or current_sheet).replace("''", "'")
        start = f"{match.group(3).upper()}{match.group(4)}"
        if match.group(5):
            end = f"{match.group(5).upper()}{match.group(6)}"
            refs.update(expand_range_keys(sheet, start, end))
        else:
            refs.add(f"{sheet}!{start}")
    text = sheet_pattern.sub(" ", text)
    cell_pattern = re.compile(r"(?<![A-Za-z0-9_$])\$?([A-Za-z]{1,3})\$?(\d+)(?::\$?([A-Za-z]{1,3})\$?(\d+))?")
    for match in cell_pattern.finditer(text):
        start = f"{match.group(1).upper()}{match.group(2)}"
        if match.group(3):
            end = f"{match.group(3).upper()}{match.group(4)}"
            refs.update(expand_range_keys(current_sheet, start, end))
        else:
            refs.add(f"{current_sheet}!{start}")
    for name, target in defined_names.items():
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text):
            cleaned = str(target).replace("$", "")
            if "!" in cleaned:
                sheet_part, _, cell_part = cleaned.rpartition("!")
                sheet = sheet_part.strip("'")
            else:
                sheet, cell_part = current_sheet, cleaned
            if ":" in cell_part:
                start, end = cell_part.split(":", 1)
                try:
                    refs.update(expand_range_keys(sheet, start, end))
                except Exception:  # noqa: BLE001
                    pass
            else:
                refs.add(f"{sheet}!{cell_part}")
    return sorted(refs)


def _detect_cycles(nodes: list[str], edges: dict[str, set[str]]) -> tuple[list[list[str]], set[str]]:
    """Return cycles and all nodes that are part of or downstream of a cycle."""
    cycles: list[list[str]] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def dfs(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            if node in stack:
                index = stack.index(node)
                cycles.append(stack[index:] + [node])
            return
        visiting.add(node)
        stack.append(node)
        for dependency in sorted(edges.get(node, set())):
            dfs(dependency)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in nodes:
        dfs(node)
    cycle_nodes = {cell for cycle in cycles for cell in cycle}
    # Everything that depends on a cycle is also unsafe.
    reverse: dict[str, set[str]] = defaultdict(set)
    for node, deps in edges.items():
        for dep in deps:
            reverse[dep].add(node)
    blocked = set(cycle_nodes)
    frontier = list(cycle_nodes)
    while frontier:
        node = frontier.pop()
        for dependent in reverse.get(node, set()):
            if dependent not in blocked:
                blocked.add(dependent)
                frontier.append(dependent)
    return cycles, blocked


def _topological(nodes: list[str], edges: dict[str, set[str]], blocked: set[str]) -> list[str]:
    """Dependency-first order for formula cells."""
    order: list[str] = []
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visited or node in blocked:
            return
        visited.add(node)
        for dependency in sorted(edges.get(node, set())):
            if dependency in nodes:
                visit(dependency)
        order.append(node)

    for node in nodes:
        visit(node)
    return order


def slugify(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not slug:
        return "value"
    if slug[0].isdigit():
        slug = f"value_{slug}"
    return slug[:60]


def inspect_workbook(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    formula_wb = load_workbook(path, data_only=False, read_only=False)
    values_wb = load_workbook(path, data_only=True, read_only=False)

    defined_names: dict[str, str] = {}
    named_range_meta: list[dict[str, Any]] = []
    for name, definition in formula_wb.defined_names.items():
        if getattr(definition, "localSheetId", None) is not None:
            continue
        defined_names[name] = str(definition.attr_text)
        named_range_meta.append({"name": name, "target": str(definition.attr_text)})

    sheets: list[dict[str, Any]] = []
    formulas: list[dict[str, Any]] = []
    constants: dict[str, Any] = {}
    formula_keys: set[str] = set()

    for ws in formula_wb.worksheets:
        values_ws = values_wb[ws.title] if ws.title in values_wb.sheetnames else None
        formula_count = 0
        for row in ws.iter_rows():
            for cell in row:
                value = cell.value
                if value is None:
                    continue
                key = f"{ws.title}!{cell.coordinate}"
                if isinstance(value, str) and value.startswith("="):
                    formula_keys.add(key)
                    formula_count += 1
                elif not isinstance(value, str) or not value.startswith("="):
                    constants[key] = _json_value(value)
        sheet_info = {
            "name": ws.title,
            "dimensions": ws.dimensions,
            "max_row": ws.max_row,
            "max_column": ws.max_column,
            "formula_count": formula_count,
            "constant_count": sum(1 for key in constants if key.startswith(f"{ws.title}!")),
            "tables": list(getattr(ws, "tables", {}).keys()),
            "merged_ranges": [str(rng) for rng in ws.merged_cells.ranges],
            "pivots": len(getattr(ws, "_pivots", []) or []),
            "hidden": ws.sheet_state != "visible",
        }
        sheets.append(sheet_info)

        for row in ws.iter_rows():
            for cell in row:
                value = cell.value
                if not (isinstance(value, str) and value.startswith("=")):
                    continue
                key = f"{ws.title}!{cell.coordinate}"
                label = _label_for(ws, cell.row, cell.column)
                cached = None
                if values_ws is not None:
                    cached = _json_value(values_ws[cell.coordinate].value)
                record: dict[str, Any] = {
                    "key": key,
                    "sheet": ws.title,
                    "cell": cell.coordinate,
                    "formula": value,
                    "label": label,
                    "number_format": cell.number_format,
                    "cached_value": cached,
                    "translatable": False,
                    "issue": None,
                    "functions": [],
                    "references": [],
                    "named_ranges": [],
                    "code": None,
                    "external": "[" in value,
                }
                try:
                    metadata = extract_formula_metadata(value, ws.title, defined_names)
                    translated = translate_formula(value, ws.title, defined_names)
                    record.update(
                        {
                            "translatable": True,
                            "functions": translated["functions"],
                            "references": translated["references"],
                            "named_ranges": translated["named_ranges"],
                            "code": translated["code"],
                        }
                    )
                except UnsupportedFormula as exc:
                    tokens: list[Any] = []
                    try:
                        tokens = FormulaTokenizer(value).tokenize()
                    except Exception:  # noqa: BLE001
                        pass
                    record["references"] = _extract_refs_fallback(value, ws.title, defined_names)
                    record["issue"] = {"reason": str(exc), "function": exc.function}
                    if exc.function in VOLATILE_FUNCTIONS:
                        record["issue"]["kind"] = "VOLATILE"
                    elif record["external"]:
                        record["issue"]["kind"] = "EXTERNAL_REFERENCE"
                    else:
                        record["issue"]["kind"] = "UNSUPPORTED"
                except Exception as exc:  # noqa: BLE001
                    record["issue"] = {"reason": f"{type(exc).__name__}: {exc}", "kind": "PARSE_ERROR"}
                    record["references"] = _extract_refs_fallback(value, ws.title, defined_names)
                formulas.append(record)

    edges: dict[str, set[str]] = defaultdict(set)
    for record in formulas:
        for ref in record["references"]:
            if ref in formula_keys:
                edges[record["key"]].add(ref)

    cycles, blocked = _detect_cycles(sorted(formula_keys), edges)
    order = _topological(sorted(formula_keys), edges, blocked)
    dependents_count: dict[str, int] = defaultdict(int)
    for node, deps in edges.items():
        for dep in deps:
            dependents_count[dep] += 1

    # Input cell discovery: labelled constants plus named ranges, prioritising Input sheets.
    label_by_cell: dict[str, str] = {}
    for ws in formula_wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    continue
                if isinstance(cell.value, str) and len(cell.value) > 80:
                    continue
                label = _label_for(ws, cell.row, cell.column)
                if label:
                    label_by_cell[f"{ws.title}!{cell.coordinate}"] = label

    named_targets: dict[str, str] = {}
    for name, target in defined_names.items():
        cleaned = str(target).replace("$", "")
        if ":" in cleaned:
            continue
        if "!" in cleaned:
            sheet_part, _, coord = cleaned.rpartition("!")
            key = f"{sheet_part.strip(chr(39))}!{coord}"
        else:
            key = f"{formula_wb.sheetnames[0]}!{cleaned}"
        if key in constants and isinstance(constants[key], (int, float)):
            named_targets[name] = key

    referenced_constants: set[str] = set()
    for record in formulas:
        for ref in record["references"]:
            if ref in constants:
                referenced_constants.add(ref)

    input_aliases: list[dict[str, Any]] = []
    used_aliases: set[str] = set()
    for name, cell_key in sorted(named_targets.items()):
        alias = slugify(name)
        if alias in used_aliases:
            alias = f"{alias}_input"
        used_aliases.add(alias)
        input_aliases.append(
            {
                "alias": alias,
                "label": next((item["name"] for item in named_range_meta if item["name"] == name), name),
                "cell": cell_key,
                "named_range": name,
                "required": True,
                "value": constants.get(cell_key),
            }
        )
    for cell_key, label in sorted(label_by_cell.items()):
        if cell_key not in referenced_constants:
            continue
        sheet = cell_key.split("!")[0]
        if not any(hint in sheet.lower() for hint in INPUT_SHEET_HINTS):
            continue
        cell = cell_key.split("!")[1]
        if not re.match(r"^[A-Z]{1,3}\d+$", cell):
            continue
        if any(item["cell"] == cell_key for item in input_aliases):
            continue
        alias = slugify(label)
        suffix = 2
        base = alias
        while alias in used_aliases:
            alias = f"{base}_{suffix}"
            suffix += 1
        used_aliases.add(alias)
        input_aliases.append(
            {
                "alias": alias,
                "label": label,
                "cell": cell_key,
                "named_range": None,
                "required": True,
                "value": constants.get(cell_key),
            }
        )

    output_cells: list[dict[str, Any]] = []
    used_outputs: set[str] = set()
    for record in formulas:
        if not record["translatable"] or record["key"] in blocked:
            continue
        if not record["label"]:
            continue
        sheet = record["sheet"].lower()
        if any(hint in sheet for hint in LOOKUP_SHEET_HINTS):
            continue
        output_key = slugify(record["label"])
        base = output_key
        suffix = 2
        while output_key in used_outputs:
            output_key = f"{base}_{suffix}"
            suffix += 1
        used_outputs.add(output_key)
        output_cells.append(
            {
                "key": output_key,
                "label": record["label"],
                "cell": record["key"],
                "formula": record["formula"],
                "translatable": True,
            }
        )

    unsupported = [
        {
            "cell": record["key"],
            "sheet": record["sheet"],
            "formula": record["formula"],
            "reason": record["issue"]["reason"] if record["issue"] else "",
            "kind": record["issue"].get("kind") if record["issue"] else "",
            "function": record["issue"].get("function") if record["issue"] else None,
        }
        for record in formulas
        if record["issue"]
    ]
    external_references = [record["key"] for record in formulas if record["external"]]

    return {
        "filename": path.name,
        "file_size_bytes": path.stat().st_size,
        "sheets": sheets,
        "named_ranges": named_range_meta,
        "formulas": formulas,
        "constants": constants,
        "formula_count": len(formulas),
        "constant_count": len(constants),
        "dependency_graph": {
            "nodes": [
                {"id": record["key"], "label": record["label"], "translatable": record["translatable"]}
                for record in formulas
            ],
            "edges": [{"from": dependency, "to": node} for node, deps in edges.items() for dependency in sorted(deps)],
            "cycles": cycles,
            "blocked": sorted(blocked),
            "cross_sheet_edges": sum(
                1 for node, deps in edges.items() for dep in deps if node.split("!")[0] != dep.split("!")[0]
            ),
            "cross_sheet_references": sum(
                1
                for record in formulas
                for ref in record["references"]
                if ref.split("!")[0] != record["sheet"]
            ),
        },
        "evaluation_order": order,
        "input_aliases": input_aliases,
        "output_cells": output_cells,
        "unsupported": unsupported,
        "external_references": external_references,
        "has_pivot_tables": any(sheet["pivots"] for sheet in sheets),
        "has_cycles": bool(cycles),
        "supported_function_count": len({fn for record in formulas for fn in record["functions"]}),
        "unsupported_function_count": len({item["function"] for item in unsupported if item.get("function")}),
    }
