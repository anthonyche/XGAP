"""Bind an immutable M15 campaign schedule to resolved query contracts.

This compiler preserves the audited F2A campaign configuration and layers a
separately versioned registry over it. Expected bundle-dependent query-contract
hashes are frozen here and must still be verified against generated bundles by
the later live-session preflight. Compilation starts no service and makes no
backend, LLM, or ontology call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_campaign import compile_m15_campaign_file
from xgap.experiments.m15_query_contract import M15ResolvedQuerySpec


QUERY_BOUND_REGISTRY_SCHEMA_VERSION = (
    "m15-f2-query-bound-campaign-registry-v1"
)
QUERY_BOUND_CAMPAIGN_PLAN_SCHEMA_VERSION = (
    "m15-f2-query-bound-campaign-plan-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class M15QueryBoundCampaignError(ValueError):
    """Raised before output when the query-bound schedule is invalid."""


def _strict_object(
    value: object,
    *,
    name: str,
    fields: set[str],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise M15QueryBoundCampaignError(f"{name} must be an object")
    result = dict(value)
    if set(result) != fields:
        raise M15QueryBoundCampaignError(
            f"{name} fields do not match the v1 contract"
        )
    return result


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15QueryBoundCampaignError(f"{name} must be a safe identifier")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M15QueryBoundCampaignError(f"{name} must be a SHA-256 digest")
    return value


def _relative_path(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise M15QueryBoundCampaignError(f"{name} must be a nonempty path")
    path = Path(value)
    if path.is_absolute() or path == Path(".") or ".." in path.parts:
        raise M15QueryBoundCampaignError(
            f"{name} must be a normalized repository-relative path"
        )
    return value


def _resolve_repo_file(repo_root: Path, relative: str, *, name: str) -> Path:
    candidate = repo_root / relative
    if candidate.is_symlink():
        raise M15QueryBoundCampaignError(f"{name} must not be a symlink")
    path = candidate.resolve()
    try:
        path.relative_to(repo_root)
    except ValueError as exc:
        raise M15QueryBoundCampaignError(f"{name} escapes repository root") from exc
    if not path.is_file():
        raise M15QueryBoundCampaignError(f"{name} must be a regular file")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class QueryContractRegistryBinding:
    workload_label: str
    query_id: str
    query_spec_path: str
    expected_query_spec_sha256: str
    expected_query_contract_sha256: str

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "QueryContractRegistryBinding":
        raw = _strict_object(
            value,
            name="query binding",
            fields={
                "workload_label",
                "query_id",
                "query_spec_path",
                "expected_query_spec_sha256",
                "expected_query_contract_sha256",
            },
        )
        return cls(
            workload_label=_safe_id(
                raw["workload_label"], name="binding.workload_label"
            ),
            query_id=_safe_id(raw["query_id"], name="binding.query_id"),
            query_spec_path=_relative_path(
                raw["query_spec_path"], name="binding.query_spec_path"
            ),
            expected_query_spec_sha256=_sha256(
                raw["expected_query_spec_sha256"],
                name="binding.expected_query_spec_sha256",
            ),
            expected_query_contract_sha256=_sha256(
                raw["expected_query_contract_sha256"],
                name="binding.expected_query_contract_sha256",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "workload_label": self.workload_label,
            "query_id": self.query_id,
            "query_spec_path": self.query_spec_path,
            "expected_query_spec_sha256": self.expected_query_spec_sha256,
            "expected_query_contract_sha256": (
                self.expected_query_contract_sha256
            ),
        }


@dataclass(frozen=True)
class M15QueryBoundCampaignRegistry:
    registry_id: str
    campaign_id: str
    base_campaign_config: str
    expected_base_campaign_spec_sha256: str
    expected_base_schedule_sha256: str
    bindings: tuple[QueryContractRegistryBinding, ...]

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "M15QueryBoundCampaignRegistry":
        raw = _strict_object(
            value,
            name="query-bound campaign registry",
            fields={
                "schema_version",
                "registry_id",
                "campaign_id",
                "base_campaign_config",
                "expected_base_campaign_spec_sha256",
                "expected_base_schedule_sha256",
                "bindings",
                "automatic_retries",
                "paper_result",
            },
        )
        if raw["schema_version"] != QUERY_BOUND_REGISTRY_SCHEMA_VERSION:
            raise M15QueryBoundCampaignError(
                "query-bound registry schema_version is unsupported"
            )
        raw_bindings = raw["bindings"]
        if not isinstance(raw_bindings, list) or not 1 <= len(raw_bindings) <= 4096:
            raise M15QueryBoundCampaignError(
                "bindings must contain between 1 and 4096 items"
            )
        bindings = tuple(
            QueryContractRegistryBinding.from_dict(item)
            for item in raw_bindings
        )
        keys = [(item.workload_label, item.query_id) for item in bindings]
        if len(keys) != len(set(keys)):
            raise M15QueryBoundCampaignError(
                "query bindings must have unique workload/query keys"
            )
        if raw["automatic_retries"] != 0:
            raise M15QueryBoundCampaignError(
                "query-bound campaign must disable automatic retries"
            )
        if raw["paper_result"] is not False:
            raise M15QueryBoundCampaignError(
                "development query-bound campaign must set paper_result=false"
            )
        return cls(
            registry_id=_safe_id(raw["registry_id"], name="registry_id"),
            campaign_id=_safe_id(raw["campaign_id"], name="campaign_id"),
            base_campaign_config=_relative_path(
                raw["base_campaign_config"], name="base_campaign_config"
            ),
            expected_base_campaign_spec_sha256=_sha256(
                raw["expected_base_campaign_spec_sha256"],
                name="expected_base_campaign_spec_sha256",
            ),
            expected_base_schedule_sha256=_sha256(
                raw["expected_base_schedule_sha256"],
                name="expected_base_schedule_sha256",
            ),
            bindings=bindings,
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "M15QueryBoundCampaignRegistry":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise M15QueryBoundCampaignError(
                "query-bound registry must be a JSON object"
            )
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": QUERY_BOUND_REGISTRY_SCHEMA_VERSION,
            "registry_id": self.registry_id,
            "campaign_id": self.campaign_id,
            "base_campaign_config": self.base_campaign_config,
            "expected_base_campaign_spec_sha256": (
                self.expected_base_campaign_spec_sha256
            ),
            "expected_base_schedule_sha256": self.expected_base_schedule_sha256,
            "bindings": [item.to_dict() for item in self.bindings],
            "automatic_retries": 0,
            "paper_result": False,
        }


@dataclass(frozen=True)
class M15QueryBoundCampaignPlan:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    @property
    def schedule_hash(self) -> str:
        return str(self.payload["query_bound_schedule_sha256"])


def _deep_copy(value: object) -> Any:
    return json.loads(json.dumps(value, allow_nan=False))


def compile_m15_query_bound_campaign(
    registry: M15QueryBoundCampaignRegistry,
    *,
    repo_root: str | Path | None = None,
) -> M15QueryBoundCampaignPlan:
    """Compile query bindings over an immutable base campaign plan."""

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    if not root.is_dir():
        raise M15QueryBoundCampaignError("repository root does not exist")
    base_path = _resolve_repo_file(
        root,
        registry.base_campaign_config,
        name="base campaign config",
    )
    try:
        base = compile_m15_campaign_file(base_path, repo_root=root).to_dict()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise M15QueryBoundCampaignError(f"base campaign is invalid: {exc}") from exc
    if base.get("campaign_id") != registry.campaign_id:
        raise M15QueryBoundCampaignError(
            "registry campaign_id disagrees with the base campaign"
        )
    if (
        base.get("campaign_spec_sha256")
        != registry.expected_base_campaign_spec_sha256
    ):
        raise M15QueryBoundCampaignError("base campaign spec hash drifted")
    if base.get("schedule_sha256") != registry.expected_base_schedule_sha256:
        raise M15QueryBoundCampaignError("base campaign schedule hash drifted")

    workload_inputs = {
        str(item["label"]): dict(item)
        for item in base.get("workload_inputs", [])
        if isinstance(item, Mapping) and isinstance(item.get("label"), str)
    }
    expected_keys = {
        (label, str(query_id))
        for label, workload in workload_inputs.items()
        for query_id in workload.get("query_ids", [])
    }
    actual_keys = {
        (binding.workload_label, binding.query_id)
        for binding in registry.bindings
    }
    if actual_keys != expected_keys:
        raise M15QueryBoundCampaignError(
            "query bindings must cover the base workload/query set exactly"
        )

    compiled_bindings: list[dict[str, Any]] = []
    for binding in registry.bindings:
        query_spec_path = _resolve_repo_file(
            root,
            binding.query_spec_path,
            name="query spec",
        )
        observed_sha = _sha256_file(query_spec_path)
        if observed_sha != binding.expected_query_spec_sha256:
            raise M15QueryBoundCampaignError(
                f"query spec hash drifted for {binding.workload_label}/"
                f"{binding.query_id}"
            )
        try:
            query_spec = M15ResolvedQuerySpec.from_json(query_spec_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise M15QueryBoundCampaignError(
                f"query spec is invalid for {binding.workload_label}/"
                f"{binding.query_id}: {exc}"
            ) from exc
        if query_spec.query_id != binding.query_id:
            raise M15QueryBoundCampaignError(
                "query spec query_id disagrees with its registry binding"
            )
        workload = workload_inputs[binding.workload_label]
        compiled_bindings.append(
            {
                **binding.to_dict(),
                "workload_id": workload["workload_id"],
                "workload_bundle_spec_sha256": workload["bundle_spec_sha256"],
                "query_spec_schema_version": query_spec.to_dict()[
                    "schema_version"
                ],
                "hard_constraint_count": len(query_spec.hard_constraints),
                "artifact_roles": [
                    str(item["role"]) for item in query_spec.artifacts
                ],
                "query_contract_verification": (
                    "expected_hash_frozen_live_bundle_verification_pending"
                ),
            }
        )
    compiled_bindings.sort(
        key=lambda item: (item["workload_label"], item["query_id"])
    )
    portable_bindings = [
        {
            key: value
            for key, value in item.items()
            if key not in {"query_spec_path", "query_contract_verification"}
        }
        for item in compiled_bindings
    ]
    query_binding_sha256 = content_hash(portable_bindings)
    by_key = {
        (item["workload_label"], item["query_id"]): item
        for item in compiled_bindings
    }

    sessions: list[dict[str, Any]] = []
    for base_session in base.get("sessions", []):
        if not isinstance(base_session, Mapping):
            raise M15QueryBoundCampaignError("base campaign session is invalid")
        session = _deep_copy(base_session)
        label = str(session["workload_label"])
        query_ids = list(session["method_streams"][0]["query_ids"])
        refs = [
            {
                "query_id": query_id,
                "expected_query_spec_sha256": by_key[(label, query_id)][
                    "expected_query_spec_sha256"
                ],
                "expected_query_contract_sha256": by_key[(label, query_id)][
                    "expected_query_contract_sha256"
                ],
            }
            for query_id in query_ids
        ]
        session["query_contract_refs"] = refs
        for stream in session["method_streams"]:
            if stream["query_ids"] != query_ids:
                raise M15QueryBoundCampaignError(
                    "base method streams disagree on query order"
                )
            stream["query_contract_refs"] = _deep_copy(refs)
        sessions.append(session)

    query_bound_schedule_sha256 = content_hash(
        {
            "registry_id": registry.registry_id,
            "base_schedule_sha256": base["schedule_sha256"],
            "query_binding_sha256": query_binding_sha256,
            "sessions": sessions,
        }
    )
    return M15QueryBoundCampaignPlan(
        {
            "schema_version": QUERY_BOUND_CAMPAIGN_PLAN_SCHEMA_VERSION,
            "registry_id": registry.registry_id,
            "registry_spec_sha256": content_hash(registry.to_dict()),
            "campaign_id": registry.campaign_id,
            "base_campaign": {
                "config_path": registry.base_campaign_config,
                "campaign_spec_sha256": base["campaign_spec_sha256"],
                "schedule_sha256": base["schedule_sha256"],
                "plan_schema_version": base["schema_version"],
            },
            "query_binding_sha256": query_binding_sha256,
            "query_bound_schedule_sha256": query_bound_schedule_sha256,
            "query_bindings": compiled_bindings,
            "sessions": sessions,
            "expected_counts": {
                **dict(base["expected_counts"]),
                "query_contract_bindings": len(compiled_bindings),
            },
            "design_validation": _deep_copy(base["design_validation"]),
            "claim_boundary": {
                "artifact_class": "unexecuted_query_bound_campaign_plan",
                "query_specs_hash_bound": True,
                "expected_query_contract_hashes_frozen": True,
                "live_bundle_contracts_verified": False,
                "backend_calls_made": 0,
                "llm_calls_made": 0,
                "ontology_calls_made": 0,
                "contains_measurements": False,
                "paper_comparison_ready": False,
                "blocking_conditions": [
                    "query_contracts_not_yet_verified_against_live_generated_bundles",
                    "query_bound_plan_not_yet_consumed_by_live_session_runner",
                    "fewer_than_30_distinct_workload_query_contexts",
                    "at_least_one_workload_has_no_multi_task_memory_stream",
                    "coordinator_cost_model_is_uncalibrated",
                    "inferential_analysis_not_preregistered",
                ],
                "paper_result": False,
            },
            "automatic_retries": 0,
            "paper_result": False,
        }
    )


def compile_m15_query_bound_campaign_file(
    registry_path: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> M15QueryBoundCampaignPlan:
    candidate = Path(registry_path)
    if candidate.is_symlink():
        raise M15QueryBoundCampaignError("registry must not be a symlink")
    return compile_m15_query_bound_campaign(
        M15QueryBoundCampaignRegistry.from_json(candidate),
        repo_root=repo_root,
    )


def write_m15_query_bound_campaign_plan(
    plan: M15QueryBoundCampaignPlan,
    output: str | Path,
) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"query-bound campaign plan exists: {destination}")
    destination.write_text(
        json.dumps(
            plan.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--repo-root")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        plan = compile_m15_query_bound_campaign_file(
            args.registry,
            repo_root=args.repo_root,
        )
        if args.output:
            write_m15_query_bound_campaign_plan(plan, args.output)
    except (
        FileExistsError,
        M15QueryBoundCampaignError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
