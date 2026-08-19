"""Post-build empirical compatibility report for an archival Freebase catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2
from xgap.experiments.grailqa_reachability import (
    CatalogUniverse,
    ReferenceRequirements,
    load_catalog_universe,
    reference_requirements,
)


def build_compatibility_report(
    *,
    supported_questions_path: str | Path,
    pilot_references_path: str | Path,
    catalog_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Compare evaluation-only references with a completed catalog universe."""

    supported = tuple(
        reference_requirements(
            {
                "question_id": item["question_id"],
                "pattern_query": item["reference_interpretation"],
            }
        )
        for item in _read_jsonl(Path(supported_questions_path))
    )
    pilot = tuple(
        reference_requirements(item)
        for item in _read_jsonl(Path(pilot_references_path))
    )
    required_entities = {
        entity for item in (*supported, *pilot) for entity in item.entities
    }
    universe = load_catalog_universe(
        catalog_root, required_entity_ids=required_entities
    )
    catalog = GrailQAInferenceCatalogV2.load(catalog_root)
    report = {
        "schema_version": "m13e3a-freebase-archival-compatibility-v1",
        "status": "complete",
        "catalog_id": universe.catalog_id,
        "catalog_hash": universe.catalog_hash,
        "gold_usage": "evaluation_only_after_catalog_construction",
        "inference_gold_usage": False,
        "pilot_reference_mids": _entity_coverage(pilot, universe),
        "supported_workload_reference_mids": _entity_coverage(supported, universe),
        "ontology_relations_absent": sorted(
            set(catalog.ontology.relations) - set(universe.relations)
        ),
        "ontology_types_absent": sorted(
            set(catalog.ontology.classes) - set(universe.types)
        ),
        "joint_catalog_coverage": {
            "frozen_pilot": _joint_coverage(pilot, universe),
            "all_supported": _joint_coverage(supported, universe),
        },
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _entity_coverage(
    requirements: Iterable[ReferenceRequirements], universe: CatalogUniverse
) -> dict[str, Any]:
    required = sorted({entity for item in requirements for entity in item.entities})
    missing = sorted(set(required) - set(universe.entities))
    return {
        "required_unique_count": len(required),
        "missing_unique_count": len(missing),
        "missing_ids": missing,
    }


def _joint_coverage(
    requirements: Sequence[ReferenceRequirements], universe: CatalogUniverse
) -> dict[str, Any]:
    covered = sum(
        set(item.entities).issubset(universe.entities)
        and set(item.relations).issubset(universe.relations)
        and set(item.types).issubset(universe.types)
        for item in requirements
    )
    return {
        "count": covered,
        "total": len(requirements),
        "ratio": covered / len(requirements) if requirements else None,
    }


def _read_jsonl(path: Path) -> tuple[Mapping[str, Any], ...]:
    with path.open(encoding="utf-8") as handle:
        return tuple(json.loads(line) for line in handle if line.strip())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supported-questions", required=True)
    parser.add_argument("--pilot-references", required=True)
    parser.add_argument("--catalog-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    report = build_compatibility_report(
        supported_questions_path=args.supported_questions,
        pilot_references_path=args.pilot_references,
        catalog_root=args.catalog_root,
        output_path=args.output,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
