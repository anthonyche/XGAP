"""One local paid-selection pilot over an existing, frozen FinBench partition."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from itertools import permutations
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.experiments.finbench_paid_selection import (
    FIXED_QUERY_IDS, prepare_finbench_paid_selection, run_finbench_paid_selection,
)
from xgap.experiments.finbench_paid_journal import PaidSelectionJournal
from xgap.experiments.m15_finbench_federation import canonicalize_finbench_rows
from xgap.experiments.m15_finbench_partition import (
    load_finbench_source_partition, validate_finbench_source_identity,
)
from xgap.experiments.m15_finbench_workload import load_finbench_primary_workload
from xgap.experiments.m15_fixture_loader import (
    FusekiGraphStoreFixtureLoader, Neo4jParameterizedFixtureLoader,
)
from xgap.experiments.m15_native_services import (
    LoopbackPortReservations, ServiceSpec, _fuseki_server_configuration,
    _neo4j_configuration, inspect_java_runtime, start_service,
    stop_service, wait_for_service_health,
)
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.scheduler import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


METHODS = ("fixed_hash", "fixed_bind", "paid_selection")
BALANCED_SCHEMA = "xgap-finbench-paid-selection-balanced-v1"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path, value, *, sealed=False):
    encoded = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if sealed:
        with path.open("x") as stream:
            stream.write(encoded)
    else:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(encoded)
        temporary.replace(path)


def _fingerprints(workload, partition, order_file):
    paths = [*sorted((REPO / "src/xgap").rglob("*.py")), Path(__file__),
             REPO / "services/m15-native-runtime.lock.json", order_file]
    paths.extend(p for p in workload.rglob("*") if p.is_file())
    paths.extend(partition / name for name in (
        "source_partition_manifest.json", "load_neo4j_batches.jsonl", "load_fuseki.ttl"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("Measured source and frozen inputs must be regular files")
    return {str(path): {"bytes": path.stat().st_size, "sha256": _sha(path)} for path in paths}


def _orders(raw, candidates, *, require_exposed=True):
    ids = raw.get("query_ids")
    if not isinstance(ids, list) or len(ids) != len(set(ids)) or set(ids) != set(candidates):
        raise ValueError("Orders must name exactly the prepared queries once")
    if require_exposed and set(ids) != set(FIXED_QUERY_IDS):
        raise ValueError("This pilot only admits the original three integration-exposed query IDs")
    for key in ("method_orders", "acquisition_orders"):
        if not isinstance(raw.get(key), dict) or set(raw[key]) != set(ids):
            raise ValueError("Orders must cover every selected query exactly")
    for qid in ids:
        strategies = {candidate.plan.metadata["physical_strategy"] for candidate in candidates[qid]}
        for key, expected in (("method_orders", set(METHODS)), ("acquisition_orders", strategies)):
            values = raw[key][qid]
            if not isinstance(values, list) or len(values) != len(expected) or set(values) != expected:
                raise ValueError("Method and acquisition orders must be exact permutations")


def _schedule(orders, candidates, public):
    """Admit the original pilot or the predeclared six-block, full48 schedule."""
    if orders.get("schema_version") != BALANCED_SCHEMA:
        _orders(orders, candidates)
        return [orders]
    population = [item["query_id"] for item in public["public_instances"]["instances"]]
    ids, blocks = orders.get("query_ids"), orders.get("blocks")
    if (len(population) != 48 or len(set(population)) != 48 or not isinstance(ids, list)
            or len(ids) != 48 or set(ids) != set(population) or set(candidates) != set(population)
            or not isinstance(blocks, list) or len(blocks) != 6):
        raise ValueError("Balanced execution requires all original 48 queries in exactly six blocks")
    block_ids = [block.get("block_id") for block in blocks]
    if any(not isinstance(value, str) or not value.strip() for value in block_ids) or len(set(block_ids)) != 6:
        raise ValueError("Balanced block IDs must be unique nonblank strings")
    for block in blocks:
        _orders(block, candidates, require_exposed=False)
    for qid in ids:
        if {tuple(block["method_orders"][qid]) for block in blocks} != set(permutations(METHODS)):
            raise ValueError("Every query must cover all six method permutations")
        for position in range(3):
            directions = [tuple(block["acquisition_orders"][qid]) for block in blocks
                          if block["method_orders"][qid].index("paid_selection") == position]
            if len(directions) != 2 or directions[0] != directions[1][::-1]:
                raise ValueError("Every paid-method position must contain both acquisition directions")
    if orders.get("maximum_plan_runs") != 1440 or orders.get("maximum_query_calls") != 2880:
        raise ValueError("Balanced execution must declare its 1440-plan and 2880-query-call limits")
    return blocks


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _block_preparation(preparation, query_ids):
    """Reorder the already compiled catalog; never compile another candidate."""
    result = {key: value for key, value in preparation.items() if key != "preparation_sha256"}
    by_id = {qid: [] for qid in query_ids}
    for item in preparation["plan_catalog"]:
        by_id[item["query_id"]].append(item)
    result["selected_query_ids"] = list(query_ids)
    result["plan_catalog"] = [item for qid in query_ids for item in by_id[qid]]
    result["plan_catalog_sha256"] = _digest(result["plan_catalog"])
    result["source_preparation_sha256"] = preparation["preparation_sha256"]
    result["preparation_view"] = "order-only view; no additional compilation"
    result["preparation_sha256"] = _digest(result)
    return result


def _unattempted(public, block):
    return {"status": "not_attempted", "completed": False, "success": False,
        "block_id": block["block_id"], "attempted_plan_runs": 0,
        "total_remote_calls": None, "total_bytes_moved": None, "oracle_content_parsed": False,
        "queries": [{"query_id": item["query_id"], "family_id": item["family_id"],
            "split_role": item["split_role"], "integration_exposed": item["query_id"] in FIXED_QUERY_IDS,
            "selected_for_attempt": item["query_id"] in block["query_ids"],
            "methods": [{"method_id": method, "status": "not_attempted", "executions": [],
                "selection": None, "final_rows": None, "wall_ms": None,
                "total_remote_calls": None, "total_bytes_moved": None} for method in METHODS]}
            for item in public["public_instances"]["instances"]]}


def _campaign_record(public, blocks):
    return {"schema_version": "xgap-finbench-paid-selection-blocks-v1", "completed": False,
        "all_blocks_sealed": False, "stop_reason": None,
        "population_count": len(public["public_instances"]["instances"]),
        "cache_policy": "one fresh owned database load; shared progressively warm mixed sequence across blocks; no warmup or reset",
        "model_calls": 0, "automatic_retries": 0,
        "blocks": [_unattempted(public, block) for block in blocks]}


def _run_blocks(*, public, candidates, preparation, scheduler, blocks, output,
                deadline, record, on_update):
    """Run each admitted block once, then seal even the unattempted remainder."""
    for index, block in enumerate(blocks):
        block_root = output / f"block-{index + 1:02d}"
        block_root.mkdir(exist_ok=False)
        measurement, sink = None, None
        if record["stop_reason"] is None and time.perf_counter() >= deadline:
            record["stop_reason"] = "global_work_budget_exhausted_before_block"
        if record["stop_reason"] is None:
            measurement = {}
            try:
                sink = PaidSelectionJournal(block_root / "journal", measurement)
                run_finbench_paid_selection(public_workload=public, candidates_by_query=candidates,
                    preparation_receipt=_block_preparation(preparation, block["query_ids"]),
                    scheduler=scheduler, method_orders=block["method_orders"],
                    acquisition_orders=block["acquisition_orders"], query_ids=block["query_ids"],
                    record=measurement, on_update=sink,
                    max_elapsed_seconds=min(600.0, max(0.001, deadline - time.perf_counter())))
                if not measurement.get("executions_sealed_before_evaluation"):
                    raise ValueError("Paid-selection core did not seal its execution outcomes")
                if measurement.get("completed") is not True:
                    record["stop_reason"] = measurement.get("stop_reason") or "incomplete_block; no retry"
            except Exception as error:
                record["stop_reason"] = f"{type(error).__name__}: {error}"
                record["blocks"][index]["driver_error"] = record["stop_reason"]
        if not measurement:
            measurement = _unattempted(public, block)
        # An interrupted core remains raw; the driver seal never invents a core success/seal.
        sealed = block_root / "measurement_sealed.json"
        seal_started = time.perf_counter()
        _write(sealed, measurement, sealed=True)
        seal_ms = (time.perf_counter() - seal_started) * 1000
        summary = record["blocks"][index]
        summary.update(status=measurement.get("status", "interrupted"),
            completed=measurement.get("completed") is True,
            success=measurement.get("success") is True,
            attempted_plan_runs=measurement.get("attempted_plan_runs", 0),
            total_remote_calls=measurement.get("total_remote_calls"),
            total_bytes_moved=measurement.get("total_bytes_moved"),
            measurement_file=str(sealed.relative_to(output)), measurement_sha256=_sha(sealed),
            sealed=True, core_execution_seal_sha256=measurement.get("execution_seal_sha256"),
            full_ledger_seal_ms=seal_ms, full_ledger_seal_bytes=sealed.stat().st_size,
            full_ledger_seal_in_method_wall=False)
        for field, known in (("total_remote_calls", "known_remote_calls"),
                             ("total_bytes_moved", "known_exchange_bytes")):
            summary[known] = sum(action[field] for query in measurement.get("queries", [])
                for method in query["methods"] for action in method["executions"]
                if type(action.get(field)) is int)
        for target, source in zip(summary["queries"], measurement.get("queries", [])):
            if target["query_id"] != source["query_id"]:
                raise ValueError("A block changed the original population identity/order")
            for target_method, source_method in zip(target["methods"], source["methods"]):
                for key in ("status", "wall_ms", "total_remote_calls", "total_bytes_moved"):
                    target_method[key] = source_method.get(key)
        if sink is not None:
            receipt = sink.receipt()
            _write(block_root / "journal_receipt.json", receipt, sealed=True)
            summary["journal_receipt_file"] = str((block_root / "journal_receipt.json").relative_to(output))
        on_update()
    record["completed"] = all(block["completed"] for block in record["blocks"])
    record["all_blocks_sealed"] = all(block.get("sealed") for block in record["blocks"])
    record["attempted_plan_runs"] = sum(block["attempted_plan_runs"] for block in record["blocks"])
    for key in ("total_remote_calls", "total_bytes_moved"):
        costs = [block[key] for block in record["blocks"]]
        record[key] = sum(costs) if all(type(value) is int for value in costs) else None
        record["known_" + key] = sum(value for value in costs if type(value) is int)
    for key in ("known_remote_calls", "known_exchange_bytes"):
        record[key] = sum(block[key] for block in record["blocks"])
    _write(output / "campaign_sealed.json", record, sealed=True)
    on_update()
    return record


class RecordedClient:
    """Retain each actual client attempt; fixture and measured calls stay distinct."""

    def __init__(self, client, journal):
        self.client, self.backend_id, self.journal = client, client.backend_id, journal
        self.attempts = self.load_attempts = 0
        self.lock = threading.Lock()

    def _append(self, item):
        with self.lock, self.journal.open("a") as stream:
            stream.write(json.dumps(item, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()

    def execute(self, artifact):
        is_load = artifact.artifact_id.startswith("m15-load-neo4j-")
        with self.lock:
            self.attempts += 1
            self.load_attempts += int(is_load)
            index = self.attempts
        binding = {"backend_id": self.backend_id, "call_index": index,
                   "artifact_id": artifact.artifact_id, "fixture_load": is_load}
        self._append({**binding, "event": "attempt", "at": _now(),
                      "artifact": artifact.to_dict() if not is_load else None})
        try:
            result = self.client.execute(artifact)
        except Exception as error:
            self._append({**binding, "event": "exception", "error_type": type(error).__name__})
            raise
        self._append({**binding, "event": "result", "execution_report": result.to_dict()})
        return result


def _evaluate(measurement, workload, *, on_oracle_loaded=lambda: None):
    """Read answers once after the immutable execution record has been sealed."""
    oracle = load_finbench_primary_workload(workload)
    on_oracle_loaded()
    return _evaluate_record(measurement, oracle)


def _evaluate_record(measurement, oracle):
    answers = oracle["sealed_oracles"]["queries"]
    result = {"scope": "independent post-seal audit of attempted final and acquisition executions; no answer reuse",
              "oracle_workload_sha256": oracle["manifest"]["workload_sha256"],
              "queries": [], "attempted_final_count": 0, "exact_final_count": 0,
              "attempted_acquisition_count": 0, "exact_acquisition_count": 0,
              "indeterminate_final_count": 0, "indeterminate_acquisition_count": 0}

    def compare(action, query):
        compared = {"execution_status": action["status"], "exact": None,
                    "actual_rows": None, "plan_id": action.get("plan_id"),
                    "physical_strategy": action.get("physical_strategy")}
        if action["status"] == "not_attempted":
            return compared
        role = action["role"]
        runtime = action.get("runtime_result")
        if (action["status"] == "started" and runtime is None
                and action.get("call_wall_ms") is None):
            compared["dispatch_status"] = "indeterminate"
            result[f"indeterminate_{role}_count"] += 1
            return compared
        result[f"attempted_{role}_count"] += 1
        if isinstance(runtime, dict) and runtime.get("success") is True:
            try:
                actual = canonicalize_finbench_rows(query["family_id"], runtime["final_rows"])
                expected = canonicalize_finbench_rows(query["family_id"], answers[query["query_id"]]["final_rows"])
                compared.update(exact=actual == expected, actual_rows=actual,
                                expected_row_count=len(expected), actual_row_count=len(actual))
            except (ValueError, KeyError, TypeError) as error:
                compared.update(exact=False, evaluation_error=str(error))
        elif isinstance(runtime, dict) and runtime.get("success") is False:
            compared["exact"] = False
        result[f"exact_{role}_count"] += int(compared["exact"] is True)
        return compared

    for query in measurement["queries"]:
        item = {key: query[key] for key in ("query_id", "family_id", "split_role", "integration_exposed")}
        item["methods"] = []
        for method in query["methods"]:
            finals = [action for action in method["executions"] if action["role"] == "final"]
            if len(finals) > 1:
                raise ValueError("A method must not execute its final answer more than once")
            compared = {"method_id": method["method_id"], "execution_status": "not_attempted",
                        "exact": None, "actual_rows": None}
            if finals:
                compared.update(compare(finals[0], query))
            compared["acquisitions"] = [compare(action, query) for action in method["executions"]
                                        if action["role"] == "acquisition"]
            item["methods"].append(compared)
        result["queries"].append(item)
    result["attempted_plan_count"] = result["attempted_final_count"] + result["attempted_acquisition_count"]
    result["exact_plan_count"] = result["exact_final_count"] + result["exact_acquisition_count"]
    result["indeterminate_plan_count"] = result["indeterminate_final_count"] + result["indeterminate_acquisition_count"]
    return result


def _evaluate_blocks(campaign, output, workload, *, on_oracle_loaded=lambda: None):
    if campaign.get("all_blocks_sealed") is not True:
        raise ValueError("All attempted and unattempted blocks must be sealed before reading answers")
    for block in campaign["blocks"]:
        path = output / block["measurement_file"]
        if block.get("sealed") is not True or _sha(path) != block["measurement_sha256"]:
            raise ValueError("A block execution seal is missing or changed")
    oracle = load_finbench_primary_workload(workload)
    on_oracle_loaded()
    result = {"scope": "all blocks independently audited after all execution seals; original query denominator retained",
              "oracle_load_count": 1, "blocks": []}
    for block in campaign["blocks"]:
        measurement = json.loads((output / block["measurement_file"]).read_bytes())
        evaluation = _evaluate_record(measurement, oracle)
        evaluation["block_id"] = block["block_id"]
        result["blocks"].append(evaluation)
    for key in ("attempted_final_count", "exact_final_count", "attempted_acquisition_count",
                "exact_acquisition_count", "attempted_plan_count", "exact_plan_count",
                "indeterminate_final_count", "indeterminate_acquisition_count", "indeterminate_plan_count"):
        result[key] = sum(block[key] for block in result["blocks"])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runtime-root", "java", "workload-root", "partition-root", "output", "order-file"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("--execute is required for owned native services and queries")
    runtime, workload, partition, output, order_file = (
        Path(value).absolute() for value in (args.runtime_root, args.workload_root,
        args.partition_root, args.output, args.order_file))
    if any(path.is_symlink() for path in (runtime, workload, partition, output, order_file)):
        parser.error("Input roots, output and order file must not be symlinks")
    if any(output.resolve().is_relative_to(path.resolve()) for path in (runtime, workload, partition)):
        parser.error("Output must be outside shared distributions and frozen inputs")
    output.mkdir(exist_ok=False)
    started = time.perf_counter()
    record = {"schema_version": "xgap-finbench-paid-selection-native-v1", "started_at": _now(),
              "execution_environment": "local", "platform": platform.platform(),
              "source_identity_mode": "source_archive", "paper_result": False,
              "ordinary_P1_exercised": False, "A3_exercised": False,
              "model_calls": 0, "network_downloads": 0, "automatic_retries": 0,
              "work_deadline_seconds": 800, "cleanup_reserve_seconds": 100,
              "overall_budget_seconds": 900, "measurement_budget_seconds": 600,
              "native_plus_coordinator_rss_limit_bytes": 6 * 1024**3,
              "peak_sampled_rss_bytes": 0, "memory_limit_exceeded": False,
              "memory_monitor_error": None, "phase": "preparation", "success": False,
              "services": [], "health": [], "load_reports": {}, "shutdown": [],
              "whole_SF0_1_loaded": False, "oracle_content_parsed": False}
    save = lambda: _write(output / "native_run.json", record)
    save()
    state = output / "state"
    running, clients, measurement, campaign = [], {}, {}, None
    ports, monitor, before, setup_started = None, None, None, None
    monitor_stop = threading.Event()
    old_alarm, old_memory = signal.getsignal(signal.SIGALRM), signal.getsignal(signal.SIGUSR1)

    def abort(_signum, _frame):
        raise TimeoutError("Native pilot exceeded its finite time or sampled memory budget")

    def monitor_memory():
        while not monitor_stop.wait(1):
            try:
                observed = subprocess.run(["ps", "-axo", "pid=,pgid=,rss="], capture_output=True,
                                          text=True, timeout=3, check=False)
                if observed.returncode:
                    raise RuntimeError("RSS observation failed")
                groups = {service.process.pid for service in running}
                rss = sum(int(parts[2]) * 1024 for line in observed.stdout.splitlines()
                          if len(parts := line.split()) == 3 and
                          (int(parts[0]) == os.getpid() or int(parts[1]) in groups))
                record["peak_sampled_rss_bytes"] = max(record["peak_sampled_rss_bytes"], rss)
                if rss > record["native_plus_coordinator_rss_limit_bytes"]:
                    record["memory_limit_exceeded"] = True
                    os.kill(os.getpid(), signal.SIGUSR1)
                    return
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                record["memory_monitor_error"] = type(error).__name__
                os.kill(os.getpid(), signal.SIGUSR1)
                return

    signal.signal(signal.SIGALRM, abort)
    signal.signal(signal.SIGUSR1, abort)
    signal.alarm(800)
    try:
        order_bytes = order_file.read_bytes()
        orders = json.loads(order_bytes)
        public, candidates, preparation = prepare_finbench_paid_selection(workload, query_ids=orders["query_ids"])
        blocks = _schedule(orders, candidates, public)
        balanced = orders.get("schema_version") == BALANCED_SCHEMA
        candidate_count = sum(len(values) for values in candidates.values())
        if candidate_count != (96 if balanced else 6):
            raise ValueError("Prepared candidate count differs from the frozen experimental scope")
        campaign = _campaign_record(public, blocks)
        record.update(order_schema=orders["schema_version"], block_count=len(blocks),
            prepared_candidate_count=candidate_count, maximum_plan_runs=5 * sum(len(b["query_ids"]) for b in blocks),
            maximum_query_calls=10 * sum(len(b["query_ids"]) for b in blocks),
            cache_policy=campaign["cache_policy"], family_split_semantics="original seen/heldout family labels; not cache temperature",
            campaign_file="campaign_sealed.json")
        _write(output / "campaign_progress.json", campaign)
        part = load_finbench_source_partition(partition)
        archive_sha = validate_finbench_source_identity(public["manifest"], part, source_identity_mode="source_archive")
        pins = {"workload_sha256": public["manifest"]["workload_sha256"],
                "source_partition_sha256": part["partition_sha256"], "source_archive_sha256": archive_sha}
        if any(orders.get(key) != value for key, value in pins.items()):
            raise ValueError("Frozen orders differ from the actual source or workload identity")
        if balanced and orders.get("public_instances_file_sha256") != _sha(workload / "public_instances.json"):
            raise ValueError("Frozen orders differ from the original public instance bytes")
        if public["manifest"]["instance_count"] != 48 or part.get("total_source_rows") != 365181:
            raise ValueError("This pilot requires the original 48 queries and complete SF0.1 partition")
        if part.get("neo4j_load", {}).get("filename") != "load_neo4j_batches.jsonl":
            raise ValueError("This pilot requires the existing parameterized Neo4j partition")
        record["population"] = [{"query_id": item["query_id"], "family_id": item["family_id"],
            "split_role": item["split_role"], "integration_exposed": item["query_id"] in FIXED_QUERY_IDS,
            "measurement_status": "not_attempted"} for item in public["public_instances"]["instances"]]
        record["selected_query_ids"] = orders["query_ids"]
        record["source_pins"] = pins
        record["git_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
        record["git_status_before"] = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).splitlines()
        before = _fingerprints(workload, partition, order_file)
        _write(output / "prepared_inputs.json", {"created_at": _now(), "source_pins": pins,
            "preparation": preparation, "orders": orders, "source_and_input_files": before,
            "plans": {qid: [candidate.plan.to_dict() for candidate in values] for qid, values in candidates.items()},
            "backend_calls_before_seal": 0, "oracle_content_parsed": False}, sealed=True)
        with (output / "orders.json").open("xb") as stream:
            stream.write(order_bytes)
        record["prepared_inputs_sha256"] = _sha(output / "prepared_inputs.json")
        record["preparation_elapsed_seconds"] = time.perf_counter() - started
        products = {"neo4j": runtime / "neo4j-community-5.26.30", "fuseki": runtime / "apache-jena-fuseki-5.6.0"}
        for name, executable in (("neo4j", "bin/neo4j"), ("fuseki", "fuseki-server")):
            path = products[name] / executable
            if not path.is_file() or path.is_symlink() or not os.access(path, os.X_OK):
                raise ValueError("Existing native distribution is missing or not executable")
        record["java"] = inspect_java_runtime(args.java, required_major=21).to_dict()
        setup_started = time.perf_counter()
        for relative in ("neo4j/data", "neo4j/transactions", "neo4j/logs", "neo4j/run", "neo4j/import", "neo4j/plugins", "fuseki"):
            (state / relative).mkdir(parents=True)
        conf = state / "neo4j-conf"
        shutil.copytree(products["neo4j"] / "conf", conf)
        ports = LoopbackPortReservations.acquire(3)
        neo_port, bolt_port, rdf_port = ports.ports
        profile = {"profile_id": "finbench_sf0_1", "heap_initial_size": "1g", "heap_max_size": "2g", "pagecache_size": "1g"}
        neo_conf = _neo4j_configuration(neo4j_root=products["neo4j"], state_root=state,
            http_port=neo_port, bolt_port=bolt_port, resource_profile=profile, query_timeout_seconds=60)
        neo_conf = neo_conf.replace("one job-owned XGAP M15 allocation", "one owned local FinBench paid-selection pilot")
        (conf / "neo4j.conf").write_text(neo_conf)
        (output / "neo4j.conf").write_text(neo_conf)
        rdf_conf = _fuseki_server_configuration(query_timeout_seconds=75)
        (state / "fuseki/config.ttl").write_text(rdf_conf)
        (output / "fuseki-config.ttl").write_text(rdf_conf)
        neo_url, rdf_url = f"http://127.0.0.1:{neo_port}", f"http://127.0.0.1:{rdf_port}"
        isolated = {"JAVA_TOOL_OPTIONS": "", "_JAVA_OPTIONS": "", "JDK_JAVA_OPTIONS": ""}
        specs = (
            ServiceSpec("neo4j", "neo4j", "5.26.30", (str(products["neo4j"] / "bin/neo4j"), "console"), products["neo4j"],
                {**isolated, "JAVACMD": args.java, "NEO4J_CONF": str(conf), "NEO4J_HOME": str(products["neo4j"])},
                neo_url + "/db/neo4j/tx/commit", output / "neo4j.log"),
            ServiceSpec("fuseki", "fuseki", "5.6.0", (str(products["fuseki"] / "fuseki-server"), "--localhost", "--ping", "--port", str(rdf_port), "--update", "--mem", "/xgap"), products["fuseki"],
                {**isolated, "JAVA": args.java, "FUSEKI_HOME": str(products["fuseki"]), "FUSEKI_BASE": str(state / "fuseki"), "JVM_ARGS": "-Xms128m -Xmx1g"},
                rdf_url + "/$/ping", output / "fuseki.log"),
        )
        record.update(phase="service_start", service_specs=[spec.to_dict() for spec in specs],
                      neo4j_resource_profile=profile, client_timeout_seconds={"neo4j": 75, "fuseki": 90},
                      query_timeout_seconds={"neo4j": 60, "fuseki": 75})
        save()
        monitor = threading.Thread(target=monitor_memory, daemon=True)
        monitor.start()
        for index, spec in enumerate(specs):
            for port in ((0, 1) if index == 0 else (2,)):
                ports.release(port)
            service = start_service(spec)
            running.append(service)
            record["services"].append({"service_id": spec.service_id, "pid": service.process.pid})
            save()
            health = wait_for_service_health(service, timeout_seconds=120)
            record["health"].append(health.to_dict())
            save()
            if not health.success:
                raise RuntimeError("Owned native service failed readiness; no retry")
        neo_desc = BackendDescriptor("neo4j", "neo4j", "cypher", "property_graph", runtime={"timeout_seconds": 75})
        rdf_desc = BackendDescriptor("fuseki", "fuseki", "sparql", "rdf", runtime={"timeout_seconds": 90})
        neo, rdf = Neo4jClient(neo_desc), FusekiClient(rdf_desc)
        neo.http_url, neo.database, neo.user, neo.password = neo_url, "neo4j", "neo4j", ""
        rdf.base_url, rdf.dataset = rdf_url, "xgap"
        clients = {client.backend_id: RecordedClient(client, output / f"{client.backend_id}-executions.jsonl") for client in (neo, rdf)}
        rdf_loader = FusekiGraphStoreFixtureLoader(rdf_desc)
        rdf_loader.base_url, rdf_loader.dataset = rdf_url, "xgap"
        loaders = {"neo4j": Neo4jParameterizedFixtureLoader(clients["neo4j"]), "fuseki": rdf_loader}
        record["phase"] = "load_existing_SF0_1"
        save()
        for name, filename in (("neo4j", "load_neo4j_batches.jsonl"), ("fuseki", "load_fuseki.ttl")):
            report = loaders[name].load(partition / filename)
            record["load_reports"][name] = report.to_dict()
            save()
            if not report.success:
                raise RuntimeError("Frozen SF0.1 fixture load failed; no retry")
        record.update(whole_SF0_1_loaded=True, setup_elapsed_seconds=time.perf_counter() - setup_started,
                      phase="paid_selection")
        save()
        plugins = BackendPluginRegistry()
        for name, client in clients.items():
            plugins.register(NativeBackendPlugin(name, client))
        _run_blocks(public=public, candidates=candidates, preparation=preparation,
            scheduler=FederatedScheduler(BackendInvokeTool(plugins)), blocks=blocks, output=output,
            deadline=started + 800, record=campaign,
            on_update=lambda: _write(output / "campaign_progress.json", campaign))
        record.update(campaign_file_sha256=_sha(output / "campaign_sealed.json"),
                      phase="independent_evaluation")
        if not balanced:
            # Preserve the original pilot's standalone result path and evaluation shape.
            measurement = json.loads((output / campaign["blocks"][0]["measurement_file"]).read_bytes())
            _write(output / "measurement_sealed.json", measurement, sealed=True)
            record.update(measurement_file_sha256=_sha(output / "measurement_sealed.json"),
                          core_execution_seal_sha256=measurement.get("execution_seal_sha256"))
        save()
        record["oracle_content_read_started"] = True
        save()
        block_evaluation = _evaluate_blocks(campaign, output, workload,
            on_oracle_loaded=lambda: record.update(oracle_content_parsed=True))
        evaluation = block_evaluation if balanced else block_evaluation["blocks"][0]
        _write(output / "evaluation.json", evaluation, sealed=True)
        record["evaluation"] = {key: value for key, value in evaluation.items() if key not in ("queries", "blocks")}
        for index, item in enumerate(record["population"]):
            item["measurement_status"] = {block["block_id"]: [method["status"]
                for method in block["queries"][index]["methods"]] for block in campaign["blocks"]}
        record["success"] = (campaign.get("completed") is True
            and evaluation["attempted_final_count"] == sum(len(b["query_ids"]) for b in blocks) * 3
            and evaluation["attempted_plan_count"] == record["maximum_plan_runs"]
            and evaluation["exact_plan_count"] == evaluation["attempted_plan_count"])
    except Exception as error:
        record.update(error_type=type(error).__name__, error=str(error), success=False)
    finally:
        signal.alarm(0)
        if setup_started is not None and "setup_elapsed_seconds" not in record:
            record["setup_elapsed_seconds"] = time.perf_counter() - setup_started
            record["setup_completed"] = False
        elif setup_started is not None:
            record["setup_completed"] = True
        monitor_stop.set()
        if monitor is not None:
            monitor.join(timeout=4)
        for service in reversed(running):
            try:
                stopped = stop_service(service, timeout_seconds=30)
                record["shutdown"].append(stopped.to_dict())
                if not stopped.success or stopped.escalated_to_kill:
                    record["success"] = False
            except Exception as error:
                record["shutdown"].append({"service_id": service.spec.service_id,
                    "success": False, "error_type": type(error).__name__, "error": str(error)})
                record["success"] = False
        if ports is not None:
            ports.close()
        if state.exists() and all(service.process.poll() is not None for service in running):
            try:
                shutil.rmtree(state)
            except OSError as error:
                record.update(cleanup_error=str(error), success=False)
        record["owned_state_removed"] = not state.exists()
        signal.signal(signal.SIGALRM, old_alarm)
        signal.signal(signal.SIGUSR1, old_memory)
        record["client_attempts"] = {name: {"all": client.attempts, "fixture_load": client.load_attempts,
            "query": client.attempts - client.load_attempts} for name, client in clients.items()}
        if before is not None:
            try:
                after = _fingerprints(workload, partition, order_file)
                _write(output / "source_after.json", after, sealed=True)
                record["source_and_inputs_unchanged"] = before == after
                if before != after:
                    record["success"] = False
            except (OSError, ValueError) as error:
                record.update(source_verification_error=str(error), success=False)
        record.update(finished_at=_now(), total_elapsed_seconds=time.perf_counter() - started,
                      status="success" if record["success"] else "failed")
        if record["total_elapsed_seconds"] > 900 or record["memory_limit_exceeded"]:
            record.update(success=False, status="failed")
        save()
    print(json.dumps({"success": record["success"], "output": str(output),
                      "elapsed_seconds": record["total_elapsed_seconds"], "evaluation": record.get("evaluation"),
                      "error": record.get("error")}, allow_nan=False))
    return 0 if record["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
