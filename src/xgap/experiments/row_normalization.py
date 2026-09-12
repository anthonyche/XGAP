"""Prespecified row-value equivalence; never reorder or remove duplicate rows."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


SCHEMA = 'xgap-row-normalization-v1'
KINDS = {'text', 'integer', 'decimal3-half-up'}


def validate_normalization(specification):
    if (not isinstance(specification, dict) or set(specification) != {'schema_version', 'fields'}
            or specification['schema_version'] != SCHEMA):
        raise ValueError('Invalid row normalization contract')
    fields = specification['fields']
    if (not isinstance(fields, dict) or not 1 <= len(fields) <= 16
            or any(not isinstance(k, str) or not k or not isinstance(v, str) or v not in KINDS for k, v in fields.items())):
        raise ValueError('Invalid normalized field schema')
    return fields


def normalize_rows(rows, specification):
    fields = validate_normalization(specification)
    if not isinstance(rows, list): raise ValueError('Expected a list of answer rows')
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(fields):
            raise ValueError('Answer fields differ from the declared normalization schema')
        normalized = {}
        for field, kind in fields.items():
            value = row[field]
            if kind == 'text':
                if not isinstance(value, str): raise ValueError('Text identity must remain a string')
                normalized[field] = value
                continue
            if type(value) not in (str, int, float) or len(str(value)) > 128:
                raise ValueError('Expected a bounded finite numeric value')
            try:
                number = Decimal(str(value))
                if not number.is_finite(): raise ValueError('Nonfinite numeric answer')
                if abs(number) > Decimal('1e30'): raise ValueError('Number exceeds the normalization magnitude bound')
                if kind == 'integer':
                    if number != number.to_integral_value(): raise ValueError('Nonintegral count or distance')
                    normalized[field] = int(number)
                else:
                    rounded = number.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
                    normalized[field] = format(rounded.copy_abs() if not rounded else rounded, '.3f')
            except (InvalidOperation, OverflowError) as error:
                raise ValueError('Invalid normalized number') from error
        result.append(normalized)
    return result
