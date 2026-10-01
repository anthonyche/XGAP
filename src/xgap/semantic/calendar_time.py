"""Bounded local-calendar millisecond values; no timezone or precision guessing."""

from datetime import datetime
import re


MILLISECOND_PATTERN = (
    r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01]) "
    r"([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,3})?$"
)
_PATTERN = re.compile(MILLISECOND_PATTERN)


def canonical_timestamp_ms(value):
    """Pad omitted fractional zeros only after exact format/calendar validation."""
    if not isinstance(value, str) or not 19 <= len(value) <= 23 or not _PATTERN.fullmatch(value):
        return None
    seconds, _, fraction = value.partition('.')
    try:
        datetime.strptime(seconds, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return seconds + '.' + fraction.ljust(3, '0')
