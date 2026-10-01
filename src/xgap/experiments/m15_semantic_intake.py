"""Controlled M15-E3 intake-to-resolution development path."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.agent import (
    GoalLoop,
    InMemoryStore,
    SelectiveResolutionConfig,
    SelectiveSemanticResolutionPolicy,
    build_selective_resolution_goal,
    selective_resolution_environment,
)
from xgap.semantic import DeterministicSemanticIntake
from xgap.tools import (
    ArtifactCatalogProvider,
    ArtifactOntologyProvider,
    ExplicitUserSelectionProvider,
    ToolRegistry,
    artifact_catalog_tool,
    artifact_ontology_tool,
    explicit_user_clarification_tool,
)


def run_semantic_intake(
    *,
    question: str,
    intake_path: str | Path,
    catalog_path: str | Path,
    ontology_path: str | Path,
    user_selections: Mapping[str, str] | None = None,
    user_source_id: str = "explicit-user-input",
) -> dict[str, Any]:
    """Compile a request and run the bounded E1 policy with local E3 tools."""

    intake = DeterministicSemanticIntake.from_path(intake_path)
    intake_result = intake.compile(question)
    catalog = ArtifactCatalogProvider(catalog_path)
    ontology = ArtifactOntologyProvider(ontology_path)

    registry = ToolRegistry()
    registry.register(artifact_catalog_tool(catalog))
    registry.register(artifact_ontology_tool(ontology))
    if user_selections:
        registry.register(
            explicit_user_clarification_tool(
                ExplicitUserSelectionProvider(
                    user_selections,
                    source_id=user_source_id,
                )
            )
        )

    memory = InMemoryStore()
    config = SelectiveResolutionConfig(
        use_catalog=True,
        use_ontology=True,
        use_llm=False,
        max_candidates_per_hole=8,
    )
    goal = build_selective_resolution_goal(intake_result.program, config)
    state = GoalLoop().run(
        goal,
        SelectiveSemanticResolutionPolicy(
            intake_result.program,
            question,
            config,
        ),
        selective_resolution_environment(
            registry,
            memory=memory,
            metadata={
                "intake_template_sha256": intake.artifact_sha256,
                "catalog_sha256": catalog.artifact_sha256,
                "ontology_sha256": ontology.artifact_sha256,
            },
        ),
    )
    observations = [
        item.payload
        for item in state.observations
        if item.kind == "tool_result"
    ]
    return {
        "schema_version": "m15-e3-semantic-intake-run-v1",
        "intake": intake_result.to_dict(),
        "goal_state": state.to_dict(),
        "execution_memory": [record.to_dict() for record in memory.records()],
        "cost": {
            "tool_calls": state.tool_calls,
            "external_calls": int(
                sum(item.get("metrics", {}).get("external_calls", 0.0) for item in observations)
            ),
            "llm_calls": 0,
            "catalog_artifact_reads": sum(
                entry.tool_name == "semantic.catalog.lookup" for entry in state.trace
            ),
            "ontology_artifact_reads": sum(
                entry.tool_name == "semantic.ontology.lookup" for entry in state.trace
            ),
        },
        "artifacts": {
            "intake_template_sha256": intake.artifact_sha256,
            "catalog_sha256": catalog.artifact_sha256,
            "ontology_sha256": ontology.artifact_sha256,
        },
        "claim_boundary": {
            "controlled_development_artifacts": True,
            "general_nl_understanding": False,
            "ontology_truth_claim": False,
            "backend_calls": 0,
            "paper_result": False,
        },
        "paper_result": False,
    }


def _selections(values: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        hole_id, separator, candidate_id = value.partition("=")
        if not separator or not hole_id.strip() or not candidate_id.strip():
            raise ValueError("--selection must use HOLE_ID=CANDIDATE_ID")
        if hole_id in result:
            raise ValueError("--selection hole IDs must be unique")
        result[hole_id] = candidate_id
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True)
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--selection", action="append", default=[])
    args = parser.parse_args(argv)
    result = run_semantic_intake(
        question=args.question,
        intake_path=args.intake,
        catalog_path=args.catalog,
        ontology_path=args.ontology,
        user_selections=_selections(args.selection),
        user_source_id="explicit-cli-user-input",
    )
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result["goal_state"]["status"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
