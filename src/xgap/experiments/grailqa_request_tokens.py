"""Inventory exact GrailQA generation-request tokens without sending requests.

An explicit preflight spec and an existing pinned tokenizer snapshot are
required. Token fit is neither semantic readiness nor permission to run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import CWRUVLLMContract
from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2
from xgap.experiments.grailqa_preflight import GrailQAPreflightSpec, preflight_readiness
from xgap.experiments.grailqa_semantic_pilot import build_inference_request
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.llm.token_budget import ChatTokenBudgetGuard, LocalPinnedChatTokenizer


SCHEMA_VERSION = "grailqa-offline-request-token-inventory-v1"


class _NoSendTransport:
    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        raise RuntimeError("This offline inventory cannot send model requests.")


def _questions(path: Path) -> dict[str, Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("question_id"), (str, int)):
                raise ValueError("Invalid inference-question record.")
            question_id = str(row["question_id"])
            if question_id in rows:
                raise ValueError("Duplicate inference-question ID.")
            rows[question_id] = row
    return rows


def _unavailable(question_id: str, reason: str) -> dict[str, Any]:
    return {
        "question_id": question_id, "status": "unavailable", "passed": False,
        "reason": reason, "input_tokens": None, "requested_output_tokens": None,
        "payload_sha256": None,
    }


def inventory_request_tokens(
    *, spec_path: str | Path, repo_root: str | Path,
    tokenizer_snapshot: str | Path, tokenizer_revision: str,
) -> dict[str, Any]:
    """Build each frozen generation payload, count locally, and retain all IDs.

    Readiness/reachability artifacts are gate metadata only. Request construction
    receives exclusively the inference question and locally retrieved view.
    Unavailable inputs or tokenization never become estimated token counts.
    """
    repo = Path(repo_root).resolve()
    spec_file = (repo / spec_path).resolve()
    snapshot = Path(tokenizer_snapshot).absolute()
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "success": False, "complete": False, "status": "incomplete",
        "scope": "generation_request_token_fit_only",
        "inputs": {
            "spec": str(spec_file), "repo_root": str(repo),
            "tokenizer_snapshot": str(snapshot), "tokenizer_revision": tokenizer_revision,
        },
        "readiness": None, "question_count": None, "requests": [], "errors": [],
        "external_call_counts": {
            "llm_calls": 0, "backend_calls": 0, "ontology_service_calls": 0,
            "downloads": 0,
        },
        "claim_boundary": {
            "run_authorized": False, "paper_result": False,
            "semantic_validity_verified": False, "remote_serving_parity_verified": False,
            "reachability_used_as_model_input": False,
            "repair_payloads_counted": False, "per_send_generation_guard_required": True,
            "per_send_repair_guard_required": True,
            "repair_note": "Actual repair payloads depend on responses and are not yet known.",
        },
        "paper_result": False,
    }
    try:
        spec = GrailQAPreflightSpec.load(spec_file)
    except Exception as error:
        report["errors"].append({"reason": "spec_unavailable", "error_type": type(error).__name__})
        return _finish(report)
    report["question_count"] = len(spec.question_ids)
    report["spec_freeze_hash"] = spec.data["freeze_hash"]
    report["requests"] = [_unavailable(qid, "inputs_unavailable") for qid in spec.question_ids]
    for key in ("pilot_root", "catalog_root", "reachability_root", "model_bundle_root", "deployment_contract"):
        if key in spec.data:
            report["inputs"][key] = str((repo / str(spec.data[key])).resolve())
    try:
        readiness = preflight_readiness(spec, repo, require_credentials=False)
        report["readiness"] = readiness
        model = ModelBundle.load(repo / str(spec.data["model_bundle_root"]))
        contract = CWRUVLLMContract.load(repo / str(spec.data["deployment_contract"]))
        if model.bundle_hash != spec.data["model_bundle_hash"]:
            raise ValueError("Spec/model identity mismatch.")
        if contract.contract_hash != spec.data["deployment_contract_hash"]:
            raise ValueError("Spec/deployment identity mismatch.")
        if model.config.exact_model_snapshot != contract.model:
            raise ValueError("Model/deployment identity mismatch.")
        report["model_bundle_hash"] = model.bundle_hash
        report["deployment_contract_hash"] = contract.contract_hash
        report["expected_model"] = contract.model
        provider = build_openai_compatible_provider(
            model, _NoSendTransport(), response_parser=parse_normalized_planner_response,
        )
        catalog = GrailQAInferenceCatalogV2.load(readiness["catalog_root"])
        questions = _questions(repo / str(spec.data["pilot_root"]) / "inference_questions.jsonl")
    except Exception as error:
        report["errors"].append({"reason": "inputs_unavailable", "error_type": type(error).__name__})
        return _finish(report)

    guard = None
    try:
        counter = LocalPinnedChatTokenizer(snapshot, tokenizer_revision)
        guard = ChatTokenBudgetGuard(
            counter, input_limit=model.config.token_limits["input"],
            output_limit=model.config.token_limits["output"],
            context_limit=contract.data["serving"]["max_model_len"],
            expected_model=contract.model,
        )
        report["tokenizer_identity"] = dict(counter.identity)
    except Exception as error:
        report["errors"].append({"reason": "tokenizer_or_budget_unavailable", "error_type": type(error).__name__})

    rows = []
    for question_id in spec.question_ids:
        if question_id not in questions:
            rows.append(_unavailable(question_id, "question_unavailable"))
            continue
        try:
            question = questions[question_id]
            retrieval = catalog.retrieve(
                question_id, str(question["text"]), top_k=int(spec.data["retrieval_k"]),
            )
            if not retrieval.types or not retrieval.relations:
                rows.append(_unavailable(question_id, "retrieval_unavailable"))
                continue
            view = catalog.prompt_view(
                retrieval, candidates_per_slot=int(spec.data["prompt_candidates_per_slot"]),
                max_entities=int(spec.data["prompt_candidates_per_slot"]),
            )
            request = build_inference_request(question, retrieval, view, int(spec.data["candidate_cap"]))
            payload = provider.build_request_payload(request)
        except Exception as error:
            row = _unavailable(question_id, "request_build_unavailable")
            row["error_type"] = type(error).__name__
            rows.append(row)
            continue
        if guard is None:
            row = _unavailable(question_id, "tokenizer_or_budget_unavailable")
            row.update(payload_sha256=content_hash(payload), requested_output_tokens=payload["max_tokens"])
        else:
            check = guard.check(payload, call_kind="generation")
            row = {"question_id": question_id, **check}
            row["status"] = "counted" if check["input_tokens"] is not None else "unavailable"
        rows.append(row)
    report["requests"] = rows
    return _finish(report)


def _finish(report: dict[str, Any]) -> dict[str, Any]:
    rows = report["requests"]
    measured = [row for row in rows if row["input_tokens"] is not None]
    report["counted_request_count"] = len(measured)
    report["unavailable_request_count"] = len(rows) - len(measured)
    report["passed_request_count"] = sum(row["passed"] for row in rows)
    report["maximum_input_tokens"] = max((row["input_tokens"] for row in measured), default=None)
    report["complete"] = bool(rows) and len(measured) == report["question_count"]
    report["success"] = report["complete"] and all(row["passed"] for row in rows)
    report["status"] = "success" if report["success"] else "failed" if report["complete"] else "incomplete"
    # Token fit does not promote a false preflight-readiness gate or confer
    # authorization. Both the separate readiness object and boundary remain.
    report["inventory_sha256"] = content_hash(report)
    return report


def _check_output(output: Path, report: Mapping[str, Any]) -> None:
    if output.exists() or output.is_symlink():
        raise FileExistsError("Inventory output already exists.")
    target = output.resolve()
    inputs = report["inputs"]
    repo = Path(inputs["repo_root"])
    protected = [repo / name for name in ("sources", "datasets", "models", "experiments", "src", "tests", "docs")]
    protected.extend(Path(inputs[key]) for key in (
        "pilot_root", "catalog_root", "reachability_root", "model_bundle_root",
    ) if key in inputs)
    snapshot = Path(inputs["tokenizer_snapshot"])
    protected.append(snapshot)
    if snapshot.parent.name == "snapshots":
        protected.append(snapshot.parent.parent)
    readiness = report.get("readiness") or {}
    protected.extend(Path(readiness[key]) for key in ("catalog_root", "reachability_root") if key in readiness)
    exact = [Path(inputs["spec"])]
    exact.extend(Path(inputs[key]) for key in ("deployment_contract",) if key in inputs)
    exact.extend(Path(readiness[key]) for key in ("reachability_summary_path", "reachability_rows_path") if key in readiness)
    if any(target.is_relative_to(root.resolve()) for root in protected) or target in [path.resolve() for path in exact]:
        raise ValueError("Output must be outside read-only input artifacts and repository source trees.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("spec", "repo-root", "tokenizer-snapshot", "tokenizer-revision", "output"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output).absolute()
    if output.exists() or output.is_symlink():
        parser.error("Inventory output already exists; choose a new output path.")
    report = inventory_request_tokens(
        spec_path=args.spec, repo_root=args.repo_root,
        tokenizer_snapshot=args.tokenizer_snapshot, tokenizer_revision=args.tokenizer_revision,
    )
    try:
        _check_output(output, report)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({
        "status": report["status"], "output": str(output),
        "counted_request_count": report["counted_request_count"],
        "unavailable_request_count": report["unavailable_request_count"],
        "paper_result": False,
    }, sort_keys=True))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
