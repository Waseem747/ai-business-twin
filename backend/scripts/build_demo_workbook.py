"""Create the fictional Northwind Retail margin workbook used by the MVP demo.

The workbook contains real Excel formulas (cross-sheet references, IF/VLOOKUP/
INDEX-MATCH/SUMIFS/COUNTIFS, named ranges) plus deliberately unsupported and
circular cells to exercise the conversion governance path.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.table import Table, TableStyleInfo

OUTPUT = Path(__file__).resolve().parents[1] / "data" / "demo" / "Northwind_Margin_Model.xlsx"

NAVY = "0F2742"
BLUE = "1D5FA8"
LIGHT = "EAF1F8"
GOLD = "C9A227"
GREY = "6B7785"

thin = Side(style="thin", color="C9D3DF")
border = Border(left=thin, right=thin, top=thin, bottom=thin)


def style_header(cell) -> None:
    cell.font = Font(bold=True, color="FFFFFF", size=10)
    cell.fill = PatternFill("solid", fgColor=NAVY)
    cell.alignment = Alignment(vertical="center")
    cell.border = border


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    # ---------------------------------------------------------------- Instructions
    ws = wb.active
    ws.title = "Instructions"
    ws.column_dimensions["A"].width = 100
    ws["A1"] = "NORTHWIND RETAIL CO. - GROSS MARGIN MODEL"
    ws["A1"].font = Font(bold=True, size=18, color=NAVY)
    ws["A3"] = "PURPOSE"
    ws["A3"].font = Font(bold=True, color=BLUE)
    ws["A4"] = (
        "This workbook is the demo business logic source for the AI Business Twin Excel conversion engine. "
        "It estimates gross margin, contribution and projected cash for a fictional retail company."
    )
    ws["A6"] = "SHEETS"
    ws["A6"].font = Font(bold=True, color=BLUE)
    ws["A7"] = "Inputs - driver values (named ranges are defined for each driver)."
    ws["A8"] = "Transactions - detailed channel transactions used by SUMIFS and COUNTIFS."
    ws["A9"] = "ChannelRates - commission lookup table used by VLOOKUP and INDEX/MATCH."
    ws["A10"] = "MarginModel - the calculation model and report outputs."
    ws["A11"] = "CircularExample - intentionally circular cells used to test detection; not used by the model."
    ws["A13"] = "DEMO DATA - fictional values, not a real company."
    ws["A13"].font = Font(bold=True, color="B3261E")
    ws["A15"] = "The workbook deliberately includes one unsupported formula (HLOOKUP) to demonstrate review controls."
    ws["A16"] = "All converted logic requires human approval before activation."
    ws.column_dimensions["A"].width = 110

    # ---------------------------------------------------------------- Inputs
    ws = wb.create_sheet("Inputs")
    ws["A1"] = "Northwind Retail - Driver Inputs (DEMO)"
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    headers = ["Driver", "Value", "Unit", "Notes"]
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=col, value=header)
        style_header(cell)
    rows = [
        ("Revenue - current month", 561000, "USD", "POS + online + wholesale, October"),
        ("Cost of goods sold", 386000, "USD", "Landed supplier cost after freight"),
        ("Marketing spend", 64600, "USD", "Paid media and promotions"),
        ("Fixed operating costs", 104000, "USD", "Payroll, occupancy and other fixed costs"),
        ("Units sold", 7800, "units", "Total units across channels"),
        ("Discount depth", 11.8, "%", "Weighted average promotional discount"),
        ("Revenue target", 575000, "USD", "Board-approved monthly target"),
        ("Supplier rebate", 2.5, "%", "Annual volume rebate accrual"),
        ("Opening cash", 627000, "USD", "Cash at start of month"),
        ("Minimum cash policy", 250000, "USD", "Treasury policy floor"),
    ]
    for index, (label, value, unit, note) in enumerate(rows, start=4):
        ws.cell(row=index, column=1, value=label)
        value_cell = ws.cell(row=index, column=2, value=value)
        value_cell.border = border
        ws.cell(row=index, column=3, value=unit)
        ws.cell(row=index, column=4, value=note).font = Font(color=GREY, size=9)
        if unit == "%":
            value_cell.number_format = "0.0%"
            value_cell.value = value / 100
        else:
            value_cell.number_format = '#,##0.00'
    # Named ranges over the actual value cells.
    for name, row in [
        ("Revenue_Current", 4),
        ("COGS_Current", 5),
        ("Marketing_Current", 6),
        ("Fixed_Costs", 7),
        ("Units_Sold", 8),
        ("Discount_Depth_Pct", 9),
        ("RevenueTarget", 10),
        ("Supplier_Rebate_Pct", 11),
        ("Opening_Cash", 12),
        ("Minimum_Cash_Policy", 13),
    ]:
        wb.defined_names.add(DefinedName(name, attr_text=f"Inputs!$B${row}"))
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 55
    ws.freeze_panes = "A4"

    # ---------------------------------------------------------------- Transactions
    ws = wb.create_sheet("Transactions")
    t_headers = ["Date", "Channel", "Revenue", "Gross Profit", "Order ID"]
    for col, header in enumerate(t_headers, start=1):
        style_header(ws.cell(row=1, column=col, value=header))
    channels = ["Online", "Stores", "Online", "Wholesale", "Stores", "Online", "Stores", "Online"]
    start = date(2026, 10, 1)
    for index in range(40):
        row = index + 2
        channel = channels[index % len(channels)]
        revenue = 2400 + (index % 11) * 610 + (1900 if index % 7 == 0 else 0)
        if channel == "Online" and index % 9 == 0:
            revenue += 4200
        margin = {"Online": 0.323, "Stores": 0.344, "Wholesale": 0.247}[channel]
        ws.cell(row=row, column=1, value=start + timedelta(days=index % 28))
        ws.cell(row=row, column=2, value=channel)
        ws.cell(row=row, column=3, value=revenue).number_format = '#,##0'
        ws.cell(row=row, column=4, value=round(revenue * margin, 2)).number_format = '#,##0.00'
        ws.cell(row=row, column=5, value=f"NW-{20260 + index:06d}")
    table = Table(displayName="TransactionsTable", ref="A1:E41")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(table)
    for column, width in {"A": 12, "B": 14, "C": 14, "D": 15, "E": 15}.items():
        ws.column_dimensions[column].width = width
    ws.freeze_panes = "A2"

    # ---------------------------------------------------------------- Channel rates
    ws = wb.create_sheet("ChannelRates")
    for col, header in enumerate(["Channel", "Commission %", "Fulfilment cost/order"], start=1):
        style_header(ws.cell(row=1, column=col, value=header))
    rate_rows = [("Online", 0.18, 3.5), ("Stores", 0.22, 1.2), ("Wholesale", 0.08, 6.0)]
    for index, (channel, commission, fulfilment) in enumerate(rate_rows, start=2):
        ws.cell(row=index, column=1, value=channel)
        ws.cell(row=index, column=2, value=commission).number_format = "0.0%"
        ws.cell(row=index, column=3, value=fulfilment).number_format = '#,##0.00'
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 15
    ws.column_dimensions["C"].width = 22

    # ---------------------------------------------------------------- Margin model
    ws = wb.create_sheet("MarginModel")
    ws["A1"] = "Northwind Retail - Margin & Contribution Model"
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    for col, header in enumerate(["Metric", "Value", "Formula / source"], start=1):
        style_header(ws.cell(row=2, column=col, value=header))
    model_rows = [
        ("Gross margin %", "=IF(Inputs!B4>100000,(Inputs!B4-Inputs!B5)/Inputs!B4*100,0)", "IF(revenue > threshold)"),
        ("Gross profit", "=Inputs!B4-Inputs!B5", "Revenue - COGS"),
        ("Operating expenses", "=Inputs!B6+Inputs!B7", "Marketing + fixed costs"),
        ("Net profit", "=B4-B5", "Gross profit - operating expenses"),
        ("Net margin %", "=IFERROR(B6/Inputs!B4*100,0)", "IFERROR net profit / revenue"),
        ("Target variance", "=Inputs!B4-RevenueTarget", "Revenue - named revenue target"),
        ("Supplier rebate", "=ROUND(Inputs!B4*Supplier_Rebate_Pct/100,2)", "ROUND revenue * rebate %"),
        ("Online revenue", '=SUMIFS(Transactions!C2:C41,Transactions!B2:B41,"Online")', "SUMIFS by channel"),
        ("High-value online orders", '=COUNTIFS(Transactions!B2:B41,"Online",Transactions!C2:C41,">5000")', "COUNTIFS channel + value"),
        ("Online commission %", '=VLOOKUP("Online",ChannelRates!A2:C4,2,FALSE)', "VLOOKUP commission"),
        ("Wholesale commission %", '=INDEX(ChannelRates!B2:B4,MATCH("Wholesale",ChannelRates!A2:A4,0))', "INDEX + MATCH"),
        ("Average commission %", "=AVERAGE(ChannelRates!B2:B4)", "AVERAGE lookup column"),
        ("Commission cost", "=ROUND(B10*B12,2)", "Online revenue * online commission"),
        ("Contribution after commission", "=B4-B15", "Gross profit - commission"),
        ("Projected cash", "=Opening_Cash+B6-B15", "Opening cash + net profit - commission"),
        ("Cash buffer months", "=IFERROR(Inputs!B12/B5,0)", "Opening cash / operating expenses"),
        ("Rebate-adjusted gross profit", "=B4+B9", "Gross profit + supplier rebate"),
        ("Gross margin at +2% price", "=IFERROR((Inputs!B4*1.02-Inputs!B5)/(Inputs!B4*1.02)*100,0)", "Price sensitivity (no volume effect)"),
        ("Revenue per unit", "=IFERROR(Inputs!B4/Inputs!B8,0)", "Revenue / units"),
        ("Rounded margin check", "=ROUNDUP(B3,1)", "ROUNDUP margin to 1 decimal"),
        ("Unsupported rate lookup", '=HLOOKUP("Online",ChannelRates!A1:C2,2,FALSE)', "Unsupported function flagged for review"),
        ("Model label", '=CONCATENATE("Month: ", "October 2026")', "Text concatenation"),
    ]
    for index, (label, formula, source) in enumerate(model_rows, start=3):
        ws.cell(row=index, column=1, value=label)
        formula_cell = ws.cell(row=index, column=2, value=formula)
        formula_cell.border = border
        ws.cell(row=index, column=3, value=source).font = Font(color=GREY, size=9)
        if label in {"Gross margin %", "Net margin %", "Online commission %", "Wholesale commission %", "Average commission %", "Gross margin at +2% price", "Rounded margin check"}:
            formula_cell.number_format = "0.00"
        elif label in {"High-value online orders"}:
            formula_cell.number_format = "0"
        else:
            formula_cell.number_format = '#,##0.00'
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 48
    ws.freeze_panes = "A3"

    # ---------------------------------------------------------------- Circular example
    ws = wb.create_sheet("CircularExample")
    ws["A1"] = "Circular reference test (intentionally invalid)"
    ws["A1"].font = Font(bold=True, color="B3261E")
    ws["A3"] = "Cell A"
    ws["B3"] = "=C3+1"
    ws["A4"] = "Cell B"
    ws["C3"] = "=B3+1"
    ws["A6"] = "These cells are excluded from conversion and reported by the dependency graph."

    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = False

    wb.save(OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    print(build())
