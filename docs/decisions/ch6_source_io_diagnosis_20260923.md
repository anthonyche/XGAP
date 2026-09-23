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
