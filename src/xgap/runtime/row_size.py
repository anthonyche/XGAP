"""Exact canonical JSON byte counts without constructing another whole row.

This is telemetry, not an alternative row encoding. Structured values and
Decimals use the canonical encoder; scalar strings use the same ASCII escaping.
No row/value cache survives mutation or retains unbounded payloads.
"""
from json.encoder import encode_basestring_ascii
from xgap.runtime.scalars import stable_text


def encoded_row_size(row):
    if type(row) is not dict or any(type(k) is not str for k in row):
        return len(stable_text(row).encode())
    size=2+max(0,len(row)-1)
    for key,value in row.items():
        size+=len(encode_basestring_ascii(key))+1
        kind=type(value)
        if kind is str:size+=len(encode_basestring_ascii(value))
        elif value is None:size+=4
        elif kind is bool:size+=4 if value else 5
        elif kind is int:size+=len(str(value))
        else:size+=len(stable_text(value).encode())
    return size
