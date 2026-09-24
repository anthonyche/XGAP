# D2 native next-eight admission — 3868951

2026-09-25. Complete MovieLens20M; frozen original indices 11–18. This is
complete-query backend admission, not NL interpretation or a five-method result.

## Verified evidence

Job completed with exit 0 in 87 s on compt311. That includes offline serving
setup and is not query latency. Code: `c3437fc309ef54f35d51288a9c284abbe2323127`.
All eight returned answers equal their frozen references, including row order.
Each case executed one final plan with zero LLM calls. All executed plan hashes
match the zero-call planning seal made before source startup. Resources closed,
owned groups drained and reconstructed serving copies reclaimed.

| Original index | Case (D2-test prefix omitted) | Rows | Execution ms | Worker wall ms | Planning ms | Backend calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 11 | uniform-witnessed_sum-000-W4 | 0 | 3928.85 | 6389.44 | 214.38 | 2 |
| 12 | active-anchor-window_edge-000-W2 | 0 | 2268.72 | 4324.11 | 68.49 | 3 |
| 13 | active-anchor-window_edge-000-W3 | 0 | 1326.65 | 3461.50 | 101.91 | 4 |
| 14 | active-anchor-window_edge-000-W4 | 0 | 489.66 | 2665.88 | 100.13 | 2 |
| 15 | active-anchor-zigzag-000-W1 | 20 | 3054.76 | 5469.21 | 169.66 | 1 |
| 16 | active-anchor-zigzag-000-W2 | 0 | 122.96 | 2553.22 | 104.13 | 1 |
| 17 | active-anchor-zigzag-000-W4 | 0 | 468.66 | 2660.85 | 167.26 | 2 |
| 18 | active-anchor-ordered_star-000-W2 | 0 | 690.87 | 3195.14 | 104.24 | 5 |

Seven references are empty. The nonempty active-anchor zigzag/W1 result has
20 rows and took 3054.76 ms to execute. These observations establish admission
for these cases, not a general complex-query speedup or answer-quality result.
Active-anchor eligibility alone does not imply a nonempty complete-query answer;
no cases are replaced after observing results.

Sampled peak method/source RSS across the eight cases: 41,922,560 /
1,337,274,368 bytes. All observed samples remain below the unchanged 3/4-GiB
caps. Sampling can miss brief peaks; faults and process I/O are not scanned-row
counts or I/O-wait time. No measured scan reduction is inferred.

Archive: `xgap-native-next8-closed-3868951.tar.gz`, 223,355 bytes; SHA-256:
`4e2e37f1099c91ba303af1cff5426b245157cb8f32be10673fb3dee4e79fe0d0`.
Native receipt SHA-256:
`a98282d54d31820dfd731e02d516c840742219ec499c72894101a2ab529b6d8d`.
Verified: 80 available artifact pins, 20 compressed/decoded raw responses,
and all 40 relocated case-input copies against their frozen contract pins.
Other external pins absent from this archive remain explicitly unverified locally.

Artifacts beneath `/Users/anthonyche/xgap-data/ch6-release-boundary-20260924`:
- `next8-closed-audit-3868951.json`
- `next8-closed-input-pins-3868951.json`
- `next8-closed-3868951/` (raw extracted evidence)
- `native-cumulative-admission-through-3868951.json`

## Last five handoff

Cumulative native admission is 19/24 across preserved code versions, not one
whole-cohort admission on c3437fc. Original indices 19–23 remain unattempted:
active-anchor cycle/W1, cycle/W3, witnessed_count/W3, witnessed_sum/W1,
ranked_count/W4. They retain original order and stop on first failure.

Prepared ZIP: `/Users/anthonyche/Downloads/xgaplast5-c3437fc-v1.zip`, 7,845 bytes;
SHA-256 `2b9cc621f7270575d8b68cf82a7ba93b53a61d3f38adbba2ffa93947f06f6576`.
The package reuses the deployed clean c3437fc checkout, unchanged v3 estimator,
source snapshot and budgets. No production code or estimator change is included.
Local verification covers the previous successful archive and receipts, five
frozen case contracts, embedded ZIP member hashes, Python 3.6 staging syntax,
shell syntax, and rejection of altered order/estimator/case pins/snapshot.
The input checker was tested on preserved cases 11/12; raw files for 19–23
are server-only and MUST pass staging hash checks before submission.

Inside the job, zero-call planning seals all five selected plans before source
startup; full-edge reads are rejected at that gate. Actual execution plan hashes
are compared to the seal. Source/worker/request limits remain 4 GiB / 3 GiB / 60 s,
worker wall limit 120 s; one final execution per case, no automatic retry.
CPU allocation: 8 cores, 24 GiB, 1 h, compt311. No GPU or LLM request.
Existing journal/output blocks duplicate submission. The prior successful
archive and closure are required; no old evidence is overwritten.

Server journal: `/home/hxc859/xgap-ch6-artifacts/native-last5-c3437fc-v1`.
Output: `/home/hxc859/xgap-ch6-artifacts/formal-native-last5-closed-v1/D2`.
Log: `native-last5-closed-<job>.out` in that journal.
Archive: `/home/hxc859/xgap-native-last5-closed-<job>.tar.gz`.
Package validation: `native-last5-closed-pack-c3437fc-v1/verification.json`
beneath the local artifact root. The user validated and submitted the package
as **3869038**. Submission is confirmed; running/terminal state is not yet known.
Log: `native-last5-closed-3869038.out`; expected archive:
`/home/hxc859/xgap-native-last5-closed-3869038.tar.gz`. Do not resubmit or
change the checkout. Read the existing job and its result before further work.

Full formal launch remains closed. Native version-impact reconciliation, remaining
RDF admission and the release-factor/support/budget/F6 binding gates remain;
passing the last five alone does not authorize the full campaign. The v3
estimator's ordering proxy remains an estimate rather than a resource guarantee.
