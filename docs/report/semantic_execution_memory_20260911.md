# T3-B: observation memory through the common question entry

2026-09-11, base8db41fa. Accepted development evidence: focused/native passed; broad90283 exited0.
Scope frozen in [semantic execution memory v1](../decisions/semantic_execution_memory_v1.md).
The latest user standard is a research prototype serving paper experiments,
not a perfect general product. This step supports a same-entry no-memory contrast.

## Behavior

The normal question/binding/planning/execution chain now accepts optional
SemanticPlanMemory backed by the existing InMemoryStore or JsonlMemoryStore.
An exact context contains semantic meaning, admitted plans, registered native
observations, cost constants, declared source/bundle versions and a caller-owned
environment episode. Reuse has a finite maximum age. Missing/expired/changed
contexts collect observations; invalid persisted state stops with an error.

A complete successful observation collection is persisted with its actual
acquisition calls, time and originating goal. A hit selects from those estimates
and still executes backend queries; it never returns a cached answer. Historical
acquisition remains attached to the trace and is not billed again as fresh work.
Memory lookup/write time is included in planning and end-to-end time. Constructing
the caller-supplied memory store is setup; the native reload harness records that
time separately. Disk failure retains already consumed calls and stops without retry.

The existing no-memory and static placement modes remain available. Their
candidate/compiler/execution code is shared. Explicit snapshot, static policy
and automatic memory inputs cannot silently override one another. Failed or
partial observation collections are not published as complete entries; a warm
execution failure never triggers another plan or observation acquisition.

## Evidence

First local test command named a nonexistent legacy test file and exited4 before
running any tests. Corrected focused96791 passed112 in5.53s. Final focused10840
passed148 in7.50s, including the existing adaptive runtime. All five question
cases preserve independently authored gold under cold, warm and no-memory modes.
Tests cover persistence reload, context changes, expiry, incompatible inputs,
invalid memory, observation/execution failure and persistence failure accounting.

Native8381 exited0 using real owned Neo4j/Fuseki services and the unchanged tiny
graph. Five cold and five warm programs,18 candidate answers,10 independent
native targets and the retained split-data slice all pass. Every warm run reads
a fresh JSONL store instance and selects the same plan as its corresponding
cold run. All37 native source hashes match; both services stopped normally.

| Query | Cold observations | Cold execution | Warm observations | Warm execution |
|---|---:|---:|---:|---:|
| B01 | 4 | 2 | 0 | 2 |
| B02 | 4 | 2 | 0 | 2 |
| B03 | 4 | 2 | 0 | 2 |
| B04 | 2 | 1 | 0 | 1 |
| B05 | 4 | 2 | 0 | 2 |
| Total | 18 | 9 | 0 | 9 |

The harness separately used25 candidate-validation calls,10 independent native
reference calls and2 retained-slice calls: **73 test-query calls** overall,
excluding service/data setup. The18 historical observation calls attached to
the warm traces are those already charged to the cold runs, not18 new calls.

Final broad90283 exited0:3481 passed/38 skipped in691.20s and24 harness/example
entrypoints passed. No source/test changes after launch; all39 recorded source/test
hashes still match. The run finished before the latest research-directed testing
policy was applied; it was not repeated. Log: `/tmp/xgap-t3b-memory-acceptance.log`. Machine-readable evidence:
`experiments/artifacts/semantic_execution_memory_20260911.json` and
`/Users/anthonyche/xgap-data/t3b-memory-native-20260911/result.json`.

## Limits and next experimental gate

This verifies exact-context observation reuse, not family transfer, learned
prediction or within-query adaptive replanning. Cold-then-warm order and extra
candidate executions affect backend caches; no latency improvement is claimed.
Staleness within the caller's environment episode is possible. Existing frozen
paper protocols, task populations and full-agent ablations remain unchanged.

Reproduce with the existing native harness flags
`--agentic-semantic --memory-roundtrip`; controlled requests can be replaced by
the existing recorded-response option without new model calls. GPU producer
bc2bb67 and queued five-question job3804011 stay unchanged. Its last observed
state was PENDING/Priority, estimated18:28:27 Beijing; this was not re-polled.
Real model responses and new real-data comparisons remain the next evidence.
No big dataset, catalog rebuild, UI or general streaming framework was added.
