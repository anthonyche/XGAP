# D2 source-work diagnosis, 2026-09-23

User direction: stop blind query rewrites and repeated whole-pilot gates. Diagnose
scan work, page faults and I/O stalls on the captured failing request first.

`replay_rdf_source_work.py` runs exactly one unchanged captured SELECT against a
verified private copy of the full frozen graph store. It pins source/capture/JAR
and Java instrumentation, keeps the 60 s process / 4 GiB RSS / 768 MiB heap
budgets, and makes zero LLM calls. Copy, hash and compilation are setup, excluded
from the query-phase deltas. No global cache flushing or source mutation.

The Jena 5.6.0 diagnostic wraps the existing TupleIndex interfaces. It delegates
index weights, lookup and iteration unchanged; records lookups and returned
index tuples by index and bound-position mask, plus time inside those APIs.
These are **not all B-tree records/pages examined**. The cached all-variable
scan path is not intercepted; the captured query has fixed predicates. Counters
are not fed into the online planner. The wrapper and 1 Hz stack/proc sampling
have overhead, so these are diagnosis, not paper latency or speedup numbers.

Linux process deltas report minor/major faults, user/system ticks and proc I/O
counters. Per-second samples preserve the query stack and uninterruptible native
threads' wait channels. Missing Linux fields remain unavailable. CPU-wall gap
is not a measurement of I/O wait; major faults are not triple scans; read_bytes
is not HTTP traffic. An untouched/fresh private copy does not imply cold OS cache.
See [Linux delay accounting](https://www.kernel.org/doc/html/latest/accounting/delay-accounting.html)
and [Jena storage architecture](https://jena.apache.org/documentation/tdb/architecture.html).

Local validation on the existing synthetic TDB2 graph: the constant-key request
returns the same one witness; 7 index tuple yields from 7 lookups (1 POS, 6 SPO).
No real-source performance result yet. Next: a single exact 567-key failed
request, then a fix selected from the measured evidence, not another full gate.

## First measured replay

3859381 (`3a32d2e`, compt311), original query SHA
`26eb1410c89dac31234d77401afccc6e7cc47bc259a91aa651088abbd133ebb2`:
60.193 s process timeout; last query sample at 49.866 s, 6 witness rows,
91 index tuple yields. POS `?BB` has 7 find calls / 18 tuples / 38.365 s in
completed index API calls; a further POS find was pending for about 9.735 s.
Query-phase deltas: 1,910,075,392 storage read bytes, 466 major / 10,723 minor
faults, 215 user / 237 system ticks. Final sample is not the full query interval.
All 50 query stack samples are mapped integer reads; detailed stacks include
RecordBufferPage.format, BPTreeNode.iterator and range-iterator loadStack.
No uninterruptible native thread was captured, and task_delayacct availability
is unknown. Therefore do not invent an I/O wait duration from CPU-wall residuals.
The graph copy is 56,115,900,920 bytes. This run used a different compute node
from the old gates, and cannot be used as their paired latency comparison.

Pinned Jena source/bytecode shows BPTreeNode.iterator eagerly materializes child
pages for its range, before LIMIT can stop tuple consumption. This is a plausible
source of page-read amplification, supported by the observed stack, but physical
page counts are not yet instrumented. First isolate mapped versus direct buffered
file access with the **same captured query** and same 60 s / 4 GiB bounds on the
same node. Direct is Jena's file-access mode, not OS O_DIRECT. No new query rewrite,
source facts, estimator, baseline algorithm or official deployment default changes.

## Recurring measurement without rerunning a diagnostic suite

Owned source resources now retain Linux minor/major fault and I/O counter deltas
between first and last observations, on the existing 1 Hz RSS-component cadence.
Only owned source identities are read. PID reuse, a single sample, unavailable
fields and counter resets yield null, never a false zero; CPU/RSS guards stay
unchanged. The measurements do not claim process I/O equals source-only file I/O,
physical scans equal yielded tuples, or that wall-minus-CPU measures I/O waiting.
Four parser/identity/delta tests and seven existing resource/common-trial tests
pass. These counters have not yet been collected in a full-source online gate.

Diagnostic evidence was downloaded and checksum-verified as
`xgap-source-work-3859381.tar.gz`, SHA-256
`6feb8cebdaeb89112db8935645cb68948323422c9489200215f016698e274cb8`.
The server JAR SHA matches local pinned Jena 5.6.0 exactly:
`d28c1eaf703122ee628895a460c20fa4aa60a892f435d403ea8c036f241da1f8`.
Direct-access replay 3859447 keeps compt311, eight CPUs / 24 GiB allocation,
query/heap/RSS budgets and original 567-key request. It started by backfill after
an initially late scheduler estimate; no job was canceled, resubmitted or moved.

## Configuration wiring defect, not a successful direct-mode trial

3859447 still timed out; final query sample 51.319 s / 8 witnesses / 121 index
items, 2,530,865,152 storage bytes and 622 major faults. The diagnostic's
`file_mode=direct` reports **SystemTDB only**, not the effective DBOE access mode.
Do not interpret the field or historical CLI `--set=tdb2:fileMode=direct` as
proof that the underlying B+trees used direct access.

Pinned source/bytecode identifies a real wiring issue: TDB2's BPlusTreeFactory
calls BlockMgrFactory without a FileMode; that factory consults **SystemIndex**,
whose 64-bit default is mapped. SystemTDB's separate setting does not set it.
`XgapStorageMode` now asserts BOTH settings before opening the store or starting
Fuseki. The diagnostic additionally records actual block-manager descriptions.
Tiny TDB validation produces the identical witness; all nine triple/quad index
managers now explicitly show `BlockMgrCache ... BlockMgrFileAccess[8192 bytes]:Direct`.

`RdfTdbSession(file_mode='direct')` uses the same pinned bootstrap for every
owned RDF source, with compilation and hashes in offline setup. Default sessions
remain default until real-source validation; this repairs an opt-in option, not
an unvalidated blanket change. All methods sharing a source session receive the
same storage configuration. No query/compiler rewrite or vendor Jena patch.

The bootstrap also passed an actual local Fuseki HTTP check on the existing tiny
TDB graph: service started, log attests `TDB=direct DBOE=direct`, and one captured
constant-key SELECT returned the same normalized witness as the unmodified
reference. Owned service was terminated/reaped after that check. This is a
transport/configuration correctness check, not a full-source performance result.
Fixed-node, unchanged-query DBOE-corrected replay is job 3859504. Source code is
`81745b8`; its small standalone archive SHA-256 is
`aeb2dda162ae470dfbebea7ff35a98411966edf0cc9a9890500ea575f3119e8e`.

The backend admission command now accepts an explicit `--case-id` for failure
replay without editing or replacing the frozen bundle. Original case indices and
bundle hashes remain; receipts distinguish `single_case_replay` and set
`full_bundle_admitted=false` even when that one case passes. Missing/duplicate
case identities fail before serving. Its focused identity-selection test passes.
This permits the next pipeline check to target the original fifth case instead
of re-running the four already passing cases first.

Pause handoff: 3859504 remained PENDING/Priority at the last evening check;
its scheduler estimate was 2026-09-23 17:24:31 EDT (2026-09-24 05:24:31 Beijing),
not an assured start. The user requested a pause after this milestone until
September 24 10:00 Beijing. Code/tiny validation is complete, but full-source
repair acceptance is not. Preserve this one bounded job to execute unattended;
no further whole-bundle gate or repeated polling. See the
[evidence and resume checklist](../report/ch6_storage_fix_pause_20260923.md).

## September 24: actual Direct result and next bounded repair

User resumed at 10:00 Beijing. 3859504 completed its diagnostic wrapper, but the
query hit the 60 s guard (60.222 s including cleanup); sampled peak RSS 200,413,184
bytes. Effective SystemIndex and all index block managers confirm Direct. The
last query sample at 48.997 s has 29 witnesses, 436 index tuple yields, 14,827,520
storage read bytes, 0 major / 26,462 minor faults. POS: 30 finds, 87 tuples,
44.215 s completed index API time. Of 49 query samples, 48 show pread0 at stack
top and 47 have an uninterruptible thread; wchan was hidden as `0`. These are
sample observations, not a quantified wait duration. Source private copy and
owned process cleanup completed. This is not full D2 admission or a paired
speedup. Archive SHA-256 (both 3859447 and 3859504):
`cd198876a328588b177a02a7d156e9ae84b8e7c8cd8936c7a4c00a726abfa6c3`.

The remaining stack again includes BPTreeNode.iterator. Its eager child-page
materialization happens before LIMIT can stop iteration. An **offline-only**
overlay of the pinned Jena range iterator now snapshots child IDs and reads pages
on demand, preserving comparator, range boundaries, order and caller transaction.
It does not change the query, source population, planner, estimator or engine JAR.
The original class digest is checked before compilation; runtime evidence names
the actual overlay location. This is an experimental Jena modification, not an
upstream release or XGAP planning claim. Formal deployment has not adopted it.

Focused local checks: upstream source compiles to identical resolved instructions
as the pinned JAR class; original and modified versions both pass 108 ranges
against an independent integer oracle, deletion/exhaustion, a real TDB reader
across concurrent commit, rollback and reopen. Logical record-page gets before
the first record fall from 14 to 2 (includes cache hits, not disk-page counts).
The existing captured-query tiny fixture returns the identical witness.

Next admission is **one unchanged 567-key failed source request**, once, on a
verified full-store copy, Direct plus the named overlay, compt311 with the same
60 s / 4 GiB / 768 MiB heap and 20-minute allocation. No full pilot, query rewrite,
extra warmup, full graph preprocessing, alternative-plan selection or LLM call.
Only after successful result/guard/identity verification can the original fifth
pipeline case be considered. A later common-backend adoption must pin and disclose
this modified engine equally; no silent baseline substitution or output tuning.

### Mapped tuple path coverage correction

3864057 completed its wrapper but the query timed out: final sample 53.501 s,
30 witnesses, 15,175,680 storage bytes, 0 major faults. Cleanup completed. The
ordinary range class was loaded, but the sampled stack still called the eager
BPTreeNode.iterator. Pinned bytecode identifies the second path:
TupleIndexRecord uses BPlusTree.iterator(..., RecordMapper), which invokes the
separate BPTreeRangeIteratorMapper. The first overlay did not cover it; loading
an overlay class was insufficient runtime attestation. No improvement is claimed.

The v2 overlay covers both paths with the same lazy-page helper and adds a mapped
invocation counter. Original mapped source compiled instructions match the pinned
JAR. Both original and patched builds pass 108 integer-oracle ranges on EACH path
and real TDB MVCC/rollback/reopen; first-record logical record-page gets are
14/14 versus 2/2. The toy query returns the identical witness with three measured
mapped invocations. Intermediate test-harness failures (mapper key-scratch
contract) remain in local logs; corrected tests pass against both builds.
Next is one same-query, same-budget v2 diagnosis; no full pilot or production
overlay adoption. The first failed overlay remains sealed separately.

3864137 (code `070e521`, same compt311) still hits the 60 s process guard, with
cleanup complete and sampled peak RSS 212,021,248 bytes. Last query sample at
49.868 s: 491 witnesses, 24,002,560 storage bytes, 0 major faults, 2,456 actual
mapped-iterator invocations. POS completed API time 37.304 s; SPO fully bound
11.220 s. The active stack now reaches internalSearch through the modified
mapped path, not eager BPTreeNode.iterator. This establishes path coverage and
more completed work in this diagnostic, not a completed answer or paper speedup.

The parent 60 s diagnostic guard includes JVM/dataset startup; it allowed only
about 50 s in the query phase. Real serving already separates offline startup
from the unchanged 60 s HTTP request contract. Therefore the next useful check
is the original fifth **single-case pipeline**, not another instrumented replay
with an arbitrarily larger query allowance. It keeps the frozen 120 s worker,
60 s request, 4 GiB source RSS, same node and original bundle/reference. No prior
successful cases are rerun. This supersedes the earlier requirement for a fully
completed standalone diagnostic before considering the pipeline; the measured
timing-scope difference is the reason. A failure remains a failure.

The service now has an explicit opt-in pinned overlay, disabled by default.
The admission CLI only permits it for an explicitly named Direct RDF single case;
it cannot label a full bundle admitted. All sources in that session receive the
same engine overlay, with source/class/original digests in receipts and actual
mapped invocation counts in shutdown logs. Formal campaign defaults remain
upstream. Actual tiny Fuseki HTTP returns the identical witness and records three
mapped invocations; five focused copy/selection checks pass. No LLM calls.

### Original fifth pipeline case accepted; remaining suffix only

3864165, exact `f6ec1a0`, completed on compt311 in 7m06s. The unchanged original
fifth query passed with EM=1 (20 final rows), one final plan and no retries/LLM.
All five HTTP requests completed: 17.282, .832, 1.118, 38.872, .063 seconds.
The 38.872-second request has the exact original query SHA
`26eb1410c89dac31234d77401afccc6e7cc47bc259a91aa651088abbd133ebb2`
and returns all 567 witnesses. Worker execution is 57.671 s; parent guard is
61.119 s. Fresh-session copying/verification/startup is 344.856 s offline,
with no warmup request. Do not combine these timing scopes or call this an NL run.

Observed source peak RSS: 768,208,896 B; method: 46,071,808 B. Graph-source
first-to-last sampled storage reads: 55,820,288 B and zero major faults; these
are whole-case source deltas, not directly comparable to the earlier one-query
diagnostics. Actual mapped invocations: 143,115; both overlay locations and
SystemIndex/SystemTDB Direct are attested. Cleanup completed. OS lsblk reports
the local backing disk ROTA=1; this is deployment evidence, not a hardware model.
The upstream JAR and source population remain unchanged; the overlay is disclosed.
Uncontrolled cache/order and the changed measurement scope preclude a paper
speedup ratio. Full-bundle admission and formal campaign remain false.

Archive `xgap-d2-single-lazy-3864165.tar.gz` (94,767 B) downloaded and SHA verified:
`7a2ab879b333afef3a34df08d560c00cf85e642352c20c49ed4286f38ccb6385`.
All five compressed response hashes were independently verified after download.
The next useful boundary is original frozen cases 6–8, not replaying cases 1–5.
An explicit `--case-ids` selection permits at most eight distinct IDs, validates
all IDs before serving, retains original bundle order/index and uses one shared
session. It stops on the first failure and always records `diagnostic_subset`
with `full_bundle_admitted=false`, even if every bundle ID is supplied.
No edited/substitute bundle, larger online budget or alternative-plan trial.
Four focused selector/release-boundary tests pass; formal overlay adoption remains
a separate pinned common-backend decision after necessary admission evidence.

### Remaining-case job and formal integration boundary

The user executed the SHA-checked one-time deployment script; job **3865081** is
the unique cases-6–8 diagnosis at exact `9d40ade`. Slurm was observed RUNNING on
compt311 (00:32 elapsed). The script validates the original successful receipt,
source bundle, prepared store, original Slurm template and package, refusing any
existing new deployment/submission target. Output:
`formal-rdf-remaining-lazy-v1/D2/rdf`; journal: `remaining-lazy-v1-submission/`.
Do not resubmit or treat RUNNING as answer evidence.

Subsequently the user returned sacct COMPLETED/0:0, elapsed 6m09s on compt311,
and the wrapper's `success=true, attempted=3, audited=3, error=null`. In pinned
`9d40ade` this entails EM=1 for each selected case and verified service closure;
there was no retry. Per-case resource receipts are still being collected. This
completes the previously blocked suffix diagnosis, not full-bundle/formal release.

A read-only audit while it runs identifies an explicit next boundary:
`run_bounded_joint_batch.validate` currently accepts only the optional
`design.source_storage` deployment field; `_run` constructs `RdfTdbSession`
without Direct/lazy arguments. Thus the formal five-method runner still uses
upstream defaults, irrespective of successful diagnostic receipts. The external
ARUQULA→FedX session already receives that same shared source session, so the
eventual fix belongs at the common session factory, never in a method-specific
worker. No promotion or formal execution has happened in this audit.

After the pending diagnosis, a promotion must freeze an explicit runtime identity
and its engine/overlay pins in the manifest, reject native/RDF mismatches, carry
the identity into admission and release checks, and keep it identical for all
five methods in each comparison. Modified-engine verification is a deployment
gate, not baseline algorithm tuning. Existing upstream receipts stay historical;
do not merge different engine configurations into a paired speedup or use a
successful diagnostic subset as complete admission. Offline F6 costs may only be
reused if their execution deployment/runtime is the same as the measured pool.
