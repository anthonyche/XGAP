from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import runpy
from typing import Any

import pytest

from xgap.experiments.grailqa_semantic_paper_protocol import (
    AUTHOR_SELECTION_SCHEMA_VERSION,
    DEFAULT_PROTOCOL_PATH,
    GrailQASemanticPaperProtocolError,
    compile_grailqa_semantic_paper_readiness,
)
from xgap.experiments.hashing import content_hash


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_V1 = Path("experiments/configs/grailqa_semantic_paper_protocol_draft_v1.json")
PROTOCOL_V2 = Path("experiments/configs/grailqa_semantic_paper_protocol_draft_v2.json")
READINESS_V1 = Path("experiments/artifacts/grailqa_semantic_paper_protocol_readiness_draft_v1.json")
READINESS_V2 = Path("experiments/artifacts/grailqa_semantic_paper_protocol_readiness_draft_v2.json")
SHELL_FIXTURES = runpy.run_path(str(ROOT / "tests/test_m13e4_grailqa_shell_pipeline.py"))


def _load(relative: Path) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _runner_requirement(protocol: dict[str, Any]) -> dict[str, Any]:
    return next(
        item for item in protocol["implementation_requirements"]
        if item["requirement_id"] == "paper_semantic_runner"
    )


@pytest.mark.parametrize(
    ("relative", "frozen_sha256"),
    [
        (PROTOCOL_V1, "f91743e25405d2c9d374fbb550c26aabd9d229d3b547b99d22c2579cc594fddf"),
        (READINESS_V1, "c6976e292d198e149e771c9197332c314d723dbbf427a6dcf70c468f541b8ebd"),
    ],
)
def test_parser_revision_preserves_exact_legacy_artifact_bytes(
    relative: Path, frozen_sha256: str,
) -> None:
    assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == frozen_sha256


def test_protocol_revision_changes_only_identity_runner_digest_and_freeze() -> None:
    old = _load(PROTOCOL_V1)
    new = _load(PROTOCOL_V2)
    old_runner = _runner_requirement(old)
    new_runner = _runner_requirement(new)

    assert new["protocol_id"] == "m13e4-grailqa-sigmod2027-semantic-draft-v2"
    assert new["protocol_id"] != old["protocol_id"]
    assert new["freeze_hash"] != old["freeze_hash"]
    assert new["freeze_hash"] == content_hash({
        key: value for key, value in new.items() if key != "freeze_hash"
    })
    assert new_runner["evidence"]["sha256"] != old_runner["evidence"]["sha256"]
    assert new_runner["evidence"]["sha256"] == hashlib.sha256(
        (ROOT / new_runner["evidence"]["path"]).read_bytes()
    ).hexdigest()

    # Comparing the complete protocol catches changes in every scientific,
    # source, author, ordering, and gate field, including any newly added field.
    reconciled = copy.deepcopy(new)
    reconciled["protocol_id"] = old["protocol_id"]
    reconciled["freeze_hash"] = old["freeze_hash"]
    _runner_requirement(reconciled)["evidence"]["sha256"] = old_runner["evidence"]["sha256"]
    assert reconciled == old


def test_default_v2_compilation_matches_saved_readiness_and_grants_no_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(ROOT)
    assert DEFAULT_PROTOCOL_PATH == PROTOCOL_V2

    readiness = compile_grailqa_semantic_paper_readiness(repo_root=ROOT).to_dict()

    assert readiness == _load(READINESS_V2)
    assert readiness["protocol_sha256"] == content_hash(_load(PROTOCOL_V2))
    assert readiness["gates"] == {
        "result_blind_protocol_structurally_valid": True,
        "all_author_decisions_selected": False,
        "author_approved": False,
        "preflight18_independently_audited_and_reviewed": False,
        "paper_runner_and_analysis_ready": False,
        "full_150_run_authorized": False,
    }
    assert readiness["author_selection_sha256"] is None
    assert len(readiness["next_author_decisions"]) == 5
    assert all(item["selected_value"] is None for item in readiness["author_decisions"])
    assert readiness["claim_boundary"] == {
        "artifact_class": "result_blind_semantic_protocol_readiness",
        "contains_measurements": False,
        "backend_calls_made": 0,
        "llm_calls_made": 0,
        "ontology_service_calls_made": 0,
        "author_decision_inferred": False,
        "paper_result": False,
    }
    assert readiness["automatic_retries"] == 0
    assert readiness["paper_result"] is False


def test_legacy_protocol_rejects_current_runner_implementation_drift() -> None:
    with pytest.raises(
        GrailQASemanticPaperProtocolError,
        match="implementation evidence changed: paper_semantic_runner",
    ):
        compile_grailqa_semantic_paper_readiness(ROOT / PROTOCOL_V1, repo_root=ROOT)


def test_v1_bound_synthetic_author_selection_cannot_approve_v2() -> None:
    old = _load(PROTOCOL_V1)
    new = _load(PROTOCOL_V2)
    # This in-memory synthetic receipt exercises hash binding only. It is never
    # persisted as author evidence and is not an execution authority.
    selection_body = {
        "schema_version": AUTHOR_SELECTION_SCHEMA_VERSION,
        "protocol_sha256": content_hash(old),
        "authority_source_id": "test:synthetic:parser-revision-freeze",
        "decisions": {
            item["decision_id"]: item["allowed_values"][0]
            for item in old["author_decisions"]
        },
    }
    old_selection = {**selection_body, "selection_sha256": content_hash(selection_body)}

    with pytest.raises(
        GrailQASemanticPaperProtocolError,
        match="author selection does not bind this protocol",
    ):
        compile_grailqa_semantic_paper_readiness(
            new, repo_root=ROOT, author_selection=old_selection
        )

    # The same synthetic decisions are valid when explicitly bound to v2,
    # isolating the rejection above to protocol identity rather than choices.
    new_body = {**selection_body, "protocol_sha256": content_hash(new)}
    new_selection = {**new_body, "selection_sha256": content_hash(new_body)}
    readiness = compile_grailqa_semantic_paper_readiness(
        new, repo_root=ROOT, author_selection=new_selection
    ).to_dict()
    assert readiness["gates"]["author_approved"] is True
    assert readiness["gates"]["all_author_decisions_selected"] is True
    assert readiness["gates"]["full_150_run_authorized"] is False
    assert readiness["paper_result"] is False
    assert _load(PROTOCOL_V1) == old
    assert _load(PROTOCOL_V2) == new


@pytest.mark.parametrize("script_key", ["SUBMIT", "RUN", "FINALIZE"])
def test_real_shell_entrypoints_default_to_v2_with_offline_process_doubles(
    tmp_path: Path, script_key: str,
) -> None:
    repo, env = SHELL_FIXTURES["pipeline"].__wrapped__(tmp_path)
    env.pop("XGAP_GRAILQA_SEMANTIC_PROTOCOL")
    # The existing process fixture owns synthetic control validation; this test
    # exercises the real shell's default path and its Python handoff arguments.
    SHELL_FIXTURES["_json"](repo / PROTOCOL_V2, {})

    result = SHELL_FIXTURES["_run"]((repo, env), SHELL_FIXTURES[script_key])

    assert result.returncode == 0, result.stdout + result.stderr
    calls = SHELL_FIXTURES["_calls"](env["FAKE_PYTHON_LOG"])
    protocol_paths = [
        args[args.index("--protocol") + 1]
        for args in calls if "--protocol" in args
    ]
    assert protocol_paths
    assert set(protocol_paths) == {str(repo / PROTOCOL_V2)}
