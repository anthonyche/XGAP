# D2 cycle/W4 closed-endpoint admission — 3868918

2026-09-25. Complete MovieLens20M source; original presampled query/reference;
unchanged CPU/source/worker/request budgets. This is an offline complete-query
backend admission, not a natural-language or five-method experiment result.

## Verified result

- Job: COMPLETED/0:0, 160 seconds including offline source preparation, compt311.
- Source code: `c3437fc309ef54f35d51288a9c284abbe2323127`.
- Case: `D2-test-uniform-cycle-000-W4`, original native index 10.
- Answer: 20 rows; exact content and order equal all 20 frozen reference rows.
- Execution: 47742.11 ms; worker wall: 51289.98 ms; planning: 254.79 ms.
- Final native request: 41715.61 ms; one final-plan execution, five source calls,
  zero LLM calls and no current-query observation calls during search.
- HTTP response bodies: 29,185 bytes in total. Final response: 11,535 bytes.
- Sampled peak method/source RSS: 41,267,200 / 1,239,695,360 bytes
  (39.36 MiB / 1.155 GiB), below the unchanged 3/4-GiB limits.
- Processes stopped, observer sealed, owned groups drained and reconstructed
  serving copies reclaimed. Frozen source and query evidence retained.

Downloaded archive: 73,374 bytes, SHA-256
`bd0c54fcaed1eb4caaad01a697b75bc872f34792385e56ff9eabdf621dd7af2a`.
16 available artifact pins and all five compressed/decoded raw responses were
verified. The executed plan matches the pre-execution zero-call selection seal;
its final seven external membership keys equal the previous failed request's
keys. Unavailable external file pins are listed separately in the local audit;
they were not falsely reported as reverified from this small archive.

Local audit:
`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/closed-endpoints-audit-3868918.json`.
Raw extraction: `closed-endpoints-3868918` beneath that artifact root.

## What the result establishes

The general independent-endpoint binding repair now enables this previously
60-second-timeout query to return its exact answer within the original limits.
It does not establish a stable speedup ratio: the old run timed out and has no
completed execution latency, and there is only one successful run here. Do not
use the 160-second Slurm job wall time as query latency. The complete-source
run did not execute EXPLAIN/PROFILE; Expand(Into) evidence comes from the
previous real tiny diagnostic, not a captured full-source plan for this run.

The source remains substantial work: sampled source CPU 65.18 s. The main
Neo4j process has observed rchar delta 2,790,068,311, read_bytes 24,068,096,
minor faults 337,739 and major faults 0. These are sampled process counters,
not scanned-row measurements or I/O-wait duration. No scan reduction or I/O-wait
improvement is inferred. The last source request still needs about 41.72 s.

The frozen v3 estimator is unchanged; its independent greedy ordering proxy
still differs from the emitted stage ordering. This limitation remains explicit
and is not recast as measured native work or a resource guarantee. No fitting
or parameter tuning used the held-out answer/latency.

## Remaining admission and next bounded batch

The original 24-case native cohort has cumulative successful admission records
for indices 0–10 across preserved code versions, not one 24-case run on this
commit. Indices 11–23 remain unattempted. No earlier failed record is overwritten.
Next is original indices 11–18 in frozen order, eight unattempted cases, with
zero LLM calls and stop-on-first-failure. No previously passed query is rerun.
This next batch is backend admission, not the full formal matrix. Full native/
RDF cohort and release-factor/support/budget gates still precede formal launch.

Package `/Users/anthonyche/Downloads/xgapnext8-c3437fc-v1.zip`, 8,831 bytes,
SHA-256 `f5ee7d2e9c8aa5b05f2a26dd7ab93c0ba8fe174234896b3c5e3a0ed9df4374f6`.
It reuses the already deployed clean `c3437fc` checkout and frozen v3 profile.
Local checks verified the prior success archive, all eight frozen case contracts,
actual input files for indices 11/12, mutation rejection, Python 3.6 staging,
shell syntax and ZIP member equality. Raw files for indices 13–18 exist only on
the server; staging must hash-check them before submission. Inside the job,
zero-call planning of all eight cases seals plan hashes before source startup;
an unexpected full-edge read stops the gate before execution. Actual worker
plans are compared to those seals in the final receipt. Existing journal/output
blocks repeat submission. No estimator or source settings are revised.

Server journal: `/home/hxc859/xgap-ch6-artifacts/native-next8-c3437fc-v1`.
Output: `/home/hxc859/xgap-ch6-artifacts/formal-native-next8-closed-v1/D2`.
Expected log: `native-next8-closed-<job>.out` in the journal.
Expected archive: `/home/hxc859/xgap-native-next8-closed-<job>.tar.gz`.
The user successfully validated and submitted this package as **3868951**.
Running/terminal state is not yet received. Log: `native-next8-closed-3868951.out`
in the journal; expected archive: `/home/hxc859/xgap-native-next8-closed-3868951.tar.gz`.
No duplicate submission or checkout change. Automatic access remains unavailable;
the user has been asked for one read-only status/log query after completion.
Full formal launch is closed.


## Next-eight job terminal report — 3868951

The user reports COMPLETED/0:0, 87 s, compt311; both receipts success=true,
attempted=audited=8. Archive: 223,355 bytes, SHA-256
`4e2e37f1099c91ba303af1cff5426b245157cb8f32be10673fb3dee4e79fe0d0`.
The archive has now been locally verified: eight correct ordered answers,
seven empty references and one 20-row answer. See the
[next-eight audit and last-five handoff](ch6_next8_closed_admission_3868951.md).
Original indices 19–23 remain unattempted; do not rerun this successful batch.
