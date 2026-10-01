# INT-2: original FinBench workpack intake and source-identity bridge

2026-09-11; parent d1b9dc3b585c9db7e91473b2a737243fc16d7e21.
This is research integration engineering, not a new paper result.

## Frozen purpose and scope

R-E/INT needs independent answers for the original real queries; R-C needs the
same population and source identity across method comparisons. The actual original48
workpack pins the source archive, while the old small correctness entry demanded
a partition pin the original manifest does not contain. This admission mismatch
would block integration before either backend runs; it is not a catalog/hop bug.

Allowed changes:existing FinBench source-admission helper, live correctness entry,
native argument forwarding, independent reconstruction audit, affected small tests
and evidence/status documents. Do not rewrite original queries, registry, schedule,
answers, partition generators, catalog or planner. No new services/model jobs or
large-data development run. Accept on exact intake, public compilation and minimal
identity/entry/audit checks; actual native answers await verified source facts.

## Verified inputs and observations

The uploaded archive is 1,076,623 bytes, SHA-256
`094c0c39465abf03a7df6150efbb97cac5754fee04b18b2fd5d2458481912f78`.
The original collection receipt SHA-256 is
`8b5ee3372e7a2aaf8b774939b84ef29d9f0fbe298556bd4fe9489fe9a07c6133`.
All21 expected regular files match their recorded sizes/hashes, total10,286,576
uncompressed bytes. Original workload, registry and schedule validators accept.
The sealed oracle file was hashed/copied only; its answers were not parsed.

Local original bytes and receipts are retained under
`/Users/anthonyche/xgap-data/int-finbench-workpack-20260911/`.
The machine evidence below fingerprints this intake and the saved public check.

The existing public loader/compiler compiled all48 original query IDs into96
physical plans, each round-tripped through FederatedExecutionPlan. The original
32seen/16cold partition and three families of16 remain unchanged. This verifies
public contracts and compilation only:zero backend/model calls, no data loading,
no answer accuracy or native performance measurement. The metadata check's CPU
elapsed time is not an experimental planner-scaling result. The first invocation
failed at import because PYTHONPATH was missing; the saved script explicitly adds
src before the successful compilation check. No external action was repeated.

The supplied receipt contains a successful sacct observation:

```text
3804011|COMPLETED|0:0|00:14:28|gput064
```

Batch and extern records also show COMPLETED/0:0. The aggregate
job_status_success=false came from squeue reporting an invalid/missing ended job.
It does not imply model-job failure. Conversely, process completion alone does
not prove that all five model questions passed:their saved results are still needed.

## Implemented admission contract

`run_m15_live_finbench_correctness(..., source_identity_mode="partition")` keeps
its original default. Explicit `source_archive` accepts the original workpack
without editing it. The existing native entry exposes
`--finbench-source-identity-mode source_archive`, for correctness mode only, and
preserves the caller's tiny query subset/order. Campaign/confirmatory mode contracts
are unchanged.

Both modes require a valid matching source archive SHA and a valid actual partition
SHA. If the workload declares a partition pin, it must be valid and match in either
mode; an explicit null/empty value is not treated as absence. The partition loader
still verifies partition metadata and output file identities. The helper does not
itself certify original archive bytes:that remains the existing archive intake's
responsibility. Actual source archive identity, admission mode and partition identity
are sealed into plans and the run manifest.

The independent auditor replays admission against the public workload and validated
partition. Catalog, live manifest and native service manifest must agree on mode;
legacy missing mode means partition. It rejects unknown/null modes and recomputed
record hashes that hide an archive/layout mismatch. Plans still seal before loads,
and the answer oracle still opens after all selected plan executions. No execution
semantics, failure behavior, automatic retries or cost model changed.

## Focused verification

74 distinct affected/new tests have passing evidence, all offline:

- Source identity helper:47 passed in0.08s, one invocation.
- Live entry and audit:18 passed in0.37s. After adding native service-mode auditing,
  its one new rejection plus the two affected clean reconstruction cases passed
  in0.22s (3 passed/9 deselected); other successful cases were not rerun.
- Native CLI/lifecycle forwarding:7 new plus1 existing confirmatory-argument case
  have passing evidence. Initial run:3 passed/5 failed in0.26s because the new
  negative-test fixture omitted required java_command. Only those5 tests were
  corrected and rerun:5 passed in0.17s. This was test setup failure, not a hidden
  service or model attempt. Java/start/health/clients/loaders/shutdown are mocked.

Commands and evidence fingerprints are in
[the machine receipt](../../experiments/artifacts/finbench_workpack_intake_20260911.json).
No broad regression, native/model run, oracle-driven query selection, frozen
artifact regeneration or repeat of an already accepted milestone was performed.

## Remaining concrete boundary and next gate

The workpack contains definitions/metadata/sealed answers, not source graph facts.
One download of the pinned source archive from its official lock URL failed by
connection timeout (curl28,15.03s); the failure receipt is retained, automatic
retries0. The source already exists on Pioneer at
`/home/hxc859/.cache/xgap/finbench-v0.1.0/sf0.1.tar.gz`:
66,710,298 bytes, SHA-256
`f0359b5c4515cd5d86349b4a11a7470f6f153e42c5ac21c59e70f5c0d0b37a60`.
Recover those existing bytes instead of repeating the download or regenerating data.
After verification, reuse the existing partition builder and loaders. The fixed
small INT query set is original f1-01/f2-01/f3-01; all48 remain the formal cohort.
This fixes integration admission, not a complete ordinary-P1 method comparison:
FinBench hash/bind partition alternatives are not equivalent source replicas.

Also recover the existing12 stable files for the completed five-question model
run (plus a generated transfer receipt), then use the existing native interpretation
recording replay. Do not resubmit the job or rerun finalization; job.log is excluded
because finalization can append to it after hashing. Asynchronous replay validates
LINK, not colocated query-to-answer latency.

E1's gold-blind answer projection, real prior forecast/cost preparation and fair
frozen E1–E5 comparisons remain required. The September18 deadline and original
GrailQA150/FinBench48 denominators remain; no missing result becomes a success.
