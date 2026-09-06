"""Read-only reconstruction audit for one F2C11 physical-baseline analysis."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_baselines import (
    DIRECT_FAMILY_BASELINE_ANALYSIS_SCHEMA_VERSION,
    analyze_m15_direct_family_baselines,
)


DIRECT_FAMILY_BASELINE_AUDIT_SCHEMA_VERSION = (
    "m15-f2c11-physical-baseline-evidence-audit-v1"
)


@dataclass(frozen=True)
class DirectFamilyBaselineEvidenceCheck:
    check_id: str
    passed: bool
    expected: Any
    observed: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class M15DirectFamilyBaselineEvidenceAudit:
    success: bool
    run_root: Path
    analysis_file: Path
    checks: tuple[DirectFamilyBaselineEvidenceCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DIRECT_FAMILY_BASELINE_AUDIT_SCHEMA_VERSION,
            "success": self.success,
            "run_root": str(self.run_root),
            "analysis_file": str(self.analysis_file),
            "check_count": len(self.checks),
            "failed_check_ids": list(self.failed_check_ids),
            "checks": [item.to_dict() for item in self.checks],
            "run_tree_mutated": self.run_tree_mutated,
            "paper_result": False,
        }


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"run tree contains a symbolic link: {path}")
        if not path.is_file():
            continue
        relative = str(path.relative_to(root)).encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _read_object(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file():
        return {}, "missing_or_nonregular"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, f"invalid_json:{exc}"
    if not isinstance(payload, Mapping):
        return {}, "not_object"
    return dict(payload), "ok"


def audit_m15_direct_family_baselines(
    *,
    run_root: str | Path,
    source_audit: Mapping[str, Any] | str | Path,
    policy: Mapping[str, Any] | str | Path,
    analysis: str | Path,
) -> M15DirectFamilyBaselineEvidenceAudit:
    """Recompute the F2C11 analysis without mutating its F2C10D source."""

    selected_root = Path(run_root)
    if selected_root.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    root = selected_root.resolve()
    if not root.is_dir():
        raise ValueError("run_root must be a real directory")
    selected_analysis = Path(analysis)
    if selected_analysis.is_symlink():
        raise ValueError("analysis must not be a symbolic link")
    analysis_path = selected_analysis.resolve()
    before = _tree_digest(root)
    checks: list[DirectFamilyBaselineEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            DirectFamilyBaselineEvidenceCheck(
                check_id=check_id,
                passed=observed == expected,
                expected=expected,
                observed=observed,
            )
        )

    observed, state = _read_object(analysis_path)
    check("artifact.analysis", "ok", state)
    check(
        "artifact.outside_source_run",
        True,
        analysis_path != root and root not in analysis_path.parents,
    )
    expected: dict[str, Any] = {}
    try:
        expected = analyze_m15_direct_family_baselines(
            run_root=root,
            audit=source_audit,
            policy=policy,
        )
        check("reconstruction.success", True, True)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        check("reconstruction.success", True, f"invalid:{exc}")

    check("analysis.exact", expected, observed)
    check(
        "analysis.schema",
        DIRECT_FAMILY_BASELINE_ANALYSIS_SCHEMA_VERSION,
        observed.get("schema_version"),
    )
    observed_body = {
        key: value for key, value in observed.items() if key != "analysis_sha256"
    }
    check(
        "analysis.hash",
        content_hash(observed_body),
        observed.get("analysis_sha256"),
    )
    check("analysis.task_count", 10, len(observed.get("per_semantic_task", [])))
    check("analysis.method_count", 5, len(observed.get("methods", {})))
    check("boundary.backend_calls", 0, observed.get("analysis_backend_calls"))
    check("boundary.llm_calls", 0, observed.get("analysis_llm_calls"))
    check(
        "boundary.ontology_calls",
        0,
        observed.get("analysis_ontology_service_calls"),
    )
    check(
        "boundary.current_query_observations",
        [],
        observed.get("current_query_observation_operations"),
    )
    check(
        "boundary.online_results",
        False,
        observed.get("online_selected_results_used_for_selection_or_metrics"),
    )
    check(
        "boundary.answer_rows",
        False,
        observed.get("answer_row_values_used_for_selection_or_metrics"),
    )
    check("boundary.confirmatory", False, observed.get("confirmatory_statistics"))
    check("boundary.paper_result", False, observed.get("paper_result"))

    after = _tree_digest(root)
    mutated = before != after
    check("run_tree.unchanged", False, mutated)
    return M15DirectFamilyBaselineEvidenceAudit(
        success=bool(checks) and all(item.passed for item in checks),
        run_root=root,
        analysis_file=analysis_path,
        checks=tuple(checks),
        run_tree_mutated=mutated,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--source-audit", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        run_root = Path(args.run_root).resolve()
        audit = audit_m15_direct_family_baselines(
            run_root=run_root,
            source_audit=args.source_audit,
            policy=args.policy,
            analysis=args.analysis,
        )
        payload = audit.to_dict()
        if args.output:
            output = Path(args.output).resolve()
            if output == run_root or run_root in output.parents:
                raise ValueError("audit output must remain outside the source run tree")
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists():
                raise ValueError(f"audit output exists: {output}")
            output.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if audit.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
