"""Synchronous per-result persistence for the prepared FinBench cost experiment.

The core record is read-only here. Raw outcomes and selections are written once;
the append journal contains only changed row-free indexes. The caller writes the
complete sealed core record after measurement, independently of this sink.
"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time


def _encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class PaidSelectionJournal:
    """One new directory and one core attempt; a write failure forbids retry."""

    def __init__(self, output, record):
        started = time.perf_counter()
        self.output, self.record = Path(output), record
        self.output.mkdir(parents=True, exist_ok=False)
        for name in ("actions", "selections"):
            (self.output / name).mkdir()
        with (self.output / "events.jsonl").open("xb") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(self.output)
        _sync_directory(self.output.parent)
        self._files, self._written, self._states, self._methods = [], {}, {}, {}
        self._last_active, self._error = None, None
        self._bytes = self._callbacks = 0
        self._totals = {f"{scope}_{unit}": 0 for scope in ("included", "excluded", "unattributed")
                        for unit in ("ms", "bytes")}
        self._initialization_ms = (time.perf_counter() - started) * 1000

    def _once(self, kind, identity, value):
        key = (kind, identity)
        if key in self._written:
            return self._written[key]
        payload = _encode(value)
        filename = hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".json"
        relative = str(Path("actions" if kind == "action" else "selections") / filename)
        item = {"kind": kind, "identity": identity, "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload), "status": "started"}
        self._files.append(item)
        with (self.output / relative).open("xb") as stream:
            self._bytes += stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory((self.output / relative).parent)
        item["status"] = "durable"
        self._written[key] = item
        return item

    def __call__(self):
        if self._error is not None:
            raise RuntimeError("Paid-selection journal previously failed; writes cannot be retried")
        started, initial_bytes = time.perf_counter(), self._bytes
        owner, scope = None, "unattributed"
        self._callbacks += 1
        try:
            methods = [(q["query_id"], m) for q in self.record.get("queries", []) for m in q["methods"]]
            active = [(qid, m["method_id"]) for qid, m in methods if m["status"] == "started"]
            if len(active) > 1:
                raise ValueError("A sequential paid-selection journal cannot have multiple active methods")
            if active:
                owner, scope = active[0], "included"
                self._last_active = owner
            elif self._last_active and not self.record.get("executions_sealed_before_evaluation"):
                owner, scope = self._last_active, "excluded"
            changed = []
            for qid, method in methods:
                identity = qid + "/" + method["method_id"]
                actions = []
                for action in method["executions"]:
                    reference = None
                    if action["status"] in ("completed", "failed", "unknown"):
                        reference = self._once("action", action["action_id"], action)
                    actions.append({**{key: action.get(key) for key in
                        ("action_id", "role", "plan_id", "physical_strategy", "status")}, "result": reference})
                selection = method.get("selection")
                reference = self._once("selection", identity, selection) if selection is not None else None
                summary = {key: method.get(key) for key in ("method_id", "status", "wall_ms",
                           "total_remote_calls", "total_bytes_moved")}
                summary.update(query_id=qid, actions=actions, selection=reference)
                if summary != self._states.get(identity):
                    changed.append(summary)
                    self._states[identity] = summary
            event = {"callback": self._callbacks, "status": self.record.get("status"),
                     "scope": scope, "method": list(owner) if owner else None, "changed_methods": changed,
                     "completed": self.record.get("completed"), "stop_reason": self.record.get("stop_reason"),
                     "execution_seal_sha256": self.record.get("execution_seal_sha256")}
            if self._callbacks == 1:
                event.update(population=self.record.get("population"),
                             workload_sha256=self.record.get("workload_sha256"),
                             order_sha256=self.record.get("order_sha256"))
            payload = _encode(event)
            with (self.output / "events.jsonl").open("ab") as stream:
                self._bytes += stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception as error:
            self._error = {"type": type(error).__name__, "message": str(error), "callback": self._callbacks}
            raise
        finally:
            elapsed, written = (time.perf_counter() - started) * 1000, self._bytes - initial_bytes
            self._totals[scope + "_ms"] += elapsed
            self._totals[scope + "_bytes"] += written
            if owner:
                totals = self._methods.setdefault(owner, {"query_id": owner[0], "method_id": owner[1],
                    "callback_count": 0, "included_ms": 0.0, "excluded_ms": 0.0,
                    "included_bytes": 0, "excluded_bytes": 0})
                totals["callback_count"] += 1
                totals[scope + "_ms"] += elapsed
                totals[scope + "_bytes"] += written

    def receipt(self):
        """Return external accounting, including partial writes; never alter core."""
        return deepcopy({"schema_version": "xgap-finbench-paid-journal-v1",
            "output_root": str(self.output.resolve()), "success": self._error is None, "error": self._error,
            "initialization_ms": self._initialization_ms, "callback_count": self._callbacks,
            "bytes_written": self._bytes, "bytes_complete": self._error is None, **self._totals,
            "per_method": list(self._methods.values()), "files": self._files,
            "progress_path": "events.jsonl", "core_record_mutated": False, "automatic_retries": 0,
            "timing_scope": "callback indexing, serialization, hashing, synchronous writes and fsync",
            "included_rule": "callback enters while method.status is started",
            "excluded_rule": "terminal method summary after method wall; initial/final block callbacks unattributed",
            "write_failure_bytes": "known write-return bytes only; partial failed writes may add unknown bytes"})
