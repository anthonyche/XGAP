"""Shared local-catalog records with stable identity across CLI/import use.

Keep these records outside executable builder modules: ``python -m`` loads a
builder as ``__main__``, while its collaborators import the canonical module.
Both paths must use the same classes without weakening input validation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any


@dataclass(frozen=True)
class InferenceQuestion:
    question_id: str
    text: str

    @property
    def question_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LocalCandidateMatch:
    question_id: str
    entity_id: str
    matched_label: str
    normalized_label: str
    match_type: str
    score: float
    source_shard: str
    rank: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "entity_id": self.entity_id,
            "matched_label": self.matched_label,
            "normalized_label": self.normalized_label,
            "match_type": self.match_type,
            "lexical_score": self.score,
            "source_shard": str(self.source_shard),
            "rank": self.rank,
        }
