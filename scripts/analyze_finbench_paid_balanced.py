#!/usr/bin/env python3
"""Read sealed original48 balanced observations; never execute or read oracles."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics
import sys


METHODS = ("fixed_hash", "fixed_bind", "paid_selection")
QUERY_IDS = tuple(f"m15-fb-confirmatory-48-f{f}-{i:02d}" for f in (1, 2, 3) for i in range(1, 17))
BLOCK_IDS = tuple(f"balanced-{i:02d}" for i in range(6))
FAMILIES = ("f1_direct_transfer_control", "f2_temporal_path_control", "f3_aggregate_risk_ranking")
ORDER_SHA = "b6f0d3dcb981b1f2c66a49fb8c601ce73dfec453f2a39911e3ef256d3912380e"
PINS = {
    "workload_sha256": "63a8ef36bc7576033db93caa2aa486409bc90ecfc699385b61e7d02be4320a5f",
    "source_partition_sha256": "0ee8b18d3289ddb11fd78308f14584d20f073deaa50f72cfad74b1a379cdab2b",
    "source_archive_sha256": "f0359b5c4515cd5d86349b4a11a7470f6f153e42c5ac21c59e70f5c0d0b37a60",
}
SEED, RESAMPLES = 2026091212, 10000
COUNTS = tuple(f"{prefix}_{role}_count" for prefix in ("attempted", "exact", "indeterminate")
               for role in ("final", "acquisition", "plan"))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _index(items, key, expected):
    _require(isinstance(items, list), f"Missing list: {key}")
    result = {item[key]: item for item in items}
    _require(len(result) == len(items) and set(result) == set(expected), f"Identity/denominator mismatch: {key}")
    return result


class Inputs:
    def __init__(self, root):
        self.root, self.files = root.resolve(), {}

    def path(self, relative):
        path = self.root / relative
        _require(not Path(relative).is_absolute() and path.resolve().is_relative_to(self.root),
                 f"Artifact escapes input directory: {relative}")
        _require(path.is_file() and not path.is_symlink(), f"Missing regular artifact: {relative}")
        return path

    def read(self, relative, expected=None, *, decode=True):
        payload = self.path(relative).read_bytes()
        sha = hashlib.sha256(payload).hexdigest()
        _require(expected is None or expected == sha, f"File SHA mismatch: {relative}")
        self.files[str(relative)] = {"sha256": sha, "size_bytes": len(payload),
                                     "verified_against_recorded_pin": expected is not None}
        return json.loads(payload) if decode else payload


def _identity(query, qid):
    family = QUERY_IDS.index(qid) // 16
    _require(query.get("family_id") == FAMILIES[family]
             and query.get("split_role") == ("heldout_family" if family == 2 else "crossfit_seen_family")
             and query.get("integration_exposed") is qid.endswith("-01"), f"Population labels changed: {qid}")


def _seal(record, field):
    expected = record.get(field)
    _require(expected == _digest({k: v for k, v in record.items() if k != field}), f"Invalid {field}")


def _orders(orders):
    _require(orders.get("schema_version") == "xgap-finbench-paid-selection-balanced-v1"
             and orders.get("protocol_id") == "finbench-paid-balanced-20260912-v1"
             and orders.get("query_ids") == list(QUERY_IDS), "Not the frozen balanced original48 protocol")
    _require(all(orders.get(k) == v for k, v in PINS.items()), "Order source identity changed")
    blocks = _index(orders["blocks"], "block_id", BLOCK_IDS)
    permutations = list(itertools.permutations(METHODS))
    for b, bid in enumerate(BLOCK_IDS):
        block = blocks[bid]
        shuffled = list(QUERY_IDS)
        random.Random(2026091201 + b).shuffle(shuffled)
        _require(block["query_ids"] == shuffled, f"Question order changed: {bid}")
        _require(set(block["method_orders"]) == set(QUERY_IDS)
                 and set(block["acquisition_orders"]) == set(QUERY_IDS), "Incomplete frozen orders")
        for i, qid in enumerate(QUERY_IDS):
            slot = (i + b) % 6
            _require(tuple(block["method_orders"][qid]) == permutations[slot], "Method permutation changed")
            pair = block["acquisition_orders"][qid]
            _require(len(pair) == len(set(pair)) == 2
                     and sum(s.endswith("_hash") for s in pair) == 1
                     and sum(s.startswith("control_first_") for s in pair) == 1, "Invalid strategy pair")
            direction = (0, 0, 1, 1, 0, 1)[slot] ^ (i % 2)
            _require(pair[0].endswith("_hash") == (direction == 0), "Acquisition balance changed")
    return blocks


def _journal(inputs, block, measurement):
    """Verify immutable copies against the sealed record; retain partial failures."""
    methods = {(q["query_id"], m["method_id"]): m for q in measurement["queries"] for m in q["methods"]}
    name = block.get("journal_receipt_file")
    if name is None:
        _require(all(m["status"] == "not_attempted" for m in methods.values()), "Attempted block lacks journal receipt")
        return {}, {"status": "not_created", "per_method": []}
    receipt = inputs.read(name, block.get("journal_receipt_sha256"))
    _require(receipt.get("schema_version") == "xgap-finbench-paid-journal-v1"
             and receipt.get("core_record_mutated") is False and receipt.get("automatic_retries") == 0,
             "Incompatible journal receipt")
    expected = {}
    for (qid, mid), method in methods.items():
        for action in method["executions"]:
            if action["status"] in ("completed", "failed", "unknown"):
                expected["action", action["action_id"]] = action
        if method.get("selection") is not None:
            expected["selection", qid + "/" + mid] = method["selection"]
    found, byte_count = set(), 0
    base = Path(name).parent / "journal"
    for item in receipt["files"]:
        key = (item["kind"], item["identity"])
        _require(key not in found and key in expected, "Duplicate/unattributed journal outcome")
        found.add(key)
        if item.get("status") != "durable":
            _require(receipt.get("success") is False, "Successful journal contains non-durable outcome")
            continue
        relative = base / item["path"]
        value = inputs.read(relative, item["sha256"])
        _require(inputs.files[str(relative)]["size_bytes"] == item["size_bytes"]
                 and value == expected[key], f"Journal outcome differs from core: {key}")
        byte_count += item["size_bytes"]
    progress = inputs.read(base / receipt["progress_path"], decode=False)
    if receipt.get("success") is True:
        _require(found == set(expected), "Journal omitted a received outcome or selection")
        _require(receipt.get("bytes_complete") is True
                 and byte_count + len(progress) == receipt["bytes_written"], "Journal byte receipt mismatch")
        events = [json.loads(line) for line in progress.splitlines()]
        _require(len(events) == receipt["callback_count"]
                 and [e["callback"] for e in events] == list(range(1, len(events) + 1)), "Journal callbacks differ")
    per_method = {}
    for entry in receipt["per_method"]:
        key = entry["query_id"], entry["method_id"]
        _require(key in methods and key not in per_method, "Journal method identity mismatch")
        _require(all(_finite(entry[k]) for k in ("included_ms", "excluded_ms", "included_bytes", "excluded_bytes")),
                 "Invalid persistence cost")
        wall = methods[key].get("wall_ms")
        _require(not _finite(wall) or entry["included_ms"] <= wall + 0.001,
                 "Included persistence exceeds measured method wall")
        per_method[key] = entry
    for key in ("included_ms", "excluded_ms", "included_bytes", "excluded_bytes"):
        total = receipt.get(key)
        _require(_finite(total) and math.isclose(sum(p[key] for p in per_method.values()), total,
                                               rel_tol=1e-9, abs_tol=0.001), "Persistence allocation differs from receipt")
    _require(all(key in per_method for key, method in methods.items() if method["status"] != "not_attempted"),
             "Attempted method lacks persistence accounting")
    summary = {k: v for k, v in receipt.items() if k not in ("files", "per_method", "output_root")}
    summary.update(receipt_file=name, immutable_file_count=len(found))
    return per_method, summary


def _action_summary(action, evaluated, counts):
    status, role = action["status"], action["role"]
    _require(evaluated.get("execution_status") == status
             and all(evaluated.get(k) == action.get(k) for k in ("plan_id", "physical_strategy")),
             "Evaluation action identity/status differs from execution")
    exact = evaluated.get("exact")
    _require(exact is None or type(exact) is bool, "Invalid exactness type")
    indeterminate = status == "started" and action.get("runtime_result") is None and action.get("call_wall_ms") is None
    if status != "not_attempted":
        counts[("indeterminate" if indeterminate else "attempted") + "_" + role + "_count"] += 1
        counts["exact_" + role + "_count"] += int(exact is True)
    _require(evaluated.get("dispatch_status") == "indeterminate" if indeterminate
             else evaluated.get("dispatch_status") != "indeterminate", "Indeterminate dispatch classification differs")
    _require(exact is not True or isinstance(action.get("runtime_result"), dict)
             and action["runtime_result"].get("success") is True, "Exact answer lacks successful received result")
    for key in ("elapsed_ms", "call_wall_ms", "total_remote_calls", "total_bytes_moved"):
        _require(action.get(key) is None or _finite(action[key]), "Invalid recorded action cost")
    if status == "completed":
        _require(all(_finite(action.get(k)) for k in ("elapsed_ms", "call_wall_ms", "total_remote_calls", "total_bytes_moved")),
                 "Completed action has unknown cost")
    if status in ("completed", "failed"):
        runtime = action.get("runtime_result")
        _require(isinstance(runtime, dict) and runtime.get("success") is (status == "completed")
                 and all(runtime.get(k) == action.get(k) for k in
                         ("plan_id", "elapsed_ms", "total_remote_calls", "total_bytes_moved")),
                 "Charged outcome differs from raw runtime result")
    return {**{k: action.get(k) for k in ("action_id", "role", "plan_id", "physical_strategy", "status",
            "elapsed_ms", "call_wall_ms", "total_remote_calls", "total_bytes_moved", "error_type", "error")},
            "exact": exact, "indeterminate_dispatch": indeterminate,
            "evaluation_error": evaluated.get("evaluation_error")}


def _costs(actions, field, *, expected_actions=None, applicable=True):
    if not applicable:
        _require(not actions, "An inapplicable cost contains actions")
        return {"known": 0, "unknown_action_count": 0, "not_attempted_or_missing_action_count": 0,
                "total": 0, "status": "not_applicable"}
    attempted = [a for a in actions if a["status"] != "not_attempted"]
    values = [a.get(field) for a in attempted]
    known = sum(v for v in values if _finite(v))
    unknown = sum(not _finite(v) for v in values)
    expected = len(actions) if expected_actions is None else expected_actions
    _require(expected >= len(actions), "Cost action count exceeds its denominator")
    missing = expected - len(attempted)
    complete = expected > 0 and not unknown and not missing
    return {"known": known, "unknown_action_count": unknown,
            "not_attempted_or_missing_action_count": missing,
            "total": known if complete else None, "status": "complete" if complete else "unavailable_or_incomplete"}


def _persistence_costs(observations, expected_slots):
    result = {}
    for key in ("included_ms", "excluded_ms", "included_bytes", "excluded_bytes"):
        values = [o["persistence"].get(key) for o in observations]
        known = sum(v for v in values if _finite(v))
        missing = expected_slots - sum(_finite(v) for v in values)
        result["persistence_" + key] = None if missing else known
        result["persistence_known_" + key] = known
        result["persistence_unobserved_" + key + "_slots"] = missing
    return result


def _observations(inputs, campaign, evaluations, orders, catalog):
    blocks = _index(campaign["blocks"], "block_id", BLOCK_IDS)
    evblocks = _index(evaluations["blocks"], "block_id", BLOCK_IDS)
    observations, persistence, totals = [], [], Counter()
    for bid in BLOCK_IDS:
        block, ev = blocks[bid], evblocks[bid]
        _require(block.get("sealed") is True, "Unsealed measurement")
        record = inputs.read(block["measurement_file"], block["measurement_sha256"])
        if record.get("execution_seal_sha256") is not None:
            _seal(record, "execution_seal_sha256")
        _require(block.get("core_execution_seal_sha256") == record.get("execution_seal_sha256"), "Core seal differs")
        _require(not record.get("completed") or record.get("execution_seal_sha256") is not None, "Completed block lacks core seal")
        queries = _index(record["queries"], "query_id", QUERY_IDS)
        summaries = _index(block["queries"], "query_id", QUERY_IDS)
        eq = _index(ev["queries"], "query_id", QUERY_IDS)
        if record.get("frozen_orders") is not None:
            expected = {k: orders[bid][k] for k in ("query_ids", "method_orders", "acquisition_orders")}
            _require(record["frozen_orders"] == expected and record["order_sha256"] == _digest(expected), "Executed order changed")
            _require(record.get("population") == list(QUERY_IDS) and record.get("oracle_content_parsed") is False
                     and record.get("answers_evaluated") is False and record.get("model_calls") == 0
                     and record.get("automatic_retries") == 0, "Execution scope changed")
            _require(all(record.get(k) == PINS[k] for k in ("workload_sha256", "source_archive_sha256")), "Block source changed")
            _seal(record["preparation_receipt"], "preparation_sha256")
        per_method, journal = _journal(inputs, block, record)
        persistence.append({"block_id": bid, "journal": journal,
            "full_ledger_seal_ms": block.get("full_ledger_seal_ms"),
            "full_ledger_seal_bytes": block.get("full_ledger_seal_bytes"), "full_ledger_seal_in_method_wall": False})
        counts = Counter()
        for qid in QUERY_IDS:
            for query in (queries[qid], summaries[qid], eq[qid]):
                _identity(query, qid)
            methods = _index(queries[qid]["methods"], "method_id", METHODS)
            summary_methods = _index(summaries[qid]["methods"], "method_id", METHODS)
            em = _index(eq[qid]["methods"], "method_id", METHODS)
            for mid in METHODS:
                method, evaluated = methods[mid], em[mid]
                _require(all(summary_methods[mid].get(k) == method.get(k) for k in
                    ("status", "wall_ms", "total_remote_calls", "total_bytes_moved")), "Campaign method summary changed")
                actions = method["executions"]
                _require(len({a["action_id"] for a in actions}) == len(actions), "Duplicate action")
                expected_roles = ["acquisition", "acquisition", "final"] if mid == "paid_selection" else ["final"]
                _require([a["role"] for a in actions] == expected_roles or not actions
                         and method["status"] == "not_attempted", "Method action structure changed")
                acquisitions = [a for a in actions if a["role"] == "acquisition"]
                _require(not acquisitions or [a["physical_strategy"] for a in acquisitions]
                         == orders[bid]["acquisition_orders"][qid], "Executed acquisition order changed")
                for action in actions:
                    index = acquisitions.index(action) + 1 if action["role"] == "acquisition" else 1
                    _require(action["action_id"] == f"{qid}/{mid}/{action['role']}-{index}", "Action belongs to another method/query")
                    strategy = action.get("physical_strategy")
                    if strategy is not None:
                        _require(catalog.get((qid, strategy)) == action.get("plan_id"), "Action differs from prepared query/strategy")
                    else:
                        _require(mid == "paid_selection" and action["role"] == "final"
                                 and action["status"] == "not_attempted", "Attempted action lacks prepared identity")
                    if mid != "paid_selection":
                        _require(strategy.endswith("_hash") == (mid == "fixed_hash"), "Fixed strategy changed")
                _require(len(evaluated["acquisitions"]) == len(acquisitions), "Evaluation acquisition denominator changed")
                summarized = [_action_summary(a, e, counts) for a, e in zip(acquisitions, evaluated["acquisitions"])]
                finals = [a for a in actions if a["role"] == "final"]
                if finals:
                    summarized.append(_action_summary(finals[0], evaluated, counts))
                else:
                    _require(evaluated.get("exact") is None and evaluated["execution_status"] == "not_attempted", "Unrun method has answer")
                selection = method.get("selection")
                if selection is not None:
                    _require(mid == "paid_selection" and selection.get("answer_values_consulted") is False
                             and selection.get("sampled_answer_reused") is False, "Selection/answer scope changed")
                    costs = [{k: a[k] for k in ("action_id", "plan_id", "physical_strategy", "elapsed_ms", "total_bytes_moved")}
                             for a in acquisitions]
                    _require(selection["cost_inputs"] == costs, "Selection cost inputs differ")
                    winner = min(costs, key=lambda c: (c["elapsed_ms"], c["total_bytes_moved"], c["physical_strategy"]))
                    _require(selection["source_action_id"] == winner["action_id"]
                             and selection["selected_plan_id"] == winner["plan_id"]
                             and selection["selected_physical_strategy"] == winner["physical_strategy"]
                             and finals[0]["plan_id"] == winner["plan_id"]
                             and finals[0]["physical_strategy"] == winner["physical_strategy"], "Non-cost-only winner/final placement")
                _require(mid != "paid_selection" or not finals or finals[0]["status"] == "not_attempted"
                         or selection is not None, "Paid final lacks sealed winner")
                wall = method.get("wall_ms")
                _require(wall is None or _finite(wall), "Invalid method wall")
                eligible = method["status"] == "completed" and _finite(wall) and bool(summarized) \
                    and all(a["status"] == "completed" and a["exact"] is True for a in summarized)
                p = per_method.get((qid, mid), {})
                observations.append({"block_id": bid, "query_id": qid, "method_id": mid,
                    "status": method["status"], "wall_ms": wall, "six_repeat_eligible": eligible,
                    "final_exact": evaluated.get("exact"), "actions": summarized,
                    "selected_strategy": selection.get("selected_physical_strategy") if selection else None,
                    "selection_ms": selection.get("selection_ms") if selection else None,
                    "error_type": method.get("error_type"), "error": method.get("error"),
                    "persistence_observed": bool(p),
                    "persistence": {k: p.get(k) for k in ("included_ms", "excluded_ms", "included_bytes", "excluded_bytes")}})
        for prefix in ("attempted", "exact", "indeterminate"):
            counts[prefix + "_plan_count"] = counts[prefix + "_final_count"] + counts[prefix + "_acquisition_count"]
        _require(ev.get("oracle_workload_sha256") == PINS["workload_sha256"], "Evaluation workload changed")
        _require(all(ev.get(k) == counts[k] for k in COUNTS), "Block evaluation counters disagree")
        totals.update(counts)
    _require(all(evaluations.get(k) == totals[k] for k in COUNTS), "Campaign evaluation counters disagree")
    _require(totals["attempted_plan_count"] + totals["indeterminate_plan_count"] <= 1440, "Execution budget exceeded")
    counts = {k: totals[k] for k in COUNTS}
    for role, denominator in (("final", 864), ("acquisition", 576), ("plan", 1440)):
        counts["not_attempted_" + role + "_count"] = denominator - totals["attempted_" + role + "_count"] - totals["indeterminate_" + role + "_count"]
    return observations, persistence, counts


def _aggregate(observations):
    rows = []
    for qid in QUERY_IDS:
        family = QUERY_IDS.index(qid) // 16
        for mid in METHODS:
            repeats = [o for o in observations if o["query_id"] == qid and o["method_id"] == mid]
            valid = len(repeats) == 6 and all(o["six_repeat_eligible"] for o in repeats)
            actions = [a for o in repeats for a in o["actions"]]
            row = {"query_id": qid, "family_id": FAMILIES[family],
                "split_role": "heldout_family" if family == 2 else "crossfit_seen_family",
                "integration_exposed": qid.endswith("-01"), "method_id": mid,
                "repeat_denominator": 6, "observed_repeat_count": len(repeats),
                "completed_exact_repeats": sum(o["six_repeat_eligible"] for o in repeats),
                "status_counts": dict(Counter(o["status"] for o in repeats)),
                "median_wall_ms": statistics.median(o["wall_ms"] for o in repeats) if valid else None,
                "wall_ms_by_block": {o["block_id"]: o["wall_ms"] for o in repeats},
                "selected_strategies": dict(Counter(o["selected_strategy"] for o in repeats if o["selected_strategy"])),
                "indeterminate_dispatches": sum(a["indeterminate_dispatch"] for a in actions)}
            for label, field in (("query_calls", "total_remote_calls"), ("logical_exchange_bytes", "total_bytes_moved"),
                                 ("charged_scheduler_ms", "elapsed_ms"), ("call_boundary_ms", "call_wall_ms")):
                row[label] = _costs(actions, field, expected_actions=18 if mid == "paid_selection" else 6)
                row["acquisition_" + label] = _costs([a for a in actions if a["role"] == "acquisition"], field,
                    expected_actions=12 if mid == "paid_selection" else 0, applicable=mid == "paid_selection")
            row.update(_persistence_costs(repeats, 6))
            rows.append(row)
    return rows


def _percentile(values, p):
    values = sorted(values)
    at = (len(values) - 1) * p
    lo = int(at)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (at - lo)


def _comparisons(rows):
    medians = {(r["query_id"], r["method_id"]): r["median_wall_ms"] for r in rows}
    results = []
    for population, ids in (("original32_seen", QUERY_IDS[:32]), ("original16_heldout", QUERY_IDS[32:]),
                            ("predeclared30_unexposed_seen", tuple(q for q in QUERY_IDS[:32] if not q.endswith("-01")))):
        for baseline in METHODS[:2]:
            ratios = {q: medians[q, "paid_selection"] / medians[q, baseline] for q in ids
                      if all(_finite(medians[q, m]) and medians[q, m] > 0 for m in ("paid_selection", baseline))}
            complete = len(ratios) == len(ids)
            item = {"population": population, "comparison": "paid_selection/" + baseline,
                "query_denominator": len(ids), "complete_positive_pairs": len(ratios),
                "missing_pair_ids": [q for q in ids if q not in ratios], "per_query_ratios": ratios,
                "gmean_ratio": math.exp(statistics.mean(math.log(v) for v in ratios.values())) if complete else None,
                "percentile_interval_97_5": None,
                "interpretation": "below 1 favors paid; descriptive" if complete else "incomplete pairs; no population ratio"}
            if complete and population == "original32_seen":
                # Identical draws for the two comparisons; resample paired query units within each fixed family.
                rng = random.Random(SEED)
                strata = [[math.log(ratios[q]) for q in ids if q in QUERY_IDS[i:i + 16]] for i in (0, 16)]
                draws = [math.exp(sum(rng.choice(s) for s in strata for _ in range(len(s))) / len(ids))
                         for _ in range(RESAMPLES)]
                item["percentile_interval_97_5"] = [_percentile(draws, .0125), _percentile(draws, .9875)]
                item["interpretation"] = "conditional stratified query bootstrap; Bonferroni two-comparison convention"
            results.append(item)
    return results


def analyze(inputs):
    native = inputs.read("native_run.json")
    prepared = inputs.read("prepared_inputs.json", native["prepared_inputs_sha256"])
    orders = inputs.read("orders.json", ORDER_SHA)
    _require(prepared["orders"] == orders and native.get("source_pins") == PINS
             and prepared.get("source_pins") == PINS, "Prepared/native source pins differ")
    _seal(prepared["preparation"], "preparation_sha256")
    _require(prepared["preparation"]["plan_catalog_sha256"] == _digest(prepared["preparation"]["plan_catalog"]),
             "Prepared catalog hash differs")
    catalog_items = prepared["preparation"]["plan_catalog"]
    catalog = {(item["query_id"], item["physical_strategy"]): item["plan"]["plan_id"] for item in catalog_items}
    _require(len(catalog) == len(catalog_items) == 96 and {q for q, _ in catalog} == set(QUERY_IDS),
             "Prepared catalog does not cover the original96 plans")
    frozen = _orders(orders)
    campaign = inputs.read(native.get("campaign_file", "campaign_sealed.json"), native["campaign_file_sha256"])
    _require(campaign.get("all_blocks_sealed") is True and campaign.get("population_count") == 48,
             "Campaign lacks sealed original48 denominator")
    evaluation = inputs.read("evaluation.json", native.get("evaluation_file_sha256"))
    _require(evaluation.get("oracle_load_count") == 1, "Evaluation was not the once post-seal audit")
    _require(all(native.get("evaluation", {}).get(k) == evaluation.get(k) for k in COUNTS), "Native evaluation summary differs")
    observations, persistence, counts = _observations(inputs, campaign, evaluation, frozen, catalog)
    rows = _aggregate(observations)
    all_actions = [a for o in observations for a in o["actions"]]
    calls = _costs(all_actions, "total_remote_calls", expected_actions=1440)
    _require(calls["known"] <= 2880, "Query call budget exceeded")
    _require(campaign.get("known_remote_calls") == calls["known"]
             and campaign.get("known_exchange_bytes") == _costs(all_actions, "total_bytes_moved", expected_actions=1440)["known"],
             "Campaign known-cost totals differ from actions")
    if counts["attempted_plan_count"] == 1440 and calls["unknown_action_count"] == 0:
        _require(sum(client["query"] for client in native.get("client_attempts", {}).values()) == calls["known"],
                 "Native query-call receipt differs from charged action calls")
    after = inputs.read("source_after.json") if (inputs.root / "source_after.json").is_file() else None
    unchanged = prepared.get("source_and_input_files") == after if after is not None else None
    _require(unchanged is None or native.get("source_and_inputs_unchanged") is unchanged, "Source before/after receipt differs")
    method_costs = {}
    for mid in METHODS:
        selected = [o for o in observations if o["method_id"] == mid]
        actions = [a for o in selected for a in o["actions"]]
        expected_actions = 864 if mid == "paid_selection" else 288
        method_costs[mid] = {"method_slot_denominator": 288, "status_counts": dict(Counter(o["status"] for o in selected)),
            "observed_method_wall_ms": sum(o["wall_ms"] for o in selected if _finite(o["wall_ms"])),
            "unavailable_method_wall_slots": sum(not _finite(o["wall_ms"]) for o in selected),
            "query_calls": _costs(actions, "total_remote_calls", expected_actions=expected_actions),
            "logical_exchange_bytes": _costs(actions, "total_bytes_moved", expected_actions=expected_actions),
            "charged_scheduler_ms": _costs(actions, "elapsed_ms", expected_actions=expected_actions),
            "acquisition_scheduler_ms": _costs([a for a in actions if a["role"] == "acquisition"], "elapsed_ms",
                expected_actions=576 if mid == "paid_selection" else 0, applicable=mid == "paid_selection"),
            **_persistence_costs(selected, 288)}
    return {"status": "analyzed", "population_count": 48, "block_count": 6,
        "method_slot_denominator": 864, "final_slot_denominator": 864, "acquisition_slot_denominator": 576,
        "counts": counts, "campaign_completed": campaign.get("completed"), "stop_reason": campaign.get("stop_reason"),
        "native_success": native.get("success"), "native_error": native.get("error"),
        "source_receipts_unchanged": unchanged,
        "evaluation_provenance": "Saved post-seal evaluation; this analyzer never reads oracle contents. File identities do not independently prove chronology.",
        "bootstrap": {"seed": SEED, "resamples": RESAMPLES, "percentiles": [1.25, 98.75],
            "unit": "paired query, stratified within the two fixed seen families; six repeats reduced to median",
            "limitation": "Conditional sampling assumptions; no exact finite-sample coverage or unseen-family guarantee."},
        "comparisons": _comparisons(rows), "per_query": rows, "observations": observations,
        "method_costs": method_costs, "block_persistence": persistence,
        "separate_shared_costs": {"preparation_elapsed_seconds": native.get("preparation_elapsed_seconds"),
            "compilation_ms": prepared["preparation"].get("compilation_ms"), "setup_elapsed_seconds": native.get("setup_elapsed_seconds"),
            "native_overall_seconds": native.get("total_elapsed_seconds"), "client_attempts": native.get("client_attempts"),
            "scope": "Shared preparation/startup/load/cleanup are not added to each method or pooled from earlier runs."},
        "cost_scope": "Method wall already includes online persistence and both paid acquisitions. Scheduler elapsed is per plan, not summed parallel nodes. Bytes are logical exchange bytes, not wire traffic. No overhead subtraction.",
        "limitations": ["Prepared-plan comparison; no P1/A3, model, memory-transfer or scalability claim.",
            "One evolving-cache deployment with frozen balanced order; not isolated cold/warm latency.",
            "Full-population ratios require all six completed and exact actions for each paired method.",
            "Heldout16 and unexposed30 are separate descriptive views; primary denominator stays 32.",
            "Measured cost-only choice does not establish next-run latency optimality or a total-paid-cost bound."]}


def _markdown(result):
    lines = ["# FinBench balanced prepared-plan analysis", "", f"Status: {result['status']}. Original denominator: 48 queries, 6 blocks, 864 method slots.", ""]
    if result["status"] != "analyzed":
        return "\n".join(lines + ["Integrity validation failed; no statistical result is reported.", "", result["error"], ""])
    lines += ["| Population | Comparison | Complete pairs | Geometric mean ratio | 97.5% interval |",
              "|---|---|---:|---:|---| "]
    for c in result["comparisons"]:
        ratio = "unavailable" if c["gmean_ratio"] is None else f"{c['gmean_ratio']:.6f}"
        ci = c["percentile_interval_97_5"]
        lines.append(f"| {c['population']} | {c['comparison']} | {c['complete_positive_pairs']}/{c['query_denominator']} | {ratio} | "
                     + (f"[{ci[0]:.6f}, {ci[1]:.6f}]" if ci else "not reported") + " |")
    lines += ["", "Ratios below 1 favor paid selection. Intervals are conditional query-bootstrap intervals; heldout and sensitivity views are descriptive.", "",
        "| Method | Observed wall ms | Known query calls | Known logical bytes | Known charged scheduler ms | Online persistence ms | Post-method persistence ms |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for mid, c in result["method_costs"].items():
        included = "unavailable" if c["persistence_included_ms"] is None else f"{c['persistence_included_ms']:.3f}"
        excluded = "unavailable" if c["persistence_excluded_ms"] is None else f"{c['persistence_excluded_ms']:.3f}"
        lines.append(f"| {mid} | {c['observed_method_wall_ms']:.3f} | {c['query_calls']['known']} | {c['logical_exchange_bytes']['known']} | "
                     f"{c['charged_scheduler_ms']['known']:.3f} | {included} | {excluded} |")
    lines += ["", "Known costs are lower bounds when action costs are unavailable; JSON/CSV preserve unknown counts and all failure/unrun slots.", "",
              result["cost_scope"], "", *["- " + text for text in result["limitations"]], ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    source, output = args.input.resolve(), args.output.resolve()
    if output.is_relative_to(source) or source.is_relative_to(output):
        parser.error("Analysis output must be a fresh directory outside the raw input tree")
    output.mkdir(parents=True, exist_ok=False)
    inputs = Inputs(source)
    try:
        result = analyze(inputs)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        result = {"status": "invalid_artifacts", "error": f"{type(error).__name__}: {error}",
            "population_count": 48, "block_count": 6, "method_slot_denominator": 864,
            "per_query": _aggregate([]), "comparisons": [], "statistical_results_withheld": True}
    result.update(schema_version="xgap-finbench-paid-balanced-analysis-v1", protocol_id="finbench-paid-balanced-20260912-v1",
        created_at=datetime.now(timezone.utc).isoformat(), input_root=str(source),
        analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        input_files=inputs.files, oracle_files_opened=False, raw_files_modified=False)
    with (output / "analysis.json").open("x") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    with (output / "per_query.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result["per_query"][0]))
        writer.writeheader()
        writer.writerows({k: json.dumps(v, sort_keys=True, separators=(",", ":")) if isinstance(v, (dict, list)) else v
                         for k, v in row.items()} for row in result["per_query"])
    (output / "summary.md").write_text(_markdown(result))
    print(json.dumps({"status": result["status"], "output": str(output), "population_count": 48}))
    return 0 if result["status"] == "analyzed" else 1


if __name__ == "__main__":
    sys.exit(main())
