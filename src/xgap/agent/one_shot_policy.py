"""Versioned bounded modes; defaults are prototype settings, not tuned results."""

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class OneShotPolicy:
    mode: str = "precision"
    candidate_cap: int = 3
    max_operators: int = 64
    max_holes: int = 16
    max_candidates_per_hole: int = 64
    use_ontology: bool = True
    max_local_options: int = 64
    max_physical_candidates: int = 256
    max_remote_calls: int = 16
    max_parallelism: int = 4
    max_bindings: int = 10000
    max_binding_bytes: int = 1048576
    quality_penalty_ms: float = 1000.0
    unknown_quality_proxy: float = 0.5
    retrieval_rows_per_relation: int | None = None
    grounding_ranking: str = "artifact_entry_order_v1"
    max_quality_deficit: float | None = None
    retrieval_scope: str = "all_relations_v1"

    def __post_init__(self):
        if self.mode not in ("precision", "performance"):
            raise ValueError("One-shot mode must be precision or performance")
        caps = {"candidate_cap": 8, "max_operators": 64, "max_holes": 64,
                "max_candidates_per_hole": 256, "max_local_options": 64,
                "max_physical_candidates": 1024, "max_remote_calls": 64,
                "max_parallelism": 16, "max_bindings": 1000000,
                "max_binding_bytes": 16 * 1048576}
        for name, maximum in caps.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be an integer in [1,{maximum}]")
        if type(self.use_ontology) is not bool:
            raise ValueError("use_ontology must be boolean")
        for name in ("quality_penalty_ms", "unknown_quality_proxy"):
            value = getattr(self, name)
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.unknown_quality_proxy > 1:
            raise ValueError("Unknown quality fallback must lie in [0,1]")
        if self.retrieval_rows_per_relation is not None:
            if (self.mode != "performance" or type(self.retrieval_rows_per_relation) is not int
                    or not 1 <= self.retrieval_rows_per_relation <= 1_000_000):
                raise ValueError("Relationship retrieval budget requires performance mode and 1..1000000 rows")
        if self.grounding_ranking not in ("artifact_entry_order_v1", "canonical_context_v1"):
            raise ValueError("Unknown one-shot grounding ranking")
        if self.grounding_ranking != "artifact_entry_order_v1" and self.mode != "precision":
            raise ValueError("Contextual grounding ranking requires precision mode")
        if self.max_quality_deficit is not None:
            value = self.max_quality_deficit
            if (self.mode != "precision" or type(value) not in (float, int)
                    or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("Quality deficit requires precision mode and a finite value in [0,1]")
        if self.retrieval_scope not in ("all_relations_v1", "bind_after_anchor_v1"):
            raise ValueError("Unknown relationship retrieval scope")
        if self.retrieval_scope != "all_relations_v1" and self.retrieval_rows_per_relation is None:
            raise ValueError("Contextual retrieval scope requires a relationship row budget")

    @classmethod
    def for_mode(cls, mode):
        if mode == "performance":
            return cls(mode=mode, candidate_cap=1, max_candidates_per_hole=8,
                       use_ontology=False, quality_penalty_ms=0.0)
        return cls(mode=mode)

    def to_dict(self):
        body = asdict(self)
        bounded = self.retrieval_rows_per_relation is not None
        if not bounded:
            body.pop("retrieval_rows_per_relation")  # Preserve old request/replay identities.
        advanced = (self.grounding_ranking != "artifact_entry_order_v1" or self.max_quality_deficit is not None
                    or self.retrieval_scope != "all_relations_v1")
        if self.grounding_ranking == "artifact_entry_order_v1":
            body.pop("grounding_ranking")
        if self.max_quality_deficit is None:
            body.pop("max_quality_deficit")
        if self.retrieval_scope == "all_relations_v1":
            body.pop("retrieval_scope")
        version = "v3" if advanced else "v2" if bounded else "v1"
        return {"schema_version": "xgap-one-shot-policy-" + version, **body,
                "quality_proxy_calibrated": False, "final_plan_executions": 1,
                "online_profile_calls": 0, "automatic_retries": 0}
