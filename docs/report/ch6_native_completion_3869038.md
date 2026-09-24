# D2 native 24-case coverage and RDF continuation — 3869038

2026-09-25. All 24 frozen native cases now have a locally verified successful
record across preserved code versions. This completes cumulative native coverage;
it does not certify all 24 on the final code, or start the formal five-method study.

## Last-five raw evidence

3869038 completed with exit 0 in 96 s on compt311. Source code is
`c3437fc309ef54f35d51288a9c284abbe2323127`. Job wall includes serving setup;
it is not query latency. All five answers match the frozen reference in content
and order; each has one final-plan execution, zero LLM calls, and the same plan
hash as its pre-source-startup symbolic selection. Closure, observer shutdown,
owned-group drain and serving-copy reclamation all pass.

| Original index | Case (D2-test-active-anchor prefix omitted) | Rows | Execution ms | Worker wall ms | Planning ms | Backend calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 19 | cycle-000-W1 | 0 | 6297.65 | 9754.70 | 134.64 | 1 |
| 20 | cycle-000-W3 | 0 | 2877.59 | 6071.37 | 236.93 | 3 |
| 21 | witnessed_count-000-W3 | 0 | 922.05 | 3973.38 | 217.39 | 4 |
| 22 | witnessed_sum-000-W1 | 0 | 531.67 | 3157.13 | 139.38 | 3 |
| 23 | ranked_count-000-W4 | 20 | 1412.20 | 4411.43 | 219.74 | 6 |

Four answers are empty; ranked_count/W4 returns 20 rows in 1412.20 ms.
These are backend correctness/admission results, not natural-language quality,
mode comparisons or repeated-run performance estimates. The references are not
resampled after observing empty answers. Sampled method/source RSS peaks are
41,365,504 / 1,177,223,168 bytes, below the unchanged 3/4-GiB limits.
Sampling can miss brief peaks; no scan rows or I/O-wait duration are inferred.

Archive `xgap-native-last5-closed-3869038.tar.gz`: 160,649 bytes, SHA-256
`7744db3c39e99e0337167b6abe7a1feae4fee3d3e0621486449d9796aad335d3`.
Native receipt SHA-256:
`156e3bdb17be4729d6e8e92e61c19af3f2dd7cb87af572104ee02c3245c06f64`.
Verified 56 available artifact pins, all 25 relocated case input copies against
frozen contracts and 17 raw compressed/decoded HTTP responses. Unavailable
external pins remain separately listed in the audit, not marked as verified.

Local artifacts under `/Users/anthonyche/xgap-data/ch6-release-boundary-20260924`:
- `last5-closed-audit-3869038.json` and `last5-closed-3869038/`.
- `native-cumulative-admission-through-3869038.json` (all 24 successful entries).

## Remaining launch boundary

| Gate | Evidence now | Next action |
| --- | --- | --- |
| D2 native fixed 24 | 24/24 cumulative; 14 use c3437fc, 10 earlier code | Compare all current symbolic plans with successful plans and list code differences; no native execution in next job |
| D2 RDF fixed 32 | Original index 0 passed in 3865863; index 1 repaired and passed in 3865967 | Continue original indices 2–9, then the unattempted suffix; pilot receipts do not replace test receipts |
| F6 raw measurements | Twelve measured trials audited with frozen answers/costs and node-local runtime | Bind actual audit to matching D1 deployment/unit; do not relabel historical measurements to new execution identities |
| Formal release | Full release audit has not passed | Reconcile real factor inputs, mixed-method supported subsets and fixed API/token/wall budgets; no fabricated missing cells |

The next static comparison is evidence for deciding any necessary targeted
revalidation. Equal plan hashes alone do not certify changed executor code;
unequal hashes do not themselves establish an incorrect answer. No blanket
24-case native rerun is dispatched. No speedup or full-system-ready claim is made.

## Frozen next package

`/Users/anthonyche/Downloads/xgaprdf8-c3437fc-v1.zip`, 7,954 bytes, SHA-256:
`6a99423f026132a81e644d441d12bb7bb38df35468e9c874215d08299159afb9`.
Reuses the existing clean c3437fc checkout. No new production implementation,
model fitting or policy tuning. Native v3 and RDF's existing frozen profile are
kept distinct; no silent estimator replacement. The RDF original bundle hash is
`3952b90945dbed4c8fd345c8b8dd0370813229537b4dc31f7f01f5ccd10b5a4d`.
All selection is frozen by its original indices 2–9, independently of results.

Before submission, verify the latest native archive, successful records for all
24 native cases, successful RDF prefix, prepared profile/runtime identities and
all native/RDF case-file pins. Within a CPU job, run symbolic planning only for
native 24 and RDF 32; seal selected plan hashes before starting sources. Execute
only RDF 2–9 with Direct/lazy pinned runtime, one final plan per query, first
failure stops, zero LLM and no retries. Preserve full inputs, raw observations,
closure and static comparisons in a new archive. Original query/source/worker
budgets remain 60 s / 4 GiB / 120 s and 3 GiB. Allocation: 8 CPU, 24 GiB, 1 h,
compt311; no GPU. Existing journal or output blocks duplicate submission.

Local validation passed 24 actual native successful records and 65 real JSON
pins, prior archive, RDF prefix and prepared/profile/runtime documents, package
member hashes, Python 3.6 staging and shell syntax, and scope/order/pin mutations.
The actual RDF bundle and its estimator file remain server-only. Local structural
guard checks explicitly use fixtures for those two unavailable objects only;
no fixture is shipped in the ZIP or used as experiment input. Mandatory server
hash validation covers both real files before submission. Raw case files are
also mandatory server checks. Local package validation is not backend admission.

Journal: `/home/hxc859/xgap-ch6-artifacts/reconcile-rdf8-c3437fc-v1`.
Output: `/home/hxc859/xgap-ch6-artifacts/formal-reconcile-rdf8-v1/D2`.
Log: `reconcile-rdf8-<job>.out`; archive:
`/home/hxc859/xgap-reconcile-rdf8-<job>.tar.gz`.
Validation: `reconcile-rdf8-pack-c3437fc-v1/verification.json` in the local
artifact root. The user validated the package and submitted **3869407**.
The user reports FAILED/2:0, 444 s, compt311. RDF attempted=audited=3;
the first failure is `D2-test-uniform-cycle-000-W2` (original index 4).
Original indices 5–9 were not executed. The first two cases passed according
to the stop-on-first-failure flow; their raw evidence remains unverified locally.
The failure category and native plan comparison remain unknown until archive
inspection. Do not infer timeout, memory exhaustion or incorrect answers from
the job exit code. Archive: 667,528 bytes, SHA-256
`8915a464ae4a40df47e58adf7885d430a04607c8b8c4b80f047121ac9c573d2a`.
A null outer archive error is not evidence that the inner admission succeeded.
Log: `reconcile-rdf8-3869407.out`; expected archive:
`/home/hxc859/xgap-reconcile-rdf8-3869407.tar.gz`. Preserve the existing job,
checkout and outputs; do not resubmit. The full formal campaign remains closed.
