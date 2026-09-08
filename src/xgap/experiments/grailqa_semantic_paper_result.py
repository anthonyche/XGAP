"""Admit one fully audited GrailQA semantic run as paper evidence.

This finalizer is deliberately read-only with respect to the source run.  It
does not import the model runner, statistics producer, or either independent
auditor.  A result is promoted only when the authority-gated 150-query run,
its independent run audit, the frozen query-level analysis, and the
independent analysis reconstruction all bind the same immutable identities.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash


PAPER_RESULT_SCHEMA_VERSION = "m13e4-grailqa-semantic-paper-result-v1"
RUN_MANIFEST_SCHEMA_VERSION = "m13e4-grailqa-semantic-paper-run-v2"
RUN_STATUS_SCHEMA_VERSION = "m13e4-grailqa-semantic-paper-run-status-v1"
RUN_AUDIT_SCHEMA_VERSION = (
    "m13e4-grailqa-semantic-paper-run-evidence-audit-v1"
)
ANALYSIS_SCHEMA_VERSION = "m13e4-grailqa-semantic-analysis-v1"
ANALYSIS_AUDIT_SCHEMA_VERSION = (
    "m13e4-grailqa-semantic-analysis-evidence-audit-v1"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class GrailQASemanticPaperResultError(ValueError):
    """Raised when a semantic result cannot cross the paper-evidence gate."""


def _regular_file(path: str | Path, *, name: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise GrailQASemanticPaperResultError(
            f"{name} must be a regular non-symbolic-link file"
        )
    return candidate.resolve()


def _regular_directory(path: str | Path, *, name: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_dir():
        raise GrailQASemanticPaperResultError(
            f"{name} must be a non-symbolic-link directory"
        )
    return candidate.resolve()


def _load_json(path: str | Path, *, name: str) -> dict[str, Any]:
    source = _regular_file(path, name=name)
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise GrailQASemanticPaperResultError(f"{name} must contain an object")
    return dict(value)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, _file_sha256(path))
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _self_hashed(
    value: Mapping[str, Any], *, field: str, name: str
) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    claimed = result.get(field)
    body = {key: item for key, item in result.items() if key != field}
    if (
        not isinstance(claimed, str)
        or _SHA256.fullmatch(claimed) is None
        or content_hash(body) != claimed
    ):
        raise GrailQASemanticPaperResultError(f"{name} self-hash is invalid")
    return result


def _jsonl_object_count(path: Path) -> int:
    count = 0
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GrailQASemanticPaperResultError(
                f"outcome ledger line {line_number} is invalid JSON"
            ) from exc
        if not isinstance(value, Mapping):
            raise GrailQASemanticPaperResultError(
                f"outcome ledger line {line_number} is not an object"
            )
        count += 1
    return count


def _validate_run_audit(
    audit: Mapping[str, Any], *, manifest: Mapping[str, Any], expected_commit: str
) -> dict[str, Any]:
    value = _self_hashed(audit, field="audit_sha256", name="run audit")
    boundary = value.get("claim_boundary")
    if (
        value.get("schema_version") != RUN_AUDIT_SCHEMA_VERSION
        or value.get("success") is not True
        or value.get("failed_check_ids") != []
        or value.get("run_tree_mutated") is not False
        or value.get("expected_commit") != expected_commit
        or value.get("source_run_sha256") != manifest.get("source_run_sha256")
        or value.get("preexecution_admission_sha256")
        != manifest.get("preexecution_admission_sha256")
        or not isinstance(value.get("check_count"), int)
        or int(value["check_count"]) <= 0
        or not isinstance(boundary, Mapping)
        or boundary.get("independent_run_reconstruction") is not True
        or boundary.get("contains_new_measurements") is not False
        or boundary.get("promotes_to_paper_result") is not False
        or boundary.get("paper_result") is not False
        or value.get("paper_result") is not False
    ):
        raise GrailQASemanticPaperResultError(
            "independent run audit does not admit the source run"
        )
    return value


def _validate_analysis(
    analysis: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    protocol: Mapping[str, Any],
    author_selection: Mapping[str, Any],
    outcome_sha256: str,
) -> dict[str, Any]:
    value = _self_hashed(
        analysis, field="analysis_sha256", name="semantic analysis"
    )
    population = value.get("population")
    boundary = value.get("claim_boundary")
    if (
        value.get("schema_version") != ANALYSIS_SCHEMA_VERSION
        or value.get("protocol_sha256") != content_hash(protocol)
        or author_selection.get("protocol_sha256") != content_hash(protocol)
        or value.get("protocol_sha256") != manifest.get("protocol_sha256")
        or value.get("author_selection_sha256")
        != author_selection.get("selection_sha256")
        or value.get("author_selection_sha256")
        != manifest.get("author_selection_sha256")
        or value.get("source_run_sha256") != manifest.get("source_run_sha256")
        or value.get("outcome_ledger_sha256") != outcome_sha256
        or value.get("selected_decisions") != author_selection.get("decisions")
        or not isinstance(population, Mapping)
        or population.get("frozen_query_count") != 150
        or population.get("inferential_unit") != "query"
        or population.get("repetitions_used_as_independent_units") is not False
        or not isinstance(value.get("primary"), Mapping)
        or not isinstance(boundary, Mapping)
        or boundary.get("postinference_gold_used_for_evaluation_only") is not True
        or boundary.get("backend_calls_made_by_analyzer") != 0
        or boundary.get("llm_calls_made_by_analyzer") != 0
        or boundary.get("ontology_service_calls_made_by_analyzer") != 0
        or boundary.get("independent_evidence_audit_required") is not True
        or boundary.get("paper_result") is not False
        or value.get("automatic_retries") != 0
        or value.get("paper_result") is not False
    ):
        raise GrailQASemanticPaperResultError(
            "semantic analysis does not bind the admitted source run"
        )
    return value


def _validate_analysis_audit(
    audit: Mapping[str, Any],
    *,
    analysis_path: Path,
    outcomes_path: Path,
    protocol_path: Path,
    author_selection_path: Path,
    pilot_selection_path: Path,
    source_run_sha256: str,
) -> dict[str, Any]:
    value = _self_hashed(audit, field="audit_sha256", name="analysis audit")
    inputs = value.get("input_sha256")
    boundary = value.get("claim_boundary")
    if (
        value.get("schema_version") != ANALYSIS_AUDIT_SCHEMA_VERSION
        or value.get("success") is not True
        or value.get("failed_check_ids") != []
        or value.get("input_artifacts_mutated") is not False
        or value.get("analysis_exact_match") is not True
        or value.get("expected_source_run_sha256") != source_run_sha256
        or not isinstance(value.get("check_count"), int)
        or int(value["check_count"]) <= 0
        or inputs
        != {
            "outcome_ledger": _file_sha256(outcomes_path),
            "analysis": _file_sha256(analysis_path),
            "protocol": _file_sha256(protocol_path),
            "author_selection": _file_sha256(author_selection_path),
            "pilot_selection": _file_sha256(pilot_selection_path),
        }
        or value.get("external_call_counts")
        != {
            "backend_calls": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
        }
        or not isinstance(boundary, Mapping)
        or boundary.get("independent_analysis_reconstruction") is not True
        or boundary.get("contains_new_measurements") is not False
        or boundary.get("full_150_run_authorized") is not False
        or boundary.get("paper_result") is not False
        or value.get("paper_result") is not False
    ):
        raise GrailQASemanticPaperResultError(
            "independent analysis audit does not admit the analysis"
        )
    return value


def admit_grailqa_semantic_paper_result(
    *,
    run_root: str | Path,
    run_audit_path: str | Path,
    analysis_path: str | Path,
    analysis_audit_path: str | Path,
    protocol_path: str | Path,
    author_selection_path: str | Path,
    repo_root: str | Path,
    expected_commit: str,
) -> dict[str, Any]:
    """Promote one exact, fully audited run without changing its evidence."""

    if _COMMIT.fullmatch(expected_commit) is None:
        raise GrailQASemanticPaperResultError(
            "expected_commit must be exact 40-hex"
        )
    root = _regular_directory(run_root, name="semantic source run")
    repo = _regular_directory(repo_root, name="repo_root")
    before = _tree_snapshot(root)
    manifest = _self_hashed(
        _load_json(root / "run_manifest.json", name="run manifest"),
        field="run_manifest_sha256",
        name="run manifest",
    )
    status = _load_json(root / "run_status.json", name="run status")
    outcomes = _regular_file(
        root / "evaluation/query_outcomes.jsonl", name="outcome ledger"
    )
    protocol_file = _regular_file(protocol_path, name="semantic protocol")
    selection_file = _regular_file(
        author_selection_path, name="author selection"
    )
    pilot_file = _regular_file(
        repo / "datasets/grailqa_pilot_v1/pilot_ids.json",
        name="pilot selection",
    )
    protocol = _load_json(protocol_file, name="semantic protocol")
    selection = _self_hashed(
        _load_json(selection_file, name="author selection"),
        field="selection_sha256",
        name="author selection",
    )
    outcome_sha256 = _file_sha256(outcomes)
    if (
        manifest.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION
        or manifest.get("status") != "success"
        or manifest.get("runner_commit") != expected_commit
        or manifest.get("question_count") != 150
        or manifest.get("outcome_ledger_sha256") != outcome_sha256
        or manifest.get("selection_uses_gold") is not False
        or manifest.get("failures_retained") is not True
        or manifest.get("gold_opened_after_all_inference") is not True
        or manifest.get("inference_seal_written_before_gold_open") is not True
        or manifest.get("automatic_retries") != 0
        or manifest.get("backend_calls") != 0
        or manifest.get("native_query_text_emitted") is not False
        or manifest.get("paper_result") is not False
        or _jsonl_object_count(outcomes) != 150
        or status.get("schema_version") != RUN_STATUS_SCHEMA_VERSION
        or status.get("status") != "success"
        or status.get("run_id") != manifest.get("run_id")
        or status.get("source_run_sha256") != manifest.get("source_run_sha256")
        or status.get("paper_result") is not False
    ):
        raise GrailQASemanticPaperResultError(
            "source run is not an exact successful 150-query run"
        )
    run_audit = _validate_run_audit(
        _load_json(run_audit_path, name="independent run audit"),
        manifest=manifest,
        expected_commit=expected_commit,
    )
    analysis_file = _regular_file(analysis_path, name="semantic analysis")
    analysis = _validate_analysis(
        _load_json(analysis_file, name="semantic analysis"),
        manifest=manifest,
        protocol=protocol,
        author_selection=selection,
        outcome_sha256=outcome_sha256,
    )
    analysis_audit = _validate_analysis_audit(
        _load_json(analysis_audit_path, name="independent analysis audit"),
        analysis_path=analysis_file,
        outcomes_path=outcomes,
        protocol_path=protocol_file,
        author_selection_path=selection_file,
        pilot_selection_path=pilot_file,
        source_run_sha256=str(manifest["source_run_sha256"]),
    )
    after = _tree_snapshot(root)
    if before != after:
        raise GrailQASemanticPaperResultError(
            "paper-result admission mutated the source run"
        )
    body: dict[str, Any] = {
        "schema_version": PAPER_RESULT_SCHEMA_VERSION,
        "status": "success",
        "run_id": manifest["run_id"],
        "runner_commit": expected_commit,
        "source_run_sha256": manifest["source_run_sha256"],
        "preexecution_admission_sha256": manifest[
            "preexecution_admission_sha256"
        ],
        "execution_request_sha256": manifest["execution_request_sha256"],
        "execution_authority_sha256": manifest[
            "execution_authority_sha256"
        ],
        "outcome_ledger_sha256": outcome_sha256,
        "run_audit_sha256": run_audit["audit_sha256"],
        "analysis_sha256": analysis["analysis_sha256"],
        "analysis_audit_sha256": analysis_audit["audit_sha256"],
        "protocol_sha256": analysis["protocol_sha256"],
        "author_selection_sha256": analysis["author_selection_sha256"],
        "selected_decisions": analysis["selected_decisions"],
        "population": analysis["population"],
        "primary": analysis["primary"],
        "all_query_sensitivity": analysis["all_query_sensitivity"],
        "jointly_prompt_reachable_stratum": analysis[
            "jointly_prompt_reachable_stratum"
        ],
        "secondary": analysis["secondary"],
        "failures": analysis["failures"],
        "system_cost": analysis["system_cost"],
        "source_run_tree_mutated": False,
        "external_call_counts_by_admitter": {
            "backend_calls": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
        },
        "claim_boundary": {
            "authority_gated_150_query_run": True,
            "independent_run_audit_passed": True,
            "independent_analysis_reconstruction_passed": True,
            "query_level_inference": True,
            "contains_new_measurements": False,
            "generalization_beyond_frozen_grailqa_population": False,
            "paper_result": True,
        },
        "paper_result": True,
    }
    return {**body, "paper_result_sha256": content_hash(body)}


def validate_grailqa_semantic_paper_result(
    value: Mapping[str, Any]
) -> dict[str, Any]:
    result = _self_hashed(
        value, field="paper_result_sha256", name="paper result"
    )
    if (
        result.get("schema_version") != PAPER_RESULT_SCHEMA_VERSION
        or result.get("status") != "success"
        or result.get("paper_result") is not True
        or result.get("source_run_tree_mutated") is not False
        or result.get("external_call_counts_by_admitter")
        != {
            "backend_calls": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
        }
        or result.get("claim_boundary")
        != {
            "authority_gated_150_query_run": True,
            "independent_run_audit_passed": True,
            "independent_analysis_reconstruction_passed": True,
            "query_level_inference": True,
            "contains_new_measurements": False,
            "generalization_beyond_frozen_grailqa_population": False,
            "paper_result": True,
        }
        or any(
            _SHA256.fullmatch(str(result.get(field, ""))) is None
            for field in (
                "source_run_sha256",
                "preexecution_admission_sha256",
                "execution_request_sha256",
                "execution_authority_sha256",
                "outcome_ledger_sha256",
                "run_audit_sha256",
                "analysis_sha256",
                "analysis_audit_sha256",
                "protocol_sha256",
                "author_selection_sha256",
            )
        )
    ):
        raise GrailQASemanticPaperResultError("paper result is invalid")
    return result


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"paper result output already exists: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            dict(value),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    admit = commands.add_parser("admit")
    admit.add_argument("--run-root", required=True)
    admit.add_argument("--run-audit", required=True)
    admit.add_argument("--analysis", required=True)
    admit.add_argument("--analysis-audit", required=True)
    admit.add_argument("--protocol", required=True)
    admit.add_argument("--author-selection", required=True)
    admit.add_argument("--repo-root", default=".")
    admit.add_argument("--expected-commit", required=True)
    admit.add_argument("--output", required=True)
    check = commands.add_parser("check")
    check.add_argument("--result", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "admit":
            result = admit_grailqa_semantic_paper_result(
                run_root=args.run_root,
                run_audit_path=args.run_audit,
                analysis_path=args.analysis,
                analysis_audit_path=args.analysis_audit,
                protocol_path=args.protocol,
                author_selection_path=args.author_selection,
                repo_root=args.repo_root,
                expected_commit=args.expected_commit,
            )
            _write_json_exclusive(Path(args.output), result)
        else:
            result = validate_grailqa_semantic_paper_result(
                _load_json(args.result, name="paper result")
            )
    except (
        FileExistsError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps({"status": "success", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
