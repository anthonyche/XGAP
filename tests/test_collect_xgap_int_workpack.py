"""Standalone stdlib checks using tiny invented files, never real server inputs."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/server/collect_xgap_int_workpack.py"
SPEC = importlib.util.spec_from_file_location("int_workpack_collector", SCRIPT)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def content_hash(value, ascii_only=True):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=ascii_only, allow_nan=False).encode()).hexdigest()


def seal(value, field, ascii_only=True):
    return {**value, field: content_hash(value, ascii_only)}


def bytes_record(data):
    return {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


class WorkpackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        self.out = Path(self.temporary.name) / "collected"
        self.files = {}
        ids = [f"m15-fb-confirmatory-48-f{family}-{i:02d}"
               for family in (1, 2, 3) for i in range(1, 17)]
        registry = seal({"population_options": [{"query_ids": ids}]}, "registry_sha256")
        self.write(collector.POPULATION + "/population_registry.json", registry)
        public = {"instances": [{"query_id": qid, "natural_language": "字符"} for qid in ids]}
        self.write(collector.WORKLOAD + "/public_instances.json", public)
        self.write(collector.WORKLOAD + "/family_contracts.json", {"families": []})
        # Its bytes are verified; parsing the oracle would make this test fail.
        self.write(collector.WORKLOAD + "/sealed_oracles.json", b"opaque oracle bytes\x00\xff")
        for template in collector.TEMPLATES:
            self.write(collector.WORKLOAD + "/templates/" + template, b"SELECT original template\n")
        self.manifest = seal({"paper_result": False, "instance_count": 48, "note": "λ",
            "population_registry_sha256": registry["registry_sha256"],
            "output_files": {name: bytes_record(self.files[collector.WORKLOAD + "/" + name])
                             for name in collector.OUTPUTS},
            "template_files": {name: bytes_record(self.files[collector.WORKLOAD + "/templates/" + name])
                               for name in collector.TEMPLATES}}, "workload_sha256", False)
        self.write(collector.WORKLOAD + "/workload_manifest.json", self.manifest)
        self.schedule = seal({"workload_sha256": self.manifest["workload_sha256"],
            "query_ids": ids, "seen_family_query_ids": ids[:32],
            "cold_family_query_ids": ids[32:]}, "schedule_sha256")
        self.write(collector.FREEZE + "/measurement_schedule.json", self.schedule)
        self.write(collector.FREEZE + "/population_approval.json", {"approved": "existing only"})
        self.write(collector.FREEZE + "/author_selection_snapshot.json", {"choice": "48"})
        freeze = seal({"status": "success", "slurm_job_id": "3793747",
            "workload_sha256": self.manifest["workload_sha256"],
            "schedule_sha256": self.schedule["schedule_sha256"],
            "population_source": {"registry_sha256": registry["registry_sha256"]},
            "artifact_files": {name[len(collector.FREEZE) + 1:]: bytes_record(data)
                for name, data in self.files.items() if name.startswith(collector.FREEZE + "/")}},
            "manifest_sha256")
        self.write(collector.FREEZE + "/run_manifest.json", freeze)
        producer = seal({"status": "success", "slurm_job_id": "3793727",
            "output": {"registry_sha256": registry["registry_sha256"],
                "registry_file_sha256": bytes_record(self.files[collector.POPULATION + "/population_registry.json"])["sha256"]}},
            "manifest_sha256")
        self.write(collector.POPULATION + "/run_manifest.json", producer)
        for run, job in ((collector.FREEZE, "3793747"), (collector.POPULATION, "3793727")):
            self.write(run + "/run_status.json", {"status": "success", "slurm_job_id": job})

    def write(self, name, value):
        data = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.files[name] = data

    def pins(self, **extra):
        return patch.multiple(collector, WORKLOAD_SHA256=self.manifest["workload_sha256"],
                              SCHEDULE_SHA256=self.schedule["schedule_sha256"], **extra)

    def test_exact_bytes_only_no_data_scan_or_oracle_parse(self):
        unrelated = self.root / collector.FREEZE / "large-data.tar.gz"
        unrelated.write_bytes(b"Must never be collected")
        with self.pins(), patch.object(collector.subprocess, "run", side_effect=AssertionError("No external calls")):
            result = collector.collect(self.root, self.out)
        self.assertTrue(result["success"], result)
        self.assertEqual(len(result["files"]), 21)
        self.assertEqual(len(result["validated"]["query_ids"]), 48)
        self.assertEqual(result["validated"]["seen_query_count"], 32)
        with tarfile.open(self.out / result["archive"]["path"], "r:gz") as archive:
            self.assertEqual(set(archive.getnames()), set(self.files))
            for member in archive.getmembers():
                self.assertTrue(member.isfile())
                self.assertEqual(archive.extractfile(member).read(), self.files[member.name])
        self.assertEqual({name: (self.root / name).read_bytes() for name in self.files}, self.files)
        self.assertFalse(result["oracle_content_parsed"])

    def test_real_cli_pin_rejects_an_unrelated_but_internally_valid_workload(self):
        result = collector.collect(self.root, self.out)
        self.assertFalse(result["success"])
        self.assertIn("workload_sha256 mismatch", result["error"]["message"])
        self.assertEqual(list(self.out.iterdir()), [self.out / "collection_receipt.json"])

    def test_changed_bytes_and_missing_manifest_leave_diagnostics_only(self):
        for kind in ("changed", "missing"):
            with self.subTest(kind=kind):
                if kind == "changed":
                    (self.root / collector.WORKLOAD / "public_instances.json").write_bytes(b"changed")
                else:
                    (self.root / collector.WORKLOAD / "workload_manifest.json").unlink()
                destination = self.out.with_name(kind)
                with self.pins():
                    result = collector.collect(self.root, destination)
                self.assertFalse(result["success"])
                self.assertEqual(list(destination.iterdir()), [destination / "collection_receipt.json"])

    def test_symlink_in_the_selected_files_is_rejected(self):
        template = self.root / collector.WORKLOAD / "templates" / sorted(collector.TEMPLATES)[0]
        external = Path(self.temporary.name) / "external-template"
        external.write_bytes(template.read_bytes())
        template.unlink()
        template.symlink_to(external)
        with self.pins():
            result = collector.collect(self.root, self.out)
        self.assertFalse(result["success"])
        self.assertIn("Symbolic", result["error"]["message"])

    def test_template_inventory_cannot_add_a_parent_path(self):
        self.manifest["template_files"]["../../../extra"] = self.manifest["template_files"].pop(sorted(collector.TEMPLATES)[0])
        self.manifest.pop("workload_sha256")
        self.manifest = seal(self.manifest, "workload_sha256", False)
        self.write(collector.WORKLOAD + "/workload_manifest.json", self.manifest)
        with self.pins():
            result = collector.collect(self.root, self.out)
        self.assertFalse(result["success"])
        self.assertIn("nine templates", result["error"]["message"])

    def test_aggregate_budget_and_output_boundaries(self):
        with self.pins(MAX_BYTES=sum(len(data) for data in self.files.values()) - 1):
            result = collector.collect(self.root, self.out)
        self.assertFalse(result["success"])
        self.assertIn("budget", result["error"]["message"])
        with self.assertRaises(ValueError):
            collector.collect(self.root, self.out)
        with self.assertRaises(ValueError):
            collector.collect(self.root, self.root / collector.FREEZE / "new-output")

    def test_optional_status_is_two_bounded_read_only_commands_with_no_retry(self):
        response = subprocess.CompletedProcess("squeue", 0, b"3804011|RUNNING\n", b"")
        timeout = subprocess.TimeoutExpired("sacct", 10, output=b"partial status\n")
        with self.pins(), patch.object(collector.subprocess, "run", side_effect=[response, timeout]) as run:
            result = collector.collect(self.root, self.out, job_status=True)
        self.assertTrue(result["success"])
        self.assertEqual(run.call_count, 2)
        self.assertEqual([call.args[0][0] for call in run.call_args_list], ["squeue", "sacct"])
        self.assertTrue(all(call.kwargs["timeout"] == 10 for call in run.call_args_list))
        self.assertFalse(result["job_status"][1]["success"])
        self.assertEqual(result["job_status"][1]["stdout"], "partial status\n")
        saved = json.loads((self.out / "collection_receipt.json").read_text())
        self.assertEqual(saved["job_status"], result["job_status"])


if __name__ == "__main__":
    unittest.main()
