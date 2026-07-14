from __future__ import annotations

import sys
from pathlib import Path as FilePath

ROOT = FilePath(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.compilers import compile_cypher
from xgap.llm import MockStructuredCandidateProvider, plan_from_question, validate_candidate


def demo_payload() -> dict[str, object]:
    return {
        "provider_id": "mock",
        "model": "mock-structured-candidates",
        "candidates": [
            {
                "candidate_id": "alice-risk-transfer",
                "confidence": 0.82,
                "pattern_query": {
                    "path_var": "p",
                    "source": {
                        "var": "person",
                        "label": "Person",
                        "properties": {"name": "Alice"},
                    },
                    "expr": {
                        "kind": "rel",
                        "edge": {"label": "OWNS", "direction": "OUT"},
                    },
                    "target": {
                        "var": "company",
                        "label": "Company",
                    },
                    "selector": {"kind": "ALL"},
                    "restrictor": "TRAIL",
                },
            }
        ],
    }


def main() -> None:
    provider = MockStructuredCandidateProvider(payload=demo_payload())
    candidates = plan_from_question(
        "Find companies connected to Alice through ownership.",
        provider=provider,
    )
    candidate = candidates[0]
    report = validate_candidate(candidate)

    print("M10 candidate validation:")
    print(report.to_json())

    artifact = compile_cypher(candidate.pattern_query)
    print("\nM9 Cypher artifact from M10 candidate:")
    print(artifact.text)


if __name__ == "__main__":
    main()
