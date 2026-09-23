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
