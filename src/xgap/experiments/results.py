"""Result normalization for backend smoke queries."""

from __future__ import annotations

from typing import Any, Iterable


SMOKE_RESULT_FIELDS = ("company", "amount", "currency", "occurred_on")


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _normalize_amount(value: Any) -> int | float | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        return text
    if numeric.is_integer():
        return int(numeric)
    return numeric


def normalize_smoke_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize financial-risk smoke rows from Neo4j or SPARQL outputs."""

    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                "company": _first_present(row, "company", "companyName"),
                "amount": _normalize_amount(_first_present(row, "amount")),
                "currency": _first_present(row, "currency"),
                "occurred_on": _first_present(row, "occurred_on", "occurredOn"),
            }
        )
    return sorted(
        normalized,
        key=lambda item: (
            "" if item["company"] is None else str(item["company"]),
            "" if item["occurred_on"] is None else str(item["occurred_on"]),
        ),
    )
