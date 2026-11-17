# Excel Logic Conversion

The converter turns a governance-friendly subset of an Excel workbook into a sandboxed Python rule. It preserves cell-level lineage, detects unsupported/ambiguous formulas and circular references, and validates the generated code against an independent Excel-compatible calculation engine before proposing activation.

## Pipeline

1. **Upload** — `.xlsx` / `.xlsm`, max 25 MB.
2. **Inspection** — sheets, used ranges, constants, formulas, labels, named ranges, tables, merge ranges, pivot presence, external references.
3. **Dependency graph** — Excel A1 and cross-sheet references expanded into a cell graph.
4. **Cycle detection** — circular references and all dependent cells are excluded and reported.
5. **Translation** — supported functions are translated into Python; unsupported/volatile formulas are flagged, never guessed.
6. **Code generation** — a sandbox-safe module containing:
   - helper functions;
   - embedded workbook constants;
   - input aliases and required-input checks;
   - the dependency-ordered cell calculations;
   - `calculate(inputs)` and `calculate_cells(inputs)`.
7. **Validation** — the generated code and the workbook are executed on multiple datasets:
   - baseline;
   - margin stress;
   - upside;
   - zero-revenue guard.
   Each output cell is compared within configurable absolute/relative tolerances.
8. **Business logic document** — Markdown report with workbook structure, named ranges, inputs, outputs, formulas, dependency summary, unsupported list, validation table, generated code and limitations.
9. **Human approval** — only a validated conversion in `AWAITING_APPROVAL` can be activated by an APPROVER/ADMIN.
10. **Registry activation** — generated code becomes an ACTIVE `BusinessRule` (`source=EXCEL`) with tests taken from the Excel-engine comparisons and a full `excel_lineage` record.

## Demo workbook

`backend/data/demo/Northwind_Margin_Model.xlsx` is intentionally constructed to demonstrate:

- cross-sheet references (`Inputs!B4`, `Transactions!C2:C41`);
- `IF`, `IFERROR`, `ROUND`, `ROUNDUP`, `CONCATENATE`;
- `SUMIFS`, `COUNTIFS`;
- `VLOOKUP`, `INDEX` + `MATCH`, `AVERAGE`;
- named ranges (`RevenueTarget`, `Supplier_Rebate_Pct`, `Opening_Cash`);
- one unsupported function (`HLOOKUP`) that is excluded and flagged;
- a circular reference pair (`CircularExample!B3` / `C3`) detected and excluded.

Current validation result: **21 outputs × 4 datasets = 84 / 84 comparisons passed** against `formulas==1.3.4`.

## Supported functions

Arithmetic and comparisons:

`+ - * / ^ & = <> < > <= >= %`, parentheses, unary signs.

Logical / conditional:

`IF`, `IFERROR`, `IFNA`, `IFS`, `AND`, `OR`, `NOT`, `ISBLANK`, `ISNUMBER`, `ISTEXT`, `ISERROR`.

Aggregation:

`SUM`, `SUMIF`, `SUMIFS`, `AVERAGE`, `AVERAGEIF`, `AVERAGEIFS`, `COUNT`, `COUNTA`, `COUNTIF`, `COUNTIFS`, `MIN`, `MAX`, `SUMPRODUCT`.

Lookup:

`VLOOKUP`, `XLOOKUP`, `INDEX`, `MATCH`.

Math / text:

`ABS`, `ROUND`, `ROUNDUP`, `ROUNDDOWN`, `INT`, `MOD`, `SQRT`, `EXP`, `LN`, `LOG`, `POWER`, `LEN`, `LEFT`, `RIGHT`, `MID`, `UPPER`, `LOWER`, `TRIM`, `CONCATENATE`.

References:

single cells, ranges, cross-sheet references, absolute references (`$` is normalized), global named ranges, numeric named constants.

## Explicitly unsupported / flagged

- `HLOOKUP`, `GETPIVOTDATA`, `FORECAST.*`, financial functions not listed, array/spill semantics.
- Volatile functions: `NOW`, `TODAY`, `RAND`, `RANDBETWEEN`, `OFFSET`, `INDIRECT`, `CELL`, `INFO`, `WEBSERVICE`, `RTD`.
- External workbook references (`[Book.xlsx]...`).
- Circular references and their transitive dependents.
- Pivot tables (detected and reported; not executed).
- Whole-column/row references beyond the configured cell limit.
- Excel error literals and unsupported syntax.

Unsupported cells do not silently enter the generated logic. Any labelled output dependent on an unsupported or circular cell is blocked and listed in the generation warnings.

## Semantic notes

- Blank numeric cells behave as zero when referenced arithmetically, matching Excel. **Missing required named inputs are not zero** — `calculate` returns `{"_status": "MISSING_INPUTS", "_missing": [...]}`.
- `IF`/`IFERROR` evaluation is lazy, matching Excel branch semantics.
- Python `round` is not used for Excel `ROUND`; the generated helper rounds half away from zero.
- Excel string comparison is case-insensitive in the helper layer.
- Division-by-zero is contained per cell; `IFERROR` catches it where present. Uncaught errors surface as failed comparisons rather than being hidden.
- Named ranges are resolved to their referenced cells for generated Python. The Excel comparator pins named ranges during test overrides to avoid stale-name artefacts.
- Dates and date arithmetic are not part of the supported numeric subset.

## Validation contract

- Comparison engine: `formulas==1.3.4`.
- Tolerances: default absolute `0.01`, relative `0.0001`; recorded in the validation report.
- A conversion is only `VALIDATED` when **all** comparisons pass.
- Engine load/calculation failure produces `ENGINE_ERROR` and requires human review; it never produces a pass.
- Mismatches show Excel value, Python value, cell and dataset.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/logic/excel/conversions` | Conversion history |
| `POST` | `/api/logic/excel/conversions` | Upload and start Workflow D |
| `GET` | `/api/logic/excel/conversions/{id}` | Detail + validation + generated code |
| `GET` | `/api/logic/excel/conversions/{id}/code` | Generated Python |
| `GET` | `/api/logic/excel/conversions/{id}/report` | Business logic Markdown report |
| `POST` | `/api/logic/excel/conversions/{id}/approve` | Approve/reject; approval resumes Workflow D and activates the rule |

## Limitations

- The supported function set is deliberately conservative. Broader coverage should be added only with independent test evidence.
- Numeric tolerance does not validate business meaning: an approved conversion can still encode a stale assumption. Human review remains mandatory.
- Workbook layout changes after conversion are not automatically tracked; re-upload and re-validate.
- The converter does not reproduce Excel formatting, macros, external links, pivot caches or Data Tables.
