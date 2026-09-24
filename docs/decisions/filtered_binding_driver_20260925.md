# Preserve necessary filters before early binding

2026-09-25. Shared physical-rule correction; no dataset/case branch, estimator
replacement, SPARQL-text rewrite, budget increase or answer-based selection.

## Evidence

3869407 raw archive SHA-256
`8915a464ae4a40df47e58adf7885d430a04607c8b8c4b80f047121ac9c573d2a`
(667,528 bytes) is verified. The audit checked 353 archive members, 100 available
artifact pins, 160 relocated frozen inputs and 18 raw request records. Unavailable
external artifacts are listed separately, not counted as verified.

| RDF original index | Case | Answer | Execution ms | Worker ms |
| --- | --- | --- | ---: | ---: |
| 2 | uniform ordered_star/W3 | Correct, 0 rows | 20469.72 | 24926.45 |
| 3 | uniform ordered_star/W4 | Correct, ordered 20 rows | 3091.70 | 6230.61 |
| 4 | uniform cycle/W2 | Failed; EM null | 81043.43 | 84272.12 |

The failure is request 16 at `cq7/native`: source timeout after 60079.26 ms,
zero response bytes. Method/source sampled peaks 317284352/1247129600 bytes
are below unchanged 3/4-GiB budgets. Graph-process observed read_bytes is
148463616, minor faults 279056, major faults 0. These counters are not scan-row
counts or I/O-wait measurements. Resource closure and serving-copy reclamation pass.

The captured first bound rating read returns 29 rows. All fail the query's
existing timestamp predicate, so `cq6/filter` yields zero rows. The old early
key driver nevertheless takes 29 movie keys from `cq5/bindings` before filtering.
The next reverse-edge request does unnecessary work and times out. This explains
an avoidable request, not the physical cause of that request's slow source plan.

## Rule and correctness

`early_key_driver` still follows exclusive inner-join identity lineage to an
already restricted Match. It now retains the contiguous FILTER/PROJECT tail
above that Match, stopping before the first multi-input operator. Track key
renaming through projections and colliding right-join columns. Shared leaves,
UNION paths and unsupported lineage remain excluded; dependency-cycle checks
remain in the caller. Do not remove the original join or predicate.

Every complete witness in the original driver has a row in the retained unary
tail with the same key. Thus its key domain is still a superset of the required
domain, while a subset of the bare Match domain. Binding with it preserves the
original result; final joins still enforce multiplicity and every predicate.
An empty necessary domain needs no downstream request. This is an existing
runtime behavior, now reached by a better dependency. Nothing substitutes gold
answers or infers emptiness before executing the predicate on source rows.

Lineage enumeration is bounded by the existing exclusive semantic DAG; added
path/column scans are polynomial. The change does not enumerate physical-plan
combinations or add online probes. No runtime improvement bound is claimed.

## Validation and limits

- Four focused tests: empty/nonempty cyclic queries executed through the real
  scheduler and RDFLib source adapter against independent SQLite references;
  projection/right-collision lineage and shared-input rejection. Prior related
  binding/streaming tests also passed. This is not live Fuseki admission.
- Original RDF frozen estimator reconstructed byte-for-byte from frozen source
  statistics; SHA-256 `f5cebb9dd779900528d8f2b637350c139a92412989ebb44f82b8da359ab07755`.
  Actual unified planner selects `cq6/filter` for both `cq1/native` and
  `cq7/native`, with zero backend/model calls and no reference-row reads.
- Execute that selected plan using only successful captured responses. Exact
  text cache misses fail closed; no network fallback. Result equals frozen empty
  reference; original 6 attempted source requests become 3 cached responses.
  The timed-out reverse-edge request is absent. This is failure replay, not a
  measured source speedup or a new complete-source success.

Next: one CPU replay of original RDF index 4 on unchanged full MovieLens20M,
profile, source runtime and budgets. Seal the selected plan before source
startup and verify the worker executes that same plan. No LLM, no automatic
retry or rerun of indices 2–3. Nonempty reverse-edge cost remains unproven;
RDF indices 5–31 and final release checks remain outstanding.

Native static reconciliation from 3869407 finds changed plan hashes at indices
0,1,2,3,6,8,9; 14 plans have the same c3437fc code/hash, three share only the
plan hash with older code. Cumulative native 24/24 is retained, not relabeled
as whole-cohort final-version admission. A later version requires another
static comparison and targeted justification, not blind whole-cohort replay.

Local evidence root: `/Users/anthonyche/xgap-data/ch6-release-boundary-20260924`:
`reconcile-rdf8-audit-3869407.json`, `filtered-driver-zero-call-v1/`,
`filtered-driver-replay-v1.json`, plus immutable raw extraction.

## Frozen replay package

Code `ac97d161b2a251aad3b01df8e18cf12f66757e91` is pushed to the research branch.
`/Users/anthonyche/Downloads/xgapfilterac97d16.zip`: 40,176 bytes, SHA-256
`02e4ac48cd9a83001bf13ab3234bbb4f6d0bcde1b624d9ee2db940b16e468199`.
The package contains the exact delta from existing c3437fc and stages a separate
checkout; it rejects existing journal/output/checkout to prevent duplicate runs.
All 13 actual available input pins, prior archive, scope/budget mutation guards,
Python 3.6 stage syntax, shell syntax, Git bundle and ZIP members were validated.
The frozen selected-plan hash and both filtered-driver dependencies are checked
before any source startup. The final worker plan must match that seal.

One CPU allocation (8 CPU, 24 GiB, 1 h, compt311); original RDF index 4 only,
zero model calls, no EXPLAIN or retry. Archive includes the exact frozen estimator
and profile copies as well as case inputs, raw responses and resource closure.
Journal: `/home/hxc859/xgap-ch6-artifacts/rdf-filtered-ac97d16`.
Output: `/home/hxc859/xgap-ch6-artifacts/formal-rdf-filtered-driver-v1/D2`.
Log `rdf-filtered-<job>.out`, archive `/home/hxc859/xgap-rdf-filtered-<job>.tar.gz`.
The user verified the ZIP, staged the exact ac97d16 checkout and submitted
**3869818**. Only submission is confirmed; queue/start/terminal state and result
are not yet known. Do not resubmit or alter this checkout. Read the existing log
`rdf-filtered-3869818.out`; expected archive
`/home/hxc859/xgap-rdf-filtered-3869818.tar.gz`. Remote file/terminal control has
been unavailable, so status/evidence handoff currently requires the user.
