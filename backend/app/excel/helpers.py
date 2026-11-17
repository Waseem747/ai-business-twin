"""Runtime helpers injected into generated Excel-equivalent Python modules.

Kept deliberately dependency-free so generated code can execute inside the
business-rule sandbox.
"""
from __future__ import annotations

HELPER_CODE = r'''
def _c(cells, key):
    return cells[key] if key in cells else 0

def _num(value):
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except Exception:
        return 0.0

def _text(value):
    if value is None:
        return ""
    return str(value)

def _safe(fn):
    try:
        return fn()
    except Exception:
        return None

def _if(condition, when_true, when_false):
    return when_true() if condition else when_false()

def _iferror(value, fallback):
    try:
        result = value()
        if result is None:
            return fallback()
        return result
    except Exception:
        return fallback()

def _and(functions):
    for fn in functions:
        if not fn():
            return False
    return True

def _or(functions):
    for fn in functions:
        if fn():
            return True
    return False

def _vals(cells, keys):
    values = []
    for key in keys:
        value = _c(cells, key)
        if isinstance(value, bool):
            values.append(1.0 if value else 0.0)
        elif isinstance(value, (int, float)):
            values.append(float(value))
    return values

def _rawvals(cells, keys):
    return [_c(cells, key) for key in keys]

def _sum(values):
    total = 0.0
    for value in values:
        total += value
    return total

def _avg(values):
    return _sum(values) / len(values) if values else None

def _min(values):
    if not values:
        return 0
    result = values[0]
    for value in values[1:]:
        if value < result:
            result = value
    return result

def _max(values):
    if not values:
        return 0
    result = values[0]
    for value in values[1:]:
        if value > result:
            result = value
    return result

def _count(values):
    return len(values)

def _counta(values):
    count = 0
    for value in values:
        if value is not None and value != "":
            count += 1
    return count

def _round(value, digits):
    number = _num(value)
    places = int(_num(digits))
    factor = 10 ** places
    scaled = number * factor
    if scaled >= 0:
        return int(scaled + 0.5) / factor
    return int(scaled - 0.5) / factor

def _roundup(value, digits):
    number = _num(value)
    places = int(_num(digits))
    factor = 10 ** places
    scaled = number * factor
    whole = int(scaled)
    if scaled >= 0 and whole < scaled:
        whole += 1
    return whole / factor

def _rounddown(value, digits):
    number = _num(value)
    places = int(_num(digits))
    factor = 10 ** places
    scaled = number * factor
    whole = int(scaled)
    if scaled < 0 and whole > scaled:
        whole -= 1
    return whole / factor

def _int(value):
    number = _num(value)
    whole = int(number)
    if number < 0 and whole > number:
        whole -= 1
    return whole

def _mod(value, divisor):
    number = _num(value)
    div = _num(divisor)
    if div == 0:
        return None
    return number - div * _int(number / div)

def _sqrt(value):
    number = _num(value)
    if number < 0:
        raise ValueError("sqrt domain")
    guess = number
    if guess == 0:
        return 0.0
    for _ in range(40):
        guess = 0.5 * (guess + number / guess)
    return guess

def _exp(value):
    number = _num(value)
    result = 1.0
    term = 1.0
    for index in range(1, 40):
        term = term * number / index
        result += term
    return result

def _ln(value):
    number = _num(value)
    if number <= 0:
        raise ValueError("ln domain")
    y = (number - 1) / (number + 1)
    y2 = y * y
    result = 0.0
    term = y
    for index in range(0, 60):
        result += term / (2 * index + 1)
        term *= y2
    return 2 * result

def _log(value, base):
    return _ln(value) / _ln(base)

def _cat(left, right):
    return _text(left) + _text(right)

def _len(value):
    return len(_text(value))

def _left(value, count):
    return _text(value)[:int(_num(count))]

def _right(value, count):
    count = int(_num(count))
    return _text(value)[-count:] if count else ""

def _mid(value, start, count):
    start = int(_num(start)) - 1
    count = int(_num(count))
    return _text(value)[start:start + count]

def _upper(value):
    return _text(value).upper()

def _lower(value):
    return _text(value).lower()

def _trim(value):
    return _text(value).strip()

def _isblank(value):
    try:
        result = value()
        return result is None or result == ""
    except Exception:
        return True

def _isnumber(value):
    try:
        result = value()
        return isinstance(result, (int, float)) and not isinstance(result, bool)
    except Exception:
        return False

def _istext(value):
    try:
        return isinstance(value(), str)
    except Exception:
        return False

def _iserror(value):
    try:
        return value() is None
    except Exception:
        return True

def _to_number(text):
    try:
        return float(text)
    except Exception:
        return None

def _criteria_match(value, criteria):
    if criteria is None:
        return value is None or value == ""
    if isinstance(criteria, str):
        for operator in (">=", "<=", "<>", ">", "<"):
            if criteria.startswith(operator):
                operand = criteria[len(operator):]
                target = _to_number(operand)
                if target is not None:
                    number = _num(value)
                    if operator == ">=":
                        return number >= target
                    if operator == "<=":
                        return number <= target
                    if operator == ">":
                        return number > target
                    if operator == "<":
                        return number < target
                    return number != target
                if operator == "<>":
                    return _text(value) != operand
                if operator == "=":
                    return _text(value) == operand
                return False
        if "*" in criteria or "?" in criteria:
            return _wildcard(_text(value), criteria)
        target = _to_number(criteria)
        if target is not None and criteria != "":
            return _num(value) == target
        if criteria == "":
            return value is None or value == ""
        return _text(value).lower() == criteria.lower()
    target = _to_number(criteria)
    if target is not None:
        return _num(value) == target
    return _text(value) == _text(criteria)

def _wildcard(text, pattern):
    if not pattern:
        return text == ""
    first = pattern[0]
    if first == "*":
        return _wildcard(text, pattern[1:]) or (bool(text) and _wildcard(text[1:], pattern))
    if first == "?":
        return bool(text) and _wildcard(text[1:], pattern[1:])
    if not text:
        return False
    return text[0].lower() == first.lower() and _wildcard(text[1:], pattern[1:])

def _sumif(cells, criteria_keys, sum_keys, criteria):
    total = 0.0
    for index in range(min(len(criteria_keys), len(sum_keys))):
        if _criteria_match(_c(cells, criteria_keys[index]), criteria):
            total += _num(_c(cells, sum_keys[index]))
    return total

def _averageif(cells, criteria_keys, sum_keys, criteria):
    total = 0.0
    count = 0
    for index in range(min(len(criteria_keys), len(sum_keys))):
        if _criteria_match(_c(cells, criteria_keys[index]), criteria):
            total += _num(_c(cells, sum_keys[index]))
            count += 1
    return total / count if count else None

def _countif(cells, criteria_keys, criteria):
    count = 0
    for key in criteria_keys:
        if _criteria_match(_c(cells, key), criteria):
            count += 1
    return count

def _sumifs(cells, sum_keys, pairs):
    total = 0.0
    for index in range(len(sum_keys)):
        matches = True
        for pair in pairs:
            keys = pair[0]
            criteria = pair[1]
            if index >= len(keys) or not _criteria_match(_c(cells, keys[index]), criteria):
                matches = False
                break
        if matches:
            total += _num(_c(cells, sum_keys[index]))
    return total

def _averageifs(cells, sum_keys, pairs):
    total = 0.0
    count = 0
    for index in range(len(sum_keys)):
        matches = True
        for pair in pairs:
            keys = pair[0]
            if index >= len(keys) or not _criteria_match(_c(cells, keys[index]), pair[1]):
                matches = False
                break
        if matches:
            total += _num(_c(cells, sum_keys[index]))
            count += 1
    return total / count if count else None

def _countifs(cells, pairs):
    if not pairs:
        return 0
    length = len(pairs[0][0])
    count = 0
    for index in range(length):
        matches = True
        for pair in pairs:
            keys = pair[0]
            if index >= len(keys) or not _criteria_match(_c(cells, keys[index]), pair[1]):
                matches = False
                break
        if matches:
            count += 1
    return count

def _sumproduct(arrays):
    if not arrays:
        return 0
    length = min(len(array) for array in arrays)
    total = 0.0
    for index in range(length):
        product = 1.0
        for array in arrays:
            product *= array[index]
        total += product
    return total

def _lookup_equal(left, right):
    if isinstance(left, str) or isinstance(right, str):
        return _text(left).lower() == _text(right).lower()
    return _num(left) == _num(right)

def _vlookup(value, cells, table, index, approximate):
    if not table:
        return None
    column = int(_num(index)) - 1
    if column < 0:
        return None
    selected = None
    for row in table:
        if column >= len(row):
            continue
        if approximate:
            if _num(row[0]) <= _num(value):
                selected = row
        elif _lookup_equal(_c(cells, row[0]), value):
            selected = row
            break
    if selected is None and approximate:
        selected = table[0]
    if selected is None or column >= len(selected):
        return None
    return _c(cells, selected[column])

def _xlookup(value, cells, lookup_keys, return_keys, fallback):
    for index in range(min(len(lookup_keys), len(return_keys))):
        if _lookup_equal(_c(cells, lookup_keys[index]), value):
            return _c(cells, return_keys[index])
    return fallback

def _index(cells, table, row, col):
    row_number = int(_num(row))
    if row_number < 1 or not table:
        return None
    if col is None:
        if len(table) == 1:
            row_data = table[0]
            return _c(cells, row_data[row_number - 1]) if row_number <= len(row_data) else None
        if row_number <= len(table):
            return _c(cells, table[row_number - 1][0])
        return None
    column_number = int(_num(col))
    if row_number > len(table) or column_number < 1 or column_number > len(table[0]):
        return None
    return _c(cells, table[row_number - 1][column_number - 1])

def _match(value, values, match_type):
    mode = int(_num(match_type))
    if mode == 0:
        for index, candidate in enumerate(values):
            if _lookup_equal(candidate, value):
                return index + 1
        return None
    best = None
    best_value = None
    for index, candidate in enumerate(values):
        number = _num(candidate)
        if mode > 0 and number <= _num(value):
            if best_value is None or number >= best_value:
                best_value = number
                best = index + 1
        elif mode < 0 and number >= _num(value):
            if best_value is None or number <= best_value:
                best_value = number
                best = index + 1
    return best
'''
