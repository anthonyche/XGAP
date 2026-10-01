"""Offline M15-E2 demo using the frozen CWRU bundle and a fake transport."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.experiments.bundles import ModelBundle
from xgap.llm import build_openai_compatible_resolution_provider
from xgap.semantic import SemanticHoleKind
from xgap.tools import ResolutionCandidateRequest, ToolContext


class OfflineTransport:
    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        payload = kwargs["payload"]
        user_request = json.loads(payload["messages"][1]["content"])
        return {
            "id": "offline-demo-request",
            "choices": [
                {
                    "message": {
                        "content": {
                            "hole_id": user_request["hole_id"],
                            "candidate_ids": [user_request["candidate_ids"][0]],
                        }
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 32,
                "completion_tokens": 6,
                "total_tokens": 38,
            },
        }


def main() -> None:
    bundle = ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_m15e2")
    provider = build_openai_compatible_resolution_provider(
        bundle,
        OfflineTransport(),
    )
    os.environ.setdefault("XGAP_LLM_API_KEY", "offline-demo-key")
    response = provider.resolve(
        ResolutionCandidateRequest(
            program_id="m15-e2-demo",
            hole_id="transfer-predicate",
            hole_kind=SemanticHoleKind.PREDICATE,
            mention="funded",
            candidate_ids=("predicate:paid", "predicate:invested"),
            question="Which companies did Alice fund?",
            hard_constraints_sha256="0" * 64,
            max_candidates=2,
        ),
        ToolContext("m15-e2-demo", 1, "propose-predicate"),
    )
    artifact = provider.last_invocation
    assert artifact is not None
    print(
        json.dumps(
            {
                "bundle_hash": bundle.bundle_hash,
                "response": response.to_dict(),
                "invocation": artifact.to_dict(),
                "network_used": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
