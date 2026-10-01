# Native full-data store preparation — 2026-09-13

The frozen FinBench SF0.1 native inputs are now loaded into Neo4j and the control
TDB2 store. One-time preparation took **33.805 seconds**, including input/engine
pinning, loading, two integrity reads, graceful shutdown and store hashing.
No benchmark question, model call, catalog build, estimator fit or baseline run
occurred. This completes data loading; native serving-copy and campaign wiring
remain separate engineering work.

| Evidence | Tiny boundary | Full SF0.1 |
| --- | ---: | ---: |
| Original load batches executed once | 13 | 194 |
| Nodes, equal to input row totals | 8 | 55,604 |
| Relationships, equal to input row totals | 16 | 309,577 |
| Offline count queries | 2 | 2 |
| Total offline preparation | 19.524 s | 33.805 s |

Full Neo4j worker+server: 29.513s, sampled peak group RSS 940.641MiB; control
TDB2 loader: 2.739s, 937.172MiB. These are sequential loads under 900s/3GiB
per-load guards, with a sampled 10GiB output budget and 6GiB free-space reserve.
The generic guard's legacy “hosted engines excluded” label does not describe
this worker: its recorded owned group contains the worker and both Neo4j Java
processes. All three identities are present in the guard evidence. No remote
engine is involved.

Neo4j logged normal `Stopped.` after requested SIGTERM; no forced kill was
needed. The outer worker and both source-loading process groups reached terminal
state, with no live descendants. Node/relationship count equality detects lost
load rows; it is not a proof of all properties or query semantics.

The frozen Neo4j data/transaction store has 87 files, 441,378,366 bytes. Control
TDB2 has 43 files, 236,139,733 bytes. The original native control file is used;
the separate same-facts-RDF metadata revision was not silently substituted.
All native engine files and both source checksums remained unchanged. The
59,587-entry catalog and frozen 32-observation estimator were reused unchanged.

The new loader preserves batch order/statements and stops on the first failure.
Three focused tests passed in 0.28s: modified input, first transaction failure,
and missing relationships. The tiny live gate tested only the new load/close/
freeze boundary; accepted NL/query/compiler gates were not repeated. Both real
preparations succeeded on their first attempt. See the
[predeclared scope](../decisions/native_store_preparation_v1.md) and
[hash-pinned artifacts](../../experiments/artifacts/native_store_preparation_20260913.json).

The result supports treating load/index work as a frozen one-time cost, separate
from per-query latency and amortizable across requests. It does not demonstrate
a planner speedup or native overall answer quality. Next: start owned serving
copies through the common observer/runner, then run the approved native track.
RDF fixed evaluation resumes at group index 5 and NL at group index 1; previous
intents, failures, answers and the 120-question population remain unchanged.
