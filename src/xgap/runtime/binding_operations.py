"""Nullable aggregation and ordering over declared binding values."""

from decimal import Decimal, localcontext
from functools import cmp_to_key
import math
from typing import Any, Mapping

from xgap.runtime.scalars import (decimal_binding, numeric, representative_key,
    scalar_order_key, stable_text, value_key, row_key)


def aggregate_rows(parameters: Mapping[str, Any], rows: tuple[dict, ...]) -> tuple[dict, ...]:
    group_by, aggregations = parameters.get("group_by"), parameters.get("aggregations")
    if (not isinstance(group_by, (list, tuple)) or
        (not group_by and not parameters.get("allow_global", False)) or
        any(not isinstance(f, str) or not f for f in group_by) or len(set(group_by)) != len(group_by)):
        raise ValueError("coordinator_group_aggregate requires unique nonempty group_by fields")
    if not isinstance(aggregations, Mapping) or not aggregations:
        raise ValueError("coordinator_group_aggregate requires a nonempty aggregations mapping")
    normalized = {}
    for output, spec in aggregations.items():
        if not isinstance(output, str) or not output or output in group_by or not isinstance(spec, Mapping):
            raise ValueError("aggregate output fields must be distinct nonempty mappings")
        if set(spec) - {"op", "field", "distinct"}:
            raise ValueError("Unknown aggregate option")
        op, field, distinct = spec.get("op"), spec.get("field"), spec.get("distinct", False)
        if op not in ("sum", "count", "min", "max"):
            raise ValueError("aggregate op must be sum, count, min, or max")
        if type(distinct) is not bool:
            raise ValueError("Aggregate distinct must be boolean")
        if (field is not None and (not isinstance(field, str) or not field)) or (op != "count" and field is None):
            raise ValueError(f"aggregate '{op}' requires a field")
        normalized[output] = op, field, distinct
    groups = {}
    for row in rows:
        if any(field not in row for field in group_by):
            raise ValueError("aggregate group fields are missing")
        values = tuple(row[field] for field in group_by)
        key = tuple(value_key(value) for value in values)
        if key not in groups:
            groups[key] = (values, [])
        previous, members = groups[key]
        if tuple(map(representative_key, values)) < tuple(map(representative_key, previous)):
            groups[key] = (values, members)
        members.append(row)
    if not group_by and not groups:
        groups[()] = ((), [])
    result = []
    for key in sorted(groups):
        group, members = groups[key]
        output = dict(zip(group_by, group))
        for name, (op, field, distinct) in normalized.items():
            if field is None:
                values = list(members)
            else:
                if any(field not in row for row in members):
                    raise ValueError(f"aggregate field '{field}' is missing")
                values = [row[field] for row in members if row[field] is not None]
            for value in values:
                row_key(value) if field is None else value_key(value)
            # Validate and retain the numeric promotion domain before DISTINCT.
            numbers = [numeric(v) for v in values] if op == "sum" else []
            if op == "sum" and any(n is None for n in numbers):
                raise ValueError(f"aggregate field '{field}' must be numeric")
            domain = {n.kind for n in numbers}
            if distinct:
                unique = {}
                for value in values:
                    k = row_key(value) if field is None else value_key(value)
                    if k not in unique or (stable_text(value) < stable_text(unique[k]) if field is None
                                          else representative_key(value) < representative_key(unique[k])):
                        unique[k] = value
                values = list(unique.values())
            if op == "count":
                output[name] = len(values)
            elif op == "sum":
                numbers = [numeric(v) for v in values]
                if not numbers:
                    total = 0
                elif domain == {"integer"}:
                    total = sum(int(n.value) for n in numbers)
                else:
                    # Preserve existing decimal-value accumulation for floats,
                    # with sufficient precision for exact aligned addition.
                    digits = max(n.value.adjusted() for n in numbers) - min(n.value.as_tuple().exponent for n in numbers)
                    with localcontext() as context:
                        context.prec = max(1, digits + len(str(len(numbers))) + 3)
                        exact = sum((n.value for n in numbers), Decimal(0))
                    if "float" in domain:
                        total = float(exact)
                        if not math.isfinite(total):
                            raise ValueError("Aggregate floating result must be finite")
                    else:
                        total = decimal_binding(exact)
                output[name] = total
            elif values:
                best = (min if op == "min" else max)(scalar_order_key(v) for v in values)
                output[name] = min((v for v in values if scalar_order_key(v) == best), key=representative_key)
            else:
                output[name] = None
        result.append(output)
    return tuple(result)


def sort_rows(parameters: Mapping[str, Any], rows: tuple[dict, ...]) -> tuple[dict, ...]:
    order_by, limit = parameters.get("order_by"), parameters.get("limit")
    if not isinstance(order_by, (list, tuple)) or not order_by:
        raise ValueError("coordinator_sort_limit requires a nonempty order_by list")
    if "limit" not in parameters or limit is not None and (type(limit) is not int or limit <= 0):
        raise ValueError("coordinator_sort_limit requires a positive integer limit or explicit null for all rows")
    ordering = []
    for spec in order_by:
        if not isinstance(spec, Mapping) or set(spec) - {"field", "direction", "nulls"}:
            raise ValueError("Invalid sort field options")
        field, direction, nulls = spec.get("field"), spec.get("direction", "asc"), spec.get("nulls", "last")
        if not isinstance(field, str) or not field or direction not in ("asc", "desc") or nulls not in ("first", "last"):
            raise ValueError("sort fields require a field, asc/desc and nulls first/last")
        ordering.append((field, direction, nulls))
    if len({field for field, _, _ in ordering}) != len(ordering):
        raise ValueError("sort field names must be unique")
    for row in rows:
        for field, _, _ in ordering:
            if field not in row:
                raise ValueError(f"sort field '{field}' is missing")
            scalar_order_key(row[field])
    def compare(left, right):
        for field, direction, nulls in ordering:
            a, b = left[field], right[field]
            if a is None or b is None:
                order = ((a is None) - (b is None)) * (1 if nulls == "last" else -1)
            else:
                ak, bk = scalar_order_key(a), scalar_order_key(b)
                order = ((ak > bk) - (ak < bk)) * (1 if direction == "asc" else -1)
            if order:
                return order
        a, b = stable_text(left), stable_text(right)
        return (a > b) - (a < b)
    return tuple(sorted((dict(row) for row in rows), key=cmp_to_key(compare))[:limit])
