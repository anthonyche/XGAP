"""Exercise the deployed ``python -m`` entrypoint, not an imported ``main``.

Only the large archival source adapter is replaced in the child process.  The
question parser, eligibility selector, catalog materialization and CLI are real.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from test_grailqa_eligible_catalog_build import build_inputs
from xgap.experiments import grailqa_eligible_candidates as eligible
from xgap.experiments import grailqa_local_catalog as local
from xgap.experiments import grailqa_local_catalog_types as shared
from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2


@pytest.fixture
def module_build(build_inputs, tmp_path):
    kwargs, _ = build_inputs
    source_hook = tmp_path / "source-hook"
    source_hook.mkdir()
    ledger = tmp_path / "source-calls.jsonl"
    # sitecustomize runs before -m, without importing grailqa_local_catalog.
    # In particular it must not mask the __main__/canonical-module distinction.
    (source_hook / "sitecustomize.py").write_text(textwrap.dedent('''\
        import json
        import os
        from pathlib import Path
        import socket
        from xgap.experiments import freebase_sources as source

        def record(kind, **details):
            with Path(os.environ["XGAP_TEST_SOURCE_CALLS"]).open("a") as handle:
                handle.write(json.dumps({"kind": kind, **details}) + "\\n")

        def verify(**kwargs):
            record("verify")
            return {"shard_count": 964, "total_bytes": 32476432840, "status": "ok"}

        def manifest(path):
            record("manifest")
            return {"resolved_parquet_revision": source.HF_FREEBASE_REVISION}

        def records(**kwargs):
            subjects = kwargs.get("subject_ids")
            record("scan", subject_ids=subjects)
            rows = [
                ("m.alias_only", source.ALIAS_PREDICATE, "Alice Example", "en", False),
                ("m.alice", source.ALIAS_PREDICATE, "Alice", "en", False),
                ("m.alice", source.NAME_PREDICATE, "Unmatched Canonical", "en", False),
                ("m.alice", source.TYPE_PREDICATE, "people.person", None, True),
            ]
            for triple in rows:
                if triple[1] not in kwargs["predicates"]:
                    continue
                if subjects is not None and triple[0] not in subjects:
                    continue
                yield source.ParquetTripleRecord(triple=triple, source_shard="data/000.parquet")

        def forbid_network(*args, **kwargs):
            raise AssertionError("The module-entrypoint fixture must remain offline.")

        source.verify_parquet_source_manifest = verify
        source.load_parquet_source_manifest = manifest
        source.iter_parquet_triple_records = records
        socket.socket.connect = forbid_network
        socket.create_connection = forbid_network
    '''), encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "schema_version": "m13e3b-grailqa-local-catalog-config-v1",
        "source": {
            "source_mode": "hf_archival_parquet", "repo_id": "CleverThis/freebase",
            "revision": "dbb1931c2698295653effe9b980a02ab29f004e0",
            "expected_shards": 964, "expected_bytes": 32476432840,
        },
        "normalized_ontology": str(kwargs["normalized_ontology_path"]),
        "reverse_properties": str(kwargs["reverse_properties_path"]),
        "anchor_extraction": {
            "min_tokens": 1, "max_tokens": 8, "omit_stopword_only": True,
            "max_candidates_per_query": 1,
        },
        "workloads": {"preflight18": {
            "artifact_id": "module-entrypoint-fixture", "output_subdirectory": "preflight18",
            "inference_questions": str(kwargs["inference_questions_path"]),
            "question_ids": ["q1"],
        }},
    }), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    local_root = tmp_path / "cli-catalogs"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(source_hook), str(repo_root / "src")))
    environment["XGAP_TEST_SOURCE_CALLS"] = str(ledger)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    def run(*, policy="canonical_eligible_topk_v2"):
        return subprocess.run(
            [sys.executable, "-m", "xgap.experiments.grailqa_local_catalog", "build",
             "--config", str(config), "--workload", "preflight18",
             "--parquet-root", str(kwargs["freebase_parquet_root"]),
             "--source-manifest", str(kwargs["source_manifest_path"]),
             "--local-root", str(local_root), "--staging-root", str(kwargs["staging_root"]),
             "--candidate-selection", policy],
            cwd=repo_root, env=environment, capture_output=True, text=True, timeout=30,
            check=False,
        )

    return run, kwargs["inference_questions_path"], local_root, ledger


def test_module_entrypoint_builds_real_eligible_catalog(module_build):
    run, _, local_root, ledger = module_build
    completed = run()
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Local catalog ready:" in completed.stdout
    catalog_root = local_root / "preflight18-eligible-v2"
    manifest = json.loads((catalog_root / "manifest.json").read_text())
    assert manifest["local_catalog_schema_version"] == "m13e3b-grailqa-local-catalog-v2"
    assert manifest["candidate_selection"] == "canonical_eligible_topk_v2"
    assert manifest["counts"]["query_candidate_assignments"] == 1
    assert manifest["paper_result"] is False
    retrieval = GrailQAInferenceCatalogV2.load(catalog_root).retrieve("q1", "Alice Example")
    assert [candidate.candidate_id for candidate in retrieval.entities] == ["m.alice"]
    calls = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [call["kind"] for call in calls] == ["verify", "manifest", "scan", "scan"]
    assert calls[-1]["subject_ids"] == ["m.alice"]


def test_module_entrypoint_preserves_legacy_build_policy(module_build):
    run, _, local_root, _ = module_build
    completed = run(policy="legacy_topk_v1")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    manifest = json.loads((local_root / "preflight18" / "manifest.json").read_text())
    assert manifest["local_catalog_schema_version"] == "m13e3b-grailqa-local-catalog-v1"
    assert manifest["counts"]["query_candidate_assignments"] == 0
    assert not (local_root / "preflight18-eligible-v2").exists()


@pytest.mark.parametrize("question", [
    {"question_id": "q1"},
    {"text": "Alice Example"},
    {"question_id": "", "text": "Alice Example"},
    {"question_id": None, "text": "Alice Example"},
    {"question_id": 1, "text": "Alice Example"},
    {"question_id": "q1", "text": None},
    {"question_id": "q1", "text": 1},
    {"question_id": "q1", "text": ""},
    {"question_id": "q1", "text": " \t "},
])
def test_module_entrypoint_rejects_invalid_workload_questions_before_source_access(module_build, question):
    run, questions, local_root, ledger = module_build
    questions.write_text(json.dumps(question) + "\n", encoding="utf-8")
    completed = run()
    assert completed.returncode != 0
    assert "ValueError" in completed.stderr
    assert "Local catalog ready:" not in completed.stdout
    assert not local_root.exists()
    assert not ledger.exists()


def test_record_classes_have_one_identity_across_importing_modules():
    assert local.InferenceQuestion is eligible.InferenceQuestion is shared.InferenceQuestion
    assert local.LocalCandidateMatch is eligible.LocalCandidateMatch is shared.LocalCandidateMatch


def test_shared_records_preserve_exact_hash_and_serialization_contract():
    text = "Alice Example / 查询"
    question = shared.InferenceQuestion("q1", text)
    assert question.question_hash == hashlib.sha256(text.encode("utf-8")).hexdigest()
    candidate = shared.LocalCandidateMatch(
        question_id="q1", entity_id="m.alice", matched_label="Alice",
        normalized_label="alice", match_type="exact_normalized_alias", score=2.25,
        source_shard=Path("data/000.parquet"),
    )
    assert candidate.to_dict() == {
        "question_id": "q1", "entity_id": "m.alice", "matched_label": "Alice",
        "normalized_label": "alice", "match_type": "exact_normalized_alias",
        "lexical_score": 2.25, "source_shard": "data/000.parquet", "rank": 0,
    }


def test_eligible_selector_still_rejects_duck_types_before_stream_or_scratch(tmp_path, monkeypatch):
    def forbidden_scratch(*args, **kwargs):
        pytest.fail("Invalid question types must not allocate scratch storage.")

    def forbidden_records():
        pytest.fail("Invalid question types must not consume the source stream.")
        yield  # Make failure occur on consumption, not generator creation.

    monkeypatch.setattr(eligible.tempfile, "TemporaryDirectory", forbidden_scratch)
    with pytest.raises(ValueError, match="nonempty string ID and text"):
        eligible.select_eligible_query_candidates(
            (SimpleNamespace(question_id="q1", text="Alice Example"),),
            forbidden_records(), staging_root=tmp_path,
        )
    assert list(tmp_path.iterdir()) == []
