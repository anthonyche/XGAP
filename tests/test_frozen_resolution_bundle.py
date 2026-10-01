"""Offline publishing, pinned reads and independently constructed failures."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from xgap.catalog.build import freeze_resolution_bundle
from xgap.catalog.bundle import FrozenResolutionBundle, SCHEMA
from xgap.experiments.toy_binding import FIXTURE
from xgap.semantic.program import SemanticHoleKind


def prepare(tmp_path, *, ontology=None):
    inputs = tmp_path / "preparation"
    inputs.mkdir()
    for name in ("catalog.json", "bindings.json"):
        shutil.copyfile(FIXTURE / name, inputs / name)
    if ontology:
        (inputs / "ontology.json").write_text(json.dumps(ontology))
    return inputs


def publish(inputs, output, **kwargs):
    return freeze_resolution_bundle(catalog=inputs / "catalog.json", bindings=inputs / "bindings.json",
                                    output=output, **kwargs)


def independent_manifest(root):
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob("*.json")
             if p.name != "manifest.json"}
    value = {"schema_version": SCHEMA, "files": files}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (root / "manifest.json").write_text(json.dumps({**value, "bundle_hash": digest}))
    return digest


def test_offline_snapshot_survives_removing_all_preparation_inputs(tmp_path):
    inputs = prepare(tmp_path); output = tmp_path / "published"
    manifest = publish(inputs, output)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()}
    shutil.rmtree(inputs)  # Owned disposable inputs; runtime must use the frozen copy only.
    for p in output.iterdir():
        p.chmod(0o444)
    bundle = FrozenResolutionBundle.load(output, expected_bundle_hash=manifest["bundle_hash"])
    assert bundle.bindings["entity:alice"].value == "a"
    assert bundle.bindings["constraint:30"].value == 30
    assert bundle.catalog.candidate_kinds["entity:alice"] is SemanticHoleKind.ENTITY
    assert bundle.identity["bundle_hash"] == manifest["bundle_hash"]
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()} == before
    with pytest.raises(TypeError):
        bundle.bindings["entity:alice"] = bundle.bindings["entity:bob"]


def test_existing_output_cannot_be_overwritten_and_content_versions_are_pinned(tmp_path):
    inputs = prepare(tmp_path); output = tmp_path / "v1"
    first = publish(inputs, output)
    with pytest.raises(FileExistsError):
        publish(inputs, output)
    catalog = json.loads((inputs / "catalog.json").read_text())
    catalog["catalog_version"] = "v2"
    (inputs / "catalog.json").write_text(json.dumps(catalog))
    second = publish(inputs, tmp_path / "v2")
    assert first["bundle_hash"] != second["bundle_hash"]
    with pytest.raises(ValueError, match="version mismatch"):
        FrozenResolutionBundle.load(tmp_path / "v2", expected_bundle_hash=first["bundle_hash"])
    assert FrozenResolutionBundle.load(output, expected_bundle_hash=first["bundle_hash"]).catalog.catalog_version == "v1"


@pytest.mark.parametrize("fault", ["missing", "extra", "wrong-kind", "unknown-field", "bad-identity"])
def test_invalid_cross_file_binding_contract_is_rejected_before_publication(tmp_path, fault):
    inputs = prepare(tmp_path)
    raw = json.loads((inputs / "bindings.json").read_text())
    if fault == "missing": raw.pop("entity:alice")
    if fault == "extra": raw["entity:unknown"] = {"kind": "entity", "value": "x"}
    if fault == "wrong-kind": raw["entity:alice"]["kind"] = "predicate"
    if fault == "unknown-field": raw["entity:alice"]["ignored"] = True
    if fault == "bad-identity": raw["entity:alice"]["identity_property"] = 5
    (inputs / "bindings.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        publish(inputs, tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("fault", ["missing-file", "tampered", "incomplete", "wrong-schema", "unknown-file", "cross-kind"])
def test_reader_rejects_saved_minimal_failures_without_rebuilding(tmp_path, fault):
    inputs = prepare(tmp_path); output = tmp_path / "output"; m = publish(inputs, output)
    pin = m["bundle_hash"]
    if fault == "missing-file": (output / "bindings.json").unlink()
    if fault == "tampered": (output / "bindings.json").write_text('{}')
    if fault == "incomplete": (output / "manifest.json").unlink()
    if fault == "wrong-schema":
        m["schema_version"] = "future"; (output / "manifest.json").write_text(json.dumps(m))
    if fault == "unknown-file":
        m["files"]["../outside"] = "0" * 64; (output / "manifest.json").write_text(json.dumps(m))
    if fault == "cross-kind":
        raw = json.loads((output / "bindings.json").read_text()); raw["entity:alice"]["kind"] = "predicate"
        (output / "bindings.json").write_text(json.dumps(raw)); pin = independent_manifest(output)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises((OSError, ValueError)):
        FrozenResolutionBundle.load(output, expected_bundle_hash=pin)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


def test_runtime_import_does_not_load_builders_or_raw_dataset_readers(tmp_path):
    inputs = prepare(tmp_path); output = tmp_path / "output"; m = publish(inputs, output)
    code = '''import sys
from xgap.agent.semantic_execution import run_frozen_semantic_query
from xgap.catalog.bundle import FrozenResolutionBundle
FrozenResolutionBundle.load(sys.argv[1], expected_bundle_hash=sys.argv[2])
assert "xgap.catalog.build" not in sys.modules
assert "xgap.experiments.grailqa_catalog_v2" not in sys.modules
assert "xgap.experiments.grailqa_local_catalog" not in sys.modules
assert "xgap.experiments.freebase_sources" not in sys.modules
'''
    result = subprocess.run([sys.executable, "-c", code, str(output), m["bundle_hash"]],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_explicit_offline_cli_publishes_loadable_reference(tmp_path):
    inputs = prepare(tmp_path); output = tmp_path / "output"
    result = subprocess.run([sys.executable, "-m", "xgap.catalog.build", "--catalog", str(inputs / "catalog.json"),
        "--bindings", str(inputs / "bindings.json"), "--output", str(output)],
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    reference = json.loads(result.stdout)
    assert FrozenResolutionBundle.load(reference["root"], expected_bundle_hash=reference["bundle_hash"])


@pytest.mark.parametrize("fault", [None, "missing-binding", "conflicting-kind"])
def test_optional_ontology_candidates_share_the_same_typed_binding_snapshot(tmp_path, fault):
    from xgap.tools.artifact_resolution import ONTOLOGY_SCHEMA_VERSION
    ontology = {"schema_version": ONTOLOGY_SCHEMA_VERSION, "ontology_id": "toy-schema", "ontology_version": "v1",
        "concepts": [{"candidate_id": "predicate:friend", "kind": "predicate", "labels": ["friend"], "provenance": {}}],
        "relations": [], "metadata": {"source": "independent toy schema"}}
    if fault == "conflicting-kind":
        ontology["concepts"][0].update(candidate_id="entity:alice", kind="type")
    inputs = prepare(tmp_path, ontology=ontology)
    if fault is None:
        raw = json.loads((inputs / "bindings.json").read_text())
        raw["predicate:friend"] = {"kind": "predicate", "value": "KNOWS"}
        (inputs / "bindings.json").write_text(json.dumps(raw))
    if fault:
        with pytest.raises(ValueError):
            publish(inputs, tmp_path / "output", ontology=inputs / "ontology.json")
        assert not (tmp_path / "output").exists()
    else:
        m = publish(inputs, tmp_path / "output", ontology=inputs / "ontology.json")
        bundle = FrozenResolutionBundle.load(tmp_path / "output", expected_bundle_hash=m["bundle_hash"])
        assert bundle.ontology.candidate_kinds == {"predicate:friend": SemanticHoleKind.PREDICATE}
        assert bundle.bindings["predicate:friend"].value == "KNOWS"
        assert bundle.identity["ontology_source"].startswith("ontology:toy-schema@v1:")


def test_interrupted_publication_has_no_complete_manifest_and_never_loads(tmp_path, monkeypatch):
    import xgap.catalog.build as builder
    inputs = prepare(tmp_path); output = tmp_path / "output"
    def interrupted(*args):
        raise OSError("controlled interruption before complete manifest publication")
    monkeypatch.setattr(builder.os, "replace", interrupted)
    with pytest.raises(OSError, match="controlled interruption"):
        publish(inputs, output)
    assert output.exists() and not (output / "manifest.json").exists()
    with pytest.raises(ValueError, match="regular file"):
        FrozenResolutionBundle.load(output, expected_bundle_hash="0" * 64)
    with pytest.raises(FileExistsError):
        publish(inputs, output)
