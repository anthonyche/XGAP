"""A cell ID is a bounded single path component, not a programming identifier."""
import re


def validate_cell_id(value):
    # An alphanumeric first byte excludes '.', '..', hidden names and options.
    # Decimal scales are legitimate identities; separators/control bytes are not.
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}', value):
        raise ValueError('Invalid cell ID: ' + repr(value)[:120])
    return value
