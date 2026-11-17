"""Excel formula tokenizer, parser and Python translator.

Supports the deterministic subset of Excel used in management models:
arithmetic, comparisons, IF/IFERROR/IFS, SUM/SUMIF(S), COUNTIF(S),
AVERAGEIF(S), VLOOKUP/XLOOKUP, INDEX/MATCH, ROUND*, MIN/MAX/ABS, boolean
logic, text concatenation, named ranges and cross-sheet references.

Anything outside the subset raises ``UnsupportedFormula`` and is reported for
human review rather than guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from openpyxl.workbook.defined_name import DefinedName

CELL_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")
RANGE_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+):\$?([A-Za-z]{1,3})\$?(\d+)$")
SHEET_PREFIX_RE = re.compile(r"^(?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_.]*))!")
IDENT_RE = re.compile(r"[A-Za-z_\\][A-Za-z0-9_.\\]*")
NUMBER_RE = re.compile(r"\d+(?:\.\d*)?(?:[eE][+-]?\d+)?")
ERROR_RE = re.compile(r"#(?:N/A|DIV/0!|VALUE!|REF!|NAME\?|NUM!|NULL!|GETTING_DATA)")
MAX_RANGE_CELLS = 5000

SUPPORTED_FUNCTIONS = {
    "IF",
    "IFERROR",
    "IFNA",
    "IFS",
    "AND",
    "OR",
    "NOT",
    "SUM",
    "SUMIF",
    "SUMIFS",
    "SUMPRODUCT",
    "AVERAGE",
    "AVERAGEIF",
    "AVERAGEIFS",
    "COUNT",
    "COUNTA",
    "COUNTIF",
    "COUNTIFS",
    "MIN",
    "MAX",
    "ABS",
    "ROUND",
    "ROUNDUP",
    "ROUNDDOWN",
    "INT",
    "MOD",
    "SQRT",
    "EXP",
    "LN",
    "LOG",
    "POWER",
    "VLOOKUP",
    "XLOOKUP",
    "INDEX",
    "MATCH",
    "ISBLANK",
    "ISNUMBER",
    "ISTEXT",
    "ISERROR",
    "LEN",
    "LEFT",
    "RIGHT",
    "MID",
    "UPPER",
    "LOWER",
    "TRIM",
    "CONCATENATE",
}

VOLATILE_FUNCTIONS = {"NOW", "TODAY", "RAND", "RANDBETWEEN", "OFFSET", "INDIRECT", "CELL", "INFO", "WEBSERVICE", "RTD"}


class UnsupportedFormula(ValueError):
    def __init__(self, message: str, *, function: str | None = None) -> None:
        super().__init__(message)
        self.function = function


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------
@dataclass
class Token:
    kind: str
    value: str
    position: int


class FormulaTokenizer:
    def __init__(self, formula: str) -> None:
        self.source = formula.lstrip("=")
        self.position = 0
        self.tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        while self.position < len(self.source):
            char = self.source[self.position]
            if char.isspace():
                self.position += 1
                continue
            if char == '"':
                self.tokens.append(Token("STRING", self._read_string(), self.position))
                continue
            if char == "'" or (char.isalpha() and self._looks_like_sheet_ref()):
                sheet_token = self._read_sheet_qualified_ref()
                if sheet_token:
                    continue
            error_match = ERROR_RE.match(self.source, self.position)
            if error_match:
                raise UnsupportedFormula(f"Excel error literal {error_match.group(0)} is not translatable")
            if char in "(),+-*/^&%=<>":
                two = self.source[self.position : self.position + 2]
                if two in {"<=", ">=", "<>"}:
                    self.tokens.append(Token("OP", two, self.position))
                    self.position += 2
                else:
                    self.tokens.append(Token("OP", char, self.position))
                    self.position += 1
                continue
            number_match = NUMBER_RE.match(self.source, self.position)
            if number_match:
                value = number_match.group(0)
                self.tokens.append(Token("NUMBER", value, self.position))
                self.position = number_match.end()
                continue
            cell_match = re.match(r"\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?", self.source[self.position :])
            if cell_match:
                text = cell_match.group(0)
                # Ensure not part of a longer identifier.
                end = self.position + len(text)
                if end >= len(self.source) or not (self.source[end].isalnum() or self.source[end] == "_"):
                    kind = "RANGE" if ":" in text else "CELL"
                    self.tokens.append(Token(kind, text, self.position))
                    self.position = end
                    continue
            ident_match = IDENT_RE.match(self.source, self.position)
            if ident_match:
                text = ident_match.group(0)
                self.tokens.append(Token("IDENT", text, self.position))
                self.position = ident_match.end()
                continue
            if char == "[":
                raise UnsupportedFormula("External workbook references are not supported")
            raise UnsupportedFormula(f"Unexpected character '{char}' at position {self.position}")
        return self.tokens

    def _looks_like_sheet_ref(self) -> bool:
        match = re.match(r"[A-Za-z_][A-Za-z0-9_.]*!", self.source[self.position :])
        return bool(match)

    def _read_string(self) -> str:
        start = self.position
        self.position += 1
        pieces = []
        while self.position < len(self.source):
            char = self.source[self.position]
            if char == '"':
                if self.position + 1 < len(self.source) and self.source[self.position + 1] == '"':
                    pieces.append('"')
                    self.position += 2
                    continue
                self.position += 1
                return "".join(pieces)
            pieces.append(char)
            self.position += 1
        raise UnsupportedFormula("Unterminated string literal", function=None)

    def _read_sheet_qualified_ref(self) -> Token | None:
        remaining = self.source[self.position :]
        match = re.match(
            r"(?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_.]*))!\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?",
            remaining,
        )
        if not match:
            return None
        text = match.group(0)
        kind = "RANGE" if ":" in text.split("!")[-1] else "CELL"
        self.tokens.append(Token(kind, text, self.position))
        self.position += len(text)
        return self.tokens[-1]


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------
@dataclass
class Node:
    pass


@dataclass
class NumberNode(Node):
    value: float


@dataclass
class StringNode(Node):
    value: str


@dataclass
class BoolNode(Node):
    value: bool


@dataclass
class CellNode(Node):
    sheet: str
    coord: str
    key: str


@dataclass
class RangeNode(Node):
    sheet: str
    start: str
    end: str
    keys: list[str]


@dataclass
class NameNode(Node):
    name: str


@dataclass
class FuncNode(Node):
    name: str
    args: list[Node | None]


@dataclass
class BinaryNode(Node):
    op: str
    left: Node
    right: Node


@dataclass
class UnaryNode(Node):
    op: str
    operand: Node


@dataclass
class PercentNode(Node):
    operand: Node


@dataclass
class EmptyNode(Node):
    pass


@dataclass
class ParsedFormula:
    ast: Node
    functions: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    named_ranges: list[str] = field(default_factory=list)


class FormulaParser:
    def __init__(self, tokens: list[Token], current_sheet: str, defined_names: dict[str, str]) -> None:
        self.tokens = tokens
        self.position = 0
        self.current_sheet = current_sheet
        self.defined_names = defined_names
        self.functions: list[str] = []
        self.references: list[str] = []
        self.named_ranges: list[str] = []

    def parse(self) -> Node:
        node = self._parse_comparison()
        if self.position < len(self.tokens):
            raise UnsupportedFormula(f"Unexpected token '{self.tokens[self.position].value}'")
        return node

    def _peek(self) -> Token | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _take(self) -> Token:
        token = self.tokens[self.position]
        self.position += 1
        return token

    def _accept(self, value: str) -> bool:
        token = self._peek()
        if token and token.value == value:
            self.position += 1
            return True
        return False

    def _parse_comparison(self) -> Node:
        left = self._parse_concat()
        while True:
            token = self._peek()
            if token and token.value in {"=", "<>", "<", ">", "<=", ">="}:
                op = self._take().value
                right = self._parse_concat()
                left = BinaryNode(op, left, right)
            else:
                return left

    def _parse_concat(self) -> Node:
        left = self._parse_additive()
        while self._accept("&"):
            left = BinaryNode("&", left, self._parse_additive())
        return left

    def _parse_additive(self) -> Node:
        left = self._parse_multiplicative()
        while True:
            token = self._peek()
            if token and token.value in {"+", "-"}:
                op = self._take().value
                left = BinaryNode(op, left, self._parse_multiplicative())
            else:
                return left

    def _parse_multiplicative(self) -> Node:
        left = self._parse_power()
        while True:
            token = self._peek()
            if token and token.value in {"*", "/"}:
                op = self._take().value
                left = BinaryNode(op, left, self._parse_power())
            else:
                return left

    def _parse_power(self) -> Node:
        left = self._parse_unary()
        if self._accept("^"):
            left = BinaryNode("^", left, self._parse_power())
        return left

    def _parse_unary(self) -> Node:
        token = self._peek()
        if token and token.value in {"+", "-"}:
            op = self._take().value
            return UnaryNode(op, self._parse_unary())
        return self._parse_postfix()

    def _parse_postfix(self) -> Node:
        node = self._parse_primary()
        while self._accept("%"):
            node = PercentNode(node)
        return node

    def _parse_primary(self) -> Node:
        token = self._peek()
        if token is None:
            raise UnsupportedFormula("Unexpected end of formula")
        if token.kind == "NUMBER":
            self._take()
            return NumberNode(float(token.value))
        if token.kind == "STRING":
            self._take()
            return StringNode(token.value)
        if token.value == "(":
            self._take()
            node = self._parse_comparison()
            if not self._accept(")"):
                raise UnsupportedFormula("Missing closing parenthesis")
            return node
        if token.kind == "CELL":
            self._take()
            sheet, coord = self._resolve_sheet(token.value)
            key = f"{sheet}!{coord}"
            self.references.append(key)
            return CellNode(sheet, coord, key)
        if token.kind == "RANGE":
            self._take()
            sheet, coords = self._resolve_sheet(token.value, range_token=True)
            start, end = coords.split(":")
            keys = expand_range_keys(sheet, start, end)
            self.references.extend(keys)
            return RangeNode(sheet, start, end, keys)
        if token.kind == "IDENT":
            name = self._take().value
            if self._accept("("):
                return self._parse_function(name)
            upper = name.upper()
            if upper in {"TRUE", "FALSE"}:
                return BoolNode(upper == "TRUE")
            if name in self.defined_names:
                target = self.defined_names[name]
                self.named_ranges.append(name)
                sheet, ref, is_range = resolve_defined_name(target, self.current_sheet)
                if re.match(r"^-?\d+(?:\.\d+)?$", ref):
                    return NumberNode(float(ref))
                if is_range:
                    start, end = ref.split(":")
                    keys = expand_range_keys(sheet, start, end)
                    self.references.extend(keys)
                    return RangeNode(sheet, start, end, keys)
                self.references.append(f"{sheet}!{ref}")
                return CellNode(sheet, ref, f"{sheet}!{ref}")
            if upper in SUPPORTED_FUNCTIONS:
                raise UnsupportedFormula(f"Function {upper} must be called with parentheses")
            raise UnsupportedFormula(f"Unknown name '{name}'", function=name)
        raise UnsupportedFormula(f"Unexpected token '{token.value}'")

    def _parse_function(self, name: str) -> Node:
        normalized = name.upper().replace("_XLFN.", "")
        if normalized.startswith("_XLWS."):
            normalized = normalized[6:]
        if normalized in VOLATILE_FUNCTIONS:
            raise UnsupportedFormula(f"Volatile function {normalized} is not deterministic", function=normalized)
        if normalized not in SUPPORTED_FUNCTIONS:
            raise UnsupportedFormula(f"Unsupported function {normalized}", function=normalized)
        self.functions.append(normalized)
        args: list[Node | None] = []
        if self._accept(")"):
            return FuncNode(normalized, args)
        while True:
            if self._accept(","):
                args.append(None)
                continue
            if self._peek() and self._peek().value == ")":
                args.append(None)
                self._take()
                break
            args.append(self._parse_comparison())
            if self._accept(","):
                continue
            if self._accept(")"):
                break
            raise UnsupportedFormula(f"Missing comma or closing parenthesis in {normalized}")
        return FuncNode(normalized, args)

    def _resolve_sheet(self, text: str, range_token: bool = False) -> tuple[str, str]:
        match = SHEET_PREFIX_RE.match(text)
        if match:
            sheet = (match.group(1) or match.group(2) or "").replace("''", "'")
            rest = text[match.end() :]
        else:
            sheet = self.current_sheet
            rest = text
        rest = rest.replace("$", "")
        if range_token:
            range_match = RANGE_RE.match(rest)
            if not range_match:
                raise UnsupportedFormula(f"Invalid range '{text}'")
            return sheet, f"{range_match.group(1).upper()}{range_match.group(2)}:{range_match.group(3).upper()}{range_match.group(4)}"
        cell_match = CELL_RE.match(rest)
        if not cell_match:
            raise UnsupportedFormula(f"Invalid cell reference '{text}'")
        return sheet, f"{cell_match.group(1).upper()}{cell_match.group(2)}"


def resolve_defined_name(value: Any, current_sheet: str) -> tuple[str, str, bool]:
    """Resolve a defined name to (sheet, cell_or_range, is_range)."""
    text = str(value).strip().replace("$", "")
    if text.startswith("="):
        text = text[1:]
    if "!" in text:
        match = SHEET_PREFIX_RE.match(text)
        if not match:
            raise UnsupportedFormula(f"Cannot resolve defined name target '{text}'")
        sheet = (match.group(1) or match.group(2) or "").replace("''", "'")
        ref = text[match.end() :]
    else:
        sheet, ref = current_sheet, text
    if RANGE_RE.match(ref):
        return sheet, ref.replace("$", ""), True
    if CELL_RE.match(ref):
        return sheet, ref.replace("$", ""), False
    if re.match(r"^-?\d+(?:\.\d+)?$", ref):
        return sheet, ref, False
    raise UnsupportedFormula(f"Defined name target '{text}' is not a cell, range or constant")


def column_to_index(column: str) -> int:
    result = 0
    for char in column.upper():
        result = result * 26 + (ord(char) - 64)
    return result


def index_to_column(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def expand_range_keys(sheet: str, start: str, end: str) -> list[str]:
    start_match = CELL_RE.match(start)
    end_match = CELL_RE.match(end)
    if not start_match or not end_match:
        raise UnsupportedFormula(f"Invalid range {start}:{end}")
    start_col = column_to_index(start_match.group(1))
    start_row = int(start_match.group(2))
    end_col = column_to_index(end_match.group(1))
    end_row = int(end_match.group(2))
    if start_col > end_col:
        start_col, end_col = end_col, start_col
    if start_row > end_row:
        start_row, end_row = end_row, start_row
    count = (end_col - start_col + 1) * (end_row - start_row + 1)
    if count > MAX_RANGE_CELLS:
        raise UnsupportedFormula(f"Range {start}:{end} exceeds the {MAX_RANGE_CELLS}-cell limit")
    keys = []
    for row in range(start_row, end_row + 1):
        for col in range(start_col, end_col + 1):
            keys.append(f"{sheet}!{index_to_column(col)}{row}")
    return keys


# ---------------------------------------------------------------------------
# Translator
# ---------------------------------------------------------------------------
class PythonTranslator:
    def __init__(self, current_sheet: str, defined_names: dict[str, str]) -> None:
        self.current_sheet = current_sheet
        self.defined_names = defined_names

    def translate(self, node: Node) -> str:
        if isinstance(node, NumberNode):
            value = node.value
            return str(int(value)) if value.is_integer() else repr(value)
        if isinstance(node, StringNode):
            return repr(node.value)
        if isinstance(node, BoolNode):
            return "True" if node.value else "False"
        if isinstance(node, CellNode):
            return f'_c(cells, {node.key!r})'
        if isinstance(node, RangeNode):
            raise UnsupportedFormula("A range cannot be used as a scalar value")
        if isinstance(node, NameNode):
            raise UnsupportedFormula(f"Unresolved name {node.name}")
        if isinstance(node, EmptyNode):
            return "None"
        if isinstance(node, PercentNode):
            return f"({self.translate(node.operand)} / 100)"
        if isinstance(node, UnaryNode):
            return f"({node.op}{self.translate(node.operand)})"
        if isinstance(node, BinaryNode):
            op = node.op
            if op == "=":
                op = "=="
            elif op == "<>":
                op = "!="
            elif op == "^":
                op = "**"
            elif op == "&":
                return f"_cat({self.translate(node.left)}, {self.translate(node.right)})"
            return f"({self.translate(node.left)} {op} {self.translate(node.right)})"
        if isinstance(node, FuncNode):
            return self._translate_function(node)
        raise UnsupportedFormula(f"Unsupported formula node {type(node).__name__}")

    def _require_range(self, node: Node | None, function: str) -> RangeNode | list[str]:
        if isinstance(node, RangeNode):
            return node
        if isinstance(node, CellNode):
            return [node.key]
        raise UnsupportedFormula(f"{function} requires a cell range argument")

    def _keys(self, node: Node | None, function: str) -> list[str]:
        resolved = self._require_range(node, function)
        if isinstance(resolved, RangeNode):
            return resolved.keys
        return resolved

    def _table(self, node: Node | None, function: str) -> list[list[str]]:
        keys = self._keys(node, function)
        rows: list[list[str]] = []
        current_row: list[str] = []
        current_row_number = None
        for key in keys:
            coord = key.split("!")[-1]
            match = CELL_RE.match(coord)
            row_number = int(match.group(2)) if match else 0
            if current_row_number is None:
                current_row_number = row_number
            if row_number != current_row_number:
                rows.append(current_row)
                current_row = []
                current_row_number = row_number
            current_row.append(key)
        if current_row:
            rows.append(current_row)
        return rows

    def _arg(self, node: Node | None) -> str:
        return "None" if node is None else self.translate(node)

    def _translate_function(self, node: FuncNode) -> str:
        name = node.name
        args = node.args

        def require_args(count: int, optional: int = 0) -> None:
            if len(args) < count or len(args) > count + optional:
                raise UnsupportedFormula(f"{name} expects {count}..{count + optional} arguments", function=name)

        if name == "IF":
            require_args(2, 1)
            condition = self.translate(args[0])  # type: ignore[arg-type]
            true_value = self._arg(args[1])
            false_value = self._arg(args[2]) if len(args) > 2 else "None"
            return f"_if({condition}, lambda: {true_value}, lambda: {false_value})"
        if name in {"IFERROR", "IFNA"}:
            require_args(2)
            return f"_iferror(lambda: {self.translate(args[0])}, lambda: {self.translate(args[1])})"  # type: ignore[arg-type]
        if name == "IFS":
            if len(args) < 2 or len(args) % 2 != 0:
                raise UnsupportedFormula("IFS requires condition/value pairs", function=name)
            expression = "None"
            for index in range(len(args) - 2, -1, -2):
                condition = self.translate(args[index])  # type: ignore[arg-type]
                value = self._arg(args[index + 1])
                expression = f"_if({condition}, lambda: {value}, lambda: {expression})"
            return expression
        if name in {"AND", "OR"}:
            values = ", ".join(f"lambda: {self._arg(arg)}" for arg in args)
            helper = "_and" if name == "AND" else "_or"
            return f"{helper}([{values}])"
        if name == "NOT":
            require_args(1)
            return f"(not {self.translate(args[0])})"  # type: ignore[arg-type]
        if name in {"SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA"}:
            lists = []
            for arg in args:
                if isinstance(arg, (RangeNode, CellNode)):
                    lists.append(f"_vals(cells, {self._keys(arg, name)!r})")
                elif arg is not None:
                    lists.append(f"[{self.translate(arg)}]")
            if name == "COUNTA":
                raw_lists = []
                for arg in args:
                    if isinstance(arg, (RangeNode, CellNode)):
                        raw_lists.append(f"_rawvals(cells, {self._keys(arg, name)!r})")
                    elif arg is not None:
                        raw_lists.append(f"[{self.translate(arg)}]")
                return f"_counta({' + '.join(raw_lists) if raw_lists else '[]'})"
            combined = " + ".join(lists) if lists else "[]"
            helper = {
                "SUM": "_sum",
                "AVERAGE": "_avg",
                "MIN": "_min",
                "MAX": "_max",
                "COUNT": "_count",
            }[name]
            return f"{helper}({combined})"
        if name in {"SUMIF", "AVERAGEIF", "COUNTIF"}:
            require_args(2, 1)
            criteria_keys = self._keys(args[0], name)
            criteria = self._arg(args[1])
            if name == "COUNTIF":
                return f"_countif(cells, {criteria_keys!r}, {criteria})"
            sum_keys = self._keys(args[2], name) if len(args) > 2 and args[2] else criteria_keys
            helper = "_sumif" if name == "SUMIF" else "_averageif"
            return f"{helper}(cells, {criteria_keys!r}, {sum_keys!r}, {criteria})"
        if name in {"SUMIFS", "AVERAGEIFS", "COUNTIFS"}:
            if name == "COUNTIFS":
                if len(args) < 2 or len(args) % 2 != 0:
                    raise UnsupportedFormula("COUNTIFS requires range/criteria pairs", function=name)
                pairs = []
                for index in range(0, len(args), 2):
                    pairs.append(f"[{self._keys(args[index], name)!r}, {self._arg(args[index + 1])}]")
                return f"_countifs(cells, [{', '.join(pairs)}])"
            if len(args) < 3 or len(args) % 2 == 0:
                raise UnsupportedFormula(f"{name} requires a sum range plus range/criteria pairs", function=name)
            sum_keys = self._keys(args[0], name)
            pairs = []
            for index in range(1, len(args), 2):
                pairs.append(f"[{self._keys(args[index], name)!r}, {self._arg(args[index + 1])}]")
            helper = "_sumifs" if name == "SUMIFS" else "_averageifs"
            return f"{helper}(cells, {sum_keys!r}, [{', '.join(pairs)}])"
        if name == "SUMPRODUCT":
            arrays = [f"_vals(cells, {self._keys(arg, name)!r})" for arg in args]
            return f"_sumproduct([{', '.join(arrays)}])"
        if name == "VLOOKUP":
            require_args(3, 1)
            approximate = self._arg(args[3]) if len(args) > 3 else "True"
            return (
                f"_vlookup({self.translate(args[0])}, cells, {self._table(args[1], name)!r}, "  # type: ignore[arg-type]
                f"{self.translate(args[2])}, {approximate})"  # type: ignore[arg-type]
            )
        if name == "XLOOKUP":
            require_args(3, 2)
            fallback = self._arg(args[3]) if len(args) > 3 else "None"
            return (
                f"_xlookup({self.translate(args[0])}, cells, {self._keys(args[1], name)!r}, "  # type: ignore[arg-type]
                f"{self._keys(args[2], name)!r}, {fallback})"
            )
        if name == "INDEX":
            require_args(2, 1)
            row = self.translate(args[1])  # type: ignore[arg-type]
            col = self.translate(args[2]) if len(args) > 2 and args[2] is not None else "None"  # type: ignore[arg-type]
            return f"_index(cells, {self._table(args[0], name)!r}, {row}, {col})"
        if name == "MATCH":
            require_args(2, 1)
            match_type = self.translate(args[2]) if len(args) > 2 and args[2] is not None else "1"  # type: ignore[arg-type]
            return f"_match({self.translate(args[0])}, _rawvals(cells, {self._keys(args[1], name)!r}), {match_type})"  # type: ignore[arg-type]
        if name in {"ROUND", "ROUNDUP", "ROUNDDOWN"}:
            require_args(2)
            helper = {"ROUND": "_round", "ROUNDUP": "_roundup", "ROUNDDOWN": "_rounddown"}[name]
            return f"{helper}({self.translate(args[0])}, {self.translate(args[1])})"  # type: ignore[arg-type]
        if name == "ABS":
            require_args(1)
            return f"abs({self.translate(args[0])})"  # type: ignore[arg-type]
        if name == "INT":
            require_args(1)
            return f"_int({self.translate(args[0])})"  # type: ignore[arg-type]
        if name == "MOD":
            require_args(2)
            return f"_mod({self.translate(args[0])}, {self.translate(args[1])})"  # type: ignore[arg-type]
        if name == "SQRT":
            require_args(1)
            return f"_sqrt({self.translate(args[0])})"  # type: ignore[arg-type]
        if name == "EXP":
            require_args(1)
            return f"_exp({self.translate(args[0])})"  # type: ignore[arg-type]
        if name == "LN":
            require_args(1)
            return f"_ln({self.translate(args[0])})"  # type: ignore[arg-type]
        if name == "LOG":
            require_args(1, 1)
            base = self.translate(args[1]) if len(args) > 1 and args[1] else "10"
            return f"_log({self.translate(args[0])}, {base})"  # type: ignore[arg-type]
        if name == "POWER":
            require_args(2)
            return f"({self.translate(args[0])} ** {self.translate(args[1])})"  # type: ignore[arg-type]
        if name in {"ISBLANK", "ISNUMBER", "ISTEXT", "ISERROR"}:
            require_args(1)
            return f"_{name.lower()}(lambda: {self.translate(args[0])})"  # type: ignore[arg-type]
        if name == "LEN":
            require_args(1)
            return f"_len({self.translate(args[0])})"  # type: ignore[arg-type]
        if name in {"LEFT", "RIGHT"}:
            require_args(1, 1)
            optional = self.translate(args[1]) if len(args) > 1 and args[1] else "1"  # type: ignore[arg-type]
            helper = "_left" if name == "LEFT" else "_right"
            return f"{helper}({self.translate(args[0])}, {optional})"  # type: ignore[arg-type]
        if name == "MID":
            require_args(3)
            return f"_mid({self.translate(args[0])}, {self.translate(args[1])}, {self.translate(args[2])})"  # type: ignore[arg-type]
        if name in {"UPPER", "LOWER", "TRIM"}:
            require_args(1)
            helper = {"UPPER": "_upper", "LOWER": "_lower", "TRIM": "_trim"}[name]
            return f"{helper}({self.translate(args[0])})"  # type: ignore[arg-type]
        if name == "CONCATENATE":
            parts = [self.translate(arg) for arg in args if arg is not None]
            if not parts:
                return "''"
            result = parts[0]
            for part in parts[1:]:
                result = f"_cat({result}, {part})"
            return result
        raise UnsupportedFormula(f"Unsupported function {name}", function=name)


def extract_formula_metadata(formula: str, current_sheet: str, defined_names: dict[str, str]) -> ParsedFormula:
    tokens = FormulaTokenizer(formula).tokenize()
    parser = FormulaParser(tokens, current_sheet, defined_names)
    ast_node = parser.parse()
    return ParsedFormula(
        ast=ast_node,
        functions=sorted(set(parser.functions)),
        references=sorted(set(parser.references)),
        named_ranges=sorted(set(parser.named_ranges)),
    )


def translate_formula(formula: str, current_sheet: str, defined_names: dict[str, str]) -> dict[str, Any]:
    tokens = FormulaTokenizer(formula).tokenize()
    parser = FormulaParser(tokens, current_sheet, defined_names)
    ast_node = parser.parse()
    translator = PythonTranslator(current_sheet, defined_names)
    code = translator.translate(ast_node)
    return {
        "code": code,
        "functions": sorted(set(parser.functions)),
        "references": sorted(set(parser.references)),
        "named_ranges": sorted(set(parser.named_ranges)),
    }
