# D2 remaining-six admission: verified failure and isolated diagnosis

2026-09-25 Beijing. This is backend admission, not a formal five-method result.
Production source stays `5f9402384308ecf2a98a0a3baf40d92271439487`.

## Verified 3868824 evidence

Job 3868824: FAILED/2:0, 146 seconds, compt311. Four cases were attempted and
audited, stopping at the first failure. The downloaded archive is 179,113 bytes:
`012935574200aa8605709d2842e8bc5a71184c579bdddc1baa4606d864e8230d` (SHA-256).
Its receipts, pinned plans/answers, all 14 captured HTTP records and compressed
and decoded response hashes were checked locally. Three ordered answers equal
the frozen references; **all three are empty**.

| Original index / case | Answer EM | Returned / reference rows | Execution ms | Worker wall ms | Backend calls |
| --- | --- | --- | --- | --- | --- |
| 7 ordered_star/W2, uniform | 1 | 0 / 0 | 3269.14 | 6067.24 | 5 |
| 8 cycle/W1, uniform | 1 | 0 / 0 | 2280.93 | 4849.40 | 1 |
| 9 cycle/W3, uniform | 1 | 0 / 0 | 656.49 | 3124.42 | 3 |
| 10 cycle/W4, uniform | null (execution failed) | no answer / 20 | 60987.92 | 63450.89 | 5 |

One final-plan execution and zero model calls per attempted case. Selected plan
hashes match the frozen zero-call choices. Empty successes do not establish a
nonempty high-fanout memory or speed improvement. The failed worker's empty
placeholder is not an answer and must not be scored as an incorrect returned
empty result. Original indices 11 and 12 in this batch remain unattempted; the
whole native cohort has 24 cases, including later indices 13–23. Full native
and RDF admission remain incomplete.

## Failure localization

W4's first four source requests take about 0.928 seconds combined. They retrieve
one anchor, 29 anchored edges, 29 Movie identities and 29 attribute bindings.
The final query receives exactly the seven keys selected by the external boolean
predicate; the captured keys were compared with the raw Fuseki response.
The fifth request times out after 60071.58 ms, with no response body. Worker error
is `timed out` at `cq24/order`; observer category is `source_timeout`.
This is not an answer mismatch, worker guard timeout or observed RSS breach.

Sampled W4 method/source peaks are 40,759,296 / 1,262,481,408 bytes, below the
unchanged 3/4 GiB group limits. Sampled source CPU is 72.03 seconds. The main
Neo4j process has observed rchar delta 490,167,185, minor faults 228,549,
read_bytes 0 and major faults 0. These sampled counters are neither scanned-row
counts nor an I/O-wait measurement; zero deltas do not establish zero I/O wait.
The request could spend time in native compilation or execution. Closure,
process draining and owned serving-copy reclamation all completed.

Static inspection also finds a model/compiler consistency gap: emitted edge
order is m1e,m3e,m5e,m7e, whereas the source-work proxy independently uses the
greedy order m1e,m7e,m3e,m5e. The model already labels this as a proxy, not EXPLAIN
or a bound. This discrepancy is not evidence of causation or permission to fit
weights to this held-out answer/latency. Repair should align estimates with the
emitted strategy, and retain versioned old models.

## One-query diagnostic submitted as 3868871

The user uploaded and submitted `xgapcycle-explain-3868824.zip` (6072 bytes), SHA-256
`1a742c5e5c8f19654e06a7cf3c11d46e202a528fea94153918a7292fea8ad5e6`.
It reuses the exact old checkout, full source snapshot, original request and
seven captured membership keys. It permits exactly one EXPLAIN, zero answer
query executions and zero LLM calls; no automatic retries or cohort rerun.
EXPLAIN estimates will not be presented as measured scanned rows.

Server journal: `/home/hxc859/xgap-ch6-artifacts/cycle-explain-3868824-v1`.
Log: `cycle-explain-3868871.out` in that journal. Expected result archive:
`/home/hxc859/xgap-cycle-explain-3868871.tar.gz`.
The user reports COMPLETED/0:0, 70 seconds, compt311, with success=true and
zero answer query executions. Archive: 56,332 bytes, SHA-256
`74e948b2057106e9f8b793c58a97cca83156ed66a9ddbabe3998ce79925b7e9f`.
The raw archive is still awaiting local transfer and verification. Automatic
access remained unavailable; the user was asked to download this existing file. Do not resubmit or mutate this checkout while in flight.

Local verified evidence lives under
`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/remaining6-3868824`.
Audit: `remaining6-evidence-3868824.json` under that artifact root, SHA-256
`3dd864b1d31284316ce44d1bd33f76e65fa7ff1e097f3057878837f7a27e56d6`.
Next: inspect the actual physical plan, implement only a justified general
repair, validate affected semantics on tiny data, then replay the failed W4 once
under the original caps. Preserve passed cases and all failures. Full formal
experiment launch remains closed.

## EXPLAIN archive verified and general repair (2026-09-25)

The reported archive SHA, compressed/decoded response hashes and exact original
statement/parameters were verified. EXPLAIN took 4830.87 ms (worker 8183.14 ms),
returned one 150,344-byte plan response, and executed no answer query. All three
copies of closing edge m7e use `Expand(All)` followed by identity filtering,
even though both endpoint keys are available. Other key lookups use indexes;
there are also anchor User label scans. This supports a specific endpoint-access
repair, not a claim that compilation or all other work is negligible. Estimated
rows are not actual row counts. Full-source execution benefit remains unknown.

The compiler now resolves both endpoint node domains independently before a
closed-edge Match. Tiny actual Neo4j plans use `Expand(Into)` for these edges.
37 focused tests pass. Three live cases (membership/nonempty, empty, descending)
passed in `closed-edge-tiny-v1`; its fourth case had an overly restrictive test
assertion after all three execution paths had already produced equal answers.
That failure is retained. The corrected parallel-edge case narrows its toy
predicate to the intended destination, and passes separately in
`closed-edge-tiny-edge-output-v2` (8 ordered rows). It demonstrates that both
parallel closing edges survive even when only duplicate-ID physical nodes carry
them. No formal input changed; no successful tiny case was rerun.

The unchanged frozen v3 model selects the repaired W4 artifact in a zero-call
inspection (`closed-endpoints-zero-call-v1`). Next is one W4 answer replay, under
the same old budgets. See the [semantic proof and limits](../decisions/native_closed_endpoints_20260925.md).
